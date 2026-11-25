import pytest

from refchecker.utils.biblatex_parser import parse_biblatex_references
from refchecker.utils.bibtex_parser import parse_bibtex_references
from refchecker.utils.reference_metadata import attach_bibliography_sources, cited_metadata_changed


@pytest.mark.parametrize(('tail', 'expected'), [
    ('J. Thin Films, vol. 65, no.\n1-4, pp. 239–248, 2001.',
     {'journal': 'J. Thin Films', 'year': 2001, 'volume': '65', 'issue': '1–4', 'pages': '239–248'}),
    ('Zeitschrift für Werkstoffe, Bd. 3, Heft 2, S. 21–\n 29, 2020.',
     {'journal': 'Zeitschrift für Werkstoffe', 'year': 2020, 'volume': '3', 'issue': '2', 'pages': '21–29'}),
    ('Materials Journal 65(1-4):239–248, 2001.',
     {'journal': 'Materials Journal', 'year': 2001, 'volume': '65', 'issue': '1–4', 'pages': '239–248'}),
    ('In: Proceedings of the 2024 Thin Films Conference, pp. S3–S12, 2025.',
     {'journal': 'Proceedings of the 2024 Thin Films Conference', 'pages': 'S3–S12', 'year': 2025}),
    ('Materials Journal, vol. 30, Art. no. e012345, 2025.',
     {'journal': 'Materials Journal', 'volume': '30', 'article_number': 'e012345', 'year': 2025}),
    ('Publisher: U. S. University Press, Series: Materials Research Reports, 2020.',
     {'publisher': 'U. S. University Press', 'series': 'Materials Research Reports', 'year': 2020}),
])
def test_printed_citation_separates_publication_fields(tail, expected):
    raw = f'[1] A. Author, “Experimental results (2019),” {tail}'

    [reference] = parse_biblatex_references(raw)

    assert reference['title'] == 'Experimental results (2019)'
    assert reference['raw_text'] == raw
    for field, value in expected.items():
        assert reference[field] == value
    if 'article_number' in expected:
        assert 'pages' not in reference


def test_title_locator_and_link_text_do_not_supply_publication_values():
    [reference] = parse_biblatex_references(
        '[1] A. Author, “Results, vol. 15 (2023),” Materials Journal, '
        'p. 2020. URL: https://example.org/page?issue=08'
    )

    assert reference['pages'] == '2020'
    assert reference['year'] is None
    assert 'volume' not in reference
    assert 'issue' not in reference


def test_unquoted_entry_recovers_publication_fields_from_known_title():
    raw = '[1] A. Author. Experimental results. J. Thin Films, 65(1–4):239–248, 2001.'
    reference = {'entry_number': 1, 'title': 'Experimental results', 'venue': 'J.'}

    attach_bibliography_sources([reference], raw, 'regex')

    assert reference['venue'] == 'J. Thin Films'
    assert reference['volume'] == '65'
    assert reference['issue'] == '1–4'
    assert reference['pages'] == '239–248'


def test_competing_structured_values_preserve_the_source_and_parser_readings():
    raw = '[1] A. Author, “Experimental results,” Materials Journal, no. 2, no. 3, pp. 10–20, 2022.'
    reference = {'entry_number': 1, 'title': 'Experimental results', 'pages': '1–20'}

    attach_bibliography_sources([reference], raw, 'regex')

    assert 'issue' not in reference
    assert reference['pages'] == '1–20'
    assert reference['extraction_provenance']['source_text'] == raw
    assert reference['extraction_provenance']['review'] == {
        'issue': {'parsed': None, 'source': ['2', '3']},
        'pages': {'parsed': '1–20', 'source': '10–20'},
    }


def test_bibtex_keeps_structured_fields_and_legacy_number():
    [reference] = parse_bibtex_references('''@article{example,
        title = {Experimental results}, author = {A. Author}, journal = {Materials Journal},
        volume = {65}, number = {1--4}, eid = {e012345}, publisher = {Example Press}, year = {2020}
    }''')

    assert reference['volume'] == '65'
    assert reference['issue'] == reference['number'] == '1--4'
    assert reference['article_number'] == 'e012345'
    assert reference['publisher'] == 'Example Press'
    assert reference['extraction_provenance']['parsed_fields']['issue'] == '1--4'
    assert not cited_metadata_changed(reference, {**reference, 'issue': '1–4'})
