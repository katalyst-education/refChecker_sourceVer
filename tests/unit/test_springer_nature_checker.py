import logging
from types import SimpleNamespace
from unittest.mock import Mock, patch

from refchecker.checkers.enhanced_hybrid_checker import EnhancedHybridReferenceChecker
from refchecker.checkers.springer_nature import SpringerNatureReferenceChecker


def _article_record():
    return {
        "contentType": "Article",
        "identifier": "doi:10.1038/example",
        "title": "A precise metadata result",
        "creators": [
            {"creator": "Author, Ada"},
            {"creator": "Writer, Bob"},
        ],
        "publicationName": "Nature Examples",
        "publicationDate": "2024-05-03",
        "publicationType": "Journal",
        "genre": ["OriginalPaper", "Article"],
        "publisherName": "Springer Nature",
        "doi": "10.1038/example",
        "url": [
            {"format": "pdf", "value": "https://example.test/paper.pdf"},
            {"format": "html", "value": "https://example.test/paper"},
        ],
    }


def _review_record():
    record = _article_record()
    record.update({
        "title": "Business Model Generation",
        "doi": "10.1108/03684921211261761",
        "identifier": "doi:10.1108/03684921211261761",
        "publicationName": "Kybernetes",
        "publicationDate": "2012-06-08",
        "genre": ["BookReview"],
    })
    return record


def test_meta_v2_request_uses_key_without_logging_it(monkeypatch, caplog, tmp_path):
    monkeypatch.setenv("REFCHECKER_SPRINGER_NATURE_RATE_LIMIT_DELAY", "0")
    response = Mock(status_code=200)
    response.json.return_value = {"records": [_article_record()]}
    response.raise_for_status.return_value = None

    with caplog.at_level(logging.INFO), patch(
        "refchecker.checkers.springer_nature.requests.get", return_value=response
    ) as get:
        checker = SpringerNatureReferenceChecker(
            api_key="private-springer-key",
            quota_state_path=str(tmp_path / "springer-quota.sqlite3"),
        )
        monkeypatch.setattr(checker, "_wait_for_slot", lambda: None)
        records = checker.search_records('title:"A precise metadata result"')

    assert records == [_article_record()]
    assert get.call_args.args[0] == "https://api.springernature.com/meta/v2/json"
    assert get.call_args.kwargs["params"] == {
        "api_key": "private-springer-key",
        "q": 'title:"A precise metadata result"',
        "s": 1,
        "p": 10,
    }
    assert "private-springer-key" not in "\n".join(
        record.getMessage() for record in caplog.records
    )


def test_rolling_daily_limit_is_shared_across_instances(tmp_path, monkeypatch):
    state_path = tmp_path / "springer-quota.sqlite3"
    monkeypatch.setattr("refchecker.checkers.springer_nature.time.time", lambda: 1_800_000_000.0)
    first = SpringerNatureReferenceChecker(
        api_key="shared-key",
        daily_request_limit=2,
        minute_request_limit=10,
        quota_state_path=str(state_path),
    )
    second = SpringerNatureReferenceChecker(
        api_key="shared-key",
        daily_request_limit=2,
        minute_request_limit=10,
        quota_state_path=str(state_path),
    )

    assert first._reserve_request() == (True, "ok", 1)
    assert second._reserve_request() == (True, "ok", 0)
    assert first._reserve_request() == (False, "daily_limit", 0)
    assert b"shared-key" not in state_path.read_bytes()


def test_rolling_minute_limit_is_shared_across_instances(tmp_path, monkeypatch):
    state_path = tmp_path / "springer-quota.sqlite3"
    monkeypatch.setattr("refchecker.checkers.springer_nature.time.time", lambda: 1_800_000_000.0)
    checker = SpringerNatureReferenceChecker(
        api_key="shared-key",
        daily_request_limit=10,
        minute_request_limit=2,
        quota_state_path=str(state_path),
    )

    assert checker._reserve_request()[0] is True
    assert checker._reserve_request()[0] is True
    allowed, reason, retry_after = checker._reserve_request()
    assert allowed is False
    assert reason == "minute_limit"
    assert retry_after == 61


def test_429_starts_cooldown_without_retrying(tmp_path, monkeypatch):
    response = Mock(status_code=429, headers={"Retry-After": "120"})
    checker = SpringerNatureReferenceChecker(
        api_key="key",
        quota_state_path=str(tmp_path / "springer-quota.sqlite3"),
    )
    monkeypatch.setattr(checker, "_wait_for_slot", lambda: None)

    with patch("refchecker.checkers.springer_nature.requests.get", return_value=response) as get:
        assert checker.search_records('title:"limited"') == []
        assert checker.search_records('title:"another"') == []

    assert get.call_count == 1


def test_403_content_restriction_is_not_retried(tmp_path, monkeypatch):
    response = Mock(status_code=403, headers={})
    checker = SpringerNatureReferenceChecker(
        api_key="limited-key",
        quota_state_path=str(tmp_path / "springer-quota.sqlite3"),
    )
    monkeypatch.setattr(checker, "_wait_for_slot", lambda: None)

    with patch("refchecker.checkers.springer_nature.requests.get", return_value=response) as get:
        assert checker.search_records('"restricted record"') == []

    assert get.call_count == 1


def test_title_search_uses_basic_plan_exact_phrases():
    query = SpringerNatureReferenceChecker._query_for_reference({
        "title": "A precise metadata result",
        "authors": ["Ada Author"],
    })
    assert query == '"A precise metadata result" "Author"'


