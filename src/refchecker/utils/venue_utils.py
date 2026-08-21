#!/usr/bin/env python3
"""Shared helpers for venue extraction and DOI-backed venue fallback."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from refchecker.utils.doi_utils import extract_doi_from_url
from refchecker.utils.text_utils import are_venues_substantially_different

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PublicationTypeResolution:
    """Canonical publication type together with its evidence quality."""

    publication_type: str
    confidence: str
    source: str
    raw_type: Optional[str] = None


_TYPE_ALIASES = {
    'book': 'whole-book',
    'monograph': 'whole-book',
    'edited-book': 'whole-book',
    'reference-book': 'whole-book',
    'booklet': 'whole-book',
    'book-chapter': 'book-chapter',
    'book-section': 'book-chapter',
    'booksection': 'book-chapter',
    'chapter': 'book-chapter',
    'inbook': 'book-chapter',
    'incollection': 'book-chapter',
    'journal-article': 'journal-article',
    'journalarticle': 'journal-article',
    'article': 'journal-article',
    'conference': 'conference-paper',
    'conference-paper': 'conference-paper',
    'proceedings-article': 'conference-paper',
    'inproceedings': 'conference-paper',
    'incproceedings': 'conference-paper',
    'proceedings': 'conference-paper',
    'posted-content': 'preprint',
    'preprint': 'preprint',
    'thesis': 'thesis',
    'dissertation': 'thesis',
    'mastersthesis': 'thesis',
    'phdthesis': 'thesis',
}


def _canonical_publication_type(value: Any) -> Optional[Tuple[str, str]]:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    normalized = raw.lower().replace('_', '-').replace(' ', '-')
    canonical = _TYPE_ALIASES.get(normalized)
    return (canonical, raw) if canonical else None


def _iter_type_values(value: Any):
    if isinstance(value, (list, tuple, set)):
        yield from value
    else:
        yield value


def resolve_publication_type(
    reference: Optional[Dict[str, Any]] = None,
    verified_data: Optional[Dict[str, Any]] = None,
    crossref_data: Optional[Dict[str, Any]] = None,
) -> PublicationTypeResolution:
    """Classify a work without requiring an ISBN.

    Authoritative database types win, followed by structured citation types and
    finally bibliographic field evidence.  The result is deliberately explicit
    about uncertainty so callers do not turn a guess into a correction.
    """
    reference = reference if isinstance(reference, dict) else {}
    verified_data = verified_data if isinstance(verified_data, dict) else {}
    crossref_data = crossref_data if isinstance(crossref_data, dict) else {}

    evidence = [
        ('crossref.type', crossref_data.get('type'), 'high'),
        ('verified.type', verified_data.get('type'), 'high'),
        ('semantic_scholar.publicationTypes', verified_data.get('publicationTypes'), 'high'),
        ('citation.bibtex_type', reference.get('bibtex_type'), 'high'),
        ('citation.publication_type', reference.get('publication_type'), 'medium'),
        ('citation.media_type', reference.get('media_type'), 'medium'),
    ]
    for source, values, confidence in evidence:
        for value in _iter_type_values(values):
            resolved = _canonical_publication_type(value)
            if resolved:
                canonical, raw = resolved
                return PublicationTypeResolution(canonical, confidence, source, raw)

    # An ISBN is useful corroboration, but it is intentionally not required.
    if reference.get('isbn') or reference.get('ISBN'):
        return PublicationTypeResolution('whole-book', 'medium', 'citation.isbn', 'ISBN')

    publisher = str(reference.get('publisher') or '').strip()
    container = str(
        reference.get('booktitle') or reference.get('container_title') or ''
    ).strip()
    if publisher and not container:
        return PublicationTypeResolution('whole-book', 'medium', 'citation.publisher', publisher)

    return PublicationTypeResolution('unknown', 'low', 'none')


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
    """Extract the citation field comparable to ``venue`` from CrossRef.

    For a whole book, the citation field stored as ``venue`` by RefChecker is
    normally the publisher.  CrossRef's ``container-title`` is instead often
    the series containing that book, so preferring it produces a false venue
    correction.  Chapters still use their containing book title.
    """
    if not work_data:
        return None

    resolution = resolve_publication_type(crossref_data=work_data)
    if resolution.publication_type == 'whole-book':
        publisher = work_data.get('publisher')
        if isinstance(publisher, str) and publisher.strip():
            return publisher.strip()

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


def get_crossref_venue_candidates(
    work_data: Dict[str, Any],
    resolution: Optional[PublicationTypeResolution] = None,
) -> list[str]:
    """Return type-appropriate values that can legitimately fill venue."""
    if not isinstance(work_data, dict) or not work_data:
        return []
    resolution = resolution or resolve_publication_type(crossref_data=work_data)

    def values(key: str) -> list[str]:
        value = work_data.get(key)
        raw_values = value if isinstance(value, list) else [value]
        return [item.strip() for item in raw_values if isinstance(item, str) and item.strip()]

    publisher = values('publisher')
    containers = values('container-title') or values('short-container-title')
    event = work_data.get('event')
    events = values('event') if isinstance(event, str) else []
    if isinstance(event, dict):
        name = event.get('name')
        events = [name.strip()] if isinstance(name, str) and name.strip() else []

    if resolution.publication_type == 'whole-book':
        return publisher
    if resolution.publication_type == 'book-chapter':
        return containers
    if resolution.publication_type == 'conference-paper':
        return containers + [item for item in events if item not in containers]
    if resolution.publication_type == 'journal-article':
        return containers
    if resolution.publication_type == 'unknown':
        # These fields have different meanings when type is unknown.  They may
        # suppress a false mismatch if the citation matches one, but must never
        # be presented as an authoritative correction.
        return publisher + [item for item in containers + events if item not in publisher]
    return containers or events


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

    work_data = lookup_crossref_work_via_doi(
        reference, paper_data=paper_data, cache_dir=cache_dir
    )
    return get_crossref_venue(work_data) if isinstance(work_data, dict) else None


def lookup_crossref_work_via_doi(
    reference: Dict[str, Any],
    paper_data: Optional[Dict[str, Any]] = None,
    cache_dir: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Load the complete CrossRef record used for type-aware validation."""
    doi = get_reference_doi(reference, paper_data)
    if not doi:
        return None

    try:
        from refchecker.checkers.crossref import CrossRefReferenceChecker

        checker = CrossRefReferenceChecker()
        checker.cache_dir = cache_dir
        work_data = checker.get_work_by_doi(doi)
        return work_data if isinstance(work_data, dict) else None
    except Exception as exc:
        logger.debug("DOI metadata lookup failed for %s: %s", doi, exc)
        return None


