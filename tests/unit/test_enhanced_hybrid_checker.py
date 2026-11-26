import logging
import threading

import requests
import pytest
from unittest.mock import Mock, patch

from refchecker.checkers.enhanced_hybrid_checker import (
    EnhancedHybridReferenceChecker,
    VerificationCancelled,
)


class NoMatchChecker:
    def verify_reference(self, reference):
        return None, [], None


class TimeoutChecker:
    def verify_reference(self, reference):
        raise requests.exceptions.Timeout('simulated timeout')


def _progress_checker(events, cancel_event=None):
    checker = EnhancedHybridReferenceChecker.__new__(EnhancedHybridReferenceChecker)
    checker.progress_callback = events.append
    checker.cancel_event = cancel_event or threading.Event()
    checker._api_semaphores = {}
    checker._api_time_lock = threading.Lock()
    checker._api_total_time = {'demo': 0.0}
    checker._api_sem_wait_time = {'demo': 0.0}
    checker.api_stats = {
        'demo': {'success': 0, 'failure': 0, 'avg_time': 0, 'throttled': 0},
    }
    return checker


def test_database_progress_emits_searching_and_no_match():
    events = []
    checker = _progress_checker(events)

    assert checker._try_api('demo', NoMatchChecker(), {'title': 'Missing'})[4] == 'not_found'

    assert [event['status'] for event in events] == ['searching', 'no_match']
    assert events[-1]['duration_ms'] >= 0


def test_database_progress_emits_timeout():
    events = []
    checker = _progress_checker(events)

    assert checker._try_api('demo', TimeoutChecker(), {'title': 'Slow'})[4] == 'timeout'

    assert [event['status'] for event in events] == ['searching', 'timed_out']


def test_one_exact_doi_match_returns_without_waiting_for_slow_catalogue():
    """A supplementary catalogue must not delay an exact DOI confirmation."""
    class DoiMatchChecker:
        def __init__(self, label):
            self.database_label = label

        def verify_reference(self, reference):
            return ({
                'title': reference['title'],
                'authors': reference['authors'],
                'year': reference['year'],
                'doi': reference['doi'],
            }, [], f"https://example.org/{self.database_label}")

    checker = _catalogue_reconciliation_checker()
    checker.crossref = DoiMatchChecker('CrossRef')
    reference = {
        'title': 'A decisively identified work',
        'authors': ['Ada Author'],
        'year': 2024,
        'doi': '10.1000/example',
    }

    result, incomplete_results = checker._verify_non_arxiv_parallel(
        reference, [], [], force_all_databases=False,
    )
    data, findings, _ = result

    assert data['doi'] == '10.1000/example'
    assert findings == []
    assert incomplete_results == {}


def test_two_title_author_matches_are_decisive_without_a_doi():
    checker = _catalogue_reconciliation_checker()
    reference = {
        'title': 'A High Confidence Title And Author Match',
        'authors': ['Ada Author'],
        'year': 2024,
    }

    class TitleAuthorMatch:
        def __init__(self, label):
            self.database_label = label

        def verify_reference(self, candidate):
            return ({
                'title': candidate['title'],
                'authors': candidate['authors'],
                'year': candidate['year'],
            }, [], f"https://example.org/{self.database_label}")

    checker.semantic_scholar = TitleAuthorMatch('Semantic Scholar')
    checker.crossref = TitleAuthorMatch('CrossRef')

    result, incomplete_results = checker._verify_non_arxiv_parallel(
        reference, [], [], force_all_databases=False,
    )
    data, findings, _ = result

    assert data['title'] == reference['title']
    assert findings == []
    assert incomplete_results == {}


def test_database_candidate_summary_includes_display_metadata_and_result_url():
    summary = EnhancedHybridReferenceChecker._database_trace_summary(
        {
            'title': 'Matched work',
            'authors': [
                {'name': 'Ada Lovelace'},
                {'given': 'Grace', 'family': 'Hopper'},
            ],
            'year': 2024,
            'externalIds': {'DOI': '10.1000/example'},
        },
        'https://example.org/result',
    )

    assert summary == {
        'title': 'Matched work',
        'authors': ['Ada Lovelace', 'Grace Hopper'],
        'corporate_contributors': [],
        'year': 2024,
        'url': 'https://example.org/result',
        'links': [
            {'type': 'result', 'url': 'https://example.org/result'},
            {'type': 'doi', 'url': 'https://doi.org/10.1000/example'},
        ],
        'doi': '10.1000/example',
        'id': None,
    }


def test_database_candidate_summary_keeps_all_distinct_links():
    summary = EnhancedHybridReferenceChecker._database_trace_summary({
        'url': 'https://example.org/landing',
        'urls': ['https://example.org/landing', 'https://example.org/alternate'],
        'openAccessPdf': {'url': 'https://example.org/paper.pdf'},
        'externalIds': {'ArXiv': '2401.01234'},
    })

    assert [item['url'] for item in summary['links']] == [
        'https://example.org/landing',
        'https://example.org/alternate',
        'https://example.org/paper.pdf',
        'https://arxiv.org/abs/2401.01234',
    ]


def test_cancelled_verification_does_not_call_provider():
    events = []
    cancel_event = threading.Event()
    cancel_event.set()
    checker = _progress_checker(events, cancel_event)
    provider = NoMatchChecker()

    with pytest.raises(VerificationCancelled):
        checker._try_api('demo', provider, {'title': 'Cancelled'})

    assert events == []


def test_retry_wait_is_interruptible():
    checker = _progress_checker([])
    checker.cancel_event.set()

    with pytest.raises(VerificationCancelled):
        checker._wait_or_cancel(30)


class LocalMatchChecker:
    database_label = "Semantic Scholar"
    database_key = "local_s2"

    def verify_reference(self, reference):
        return (
            {
                "title": reference.get("title", ""),
                "paperId": "s2-match-id",
            },
            [],
            "https://www.semanticscholar.org/paper/s2-match-id",
        )


class LocalDoiMismatchChecker:
    database_label = "Semantic Scholar"
    database_key = "local_s2"

    def __init__(self):
        self.called = False

    def verify_reference(self, reference):
        self.called = True
        return (
            {
                "title": reference["title"],
                "authors": [{"name": "Ada Author"}],
                "externalIds": {"DOI": "10.48550/arXiv.2410.13298"},
            },
            [{
                "warning_type": "doi",
                "warning_details": (
                    "DOI mismatch\n"
                    "       cited:  10.18653/v1/2024.emnlp-main.223\n"
                    "       actual: 10.48550/arXiv.2410.13298"
                ),
            }],
            "https://arxiv.org/abs/2410.13298",
        )


