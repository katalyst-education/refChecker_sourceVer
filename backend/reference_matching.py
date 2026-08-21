"""Identity matching for references re-extracted from a source document."""

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    normalized = " ".join(str(value).split()).strip().casefold()
    return " ".join(re.findall(r"\w+", normalized, flags=re.UNICODE))


def _normalize_url(value: Any) -> str:
    if value is None:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except (TypeError, ValueError):
        return raw.rstrip("/").casefold()
    if not parsed.netloc:
        return raw.rstrip("/").casefold()
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.netloc.casefold()}{path}"


def _normalize_doi(value: Any) -> str:
    if value is None:
        return ""
    doi = str(value).strip().casefold()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi)
    doi = re.sub(r"^doi:\s*", "", doi)
    return doi.rstrip(".,; ")


def _author_identity(reference: Dict[str, Any]) -> set:
    authors = reference.get("authors") or []
    if isinstance(authors, str):
        authors = [authors]
    identities = set()
    for author in authors:
        if isinstance(author, dict):
            author = author.get("name") or " ".join(
                str(author.get(key) or "").strip()
                for key in ("givenName", "familyName")
            )
        normalized = _normalize_text(author)
        if normalized:
            identities.add(normalized)
    return identities


def find_reextracted_reference_index(
    extracted_references: list,
    target: Dict[str, Any],
    preferred_index: Optional[int] = None,
) -> Optional[int]:
    """Return the identity match for a selected stored reference.

    Re-extraction can omit or reorder citations, so array position is never
    sufficient evidence. Strong identifiers are tried first, followed by an
    exact punctuation-insensitive title match. Position is used only to break
    ties between candidates that already share a strong identity.
    """
    if not extracted_references:
        return None

    def unique_or_nearest(candidates: List[int]) -> Optional[int]:
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        target_year = str(target.get("year") or "").strip()
        target_authors = _author_identity(target)
        scored = []
        for candidate_index in candidates:
            candidate = extracted_references[candidate_index]
            score = 0
            candidate_year = str(candidate.get("year") or "").strip()
            if target_year and candidate_year and target_year == candidate_year:
                score += 2
            if target_authors.intersection(_author_identity(candidate)):
                score += 2
            distance = (
                abs(candidate_index - preferred_index)
                if preferred_index is not None else len(extracted_references)
            )
            scored.append((score, -distance, candidate_index))

        scored.sort(reverse=True)
        if len(scored) == 1 or scored[0][:2] != scored[1][:2]:
            return scored[0][2]
        return None

    target_doi = _normalize_doi(target.get("doi") or target.get("verified_doi"))
    if target_doi:
        doi_matches = [
            i for i, reference in enumerate(extracted_references)
            if _normalize_doi(
                reference.get("doi") or reference.get("verified_doi")
            ) == target_doi
        ]
        match = unique_or_nearest(doi_matches)
        if match is not None:
            return match

    target_urls = {
        normalized
        for key in ("url", "cited_url", "verified_url")
        if (normalized := _normalize_url(target.get(key)))
    }
    if target_urls:
        url_matches = []
        for i, reference in enumerate(extracted_references):
            candidate_urls = {
                normalized
                for key in ("url", "cited_url", "verified_url")
                if (normalized := _normalize_url(reference.get(key)))
            }
            if target_urls.intersection(candidate_urls):
                url_matches.append(i)
        match = unique_or_nearest(url_matches)
        if match is not None:
            return match

    target_title = _normalize_text(target.get("title"))
    if target_title:
        title_matches = [
            i for i, reference in enumerate(extracted_references)
            if _normalize_text(reference.get("title")) == target_title
        ]
        return unique_or_nearest(title_matches)

    return None
