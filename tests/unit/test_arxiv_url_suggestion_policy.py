from refchecker.utils.doi_utils import reference_has_doi
from refchecker.utils.reference_suggestions import (
    should_suggest_arxiv_url,
    suppress_redundant_arxiv_suggestions,
)


def test_reference_has_structured_doi():
    assert reference_has_doi({"doi": "10.1234/example"}) is True


def test_reference_has_doi_resolver_url():
    assert reference_has_doi({"url": "https://doi.org/10.1234/example"}) is True


def test_reference_without_doi():
    assert reference_has_doi({"url": "https://example.org/paper"}) is False


def test_matching_arxiv_url_is_not_suggested():
    reference = {"url": "https://arxiv.org/abs/2210.06340"}
    assert should_suggest_arxiv_url(reference, "2210.06340") is False


def test_different_arxiv_url_does_not_hide_correct_suggestion():
    reference = {"url": "https://arxiv.org/abs/2301.00001"}
    assert should_suggest_arxiv_url(reference, "2210.06340") is True


def test_stale_cached_suggestion_is_removed_for_matching_cited_url():
    cached = {
        "status": "suggestion",
        "errors": [],
        "warnings": [],
        "suggestions": [{
            "suggestion_type": "url",
            "suggestion_details": (
                "Reference could include arXiv URL: "
                "https://arxiv.org/abs/2210.06340"
            ),
        }],
    }
    cited = {"url": "https://arxiv.org/abs/2210.06340"}

    cleaned = suppress_redundant_arxiv_suggestions(cached, cited)

    assert cleaned["suggestions"] == []
    assert cleaned["status"] == "verified"


def test_completed_result_does_not_repeat_its_attached_arxiv_metadata():
    result = {
        "status": "warning",
        "doi": "10.48550/arxiv.2210.06340",
        "arxiv_id": "2210.06340",
        "errors": [],
        "warnings": [{"error_type": "venue"}],
        "suggestions": [{
            "suggestion_type": "url",
            "suggestion_details": (
                "Reference could include arXiv URL: "
                "https://arxiv.org/abs/2210.06340"
            ),
        }],
    }

    cleaned = suppress_redundant_arxiv_suggestions(result, result)

    assert cleaned["suggestions"] == []
    assert cleaned["status"] == "warning"
