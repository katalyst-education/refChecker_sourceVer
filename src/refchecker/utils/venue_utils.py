#!/usr/bin/env python3
"""Shared helpers for venue extraction and DOI-backed venue fallback."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from refchecker.utils.doi_utils import extract_doi_from_url
from refchecker.utils.text_utils import are_venues_substantially_different

logger = logging.getLogger(__name__)


def get_semantic_scholar_venue(paper_data: Dict[str, Any]) -> Optional[str]:
    """Extract the best available venue from a Semantic Scholar-style payload."""
    if not paper_data:
        return None

    paper_venue = None
    if paper_data.get('venue'):
        paper_venue = paper_data.get('venue')

    if not paper_venue and paper_data.get('publicationVenue'):
        pub_venue = paper_data.get('publicationVenue')
        if isinstance(pub_venue, dict):
            paper_venue = pub_venue.get('name', '')
        elif isinstance(pub_venue, str):
            paper_venue = pub_venue

    if not paper_venue and paper_data.get('journal'):
        journal = paper_data.get('journal')
        if isinstance(journal, dict):
            paper_venue = journal.get('name', '')
        elif isinstance(journal, str):
            paper_venue = journal

    if paper_venue and not isinstance(paper_venue, str):
        paper_venue = str(paper_venue)

    return paper_venue.strip() if isinstance(paper_venue, str) and paper_venue.strip() else None


def get_crossref_venue(work_data: Dict[str, Any]) -> Optional[str]:
    """Extract the most useful venue name from a CrossRef work payload."""
    if not work_data:
        return None

    container_title = work_data.get('container-title')
    if isinstance(container_title, list):
        for title in container_title:
            if isinstance(title, str) and title.strip():
                return title.strip()
    elif isinstance(container_title, str) and container_title.strip():
        return container_title.strip()

    short_container_title = work_data.get('short-container-title')
    if isinstance(short_container_title, list):
        for title in short_container_title:
            if isinstance(title, str) and title.strip():
                return title.strip()
    elif isinstance(short_container_title, str) and short_container_title.strip():
        return short_container_title.strip()

    event = work_data.get('event')
    if isinstance(event, dict):
        event_name = event.get('name')
        if isinstance(event_name, str) and event_name.strip():
            return event_name.strip()

    return None


def get_reference_doi(reference: Dict[str, Any], paper_data: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Return the cited DOI first, then fall back to the verified paper DOI."""
    doi = reference.get('doi')
    if doi:
        return doi

    for url_key in ('url', 'cited_url'):
        url = reference.get(url_key, '')
        doi = extract_doi_from_url(url)
        if doi:
            return doi

    external_ids = (paper_data or {}).get('externalIds', {})
    if isinstance(external_ids, dict):
        return external_ids.get('DOI')

    return None


def lookup_venue_via_doi(
    reference: Dict[str, Any],
    paper_data: Optional[Dict[str, Any]] = None,
    cache_dir: Optional[str] = None,
) -> Optional[str]:
    """Load CrossRef metadata for the DOI associated with a reference."""
    doi = get_reference_doi(reference, paper_data)
    if not doi:
        return None

    try:
        from refchecker.checkers.crossref import CrossRefReferenceChecker

        checker = CrossRefReferenceChecker()
        checker.cache_dir = cache_dir
        work_data = checker.get_work_by_doi(doi)
        return get_crossref_venue(work_data)
    except Exception as exc:
        logger.debug("DOI venue lookup failed for %s: %s", doi, exc)
        return None


def resolve_venue_for_validation(
    cited_venue: str,
    primary_venue: Optional[str],
    reference: Dict[str, Any],
    paper_data: Optional[Dict[str, Any]] = None,
    cache_dir: Optional[str] = None,
) -> Tuple[Optional[str], bool]:
    """Choose the venue to validate against.

    The primary verification source still wins when it already matches the cited
    venue. Otherwise, if the citation carries a DOI and CrossRef provides a
    venue, that DOI-backed venue becomes the validation source.
    """
    if cited_venue and primary_venue and not are_venues_substantially_different(cited_venue, primary_venue):
        return primary_venue, False

    doi_venue = lookup_venue_via_doi(reference, paper_data=paper_data, cache_dir=cache_dir)
    if doi_venue:
        return doi_venue, True

    return primary_venue, False
