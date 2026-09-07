"""Regression coverage for neutral issue counting."""

from refchecker.core.issue_policy import count_raw_errors


def test_unverified_evidence_is_not_counted_as_a_metadata_error():
    issues = [
        {"error_type": "unverified", "error_details": "No configured source matched"},
        {"error_type": "title", "error_details": "Title differs"},
    ]
    assert count_raw_errors(issues) == (1, 0, 0)


def test_empty_and_malformed_issue_collections_are_safe():
    assert count_raw_errors(None) == (0, 0, 0)
    assert count_raw_errors([]) == (0, 0, 0)
    assert count_raw_errors([{}]) == (0, 0, 0)


def test_every_real_metadata_error_is_counted():
    issues = [
        {"error_type": "author"},
        {"error_type": "year"},
        {"error_type": "venue"},
    ]
    assert count_raw_errors(issues) == (3, 0, 0)
