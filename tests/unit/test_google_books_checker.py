import logging
from unittest.mock import Mock, patch

from refchecker.checkers.google_books import GoogleBooksReferenceChecker
from refchecker.checkers.enhanced_hybrid_checker import EnhancedHybridReferenceChecker


def _google_volume():
    return {
        "id": "book-id",
        "volumeInfo": {
            "title": "The Hobbit",
            "subtitle": "There and Back Again",
            "authors": ["J. R. R. Tolkien"],
            "publisher": "George Allen & Unwin",
            "publishedDate": "1937-09-21",
            "industryIdentifiers": [
                {"type": "ISBN_13", "identifier": "9780007525492"},
            ],
            "canonicalVolumeLink": "https://books.google.com/books?id=book-id",
            "language": "en",
        },
    }


def _google_magazine():
    return {
        "id": "magazine-id",
        "volumeInfo": {
            "title": "Example Magazine",
            "authors": ["Example Editors"],
            "publishedDate": "2025-06",
            "printType": "MAGAZINE",
            "canonicalVolumeLink": "https://books.google.com/books?id=magazine-id",
        },
    }


def test_google_books_uses_header_book_filter_and_normalises_result(monkeypatch, caplog):
    monkeypatch.setenv("REFCHECKER_GOOGLE_BOOKS_RATE_LIMIT_DELAY", "0")
    response = Mock(status_code=200)
    response.json.return_value = {"items": [_google_volume()]}
    response.raise_for_status.return_value = None

    with caplog.at_level(logging.INFO), patch(
        "refchecker.checkers.google_books.requests.get", return_value=response
    ) as get:
        checker = GoogleBooksReferenceChecker(api_key="books-key")
        data, errors, url = checker.verify_reference({
            "title": "The Hobbit",
            "authors": ["J. R. R. Tolkien"],
            "year": 1937,
            "isbn": "978-0-00-752549-2",
            "type": "book",
        })

    assert errors == []
    assert data["google_books_id"] == "book-id"
    assert data["publication_year"] == 1937
    assert data["authors"] == [{"name": "J. R. R. Tolkien"}]
    assert url == "https://books.google.com/books?id=book-id"
    _, kwargs = get.call_args
    assert kwargs["headers"]["x-goog-api-key"] == "books-key"
    assert "key" not in kwargs["params"]
    assert kwargs["params"]["q"] == "isbn:9780007525492"
    assert kwargs["params"]["printType"] == "books"
    assert kwargs["params"]["maxResults"] <= 40
    trace = "\n".join(record.getMessage() for record in caplog.records)
    assert "GOOGLE_BOOKS_API_TRACE event=request" in trace
    assert "event=response print_type=books status=200" in trace
    assert "event=results print_type=books count=1" in trace
    assert "event=matched print_type=books" in trace
    assert "books-key" not in trace


def test_google_books_queries_explicit_magazines_with_magazine_filter(monkeypatch):
    monkeypatch.setenv("REFCHECKER_GOOGLE_BOOKS_RATE_LIMIT_DELAY", "0")
    response = Mock(status_code=200)
    response.json.return_value = {"items": [_google_magazine()]}
    response.raise_for_status.return_value = None

    with patch("refchecker.checkers.google_books.requests.get", return_value=response) as get:
        checker = GoogleBooksReferenceChecker(api_key="books-key", include_magazines=True)
        data, errors, url = checker.verify_reference({
            "title": "Example Magazine",
            "authors": ["Example Editors"],
            "year": 2025,
            "type": "magazine",
        })

    assert errors == []
    assert data["google_books_id"] == "magazine-id"
    assert data["print_type"] == "MAGAZINE"
    assert url == "https://books.google.com/books?id=magazine-id"
    assert get.call_args.kwargs["params"]["printType"] == "magazines"


def test_google_books_magazine_option_can_disable_requests():
    checker = GoogleBooksReferenceChecker(api_key="books-key", include_magazines=False)

    with patch("refchecker.checkers.google_books.requests.get") as get:
        result = checker.verify_reference({"title": "Example Magazine", "type": "magazine"})

    assert result == (None, [], None)
    get.assert_not_called()


