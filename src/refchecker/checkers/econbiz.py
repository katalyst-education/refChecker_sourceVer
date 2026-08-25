"""Reference verification against the public EconBiz v1 REST API.

EconBiz is particularly useful for economics and business literature that is
underrepresented in general scholarly indexes.  A normal metadata hit may
verify a reference.  Its optional full-text search is deliberately weaker: it
can show that a chapter occurs inside an indexed proceedings volume, but that
container record must not be presented as the cited chapter itself.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from refchecker.config.settings import get_config
from refchecker.utils.text_utils import (
    calculate_title_similarity,
    clean_title_for_search,
    compare_authors,
    find_best_match,
)

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = get_config()["text_processing"]["similarity_threshold"]
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_TITLE_SPLIT_RE = re.compile(r"\s+(?:[-\u2010-\u2015])\s+|\s*:\s*")


def _as_list(value: Any) -> List[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _author_name(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("name") or value.get("author") or value.get("full_name")
    return str(value or "").strip()


def _surname(value: Any) -> str:
    name = _author_name(value)
    if not name:
        return ""
    if "," in name:
        return name.split(",", 1)[0].strip()
    tokens = re.findall(r"[^\W\d_]+(?:[-'][^\W\d_]+)*", name, flags=re.UNICODE)
    return tokens[-1] if tokens else ""


class EconBizReferenceChecker:
    """Verify references and collect evidence through EconBiz API v1."""

    database_label = "EconBiz"
    _rate_lock = threading.Lock()
    _next_request_at = 0.0

    def __init__(self, email: Optional[str] = None) -> None:
        self.base_url = "https://api.econbiz.de/v1"
        self.portal_base_url = "https://www.econbiz.de/Record/-"
        self.email = (email or os.environ.get("REFCHECKER_CONTACT_EMAIL") or "").strip()
        self.headers = {
            "Accept": "application/json",
            "User-Agent": (
                f"RefChecker/1.0 (contact: {self.email})"
                if self.email else "RefChecker/1.0"
            ),
        }
        try:
            self.request_delay = max(
                0.0,
                float(os.environ.get("REFCHECKER_ECONBIZ_RATE_LIMIT_DELAY", "0.5")),
            )
        except ValueError:
            self.request_delay = 0.5
        self.max_retries = 3
        self.cache_dir: Optional[str] = None

    def _wait_for_slot(self) -> None:
        checker_type = type(self)
        with checker_type._rate_lock:
            now = time.monotonic()
            wait = max(0.0, checker_type._next_request_at - now)
            checker_type._next_request_at = max(now, checker_type._next_request_at) + self.request_delay
        if wait:
            time.sleep(wait)

    @staticmethod
    def _title_terms_query(title: str) -> str:
        """Build a punctuation-tolerant fielded query from Unicode title terms."""
        terms = re.findall(r"[^\W_]+(?:[-'][^\W_]+)*", title, flags=re.UNICODE)
        escaped = [re.sub(r"([+\-!(){}\[\]^\"~*?:\\/])", r"\\\1", term) for term in terms]
        return f"title:({' '.join(escaped)})" if escaped else ""

    @staticmethod
    def _evidence_query(title: str, authors: List[Any]) -> str:
        """Require a substantial title segment and cited surnames in full text."""
        segments = [segment.strip(" .;,\"'") for segment in _TITLE_SPLIT_RE.split(title)]
        eligible = [segment for segment in segments if len(segment.split()) >= 4]
        phrase = max(eligible, key=len) if eligible else title.strip(" .;,\"'")
        phrase = phrase.replace("\\", " ").replace('"', " ")
        surnames = []
        for author in authors[:3]:
            surname = _surname(author)
            if surname and surname.casefold() not in {item.casefold() for item in surnames}:
                surnames.append(surname)
        if not phrase or not surnames:
            return ""
        author_terms = " AND ".join(
            re.sub(r"([+\-!(){}\[\]^\"~*?:\\/])", r"\\\1", surname)
            for surname in surnames
        )
        return f'"{phrase}" AND {author_terms}'

    def search(self, query: str, *, fulltext: bool = False, limit: int = 10) -> List[Dict[str, Any]]:
        from refchecker.utils.cache_utils import cache_api_response, cached_api_response

        cache_key = f"v1|{query}|fulltext={bool(fulltext)}|limit={limit}"
        cached = cached_api_response(self.cache_dir, "econbiz", "search", cache_key)
        if cached:
            logger.info(
                "[ECONBIZ_TRACE] stage=search_result cache_hit=True fulltext=%s "
                "query=%r result_count=%d",
                fulltext, query, len(cached),
            )
            return cached

        params = {
            "q": query,
            "fulltext": "true" if fulltext else "false",
            "size": min(max(int(limit), 1), 50),
            "sort": "score desc",
        }
        for attempt in range(self.max_retries):
            try:
                self._wait_for_slot()
                logger.info(
                    "[ECONBIZ_TRACE] stage=request endpoint=%r fulltext=%s "
                    "query=%r limit=%d attempt=%d",
                    f"{self.base_url}/search",
                    fulltext,
                    query,
                    params["size"],
                    attempt + 1,
                )
                response = requests.get(
                    f"{self.base_url}/search",
                    params=params,
                    headers=self.headers,
                    timeout=30,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < self.max_retries - 1:
                        logger.warning(
                            "[ECONBIZ_TRACE] stage=retry http_status=%d "
                            "fulltext=%s query=%r attempt=%d next_attempt=%d",
                            response.status_code,
                            fulltext,
                            query,
                            attempt + 1,
                            attempt + 2,
                        )
                        time.sleep(min(8, 2 ** attempt))
                        continue
                response.raise_for_status()
                payload = response.json()
                results = ((payload.get("hits") or {}).get("hits") or [])
                if results:
                    cache_api_response(self.cache_dir, "econbiz", "search", cache_key, results)
                logger.info(
                    "[ECONBIZ_TRACE] stage=search_result cache_hit=False fulltext=%s "
                    "query=%r result_count=%d candidates=%r",
                    fulltext,
                    query,
                    len(results),
                    [
                        {
                            "id": item.get("id"),
                            "title": item.get("title"),
                            "year": (_as_list(item.get("date")) or [None])[0],
                            "score": item.get("_score"),
                        }
                        for item in results[:5]
                    ],
                )
                return results
            except (requests.exceptions.RequestException, ValueError) as exc:
                if attempt == self.max_retries - 1:
                    logger.error(
                        "[ECONBIZ_TRACE] stage=request_failure fulltext=%s "
                        "query=%r attempt=%d exception=%s detail=%r",
                        fulltext,
                        query,
                        attempt + 1,
                        type(exc).__name__,
                        str(exc),
                    )
                    raise
                logger.warning(
                    "[ECONBIZ_TRACE] stage=retry fulltext=%s query=%r "
                    "attempt=%d next_attempt=%d exception=%s detail=%r",
                    fulltext,
                    query,
                    attempt + 1,
                    attempt + 2,
                    type(exc).__name__,
                    str(exc),
                )
                time.sleep(min(8, 2 ** attempt))
        return []

    def _record_url(self, record: Dict[str, Any]) -> Optional[str]:
        record_id = str(record.get("id") or "").strip()
        return f"{self.portal_base_url}/{record_id}" if record_id else None

    @staticmethod
    def _normalise_result(record: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(record)
        author_values = (
            _as_list(record.get("creator"))
            or _as_list(record.get("person"))
            or _as_list(record.get("contributor"))
        )
        result["authors"] = [
            {"name": _author_name(author)} for author in author_values if _author_name(author)
        ]
        date_text = " ".join(str(value) for value in _as_list(record.get("date")))
        year_match = _YEAR_RE.search(date_text)
        year = int(year_match.group(0)) if year_match else None
        result["publication_year"] = year
        result["year"] = year
        result["venue"] = (_as_list(record.get("isPartOf")) or [None])[0]
        result["urls"] = [str(url) for url in _as_list(record.get("identifier_url")) if url]
        result["econbiz_id"] = record.get("id")
        result["_econbiz_source"] = record.get("source")
        return result

    @staticmethod
    def _year_matches(cited_year: Any, found_year: Any) -> bool:
        if cited_year in (None, ""):
            return True
        if found_year in (None, ""):
            return False
        try:
            return abs(int(cited_year) - int(found_year)) <= 1
        except (TypeError, ValueError):
            return False

    def _strict_match(
        self,
        records: List[Dict[str, Any]],
        title: str,
        authors: List[Any],
        year: Any,
    ) -> Optional[Dict[str, Any]]:
        normalised = [self._normalise_result(record) for record in records]
        candidate, score = find_best_match(
            normalised,
            clean_title_for_search(title),
            year,
            authors,
        )
        if not candidate:
            return None
        title_score = calculate_title_similarity(title, str(candidate.get("title") or ""))
        if score < SIMILARITY_THRESHOLD or title_score < SIMILARITY_THRESHOLD:
            return None
        if not self._year_matches(year, candidate.get("year")):
            return None
        found_authors = candidate.get("authors") or []
        if authors:
            if not found_authors:
                return None
            authors_match, _ = compare_authors(authors, found_authors)
            if not authors_match:
                return None
        return candidate

    def _supporting_evidence(
        self,
        records: List[Dict[str, Any]],
        cited_year: Any,
    ) -> Optional[Dict[str, Any]]:
        """Select a high-relevance, year-aligned full-text container record."""
        candidates = [self._normalise_result(record) for record in records]
        candidates = [
            record for record in candidates
            if float(record.get("_score") or 0.0) >= 0.30
            and self._year_matches(cited_year, record.get("year"))
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: float(item.get("_score") or 0.0))

    def verify_reference(
        self, reference: Dict[str, Any]
    ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        title = str(reference.get("title") or "").strip()
        authors = _as_list(reference.get("authors"))
        year = reference.get("year")
        if not title:
            return None, [], None

        title_query = self._title_terms_query(title)
        logger.info(
            "[ECONBIZ_TRACE] stage=query_plan title=%r authors=%r year=%r "
            "metadata_query=%r",
            title,
            authors,
            year,
            title_query,
        )
        records = self.search(title_query, fulltext=False) if title_query else []
        strict = self._strict_match(records, title, authors, year)
        if strict:
            url = self._record_url(strict)
            strict["_econbiz_record_url"] = url
            logger.info(
                "[ECONBIZ_TRACE] stage=match_result status=verified id=%r title=%r url=%r",
                strict.get("econbiz_id"), strict.get("title"), url,
            )
            return strict, [], url

        evidence_query = self._evidence_query(title, authors)
        logger.info(
            "[ECONBIZ_TRACE] stage=strict_result status=not_found "
            "candidate_count=%d fallback=fulltext evidence_query=%r",
            len(records),
            evidence_query,
        )
        evidence_records = self.search(evidence_query, fulltext=True) if evidence_query else []
        evidence = self._supporting_evidence(evidence_records, year)
        if evidence:
            evidence_url = self._record_url(evidence)
            container_title = str(evidence.get("title") or "an indexed publication")
            verified = dict(evidence)
            # The EconBiz record describes the containing work, not the cited
            # chapter itself. Keep the cited identity as the verified work while
            # retaining the exact container record as provenance.
            verified.update({
                "title": title,
                "authors": [
                    {"name": _author_name(author)}
                    for author in authors
                    if _author_name(author)
                ],
                "_verification_basis": "econbiz_fulltext_evidence",
                "_econbiz_container_title": container_title,
                "supporting_evidence_source": "EconBiz full-text search",
                "supporting_evidence_url": evidence_url,
                "supporting_evidence_title": container_title,
                "supporting_evidence_id": evidence.get("econbiz_id"),
            })
            try:
                cited_year = int(year) if year else None
            except (TypeError, ValueError):
                cited_year = None
            if cited_year:
                verified["year"] = cited_year
                verified["publication_year"] = cited_year
            logger.info(
                "[ECONBIZ_TRACE] stage=match_result status=verified_fulltext_evidence "
                "id=%r container_title=%r score=%r url=%r",
                evidence.get("econbiz_id"), container_title, evidence.get("_score"), evidence_url,
            )
            return verified, [], evidence_url

        logger.info(
            "[ECONBIZ_TRACE] stage=match_result status=not_found title=%r authors=%r year=%r",
            title, authors, year,
        )
        return None, [], None