class ExactDoiChecker:
    database_label = "CrossRef"
    database_key = "local_crossref"

    def __init__(self):
        self.called = False

    def verify_reference(self, reference):
        self.called = True
        return (
            {
                "title": reference["title"],
                "authors": [{"name": "Ada Author"}],
                "externalIds": {"DOI": reference["doi"]},
            },
            [],
            f"https://doi.org/{reference['doi']}",
        )


class LocalArxivMismatchChecker:
    database_label = "Semantic Scholar"
    database_key = "local_s2"

    def verify_reference(self, reference):
        return (
            {
                "title": "Read as You See: Guiding Unimodal LLMs for Low-Resource Explainable Harmful Meme Detection",
                "authors": [
                    {"name": "Fengjun Pan"},
                    {"name": "Xiaobao Wu"},
                    {"name": "Tho Quan"},
                    {"name": "Anh Tuan Luu"},
                ],
                "year": 2025,
                "externalIds": {"ArXiv": "2506.08477"},
            },
            [
                {
                    "error_type": "title",
                    "error_details": "Title mismatch",
                    "ref_title_correct": "Read as You See: Guiding Unimodal LLMs for Low-Resource Explainable Harmful Meme Detection",
                },
                {
                    "error_type": "author",
                    "error_details": "Author count mismatch: 3 cited vs 4 correct",
                    "ref_authors_correct": "Fengjun Pan, Xiaobao Wu, Tho Quan, Anh Tuan Luu",
                },
            ],
            "https://api.semanticscholar.org/CorpusID:test",
        )


class ArxivVersionWarningChecker:
    def is_arxiv_reference(self, reference):
        return False

    def verify_reference(self, reference):
        assert reference["url"] == "https://arxiv.org/abs/2506.08477"
        return (
            {
                "title": "Read as You See: Guiding Unimodal LLMs for Low-Resource Explainable Harmful Meme Detection",
                "authors": [
                    {"name": "Fengjun Pan"},
                    {"name": "Xiaobao Wu"},
                    {"name": "Tho Quan"},
                    {"name": "Anh Tuan Luu"},
                ],
                "year": 2025,
                "externalIds": {"ArXiv": "2506.08477"},
            },
            [
                {
                    "warning_type": "title (v1 vs v2 update)",
                    "warning_details": "Title mismatch (v1 vs v2 update)",
                    "ref_title_correct": "Read as You See: Guiding Unimodal LLMs for Low-Resource Explainable Harmful Meme Detection",
                },
                {
                    "warning_type": "author (v1 vs v2 update)",
                    "warning_details": "Author count mismatch: 3 cited vs 4 correct (v1 vs v2 update)",
                    "ref_authors_correct": "Fengjun Pan, Xiaobao Wu, Tho Quan, Anh Tuan Luu",
                },
            ],
            "https://arxiv.org/abs/2506.08477v1",
        )


class ArxivTitleSearchChecker:
    def is_arxiv_reference(self, reference):
        return False

    def extract_arxiv_id(self, reference):
        return None, None

    def find_arxiv_id_by_title(self, title, authors=None, year=None):
        assert title == 'Retrospective for the dynamics sensorium competition for predicting large-scale mouse primary visual cortex activity from videos'
        return '2407.09100'

    def verify_reference(self, reference):
        assert reference['url'] == 'https://arxiv.org/abs/2407.09100'
        return (
            {
                'title': 'Retrospective for the Dynamic Sensorium Competition for predicting large-scale mouse primary visual cortex activity from videos',
                'authors': [
                    {'name': 'Polina Turishcheva'},
                    {'name': 'Paul G. Fahey'},
                    {'name': 'Michaela Vystrčilová'},
                ],
                'year': 2024,
                'externalIds': {'ArXiv': '2407.09100'},
            },
            [],
            'https://arxiv.org/abs/2407.09100',
        )


class WrongOpenReviewChecker:
    def __init__(self):
        self.called = False

    def verify_reference_by_search(self, reference):
        self.called = True
        return (
            {
                'title': 'The sensorium competition on predicting large-scale mouse primary visual cortex activity',
                'authors': ['Konstantin F. Willeke', 'Paul G. Fahey'],
                'year': 2022,
                '_matched_database': 'OpenReview',
            },
            [{'warning_type': 'author', 'warning_details': 'wrong paper'}],
            'https://openreview.net/forum?id=2aphixM7rbf',
        )


def _build_checker():
    with patch.object(EnhancedHybridReferenceChecker, '_initialize_checker', return_value=None):
        checker = EnhancedHybridReferenceChecker(
            enable_openalex=False,
            enable_crossref=False,
            enable_arxiv_citation=False,
        )

    checker.local_db = None
    checker.semantic_scholar = NoMatchChecker()
    checker.crossref = TimeoutChecker()
    checker.openalex = None
    checker.open_library = None
    checker.dblp = None
    checker.openreview = None
    return checker


def test_paperclip_key_can_be_supplied_per_request(monkeypatch):
    paperclip_calls = []

    class FakePaperclip:
        enabled = True

    def fake_initialize(self, module_name, class_name, log_name, *args, **kwargs):
        if module_name == 'paperclip':
            paperclip_calls.append(kwargs)
            return FakePaperclip()
        return None

    monkeypatch.delenv('PAPERCLIP_API_KEY', raising=False)
    with patch.object(EnhancedHybridReferenceChecker, '_initialize_checker', fake_initialize):
        checker = EnhancedHybridReferenceChecker(
            paperclip_api_key='pc-request-key',
            enable_openalex=False,
            enable_crossref=False,
            enable_arxiv_citation=False,
            enable_acl_anthology=False,
        )

    assert checker.paperclip is not None
    assert paperclip_calls == [{'api_key': 'pc-request-key'}]


@patch('refchecker.checkers.enhanced_hybrid_checker.time.sleep', return_value=None)
def test_unverified_reason_includes_negative_and_failed_checkers(_mock_sleep):
    checker = _build_checker()
    reference = {
        'title': 'Few-shot learning for personalized facial expression recognition',
        'authors': ['Anan Yao', 'Sheng Zhang', 'Ruisha Qian'],
        'venue': 'Proceedings of the 29th ACM International Conference on Multimedia',
        'year': 2021,
    }

    verified_data, errors, url = checker.verify_reference(reference)

    assert verified_data is None
    assert url is None
    assert len(errors) == 1
    assert errors[0]['error_type'] == 'unverified'
    assert errors[0]['error_details'] == (
        'Paper not found by any checker; no match in Semantic Scholar; '
        'checker failures: CrossRef: simulated timeout'
    )
    assert errors[0]['sources_checked'] == 2
    assert errors[0]['sources_negative'] == 1
    assert errors[0]['verification_reason'] == 'provider_failure'


