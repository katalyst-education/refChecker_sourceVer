from unittest.mock import MagicMock
from unittest.mock import patch

from refchecker.core.refchecker import ArxivReferenceChecker


def test_standard_verification_prefers_webpage_checker_for_web_reference():
    checker = ArxivReferenceChecker.__new__(ArxivReferenceChecker)
    checker.verify_github_reference = MagicMock(return_value=None)
    checker.verify_webpage_reference = MagicMock(
        return_value=(None, "https://www.llama.com/docs/model-cards-and-prompt-formats/llama3_3/", {"title": "Llama 3.3"})
    )
    checker.non_arxiv_checker = MagicMock()

    reference = {
        "title": "Llama 3.3 — model cards and prompt formats",
        "authors": ["Meta AI"],
        "year": 2024,
        "venue": "n.d.",
        "url": "https://www.llama.com/docs/model-cards-and-prompt-formats/llama3_3/",
    }

    result = checker.verify_reference_standard(None, reference)

    assert result == (None, reference["url"], {"title": "Llama 3.3"})
    checker.verify_github_reference.assert_called_once_with(reference)
    checker.verify_webpage_reference.assert_called_once_with(reference)
    checker.non_arxiv_checker.verify_reference.assert_not_called()


def test_standard_verification_falls_back_to_academic_checker_when_not_webpage():
    checker = ArxivReferenceChecker.__new__(ArxivReferenceChecker)
    checker.verify_github_reference = MagicMock(return_value=None)
    checker.verify_webpage_reference = MagicMock(return_value=None)
    checker.non_arxiv_checker = MagicMock()
    checker.non_arxiv_checker.verify_reference.return_value = (
        {"title": "Attention Is All You Need"},
        [],
        "https://arxiv.org/abs/1706.03762",
    )

    reference = {
        "title": "Attention Is All You Need",
        "authors": ["Ashish Vaswani"],
        "year": 2017,
        "venue": "NeurIPS",
        "url": "https://arxiv.org/abs/1706.03762",
    }

    result = checker.verify_reference_standard(None, reference)

    assert result == (None, "https://arxiv.org/abs/1706.03762", {"title": "Attention Is All You Need"})
    checker.non_arxiv_checker.verify_reference.assert_called_once_with(reference)


def test_arxiv_url_is_dispatched_to_scholarly_checker_not_generic_webpage():
    checker = ArxivReferenceChecker.__new__(ArxivReferenceChecker)
    checker.verify_github_reference = MagicMock(return_value=None)
    checker.non_arxiv_checker = MagicMock()
    verified = {
        "title": "Scaling author name disambiguation with CNF blocking",
        "authors": ["Kunho Kim", "Acar Sefid", "C. Lee Giles"],
        "year": 2017,
        "_matched_database": "ArXiv",
    }
    checker.non_arxiv_checker.verify_reference.return_value = (
        verified,
        [],
        "https://arxiv.org/abs/1709.09657",
    )
    reference = {
        "title": "Scaling author name disambiguation with cnf blocking",
        "authors": ["K Kim", "A Sefid", "C L Giles"],
        "year": 2017,
        "url": "https://arxiv.org/abs/arXiv:1709.09657",
    }

    with patch(
        "refchecker.checkers.webpage_checker.WebPageChecker.verify_reference"
    ) as generic_web_verify:
        result = checker.verify_reference_standard(None, reference)

    assert result == (None, "https://arxiv.org/abs/1709.09657", verified)
    generic_web_verify.assert_not_called()
    checker.non_arxiv_checker.verify_reference.assert_called_once_with(reference)


def test_force_all_standard_verification_is_forwarded_to_hybrid_checker():
    checker = ArxivReferenceChecker.__new__(ArxivReferenceChecker)
    checker.verify_github_reference = MagicMock(return_value=None)
    checker.verify_webpage_reference = MagicMock(return_value=None)
    checker.non_arxiv_checker = MagicMock()
    checker.non_arxiv_checker.verify_reference.return_value = (None, [], None)
    reference = {"title": "A reference with an unclassified type"}

    checker.verify_reference_standard(
        None,
        reference,
        force_all_databases=True,
    )

    checker.non_arxiv_checker.verify_reference.assert_called_once_with(
        reference,
        force_all_databases=True,
    )


def test_force_all_queries_databases_for_web_reference_and_keeps_direct_fallback():
    checker = ArxivReferenceChecker.__new__(ArxivReferenceChecker)
    checker.verify_github_reference = MagicMock(return_value=None)
    webpage_result = (
        None,
        "https://example.com/reference",
        {"title": "Direct web reference", "_matched_database": "Web page"},
    )
    checker.verify_webpage_reference = MagicMock(return_value=webpage_result)
    checker.non_arxiv_checker = MagicMock()
    checker.non_arxiv_checker.verify_reference.return_value = (
        None,
        [{"error_type": "unverified", "error_details": "No database match"}],
        None,
    )
    reference = {
        "title": "Direct web reference",
        "url": "https://example.com/reference",
    }

    result = checker.verify_reference_standard(
        None,
        reference,
        force_all_databases=True,
    )

    checker.non_arxiv_checker.verify_reference.assert_called_once_with(
        reference,
        force_all_databases=True,
    )
    assert result == webpage_result


def test_standard_verification_checks_venue_named_site_before_title_search():
    checker = ArxivReferenceChecker.__new__(ArxivReferenceChecker)
    checker.verify_github_reference = MagicMock(return_value=None)
    checker.verify_webpage_reference = MagicMock(
        return_value=(None, "http://www.periodensystem.info/", {"title": "Periodensystem der Elemente"})
    )
    checker.non_arxiv_checker = MagicMock()

    reference = {
        "title": "Periodensystem der Elemente",
        "authors": ["Andy Hoppe"],
        "year": 2016,
        "venue": "periodensystem.info",
        "cited_url": "http://www.periodensystem.info/",
    }

    result = checker.verify_reference_standard(None, reference)

    assert result == (None, reference["cited_url"], {"title": "Periodensystem der Elemente"})
    checker.verify_webpage_reference.assert_called_once_with(reference)
    checker.non_arxiv_checker.verify_reference.assert_not_called()


def test_standard_verification_reports_missing_source_without_database_search():
    checker = ArxivReferenceChecker.__new__(ArxivReferenceChecker)
    checker.verify_github_reference = MagicMock(return_value=None)
    missing_source = [{
        "error_type": "unverified",
        "error_details": "Web page not found (404)",
    }]
    checker.verify_webpage_reference = MagicMock(
        return_value=(missing_source, "http://www.bmub.bund.de/missing", None)
    )
    checker.non_arxiv_checker = MagicMock()

    result = checker.verify_reference_standard(None, {
        "title": "Sicherheitsanforderungen an die Endlagerung",
        "url": "http://www.bmub.bund.de/missing",
    })

    assert result == (missing_source, "http://www.bmub.bund.de/missing", None)
    checker.non_arxiv_checker.verify_reference.assert_not_called()
