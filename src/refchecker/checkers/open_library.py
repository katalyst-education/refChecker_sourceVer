"""Open Library metadata checker for book references."""

import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from refchecker.config.settings import get_config
from refchecker.utils.error_utils import create_author_error, format_year_mismatch
from refchecker.utils.text_utils import clean_title_for_search, compare_authors, find_best_match

logger = logging.getLogger(__name__)
SIMILARITY_THRESHOLD = get_config()["text_processing"]["similarity_threshold"]


def _result_summary(results: List[Dict[str, Any]], max_results: int = 5) -> List[Dict[str, Any]]:
    """Return the useful, compact part of an Open Library search response."""
    return [
        {
            "key": result.get("key"),
            "title": result.get("title"),
            "subtitle": result.get("subtitle"),
            "authors": result.get("author_name") or [],
            "year": result.get("first_publish_year"),
        }
        for result in results[:max_results]
    ]


class OpenLibraryReferenceChecker:
    """Verify book citations against Open Library's low-volume Search API."""

    _rate_lock = threading.Lock()
    _next_request_at = 0.0

    def __init__(self, email: Optional[str] = None) -> None:
        self.base_url = "https://openlibrary.org"
        self.email = (email or os.environ.get("REFCHECKER_CONTACT_EMAIL") or "").strip()
        self.headers = {"Accept": "application/json"}
        if self.email:
            # Open Library grants identified clients its documented 3 req/s limit.
            self.headers["User-Agent"] = f"RefChecker/1.0 (contact: {self.email})"
            self.request_delay = 1 / 3
        else:
            self.headers["User-Agent"] = "RefChecker/1.0"
            self.request_delay = 1.0
        try:
            configured_delay = float(os.environ.get("REFCHECKER_OPEN_LIBRARY_RATE_LIMIT_DELAY", ""))
            # Never exceed Open Library's documented public ceiling.
            self.request_delay = max(self.request_delay, configured_delay)
        except ValueError:
            pass
        self.max_retries = 3

    def _wait_for_slot(self) -> None:
        """Apply the rate limit across all threads and checker instances."""
        checker_type = type(self)
        with checker_type._rate_lock:
            now = time.monotonic()
            wait = max(0.0, checker_type._next_request_at - now)
            checker_type._next_request_at = max(now, checker_type._next_request_at) + self.request_delay
        if wait:
            time.sleep(wait)

    def search_books(self, title: str, authors: Optional[List[str]] = None,
                     isbn: Optional[str] = None, limit: int = 5) -> List[Dict[str, Any]]:
        from refchecker.utils.cache_utils import cache_api_response, cached_api_response

        # v3 uses Open Library's general ``q`` search for books and requests
        # subtitles. Its
        # field-specific title+author filters can be too restrictive for
        # catalogued editions with incomplete author metadata.
        cache_key = f"v3|{title}|{authors or []}|{isbn or ''}|{limit}"
        hit = cached_api_response(getattr(self, "cache_dir", None), "open_library", "search_books", cache_key)
        # An empty result is not a useful long-lived cache entry: book
        # catalogues change, and a transient API/indexing issue can otherwise
        # make a reference permanently appear unverified on later checks.
        if hit:
            logger.info(
                "[OPEN_LIBRARY_TRACE] stage=search_result cache_hit=True params=%r "
                "result_count=%d candidates=%r",
                {"title": title, "author": (authors or [None])[0], "isbn": isbn, "limit": limit},
                len(hit), _result_summary(hit),
            )
            return hit
        if hit == []:
            logger.info(
                "[OPEN_LIBRARY_TRACE] stage=cache_bypass reason=empty_cached_result "
                "params=%r",
                {"title": title, "author": (authors or [None])[0], "isbn": isbn, "limit": limit},
            )
        params: Dict[str, Any] = {
            "fields": "key,title,subtitle,author_name,first_publish_year,publish_year,isbn,edition_key,edition_count",
            "limit": min(max(limit, 1), 20),
        }
        if isbn:
            params["isbn"] = isbn
        else:
            # Do not make Open Library's author field a hard filter.  We
            # compare its returned author data below, after candidates are
            # found, which preserves verification accuracy without losing
            # valid records whose author field is incomplete or formatted
            # differently.
            params["q"] = title
        for attempt in range(self.max_retries):
            try:
                self._wait_for_slot()
                response = requests.get(f"{self.base_url}/search.json", headers=self.headers, params=params, timeout=30)
                if response.status_code == 429:
                    time.sleep(min(8, 2 ** attempt))
                    continue
                response.raise_for_status()
                result = response.json().get("docs", [])
                cache_api_response(getattr(self, "cache_dir", None), "open_library", "search_books", cache_key, result)
                logger.info(
                    "[OPEN_LIBRARY_TRACE] stage=search_result cache_hit=False params=%r "
                    "result_count=%d candidates=%r",
                    params, len(result), _result_summary(result),
                )
                return result
            except requests.exceptions.RequestException as exc:
                if attempt == self.max_retries - 1:
                    raise
                logger.debug("Open Library request failed: %s", exc)
                time.sleep(min(8, 2 ** attempt))
        return []

    @staticmethod
    def _isbn_from_reference(reference: Dict[str, Any]) -> Optional[str]:
        for key in ("isbn", "ISBN"):
            value = reference.get(key)
            if value:
                return str(value).replace("-", "").strip()
        return None

    @staticmethod
    def _normalise_result(result: Dict[str, Any]) -> Dict[str, Any]:
        normalised = dict(result)
        main_title = str(result.get("title") or "").strip()
        subtitle = str(result.get("subtitle") or "").strip()
        # Keep Open Library's title and subtitle as distinct returned fields.
        # The combined value is for internal matching only: the citation may
        # contain the main title alone, the subtitle alone, or both.
        normalised["title"] = main_title
        normalised["subtitle"] = subtitle
        if subtitle and subtitle.casefold() not in main_title.casefold():
            normalised["_matching_title"] = f"{main_title}: {subtitle}".strip(": ")
        else:
            normalised["_matching_title"] = main_title
        normalised["authors"] = [{"name": name} for name in result.get("author_name", [])]
        normalised["publication_year"] = result.get("first_publish_year")
        normalised["year"] = result.get("first_publish_year")
        return normalised

    def verify_reference(self, reference: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        title = str(reference.get("title") or "").strip()
        authors = reference.get("authors") or []
        year = reference.get("year")
        isbn = self._isbn_from_reference(reference)
        if not title and not isbn:
            return None, [], None
        results = [self._normalise_result(item) for item in self.search_books(title, authors, isbn)]
        if not results:
            logger.info(
                "[OPEN_LIBRARY_TRACE] stage=match_result status=not_found "
                "title=%r author=%r year=%r reason=no_candidates",
                title, (authors or [None])[0], year,
            )
            return None, [], None
        if isbn and not title:
            work_data = results[0]
        else:
            # Score against the combined title/subtitle but retain the two
            # original Open Library fields in the returned metadata.
            matching_results = [
                {
                    **result,
                    "_returned_title": result.get("title", ""),
                    "title": result.get("_matching_title") or result.get("title", ""),
                }
                for result in results
            ]
            work_data, score = find_best_match(matching_results, clean_title_for_search(title), year, authors)
            if not work_data or score < SIMILARITY_THRESHOLD:
                logger.info(
                    "[OPEN_LIBRARY_TRACE] stage=match_result status=not_found "
                    "title=%r author=%r year=%r score=%r threshold=%r reason=no_acceptable_match",
                    title, (authors or [None])[0], year, score, SIMILARITY_THRESHOLD,
                )
                return None, [], None
            work_data["title"] = work_data.pop("_returned_title", work_data.get("title", ""))
        work_data.pop("_matching_title", None)
        errors: List[Dict[str, Any]] = []
        actual_authors = work_data.get("authors", [])
        if authors and actual_authors:
            matched, detail = compare_authors(authors, actual_authors)
            if not matched:
                errors.append(create_author_error(detail, [a["name"] for a in actual_authors]))
        actual_year = work_data.get("first_publish_year")
        if year and actual_year:
            try:
                different = abs(int(year) - int(actual_year)) > 1
            except (TypeError, ValueError):
                different = True
            if different:
                errors.append({"warning_type": "year", "warning_details": format_year_mismatch(year, actual_year), "ref_year_correct": actual_year})
        key = work_data.get("key")
        return work_data, errors, f"{self.base_url}{key}" if key else None
