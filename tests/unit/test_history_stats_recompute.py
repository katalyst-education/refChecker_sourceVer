import asyncio
import sqlite3

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


def test_replacing_references_persists_canonical_status_buckets(tmp_path):
    db_path = tmp_path / "history.db"
    db = Database(str(db_path))
    _run(db.init_db())
    check_id = _run(db.create_pending_check(
        paper_title="Status bucket regression",
        paper_source="https://example.org/paper",
        source_type="url",
    ))

    results = [
        {"index": 1, "title": "Verified", "status": "verified"},
        {
            "index": 2,
            "title": "Not found",
            "status": "unverified",
            "errors": [{"error_type": "unverified", "error_details": "Not found"}],
        },
        {
            "index": 3,
            "title": "Suggestion only",
            "status": "suggestion",
            "suggestions": [{"error_type": "possible_alternative"}],
        },
    ]

    assert _run(db.replace_check_references(check_id, results)) is True

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """SELECT errors_count, unverified_count, refs_with_errors,
                      refs_with_suggestions_only, refs_verified
                 FROM check_history WHERE id = ?""",
            (check_id,),
        ).fetchone()

    assert row == (0, 1, 0, 1, 2)

