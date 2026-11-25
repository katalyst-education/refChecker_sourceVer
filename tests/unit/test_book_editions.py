from unittest.mock import Mock

import pytest
import requests

from backend.reference_result import project_verification_result
from backend.refchecker_wrapper import ProgressRefChecker
from refchecker.checkers.enhanced_hybrid_checker import EnhancedHybridReferenceChecker
from refchecker.checkers.open_library import OpenLibraryReferenceChecker
from refchecker.core import bulk_pipeline
from refchecker.core.refchecker import ArxivReferenceChecker
from refchecker.utils.biblatex_parser import parse_biblatex_entry_content
from refchecker.utils.bibtex_parser import parse_bibtex_references
from refchecker.utils.book_editions import assess_book_edition
from refchecker.utils.reference_metadata import recover_cited_book_fields


CITATION = (
    "[200] R. W. G. Wyckoff, Crystal Structures, 2nd ed. New York, New York:\n"
    "Interscience Publishers, 1963, vol. 1, rocksalt structure."
)
WORK = {
    "title": "Crystal Structures",
    "author_name": ["Ralph W. G. Wyckoff"],
    "first_publish_year": 1948,
    "key": "/works/OL6806991W",
}
FIRST = {
    "title": "Crystal Structures, volume I",
    "edition_name": "1st edition",
    "publish_date": "1948",
    "publishers": ["Interscience Publishers"],
    "key": "/books/OL1M",
}
SECOND = {
    "title": "Crystal Structures, volume I",
    "edition_name": "2d ed.",
    "publish_date": "c1963",
    "publishers": ["Interscience Publishers"],
    "key": "/books/OL2M",
}


def _printed_citation():
    return parse_biblatex_entry_content("200", CITATION.removeprefix("[200] "))


def test_citation_parser_retains_printed_edition_metadata():
    citation = _printed_citation()
    assert citation["title"] == "Crystal Structures"
    assert citation["edition"] == "2nd ed."
    assert citation["volume"] == "1"
    assert citation["publisher"] == "Interscience Publishers"
    assert int(citation["year"]) == 1963

    saved = {"title": "Crystal Structures", "extraction_provenance": {"source_text": CITATION}}
    recover_cited_book_fields(saved)
    assert {key: saved[key] for key in ("edition", "volume", "publisher")} == {
        key: citation[key] for key in ("edition", "volume", "publisher")
    }


def test_printed_and_bibtex_book_editions_preserve_the_isbn():
    printed = parse_biblatex_entry_content(
        "6", 'Tolkien, J. R. R., "The Lord of the Rings," Second edition, Example Press, '
        '2001, ISBN 978-0-261-10221-7.',
    )
    [bibtex] = parse_bibtex_references('''@book{example,
        author = {J. R. R. Tolkien}, title = {The Lord of the Rings}, edition = {Second edition},
        publisher = {Example Press}, year = {2001}, isbn = {9780261102217}
    }''')
    for citation in (printed, bibtex):
        assert citation["edition"] == "Second edition"
        assert citation["isbn"] == "9780261102217"
        assert citation["publisher"] == "Example Press"


