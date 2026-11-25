from unittest.mock import Mock

import pytest

from refchecker.checkers.crossref import CrossRefReferenceChecker


CITED = {
    'title': 'Modellingcharge transport in porous silicon films',
    'authors': ['A. Silva'],
    'year': 2021,
    'journal': 'Journal of Thin Films',
    'volume': '65',
    'issue': '1–4',
    'pages': '239–248',
    'raw_text': 'A. Silva. Modellingcharge transport in porous silicon films. Journal of Thin Films, 2021.',
}
WORK = {
    'DOI': '10.1234/porous-silicon',
    'title': ['Modelling charge transport in porous silicon films'],
    'author': [{'given': 'Ana', 'family': 'Silva'}],
    'published': {'date-parts': [[2021]]},
    'container-title': ['Journal of Thin Films'],
    'type': 'journal-article',
    'volume': '65',
    'issue': '1-4',
    'page': '239-248',
}


def test_title_miss_uses_single_structured_request(monkeypatch):
    checker = CrossRefReferenceChecker()
    checker.request_delay = 0
    replies = [
        Mock(status_code=200, **{'json.return_value': {'message': {'items': []}}}),
        Mock(status_code=200, **{'json.return_value': {'message': {'items': [
            {**WORK, 'DOI': '10.1234/other', 'page': '250-258'}, WORK,
        ]}}}),
    ]
    request = Mock(side_effect=replies)
    monkeypatch.setattr('refchecker.checkers.crossref.requests.get', request)

    verified, findings, _ = checker.verify_reference(dict(CITED))

    assert verified['DOI'] == WORK['DOI']
    assert verified['_verification_basis'] == 'structured_citation'
    assert findings == []
    assert request.call_count == 2
    title_params, fallback_params = (call.kwargs['params'] for call in request.call_args_list)
    assert 'Modellingcharge' in title_params['query']
    assert fallback_params['query.bibliographic'] == 'Journal of Thin Films, vol. 65, no. 1–4, p. 239'
    assert {'container-title', 'volume', 'issue', 'page', 'article-number'} <= set(fallback_params['select'].split(','))


@pytest.mark.parametrize('conflict', [
    {'page': '240-248'},
    {'volume': '66'},
    {'issue': '5'},
    {'type': 'book-chapter'},
    {'container-title': ['A different publication']},
    {'title': ['Mechanical properties of steel at high temperature']},
    {'author': [{'given': 'John', 'family': 'Other'}]},
    {'published': {'date-parts': [[2025]]}},
    {'volume': ''},
])
def test_structured_search_requires_matching_coordinates_and_identity(monkeypatch, conflict):
    checker = CrossRefReferenceChecker()
    monkeypatch.setattr(checker, 'search_works', lambda *_: [])
    monkeypatch.setattr(checker, 'search_works_bibliographic', lambda *_: [{**WORK, **conflict}])

    assert checker.verify_reference(dict(CITED)) == (None, [], None)


def test_structured_search_leaves_two_different_matching_dois_unresolved(monkeypatch):
    checker = CrossRefReferenceChecker()
    monkeypatch.setattr(checker, 'search_works', lambda *_: [])
    monkeypatch.setattr(checker, 'search_works_bibliographic', lambda *_: [
        WORK, {**WORK, 'DOI': '10.1234/unresolved-second-match'},
    ])

    assert checker.verify_reference(dict(CITED)) == (None, [], None)


def test_conflicting_title_result_triggers_article_number_search(monkeypatch):
    checker = CrossRefReferenceChecker()
    reference = {**CITED, 'title': WORK['title'][0], 'pages': None, 'article_number': 'e012345'}
    correct = {**WORK, 'page': None, 'article-number': 'e012345'}
    wrong = {**correct, 'DOI': '10.1234/other', 'article-number': 'e999999'}
    monkeypatch.setattr(checker, 'search_works', lambda *_: [wrong])
    fallback = Mock(return_value=[wrong, correct])
    monkeypatch.setattr(checker, 'search_works_bibliographic', fallback)

    verified, findings, _ = checker.verify_reference(reference)

    assert verified['DOI'] == WORK['DOI']
    assert findings == []
    fallback.assert_called_once_with('Journal of Thin Films, vol. 65, no. 1–4, article e012345', 2021)