def resolve_venue_for_validation(
    cited_venue: str,
    primary_venue: Optional[str],
    reference: Dict[str, Any],
    paper_data: Optional[Dict[str, Any]] = None,
    cache_dir: Optional[str] = None,
) -> Tuple[Optional[str], bool]:
    """Choose the venue to validate against.

    The primary verification source still wins when it already matches.  When
    it does not, database and structured citation types determine whether venue
    means publisher, containing book, journal, or proceedings.  Unknown DOI
    types may suppress a mismatch but never supply a claimed correction.
    """
    if cited_venue and primary_venue and not are_venues_substantially_different(cited_venue, primary_venue):
        return primary_venue, False

    crossref_data = lookup_crossref_work_via_doi(
        reference, paper_data=paper_data, cache_dir=cache_dir
    )
    if not isinstance(crossref_data, dict):
        crossref_data = None
    resolution = resolve_publication_type(reference, paper_data, crossref_data)
    candidates = get_crossref_venue_candidates(crossref_data or {}, resolution)
    for candidate in candidates:
        if cited_venue and not are_venues_substantially_different(cited_venue, candidate):
            return candidate, True

    if resolution.publication_type == 'unknown' and crossref_data:
        return (cited_venue or None), True
    if candidates and resolution.confidence in {'high', 'medium'}:
        return candidates[0], True

    # A verified whole-book classification without publisher metadata means the
    # primary source's venue is commonly only a series title.  It is not a safe
    # correction for either a present or missing publisher citation.
    if resolution.publication_type == 'whole-book':
        return (cited_venue or None), False

    return primary_venue, False
