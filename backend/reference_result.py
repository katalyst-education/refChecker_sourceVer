"""Shared WebUI projection for a verifier result.

The initial scan and the per-reference re-verify endpoint both receive the
same raw verifier tuple: ``(verified_data, findings, verified_url)``.  This
module is deliberately the single place that translates that tuple into the
row shape consumed by the React UI.  Keeping the projection here prevents a
fresh "Search all DBs" result from retaining source labels, suggestions, or
other presentation data from a previous verification.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

from backend.reference_status import classify_verification_result
from backend.reference_urls import build_authoritative_urls
from refchecker.utils.reference_suggestions import suppress_redundant_arxiv_suggestions


logger = logging.getLogger(__name__)


def _format_findings(sanitized: Iterable[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return the UI's errors, warnings, infos, and suggestions lists."""
    formatted_errors: List[Dict[str, Any]] = []
    formatted_warnings: List[Dict[str, Any]] = []
    formatted_infos: List[Dict[str, Any]] = []
    formatted_suggestions: List[Dict[str, Any]] = []

    for err in sanitized:
        err_obj = {
            "error_type": err.get("error_type") or err.get("warning_type") or "unknown",
            "error_details": err.get("error_details", ""),
            "cited_value": err.get("cited_value"),
            "actual_value": err.get("actual_value"),
        }
        for key in (
            "source_years", "metadata_classification", "requires_user_confirmation",
            "match_provenance", "supporting_evidence_source",
            "supporting_evidence_url", "supporting_evidence_title",
            "supporting_evidence_id", "ref_year_correct", "ref_venue_correct",
            "ref_title_correct", "ref_authors_correct", "ref_doi_correct",
        ):
            if err.get(key):
                err_obj[key] = err[key]

        if err.get("is_info"):
            formatted_infos.append({
                "info_type": err.get("error_type") or "info",
                "info_details": err.get("error_details", ""),
                "cited_value": err.get("cited_value"),
                "source_years": err.get("source_years") or [],
                "metadata_classification": err.get("metadata_classification"),
            })
        elif err.get("is_suggestion"):
            formatted_suggestions.append({
                "suggestion_type": err.get("error_type") or "info",
                "suggestion_details": err.get("error_details", ""),
            })
        elif err.get("is_warning"):
            formatted_warnings.append(err_obj)
        else:
            formatted_errors.append(err_obj)

    return formatted_errors, formatted_warnings, formatted_infos, formatted_suggestions


def _build_enrichment(
    reference: Dict[str, Any], verified_data: Optional[Dict[str, Any]], *, enabled: bool,
) -> Dict[str, Any]:
    if not enabled:
        return {}
    try:
        from refchecker.utils.enrichment import backfill_enrichment, build_enrichment

        if isinstance(verified_data, dict):
            backfill_enrichment(verified_data, reference)
        return build_enrichment(verified_data) or {}
    except Exception as exc:  # Display enrichment must never fail verification.
        logger.debug("enrichment build failed: %s", exc)
        return {}


