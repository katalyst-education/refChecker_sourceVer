"""Shared quality gates and grounded candidate merging for reference extraction."""

import io
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from refchecker.utils.reference_metadata import (
    attach_bibliography_sources,
    needs_pdf_layout_review,
    numbered_source_entries,
    reconcile_reference_source,
    record_extraction_change,
    record_extraction_source,
)


logger = logging.getLogger(__name__)


def ground_pdf_references(references, paper_text, *, pdf_path=None, pdf_content=None):
    """Locate exact source entries and read page layout for fused author text."""
    pages = (paper_text or '').split('\f')
    if not paper_text or not references:
        return references
    normalized_pages = [' '.join(page.split()) for page in pages]
    selected = {}
    for reference in references:
        provenance = reference.get('extraction_provenance') or {}
        raw = provenance.get('source_text', '')
        lines = raw.splitlines()
        first_line = ' '.join(lines[0].split()) if lines else ''
        prefix = (first_line if len(first_line) >= 25 else ' '.join(raw.split()))[:100]
        if len(prefix) < 25:
            continue
        matches = [i for i, page in enumerate(normalized_pages) if prefix in page]
        if len(matches) != 1:
            continue
        page_index = matches[0]
        provenance['pdf_page'] = page_index + 1
        if provenance.get('entry_number') is not None and needs_pdf_layout_review(reference):
            selected.setdefault(page_index, []).append(reference)

    if not selected or (not pdf_path and pdf_content is None):
        return references
    try:
        import pdfplumber

        source = pdf_path or io.BytesIO(pdf_content.getvalue())
        with pdfplumber.open(source) as document:
            for page_index, page_references in selected.items():
                if page_index >= len(document.pages):
                    continue
                page = document.pages[page_index]
                entries = dict(numbered_source_entries(page.extract_text()))
                for reference in page_references:
                    layout_text = entries.get(reference['entry_number'])
                    if layout_text:
                        reconcile_reference_source(reference, layout_text=layout_text)
    except Exception as exc:
        logger.debug('Could not read alternate PDF layout for bibliography: %s', exc)
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
        for field in ('title', 'year', 'venue', 'journal', 'doi', 'arxiv_id', 'url', 'raw_text'):
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
