import pytest

from refchecker.utils.citation_urls import citation_links
from refchecker.utils.doi_utils import extract_doi_from_url, normalize_doi
from refchecker.utils.reference_metadata import attach_bibliography_sources, reconcile_reference_source
from refchecker.utils.url_utils import clean_url, clean_url_punctuation


@pytest.mark.parametrize(('printed', 'expected'), [
    ('https://www.ioffe\n.ru/SVA/NSM/Semicond/Si/basic.html, nSM Archive.',
     'https://www.ioffe.ru/SVA/NSM/Semicond/Si/basic.html'),
    ('https://physic\ns.nist.gov/cgi-bin/cuu/Value?asil=, 2022.',
     'https://physics.nist.gov/cgi-bin/cuu/Value?asil='),
    ('https://www.azonano.com/article.aspx?ArticleID=3\n372, 2013.',
     'https://www.azonano.com/article.aspx?ArticleID=3372'),
    ('https://example.org/shop/pr\noducts/titanium-nitride/AA415\n5618, 2024.',
     'https://example.org/shop/products/titanium-nitride/AA4155618'),
    ('https://example.org/thermal-\nanalysis/reports, 2019.',
     'https://example.org/thermal-analysis/reports'),
    ('https://example.org/thermal\u00ad\nanalysis, 2019.',
     'https://example.org/thermalanalysis'),
    ('https://example.org/record?q=A%2\n0B, 2019.',
     'https://example.org/record?q=A%20B'),
])
def test_wrapped_links_keep_visible_url_characters(printed, expected):
    [link] = citation_links(printed)
    assert link.resolved == expected
    assert link.alternative is None


def test_ambiguous_break_is_preserved_until_layout_confirms_it():
    raw = '[1] A. Author, “Research archive,” https://example.org/source/\nrecord.'
    reference = {'entry_number': 1, 'title': 'Research archive', 'url': 'https://example.org/source/'}

    attach_bibliography_sources([reference], raw, 'regex')

    assert reference['url'] == 'https://example.org/source/'
    evidence = reference['extraction_provenance']
    assert evidence['source_text'] == raw
    assert evidence['review']['url'] == {
        'parsed': 'https://example.org/source/', 'source': 'https://example.org/source/record',
    }

    layout = raw.replace('\n', '')
    reconcile_reference_source(reference, layout_text=layout)

    assert reference['url'] == 'https://example.org/source/record'
    assert evidence['layout_text'] == layout
    assert 'url' not in evidence['review']
    assert evidence['repairs'][-1]['reason'] == 'pdf_layout'


def test_wrapped_doi_url_repairs_only_the_matching_alias_and_identifier():
    raw = ('[1] A. Author, “Research archive,” https://doi.org/10.1016/S0927-0248(00)\n'
           '00099-4. Related URL: https://example.org/other.')
    reference = {
        'entry_number': 1, 'title': 'Research archive',
        'url': 'https://doi.org/10.1016/S0927-0248(00)',
        'doi': '10.1016/s0927-0248(00)',
        'cited_url': 'https://example.org/other',
    }

    attach_bibliography_sources([reference], raw, 'regex')

    assert reference['url'] == 'https://doi.org/10.1016/S0927-0248(00)00099-4'
    assert normalize_doi(reference['doi']) == '10.1016/s0927-0248(00)00099-4'
    assert reference['cited_url'] == 'https://example.org/other'


def test_page_number_and_access_date_are_citation_text():
    for tail in ('\nXXVI\nNext section', '\n2022.', '\nAccessed 14 March 2022.'):
        [link] = citation_links('https://example.org/record.' + tail)
        assert link.resolved == 'https://example.org/record'
        assert link.alternative is None


def test_url_and_doi_cleanup_preserves_balanced_delimiters():
    url = 'https://doi.org/10.1234/example(annex)'
    assert clean_url(url + ').') == url
    assert clean_url_punctuation(f'[report]({url})') == url
    assert extract_doi_from_url(url + ').') == '10.1234/example(annex)'
    assert normalize_doi('10.1234/EXAMPLE(annex)).') == '10.1234/example(annex)'
