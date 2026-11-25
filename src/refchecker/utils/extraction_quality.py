"""Shared quality gates and grounded candidate merging for reference extraction."""

from collections import defaultdict
import io
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from refchecker.utils.reference_metadata import (
    CITED_REFERENCE_FIELDS,
    attach_bibliography_sources,
    cited_metadata_snapshot,
    needs_pdf_layout_review,
    normalize_reference_fields,
    numbered_source_entries,
    reconcile_reference_source,
    record_extraction_change,
    record_extraction_source,
    repair_pdf_citation_wraps,
)
from refchecker.utils.publication_fields import PUBLICATION_FIELDS


logger = logging.getLogger(__name__)

_INLINE_ENTRY = re.compile(r'(?<=\d{4}\.)[ \t]+(?=\[(\d{1,4})\]\s+[^\W\d_])')
_CITATION_YEAR = re.compile(r'[,.(]\s*(?:19|20)\d{2}[a-z]?\s*[.)]')
_VENUE_TAIL = re.compile(r',\s*(?:vol\.|no\.|pp?\.)\s*\d', re.IGNORECASE)
_CONTINUATION = re.compile(r'^(?:vol\.|no\.|pp?\.|,|(?:19|20)\d{2}\.)', re.IGNORECASE)
_WRAPPED_HYPHEN = re.compile(r'(?<=\w)-\s+(?=\w)')
_WORD = re.compile(r'[^\W\d_]+')
_MAX_NUMBER_GAP = 3
_MISSING_TITLE = {'', 'Unknown Title', 'Untitled Reference'}


def _source_pages(raw, pages):
    lines = raw.splitlines()
    first = ' '.join(lines[0].split()) if lines else ''
    prefix = (first if len(first) >= 25 else ' '.join(raw.split()))[:100]
    return {index for index, page in enumerate(pages) if len(prefix) >= 25 and prefix in page}


def _text_key(value):
    return ''.join(character for character in value.casefold() if character.isalnum())


def _same_source_start(primary, alternate):
    """Allow different wrapping and truncation after the same citation start."""
    left, right = _text_key(primary), _text_key(alternate)
    length = min(len(left), len(right), 48)
    return length >= 20 and left[:length] == right[:length]


def _inline_source_entries(number, raw):
    """Identify joined sequential references with a citation ending before each label."""
    parts = {}
    start = 0
    for marker in _INLINE_ENTRY.finditer(raw):
        following = int(marker[1])
        if following != number + 1:
            continue
        parts[number] = raw[start:marker.start()].strip()
        number, start = following, marker.end()
    if parts:
        parts[number] = raw[start:].strip()
    return parts


def _needs_layout(reference, raw):
    authors = cited_metadata_snapshot(reference)['authors']
    title = reference.get('title') or ''
    words = _WORD.findall(' '.join([title, *authors]))
    return (
        needs_pdf_layout_review(reference)
        or title in _MISSING_TITLE
        or not authors or authors == ['Unknown Author']
        or not reference.get('year') and (bool(_CITATION_YEAR.search(raw)) or raw.endswith((',', '-', ';')))
        or not (reference.get('venue') or reference.get('journal')) and bool(_VENUE_TAIL.search(raw))
        or any(len(word) >= 25 or (len(word) >= 14 and len(re.findall(r'[a-z][A-Z]', word)) >= 2) for word in words)
    )


