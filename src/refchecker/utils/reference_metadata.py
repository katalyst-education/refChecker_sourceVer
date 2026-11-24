"""Snapshots of cited metadata for deciding whether verification needs a refresh."""


_CITATION_FIELDS = (
    'title', 'year', 'doi', 'arxiv_id', 'pmid', 'volume', 'issue', 'pages',
    'publisher', 'isbn', 'issn', 'edition',
)
CITED_REFERENCE_FIELDS = _CITATION_FIELDS + ('authors', 'venue', 'journal', 'url', 'cited_url')


def _text(value):
    return ' '.join(str(value).split()) if value is not None else ''


def cited_metadata_snapshot(reference):
    """Represent citation values consistently across extracted and saved rows.

    Venue and URL aliases share a slot. Empty values and author representations
    are normalized; case, punctuation, author order, and cited values survive.
    Parser bookkeeping, raw source layout, and verification results have their
    own lifecycles and are excluded from this citation snapshot.
    """
    result = {field: _text(reference.get(field)) for field in _CITATION_FIELDS}
    result['venue'] = sorted({_text(reference.get(field)) for field in ('venue', 'journal')} - {''})
    result['url'] = sorted({_text(reference.get(field)) for field in ('cited_url', 'url')} - {''})
    authors = reference.get('authors') or []
    if isinstance(authors, str):
        authors = [authors]
    result['authors'] = [
        _text(author.get('name') or ' '.join(
            _text(author.get(field)) for field in ('givenName', 'familyName')
        )) if isinstance(author, dict) else _text(author)
        for author in authors
    ]
    return result


def cited_metadata_changed(previous, extracted):
    """Return whether any cited bibliographic field changed during extraction."""
    return cited_metadata_snapshot(previous) != cited_metadata_snapshot(extracted)