@pytest.mark.parametrize("match_edition", [True, False])
def test_book_edition_results_match_through_cli_bulk_web_and_search_all(monkeypatch, match_edition):
    monkeypatch.setattr(EnhancedHybridReferenceChecker, "_initialize_checker", lambda *_args, **_kwargs: None)
    hybrid = EnhancedHybridReferenceChecker()
    hybrid.open_library = OpenLibraryReferenceChecker()
    monkeypatch.setattr(hybrid.open_library, "search_books", lambda *_: [WORK])
    wrong_volume = {**SECOND, "title": "Crystal Structures, volume II", "key": "/books/OL3M"}
    entries = [FIRST, wrong_volume, SECOND] if match_edition else [FIRST, wrong_volume]
    monkeypatch.setattr(hybrid.open_library, "_search_editions", lambda *_: entries)
    cli = ArxivReferenceChecker.__new__(ArxivReferenceChecker)
    cli.non_arxiv_checker = hybrid
    cli.enable_parallel = False
    web = ProgressRefChecker.__new__(ProgressRefChecker)
    web.checker = hybrid
    cited = _printed_citation()

    findings, url, data = cli.verify_reference(None, dict(cited))
    assert web._verify_reference_body(dict(cited)) == (data, findings, url)
    search_data, search_findings, search_url = hybrid.verify_reference(dict(cited), force_all_databases=True)
    assert search_data["_book_edition_assessment"] == data["_book_edition_assessment"]
    assert search_findings == (findings or [])
    assert search_url == url
    projected = project_verification_result(cited, data, findings, url, enrich_enabled=False)
    assert int(projected["year"]) == 1963
    assert projected["cited_metadata"]["edition"] == "2nd ed."
    assert projected["corrected_reference"] is None

    if match_edition:
        assert projected["status"] == "verified"
        assert not findings
        assert data["publication_year"] == 1963
        assert data["_book_edition_assessment"]["dates"] == {"copyright": 1963}
        assert url.endswith("/books/OL2M")
    else:
        assert projected["status"] == "warning"
        [warning] = projected["warnings"]
        assert warning["error_type"] == "edition_unverified"
        assert "1948" in warning["error_details"]
        assert "1963" in warning["error_details"]
        assert "verified_year" not in projected
        assert url.endswith("/works/OL6806991W")

    cache = bulk_pipeline.BulkVerificationCache()
    record = Mock()
    monkeypatch.setattr(bulk_pipeline, "_record_reference_result_silent", record)
    bulk_pipeline._verify_bibliography_silent(cli, None, [dict(cited)], False, cache)
    assert record.call_args.kwargs["verified_data"] == data
    assert cache.get({**cited, "edition": "first edition"}) is None
    assert cache.get({**cited, "volume": "2"}) is None


def test_publication_dates_are_reported_for_the_cited_edition():
    isbn = "9780261102217"
    cited = {"title": "Example Book", "year": 2003, "isbn": isbn}
    verified = {
        "title": "Example Book", "type": "book", "isbn": isbn, "year": 2002,
        "published-print": {"date-parts": [[2003]]},
        "published-online": {"date-parts": [[2002, 12, 20]]},
    }
    raw = [{"warning_type": "year", "ref_year_correct": 2002}]
    data, findings = assess_book_edition(cited, verified, raw)
    assert findings == [{
        "info_type": "book_publication_dates",
        "info_details": "Edition dates differ by publication type. print 2003, online 2002.",
    }]
    row = project_verification_result(cited, data, findings, None, enrich_enabled=False)
    assert row["status"] == "verified"
    assert row["year"] == 2003
    assert row["corrected_reference"] is None


def test_only_the_cited_edition_can_support_a_year_correction():
    cited = {"title": "Example Book", "year": 2003, "isbn": "9780261102217"}
    verified = {"type": "book", "isbn": "0261102214", "year": 2001}
    data, findings = assess_book_edition(cited, verified, [])
    row = project_verification_result(cited, data, findings, None, enrich_enabled=False)
    assert row["corrected_reference"] == {"year": 2001}

    other = {**verified, "isbn": "9780140328721"}
    data, findings = assess_book_edition(cited, other, [])
    row = project_verification_result(cited, data, findings, None, enrich_enabled=False)
    assert row["corrected_reference"] is None
    assert row["warnings"][0]["error_type"] == "edition_unverified"


def test_unavailable_edition_lookup_keeps_work_match(monkeypatch):
    checker = OpenLibraryReferenceChecker()
    monkeypatch.setattr(checker, "search_books", lambda *_: [WORK])
    monkeypatch.setattr(checker, "_wait_for_slot", lambda: None)
    request = Mock(side_effect=requests.Timeout)
    monkeypatch.setattr(requests, "get", request)
    cited = _printed_citation()
    data, findings, url = checker.verify_reference(cited)
    assert data["_book_edition_assessment"]["status"] == "unverified"
    assert findings[0]["warning_type"] == "edition_unverified"
    assert url.endswith("/works/OL6806991W")
    request.assert_called_once()


def test_no_work_found_stays_unverified(monkeypatch):
    monkeypatch.setattr(EnhancedHybridReferenceChecker, "_initialize_checker", lambda *_args, **_kwargs: None)
    hybrid = EnhancedHybridReferenceChecker()
    hybrid.open_library = OpenLibraryReferenceChecker()
    monkeypatch.setattr(hybrid.open_library, "search_books", lambda *_: [])
    monkeypatch.setattr(hybrid.open_library, "_search_editions", Mock(side_effect=AssertionError))
    cited = _printed_citation()
    data, findings, url = hybrid.verify_reference(cited)
    result = project_verification_result(cited, data, findings, url, enrich_enabled=False)
    assert result["status"] == "unverified"
    assert result["book_edition_assessment"] is None