@patch('refchecker.checkers.enhanced_hybrid_checker.time.sleep', return_value=None)
def test_google_books_retry_retains_force_all_context_and_reports_failure(_mock_sleep):
    """A forced Google Books retry must not degrade into an ineligible skip."""
    checker = _build_checker()

    class FailingGoogleBooksChecker:
        database_label = 'Google Books'

        def __init__(self):
            self.force_all_values = []

        def verify_reference(self, reference):
            self.force_all_values.append(reference.get('_google_books_force_all'))
            return None, [{
                'error_type': 'api_failure',
                'error_details': '503 Service Unavailable',
            }], None

    google_books = FailingGoogleBooksChecker()
    checker.semantic_scholar = None
    checker.crossref = None
    checker.google_books = google_books

    verified_data, errors, url = checker._verify_reference_core(
        {'title': 'A book that must query every database', 'authors': []},
        force_all_databases=True,
    )

    assert verified_data is None
    assert url is None
    assert google_books.force_all_values == [True, True]
    assert errors[0]['error_details'] == (
        'All available checkers failed: Google Books: 503 Service Unavailable'
    )


@pytest.mark.parametrize(('http_status', 'failure_type', 'progress_status'), [
    (None, 'api_failure', 'failed'),
    (404, 'api_failure', 'failed'),
    (429, 'throttled', 'rate_limited'),
])
def test_connector_failure_progress_distinguishes_http_rate_limits(http_status, failure_type, progress_status):
    checker = _build_checker()
    connector = Mock()
    connector.database_label = 'DBLP'
    connector.verify_reference.return_value = (
        None, [{'error_type': 'api_failure', 'error_details': 'DBLP API request failed',
                'http_status': http_status}], None,
    )

    with patch.object(checker, '_emit_database_event') as progress:
        *_, failure, detail = checker._try_api('dblp', connector, {'title': 'Example article'})

    assert failure == failure_type
    assert detail == ('DBLP API request failed' if http_status is None else f'DBLP API request failed (HTTP {http_status})')
    assert progress.call_args.kwargs['status'] == progress_status


@pytest.mark.parametrize(('http_status', 'html', 'expected_status', 'reason', 'counts'), [
    (403, '', 'unverified', 'url_access_failed', (0, 0, 0)),
    (200, '<title>Please log in to DSpace</title>', 'warning', 'authentication_required', (0, 1, 0)),
    (200, '<title>A completely unrelated work</title>', 'error', None, (1, 0, 0)),
])
def test_cited_page_fallback_preserves_access_and_content_outcomes(
    monkeypatch, http_status, html, expected_status, reason, counts,
):
    from backend.reference_result import project_verification_result
    from refchecker.checkers.webpage_checker import WebPageChecker
    from refchecker.core.issue_policy import count_raw_errors

    reference = {
        'title': 'Photovoltaic measurements in thin films',
        'venue': 'Journal of Materials Research',
        'cited_url': 'https://www.researchgate.net/publication/1234',
    }
    response = requests.Response()
    response.status_code = http_status
    response.url = reference['cited_url']
    response._content = html.encode()
    monkeypatch.setattr(WebPageChecker, '_respectful_request', lambda *_: response)
    checker = _build_checker()
    checker.crossref = None

    data, findings, url = checker.verify_reference(reference)
    result = project_verification_result(reference, data, findings, url, enrich_enabled=False)

    assert data is None
    assert count_raw_errors(findings) == counts
    assert result['status'] == expected_status
    if reason == 'url_access_failed':
        assert result['errors'][0]['verification_reason'] == reason
        assert result['errors'][0]['http_status'] == 403
        assert result['errors'][0]['sources_negative'] == 1
        assert result['authoritative_urls'] == []
    elif reason == 'authentication_required':
        assert result['warnings'][0]['verification_reason'] == reason
        assert result['warnings'][0]['authentication_url'] == reference['cited_url']
        assert result['authoritative_urls'] == []
    else:
        assert any(finding['error_type'] == 'url' for finding in result['errors'])


def test_force_all_databases_does_not_skip_url_reference():
    class RecordingNoMatchChecker:
        def __init__(self):
            self.calls = []

        def verify_reference(self, reference):
            self.calls.append(reference)
            return None, [], None

    checker = _build_checker()
    semantic_scholar = RecordingNoMatchChecker()
    checker.semantic_scholar = semantic_scholar
    checker.crossref = None

    _, _, url = checker._verify_reference_core(
        {
            'title': 'A web publication with searchable metadata',
            'authors': ['URL Reference'],
            'cited_url': 'https://example.org/publication',
        },
        force_all_databases=True,
    )

    assert len(semantic_scholar.calls) == 1
    assert url == 'https://example.org/publication'


def test_verify_reference_records_matched_database_from_local_checker():
    checker = _build_checker()
    checker.local_db = LocalMatchChecker()
    checker.semantic_scholar = None
    checker.crossref = None

    verified_data, errors, url = checker.verify_reference({"title": "Test title", "authors": []})

    assert errors == []
    assert url == "https://www.semanticscholar.org/paper/s2-match-id"
    assert verified_data["_matched_database"] == "Semantic Scholar"
    assert verified_data["_matched_checker"] == "local_s2"


def test_dnb_and_zdb_are_part_of_parallel_remote_fallbacks():
    checker = _build_checker()
    checker.crossref = None
    checker.openalex = None
    checker.open_library = None
    checker.dblp = None
    checker.acl_anthology = None
    checker.paperclip = None
    barrier = threading.Barrier(3)

    class ParallelNoMatchChecker:
        def verify_reference(self, reference):
            barrier.wait(timeout=1)
            return None, [], None

    class DnbMatchChecker(LocalMatchChecker):
        database_label = "DNB Catalogue"

        def verify_reference(self, reference):
            barrier.wait(timeout=1)
            return super().verify_reference(reference)

    checker.semantic_scholar = ParallelNoMatchChecker()
    checker.dnb = DnbMatchChecker()
    checker.zdb = ParallelNoMatchChecker()

    verified_data, errors, url = checker.verify_reference({
        "title": "Test title",
        "authors": [],
    })

    assert errors == []
    assert url == "https://www.semanticscholar.org/paper/s2-match-id"
    assert verified_data["_matched_checker"] == "dnb"
    assert verified_data["_matched_database"] == "DNB Catalogue"