def _plan_layout_retry(references, bibliography, normalized_pages, requested):
    primary = defaultdict(list)
    for number, raw in numbered_source_entries(bibliography):
        primary[number].append(raw)
    by_number = defaultdict(list)
    for reference in references:
        number = reference.get('entry_number')
        if number is not None:
            by_number[number].append(reference)

    locations = {
        number: set().union(*(_source_pages(raw, normalized_pages) for raw in texts))
        for number, texts in primary.items()
    }
    targets = {}
    merged = {}
    for number, texts in primary.items():
        rows = by_number[number]
        if len(texts) != 1 or len(rows) != 1 or _needs_layout(rows[0], texts[0]):
            targets[number] = locations[number]
        if len(texts) == 1:
            parts = _inline_source_entries(number, texts[0])
            if parts:
                merged.update({label: part for label, part in parts.items() if label == number or label not in primary})
                for label in parts:
                    if label == number or label not in primary:
                        targets[label] = locations[number]

    gaps = {}
    numbers = list(primary)
    for left, right in zip(numbers, numbers[1:]):
        if len(primary[left]) != 1 or len(primary[right]) != 1 or not 1 < right - left <= _MAX_NUMBER_GAP + 1:
            continue
        bounds = locations[left] | locations[right]
        if len(locations[left]) == len(locations[right]) == 1 and max(bounds) - min(bounds) <= 1:
            for number in range(left + 1, right):
                if number not in primary:
                    targets[number] = bounds
                    gaps[number] = (left, right)

    if requested is not None:
        targets = {number: pages for number, pages in targets.items() if number in requested}

    # A damaged entry can continue onto the page headed by the next reference.
    for number, pages in targets.items():
        following = locations.get(number + 1)
        if len(pages) != 1 or not following or len(following) != 1 or min(following) != min(pages) + 1:
            continue
        texts = primary.get(number, [])
        if len(texts) == 1:
            raw = ' '.join(texts[0].split())
            if raw.endswith((',', '-', ';')) or raw not in normalized_pages[min(pages)]:
                targets[number] = pages | following
    return primary, by_number, targets, merged, gaps


def _read_pdf_layout(source, selected_pages):
    import pdfplumber

    pages = {}
    with pdfplumber.open(source) as document:
        for page in sorted(selected_pages):
            if page >= len(document.pages):
                continue
            try:
                pages[page] = document.pages[page].extract_text() or ''
            except Exception as exc:
                logger.debug('Could not read alternate PDF layout for page %d: %s', page + 1, exc)

    entries = defaultdict(list)
    for page, text in pages.items():
        parsed = list(numbered_source_entries(text))
        for position, (number, raw) in enumerate(parsed):
            if position == len(parsed) - 1 and not _CITATION_YEAR.search(raw):
                following_page = pages.get(page + 1, '')
                following = next(numbered_source_entries(following_page), None)
                if following and following[0] == number + 1:
                    continuation = following_page.split(following[1], 1)[0].strip()
                    if _CONTINUATION.match(continuation) and _CITATION_YEAR.search(continuation):
                        raw = raw + '\n' + continuation
            entries[number].append(((page, position), raw))
    return entries


def _parse_layout_entry(number, raw):
    from refchecker.utils.biblatex_parser import parse_biblatex_entry_content
    from refchecker.utils.text_utils import validate_parsed_references

    # This is one independently delimited entry. Use the same field parser
    # as the numbered bibliography parser, without its document-wide gate.
    candidate = parse_biblatex_entry_content(str(number), raw.partition(']')[2].strip())
    if not candidate or candidate.get('title', '') in _MISSING_TITLE:
        return None
    candidate['raw_text'] = raw
    attach_bibliography_sources([candidate], raw, 'regex')
    normalize_reference_fields(candidate)
    if validate_parsed_references([candidate], require_all=True)['is_valid']:
        return candidate
    return None


def _grounded_gap(number, position, gaps, primary, layout):
    if number not in gaps:
        return False
    left, right = gaps[number]
    for neighbor, sign in ((left, -1), (right, 1)):
        anchors = layout.get(neighbor, [])
        if len(anchors) != 1:
            return False
        anchor_position, anchor_text = anchors[0]
        ordered = anchor_position < position if sign == -1 else anchor_position > position
        if not ordered or not _same_source_start(primary[neighbor][0], anchor_text):
            return False
    return True


