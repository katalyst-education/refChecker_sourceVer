"""Cross-source publication-year reconciliation.

Publication databases legitimately disagree about a work's year (for example,
online-first versus issue/print publication).  A citation year must therefore
not be called wrong merely because the first matching database reports a
different year.  This module performs the reconciliation once, in the shared
verification layer used by CLI, bulk, and WebUI paths.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

import requests


logger = logging.getLogger(__name__)

_LOOKUP_TIMEOUT_SECONDS = 5.0
_CACHE_TTL_SECONDS = 6 * 60 * 60
_CACHE: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
_CACHE_LOCK = threading.Lock()
_LOOKUP_SEMAPHORE = threading.BoundedSemaphore(8)


def _coerce_year(value: Any) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if 1000 <= value <= 2999 else None
    match = re.search(r"\b(1\d{3}|2\d{3})\b", str(value))
    return int(match.group(1)) if match else None


def _clean_doi(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    doi = value.strip()
    for prefix in (
        "https://doi.org/", "http://doi.org/", "https://dx.doi.org/",
        "http://dx.doi.org/", "doi:",
    ):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):]
            break
    doi = doi.strip().rstrip("/").lower()
    return doi if doi.startswith("10.") and "/" in doi else None


def _canonical_identifiers(
    reference: Dict[str, Any], verified_data: Dict[str, Any]
) -> Tuple[Optional[str], Optional[str]]:
    external = verified_data.get("externalIds") or {}
    ids = verified_data.get("ids") or {}
    doi = next((
        cleaned for cleaned in (
            _clean_doi(verified_data.get("doi")),
            _clean_doi(verified_data.get("DOI")),
            _clean_doi(ids.get("doi") if isinstance(ids, dict) else None),
            _clean_doi(external.get("DOI") if isinstance(external, dict) else None),
            _clean_doi(reference.get("doi")),
        ) if cleaned
    ), None)
    pmid_raw = (
        verified_data.get("pmid")
        or (external.get("PubMed") if isinstance(external, dict) else None)
        or (ids.get("pmid") if isinstance(ids, dict) else None)
        or reference.get("pmid")
    )
    pmid_match = re.search(r"\d+", str(pmid_raw or ""))
    return doi, (pmid_match.group(0) if pmid_match else None)


def _get_json(url: str, *, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        acquired = _LOOKUP_SEMAPHORE.acquire(timeout=_LOOKUP_TIMEOUT_SECONDS)
        if not acquired:
            return {}
        try:
            response = requests.get(url, params=params, timeout=_LOOKUP_TIMEOUT_SECONDS)
        finally:
            _LOOKUP_SEMAPHORE.release()
        if response.status_code != 200:
            return {}
        payload = response.json()
        return payload if isinstance(payload, dict) else {}
    except Exception as exc:
        logger.debug("publication-year lookup failed for %s: %s", url, exc)
        return {}


def _crossref_year(doi: str) -> Optional[int]:
    payload = _get_json(f"https://api.crossref.org/works/{quote(doi, safe='')}")
    message = payload.get("message") or {}
    if not isinstance(message, dict):
        return None
    # Prefer the issue/print year. Online-first is a common reason that
    # Semantic Scholar reports the previous year.
    for key in ("published-print", "issued", "published", "published-online"):
        parts = ((message.get(key) or {}).get("date-parts") or [])
        if parts and isinstance(parts[0], list) and parts[0]:
            year = _coerce_year(parts[0][0])
            if year:
                return year
    return None


def _openalex_year(doi: str) -> Optional[int]:
    payload = _get_json(f"https://api.openalex.org/works/doi:{quote(doi, safe='')}")
    return _coerce_year(payload.get("publication_year") or payload.get("publication_date"))


def _semantic_scholar_year(doi: str) -> Optional[int]:
    payload = _get_json(
        f"https://api.semanticscholar.org/graph/v1/paper/DOI:{quote(doi, safe='')}",
        params={"fields": "year,publicationDate"},
    )
    return _coerce_year(payload.get("year") or payload.get("publicationDate"))


def _pubmed_id_for_doi(doi: str) -> Optional[str]:
    payload = _get_json(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        params={"db": "pubmed", "term": f"{doi}[AID]", "retmode": "json", "retmax": 1},
    )
    id_list = ((payload.get("esearchresult") or {}).get("idlist") or [])
    return str(id_list[0]) if id_list else None


def _pubmed_year(pmid: str) -> Optional[int]:
    payload = _get_json(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
        params={"db": "pubmed", "id": pmid, "retmode": "json"},
    )
    result = payload.get("result") or {}
    record = result.get(str(pmid)) or {}
    if not isinstance(record, dict):
        return None
    # PubMed's displayed issue date is ``pubdate``.  Fall back to the sortable
    # publication date and then the electronic-publication date.
    return _coerce_year(
        record.get("pubdate") or record.get("sortpubdate") or record.get("epubdate")
    )


def _normalize_source_label(label: Any) -> str:
    text = str(label or "Verified database").strip()
    low = text.lower()
    if "semantic scholar" in low or low in {"s2", "local_s2"}:
        return "Semantic Scholar"
    if "pubmed" in low or "ncbi" in low:
        return "PubMed/NCBI"
    if "crossref" in low:
        return "Crossref"
    if "openalex" in low:
        return "OpenAlex"
    return text


def _dedupe_evidence(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_source: Dict[str, Dict[str, Any]] = {}
    for item in items:
        label = _normalize_source_label(item.get("source"))
        year = _coerce_year(item.get("year"))
        if label and year:
            by_source[label.lower()] = {"source": label, "year": year}
    return list(by_source.values())


def fetch_publication_years(
    reference: Dict[str, Any], verified_data: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Fetch real provider years for a DOI/PMID, with a bounded TTL cache."""
    doi, pmid = _canonical_identifiers(reference, verified_data)
    cache_key = f"doi:{doi}" if doi else (f"pmid:{pmid}" if pmid else "")
    if not cache_key:
        return []
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached and now - cached[0] < _CACHE_TTL_SECONDS:
            return [dict(item) for item in cached[1]]

    if not pmid and doi:
        pmid = _pubmed_id_for_doi(doi)

    jobs: List[Tuple[str, Callable[[], Optional[int]]]] = []
    if pmid:
        jobs.append(("PubMed/NCBI", lambda: _pubmed_year(pmid)))
    if doi:
        jobs.extend((
            ("Crossref", lambda: _crossref_year(doi)),
            ("OpenAlex", lambda: _openalex_year(doi)),
            ("Semantic Scholar", lambda: _semantic_scholar_year(doi)),
        ))

    evidence: List[Dict[str, Any]] = []
    if jobs:
        with ThreadPoolExecutor(max_workers=len(jobs), thread_name_prefix="YearMetadata") as pool:
            futures = [(label, pool.submit(fetcher)) for label, fetcher in jobs]
            for label, future in futures:
                try:
                    year = _coerce_year(future.result())
                except Exception as exc:
                    logger.debug("%s publication-year lookup failed: %s", label, exc)
                    year = None
                if year:
                    evidence.append({"source": label, "year": year})

    evidence = _dedupe_evidence(evidence)
    with _CACHE_LOCK:
        _CACHE[cache_key] = (now, [dict(item) for item in evidence])
    return evidence