def test_tib_is_selected_after_dnb_in_remote_priority():
    checker = _build_checker()
    checker.crossref = None
    checker.openalex = None
    checker.open_library = None
    checker.zdb = None
    checker.dblp = None
    checker.acl_anthology = None
    checker.paperclip = None
    checker.semantic_scholar = NoMatchChecker()
    calls = []

    class CatalogueMatchChecker:
        def __init__(self, key, label):
            self.key = key
            self.database_label = label

        def verify_reference(self, reference):
            calls.append(self.key)
            return ({"title": reference["title"], "ppn": self.key}, [], f"https://example/{self.key}")

    checker.dnb = CatalogueMatchChecker("dnb", "DNB Catalogue")
    checker.tib = CatalogueMatchChecker("tib", "TIB Catalogue")

    verified_data, errors, url = checker.verify_reference({"title": "Test title", "authors": []})

    assert set(calls) == {"dnb", "tib"}
    assert errors == []
    assert url == "https://example/dnb"
    assert verified_data["_matched_checker"] == "dnb"
    assert verified_data["_matched_database"] == "DNB Catalogue"


class CatalogueCandidateChecker:
    def __init__(self, label, data, findings=None, url=None):
        self.database_label = label
        self.data = data
        self.findings = findings or []
        self.url = url or f"https://example.org/{label.lower().replace(' ', '-')}"

    def verify_reference(self, reference):
        return dict(self.data), list(self.findings), self.url


def _catalogue_reconciliation_checker(events=None):
    checker = _build_checker()
    checker.local_db = None
    checker.local_db_checkers = []
    for name in (
        'semantic_scholar', 'crossref', 'openalex', 'econbiz', 'zdb', 'dblp',
        'acl_anthology', 'paperclip', 'openreview', 'springer_nature',
        'google_books', 'arxiv_citation',
    ):
        setattr(checker, name, None)
    checker.progress_callback = events.append if events is not None else None
    return checker


def test_catalogue_consensus_resolves_lay_nippa_corporate_author_conflict():
    events = []
    checker = _catalogue_reconciliation_checker(events)
    title = 'Management produktbegleitender Dienstleistungen'
    checker.dnb = CatalogueCandidateChecker(
        'DNB Catalogue',
        {
            'title': title,
            'authors': [{'name': 'Lay, Gunter'}],
            'corporate_contributors': [{
                'name': 'Fraunhofer-Institut für Systemtechnik und Innovationsforschung',
                'kind': 'organization',
                'marc_tag': '710',
            }],
            'year': 2005,
        },
        [{
            'warning_type': 'author',
            'warning_details': 'Author 2 mismatch: Michael Nippa vs Fraunhofer-Institut',
        }],
    )
    checker.tib = CatalogueCandidateChecker('TIB Catalogue', {
        'title': title,
        'authors': [{'name': 'Lay, Gunter'}, {'name': 'Nippa, Michael'}],
        'year': 2005,
    })
    checker.open_library = CatalogueCandidateChecker('Open Library', {
        'title': title,
        'authors': [{'name': 'Gunter Lay'}, {'name': 'Michael Nippa'}],
        'year': 2005,
    })

    data, findings, _ = checker._verify_reference_core({
        'title': title,
        'authors': ['Gunter Lay', 'Michael Nippa'],
        'year': 2005,
    }, force_all_databases=True)

    assert data['_matched_database'] == 'TIB Catalogue'
    assert data['_evidence_reconciliation']['decision'] == 'accept_cited_authors'
    assert set(data['_evidence_reconciliation']['supporting_sources']) == {
        'TIB Catalogue', 'Open Library',
    }
    assert not any(checker._finding_kind(item).startswith('author') for item in findings)
    assert any(
        item.get('info_type') == 'metadata_conflict'
        and 'Fraunhofer-Institut' in item.get('info_details', '')
        for item in findings
    )
    dnb_event = next(
        event for event in events
        if event.get('database') == 'dnb' and event.get('status') == 'metadata_conflict'
    )
    assert dnb_event['status'] == 'metadata_conflict'
    assert 'corporate contributor' in dnb_event['reason']


def test_search_all_preserves_year_warning_when_two_sources_agree_on_actual_year():
    checker = _catalogue_reconciliation_checker()
    title = 'Der Referenzmodellkatalog – Ein Instrument des Wissensmanagements'
    checker.semantic_scholar = CatalogueCandidateChecker('Semantic Scholar', {
        'title': title,
        'authors': [{'name': 'Peter Fettke'}, {'name': 'P. Loos'}],
        'year': 2001,
    }, [{
        'warning_type': 'author',
        'warning_details': 'Abbreviated author metadata',
    }])
    checker.dnb = CatalogueCandidateChecker('DNB Catalogue', {
        'title': title,
        'authors': [{'name': 'Fettke, Peter'}, {'name': 'Loos, Peter'}],
        'year': 2001,
    })
    checker.tib = None
    checker.open_library = None

    data, findings, _ = checker.verify_reference({
        'title': title,
        'authors': ['Peter Fettke', 'Peter Loos'],
        'year': 2002,
    }, force_all_databases=True)

    assert data['_matched_database'] == 'DNB Catalogue'
    year_warning = next(item for item in findings if item.get('warning_type') == 'year')
    assert year_warning['cited_value'] == '2002'
    assert year_warning['actual_value'] == '2001'
    assert {item['source'] for item in year_warning['source_years']} == {
        'Semantic Scholar', 'DNB Catalogue',
    }
    assert data['_publication_year_assessment']['classification'] == 'likely_citation_error'


@pytest.mark.parametrize('force_all_databases', [False, True])
@pytest.mark.parametrize('matching_doi', [False, True])
def test_kitchenham_title_identity_is_consistent_across_search_modes(force_all_databases, matching_doi):
    events = []
    checker = _catalogue_reconciliation_checker(events)
    checker.dnb = checker.tib = checker.open_library = None
    reference = {
        'title': 'Guidelines for performing Systematic Literature Reviews in software engineering',
        'authors': ['B. Kitchenham'],
        'year': 2007,
    }
    candidate = {
        'title': 'Protocol for a Tertiary study of Systematic Literature Reviews and Evidence-based Guidelines in IT and Software Engineering',
        'authors': ['B. Kitchenham', 'P. Brereton', 'D. Budgen', 'M. Turner', 'J. Bailey', 'S. Linkman'],
        'year': 2009,
    }
    if matching_doi:
        reference['doi'] = candidate['doi'] = '10.1000/identity-test'
    checker.semantic_scholar = CatalogueCandidateChecker('Semantic Scholar', candidate)

    data, findings, _ = checker._verify_reference_core(
        reference, force_all_databases=force_all_databases,
    )

    if matching_doi:
        assert data['title'] == candidate['title']
    else:
        assert data is None
        assert findings
        rejected = [event for event in events if event.get('status') == 'rejected_wrong_paper']
        assert len(rejected) == 1
        assert 'title similarity is only' in rejected[0]['reason']


