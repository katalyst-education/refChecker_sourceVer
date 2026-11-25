"""Extract publication details from the part of a printed citation after its title."""

import re


PUBLICATION_FIELDS = ('volume', 'issue', 'pages', 'article_number', 'publisher', 'series')

_NUMBER = r'[A-Za-z]?\d+[A-Za-z]?'
_RANGE = rf'{_NUMBER}(?:\s*[-\u2010-\u2014]+\s*{_NUMBER})?'
_END = r'(?=\s*(?:[,;.]\s|[,;.]?$|\((?:19|20)\d{2}\)|\b(?:vol\.|no\.|pp?\.|art\.|Bd\.|Nr\.|S\.)))'
_TEXT_FIELD = r'[^,;]+?(?=\s*(?:[,;]|\.?$))'
_LABELS = (
    ('volume', r'vol(?:ume)?\.|volume\b|bd\.|band\b', _RANGE + _END),
    ('issue', r'no\.|nos\.|number\b|issue\b|nr\.|heft\b', _RANGE + _END),
    ('pages', r'pp?\.|pages?\b|s\.|seiten?\b', _RANGE + _END),
    ('article_number', r'(?:art\.|article\b)(?:\s*(?:no\.|number))?|artikel(?:\s*(?:-\s*nr\.|nummer))?', _NUMBER + _END),
    ('publisher', r'publisher\s*:|verlag\s*:', _TEXT_FIELD),
    ('series', r'(?:report\s+)?series\s*:|schriftenreihe\s*:|reihe\s*:', _TEXT_FIELD),
)
_LABELED_FIELD = re.compile(
    r'(?<!\w)(?:' + '|'.join(
        rf'(?:{label})\s*(?::\s*)?(?P<{field}>{value})'
        for field, label, value in _LABELS
    ) + ')', re.IGNORECASE,
)
_COMPACT_LOCATOR = re.compile(
    rf'[,.;\s]\s*(?P<volume>\d+)\s*(?:\(\s*(?P<issue>{_RANGE})\s*\))?'
    rf'\s*:\s*(?P<pages>{_RANGE}){_END}'
)
_YEAR = re.compile(r'\(((?:19|20)\d{2})\)|(?:^|[,.;])\s*((?:19|20)\d{2})(?=\s*[,.;]|\s*$)')
_TRAILING_LINK = re.compile(
    r'https?://|\b(?:DOI|arXiv|URL|ISBN|ISSN)\s*:|\[\s*(?:Online|\d+)\s*\]', re.IGNORECASE,
)
_PLACE_AND_PUBLISHER = re.compile(
    r'[^,:;\d]+(?:,\s*[^,:;\d]+)?\s*:\s*([^,;]+),\s*(?:19|20)\d{2}[.;]?\s*$'
)


def publication_tail(source, title):
    """Find the tail of an unquoted entry using its already parsed title."""
    words = title.split()
    if not words or title == 'Unknown Title':
        return ''
    pattern = r'(?<!\w)' + r'\s+'.join(map(re.escape, words)) + r'(?=\s*[,.;])'
    matches = list(re.finditer(pattern, source, re.IGNORECASE))
    return source[matches[0].end():] if len(matches) == 1 else ''


def _locator(value):
    return re.sub(r'\s*[-\u2010-\u2014]+\s*', '\u2013', value)


def publication_value_key(field, value):
    """Treat typographic variants of the same printed range as equivalent."""
    value = ' '.join(str(value).split()) if value is not None else ''
    return _locator(value) if field in {'volume', 'issue', 'pages'} else value


def parse_publication_tail(tail):
    """Return unambiguous fields and competing values from a delimited citation tail."""
    tail = ' '.join(_TRAILING_LINK.split(tail, maxsplit=1)[0].split())
    tail = re.sub(r'^\s*[,.;]?\s*(?:In\s*:\s*|In\s+)', '', tail, flags=re.IGNORECASE)
    labeled = list(_LABELED_FIELD.finditer(tail))
    compact = list(_COMPACT_LOCATOR.finditer(tail))
    values = {}
    for match in labeled + compact:
        for field, value in match.groupdict().items():
            if value is None:
                continue
            value = publication_value_key(field, value.strip(' ,;'))
            values.setdefault(field, {})[value] = None

    fields = {field: next(iter(items)) for field, items in values.items() if len(items) == 1}
    ambiguous = {field: list(items) for field, items in values.items() if len(items) > 1}
    # A numeric locator can be four digits too, so mask locators before finding a year.
    year_text = tail
    matches = sorted(labeled + compact, key=lambda match: match.start())
    for match in reversed(matches):
        year_text = year_text[:match.start()] + ' ' * len(match[0]) + year_text[match.end():]
    years = list(_YEAR.finditer(year_text))
    year = years[-1] if years else None
    if year and 1900 <= int(year[1] or year[2]) <= 2030:
        fields['year'] = int(year[1] or year[2])

    if matches:
        end = min(matches[0].start(), year.start() if year else len(tail))
        venue = tail[:end].strip(' ,;')
        if venue.startswith('.'):
            venue = venue[1:].lstrip()
        if venue and venue[0] not in ':(' and any(char.isalpha() for char in venue):
            if not {'publisher', 'series'}.intersection(values) or matches[0].lastgroup in PUBLICATION_FIELDS[:4]:
                fields['venue'] = venue
    elif tail.startswith('.'):
        publisher = _PLACE_AND_PUBLISHER.fullmatch(tail.strip(' .'))
        if publisher:
            fields['publisher'] = publisher[1].strip()

    return fields, ambiguous
