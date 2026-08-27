"""Shared authoritative-link projection for reference verification results."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from refchecker.utils.url_utils import construct_semantic_scholar_url


def build_authoritative_urls(
    reference: Dict[str, Any],
    verified_data: Optional[Dict[str, Any]],
    verification_url: Optional[str],
    *,
    status: str,
    verified_via_webpage: bool = False,
) -> List[Dict[str, str]]:
    """Return the matched-source URL plus real DOI, arXiv, and S2 identifiers."""
    urls: List[Dict[str, str]] = []

    if verified_via_webpage:
        cited_url = reference.get("cited_url") or reference.get("url") or verification_url
        if cited_url:
            urls.append({"type": "verified_url", "url": str(cited_url)})
    elif verification_url and not (status == "unverified" and not verified_data):
        url_text = str(verification_url)
        if "semanticscholar.org" in url_text:
            url_type = "semantic_scholar"
        elif "openalex.org" in url_text:
            url_type = "openalex"
        elif "crossref.org" in url_text or "doi.org" in url_text:
            url_type = "doi"
        elif "openreview.net" in url_text:
            url_type = "openreview"
        elif "arxiv.org" in url_text:
            url_type = "arxiv"
        else:
            url_type = "other"
        urls.append({"type": url_type, "url": url_text})

    if not isinstance(verified_data, dict):
        return urls

    external_ids = verified_data.get("externalIds") or {}
    if not isinstance(external_ids, dict):
        external_ids = {}

    def add(url_type: str, url: Optional[str]) -> None:
        if url and not any(item["url"] == url for item in urls):
            urls.append({"type": url_type, "url": url})

    arxiv_id = external_ids.get("ArXiv") or verified_data.get("arxiv_id")
    if arxiv_id:
        add("arxiv", f"https://arxiv.org/abs/{arxiv_id}")

    doi = external_ids.get("DOI") or verified_data.get("doi") or verified_data.get("DOI")
    if doi:
        add("doi", f"https://doi.org/{doi}")

    paper_id = external_ids.get("S2PaperId") or verified_data.get("paperId")
    if paper_id:
        add("semantic_scholar", construct_semantic_scholar_url(str(paper_id)))
    add("semantic_scholar", verified_data.get("_semantic_scholar_url"))
    return urls