def test_wrong_database_match_is_rejected_before_metadata_reconciliation():
    events = []
    checker = _catalogue_reconciliation_checker(events)
    checker.dnb = CatalogueCandidateChecker('DNB Catalogue', {
        'title': 'A completely different industrial economics book',
        'authors': [{'name': 'Another Person'}],
        'year': 2005,
    })
    checker.tib = CatalogueCandidateChecker('TIB Catalogue', {
        'title': 'Management produktbegleitender Dienstleistungen',
        'authors': [{'name': 'Gunter Lay'}, {'name': 'Michael Nippa'}],
        'year': 2005,
    })
    checker.open_library = None

    data, findings, _ = checker._verify_reference_core({
        'title': 'Management produktbegleitender Dienstleistungen',
        'authors': ['Gunter Lay', 'Michael Nippa'],
        'year': 2005,
    }, force_all_databases=True)

    assert data['_matched_database'] == 'TIB Catalogue'
    assert findings == []
    excluded = [event for event in events if event.get('status') == 'rejected_wrong_paper']
    assert len(excluded) == 1
    assert excluded[0]['database'] == 'dnb'
    assert 'title similarity' in excluded[0]['reason']


def test_llm_only_adjudicates_unresolved_candidates_that_pass_identity_gate():
    class RecordingProvider:
        def __init__(self):
            self.prompt = ''

        def _call_llm(self, prompt):
            self.prompt = prompt
            return ('{"decision":"accept_cited_authors","confidence":0.91,'
                    '"supporting_sources":["TIB Catalogue"],"explanation":"Supported"}')

    events = []
    checker = _catalogue_reconciliation_checker(events)
    provider = RecordingProvider()
    checker.llm_provider = provider
    reference = {
        'title': 'A well identified work with a sufficiently specific title',
        'authors': ['Ada Author', 'Bob Writer'],
        'year': 2024,
    }
    evidence = [
        checker._database_evidence('tib', ({
            'title': reference['title'], 'authors': reference['authors'], 'year': 2024,
        }, [], 'https://example.org/tib')),
        checker._database_evidence('dnb', ({
            'title': reference['title'], 'authors': ['Ada Author'], 'year': 2024,
        }, [{'warning_type': 'author', 'warning_details': 'Second author missing'}], 'https://example.org/dnb')),
        checker._database_evidence('open_library', ({
            'title': 'A different work', 'authors': ['Wrong Person'], 'year': 1990,
        }, [], 'https://example.org/wrong')),
    ]

    data, findings, _ = checker._reconcile_database_evidence(reference, evidence)

    assert data['_evidence_reconciliation']['llm_used'] is True
    assert data['_evidence_reconciliation']['decision'] == 'accept_cited_authors'
    assert 'A different work' not in provider.prompt
    assert not any(checker._finding_kind(item).startswith('author') for item in findings)
    assert any(event.get('status') == 'excluded_wrong_match' for event in events)


def test_econbiz_fulltext_evidence_is_verified(caplog):
    checker = _build_checker()
    checker.semantic_scholar = None
    checker.crossref = None
    checker.openalex = None
    checker.open_library = None
    checker.dnb = None
    checker.tib = None
    checker.zdb = None
    checker.dblp = None
    checker.acl_anthology = None
    checker.paperclip = None

    class EconBizEvidenceChecker:
        database_label = "EconBiz"

        def verify_reference(self, reference):
            return {
                "title": reference["title"],
                "authors": [{"name": "Jane Doe"}],
                "year": 2002,
                "_verification_basis": "econbiz_fulltext_evidence",
                "supporting_evidence_source": "EconBiz full-text search",
            }, [], "https://www.econbiz.de/Record/-/10005852170"

    checker.econbiz = EconBizEvidenceChecker()
    with caplog.at_level(logging.INFO, logger="refchecker.checkers.enhanced_hybrid_checker"):
        data, errors, url = checker.verify_reference({
            "title": "A chapter in an indexed proceedings volume",
            "authors": ["Jane Doe"],
            "year": 2002,
        })

    assert data is not None
    assert errors == []
    assert data["supporting_evidence_source"] == "EconBiz full-text search"
    assert data["_matched_database"] == "EconBiz"
    assert url == "https://www.econbiz.de/Record/-/10005852170"
    assert any(
        "stage=result database=econbiz status=verified_fulltext_evidence" in record.getMessage()
        for record in caplog.records
    )


def test_database_trace_reports_every_launched_database_and_final_selection(caplog):
    checker = _build_checker()
    checker.crossref = None
    checker.openalex = None
    checker.open_library = None
    checker.zdb = None
    checker.dblp = None
    checker.acl_anthology = None
    checker.paperclip = None
    checker.semantic_scholar = NoMatchChecker()
    checker.dnb = NoMatchChecker()
    checker.tib = LocalMatchChecker()

    with caplog.at_level(logging.INFO, logger="refchecker.checkers.enhanced_hybrid_checker"):
        verified_data, errors, _ = checker.verify_reference({"title": "Trace me", "authors": []})

    messages = [record.getMessage() for record in caplog.records]
    assert any("stage=verification_start" in message and "'dnb', 'tib'" in message for message in messages)
    for database in ("semantic_scholar", "dnb", "tib"):
        assert any(f"stage=request database={database}" in message for message in messages)
        assert any(f"stage=result database={database}" in message for message in messages)
    assert any(
        "stage=verification_final" in message and "matched_database='Semantic Scholar'" in message
        for message in messages
    )
    assert errors == []
    assert verified_data["_matched_checker"] == "tib"


def test_semantic_scholar_result_survives_dict_shaped_citation_fields():
    checker = _build_checker()
    checker.local_db = None
    checker.semantic_scholar = LocalMatchChecker()
    checker.crossref = None

    verified_data, errors, url = checker.verify_reference({
        "title": "Ontology in computer systems",
        "authors": ["V. A. Lapshin"],
        "doi": {"value": "10.1000/example"},
        "venue": {"text": "M.: Science World"},
    })

    assert verified_data is not None
    assert errors == []
    assert url == "https://www.semanticscholar.org/paper/s2-match-id"