def test_google_books_matches_umlaut_title_against_transliterated_citation(monkeypatch):
    monkeypatch.setenv("REFCHECKER_GOOGLE_BOOKS_RATE_LIMIT_DELAY", "0")
    response = Mock(status_code=200)
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "items": [
            {
                "id": "FcpuBAAAQBAJ",
                "volumeInfo": {
                    "title": "Integriertes Gesch\u00e4ftsmodell",
                    "subtitle": "Anwendung des St. Galler Management-Konzepts im Gesch\u00e4ftsmodellkontext",
                    "authors": ["Oliver D. Doleski"],
                    "publishedDate": "2014",
                    "canonicalVolumeLink": "https://books.google.com/books?id=FcpuBAAAQBAJ",
                },
            }
        ]
    }

    with patch("refchecker.checkers.google_books.requests.get", return_value=response):
        checker = GoogleBooksReferenceChecker(api_key="books-key")
        data, errors, url = checker.verify_reference({
            "title": "Integriertes Geschaeftsmodell. Anwendung des St. Galler Management-Konzepts im Geschaeftsmodellkontext",
            "authors": ["Oliver D. Doleski"],
            "year": 2014,
            "type": "book",
        })

    assert data["google_books_id"] == "FcpuBAAAQBAJ"
    assert errors == []
    assert url == "https://books.google.com/books?id=FcpuBAAAQBAJ"


def test_forced_google_books_search_uses_all_print_types_for_an_article(monkeypatch):
    monkeypatch.setenv("REFCHECKER_GOOGLE_BOOKS_RATE_LIMIT_DELAY", "0")
    response = Mock(status_code=200)
    response.json.return_value = {"items": []}
    response.raise_for_status.return_value = None

    with patch("refchecker.checkers.google_books.requests.get", return_value=response) as get:
        checker = GoogleBooksReferenceChecker(api_key="books-key")
        checker.verify_reference({
            "title": "An ordinary article",
            "type": "article",
            "_google_books_force_all": True,
        })

    assert get.call_args.kwargs["params"]["printType"] == "all"


def test_google_books_logs_ranked_candidates_before_similarity_rejection(monkeypatch, caplog):
    monkeypatch.setenv("REFCHECKER_GOOGLE_BOOKS_RATE_LIMIT_DELAY", "0")
    response = Mock(status_code=200)
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "items": [
            {
                "id": "near-miss",
                "volumeInfo": {
                    "title": "Not the cited title",
                    "authors": ["Wrong Author"],
                    "publishedDate": "2019",
                },
            },
            {
                "id": "far-miss",
                "volumeInfo": {
                    "title": "Completely different work",
                    "authors": ["Another Author"],
                    "publishedDate": "2001",
                },
            },
        ]
    }
    score_by_title = {
        "Not the cited title": 0.767,
        "Completely different work": 0.421,
    }

    def fake_find_best_match(search_results, *_args, **_kwargs):
        if not search_results:
            return None, 0.0
        ranked = sorted(
            search_results,
            key=lambda item: score_by_title.get(item.get("title", ""), 0.0),
            reverse=True,
        )
        best = ranked[0]
        return best, score_by_title.get(best.get("title", ""), 0.0)

    with caplog.at_level(logging.INFO), patch(
        "refchecker.checkers.google_books.requests.get", return_value=response
    ), patch(
        "refchecker.checkers.google_books.find_best_match",
        side_effect=fake_find_best_match,
    ):
        checker = GoogleBooksReferenceChecker(api_key="books-key")
        data, errors, url = checker.verify_reference({
            "title": "Expected citation title",
            "authors": ["Cited Author"],
            "year": 2024,
            "type": "book",
        })

    assert (data, errors, url) == (None, [], None)
    trace = "\n".join(record.getMessage() for record in caplog.records)
    assert "GOOGLE_BOOKS_API_TRACE event=no_match_candidates" in trace
    assert "Not the cited title" in trace
    assert "score': 0.767" in trace
    assert "GOOGLE_BOOKS_API_TRACE event=no_match reason=similarity" in trace


class _NoMatch:
    def verify_reference(self, reference):
        return None, [], None


class _CompleteMatch:
    def __init__(self, source="earlier"):
        self.calls = 0
        self.source = source

    def verify_reference(self, reference):
        self.calls += 1
        return {
            "title": reference["title"],
            "authors": [{"name": "J. R. R. Tolkien"}],
        }, [], f"https://example.test/{self.source}"


