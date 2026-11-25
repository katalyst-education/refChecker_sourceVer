"""Edition-specific evidence for book citations and catalogue records."""

import re

from refchecker.utils.error_utils import format_year_mismatch


_ORDINALS = ('first', 'second', 'third', 'fourth', 'fifth', 'sixth', 'seventh',
             'eighth', 'ninth', 'tenth')
EDITION_LABEL = (
    r'(?:(?:\d+(?:st|nd|rd|th|d)?|revised|updated|' + '|'.join(_ORDINALS)
    + r')\s+(?:edition\b|ed\b\.?)|\d+\.\s*(?:auflage\b|aufl\.))'
)
_EDITION = re.compile(rf'(?<!\w){EDITION_LABEL}', re.IGNORECASE)
_EDITION_SUFFIX = re.compile(rf'[,;]\s*({_EDITION.pattern})[.\s]*$', re.IGNORECASE)
_DISPLAY_VOLUME = re.compile(
    r'(?<!\w)(?:vol\.|volumes?\b|v\.|bd\.|band\b)\s*(\d+|[ivxlcdm]+)(?!\w)', re.IGNORECASE,
)
_ISBN = re.compile(r'(?<!\w)(?:97[89][-\s]?)?(?:\d[-\s]?){9}[\dX](?!\w)', re.IGNORECASE)
_YEAR = re.compile(r'(?<!\d)(1\d{3}|2\d{3})(?!\d)')
_YEAR_FINDINGS = {'year', 'publication_year', 'publication_year_discrepancy', 'year_unverified'}


def split_title_edition(title):
    match = _EDITION_SUFFIX.search(title)
    return (title[:match.start()].strip(), match[1]) if match else (title, '')


def edition_label(value):
    match = _EDITION.search(str(value or ''))
    return match[0] if match else ''


def edition_key(value):
    value = str(value or '').strip().casefold()
    if not value:
        return ''
    match = re.match(r'\d+', value)
    if match:
        return str(int(match[0]))
    first_word = value.split()[0]
    return str(_ORDINALS.index(first_word) + 1) if first_word in _ORDINALS else first_word


def book_volume(text):
    match = _DISPLAY_VOLUME.search(str(text or ''))
    return match[1] if match else ''


def _volume_key(value):
    value = str(value or '').strip().casefold()
    if value.isdecimal():
        return str(int(value))
    roman = {'i': 1, 'v': 5, 'x': 10, 'l': 50, 'c': 100, 'd': 500, 'm': 1000}
    if value and all(character in roman for character in value):
        numbers = [roman[character] for character in value]
        return str(sum(-number if number < following else number
                       for number, following in zip(numbers, numbers[1:] + [0])))
    return value


def isbn_digits(value):
    match = _ISBN.search(str(value or ''))
    return re.sub(r'[-\s]', '', match[0]).upper() if match else ''


def isbn_key(value):
    value = isbn_digits(value)
    if len(value) == 10:
        digits = '978' + value[:9]
        checksum = sum(int(digit) * (1 if index % 2 == 0 else 3)
                       for index, digit in enumerate(digits))
        return digits + str(-checksum % 10)
    return value


def book_edition_identity(reference):
    """Edition coordinates required for citation-specific cache reuse."""
    return (
        edition_key(reference.get('edition') or reference.get('edition-number')),
        isbn_key(reference.get('isbn') or reference.get('ISBN')),
        _volume_key(book_volume(reference.get('volume')) or reference.get('volume')),
        _publisher_key(reference.get('publisher')),
    )


def is_book_citation(reference):
    from refchecker.utils.venue_utils import resolve_publication_type

    kind = resolve_publication_type(reference).publication_type
    return kind == 'whole-book' or (kind == 'unknown' and bool(reference.get('edition')))


def _publisher_key(value):
    words = re.findall(r'\w+', str(value or '').casefold())
    if words and words[-1] in {'publishers', 'publishing', 'press', 'verlag'}:
        words.pop()
    return ''.join(words)


def _year(value):
    match = _YEAR.search(str(value or ''))
    return int(match[1]) if match else None


def book_publication_dates(record):
    dates = dict(record.get('book_publication_dates') or {})
    for field, label in (('published-print', 'print'), ('published-online', 'online')):
        value = record.get(field)
        parts = (value.get('date-parts') or []) if isinstance(value, dict) else []
        if parts and parts[0]:
            dates[label] = parts[0][0]
    if not dates and not record.get('_book_work_level'):
        date = record.get('publication_year') or record.get('year') or record.get('published_date')
        if date:
            dates['catalogued publication'] = date
    return {label: year for label, date in dates.items() if (year := _year(date))}