def test_doi_mismatch_does_not_stop_search_before_exact_local_doi_match():
    checker = _build_checker()
    mismatching_checker = LocalDoiMismatchChecker()
    exact_checker = ExactDoiChecker()
    checker.local_db = mismatching_checker
    checker.local_db_checkers = [
        ("local_s2", "Semantic Scholar", mismatching_checker),
        ("local_crossref", "CrossRef", exact_checker),
    ]
    checker.semantic_scholar = None
    checker.crossref = None

    verified_data, errors, url = checker.verify_reference({
        "title": "A paper with both preprint and proceedings records",
        "authors": ["Ada Author"],
        "doi": "10.18653/v1/2024.emnlp-main.223",
    })

    assert mismatching_checker.called is True
    assert exact_checker.called is True
    assert errors == []
    assert verified_data["externalIds"]["DOI"] == "10.18653/v1/2024.emnlp-main.223"
    assert verified_data["_matched_database"] == "CrossRef"
    assert url == "https://doi.org/10.18653/v1/2024.emnlp-main.223"


def test_explicit_doi_uses_crossref_before_semantic_scholar_title_result():
    checker = _build_checker()
    crossref = ExactDoiChecker()
    semantic_scholar = LocalDoiMismatchChecker()
    checker.local_db = None
    checker.local_db_checkers = []
    checker.crossref = crossref
    checker.semantic_scholar = semantic_scholar

    verified_data, errors, _ = checker.verify_reference({
        "title": "A paper with both preprint and proceedings records",
        "authors": ["Ada Author"],
        "doi": "10.18653/v1/2024.emnlp-main.223",
    })

    assert crossref.called is True
    assert semantic_scholar.called is False
    assert errors == []
    assert verified_data["externalIds"]["DOI"] == "10.18653/v1/2024.emnlp-main.223"


def test_major_author_discrepancy_recognizes_no_matching_authors_error():
    checker = _build_checker()

    assert checker._has_major_author_discrepancy([
        {
            'error_type': 'author',
            'error_details': (
                'no matching authors:\n'
                '       cited:  Alice Example, Bob Example\n'
                '       actual: Carol Verified, Dave Verified'
            ),
            'ref_authors_correct': 'Carol Verified, Dave Verified',
        }
    ]) is True


def test_shared_postprocess_converts_arxiv_version_mismatch_to_warnings():
    checker = _build_checker()
    checker.local_db = LocalArxivMismatchChecker()
    checker.semantic_scholar = None
    checker.crossref = None
    checker.arxiv_citation = ArxivVersionWarningChecker()

    reference = {
        "title": "Detecting harmful memes with decoupled understanding and guided cot reasoning",
        "authors": ["Fengjun Pan", "Anh Tuan Luu", "Xiaobao Wu"],
        "year": 2025,
        "venue": "arXiv:2506.08477",
    }

    verified_data, errors, url = checker.verify_reference(reference)

    assert url == "https://arxiv.org/abs/2506.08477v1"
    assert verified_data["_matched_database"] == "ArXiv"
    assert all("warning_type" in error for error in errors)
    assert not any("error_type" in error for error in errors)
    assert any(error["warning_type"] == "title (v1 vs v2 update)" for error in errors)
    assert any(error["warning_type"] == "author (v1 vs v2 update)" for error in errors)


def test_arxiv_title_search_precedes_loose_openreview_match():
    checker = _build_checker()
    checker.arxiv_citation = ArxivTitleSearchChecker()
    checker.local_db = NoMatchChecker()
    checker.semantic_scholar = NoMatchChecker()
    checker.crossref = None
    checker.openreview = WrongOpenReviewChecker()

    reference = {
        'title': 'Retrospective for the dynamics sensorium competition for predicting large-scale mouse primary visual cortex activity from videos',
        'authors': ['Polina Turishcheva', 'Paul Fahey', 'Michaela Vystrčilová'],
        'year': 2024,
        'venue': 'Advances in Neural Information Processing Systems',
    }

    verified_data, errors, url = checker.verify_reference(reference)

    assert errors == []
    assert url == 'https://arxiv.org/abs/2407.09100'
    assert verified_data['_matched_database'] == 'ArXiv'
    assert verified_data['_matched_checker'] == 'arxiv_citation'
    assert checker.openreview.called is False


class LocalMissChecker:
    """Local S2 DB that finds nothing, with configurable ingest completeness."""

    database_label = "Semantic Scholar"
    database_key = "local_s2"

    def __init__(self, complete):
        self._complete = complete

    def has_complete_coverage(self):
        return self._complete

    def verify_reference(self, reference):
        return None, [], None


class RecordingSemanticScholar:
    def __init__(self):
        self.calls = 0

    def verify_reference(self, reference):
        self.calls += 1
        return None, [], None


def test_incomplete_local_db_miss_still_queries_semantic_scholar():
    """A DB mid-bootstrap answers 'not found' for papers it hasn't ingested;
    trusting that would turn coverage gaps into wrong verdicts."""
    checker = _build_checker()
    checker.local_db = LocalMissChecker(complete=False)
    checker.crossref = None
    recorder = RecordingSemanticScholar()
    checker.semantic_scholar = recorder

    checker.verify_reference({"title": "Some uningested paper", "authors": []})

    assert recorder.calls == 1


def test_complete_local_db_miss_skips_semantic_scholar():
    """The skip-SS optimization must survive for a fully ingested snapshot."""
    checker = _build_checker()
    checker.local_db = LocalMissChecker(complete=True)
    checker.crossref = None
    recorder = RecordingSemanticScholar()
    checker.semantic_scholar = recorder

    checker.verify_reference({"title": "Some uningested paper", "authors": []})

    assert recorder.calls == 0


