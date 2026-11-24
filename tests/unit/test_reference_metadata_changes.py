import pytest

from refchecker.utils.reference_metadata import cited_metadata_changed


@pytest.mark.parametrize('field,value', [
    ('title', 'Changed title'), ('authors', ['Other Author']), ('year', 2021),
    ('venue', 'Other Journal'), ('doi', '10.1000/new'), ('arxiv_id', '2601.00001'),
    ('pmid', '1234'), ('url', 'https://example.org/new'), ('volume', '2'),
    ('issue', '3'), ('pages', '5–8'), ('publisher', 'Other Press'),
    ('isbn', '9780000000000'), ('issn', '1234-5678'), ('edition', 'Second'),
])
def test_each_cited_field_change_requires_verification(field, value):
    before = {'title': 'Original title', 'authors': ['A. Author'], 'year': 2020}
    after = {**before, field: value}
    assert cited_metadata_changed(before, after)


def test_equivalent_parser_representations_keep_existing_verification():
    before = {
        'title': 'Article title', 'authors': ['A. Author'], 'year': 2020,
        'venue': 'Solar energy', 'cited_url': 'https://example.org/paper', 'doi': None,
    }
    after = {
        'title': 'Article title', 'authors': [{'name': 'A. Author'}], 'year': '2020',
        'journal': 'Solar energy', 'url': 'https://example.org/paper', 'doi': '',
        'raw_text': '[1] A. Author. Article title. Solar energy, 2020.', 'type': 'other',
    }
    assert not cited_metadata_changed(before, after)


def test_verification_results_and_parser_bookkeeping_preserve_citation_identity():
    before = {
        'title': 'Article title', 'authors': ['A. Author'], 'year': 2020,
        'ref_uid': 'row-1', 'index': 1, 'status': 'error', 'errors': [{'error_type': 'author'}],
        'verified_authors': ['Other Author'], 'verified_url': 'https://doi.org/10.1000/example',
        'enrichment': {'cited_by_count': 100},
    }
    after = {'title': 'Article title', 'authors': ['A. Author'], 'year': 2020, 'entry_number': 1}
    assert not cited_metadata_changed(before, after)


def test_author_order_change_requires_verification():
    assert cited_metadata_changed({'authors': ['A. Author', 'B. Author']}, {'authors': ['B. Author', 'A. Author']})


@pytest.mark.parametrize('before,after', [
    ({'venue': 'Journal', 'journal': 'Journal'}, {'venue': 'Journal', 'journal': 'Changed journal'}),
    ({'cited_url': 'https://a.test', 'url': 'https://a.test'}, {'cited_url': 'https://a.test', 'url': 'https://b.test'}),
])
def test_changes_to_distinct_alias_values_require_verification(before, after):
    assert cited_metadata_changed(before, after)