def test_article_match_normalises_publisher_metadata(monkeypatch):
    checker = SpringerNatureReferenceChecker(api_key="key")
    monkeypatch.setattr(checker, "search_records", lambda _query: [_article_record()])

    data, errors, url = checker.verify_reference({
        "title": "A precise metadata result",
        "authors": ["Ada Author", "Bob Writer"],
        "year": 2024,
        "journal": "Nature Examples",
    })

    assert errors == []
    assert data["doi"] == "10.1038/example"
    assert data["publication_year"] == 2024
    assert data["authors"] == [{"name": "Author, Ada"}, {"name": "Writer, Bob"}]
    assert data["genre"] == ["OriginalPaper", "Article"]
    assert data["_springer_nature_is_review"] is False
    assert url == "https://example.test/paper"


def test_book_review_is_not_accepted_as_the_underlying_book(monkeypatch):
    checker = SpringerNatureReferenceChecker(api_key="key")
    monkeypatch.setattr(checker, "search_records", lambda _query: [_review_record()])

    result = checker.verify_reference({
        "title": "Business Model Generation",
        "authors": ["Alexander Osterwalder", "Yves Pigneur"],
        "year": 2011,
        "publisher": "Campus Verlag",
        "type": "book",
    })

    assert result == (None, [], None)


def test_hybrid_annotates_springer_nature_source():
    checker = EnhancedHybridReferenceChecker.__new__(EnhancedHybridReferenceChecker)
    data = checker._annotate_match_source(
        {"title": "A precise metadata result"},
        "springer_nature",
        object(),
    )
    assert data["_matched_checker"] == "springer_nature"
    assert data["_matched_database"] == "Springer Nature"


def test_environment_key_enables_hybrid_checker(monkeypatch):
    monkeypatch.setenv("SPRINGER_NATURE_API_KEY", "env-key")
    created = {}

    def fake_initialize(self, module_name, class_name, log_name, *args, **kwargs):
        if module_name == "springer_nature":
            created["kwargs"] = kwargs
            return SimpleNamespace()
        return None

    monkeypatch.setattr(EnhancedHybridReferenceChecker, "_initialize_checker", fake_initialize)
    checker = EnhancedHybridReferenceChecker(
        enable_openalex=False,
        enable_crossref=False,
        enable_open_library=False,
        enable_econbiz=False,
        enable_dnb=False,
        enable_tib=False,
        enable_zdb=False,
        enable_google_books=False,
        enable_arxiv_citation=False,
        enable_acl_anthology=False,
        enable_paperclip=False,
    )

    assert checker.springer_nature is not None
    assert created["kwargs"]["api_key"] is None


def _routing_checker():
    with patch.object(EnhancedHybridReferenceChecker, "_initialize_checker", return_value=None):
        checker = EnhancedHybridReferenceChecker(
            enable_openalex=False,
            enable_crossref=False,
            enable_open_library=False,
            enable_econbiz=False,
            enable_dnb=False,
            enable_tib=False,
            enable_zdb=False,
            enable_google_books=False,
            enable_arxiv_citation=False,
            enable_acl_anthology=False,
            enable_paperclip=False,
        )
    checker.local_db = None
    checker.crossref = None
    checker.openalex = None
    checker.open_library = None
    checker.econbiz = None
    checker.dnb = None
    checker.tib = None
    checker.zdb = None
    checker.dblp = None
    checker.acl_anthology = None
    checker.openreview = None
    checker.paperclip = None
    checker.google_books = None
    return checker


class _RecordingProvider:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def verify_reference(self, reference):
        self.calls.append(reference)
        return self.result


def test_complete_primary_result_does_not_query_springer():
    checker = _routing_checker()
    reference = {"title": "Already verified", "authors": ["Ada Author"]}
    checker.semantic_scholar = _RecordingProvider((
        {"title": reference["title"], "authors": [{"name": "Ada Author"}]},
        [],
        "https://example.test/primary",
    ))
    checker.springer_nature = _RecordingProvider((None, [], None))

    data, errors, url = checker.verify_reference(reference)

    assert data["title"] == "Already verified"
    assert errors == []
    assert url == "https://example.test/primary"
    assert checker.springer_nature.calls == []


def test_springer_is_queried_after_primary_sources_do_not_match():
    checker = _routing_checker()
    reference = {"title": "Needs publisher fallback", "authors": ["Ada Author"]}
    checker.semantic_scholar = _RecordingProvider((None, [], None))
    checker.springer_nature = _RecordingProvider((
        {"title": reference["title"], "authors": [{"name": "Ada Author"}]},
        [],
        "https://example.test/springer",
    ))

    data, errors, url = checker.verify_reference(reference)

    assert data["_matched_checker"] == "springer_nature"
    assert data["_matched_database"] == "Springer Nature"
    assert errors == []
    assert url == "https://example.test/springer"
    assert len(checker.springer_nature.calls) == 1


def test_search_all_still_queries_springer_after_primary_match():
    checker = _routing_checker()
    reference = {"title": "Compare every source", "authors": ["Ada Author"]}
    checker.semantic_scholar = _RecordingProvider((
        {"title": reference["title"], "authors": [{"name": "Ada Author"}]},
        [],
        "https://example.test/primary",
    ))
    checker.springer_nature = _RecordingProvider((None, [], None))

    checker._verify_reference_core(reference, force_all_databases=True)

    assert len(checker.springer_nature.calls) == 1
