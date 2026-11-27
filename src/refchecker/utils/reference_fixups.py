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
_SOURCE_VENUE_CUE = re.compile(
    r"\b(?:proceedings|conference|journal|transactions|press|publishing|"
    r"publisher|springer|routledge|ieee|acm|frontiers|education|review|"
    r"society|symposium|workshop|association|university|academy|institute|"
    r"encyclopedia|unesco|oecd|sage|elsevier|wiley|mdpi|bmj|konferanse|"
    r"j\s+acad\b|academic\s+ethics|nobelprize\.org|"
    r"breakout\s+mentors|online\s+documentation|edutopia|"
    r"teaching@sydney|europass|enisa\.europa\.eu|"
    r"tech(?:nical)?\.?\s+rep(?:ort)?|committee\s+report|"
    r"publication\s+office|arxiv|convention|"
    r"behaviour\s*&\s*information\s+technology)\b|\brev\.",
    re.IGNORECASE,
)
_SOURCE_PUBLISHER_TAIL = re.compile(
    r'[.,]\s*(?:Longman|Routledge|Springer(?:\s+Nature)?|Wiley|'
    r'Elsevier|Pearson|Sage|SAGE|McGraw-Hill|Ablex|'
    r'Fachverlag Deutscher Wirtschaftsdienst|Cambridge University Press|'
    r'Oxford University Press|Jessica Kingsley Publishers)\s*,\s*'
    r'(?:19|20)\d{2}\b[\s\S]*$',
    re.IGNORECASE,
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


def recover_missing_venue_from_source(reference):
    """Recover a missing venue only from a title-matched quoted citation tail."""
    if not isinstance(reference, dict):
        return

    raw_text = reference.get('raw_text')
    title = reference.get('title')
    if not isinstance(raw_text, str) or not isinstance(title, str) or not title.strip():
        return

    from refchecker.utils.text_utils import calculate_title_similarity

    existing_venue = reference.get('venue') or reference.get('journal')
    if existing_venue:
        normalized_raw = re.sub(r'\s+', ' ', raw_text).strip()
        normalized_title = re.sub(r'\s+', ' ', title).strip()
        title_start = normalized_raw.casefold().find(normalized_title.casefold())
        if title_start >= 0:
            tail = normalized_raw[title_start + len(normalized_title):]
            cleaned_venue = re.split(
                r',\s*(?=(?:vol(?:ume)?\.?\s*\d|(?:19|20)\d{2}\b|'
                r'\d{1,4}\s*\(\d+\)|pp?\.?\s*\d|pages?\s*\d))',
                str(existing_venue),
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip(' \t\r\n,.;:')
            source_match = re.match(
                r'^\s*[.,;:]\s*' + re.escape(cleaned_venue),
                tail,
                re.IGNORECASE,
            )
            if (
                cleaned_venue != existing_venue
                and source_match
                and _SOURCE_VENUE_CUE.match(cleaned_venue)
            ):
                reference['venue'] = cleaned_venue
                reference['journal'] = cleaned_venue
        return

    normalized_raw = re.sub(r'\s+', ' ', raw_text).strip()
    normalized_title = re.sub(r'\s+', ' ', title).strip()
    title_start = normalized_raw.casefold().find(normalized_title.casefold())

    if title_start >= 0:
        strong_venue_cue = re.compile(
            r'\b(?:journal|proceedings|conference|transactions|press|publishing|'
            r'publisher|springer|routledge|ieee|acm|frontiers|society|symposium|'
            r'workshop|association|university|academy|institute|review|series|'
            r'hel(i|iy)on)\b',
            re.IGNORECASE,
        )
        for cue in strong_venue_cue.finditer(normalized_title):
            venue_start = cue.start()
            prior_separator = list(re.finditer(
                r'[.!?]\s+([^.!?]+)$',
                normalized_title[:cue.start()],
            ))
            if prior_separator:
                preceding_words = prior_separator[-1].group(1).split()
                if (
                    1 <= len(preceding_words) <= 3
                    and all(word[:1].isupper() for word in preceding_words)
                ):
                    venue_start = prior_separator[-1].start(1)
            source_venue = normalized_title[venue_start:].strip(' \t\r\n,.;:')
            title_prefix = normalized_title[:venue_start].strip(' \t\r\n,.;:')
            if len(title_prefix.split()) < 3 or not _SOURCE_VENUE_CUE.search(source_venue):
                continue
            source_start = title_start + venue_start
            if normalized_raw[source_start:source_start + len(source_venue)].casefold() != source_venue.casefold():
                continue
            tail = normalized_raw[source_start + len(source_venue):]
            if not re.match(
                r'\s*,\s*(?=(?:19|20)\d{2}\b|vol(?:ume)?\b|no\.?\b|'
                r'pp?\.?\b|pages?\b|issue\b|doi\b|issn\b|art(?:icle)?\b)',
                tail,
                re.IGNORECASE,
            ):
                continue
            reference['title'] = title_prefix
            reference['venue'] = source_venue
            reference['journal'] = source_venue
            return

    quoted_titles = list(re.finditer(r'["“](.+?)["”]', raw_text, re.DOTALL))
    title_is_quoted = any(
        calculate_title_similarity(match.group(1).lower(), title.lower()) >= 0.85
        for match in quoted_titles
    )
    if title_start >= 0 and not title_is_quoted:
        source_authors = (
            reference.get('source_authors') or reference.get('authors') or []
        )
        if isinstance(source_authors, str):
            source_authors = [source_authors]
        normalized_title_key = re.sub(r'\W+', '', normalized_title.casefold())
        if normalized_title_key and any(
            normalized_title_key
            == re.sub(r'\W+', '', str(author).casefold())
            for author in source_authors
        ):
            return

        source_title_start = normalized_raw.casefold().rfind(
            normalized_title.casefold()
        )
        source_title_end = source_title_start + len(normalized_title)
        has_title_boundary = (
            source_title_start >= 0
            and (
                source_title_end == len(normalized_raw)
                or not normalized_raw[source_title_end].isalnum()
            )
        )
        source_tail = (
            normalized_raw[source_title_end:] if has_title_boundary else ''
        )
        editor_container = re.search(
            r'\b(?:eds?|editors?)\.?,\s*(?P<container>.+)$',
            source_tail,
            re.IGNORECASE,
        )
        if editor_container and _SOURCE_VENUE_CUE.search(
            editor_container.group('container')
        ):
            source_tail = editor_container.group('container')
        source_tail = re.split(
            r'https?://|\bdoi\s*:|\baccessed\b|\bretrieved\b|'
            r'\bavailable\s*:',
            source_tail,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        source_tail = re.sub(
            r'''^\s*['"“”]?\s*[,.;:]?\s*(?:(?:in|en)\s+)?''',
            '',
            source_tail,
            flags=re.IGNORECASE,
        )
        source_venue = re.split(
            r',\s*(?=(?:vol(?:ume)?\.?\s*\d|(?:19|20)\d{2}\b|'
            r'\d{1,4}\s*\(\d+\)|pp?\.?\s*\d|pages?\s*\d|'
            r'art(?:icle)?\.?\s*no\.?))',
            source_tail,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip(' \t\r\n,.;:')
        source_venue = re.split(
            r'\s*\(\s*(?:vol(?:ume)?|no\.?)\b',
            source_venue,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip(' \t\r\n,.;:')
        source_venue_cue = _SOURCE_VENUE_CUE.search(source_venue)
        if (
            source_venue
            and len(source_venue) <= 180
            and not re.search(r'\barxiv\s*:', source_venue, re.IGNORECASE)
            and source_venue_cue
            and len(source_venue[:source_venue_cue.start()].split()) <= 3
        ):
            reference['venue'] = source_venue
            reference['journal'] = source_venue
            return

    if not quoted_titles:
        return

    match = max(
        quoted_titles,
        key=lambda item: calculate_title_similarity(
            item.group(1).lower(), title.lower()
        ),
    )
    if calculate_title_similarity(match.group(1).lower(), title.lower()) < 0.85:
        return

    tail = raw_text[match.end():]
    structured_tail = re.sub(
        r'^\s*[,.;:]?\s*["“”]?\s*(?:(?:in|en)\s+)?',
        '',
        tail,
        flags=re.IGNORECASE,
    )
    structured_venue = ''
    if not re.match(
        r'(?:presented\s+at|available\s*:|accessed\b|retrieved\b|https?://)',
        structured_tail,
        re.IGNORECASE,
    ):
        structured_match = re.match(
            r'(?P<venue>[^,]{2,180}?),\s*(?:'
            r'(?:vol(?:s|ume)?\.?|no\.?|pp?\.?|pages?|issue)\s*'
            r'[A-Za-z0-9().-]+|'
            r'art(?:icle)?\.?\s*no\.?\s*\d+|'
            r'\d{1,4}\s*,\s*(?:19|20)\d{2}\b)',
            structured_tail,
            re.IGNORECASE,
        )
        if structured_match:
            structured_venue = structured_match.group('venue').strip(
                ' \t\r\n,.;:"“”'
            )
    has_container_marker = bool(
        re.match(r'\s*(?:in|en)\s+', tail, re.IGNORECASE)
    )
    if has_container_marker:
        tail = _SOURCE_PUBLISHER_TAIL.sub('', tail)
    tail = re.split(
        r'https?://|\bdoi\s*:|\baccessed\b|\bretrieved\b|'
        r'\bavailable\s*:',
        tail,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    bracketed_venue = re.search(r'\[([^\]]+)\]', tail)
    if bracketed_venue and _SOURCE_VENUE_CUE.search(bracketed_venue.group(1)):
        tail = bracketed_venue.group(1)
    tail = tail.lstrip()
    tail = re.sub(r'^\s*[,.;:]\s*', '', tail)
    tail = re.sub(
        r'^(?:(?:in|en|presented\s+at|paper\s+presented\s+at)\s+|en,\s*)',
        '',
        tail,
        flags=re.IGNORECASE,
    )
    tail = re.sub(
        r'^the\s+(?=(?:19|20)\d{2}\b)',
        '',
        tail,
        flags=re.IGNORECASE,
    )
    editors = re.search(
        r',\s*[\s\S]{1,180}?\b(?:eds?|editors?)\.?(?=\s|$)',
        tail,
        re.IGNORECASE,
    )
    if editors:
        tail = tail[:editors.start()]
    tail = re.sub(
        r'^\s*[^,]{1,150}\(\s*Hg\.?\s*\)\s*,\s*',
        '',
        tail,
        flags=re.IGNORECASE,
    )
    tail = re.split(
        r'(?:,\s*(?:(?:19|20)\d{2}\b|(?:no\.?|pp?\.?|pages?)\s*'
        r'(?:[a-z]\s*)?\d|'
        r'\d{1,4}\s*(?:\(\d+\))?)|\s*,?\s*vol(?:ume)?\.?\s*)',
        tail,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    tail = re.split(
        r',\s*(?:(?:\d{1,2}\s+)?(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|'
        r'apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|'
        r'oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)'
        r'\.?\s+(?:19|20)\d{2}\b|(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|'
        r'apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|'
        r'oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)'
        r'\.?\s+\d{1,2}\b)',
        tail,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    tail = re.split(
        r'\s*[,.;]?\s*\[(?:online|electronic)\]',
        tail,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    tail = re.split(
        r',\s*(?:art(?:icle)?\.?\s*no\.?|paper(?:\s+id)?|id)\s*#?\s*'
        r'[\w-]+',
        tail,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    tail = re.sub(r'\s+\d{1,4}\s*\(\d+\)\s*$', '', tail)
    if _SOURCE_VENUE_CUE.search(tail):
        tail = re.sub(r'\s+\d{1,4}\s*$', '', tail)
    tail = re.sub(r'\.\s*\d{1,5}\.?\s*$', '', tail)
    venue = re.sub(r'\s+', ' ', tail).strip(' \t\r\n,.;:')
    venue = re.sub(r'^(?:19|20)\d{2},\s*', '', venue)
    venue = re.sub(r'^(?:19|20)\d{2}\s+(?=[A-Za-z])', '', venue)
    venue = re.sub(r'^Online Course,\s*', '', venue, flags=re.IGNORECASE)
    if (
        structured_venue
        and len(structured_venue.split()) >= 2
        and len(structured_venue) <= 180
        and not re.search(
            r'\b(?:journal name|title of the article)\b',
            structured_venue,
            re.IGNORECASE,
        )
    ):
        venue = structured_venue
    if (
        not venue
        or len(venue) > 240
        or re.fullmatch(r'[\d\s,./–-]+', venue)
        or re.search(r'\b(?:journal name|title of the article)\b', venue, re.IGNORECASE)
        or (
            not _SOURCE_VENUE_CUE.search(venue)
            and not structured_venue
            and not (
                has_container_marker
                and len(venue.split()) >= 2
                and not re.search(
                    r'\b(?:in press|in preparation|in review|in progress)\b',
                    venue,
                    re.IGNORECASE,
                )
            )
        )
    ):
        return

    reference['venue'] = venue
    reference['journal'] = venue


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