def _hybrid_without_network():
    with patch.object(EnhancedHybridReferenceChecker, "_initialize_checker", return_value=None):
        checker = EnhancedHybridReferenceChecker(
            enable_openalex=False,
            enable_crossref=False,
            enable_open_library=False,
            enable_google_books=False,
            enable_arxiv_citation=False,
            enable_acl_anthology=False,
            enable_paperclip=False,
        )
    checker.local_db = None
    checker.local_db_checkers = []
    checker.semantic_scholar = _NoMatch()
    checker.crossref = None
    checker.openalex = None
    checker.open_library = None
    checker.dblp = None
    checker.acl_anthology = None
    checker.paperclip = None
    checker.arxiv_citation = None
    checker.openreview = None
    return checker


def test_google_books_is_called_only_after_earlier_sources_are_insufficient():
    checker = _hybrid_without_network()
    google = _CompleteMatch("google")
    checker.google_books = google

    data, errors, url = checker.verify_reference({
        "title": "The Hobbit",
        "authors": ["J. R. R. Tolkien"],
        "year": 1937,
        "type": "book",
    })

    assert google.calls == 1
    assert errors == []
    assert url == "https://example.test/google"
    assert data["_matched_checker"] == "google_books"
    assert data["_matched_database"] == "Google Books"


def test_complete_earlier_result_prevents_google_books_call():
    checker = _hybrid_without_network()
    earlier = _CompleteMatch("semantic-scholar")
    google = _CompleteMatch("google")
    checker.semantic_scholar = earlier
    checker.google_books = google

    data, errors, url = checker.verify_reference({
        "title": "The Hobbit",
        "authors": ["J. R. R. Tolkien"],
        "type": "book",
    })

    assert earlier.calls == 1
    assert google.calls == 0
    assert errors == []
    assert url == "https://example.test/semantic-scholar"


def test_trace_distinguishes_reached_fallback_from_earlier_match(caplog):
    checker = _hybrid_without_network()
    google = _CompleteMatch("google")
    checker.google_books = google

    with caplog.at_level(logging.INFO):
        checker.verify_reference({"title": "The Hobbit", "type": "book"})

    trace = "\n".join(record.getMessage() for record in caplog.records)
    assert "event=fallback_reached forced=False title='The Hobbit'" in trace
    assert "event=fallback_result outcome=match title='The Hobbit'" in trace

    caplog.clear()
    checker = _hybrid_without_network()
    checker.semantic_scholar = _CompleteMatch("semantic-scholar")
    checker.google_books = _CompleteMatch("google")
    with caplog.at_level(logging.INFO):
        checker.verify_reference({"title": "The Hobbit", "type": "book"})

    trace = "\n".join(record.getMessage() for record in caplog.records)
    assert "event=fallback_reached" not in trace


def test_google_books_is_not_queried_for_an_ordinary_article():
    checker = _hybrid_without_network()
    google = _CompleteMatch("google")
    checker.google_books = google

    checker.verify_reference({
        "title": "A journal article",
        "authors": ["Ada Author"],
        "type": "article",
        "journal": "Example Journal",
    })

    assert google.calls == 0


def test_magazine_uses_google_books_only_after_earlier_sources_fail():
    checker = _hybrid_without_network()
    google = _CompleteMatch("google")
    checker.google_books = google

    data, errors, url = checker.verify_reference({
        "title": "Example Magazine",
        "authors": ["J. R. R. Tolkien"],
        "type": "magazine",
    })

    assert google.calls == 1
    assert errors == []
    assert url == "https://example.test/google"
    assert data["_matched_checker"] == "google_books"


def test_issn_only_journal_is_not_treated_as_a_magazine():
    checker = _hybrid_without_network()
    google = _CompleteMatch("google")
    checker.google_books = google

    checker.verify_reference({
        "title": "A scholarly article",
        "type": "article",
        "journal": "Journal of Examples",
        "issn": "1234-5678",
    })

    assert google.calls == 0


def test_hybrid_magazine_option_disables_magazine_fallback():
    checker = _hybrid_without_network()
    checker.google_books_include_magazines = False
    google = _CompleteMatch("google")
    checker.google_books = google

    checker.verify_reference({"title": "Example Magazine", "type": "magazine"})

    assert google.calls == 0


def test_force_all_databases_queries_google_books_for_ineligible_type(caplog):
    checker = _hybrid_without_network()
    google = _CompleteMatch("google")
    checker.google_books = google

    with caplog.at_level(logging.INFO):
        checker.verify_reference(
            {"title": "An ordinary article", "type": "article"},
            force_all_databases=True,
        )

    assert google.calls == 1
    trace = "\n".join(record.getMessage() for record in caplog.records)
    assert "event=fallback_reached forced=True title='An ordinary article'" in trace