def project_verification_result(
    reference: Dict[str, Any],
    verified_data: Optional[Dict[str, Any]],
    findings: Optional[List[Dict[str, Any]]],
    verified_url: Optional[str],
    *,
    index: Optional[int] = None,
    enrich_enabled: bool = True,
    include_raw_errors: bool = False,
) -> Dict[str, Any]:
    """Project raw verification data into the canonical WebUI reference row.

    ``reference`` remains the citation extracted from the document; canonical
    metadata belongs in ``verified_*`` fields so it never overwrites the cited
    work.  The returned mapping contains all verification-derived display
    fields and can therefore replace a prior projection wholesale.
    """
    cited = dict(reference or {})
    findings = findings or []
    status, sanitized = classify_verification_result(cited, verified_data, findings, verified_url)
    formatted_errors, formatted_warnings, formatted_infos, formatted_suggestions = _format_findings(sanitized)

    url_references_paper = any(
        "url references paper" in (entry.get("error_details") or "").lower()
        for entry in findings
    )
    verified_via_webpage = (
        status == "verified" and url_references_paper
    ) or bool((verified_data or {}).get("web_metadata"))
    authoritative_urls = build_authoritative_urls(
        cited, verified_data, verified_url, status=status,
        verified_via_webpage=verified_via_webpage,
    )
    enrichment = _build_enrichment(cited, verified_data, enabled=enrich_enabled)

    display_authors = None
    try:
        from refchecker.utils.text_utils import recover_full_authors_from_enrichment
        display_authors = recover_full_authors_from_enrichment(
            cited.get("authors"), enrichment.get("authors"),
        )
    except Exception as exc:
        logger.debug("author recovery failed: %s", exc)

    verified = verified_data if isinstance(verified_data, dict) else {}
    external_ids = verified.get("externalIds") or {}
    cited_doi = cited.get("doi") or cited.get("verified_doi") or ""
    cited_arxiv = cited.get("arxiv_id") or cited.get("verified_arxiv_id") or ""
    cited_pmid = cited.get("pmid") or cited.get("verified_pmid") or ""
    doi = str(cited_doi).strip().lower() or str(external_ids.get("DOI") or verified.get("doi") or "").strip().lower()
    arxiv_id = str(cited_arxiv).strip().lower() or str(external_ids.get("ArXiv") or verified.get("arxiv_id") or "").strip().lower()
    pmid = str(cited_pmid).strip() or str(external_ids.get("PubMed") or verified.get("pmid") or "").strip()

    result: Dict[str, Any] = {
        "index": cited.get("index") if index is None else index,
        "title": cited.get("title") or cited.get("cited_url") or cited.get("url") or "Unknown Title",
        "authors": display_authors or cited.get("authors", []),
        "year": cited.get("year") or None,
        "venue": cited.get("venue"),
        "cited_url": cited.get("cited_url") or cited.get("url"),
        "doi": doi or None,
        "arxiv_id": arxiv_id or None,
        "pmid": pmid or None,
        "status": status,
        "errors": formatted_errors,
        "warnings": formatted_warnings,
        "infos": formatted_infos,
        "suggestions": formatted_suggestions,
        "verified_url": verified_url,
        "authoritative_urls": authoritative_urls,
        "matched_database": verified.get("_matched_database") or (
            "Web page" if verified_via_webpage else None
        ),
        "verification_basis": verified.get("_verification_basis"),
        "supporting_evidence": (
            {
                "source": verified.get("supporting_evidence_source"),
                "url": verified.get("supporting_evidence_url"),
                "title": verified.get("supporting_evidence_title"),
                "id": verified.get("supporting_evidence_id"),
            }
            if verified.get("_verification_basis") == "econbiz_fulltext_evidence"
            else None
        ),
        "verified_via_website": verified_via_webpage,
        "enrichment": enrichment,
        "publication_year_assessment": verified.get("_publication_year_assessment"),
        "corrected_reference": None,
        "hallucination_assessment": None,
        "citation_contexts": cited.get("citation_contexts") or [],
        "citation_context": cited.get("citation_context"),
        "citation_count": cited.get("citation_count") or 0,
    }
    for source_key, destination_key in (
        ("title", "verified_title"), ("authors", "verified_authors"),
        ("year", "verified_year"), ("venue", "verified_venue"),
        ("doi", "verified_doi"), ("arxiv_id", "verified_arxiv_id"),
    ):
        if verified.get(source_key):
            result[destination_key] = verified[source_key]

    if any(warning.get("requires_user_confirmation") for warning in formatted_warnings):
        candidate = {
            key: verified[key]
            for key in ("title", "authors", "year", "venue", "doi", "arxiv_id")
            if verified.get(key) not in (None, "", [])
        }
        if candidate:
            result["corrected_reference"] = candidate

    if include_raw_errors:
        result["_raw_errors"] = findings
    return suppress_redundant_arxiv_suggestions(result, result)


# These must be removed before merging a fresh projection into a persisted row.
VERIFICATION_DERIVED_FIELDS = frozenset({
    "status", "errors", "warnings", "infos", "suggestions", "verified_url",
    "authoritative_urls", "matched_database", "matched_db", "verification_basis",
    "supporting_evidence", "verified_via_website", "enrichment",
    "publication_year_assessment", "corrected_reference", "hallucination_assessment",
    "hallucination_check_pending", "_raw_errors", "from_cache", "from_fuzzy_cache",
    "fuzzy_match_score", "verified_title", "verified_authors", "verified_year",
    "verified_venue", "verified_doi", "verified_arxiv_id", "verified_pmid",
})


def merge_fresh_verification(
    stored_reference: Dict[str, Any], projection: Dict[str, Any],
) -> Dict[str, Any]:
    """Replace all derived state while retaining stable citation/user fields."""
    merged = {
        key: value for key, value in dict(stored_reference or {}).items()
        if key not in VERIFICATION_DERIVED_FIELDS
    }
    merged.update(projection)
    # A stable database id/index belongs to the history record, not the result.
    for key in ("id", "index"):
        if key in stored_reference:
            merged[key] = stored_reference[key]
    return merged