def _is_year_issue(issue: Dict[str, Any]) -> bool:
    issue_type = issue.get("error_type") or issue.get("warning_type") or ""
    return str(issue_type).lower() in {"year", "publication_year"}


def reconcile_publication_year(
    reference: Dict[str, Any],
    verified_data: Optional[Dict[str, Any]],
    issues: Optional[List[Dict[str, Any]]],
    *,
    lookup: Callable[[Dict[str, Any], Dict[str, Any]], List[Dict[str, Any]]] = fetch_publication_years,
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """Classify a cited year using all available reliable-source evidence.

    * cited year supported and all sources agree -> verified (no year issue)
    * cited year supported but another source differs -> informational metadata
      discrepancy (still verified)
    * every available source disagrees -> likely citation error

    Network reconciliation is only attempted when the primary verifier already
    emitted a year issue and a DOI or PMID is available.
    """
    current = list(issues or [])
    if not isinstance(verified_data, dict) or not any(_is_year_issue(i) for i in current):
        return verified_data, current

    cited_year = _coerce_year(reference.get("year"))
    if not cited_year:
        return verified_data, current

    primary_year = _coerce_year(
        verified_data.get("publication_year")
        or verified_data.get("year")
        or verified_data.get("publicationDate")
        or verified_data.get("publication_date")
    )
    primary_label = _normalize_source_label(
        verified_data.get("_matched_database") or verified_data.get("_matched_checker")
    )
    evidence: List[Dict[str, Any]] = []
    if primary_year:
        evidence.append({"source": primary_label, "year": primary_year})

    preset = verified_data.get("_publication_year_sources")
    if isinstance(preset, list):
        evidence.extend(item for item in preset if isinstance(item, dict))
    else:
        try:
            evidence.extend(lookup(reference, verified_data) or [])
        except Exception as exc:
            logger.debug("publication-year reconciliation soft-failed: %s", exc)

    evidence = _dedupe_evidence(evidence)
    if not evidence:
        return verified_data, current

    # Put sources supporting the citation first so the explanatory line reads
    # naturally: "PubMed/NCBI: 2025 · Semantic Scholar: 2024".
    evidence.sort(key=lambda item: (item["year"] != cited_year, item["source"].lower()))
    years = {item["year"] for item in evidence}
    supported = cited_year in years
    year_issues = [item for item in current if _is_year_issue(item)]
    non_year_issues = [item for item in current if not _is_year_issue(item)]

    if supported and len(years) > 1:
        classification = "metadata_discrepancy"
        replacement = {
            "info_type": "publication_year_discrepancy",
            "info_details": "Publication dates differ across databases",
            "cited_value": str(cited_year),
            "source_years": evidence,
            "metadata_classification": classification,
        }
        reconciled = non_year_issues + [replacement]
    elif supported:
        classification = "verified"
        reconciled = non_year_issues
    elif len(evidence) >= 2 and len(years) == 1:
        classification = "likely_citation_error"
        template = year_issues[0] if year_issues else {}
        actual_year = primary_year or evidence[0]["year"]
        replacement = {
            key: value for key, value in template.items()
            if key not in {"error_type", "error_details", "warning_type", "warning_details"}
        }
        replacement.update({
            "warning_type": "year",
            "warning_details": "Likely citation error",
            "cited_value": str(cited_year),
            "actual_value": str(actual_year),
            "ref_year_correct": str(actual_year),
            "source_years": evidence,
            "metadata_classification": classification,
        })
        reconciled = non_year_issues + [replacement]
    else:
        # One disagreeing source, or disagreeing sources that do not agree with
        # each other, is not enough evidence for the stronger "likely citation
        # error" label. Preserve the primary verifier's conservative issue.
        return verified_data, current

    verified_data["_publication_year_sources"] = evidence
    verified_data["_publication_year_assessment"] = {
        "classification": classification,
        "cited_year": cited_year,
        "sources": evidence,
    }
    return verified_data, reconciled
