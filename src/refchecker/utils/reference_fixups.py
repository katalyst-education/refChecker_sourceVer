"""Post-parse corrections applied to every extracted reference.

Reference extraction — especially LLM extraction — routinely puts fields in the
wrong slots: the venue lands in the title, the author list lands in the title,
or the whole remainder of the raw citation lands in the venue. These fixups
repair those field swaps before any comparison runs.

They live here, outside any one checker, because all three execution paths
(bulk, CLI and WebUI) must apply them identically. They previously lived on
``ArxivReferenceChecker``, which the WebUI never calls — so the WebUI skipped
them entirely and showed the citation title twice on affected references.

Every function is **idempotent**: applying it to an already-corrected reference
is a no-op, so it is safe to call at more than one point in a pipeline.
"""

import re

# A venue never contains a quoted span; a citation tail always does.
VENUE_TAIL_QUOTES = '"\u201c\u201d\u2018\u2019\u00ab\u00bb'

_VENUE_AS_TITLE_PATTERNS = [
    r'^Proceedings of the\b',
    r'^Proc\.\s',
    r'^Journal of [A-Z]',
    r'^Transactions on\b',
    r'^Advances in\s+Neural Information Processing',
    r'^International Conference on\b',
    r'^Annual Meeting of\b',
    r'^IEEE/CVF\b',
    r'^ACM\s+(SIGKDD|SIGMOD|SIGIR|SIGCHI|SIGPLAN|SIGGRAPH)\b',
]

_TITLE_WORDS = {
    'the', 'a', 'an', 'for', 'and', 'with', 'via', 'from', 'is', 'are', 'of',
    'in', 'on', 'to', 'by', 'all', 'you', 'we', 'it', 'its', 'as', 'or', 'not',
    'can', 'how', 'do', 'at', 'no', 'learning', 'model', 'network', 'data',
    'analysis', 'method', 'approach', 'based', 'neural', 'deep', 'training',
    'using', 'towards', 'evaluation', 'efficient', 'language', 'generation',
    'detection', 'beyond', 'what', 'why', 'when', 'where',
}

_VENUE_WORD_PATTERN = re.compile(
    r'\b(?:conference|workshop|symposium|journal|proceedings|meeting|transactions)\b',
    re.IGNORECASE,
)
_ACRONYM_YEAR_PATTERN = re.compile(
    r"\b(?P<acronym>[A-Za-z][A-Za-z0-9&.-]{1,14})\s*\\?['\u2019\u2018`\u00b4]\s*\d{1,2}\b"
)
_ACRONYM_YEAR_ONLY_PATTERN = re.compile(
    r"^\s*\(?\s*(?P<acronym>[A-Za-z][A-Za-z0-9&.-]{1,14})\s*"
    r"\\?['\u2019\u2018`\u00b4]\s*\d{1,2}\s*\\?\)?\s*$"
)
_LEADING_SHORT_YEAR_FRAGMENT = re.compile(
    r"^\s*[\\'\u2019\u2018`\u00b4]*\d{1,2}\s*\\?[\)\]}]"
)


def is_suspicious_venue(venue):
    """Return whether an extracted venue is clearly unusable metadata.

    This deliberately catches only high-confidence parser damage: fields with
    fewer than two letters, and fields beginning with a two-digit year fragment
    plus a closing delimiter (for example ``08\\)``). Legitimate numbered
    venues such as ``3DV`` and ``2024 Conference on ...`` remain untouched.
    """
    if not isinstance(venue, str):
        return False

    venue = venue.strip()
    if not venue:
        return False

    if _LEADING_SHORT_YEAR_FRAGMENT.search(venue):
        return True

    return len(re.findall(r'[A-Za-z]', venue)) < 2


def _parenthesized_venue_name(text):
    """Extract a full venue name stranded inside parentheses, if present."""
    for candidate in re.findall(r'\(([^()]*)\)', text or ''):
        candidate = candidate.strip().strip(',;.').strip()
        if len(re.findall(r'[A-Za-z]', candidate)) >= 4 and _VENUE_WORD_PATTERN.search(candidate):
            return candidate
    return ''


def _acronym_from_match(match):
    """Return a plausible all/mixed-case acronym captured by ``match``."""
    if not match:
        return ''
    candidate = match.group('acronym').rstrip('.')
    letters = [char for char in candidate if char.isalpha()]
    if len(letters) < 2 or sum(char.isupper() for char in letters) < 2:
        return ''
    return candidate


def recover_acronym_year_venue(venue, raw_text=''):
    """Recover venues written as generic acronym-plus-short-year forms.

    Handles forms such as ``ICML'24``, ``ACL\u201923``, ``LREC\\`08`` and their
    parenthesized variants. When a damaged field retains a full venue name in a
    following parenthesis, that fuller name wins. No conference-specific
    allowlist is used.
    """
    venue = venue if isinstance(venue, str) else ''
    raw_text = raw_text if isinstance(raw_text, str) else ''
    suspicious = is_suspicious_venue(venue)

    if suspicious:
        full_name = _parenthesized_venue_name(venue) or _parenthesized_venue_name(raw_text)
        if full_name:
            return full_name

    exact_acronym = _acronym_from_match(_ACRONYM_YEAR_ONLY_PATTERN.match(venue))
    if exact_acronym:
        return exact_acronym

    if suspicious:
        for source in (venue, raw_text):
            acronym = _acronym_from_match(_ACRONYM_YEAR_PATTERN.search(source))
            if acronym:
                return acronym

    return ''


