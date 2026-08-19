from unittest.mock import Mock, patch

from refchecker.checkers.open_library import OpenLibraryReferenceChecker
from refchecker.utils.cache_utils import cache_api_response


BOOK = {
    "key": "/works/OL27448W",
    "title": "The Lord of the Rings",
    "author_name": ["J. R. R. Tolkien"],
    "first_publish_year": 1954,
}


@patch("refchecker.checkers.open_library.requests.get")
def test_open_library_verifies_book_and_uses_identified_client_limit(mock_get, monkeypatch):
    monkeypatch.setenv("REFCHECKER_CONTACT_EMAIL", "maintainer@example.org")
    response = Mock()
    response.status_code = 200
    response.json.return_value = {"docs": [BOOK]}
    mock_get.return_value = response

    checker = OpenLibraryReferenceChecker()
    data, errors, url = checker.verify_reference({
        "title": "The Lord of the Rings",
        "authors": ["J. R. R. Tolkien"],
        "year": 1954,
    })

    assert data["title"] == "The Lord of the Rings"
    assert errors == []
    assert url == "https://openlibrary.org/works/OL27448W"
    assert checker.request_delay == 1 / 3
    assert "maintainer@example.org" in mock_get.call_args.kwargs["headers"]["User-Agent"]
    assert mock_get.call_args.kwargs["params"]["q"] == "The Lord of the Rings"
    assert "author" not in mock_get.call_args.kwargs["params"]


@patch("refchecker.checkers.open_library.requests.get")
def test_open_library_uses_isbn_query_when_available(mock_get):
    response = Mock()
    response.status_code = 200
    response.json.return_value = {"docs": [BOOK]}
    mock_get.return_value = response

    checker = OpenLibraryReferenceChecker(email="maintainer@example.org")
    data, errors, _ = checker.verify_reference({"isbn": "978-0-261-10221-7"})

    assert data["key"] == "/works/OL27448W"
    assert errors == []
    assert mock_get.call_args.kwargs["params"]["isbn"] == "9780261102217"


def test_open_library_rate_setting_cannot_exceed_anonymous_limit(monkeypatch):
    monkeypatch.delenv("REFCHECKER_CONTACT_EMAIL", raising=False)
    monkeypatch.setenv("REFCHECKER_OPEN_LIBRARY_RATE_LIMIT_DELAY", "0.34")

    checker = OpenLibraryReferenceChecker()

    assert checker.request_delay == 1.0


def test_open_library_rate_setting_can_slow_identified_requests(monkeypatch):
    monkeypatch.setenv("REFCHECKER_CONTACT_EMAIL", "maintainer@example.org")
    monkeypatch.setenv("REFCHECKER_OPEN_LIBRARY_RATE_LIMIT_DELAY", "0.75")

    checker = OpenLibraryReferenceChecker()

    assert checker.request_delay == 0.75


@patch("refchecker.checkers.open_library.requests.get")
def test_open_library_logs_search_parameters_and_candidates(mock_get, caplog):
    response = Mock()
    response.status_code = 200
    response.json.return_value = {"docs": [BOOK]}
    mock_get.return_value = response

    checker = OpenLibraryReferenceChecker(email="maintainer@example.org")
    with caplog.at_level("INFO"):
        checker.search_books("The Lord of the Rings", ["J. R. R. Tolkien"])

    assert "[OPEN_LIBRARY_TRACE] stage=search_result" in caplog.text
    assert "'title': 'The Lord of the Rings'" in caplog.text
    assert "'key': '/works/OL27448W'" in caplog.text


@patch("refchecker.checkers.open_library.requests.get")
def test_open_library_requeries_an_empty_cached_result(mock_get, tmp_path):
    response = Mock()
    response.status_code = 200
    response.json.return_value = {"docs": [BOOK]}
    mock_get.return_value = response

    checker = OpenLibraryReferenceChecker(email="maintainer@example.org")
    checker.cache_dir = str(tmp_path)
    cache_key = "v3|The Lord of the Rings|['J. R. R. Tolkien']||5"
    cache_api_response(checker.cache_dir, "open_library", "search_books", cache_key, [])

    results = checker.search_books("The Lord of the Rings", ["J. R. R. Tolkien"])

    assert results == [BOOK]
    mock_get.assert_called_once()


@patch("refchecker.checkers.open_library.requests.get")
def test_open_library_uses_subtitle_in_title_matching(mock_get):
    book = {
        **BOOK,
        "title": "Abschalten!",
        "subtitle": "Warum mit Atomkraft Schluss sein muss und was wir alle dafür tun können",
        "author_name": ["Yves Venedey"],
        "first_publish_year": 2011,
    }
    response = Mock()
    response.status_code = 200
    response.json.return_value = {"docs": [book]}
    mock_get.return_value = response

    checker = OpenLibraryReferenceChecker(email="maintainer@example.org")
    data, _, _ = checker.verify_reference({
        "title": "Abschalten!. Warum mit Atomkraft Schluss sein muss und was wir alle dafür tun können",
        "authors": ["Ives Venedey"],
        "year": 2011,
    })

    assert data["title"] == "Abschalten!"
    assert data["subtitle"] == "Warum mit Atomkraft Schluss sein muss und was wir alle dafür tun können"
