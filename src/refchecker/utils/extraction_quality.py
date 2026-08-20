"""Shared quality gates and grounded candidate merging for reference extraction."""

import re
from typing import Any, Dict, List, Optional, Tuple


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
        for field in ('title', 'year', 'venue', 'journal', 'doi', 'arxiv_id', 'url', 'raw_text'):
            if not combined.get(field) and text_ref.get(field):
                combined[field] = text_ref[field]

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

    from refchecker.utils.text_utils import validate_parsed_references

    validation = validate_parsed_references(
        references,
        require_all=True,
        expected_count=expected_count,
    )
    return (references if validation['is_valid'] else []), expected_count
