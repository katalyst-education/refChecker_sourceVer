import asyncio

from backend.database import (
    Database,
    _compute_reference_buckets_from_results,
    _get_effective_reference_status,
    ensure_reference_uids,
)


def test_unverified_reference_is_not_treated_as_llm_pending_without_explicit_flag():
    reference = {
        "status": "unverified",
        "errors": [{"error_type": "unverified", "error_details": "Not found"}],
    }

    assert _get_effective_reference_status(reference, is_complete=False) == "unverified"


def _run(coro):
    return asyncio.run(coro)


def test_duplicate_citation_indexes_receive_distinct_stable_row_uids():
    rows = [
        {"index": 26, "title": "First work", "status": "verified"},
        {"index": 26, "title": "Second work", "status": "unverified"},
    ]

    identified = ensure_reference_uids(rows)
    reordered = ensure_reference_uids(list(reversed(identified)))

    assert identified[0]["ref_uid"] != identified[1]["ref_uid"]
    assert {row["title"]: row["ref_uid"] for row in identified} == {
        row["title"]: row["ref_uid"] for row in reordered
    }


def test_summary_counts_every_row_when_citation_indexes_are_duplicated():
    buckets = _compute_reference_buckets_from_results(
        [
            {"index": 26, "title": "First work", "status": "verified"},
            {"index": 26, "title": "Second work", "status": "unverified"},
        ],
        is_complete=True,
    )

    assert buckets["processed_refs"] == 2
    assert buckets["refs_verified"] == 1
    assert buckets["unverified_count"] == 1

