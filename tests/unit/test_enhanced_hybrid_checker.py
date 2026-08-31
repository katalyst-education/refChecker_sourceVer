import logging
import threading

import requests
import pytest
from unittest.mock import patch

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
