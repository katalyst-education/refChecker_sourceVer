"""Springer Nature Meta API v2 checker.

The API is optional and key-gated.  It is a publisher metadata source, so it
is especially useful for distinguishing an original Springer Nature work from
an editorial, correction, or book review that merely repeats the work's title.
"""

from __future__ import annotations

import logging
import os
import re
import hashlib
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from refchecker.config.settings import get_config
from refchecker.utils.doi_utils import compare_dois
from refchecker.utils.error_utils import create_author_error, create_venue_warning, validate_year
from refchecker.utils.text_utils import (
    clean_title_for_search,
    compare_authors,
    find_best_match,
)

logger = logging.getLogger(__name__)
SIMILARITY_THRESHOLD = get_config()["text_processing"]["similarity_threshold"]


class SpringerNatureReferenceChecker:
    """Verify references with the Springer Nature Meta API v2."""

    _rate_lock = threading.Lock()
    _next_request_at = 0.0
    _fallback_quota_lock = threading.Lock()
    _fallback_request_times: Dict[str, List[float]] = {}
    _fallback_cooldowns: Dict[str, float] = {}

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        daily_request_limit: Optional[int] = None,
        minute_request_limit: Optional[int] = None,
        quota_state_path: Optional[str] = None,
    ) -> None:
        api_config = get_config().get("springer_nature", {})
        self.api_key = (
            api_key
            or os.environ.get("SPRINGER_NATURE_API_KEY")
            or os.environ.get("SPRINGER_API_KEY")
            or ""
        ).strip()
        self.base_url = api_config.get(
            "base_url", "https://api.springernature.com/meta/v2/json"
        )
        self.headers = {
            "Accept": "application/json",
            "User-Agent": "RefChecker/1.0 (https://github.com/ArioMoniri/refchecker)",
        }
        self.request_delay = self._float_setting(
            "REFCHECKER_SPRINGER_NATURE_RATE_LIMIT_DELAY",
            float(api_config.get("rate_limit_delay", 1.0)),
            minimum=0.75,
        )
        # The free plan currently permits 500/day and 100/minute.  RefChecker
        # deliberately keeps a 10% safety margin for portal tests and calls
        # made by other applications using the same key.
        self.daily_request_limit = self._int_setting(
            daily_request_limit,
            "REFCHECKER_SPRINGER_NATURE_DAILY_LIMIT",
            int(api_config.get("daily_request_limit", 450)),
            minimum=1,
        )
        self.minute_request_limit = self._int_setting(
            minute_request_limit,
            "REFCHECKER_SPRINGER_NATURE_MINUTE_LIMIT",
            int(api_config.get("minute_request_limit", 90)),
            minimum=1,
        )
        self.quota_state_path = quota_state_path
        self.max_retries = max(1, int(api_config.get("max_retries", 3)))
        self.timeout = max(1.0, float(api_config.get("timeout", 30)))

    @staticmethod
    def _float_setting(name: str, default: float, *, minimum: float) -> float:
        try:
            return max(minimum, float(os.environ.get(name, str(default))))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _int_setting(
        explicit: Optional[int], name: str, default: int, *, minimum: int
    ) -> int:
        try:
            value = explicit if explicit is not None else os.environ.get(name, str(default))
            return max(minimum, int(value))
        except (TypeError, ValueError):
            return default

    @property
    def _key_id(self) -> str:
        # Only a one-way identifier is persisted; never write the API key.
        return hashlib.sha256(self.api_key.encode("utf-8")).hexdigest()[:24]

    def _quota_database(self) -> Path:
        explicit = self.quota_state_path or os.environ.get(
            "REFCHECKER_SPRINGER_NATURE_QUOTA_STATE"
        )
        if explicit:
            return Path(explicit).expanduser()

        cache_dir = getattr(self, "cache_dir", None)
        if cache_dir:
            return Path(cache_dir).expanduser() / "provider_state.sqlite3"

        if os.name == "nt":
            base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        else:
            base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        return base / "refchecker" / "provider_state.sqlite3"

    def _reserve_request_sqlite(self, now: float) -> Tuple[bool, str, int]:
        path = self._quota_database()
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path, timeout=10) as conn:
            conn.execute("PRAGMA busy_timeout = 10000")
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS springer_nature_requests ("
                "key_id TEXT NOT NULL, requested_at REAL NOT NULL)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_springer_requests_key_time "
                "ON springer_nature_requests(key_id, requested_at)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS springer_nature_cooldowns ("
                "key_id TEXT PRIMARY KEY, blocked_until REAL NOT NULL)"
            )
            conn.execute(
                "DELETE FROM springer_nature_requests WHERE requested_at < ?",
                (now - 7 * 86400,),
            )
            row = conn.execute(
                "SELECT blocked_until FROM springer_nature_cooldowns WHERE key_id = ?",
                (self._key_id,),
            ).fetchone()
            if row and float(row[0]) > now:
                return False, "cooldown", max(1, int(float(row[0]) - now))

            daily_count = int(conn.execute(
                "SELECT COUNT(*) FROM springer_nature_requests "
                "WHERE key_id = ? AND requested_at > ?",
                (self._key_id, now - 86400),
            ).fetchone()[0])
            if daily_count >= self.daily_request_limit:
                return False, "daily_limit", 0

            minute_rows = conn.execute(
                "SELECT requested_at FROM springer_nature_requests "
                "WHERE key_id = ? AND requested_at > ? ORDER BY requested_at",
                (self._key_id, now - 60),
            ).fetchall()
            if len(minute_rows) >= self.minute_request_limit:
                wait = max(1, int(float(minute_rows[0][0]) + 60 - now) + 1)
                return False, "minute_limit", wait

            conn.execute(
                "INSERT INTO springer_nature_requests(key_id, requested_at) VALUES (?, ?)",
                (self._key_id, now),
            )
            return True, "ok", self.daily_request_limit - daily_count - 1

    def _reserve_request_fallback(self, now: float) -> Tuple[bool, str, int]:
        """Fail safely in-process if the persistent quota database is unavailable."""
        with type(self)._fallback_quota_lock:
            key_id = self._key_id
            blocked_until = type(self)._fallback_cooldowns.get(key_id, 0.0)
            if blocked_until > now:
                return False, "cooldown", max(1, int(blocked_until - now))
            times = type(self)._fallback_request_times.setdefault(key_id, [])
            times[:] = [stamp for stamp in times if stamp > now - 86400]
            if len(times) >= self.daily_request_limit:
                return False, "daily_limit", 0
            minute_times = [stamp for stamp in times if stamp > now - 60]
            if len(minute_times) >= self.minute_request_limit:
                return False, "minute_limit", max(1, int(minute_times[0] + 60 - now) + 1)
            times.append(now)
            return True, "ok", self.daily_request_limit - len(times)

    def _reserve_request(self) -> Tuple[bool, str, int]:
        now = time.time()
        try:
            return self._reserve_request_sqlite(now)
        except (OSError, sqlite3.Error) as exc:
            logger.warning(
                "Springer Nature persistent quota tracking unavailable (%s); "
                "using the process-local safety counter",
                type(exc).__name__,
            )
            return self._reserve_request_fallback(now)

    def _set_cooldown(self, seconds: float) -> None:
        blocked_until = time.time() + max(1.0, seconds)
        try:
            path = self._quota_database()
            path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(path, timeout=10) as conn:
                conn.execute("PRAGMA busy_timeout = 10000")
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS springer_nature_cooldowns ("
                    "key_id TEXT PRIMARY KEY, blocked_until REAL NOT NULL)"
                )
                conn.execute(
                    "INSERT INTO springer_nature_cooldowns(key_id, blocked_until) "
                    "VALUES (?, ?) ON CONFLICT(key_id) DO UPDATE SET blocked_until=excluded.blocked_until",
                    (self._key_id, blocked_until),
                )
        except (OSError, sqlite3.Error):
            with type(self)._fallback_quota_lock:
                type(self)._fallback_cooldowns[self._key_id] = blocked_until

    @staticmethod
    def _retry_after_seconds(response: requests.Response) -> float:
        value = response.headers.get("Retry-After")
        if value:
            try:
                return max(1.0, float(value))
            except ValueError:
                pass
        # At RefChecker's conservative minute rate, a 429 without guidance is
        # most likely the provider's daily allowance.  Avoid hammering it.
        return 3600.0

    def _wait_for_slot(self) -> None:
        checker_type = type(self)
        with checker_type._rate_lock:
            now = time.monotonic()
            wait = max(0.0, checker_type._next_request_at - now)
            checker_type._next_request_at = max(now, checker_type._next_request_at) + self.request_delay
        if wait:
            time.sleep(wait)

    @staticmethod
    def _clean_doi(value: Any) -> str:
        doi = str(value or "").strip()
        doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", doi, flags=re.I)
        return doi.strip()

    @staticmethod
    def _escape_phrase(value: Any) -> str:
        return str(value or "").replace("\\", "\\\\").replace('"', '\\"').strip()

    @staticmethod
    def _author_name(author: Any) -> str:
        if isinstance(author, dict):
            return str(author.get("name") or author.get("creator") or "").strip()
        return str(author or "").strip()

    @classmethod
    def _query_for_reference(cls, reference: Dict[str, Any]) -> Optional[str]:
        doi = cls._clean_doi(reference.get("doi") or reference.get("DOI"))
        if doi:
            return f'doi:"{cls._escape_phrase(doi)}"'

        title = cls._escape_phrase(reference.get("title"))
        if not title:
            return None
        # Basic API plans do not permit the title: and name: contains
        # constraints.  An exact quoted phrase without a constraint performs
        # the Basic-compatible general-text search; local matching below still
        # requires a strong title/author match before accepting a record.
        query = f'"{title}"'
        first_author = next(
            (cls._author_name(author) for author in (reference.get("authors") or [])
             if cls._author_name(author)),
            "",
        )
        if first_author:
            # Meta API creator strings are usually "Family, Given", while
            # extracted citations are often "Given Family".  Adding only the
            # surname as a second general-text phrase avoids making that
            # presentation difference suppress an otherwise exact title result.
            if "," in first_author:
                surname = first_author.split(",", 1)[0].strip()
            else:
                surname = first_author.rsplit(" ", 1)[-1].strip()
            if surname:
                query += f' "{cls._escape_phrase(surname)}"'
        return query

    def search_records(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search Meta API v2 without ever logging or caching the API key."""
        if not self.api_key or not query:
            return []

        from refchecker.utils.cache_utils import cached_api_response, cache_api_response

        page_size = min(max(int(limit), 1), 20)
        cache_key = f"{query}|1|{page_size}"
        cached = cached_api_response(
            getattr(self, "cache_dir", None), "springer_nature", "meta_v2", cache_key
        )
        if cached is not None:
            return cached

        params = {"api_key": self.api_key, "q": query, "s": 1, "p": page_size}
        logger.info(
            "SPRINGER_NATURE_API_TRACE event=request query=%r page_size=%d",
            query,
            page_size,
        )
        for attempt in range(self.max_retries):
            self._wait_for_slot()
            allowed, reason, detail = self._reserve_request()
            if not allowed:
                logger.warning(
                    "SPRINGER_NATURE_API_TRACE event=locally_limited reason=%s retry_after=%d",
                    reason,
                    detail,
                )
                return []
            logger.info(
                "SPRINGER_NATURE_API_TRACE event=quota_reserved remaining_24h=%d",
                detail,
            )
            try:
                response = requests.get(
                    self.base_url,
                    headers=self.headers,
                    params=params,
                    timeout=self.timeout,
                )
                logger.info(
                    "SPRINGER_NATURE_API_TRACE event=response status=%d attempt=%d",
                    response.status_code,
                    attempt + 1,
                )
                if response.status_code == 429:
                    cooldown = self._retry_after_seconds(response)
                    self._set_cooldown(cooldown)
                    logger.warning(
                        "SPRINGER_NATURE_API_TRACE event=provider_limited cooldown_seconds=%d",
                        int(cooldown),
                    )
                    return []
                if response.status_code in (400, 403):
                    # Basic keys can receive 403 for records outside their
                    # content rights. Neither that nor a rejected query becomes
                    # valid through retries, so preserve quota and continue
                    # with RefChecker's other providers.
                    logger.info(
                        "SPRINGER_NATURE_API_TRACE event=request_rejected status=%d no_retry=true",
                        response.status_code,
                    )
                    cache_api_response(
                        getattr(self, "cache_dir", None),
                        "springer_nature",
                        "meta_v2",
                        cache_key,
                        [],
                    )
                    return []
                if response.status_code == 401:
                    # An invalid/inactive key affects every query; avoid
                    # spending more requests for the rest of this run.
                    self._set_cooldown(3600)
                    logger.warning(
                        "SPRINGER_NATURE_API_TRACE event=authentication_failed cooldown_seconds=3600"
                    )
                    return []
                if response.status_code >= 500:
                    if attempt < self.max_retries - 1:
                        retry_after = response.headers.get("Retry-After")
                        try:
                            wait = float(retry_after) if retry_after else 2 ** attempt
                        except ValueError:
                            wait = 2 ** attempt
                        time.sleep(min(30.0, max(0.0, wait)))
                        continue
                response.raise_for_status()
                records = response.json().get("records") or []
                cache_api_response(
                    getattr(self, "cache_dir", None),
                    "springer_nature",
                    "meta_v2",
                    cache_key,
                    records,
                )
                return records
            except requests.exceptions.RequestException:
                if attempt >= self.max_retries - 1:
                    raise
                time.sleep(min(30.0, float(2 ** attempt)))
        return []

    @staticmethod
    def _year(value: Any) -> Optional[int]:
        match = re.search(r"(?:19|20)\d{2}", str(value or ""))
        return int(match.group(0)) if match else None

    @classmethod
    def _normalise_record(cls, record: Dict[str, Any]) -> Dict[str, Any]:
        creators = record.get("creators") or []
        authors = [
            {"name": cls._author_name(item)}
            for item in creators
            if cls._author_name(item)
        ]
        urls = record.get("url") or []
        web_url = None
        for item in urls:
            if isinstance(item, dict) and item.get("value"):
                if str(item.get("format") or "").lower() == "html":
                    web_url = str(item["value"])
                    break
                web_url = web_url or str(item["value"])

        doi = cls._clean_doi(record.get("doi") or record.get("identifier")) or None
        publication_date = (
            record.get("publicationDate")
            or record.get("onlineDate")
            or record.get("coverDate")
        )
        genre = record.get("genre") or []
        if isinstance(genre, str):
            genre = [genre]
        type_values = [record.get("contentType"), record.get("publicationType"), *genre]
        normalised_types = {
            re.sub(r"[^a-z]", "", str(value or "").casefold())
            for value in type_values
        }
        # Do not reject scholarly review articles (ReviewPaper).  The dangerous
        # collision is specifically a BookReview whose title is the reviewed
        # book's title.
        is_review = "bookreview" in normalised_types
        title = str(record.get("title") or "").strip()
        return {
            "title": title,
            "authors": authors,
            "publication_year": cls._year(publication_date),
            "year": cls._year(publication_date),
            "publication_date": publication_date,
            "venue": record.get("publicationName") or record.get("journalTitle"),
            "journal": record.get("publicationName") or record.get("journalTitle"),
            "publisher": record.get("publisherName") or record.get("publisher"),
            "doi": doi,
            "externalIds": {"DOI": doi} if doi else {},
            "url": web_url or (f"https://doi.org/{doi}" if doi else None),
            "abstract": record.get("abstract"),
            "content_type": record.get("contentType"),
            "publication_type": record.get("publicationType"),
            "genre": genre,
            "isbn": record.get("isbn"),
            "issn": record.get("issn") or record.get("eIssn"),
            "volume": record.get("volume"),
            "issue": record.get("number"),
            "pages": "-".join(
                str(value) for value in (record.get("startingPage"), record.get("endingPage"))
                if value not in (None, "")
            ) or None,
            "_springer_nature_is_review": is_review,
            "_springer_nature_record": True,
        }

    @staticmethod
    def _citation_is_review(reference: Dict[str, Any]) -> bool:
        type_text = " ".join(
            str(reference.get(key) or "")
            for key in ("type", "bibtex_type", "publication_type", "genre")
        ).casefold()
        return "review" in type_text

    def verify_reference(
        self, reference: Dict[str, Any]
    ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        if not self.api_key:
            return None, [], None
        query = self._query_for_reference(reference)
        if not query:
            return None, [], None

        try:
            records = self.search_records(query)
        except requests.exceptions.RequestException as exc:
            # Request exception strings may include the fully prepared URL,
            # including the query-parameter API key. Log only the exception
            # class so credentials never enter logs.
            logger.warning(
                "Springer Nature API request failed (%s)",
                type(exc).__name__,
            )
            return None, [{
                "error_type": "api_failure",
                "error_details": "Springer Nature API was unavailable",
            }], None

        candidates = [self._normalise_record(record) for record in records]
        cited_doi = self._clean_doi(reference.get("doi") or reference.get("DOI"))
        if not cited_doi and not self._citation_is_review(reference):
            rejected = [item for item in candidates if item.get("_springer_nature_is_review")]
            candidates = [item for item in candidates if not item.get("_springer_nature_is_review")]
            if rejected:
                logger.info(
                    "SPRINGER_NATURE_API_TRACE event=rejected_review cited_title=%r rejected=%r",
                    reference.get("title"),
                    [item.get("title") for item in rejected[:3]],
                )
        if not candidates:
            return None, [], None

        match = None
        if cited_doi:
            match = next(
                (item for item in candidates if item.get("doi") and compare_dois(cited_doi, item["doi"])),
                None,
            )
        if match is None:
            matching_candidates = [dict(item) for item in candidates]
            match, score = find_best_match(
                matching_candidates,
                clean_title_for_search(reference.get("title") or ""),
                reference.get("year"),
                reference.get("authors") or [],
            )
            if not match or float(score or 0.0) < SIMILARITY_THRESHOLD:
                return None, [], None

        errors: List[Dict[str, Any]] = []
        cited_authors = reference.get("authors") or []
        actual_authors = match.get("authors") or []
        if cited_authors and actual_authors:
            authors_match, detail = compare_authors(cited_authors, actual_authors)
            if not authors_match:
                errors.append(create_author_error(
                    detail,
                    [item.get("name") for item in actual_authors if item.get("name")],
                ))

        year_issue = validate_year(
            reference.get("year"),
            match.get("publication_year"),
            year_tolerance=1,
            context={"cited_doi": cited_doi},
        )
        if year_issue:
            errors.append(year_issue)

        cited_venue = reference.get("journal") or reference.get("venue")
        actual_venue = match.get("venue")
        if cited_venue and actual_venue:
            from refchecker.utils.text_utils import are_venues_substantially_different
            if are_venues_substantially_different(
                str(cited_venue), str(actual_venue), paper_title=reference.get("title")
            ):
                errors.append(create_venue_warning(str(cited_venue), str(actual_venue)))

        url = match.get("url") or (f"https://doi.org/{match['doi']}" if match.get("doi") else None)
        logger.info(
            "SPRINGER_NATURE_API_TRACE event=matched title=%r doi=%r review=%s",
            match.get("title"),
            match.get("doi"),
            match.get("_springer_nature_is_review"),
        )
        return match, errors, url