def test_reliable_title_match_skips_fallback(monkeypatch):
    checker = CrossRefReferenceChecker()
    monkeypatch.setattr(checker, 'search_works', lambda *_: [WORK])
    fallback = Mock()
    monkeypatch.setattr(checker, 'search_works_bibliographic', fallback)

    verified, _, _ = checker.verify_reference({**CITED, 'title': WORK['title'][0]})

    assert verified['DOI'] == WORK['DOI']
    fallback.assert_not_called()


def test_direct_doi_match_skips_both_searches(monkeypatch):
    checker = CrossRefReferenceChecker()
    direct = Mock(return_value={**WORK, 'title': WORK['title'][0]})
    search = Mock()
    monkeypatch.setattr(checker, 'get_work_by_doi', direct)
    monkeypatch.setattr(checker, 'search_works', search)
    monkeypatch.setattr(checker, 'search_works_bibliographic', search)

    verified, findings, _ = checker.verify_reference({**CITED, 'doi': WORK['DOI']})

    assert verified['DOI'] == WORK['DOI']
    assert findings == []
    search.assert_not_called()


def test_unresolved_source_fields_use_the_existing_raw_citation_fallback(monkeypatch):
    checker = CrossRefReferenceChecker()
    monkeypatch.setattr(checker, 'search_works', lambda *_: [])
    fallback = Mock(return_value=[])
    monkeypatch.setattr(checker, 'search_works_bibliographic', fallback)
    reference = {
        **CITED,
        'extraction_provenance': {'review': {'pages': {'parsed': '239–248', 'source': '240–248'}}},
    }

    checker.verify_reference(reference)

    fallback.assert_called_once_with(CITED['raw_text'], 2021)


@pytest.mark.parametrize(('title', 'status'), [
    (CITED['title'], 'verified'),
    ('Modelling charge trapsport in porous silicon films', 'warning'),
])
def test_cli_batch_and_webui_share_the_structured_fallback(monkeypatch, title, status):
    from backend.refchecker_wrapper import ProgressRefChecker
    from backend.reference_result import project_verification_result
    from refchecker.checkers.enhanced_hybrid_checker import EnhancedHybridReferenceChecker
    from refchecker.core import bulk_pipeline
    from refchecker.core.refchecker import ArxivReferenceChecker

    monkeypatch.setattr(EnhancedHybridReferenceChecker, '_initialize_checker', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(EnhancedHybridReferenceChecker, '_cross_verify_secondary', lambda *_: None)
    hybrid = EnhancedHybridReferenceChecker(enable_openalex=False, enable_arxiv_citation=False)
    hybrid.crossref = CrossRefReferenceChecker()
    monkeypatch.setattr(hybrid.crossref, 'search_works', lambda *_: [])
    monkeypatch.setattr(hybrid.crossref, 'search_works_bibliographic', lambda *_: [WORK])
    cli = ArxivReferenceChecker.__new__(ArxivReferenceChecker)
    cli.non_arxiv_checker = hybrid
    cli.enable_parallel = False
    web = ProgressRefChecker.__new__(ProgressRefChecker)
    web.checker = hybrid
    cited = {**CITED, 'title': title}

    errors, url, data = cli.verify_reference(None, dict(cited))
    assert web._verify_reference_body(dict(cited)) == (data, errors, url)
    projected = project_verification_result(cited, data, errors, url, enrich_enabled=False)
    assert projected['verification_basis'] == 'structured_citation'
    assert projected['status'] == status
    assert projected['cited_metadata']['title'] == title

    cache = bulk_pipeline.BulkVerificationCache()
    record_result = Mock()
    monkeypatch.setattr(bulk_pipeline, '_record_reference_result_silent', record_result)
    bulk_pipeline._verify_bibliography_silent(cli, None, [dict(cited)], False, cache)
    assert record_result.call_args.kwargs['verified_data'] == data
    assert cache.get({**cited, 'pages': '239-248'}) == (errors, url, data)
    assert cache.get({**cited, 'pages': '240-248'}) is None
    assert cache.get({**cited, 'doi': '10.1234/other'}) is None
    assert cache.get({**cited, 'authors': ['J. Silva']}) is None
