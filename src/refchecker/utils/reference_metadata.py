"""Citation identity and evidence from the bibliography."""

from collections import Counter, defaultdict
from copy import deepcopy
import re
import unicodedata


_CITATION_FIELDS = (
    'title', 'year', 'doi', 'arxiv_id', 'pmid', 'volume', 'issue', 'pages',
    'publisher', 'isbn', 'issn', 'edition',
)
CITED_REFERENCE_FIELDS = _CITATION_FIELDS + ('authors', 'venue', 'journal', 'url', 'cited_url')
REFERENCE_SOURCE_FIELDS = ('raw_text', 'entry_number', 'extraction_provenance')

_NUMBERED_ENTRY = re.compile(r'(?m)^[ \t]*\[(\d{1,4})\][ \t]*')
_QUOTED_TITLE = re.compile(r'^([^"“”]+?)[ \t\n]*[“"]([^"“”]+)[”"]')
_LABELED_VENUE = re.compile(
    r'^\s*[,.;]?\s*(?:in\s+)?([^,]+),\s*(?:vol\.|no\.|pp?\.)\s*\d',
    re.IGNORECASE,
)
_INITIAL = r'[^\W\d_]\.'
_INITIAL_SPACING = re.compile(rf'\b({_INITIAL})\s*(?=[^\W\d_])')
_INITIALLED_NAME = re.compile(
    rf'(?:{_INITIAL}(?:-{_INITIAL})?\s*)+\s+[^\W\d_][\w\s\-’\']*',
)
_FUSED_INITIALS = re.compile(rf'\b{_INITIAL}(?:-{_INITIAL})*(?=[^\W\d_])')
_MISSING_AUTHOR = {'', 'unknown author', 'unknown', 'n/a'}


def _text(value):
    return ' '.join(str(value).split()) if value is not None else ''


def _authors(reference):
    authors = reference.get('authors') or []
    if isinstance(authors, str):
        authors = [authors]
    return [
        _text(author.get('name') or ' '.join(
            _text(author.get(field)) for field in ('givenName', 'familyName')
        )) if isinstance(author, dict) else _text(author)
        for author in authors
    ]


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
    result['authors'] = [
        _INITIAL_SPACING.sub(r'\1 ', author)
        for author in _authors(reference)
    ]
    return result


def cited_metadata_changed(previous, extracted):
    """Return whether any cited bibliographic field changed during extraction."""
    return cited_metadata_snapshot(previous) != cited_metadata_snapshot(extracted)


def normalize_reference_fields(reference):
    """Use the canonical venue slot and lift identifiers from cited text."""
    if reference.get('journal') and not reference.get('venue'):
        reference['venue'] = reference['journal']

    text = [reference.get(field) for field in ('cited_url', 'url', 'raw_text', 'raw')]
    text = [value for value in text if isinstance(value, str) and value]
    if not reference.get('doi'):
        for value in text:
            match = re.search(r'10\.\d{4,9}/[\w.\-;()/:%]+', value)
            if match:
                reference['doi'] = match[0].rstrip('.,;)')
                break
    if not reference.get('arxiv_id'):
        for value in text:
            match = re.search(r'arxiv\.org/abs/([\w.\-/]+)', value, re.IGNORECASE)
            if match:
                reference['arxiv_id'] = re.sub(r'v\d+$', '', match[1].rstrip('.,;)'))
                break
            match = re.search(r'arxiv[: ]\s*(\d{4}\.\d{4,5})', value, re.IGNORECASE)
            if match:
                reference['arxiv_id'] = match[1]
                break
    return reference


def numbered_source_entries(text):
    """Yield the printed label and original text of each numbered entry."""
    matches = list(_NUMBERED_ENTRY.finditer(text or ''))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        yield int(match[1]), text[match.start():end].strip()


def record_extraction_source(reference, parser, *, source_text=None, entry_number=None):
    """Capture the parser output before source-backed repairs are applied."""
    provenance = reference.get('extraction_provenance')
    if provenance is None:
        provenance = {
            'parser': parser,
            'parsed_fields': {
                field: deepcopy(reference[field])
                for field in CITED_REFERENCE_FIELDS if field in reference
            },
        }
        reference['extraction_provenance'] = provenance
    if source_text:
        provenance['source_text'] = source_text
    if entry_number is not None:
        reference['entry_number'] = entry_number
        provenance['entry_number'] = entry_number
    return provenance


def record_extraction_change(reference, field, before, after, reason):
    """Record an actual field change and its origin."""
    if before != after:
        reference['extraction_provenance'].setdefault('repairs', []).append({
            'field': field, 'before': deepcopy(before), 'after': deepcopy(after),
            'reason': reason,
        })


def _compact(value):
    return ''.join(unicodedata.normalize('NFC', value).split()).casefold()


def _title_key(value):
    return ''.join(character for character in _compact(value) if character.isalnum())


def _quoted_parts(raw_text):
    content = _NUMBERED_ENTRY.sub('', raw_text.lstrip(), count=1)
    match = _QUOTED_TITLE.match(content)
    if match:
        return match[1].strip().rstrip(',').strip(), match[2].strip().rstrip(',').strip(), content[match.end():]
    return '', '', ''