def book_edition_status(reference, record):
    """Return matched, unverified, or None when edition verification is unnecessary."""
    from refchecker.utils.venue_utils import resolve_publication_type

    cited_kind = resolve_publication_type(reference).publication_type
    actual_kind = resolve_publication_type({}, record).publication_type
    if cited_kind not in {'unknown', 'whole-book'}:
        return None
    if actual_kind != 'whole-book' and not is_book_citation(reference):
        return None

    cited_edition, cited_isbn, cited_volume, cited_publisher = book_edition_identity(reference)
    cited_year = _year(reference.get('year'))
    dates = book_publication_dates(record)
    first_year = _year(record.get('first_publish_year'))
    needs_edition = cited_edition or cited_isbn or cited_volume
    if record.get('_book_work_level'):
        if needs_edition or (cited_year and cited_year != first_year):
            return 'unverified'
        return None
    if not needs_edition and (not cited_year or not dates):
        return None
    if actual_kind not in {'unknown', 'whole-book'}:
        return 'unverified'

    actual_edition, actual_isbn, actual_volume, actual_publisher = book_edition_identity(record)
    record_isbns = {isbn_key(isbn) for isbn in record.get('isbn_values', [])} | {actual_isbn}
    record_isbns.discard('')
    same_isbn = bool(cited_isbn and cited_isbn in record_isbns)
    from refchecker.utils.doi_utils import normalize_doi

    cited_doi = normalize_doi(reference.get('doi') or reference.get('DOI') or '')
    actual_doi = normalize_doi(record.get('doi') or record.get('DOI') or '')
    same_identifier = same_isbn or bool(cited_doi and cited_doi == actual_doi)
    coordinates = ((cited_edition, actual_edition), (cited_volume, actual_volume))
    if any(cited and actual and cited != actual for cited, actual in coordinates):
        return 'unverified'
    if same_identifier:
        return 'matched'
    if cited_isbn or any(cited and cited != actual for cited, actual in coordinates):
        return 'unverified'
    if cited_publisher and actual_publisher and cited_publisher != actual_publisher:
        return 'unverified'
    if cited_year and cited_year not in dates.values():
        return 'unverified'
    # A matching edition or volume label or the publication date ties the record
    # to the citation. Scholarly search results without a book type need that label.
    return 'matched' if actual_kind == 'whole-book' or any(cited for cited, _ in coordinates) else 'unverified'


def assess_book_edition(reference, record, findings):
    status = book_edition_status(reference, record)
    if status is None:
        return record, findings

    record = dict(record)
    dates = book_publication_dates(record)
    cited_year = _year(reference.get('year'))
    first_year = _year(record.get('first_publish_year'))
    record['_book_edition_assessment'] = {'status': status, 'dates': dates, 'first_publish_year': first_year}
    findings = [finding for finding in findings if (
        (finding.get('error_type') or finding.get('warning_type') or finding.get('info_type'))
        not in _YEAR_FINDINGS | {'edition_unverified', 'book_publication_dates'}
    )]
    if status == 'unverified':
        volume = reference.get('volume')
        cited = ', '.join(str(value) for value in (
            reference.get('edition'), f'vol. {volume}' if volume else None, cited_year,
            f"ISBN {reference['isbn']}" if reference.get('isbn') else None,
        ) if value)
        context = []
        if first_year:
            context.append(f'The catalogue lists {first_year} as the work’s first publication year.')
        if dates:
            context.append('Catalogue record dates include ' + ', '.join(
                f'{label} {year}' for label, year in dates.items()
            ) + '.')
        alternatives = record.get('book_edition_alternatives') or []
        if alternatives:
            context.append('Available catalogue editions include ' + ' / '.join(alternatives) + '.')
        findings.append({
            'warning_type': 'edition_unverified',
            'warning_details': ' '.join([
                f'Edition unverified. Could not confirm the cited edition ({cited}).'
                if cited else 'Edition unverified. Could not confirm the cited edition.',
                *context,
            ]),
        })
    elif cited_year and not dates:
        findings.append({
            'warning_type': 'year_unverified',
            'warning_details': 'The edition was identified. Its publication year could not be verified.',
        })
    elif (
        cited_year and cited_year not in dates.values() and len(set(dates.values())) == 1
        and {'print', 'catalogued publication'} & dates.keys()
    ):
        verified_year = next(iter(dates.values()))
        findings.append({
            'warning_type': 'year',
            'warning_details': format_year_mismatch(cited_year, verified_year),
            'ref_year_correct': verified_year,
            'metadata_classification': 'book_edition_date_mismatch',
        })
    elif cited_year and dates and (len(set(dates.values())) > 1 or cited_year not in dates.values()):
        findings.append({
            'info_type' if cited_year in dates.values() else 'warning_type': 'book_publication_dates',
            'info_details' if cited_year in dates.values() else 'warning_details':
                'Edition dates differ by publication type. ' + ', '.join(
                    f'{label} {year}' for label, year in dates.items()
                ) + '.',
        })
    return record, findings