def _layout_field_repairs(reference, candidate, raw, *, split_entry=False):
    """Use the better layout to fill omissions or restore confirmed spacing."""
    provenance = record_extraction_source(reference, 'unknown')
    title = reference.get('title') or ''
    candidate_title = _WRAPPED_HYPHEN.sub('-', candidate['title'])
    title_matches = _text_key(title) == _text_key(candidate_title)
    if not title_matches and title not in _MISSING_TITLE and not split_entry:
        return

    layout_key = _text_key(raw)
    old_source_key = _text_key(provenance.get('source_text', ''))
    spill = old_source_key[len(layout_key):] if split_entry and old_source_key.startswith(layout_key) else ''
    before_names = cited_metadata_snapshot(reference)['authors']
    after_names = cited_metadata_snapshot(candidate)['authors']
    author_spacing = (
        [_text_key(name) for name in before_names] == [_text_key(name) for name in after_names]
        and sum(len(name.split()) for name in after_names) > sum(len(name.split()) for name in before_names)
    )
    for field in CITED_REFERENCE_FIELDS:
        before = reference.get(field)
        after = candidate_title if field == 'title' else candidate.get(field)
        value = _text_key(str(before)) if spill and isinstance(before, (str, int)) else ''
        from_joined_entry = bool(value and value in spill and value not in layout_key)
        if before == after or (not after and not from_joined_entry):
            continue
        if field in {'venue', 'journal'} and (reference.get('venue') or reference.get('journal')) and not before:
            continue
        improved = from_joined_entry or not before or field == 'authors' and (
            before == ['Unknown Author'] or author_spacing
        )
        if field == 'title' and after:
            improved |= title in _MISSING_TITLE or (
                title_matches and len(candidate_title.split()) > len(_WRAPPED_HYPHEN.sub('-', title).split())
            )
        if split_entry and isinstance(before, str) and field in {'title', 'venue', 'journal'} and after:
            improved |= bool(_text_key(after)) and _text_key(after) in _text_key(before)
        if improved:
            reference[field] = after
            provenance.get('review', {}).pop(field, None)
            provenance['layout_text'] = raw
            record_extraction_change(reference, field, before, after, 'pdf_layout')
    if split_entry:
        reference['raw_text'] = raw
        provenance['layout_text'] = raw


def _repair_layout_entries(references, layout, primary, by_number, targets, merged, gaps):
    # A provider can lack labels entirely. An addition in that case could
    # duplicate a genuine output row whose identity could not be aligned.
    allow_insert = all(reference.get('entry_number') is not None for reference in references)
    for number, pages in targets.items():
        alternatives = [(position, raw) for position, raw in layout.get(number, []) if position[0] in pages]
        if len(alternatives) != 1:
            continue
        position, raw = alternatives[0]
        if _inline_source_entries(number, raw):
            continue
        rows = by_number.get(number, [])
        source_texts = [merged[number]] if number in merged else primary.get(number, [])
        grounded = any(_same_source_start(text, raw) for text in source_texts)
        if not grounded and not _grounded_gap(number, position, gaps, primary, layout):
            continue
        candidate = _parse_layout_entry(number, raw)
        if candidate is None:
            continue
        if not rows and allow_insert:
            evidence = record_extraction_source(candidate, 'regex')
            evidence['pdf_page'] = position[0] + 1
            evidence['layout_recovered'] = True
            evidence['source_text'] = source_texts[0] if source_texts else raw
            if evidence['source_text'] != raw:
                evidence['layout_text'] = raw
            index = next((i for i, row in enumerate(references) if row['entry_number'] > number), len(references))
            references.insert(index, candidate)
        elif rows and _text_key(rows[0].get('title') or '') == _text_key(candidate['title']):
            first, *duplicates = rows
            if duplicates and all(cited_metadata_snapshot(row) == cited_metadata_snapshot(first) for row in duplicates):
                keep = next(i for i, row in enumerate(references) if row is first)
                references[:] = [row for i, row in enumerate(references) if i == keep or row.get('entry_number') != number]
                record_extraction_source(first, 'unknown')['layout_text'] = raw
        if len(rows) == 1 and source_texts:
            primary_key, layout_key = _text_key(source_texts[0]), _text_key(raw)
            extended = source_texts[0].endswith((',', '-', ';')) and layout_key.startswith(primary_key)
            if primary_key == layout_key or extended:
                _layout_field_repairs(rows[0], candidate, raw, split_entry=number in merged)