def _review_field(provenance, field, parsed, source):
    provenance.setdefault('review', {})[field] = {
        'parsed': deepcopy(parsed), 'source': deepcopy(source),
    }


def reconcile_reference_source(reference, *, layout_text=None):
    """Use explicit citation boundaries to repair fields and surface uncertainty.

    The quoted title anchors the author prefix and the labeled journal segment.
    An alternate PDF layout may supply spacing when its author characters agree
    with the primary source. Competing readings are kept together for review.
    """
    provenance = reference['extraction_provenance']
    raw_text = provenance.get('source_text', '')
    prefix, title, tail = _quoted_parts(raw_text)
    if not title or _title_key(title) != _title_key(reference.get('title') or ''):
        if title and prefix and provenance.get('entry_number') is not None:
            _review_field(provenance, 'title', reference.get('title'), title)
        return reference

    parsed_title = reference['title']
    source_title = _text(title)
    if _compact(source_title) == _compact(parsed_title) and len(source_title.split()) > len(parsed_title.split()):
        reference['title'] = source_title
        record_extraction_change(reference, 'title', parsed_title, source_title, 'bibliography_title')

    before = _authors(reference)
    author_source = prefix
    if layout_text:
        layout_prefix, layout_title, _ = _quoted_parts(layout_text)
        if _title_key(layout_title) == _title_key(title) and layout_prefix != prefix:
            provenance['layout_text'] = layout_text
            if _compact(layout_prefix) == _compact(prefix):
                author_source = layout_prefix
                provenance.get('review', {}).pop('authors', None)
            else:
                _review_field(provenance, 'authors', before, layout_prefix)

    authors = re.split(r'\s*,\s*(?:and\s+)?|\s+(?:and|&)\s+', _text(author_source))
    initialled = bool(author_source) and all(_INITIALLED_NAME.fullmatch(author) for author in authors)
    review = provenance.get('review', {})
    if initialled and 'authors' not in review:
        missing = not before or all(name.casefold() in _MISSING_AUTHOR for name in before)
        same_names = [_compact(name) for name in before] == [_compact(name) for name in authors]
        same_printed_text = _compact(','.join(before)) == _compact(author_source)
        if missing or ((same_names or same_printed_text) and before != authors):
            prior = reference.get('authors')
            reference['authors'] = authors
            record_extraction_change(reference, 'authors', prior, authors,
                                     'pdf_layout' if author_source != prefix else 'bibliography_authors')
        elif not same_names:
            from refchecker.utils.text_utils import enhanced_name_match

            if len(before) != len(authors) or not all(
                enhanced_name_match(old, new) for old, new in zip(before, authors)
            ):
                _review_field(provenance, 'authors', before, authors)
    elif _FUSED_INITIALS.search(prefix) and 'authors' not in review:
        _review_field(provenance, 'authors', before, prefix)

    venue_match = _LABELED_VENUE.match(tail)
    if venue_match:
        venue = _text(venue_match[1])
        current = reference.get('venue') or reference.get('journal') or ''
        if not current or (len(title) >= 12 and _title_key(title) in _title_key(current)):
            reference['venue'] = venue
            if 'journal' in reference:
                reference['journal'] = venue
            record_extraction_change(reference, 'venue', current, venue, 'bibliography_venue')
        elif _title_key(venue) != _title_key(current) and len(venue.split()) > 1:
            _review_field(provenance, 'venue', current, venue)
    return reference


def attach_bibliography_sources(references, bibliography_text, parser):
    """Attach source entries by unique citation label or quoted title."""
    by_number = defaultdict(list)
    by_title = defaultdict(list)
    for number, raw in numbered_source_entries(bibliography_text):
        by_number[number].append(raw)
        _, title, _ = _quoted_parts(raw)
        if title:
            by_title[_title_key(title)].append((number, raw))

    title_keys = [_title_key(reference.get('title') or '') for reference in references]
    parsed_title_counts = Counter(title_keys)
    for reference, title_key in zip(references, title_keys):
        provenance = reference.get('extraction_provenance') or {}
        if provenance.get('source_text'):
            continue
        raw = reference.get('raw_text') or ''
        label = _NUMBERED_ENTRY.match(raw)
        number = reference.get('entry_number') or (int(label[1]) if label else None)
        entries = by_number.get(number, [])
        title_entries = by_title.get(title_key, [])
        if len(entries) == 1 and (parser != 'llm' or raw == entries[0]):
            source = entries[0]
        elif (len(title_entries) == 1 and parsed_title_counts[title_key] == 1
              and (number is None or number == title_entries[0][0])):
            number, source = title_entries[0]
        elif parser in {'bib', 'bbl', 'grobid', 'regex'}:
            source = raw
        else:
            source = None
        record_extraction_source(reference, parser, source_text=source,
                                 entry_number=number if source else None)
        if source:
            reconcile_reference_source(reference)
    return references


def needs_pdf_layout_review(reference):
    """Select entries whose author spacing is uncertain in the text layer."""
    provenance = reference.get('extraction_provenance') or {}
    prefix, _, _ = _quoted_parts(provenance.get('source_text', ''))
    return bool(_FUSED_INITIALS.search(prefix) and 'authors' in provenance.get('review', {}))