@pytest.mark.parametrize('doi_field', ['doi', 'url', 'cited_url'])
@pytest.mark.parametrize('crossref_status', ['match', 'incomplete', 'miss', 'disabled'])
def test_publication_doi_precedes_local_merged_preprint(doi_field, crossref_status):
    from refchecker.checkers.crossref import CrossRefReferenceChecker

    checker = _build_checker()
    checker._cross_verify_secondary = Mock()
    doi = '10.1109/cvpr.2016.90'
    title = 'Deep Residual Learning for Image Recognition'
    doi_url = f'https://doi.org/{doi}'
    local = Mock(spec=['verify_reference'])
    local.verify_reference.return_value = ({
        'title': title, 'authors': [{'name': 'Kaiming He'}], 'year': 2015,
        'venue': 'IEEE Conference on Computer Vision and Pattern Recognition',
        'externalIds': {'DOI': doi, 'ArXiv': '1512.03385'},
    }, [], doi_url)
    checker.local_db_checkers = [('local_s2', 'Semantic Scholar', local)]
    crossref = CrossRefReferenceChecker()
    crossref_work = {
        'DOI': doi, 'title': title, 'author': [{'given': 'Kaiming', 'family': 'He'}],
        'issued': {'date-parts': [[2016]]}, 'URL': doi_url,
    }
    if crossref_status == 'incomplete':
        crossref_work.pop('author')
    checker.crossref = None if crossref_status == 'disabled' else crossref
    reference = {'title': title, 'authors': ['Kaiming He'], 'year': 2015,
                 doi_field: doi if doi_field == 'doi' else doi_url}

    work = crossref_work if crossref_status in ('match', 'incomplete') else None
    with (
        patch.object(crossref, 'get_work_by_doi', return_value=work) as lookup,
        patch.object(crossref, 'search_works', return_value=[]),
        patch.object(crossref, 'search_works_bibliographic', return_value=[]),
        patch('refchecker.utils.publication_years.reconcile_publication_year') as reconcile,
    ):
        data, errors, _ = checker.verify_reference(reference)

    if crossref_status == 'disabled':
        lookup.assert_not_called()
    else:
        lookup.assert_called_once_with(doi)
    reconcile.assert_not_called()
    assert data['_matched_checker'] == ('crossref' if crossref_status == 'match' else 'local_s2')
    assert [issue['ref_year_correct'] for issue in errors if issue.get('warning_type') == 'year'] == (
        [2016] if crossref_status == 'match' else []
    )


@pytest.mark.parametrize('arxiv_doi, locator', [
    ('10.48550/arXiv.1512.03385', 'doi'), ('10.48550/arXiv.1512.03385', 'url'), (None, 'url'),
])
def test_explicit_arxiv_enrichment_preserves_version_metadata(arxiv_doi, locator):
    from refchecker.checkers.arxiv_citation import ArXivCitationChecker

    checker = _build_checker()
    checker._cross_verify_secondary = Mock()
    title = 'Deep Residual Learning for Image Recognition'
    arxiv_url = 'https://arxiv.org/abs/1512.03385'
    authors = [{'name': 'Kaiming He'}]
    arxiv_ids = {'ArXiv': '1512.03385'}
    if arxiv_doi:
        arxiv_ids['DOI'] = arxiv_doi
    arxiv = ArXivCitationChecker()
    arxiv.verify_reference = Mock(return_value=({
        'title': title, 'authors': authors, 'year': 2015, 'venue': 'arXiv', 'externalIds': arxiv_ids,
    }, [], arxiv_url))
    checker.arxiv_citation = arxiv
    s2_url = 'https://www.semanticscholar.org/paper/s2-id'
    s2 = Mock(spec=['verify_reference', 'get_venue_from_paper_data'])
    publication_venue = 'IEEE Conference on Computer Vision and Pattern Recognition'
    s2.get_venue_from_paper_data.return_value = publication_venue
    s2.verify_reference.return_value = ({
        'title': title, 'authors': authors, 'year': 2016, 'venue': publication_venue,
        'paperId': 's2-id', 'externalIds': {'DOI': '10.1109/cvpr.2016.90'},
    }, [], s2_url)
    checker.semantic_scholar = s2

    data, errors, url = checker.verify_reference({
        'title': title, 'authors': ['Kaiming He'], 'venue': 'arXiv', 'year': 2015,
        locator: arxiv_doi if locator == 'doi' else arxiv_url,
    })

    arxiv.verify_reference.assert_called_once()
    assert url == arxiv_url
    assert data['year'] == 2015
    assert data['venue'] == 'arXiv'
    assert data['externalIds'].get('DOI') == arxiv_doi
    if locator == 'doi':
        assert 'S2PaperId' not in data['externalIds']  # conflicting publication DOI
    else:
        assert data['externalIds']['S2PaperId'] == 's2-id'
        assert data['_semantic_scholar_url'] == s2_url
    assert 'S2PaperId' not in arxiv_ids
    assert errors == []


@pytest.mark.parametrize('cited_year, expected_warnings', [(2015, [2016]), (2016, []), (2017, [])])
def test_search_all_keeps_exact_publication_doi_year(cited_year, expected_warnings):
    from refchecker.checkers.crossref import CrossRefReferenceChecker

    checker = _build_checker()
    checker._cross_verify_secondary = Mock()
    doi = '10.1109/cvpr.2016.90'
    url = f'https://doi.org/{doi}'
    title = 'Deep Residual Learning for Image Recognition'
    preprint_year = 2016 if cited_year == 2017 else 2015
    local = Mock(spec=['verify_reference'])
    local.verify_reference.return_value = ({
        'title': title, 'authors': [{'name': 'Kaiming He'}], 'year': preprint_year,
        'externalIds': {'DOI': doi, 'ArXiv': '1512.03385'},
    }, [], url)
    checker.local_db_checkers = [('local_s2', 'Semantic Scholar', local)]
    checker.semantic_scholar = Mock(spec=['verify_reference'])
    checker.semantic_scholar.verify_reference.return_value = (None, [], None)
    checker.google_books = Mock(spec=['verify_reference'])
    checker.google_books.verify_reference.return_value = (None, [], None)
    checker.crossref = CrossRefReferenceChecker()
    work = {
        'DOI': doi, 'title': title, 'author': [{'given': 'Kaiming', 'family': 'He'}],
        'published-print': {'date-parts': [[2016]]}, 'published-online': {'date-parts': [[2017]]},
        'URL': url,
    }
    reference = {'title': title, 'authors': ['Kaiming He'], 'year': cited_year, 'doi': doi}

    with (
        patch.object(checker.crossref, 'get_work_by_doi', return_value=work) as lookup,
        patch('refchecker.utils.publication_years.reconcile_publication_year') as reconcile,
    ):
        data, issues, result_url = checker.verify_reference(reference, force_all_databases=True)

    lookup.assert_called_once_with(doi)
    local.verify_reference.assert_called_once()
    checker.semantic_scholar.verify_reference.assert_called_once()
    checker.google_books.verify_reference.assert_called_once()
    reconcile.assert_not_called()
    assert result_url == url
    assert data['_matched_checker'] == 'crossref'
    assert data['year'] == 2016
    assert [issue['ref_year_correct'] for issue in issues if issue.get('warning_type') == 'year'] == expected_warnings
    assert all(issue.get('info_type') != 'publication_year_discrepancy' for issue in issues)


