"""DNB, TIB, and ZDB SRU 1.1 metadata checkers.

DNB and ZDB are hosted by the Deutsche Nationalbibliothek; TIB exposes its
local catalogue through K10plus.  All three use SRU/MARC21, so the shared
transport and comparison code stays identical across execution paths.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple
from xml.etree import ElementTree

import requests

from refchecker.config.settings import get_config
from refchecker.utils.error_utils import create_author_error, format_year_mismatch
from refchecker.utils.text_utils import (
    clean_title_for_search,
    compare_authors,
    find_best_match,
    titles_align_as_delimited_segments,
)

logger = logging.getLogger(__name__)
SIMILARITY_THRESHOLD = get_config()["text_processing"]["similarity_threshold"]

_SRU_NS = "http://www.loc.gov/zing/srw/"
_MARC_NS = "http://www.loc.gov/MARC21/slim"
_DIAG_NS = "http://www.loc.gov/zing/srw/diagnostic/"
_YEAR_RE = re.compile(r"(?<!\d)(1[5-9]\d{2}|20\d{2}|21\d{2})(?!\d)")
_DOI_RE = re.compile(r"10\.\d{4,9}/\S+", re.IGNORECASE)
_MATCHER_IMPLEMENTATION = "dnb-title-segment-v2"


def _has_substantial_contiguous_title(title1: str, title2: str) -> bool:
    """Conservative fallback for catalogue titles wrapping the cited title."""
    token_lists = []
    for value in (title1, title2):
        cleaned = clean_title_for_search(value).lower()
        token_lists.append(re.findall(r"[a-z0-9]+", cleaned))
    tokens1, tokens2 = token_lists
    if not tokens1 or not tokens2:
        return False
    shorter, longer = (
        (tokens1, tokens2) if len(tokens1) <= len(tokens2) else (tokens2, tokens1)
    )
    if len(shorter) < 5 or len(" ".join(shorter)) < 30:
        return False
    width = len(shorter)
    return any(longer[index:index + width] == shorter for index in range(len(longer) - width + 1))


def _first(values: Iterable[str]) -> Optional[str]:
    for value in values:
        text = str(value or "").strip(" /:;,.")
        if text:
            return text
    return None


class DnbSruReferenceChecker:
    """Verify references against the DNB, TIB, or ZDB catalogue."""

    _rate_lock = threading.Lock()
    _next_request_at = 0.0

    def __init__(self, catalog: str = "dnb", email: Optional[str] = None) -> None:
        catalog = str(catalog).strip().lower()
        if catalog not in {"dnb", "tib", "zdb"}:
            raise ValueError("catalog must be 'dnb', 'tib', or 'zdb'")
        self.catalog = catalog
        if catalog == "tib":
            self.base_url = "https://sru.k10plus.de/opac-de-89"
            self.database_label = "TIB Catalogue"
            self.record_schema = "marcxml"
            delay_env = "REFCHECKER_TIB_SRU_RATE_LIMIT_DELAY"
        else:
            self.base_url = f"https://services.dnb.de/sru/{catalog}"
            self.database_label = "DNB Catalogue" if catalog == "dnb" else "ZDB Catalogue"
            self.record_schema = "MARC21-xml"
            delay_env = "REFCHECKER_DNB_SRU_RATE_LIMIT_DELAY"
        self.email = (email or os.environ.get("REFCHECKER_CONTACT_EMAIL") or "").strip()
        self.headers = {
            "Accept": "application/xml",
            "User-Agent": (
                f"RefChecker/1.0 (contact: {self.email})"
                if self.email else "RefChecker/1.0"
            ),
        }
        try:
            configured_delay = float(os.environ.get(delay_env, "0.5"))
        except ValueError:
            configured_delay = 0.5
        # None of these catalogues publishes a numeric request-per-day quota.
        # Keep each checker type behind a conservative process-wide limiter.
        self.request_delay = max(0.1, configured_delay)
        self.max_retries = 3

    def _wait_for_slot(self) -> None:
        checker_type = type(self)
        with checker_type._rate_lock:
            now = time.monotonic()
            wait = max(0.0, checker_type._next_request_at - now)
            checker_type._next_request_at = max(now, checker_type._next_request_at) + self.request_delay
        if wait:
            time.sleep(wait)

    @staticmethod
    def _cql_quote(value: Any) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'

    @staticmethod
    def _reference_identifier(reference: Dict[str, Any], keys: Iterable[str]) -> Optional[str]:
        for key in keys:
            value = reference.get(key)
            if value:
                return str(value).strip()
        return None

    def _queries_for_reference(self, reference: Dict[str, Any]) -> List[str]:
        queries: List[str] = []
        if self.catalog == "tib":
            ppn = self._reference_identifier(reference, ("ppn", "tibkat_id", "TIBKAT"))
            if not ppn:
                url = str(reference.get("url") or "")
                match = re.search(r"TIBKAT:(\d+)", url, re.IGNORECASE)
                ppn = match.group(1) if match else None
            if ppn:
                queries.append(f"pica.ppn={self._cql_quote(ppn)}")

            isbn = self._reference_identifier(reference, ("isbn", "ISBN"))
            issn = self._reference_identifier(reference, ("issn", "ISSN"))
            doi = self._reference_identifier(reference, ("doi", "DOI"))
            if isbn:
                queries.append(f"pica.isb={self._cql_quote(isbn)}")
            if issn:
                queries.append(f"pica.iss={self._cql_quote(issn)}")
            if doi:
                queries.append(f"pica.num={self._cql_quote(doi)}")
        elif self.catalog == "zdb":
            issn = self._reference_identifier(reference, ("issn", "ISSN"))
            if issn:
                queries.append(f"iss={self._cql_quote(issn)}")
        else:
            isbn = self._reference_identifier(reference, ("isbn", "ISBN"))
            doi = self._reference_identifier(reference, ("doi", "DOI"))
            identifier = isbn or doi
            if identifier:
                queries.append(f"num={self._cql_quote(identifier)}")

        title = clean_title_for_search(str(reference.get("title") or ""))
        if title:
            if self.catalog == "tib":
                queries.append(f"pica.tit={self._cql_quote(title)}")
            else:
                queries.append(f"tit all {self._cql_quote(title)}")
        return list(dict.fromkeys(queries))

    @staticmethod
    def _subfields(record: ElementTree.Element, tag: str, *codes: str) -> List[str]:
        values: List[str] = []
        wanted = set(codes)
        for field in record.findall(f"{{{_MARC_NS}}}datafield[@tag='{tag}']"):
            for subfield in field.findall(f"{{{_MARC_NS}}}subfield"):
                if not wanted or subfield.get("code") in wanted:
                    if subfield.text and subfield.text.strip():
                        values.append(subfield.text.strip())
        return values

    @classmethod
    def _contributors(cls, record: ElementTree.Element) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
        """Return personal creators and corporate contributors separately.

        MARC 100/700 fields name people, while 110/111/710/711 name
        organisations or meetings.  Treating all six fields as a positional
        author list lets an issuing body replace a real second author.  Keep
        role subfields so later reconciliation can explain the distinction.
        """
        people: List[Dict[str, str]] = []
        organisations: List[Dict[str, str]] = []
        seen = set()
        for tag, kind in (
            ("100", "person"), ("700", "person"),
            ("110", "organization"), ("710", "organization"),
            ("111", "meeting"), ("711", "meeting"),
        ):
            for field in record.findall(f"{{{_MARC_NS}}}datafield[@tag='{tag}']"):
                names = [
                    (subfield.text or "").strip(" ,")
                    for subfield in field.findall(f"{{{_MARC_NS}}}subfield[@code='a']")
                    if (subfield.text or "").strip(" ,")
                ]
                roles = [
                    (subfield.text or "").strip(" ,")
                    for code in ("e", "4")
                    for subfield in field.findall(f"{{{_MARC_NS}}}subfield[@code='{code}']")
                    if (subfield.text or "").strip(" ,")
                ]
                for name in names:
                    key = (kind, name.casefold(), tuple(role.casefold() for role in roles))
                    if key in seen:
                        continue
                    seen.add(key)
                    contributor = {"name": name, "kind": kind, "marc_tag": tag}
                    if roles:
                        contributor["role"] = "; ".join(roles)
                    (people if kind == "person" else organisations).append(contributor)
        return people, organisations

    @classmethod
    def _parse_record(cls, record: ElementTree.Element) -> Dict[str, Any]:
        control = {
            field.get("tag"): (field.text or "").strip()
            for field in record.findall(f"{{{_MARC_NS}}}controlfield")
        }
        title_main = _first(cls._subfields(record, "245", "a")) or ""
        subtitle = _first(cls._subfields(record, "245", "b")) or ""
        title = title_main
        if subtitle and subtitle.casefold() not in title_main.casefold():
            title = f"{title_main}: {subtitle}".strip(": ")

        authors, corporate_contributors = cls._contributors(record)

        publication_text = " ".join(
            cls._subfields(record, "264", "c")
            + cls._subfields(record, "260", "c")
        )
        year_match = _YEAR_RE.search(publication_text)
        if not year_match:
            fixed = control.get("008", "")
            year_match = _YEAR_RE.search(fixed[6:15] if fixed else "")
        year = int(year_match.group(1)) if year_match else None

        dois: List[str] = []
        for value in cls._subfields(record, "024", "a"):
            match = _DOI_RE.search(value)
            if match:
                dois.append(match.group(0).rstrip(".,;)"))
        for value in cls._subfields(record, "856", "u"):
            match = _DOI_RE.search(value)
            if match:
                dois.append(match.group(0).rstrip(".,;)"))

        idn = control.get("001")
        zdb_id = _first(cls._subfields(record, "016", "a"))
        result: Dict[str, Any] = {
            "title": title,
            "subtitle": subtitle or None,
            "authors": authors,
            "corporate_contributors": corporate_contributors,
            "publication_year": year,
            "year": year,
            "publisher": _first(
                cls._subfields(record, "264", "b")
                + cls._subfields(record, "260", "b")
            ),
            "venue": _first(cls._subfields(record, "773", "t")),
            "isbn": _first(cls._subfields(record, "020", "a")),
            "issn": _first(cls._subfields(record, "022", "a")),
            "doi": _first(dois),
            "idn": idn,
            "zdb_id": zdb_id,
        }
        return {key: value for key, value in result.items() if value not in (None, "", [])}

    @classmethod
    def _parse_response(cls, content: bytes) -> List[Dict[str, Any]]:
        root = ElementTree.fromstring(content)
        diagnostic = root.find(f".//{{{_DIAG_NS}}}diagnostic")
        if diagnostic is not None:
            message = diagnostic.findtext(f"{{{_DIAG_NS}}}message") or "SRU diagnostic"
            details = diagnostic.findtext(f"{{{_DIAG_NS}}}details")
            raise ValueError(f"{message}: {details}" if details else message)
        records = root.findall(f".//{{{_MARC_NS}}}record")
        return [cls._parse_record(record) for record in records]

    @staticmethod
    def _trace_candidates(records: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
        return [
            {
                "title": record.get("title"),
                "authors": [
                    author.get("name") if isinstance(author, dict) else str(author)
                    for author in (record.get("authors") or [])[:3]
                ],
                "year": record.get("publication_year") or record.get("year"),
                "id": record.get("ppn") or record.get("idn") or record.get("zdb_id"),
                "isbn": record.get("isbn"),
                "issn": record.get("issn"),
                "doi": record.get("doi"),
            }
            for record in records[:limit]
        ]

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        from refchecker.utils.cache_utils import cache_api_response, cached_api_response

        limit = min(max(int(limit), 1), 100)
        cache_key = f"v1|{self.catalog}|{query}|{limit}"
        cached = cached_api_response(
            getattr(self, "cache_dir", None), self.catalog, "sru_search", cache_key
        )
        if cached:
            logger.info(
                "[SRU_DATABASE_TRACE] stage=search_result database=%s cache_hit=True "
                "query=%r result_count=%d candidates=%r",
                self.catalog, query, len(cached), self._trace_candidates(cached),
            )
            return cached

        params = {
            "version": "1.1",
            "operation": "searchRetrieve",
            "query": query,
            "recordSchema": self.record_schema,
            "maximumRecords": limit,
        }
        for attempt in range(self.max_retries):
            try:
                self._wait_for_slot()
                logger.info(
                    "[SRU_DATABASE_TRACE] stage=request database=%s endpoint=%r query=%r "
                    "schema=%s limit=%d attempt=%d",
                    self.catalog, self.base_url, query, self.record_schema, limit, attempt + 1,
                )
                response = requests.get(
                    self.base_url,
                    headers=self.headers,
                    params=params,
                    timeout=30,
                )
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        wait = float(retry_after) if retry_after else 2 ** attempt
                    except ValueError:
                        wait = 2 ** attempt
                    time.sleep(min(30.0, max(1.0, wait)))
                    continue
                response.raise_for_status()
                results = self._parse_response(response.content)
                logger.info(
                    "[SRU_DATABASE_TRACE] stage=search_result database=%s cache_hit=False "
                    "query=%r http_status=%d result_count=%d candidates=%r",
                    self.catalog,
                    query,
                    response.status_code,
                    len(results),
                    self._trace_candidates(results),
                )
                cache_api_response(
                    getattr(self, "cache_dir", None), self.catalog, "sru_search", cache_key, results
                )
                return results
            except requests.exceptions.RequestException as exc:
                logger.info(
                    "[SRU_DATABASE_TRACE] stage=request_failure database=%s query=%r "
                    "attempt=%d exception=%s detail=%r",
                    self.catalog, query, attempt + 1, type(exc).__name__, str(exc),
                )
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(min(8, 2 ** attempt))
        return []

    def _record_url(self, record: Dict[str, Any]) -> Optional[str]:
        if self.catalog == "tib" and record.get("ppn"):
            return f"https://www.tib.eu/de/suchen/id/TIBKAT:{record['ppn']}"
        if self.catalog == "zdb" and record.get("zdb_id"):
            return f"https://ld.zdb-services.de/resource/{record['zdb_id']}"
        if record.get("idn"):
            return f"https://d-nb.info/{record['idn']}"
        return None

    def verify_reference(
        self, reference: Dict[str, Any]
    ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        title = str(reference.get("title") or "").strip()
        authors = reference.get("authors") or []
        year = reference.get("year")
        queries = self._queries_for_reference(reference)
        logger.info(
            "[SRU_DATABASE_TRACE] stage=query_plan database=%s title=%r authors=%r "
            "year=%r queries=%r implementation=%s source=%r",
            self.catalog, title, authors, year, queries, _MATCHER_IMPLEMENTATION, __file__,
        )
        if not queries:
            logger.info(
                "[SRU_DATABASE_TRACE] stage=match_result database=%s status=skipped reason=no_query",
                self.catalog,
            )
            return None, [], None

        records: List[Dict[str, Any]] = []
        matched_query = ""
        for query in queries:
            records = self.search(query)
            if records:
                matched_query = query
                break
        if not records:
            logger.info(
                "[SRU_DATABASE_TRACE] stage=match_result database=%s status=not_found "
                "reason=no_candidates attempted_queries=%r",
                self.catalog, queries,
            )
            return None, [], None

        if title:
            cleaned_title = clean_title_for_search(title)
            matched, score = find_best_match(
                records, cleaned_title, year, authors
            )
            tib_identifier_match = self.catalog == "tib" and matched_query.startswith(
                ("pica.ppn=", "pica.isb=", "pica.iss=", "pica.num=")
            )
            delimited_title_match = bool(
                matched
                and (
                    titles_align_as_delimited_segments(
                        cleaned_title,
                        matched.get("title") or matched.get("display_name", ""),
                    )
                    or _has_substantial_contiguous_title(
                        cleaned_title,
                        matched.get("title") or matched.get("display_name", ""),
                    )
                )
            )
            if not matched or (
                score < SIMILARITY_THRESHOLD
                and not tib_identifier_match
                and not delimited_title_match
            ):
                logger.info(
                    "[SRU_DATABASE_TRACE] stage=match_result database=%s status=rejected "
                    "reason=similarity score=%.3f threshold=%.3f query=%r candidate=%r",
                    self.catalog,
                    score,
                    SIMILARITY_THRESHOLD,
                    matched_query,
                    self._trace_candidates([matched] if matched else []),
                )
                return None, [], None
            if delimited_title_match and score < SIMILARITY_THRESHOLD:
                logger.info(
                    "[SRU_DATABASE_TRACE] stage=match_override database=%s "
                    "reason=delimited_title_segment score=%.3f threshold=%.3f "
                    "query=%r candidate=%r",
                    self.catalog,
                    score,
                    SIMILARITY_THRESHOLD,
                    matched_query,
                    self._trace_candidates([matched]),
                )
            if tib_identifier_match:
                # An exact PPN/ISBN/ISSN/DOI lookup is authoritative even when
                # the catalogue appends a long subtitle that lowers fuzzy title
                # similarity (as on TIBKAT:129529559).
                matched = records[0]
        else:
            matched = records[0]

        errors: List[Dict[str, Any]] = []
        actual_authors = matched.get("authors", [])
        if authors and actual_authors:
            authors_match, detail = compare_authors(authors, actual_authors)
            if not authors_match:
                errors.append(
                    create_author_error(
                        detail,
                        [author.get("name", "") for author in actual_authors],
                    )
                )
        actual_year = matched.get("publication_year")
        if year and actual_year:
            try:
                different = abs(int(year) - int(actual_year)) > 1
            except (TypeError, ValueError):
                different = True
            if different:
                errors.append({
                    "warning_type": "year",
                    "warning_details": format_year_mismatch(year, actual_year),
                    "ref_year_correct": actual_year,
                })
        logger.info(
            "[SRU_DATABASE_TRACE] stage=match_result database=%s status=matched query=%r "
            "candidate=%r error_count=%d url=%r",
            self.catalog,
            matched_query,
            self._trace_candidates([matched]),
            len(errors),
            self._record_url(matched),
        )
        return matched, errors, self._record_url(matched)


class ZdbSruReferenceChecker(DnbSruReferenceChecker):
    """ZDB specialization used by the shared hybrid orchestrator."""

    def __init__(self, email: Optional[str] = None) -> None:
        super().__init__(catalog="zdb", email=email)


class TibSruReferenceChecker(DnbSruReferenceChecker):
    """TIB local-catalogue specialization backed by K10plus SRU."""

    def __init__(self, email: Optional[str] = None) -> None:
        super().__init__(catalog="tib", email=email)

    @classmethod
    def _parse_record(cls, record: ElementTree.Element) -> Dict[str, Any]:
        result = super()._parse_record(record)
        idn = result.pop("idn", None)
        if idn:
            result["ppn"] = idn
        return result