def repair_extracted_venue(reference):
    """Repair or blank an impossible venue before database comparison."""
    venue = reference.get('venue', '') or ''
    if not isinstance(venue, str):
        return

    recovered = recover_acronym_year_venue(venue, reference.get('raw_text', ''))
    if recovered:
        reference['venue'] = recovered
    elif is_suspicious_venue(venue):
        reference['venue'] = ''


def strip_citation_tail_from_venue(reference):
    """Reduce a venue that swallowed the citation tail to the venue itself.

    LLM extraction sometimes returns the whole remainder of the raw citation as
    the venue::

        Tian, "BioProBench: ...," in International Conference on Machine
        Learning (ICML) , 2026

    The title then appears twice in the UI and every venue comparison runs
    against a string that can never match the real venue.
    """
    venue = reference.get('venue', '') or ''
    if not venue or not isinstance(venue, str):
        return

    if not any(q in venue for q in VENUE_TAIL_QUOTES):
        return

    # Prefer the segment introduced by "in", which is where the venue sits in
    # every style that quotes the title. Search after the closing quote so an
    # "in" inside the title cannot match.
    last_quote = max(venue.rfind(q) for q in VENUE_TAIL_QUOTES)
    tail = venue[last_quote + 1:] if last_quote >= 0 else venue

    m = re.search(r'^\s*[,.]?\s*in\s+(.+)$', tail, re.IGNORECASE)
    candidate = m.group(1) if m else tail

    # Everything from the year onwards is citation metadata, not venue — and
    # notes often follow it (", 2024, arXiv:2404" / ", 2026, SEAM"). Require
    # the comma so a venue that legitimately carries a year, like "ICLR 2024"
    # or "Proceedings of the 2024 Conference", survives.
    candidate = re.split(r'\s*,\s*(?:19|20)\d{2}[a-z]?\b', candidate)[0]
    candidate = candidate.strip().strip(',;.').strip()

    if not candidate or len(candidate) < 3:
        # Nothing usable survived, so the field is noise either way and a blank
        # venue is far better than one that fails every comparison.
        reference['venue'] = ''
        return

    reference['venue'] = candidate


def fixup_reference_fields(reference):
    """Correct common field-swap errors in a parsed reference, in-place.

    These errors arise when the extractor puts fields in the wrong order (or
    from cached results parsed before a fix was applied).
    """
    title = reference.get('title', '') or ''
    authors = reference.get('authors', []) or []
    venue = reference.get('venue', '') or ''

    # --- Venue-as-title ---
    if title and any(re.search(p, title, re.IGNORECASE) for p in _VENUE_AS_TITLE_PATTERNS):
        combined_authors = (' '.join(authors) if isinstance(authors, list) else str(authors)) if authors else ''
        if combined_authors and len(combined_authors) > 10:
            reference['venue'] = title
            reference['title'] = combined_authors
            reference['authors'] = []
        elif venue and len(venue) > 10:
            reference['title'], reference['venue'] = venue, title
        else:
            reference['venue'] = title
            reference['title'] = ''

    # --- Author-list-as-title ---
    title = reference.get('title', '') or ''
    authors = reference.get('authors', []) or []
    if title and not authors:
        words = title.split()
        if len(words) >= 8:
            capitalized = sum(1 for w in words if w[0].isupper() and w.isalpha())
            if len(words) > 0 and capitalized / len(words) > 0.8 and not any(w.lower() in _TITLE_WORDS for w in words):
                reference['authors'] = [title]
                reference['title'] = ''

    # --- Citation-string-as-title ---
    title = reference.get('title', '') or ''
    if title:
        _cit_pattern = r'\b\d{1,4}\s*[\(:]?\s*\d{1,4}\s*[\)]?\s*:\s*\d{1,4}\s*[-–]\s*\d{1,4}\b'
        if re.search(_cit_pattern, title):
            m = re.search(r'\.\s*([A-Z][^.]{15,}?)\.\s*[a-z]', title)
            if m:
                reference['title'] = m.group(1).strip()

    # --- Corrupt venue / acronym-year recovery ---
    # Run before quote-tail cleanup because the apostrophe in ``ACL\u201923`` is
    # typography, not the closing quotation mark of a swallowed citation.
    repair_extracted_venue(reference)

    # --- Citation-tail-as-venue ---
    strip_citation_tail_from_venue(reference)


__all__ = [
    "VENUE_TAIL_QUOTES",
    "fixup_reference_fields",
    "is_suspicious_venue",
    "recover_acronym_year_venue",
    "repair_extracted_venue",
    "strip_citation_tail_from_venue",
]