@pytest.mark.parametrize('force_all_databases', [False, True])
@pytest.mark.parametrize('doi_field, arxiv_field', [('doi', 'url'), ('cited_url', 'url'), ('url', 'cited_url')])
def test_publication_doi_takes_priority_over_ancillary_arxiv_url(doi_field, arxiv_field, force_all_databases):
    from refchecker.checkers.arxiv_citation import ArXivCitationChecker
    from refchecker.checkers.crossref import CrossRefReferenceChecker

    checker = _build_checker()
    checker._cross_verify_secondary = Mock()
    doi = '10.1109/cvpr.2016.90'
    doi_url = f'https://doi.org/{doi}'
    arxiv_url = 'https://arxiv.org/abs/1512.03385'
    title = 'Deep Residual Learning for Image Recognition'
    checker.crossref = CrossRefReferenceChecker()
    checker.arxiv_citation = ArXivCitationChecker()
    work = {
        'DOI': doi, 'title': title, 'author': [{'given': 'Kaiming', 'family': 'He'}],
        'issued': {'date-parts': [[2016]]}, 'URL': doi_url,
    }
    # ArXiv version reporting must not replace the publication during shared postprocessing either.
    arxiv_result = ({
        'title': title, 'authors': [{'name': 'Kaiming He'}], 'year': 2015,
        'externalIds': {'ArXiv': '1512.03385'},
    }, [{'warning_type': 'year (version update)'}], arxiv_url)
    reference = {
        'title': title, 'authors': ['Kaiming He'], 'year': 2015,
        doi_field: doi if doi_field == 'doi' else doi_url, arxiv_field: arxiv_url,
    }
    assert checker.arxiv_citation.is_arxiv_reference(reference)

    with (
        patch.object(checker.crossref, 'get_work_by_doi', return_value=work) as lookup,
        patch.object(checker.arxiv_citation, 'verify_reference', return_value=arxiv_result),
        patch('refchecker.utils.publication_years.reconcile_publication_year'),
    ):
        data, issues, url = checker.verify_reference(reference, force_all_databases=force_all_databases)

    lookup.assert_called_once_with(doi)
    assert url == doi_url
    assert data['_matched_checker'] == 'crossref'
    assert data['year'] == 2016
    assert [issue['ref_year_correct'] for issue in issues if issue.get('warning_type') == 'year'] == [2016]


@pytest.mark.parametrize('force_all_databases', [False, True])
def test_datacite_is_a_doi_gated_fallback(force_all_databases):
    checker = _build_checker()
    checker.crossref = NoMatchChecker()
    data = {'title': 'Archived dataset', 'doi': '10.5281/zenodo.123', 'authors': ['Ada Author']}
    url = 'https://zenodo.org/records/123'
    checker.datacite = Mock(database_label='DataCite')
    checker.datacite.verify_reference.return_value = (data, [], url)
    reference = {'title': data['title'], 'DOI': ' DOI:10.5281/ZENODO.123 '}

    verified, errors, verified_url = checker.verify_reference(reference, force_all_databases)

    assert verified['_matched_database'] == 'DataCite'
    assert verified['_matched_checker'] == 'datacite'
    assert errors == []
    assert verified_url == url
    assert checker.datacite.verify_reference.call_args.args[0]['doi'] == data['doi']
    checker.datacite.reset_mock()
    _, errors, _ = checker.verify_reference({'title': 'No DOI'}, force_all_databases)
    checker.datacite.verify_reference.assert_not_called()
    assert errors[0]['sources_negative'] == 2


@pytest.mark.parametrize('http_status,html,expected_reason', [
    (200, '<title>Archived dataset</title>', None),
    (403, '', 'url_access_failed'),
    (200, '<title>Please log in to DSpace</title>', 'authentication_required'),
])
def test_doi_only_uses_webpage_fallback_with_existing_access_handling(
    monkeypatch, http_status, html, expected_reason,
):
    from refchecker.checkers.webpage_checker import WebPageChecker

    checker = _build_checker()
    checker.crossref = None
    response = requests.Response()
    response.status_code = http_status
    response.url = 'https://example.org/landing'
    response._content = html.encode()
    request = Mock(return_value=response)
    monkeypatch.setattr(WebPageChecker, '_request_public_landing_page', request)
    reference = {'title': 'Archived dataset', 'doi': 'DOI:10.5281/DATA(SET)'}

    data, errors, _ = checker.verify_reference(reference)

    request.assert_called_once_with('https://doi.org/10.5281/data%28set%29')
    assert 'url' not in reference and 'cited_url' not in reference
    if expected_reason:
        assert data is None
        assert errors[0]['verification_reason'] == expected_reason
    else:
        assert data['_matched_database'] == 'Web Page'
        assert errors == []


def test_datacite_timeout_is_distinguished_from_a_negative_lookup():
    checker = _build_checker()
    checker.crossref = None
    checker.datacite = TimeoutChecker()
    # An explicit non-web URL suppresses synthesis, letting us inspect the
    # search finding independently of the outcome of a resolver request.
    _, errors, _ = checker.verify_reference({
        'title': 'Archived dataset', 'doi': '10.5281/zenodo.123', 'cited_url': 'ftp://example.org/data',
    })

    assert errors[0]['verification_reason'] == 'provider_failure'
    assert 'DataCite' in errors[0]['error_details']
    assert errors[0]['sources_checked'] == 2
    assert errors[0]['sources_negative'] == 1


def test_doi_web_fallback_does_not_verify_on_pdf_reachability_alone(monkeypatch):
    from refchecker.checkers.webpage_checker import WebPageChecker

    checker = _build_checker()
    checker.crossref = None
    response = requests.Response()
    response.status_code = 200
    response.url = 'https://example.org/download'
    response._content = b'%PDF-1.4 test'
    monkeypatch.setattr(WebPageChecker, '_request_public_landing_page', Mock(return_value=response))

    data, errors, _ = checker.verify_reference({'title': 'Archived dataset', 'doi': '10.5281/data'})

    assert data is None
    assert errors[0]['error_type'] == 'unverified'


def test_datacite_cannot_displace_a_successful_local_lookup(monkeypatch):
    from refchecker.checkers.webpage_checker import WebPageChecker

    checker = _build_checker()
    checker.local_db = Mock(database_label='Semantic Scholar')
    checker.datacite = Mock()
    request = Mock()
    monkeypatch.setattr(WebPageChecker, '_request_public_landing_page', request)
    reference = {'title': 'Archived dataset', 'authors': ['Ada Author'], 'year': 2024, 'doi': '10.5281/data'}
    checker.local_db.verify_reference.return_value = (dict(reference), [], 'https://example.org/dataset')

    data, errors, _ = checker.verify_reference(reference)

    assert data['_matched_checker'] == 'local_s2'
    assert errors == []
    checker.datacite.verify_reference.assert_not_called()
    request.assert_not_called()
