"""Shared policy for optional reference-metadata suggestions."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from refchecker.utils.doi_utils import reference_has_doi
from refchecker.utils.url_utils import extract_arxiv_id_from_url


def _normalize_arxiv_id(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    from_url = extract_arxiv_id_from_url(text)
    if from_url:
        return from_url.lower()
    lowered = text.lower()
    if lowered.startswith("arxiv:"):
        lowered = lowered[len("arxiv:"):]
    import re
    lowered = re.sub(r"v\d+$", "", lowered)
    return lowered or None


def reference_cites_arxiv(reference: Mapping[str, Any], arxiv_id: Any) -> bool:
    """Return whether the citation already names the expected arXiv work."""
    expected = _normalize_arxiv_id(arxiv_id)
    if not expected or not reference:
        return False

    for key in ("url", "cited_url", "eprint", "arxiv_id"):
        if _normalize_arxiv_id(reference.get(key)) == expected:
            return True
    return False


def should_suggest_arxiv_url(reference: Mapping[str, Any], arxiv_id: Any) -> bool:
    """An arXiv URL is useful only when neither a DOI nor that arXiv ID is cited."""
    return bool(
        _normalize_arxiv_id(arxiv_id)
        and not reference_has_doi(reference)
        and not reference_cites_arxiv(reference, arxiv_id)
    )


def _suggested_arxiv_id(item: Any) -> Optional[str]:
    if not isinstance(item, Mapping):
        return None
    details = (
        item.get("suggestion_details")
        or item.get("info_details")
        or item.get("message")
        or ""
    )
    if "arxiv url" not in str(details).lower():
        return None
    return _normalize_arxiv_id(details)


def suppress_redundant_arxiv_suggestions(
    result: Mapping[str, Any],
    cited_reference: Mapping[str, Any],
) -> Dict[str, Any]:
    """Remove stale cached arXiv suggestions already satisfied by the citation."""
    cleaned = dict(result)

    def keep(item: Any) -> bool:
        suggested_id = _suggested_arxiv_id(item)
        if not suggested_id:
            return True
        return should_suggest_arxiv_url(cited_reference, suggested_id)

    for key in ("suggestions", "_raw_errors"):
        items = cleaned.get(key)
        if isinstance(items, list):
            cleaned[key] = [item for item in items if keep(item)]

    if (
        str(cleaned.get("status") or "").lower() == "suggestion"
        and not cleaned.get("suggestions")
        and not cleaned.get("errors")
        and not cleaned.get("warnings")
    ):
        cleaned["status"] = "verified"

    return cleaned