def ground_pdf_references(references, paper_text, *, pdf_path=None, pdf_content=None,
                          bibliography_text=None, extraction_mode='cascade', reference_numbers=None):
    """Record source locations and retry only PDF pages with evidence of extraction damage."""
    for reference in references:
        normalize_reference_fields(reference)
    pages = (paper_text or '').split('\f')
    if not paper_text:
        return references
    requested = set(reference_numbers) if reference_numbers is not None else None
    normalized_pages = [' '.join(page.split()) for page in pages]
    author_reviews = defaultdict(list)
    for reference in references:
        provenance = reference.get('extraction_provenance') or {}
        matches = _source_pages(provenance.get('source_text', ''), normalized_pages)
        if len(matches) != 1:
            continue
        page_index = next(iter(matches))
        provenance['pdf_page'] = page_index + 1
        number = provenance.get('entry_number')
        if number is not None and (requested is None or number in requested) and needs_pdf_layout_review(reference):
            author_reviews[page_index].append(reference)

    quality_check = bibliography_text and extraction_mode == 'cascade'
    selected = set(author_reviews)
    if quality_check:
        primary, by_number, targets, merged, gaps = _plan_layout_retry(
            references, bibliography_text, normalized_pages, requested,
        )
        selected.update(page for pages in targets.values() for page in pages)

    if not selected or (not pdf_path and pdf_content is None):
        repair_pdf_citation_wraps(references, paper_text)
        return references
    try:
        source = pdf_path or io.BytesIO(pdf_content.getvalue())
        layout = _read_pdf_layout(source, selected)
    except Exception as exc:
        logger.debug('Could not read alternate PDF layout for bibliography: %s', exc)
        repair_pdf_citation_wraps(references, paper_text)
        return references

    logger.debug('Retried bibliography extraction on PDF pages %s', [page + 1 for page in sorted(selected)])
    for page, rows in author_reviews.items():
        for reference in rows:
            entries = [raw for position, raw in layout.get(reference['entry_number'], []) if position[0] == page]
            if len(entries) == 1:
                reconcile_reference_source(reference, layout_text=entries[0])
    if quality_check:
        _repair_layout_entries(references, layout, primary, by_number, targets, merged, gaps)
    repair_pdf_citation_wraps(references, paper_text)
    return references


def _author_family_key(author: Any) -> str:
    text = re.sub(r"[^\w\s,'’-]", " ", str(author or ''), flags=re.UNICODE).strip().lower()
    if not text:
        return ''
    if ',' in text:
        return text.split(',', 1)[0].strip()
    parts = text.split()
    return parts[-1] if parts else ''


def merge_grounded_reference_candidates(
    structured: List[Dict[str, Any]],
    text_parsed: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge aligned PDF-derived candidates without using canonical metadata.

    GROBID remains primary.  The text parser can fill missing fields and restore
    a longer author list only when the candidates agree on title and first
    author.  If alignment is doubtful, the structured input is returned intact.
    """
    from refchecker.utils.text_utils import calculate_title_similarity

    if len(structured) != len(text_parsed):
        return structured

    merged = []
    for structured_ref, text_ref in zip(structured, text_parsed):
        left_title = structured_ref.get('title') or ''
        right_title = text_ref.get('title') or ''
        if left_title and right_title:
            similarity = calculate_title_similarity(left_title.lower(), right_title.lower())
            if similarity < 0.72:
                return structured

        combined = dict(structured_ref)
        record_extraction_source(combined, 'grobid')
        for field in ('title', 'year', 'venue', 'journal', 'doi', 'arxiv_id', 'url', 'raw_text', *PUBLICATION_FIELDS):
            if not combined.get(field) and text_ref.get(field):
                combined[field] = text_ref[field]
                if field != 'raw_text':
                    record_extraction_change(combined, field, structured_ref.get(field),
                                             combined[field], 'bibliography_parser')

        structured_authors = [
            author for author in (structured_ref.get('authors') or [])
            if str(author).strip()
        ]
        text_authors = [
            author for author in (text_ref.get('authors') or [])
            if str(author).strip()
        ]
        if not structured_authors and text_authors:
            combined['authors'] = text_authors
        elif len(text_authors) > len(structured_authors) and structured_authors:
            if _author_family_key(structured_authors[0]) == _author_family_key(text_authors[0]):
                combined['authors'] = text_authors
        record_extraction_change(combined, 'authors', structured_ref.get('authors'),
                                 combined.get('authors'), 'bibliography_parser')
        merged.append(combined)
    return merged


def strict_numbered_text_candidate(
    checker: Any,
    bibliography_text: Optional[str],
) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    """Return a complete, strictly valid deterministic numbered parse."""
    if not bibliography_text:
        return [], None
    numbered_entries = checker._split_numbered_reference_entries(bibliography_text)
    expected_count = len(numbered_entries) or None
    if not expected_count:
        return [], None

    references = checker._parse_references_regex('\n'.join(numbered_entries))
    if not references:
        return [], expected_count
    attach_bibliography_sources(references, bibliography_text, 'regex')

    from refchecker.utils.text_utils import validate_parsed_references

    validation = validate_parsed_references(
        references,
        require_all=True,
        expected_count=expected_count,
    )
    return (references if validation['is_valid'] else []), expected_count
