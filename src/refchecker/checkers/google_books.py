"""Google Books metadata checker used as the final book/magazine fallback."""

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


class GoogleBooksReferenceChecker:
    """Verify book citations against the Google Books Volumes API.

    Responses are cached only for the lifetime of this checker instance.  This
    deliberately avoids creating a permanent copy of Google Books content.
    """

    _rate_lock = threading.Lock()
    _next_request_at = 0.0

    def __init__(
        self,
        api_key: Optional[str] = None,
        include_magazines: Optional[bool] = None,
    ) -> None:
        self.api_key = (api_key or os.environ.get("GOOGLE_BOOKS_API_KEY") or "").strip()
        if include_magazines is None:
            include_magazines = str(
                os.environ.get("REFCHECKER_GOOGLE_BOOKS_INCLUDE_MAGAZINES", "true")
            ).strip().lower() in {"1", "true", "yes", "on"}
        self.include_magazines = bool(include_magazines)
        self.base_url = "https://www.googleapis.com/books/v1/volumes"
        self.headers = {"Accept": "application/json"}
        if self.api_key:
            # Current Google Cloud guidance prefers the header over a query
            # parameter, which can leak credentials through URL logs.
            self.headers["x-goog-api-key"] = self.api_key
        try:
            self.request_delay = max(
                0.0,
                float(os.environ.get("REFCHECKER_GOOGLE_BOOKS_RATE_LIMIT_DELAY", "1.0")),
            )
        except ValueError:
            self.request_delay = 1.0
        self.max_retries = 3
        self._memory_cache: Dict[str, List[Dict[str, Any]]] = {}

    def _wait_for_slot(self) -> None:
        checker_type = type(self)
        with checker_type._rate_lock:
            now = time.monotonic()
            wait = max(0.0, checker_type._next_request_at - now)
            checker_type._next_request_at = max(now, checker_type._next_request_at) + self.request_delay
        if wait:
            time.sleep(wait)

    @staticmethod
    def _isbn_from_reference(reference: Dict[str, Any]) -> Optional[str]:
        for key in ("isbn", "ISBN"):
            value = reference.get(key)
            if value:
                return "".join(ch for ch in str(value) if ch.isdigit() or ch.upper() == "X")
        return None

    @staticmethod
    def _author_name(author: Any) -> str:
        if isinstance(author, dict):
            return str(author.get("name") or "").strip()
        return str(author or "").strip()

    @staticmethod
    def infer_print_type(reference: Dict[str, Any]) -> Optional[str]:
        """Identify media types that the Google Books fallback can safely query."""
        reference_type = str(
            reference.get("type")
            or reference.get("bibtex_type")
            or reference.get("publication_type")
            or reference.get("media_type")
            or reference.get("print_type")
            or ""
        ).strip().lower()
        if reference_type in {"magazine", "magazine_issue"}:
            return "magazines"
        if reference_type in {"book", "inbook", "booklet"}:
            return "books"

        # A literal magazine label is useful evidence; ISSN alone is not,
        # because it would also route ordinary scholarly journals here.
        container = " ".join(
            str(reference.get(field) or "")
            for field in ("journal", "venue", "booktitle", "container_title")
        ).lower()
        if "magazine" in container:
            return "magazines"
        if reference.get("isbn") or reference.get("ISBN"):
            return "books"
        if reference.get("publisher") and not container.strip():
            return "books"
        return None

    def search_volumes(
        self,
        title: str,
        authors: Optional[List[Any]] = None,
        isbn: Optional[str] = None,
        limit: int = 10,
        print_type: str = "books",
    ) -> List[Dict[str, Any]]:
        if not self.api_key:
            return []

        if print_type not in {"all", "books", "magazines"}:
            raise ValueError("print_type must be 'all', 'books', or 'magazines'")
        if print_type == "magazines" and not self.include_magazines:
            return []

        first_author = next(
            (self._author_name(author) for author in (authors or []) if self._author_name(author)),
            "",
        )
        if isbn:
            query = f"isbn:{isbn}"
        else:
            query = f'intitle:"{title}"'
            if first_author:
                query += f' inauthor:"{first_author}"'
        cache_key = f"{print_type}|{query}|{limit}"
        if cache_key in self._memory_cache:
            logger.info(
                "GOOGLE_BOOKS_API_TRACE event=cache_hit print_type=%s query=%r count=%d",
                print_type,
                query,
                len(self._memory_cache[cache_key]),
            )
            return self._memory_cache[cache_key]

        params = {
            "q": query,
            "printType": print_type,
            "projection": "lite",
            "orderBy": "relevance",
            "maxResults": min(max(limit, 1), 40),
        }
        logger.info(
            "GOOGLE_BOOKS_API_TRACE event=request print_type=%s query=%r max_results=%d",
            print_type,
            query,
            params["maxResults"],
        )
        for attempt in range(self.max_retries):
            self._wait_for_slot()
            response = requests.get(self.base_url, headers=self.headers, params=params, timeout=30)
            logger.info(
                "GOOGLE_BOOKS_API_TRACE event=response print_type=%s status=%d attempt=%d",
                print_type,
                response.status_code,
                attempt + 1,
            )
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                try:
                    wait = float(retry_after) if retry_after else 2 ** attempt
                except ValueError:
                    wait = 2 ** attempt
                if attempt < self.max_retries - 1:
                    time.sleep(min(30.0, max(0.0, wait)))
                    continue
            response.raise_for_status()
            results = response.json().get("items") or []
            logger.info(
                "GOOGLE_BOOKS_API_TRACE event=results print_type=%s count=%d",
                print_type,
                len(results),
            )
            self._memory_cache[cache_key] = results
            return results
        return []

    def search_books(
        self,
        title: str,
        authors: Optional[List[Any]] = None,
        isbn: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Backward-compatible book-only search helper."""
        return self.search_volumes(title, authors, isbn, limit, print_type="books")

    @staticmethod
    def _normalise_result(result: Dict[str, Any]) -> Dict[str, Any]:
        info = result.get("volumeInfo") or {}
        main_title = str(info.get("title") or "").strip()
        subtitle = str(info.get("subtitle") or "").strip()
        published_date = str(info.get("publishedDate") or "").strip()
        year = published_date[:4] if len(published_date) >= 4 and published_date[:4].isdigit() else None
        identifiers = info.get("industryIdentifiers") or []
        isbn_values = {
            str(item.get("type") or ""): str(item.get("identifier") or "")
            for item in identifiers
            if isinstance(item, dict) and item.get("identifier")
        }
        normalised = {
            "google_books_id": result.get("id"),
            "google_books_url": (
                f"https://books.google.com/books?id={result.get('id')}"
                if result.get("id") else None
            ),
            "title": main_title,
            "subtitle": subtitle,
            "authors": [{"name": name} for name in (info.get("authors") or [])],
            "publisher": info.get("publisher"),
            "published_date": published_date or None,
            "publication_year": int(year) if year else None,
            "year": int(year) if year else None,
            "isbn": isbn_values.get("ISBN_13") or isbn_values.get("ISBN_10"),
            "industry_identifiers": identifiers,
            "language": info.get("language"),
            "info_link": info.get("infoLink"),
            "canonical_volume_link": info.get("canonicalVolumeLink"),
            "print_type": info.get("printType"),
        }
        if subtitle and subtitle.casefold() not in main_title.casefold():
            normalised["_matching_title"] = f"{main_title}: {subtitle}".strip(": ")
        else:
            normalised["_matching_title"] = main_title
        return normalised

    def verify_reference(
        self, reference: Dict[str, Any]
    ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        if not self.api_key:
            return None, [], None
        title = str(reference.get("title") or "").strip()
        authors = reference.get("authors") or []
        cited_year = reference.get("year")
        isbn = self._isbn_from_reference(reference)
        force_all = bool(reference.get("_google_books_force_all"))
        print_type = "all" if force_all else self.infer_print_type(reference)
        if print_type is None:
            logger.info(
                "GOOGLE_BOOKS_API_TRACE event=skipped reason=unsupported_media title=%r",
                title,
            )
            return None, [], None
        if print_type == "magazines" and not self.include_magazines:
            logger.info(
                "GOOGLE_BOOKS_API_TRACE event=skipped reason=magazines_disabled title=%r",
                title,
            )
            return None, [], None
        if not title and not isbn:
            logger.info("GOOGLE_BOOKS_API_TRACE event=skipped reason=missing_title_and_isbn")
            return None, [], None

        raw_results = self.search_volumes(title, authors, isbn, print_type=print_type)
        # An ISBN query can miss because an edition is catalogued under a
        # different identifier. Use one title/author query as the last attempt.
        if not raw_results and isbn and title:
            raw_results = self.search_volumes(title, authors, None, print_type=print_type)
        results = [self._normalise_result(item) for item in raw_results]
        if not results:
            logger.info(
                "GOOGLE_BOOKS_API_TRACE event=no_match print_type=%s title=%r",
                print_type,
                title,
            )
            return None, [], None

        exact_isbn = None
        if isbn:
            cited = isbn.upper()
            for raw, normalised in zip(raw_results, results):
                identifiers = (raw.get("volumeInfo") or {}).get("industryIdentifiers") or []
                if any(
                    "".join(ch for ch in str(item.get("identifier") or "") if ch.isdigit() or ch.upper() == "X").upper() == cited
                    for item in identifiers
                    if isinstance(item, dict)
                ):
                    exact_isbn = normalised
                    break

        if exact_isbn is not None:
            work_data = exact_isbn
        else:
            matching_results = [
                {**item, "_returned_title": item.get("title", ""), "title": item.get("_matching_title", "")}
                for item in results
            ]
            work_data, score = find_best_match(
                matching_results, clean_title_for_search(title), cited_year, authors
            )
            if not work_data or score < SIMILARITY_THRESHOLD:
                logger.info(
                    "GOOGLE_BOOKS_API_TRACE event=no_match reason=similarity print_type=%s title=%r candidates=%d score=%.3f",
                    print_type,
                    title,
                    len(results),
                    float(score or 0.0),
                )
                return None, [], None
            work_data["title"] = work_data.pop("_returned_title", work_data.get("title", ""))

        work_data.pop("_matching_title", None)
        errors: List[Dict[str, Any]] = []
        actual_authors = work_data.get("authors") or []
        if authors and actual_authors:
            matched, detail = compare_authors(authors, actual_authors)
            if not matched:
                errors.append(create_author_error(detail, [a["name"] for a in actual_authors]))
        actual_year = work_data.get("publication_year")
        if cited_year and actual_year:
            try:
                different = abs(int(cited_year) - int(actual_year)) > 1
            except (TypeError, ValueError):
                different = True
            if different:
                errors.append({
                    "warning_type": "year",
                    "warning_details": format_year_mismatch(cited_year, actual_year),
                    "ref_year_correct": actual_year,
                })
        url = (
            work_data.get("canonical_volume_link")
            or work_data.get("info_link")
            or work_data.get("google_books_url")
        )
        logger.info(
            "GOOGLE_BOOKS_API_TRACE event=matched print_type=%s title=%r google_books_id=%r",
            print_type,
            title,
            work_data.get("google_books_id"),
        )
        return work_data, errors, url
