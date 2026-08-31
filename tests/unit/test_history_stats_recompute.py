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


def test_history_recomputes_display_stats_from_results_json(tmp_path):
    db = Database(str(tmp_path / "history.db"))
    _run(db.init_db())

    results = [
        {
            "status": "error",
            "errors": [
                {"error_type": "author", "error_details": "Author mismatch"},
                {"error_type": "unverified", "error_details": "Could not verify URL"},
            ],
            "warnings": [],
            "suggestions": [],
        },
        {
            "status": "warning",
            "errors": [],
            "warnings": [
                {"warning_type": "year", "warning_details": "Year mismatch"},
                {"warning_type": "venue", "warning_details": "Venue mismatch"},
            ],
            "suggestions": [],
        },
        {
            "status": "suggestion",
            "errors": [],
            "warnings": [],
            "suggestions": [
                {"suggestion_type": "doi", "suggestion_details": "Add DOI"},
                {"suggestion_type": "url", "suggestion_details": "Add URL"},
            ],
        },
        {
            "status": "hallucination",
            "errors": [
                {"error_type": "author", "error_details": "Author mismatch"},
                {"error_type": "unverified", "error_details": "Could not verify"},
            ],
            "warnings": [{"warning_type": "year", "warning_details": "Year mismatch"}],
            "suggestions": [{"suggestion_type": "doi", "suggestion_details": "Add DOI"}],
            "hallucination_assessment": {"verdict": "LIKELY"},
        },
        {
            "status": "verified",
            "errors": [],
            "warnings": [],
            "suggestions": [],
        },
    ]
    ai_detection = {
        "overall_score": 0.73,
        "band": "high",
        "backend_used": "local",
        "device_used": "cuda",
        "word_count": 1842,
    }

    check_id = _run(db.create_pending_check(
        paper_title="Towards a Formal Theory of Representational Compositionality",
        paper_source="https://openreview.net/forum?id=fXCfl7Example",
        source_type="url",
    ))

    _run(db.update_check_results(
        check_id=check_id,
        paper_title="Towards a Formal Theory of Representational Compositionality",
        total_refs=len(results),
        errors_count=99,
        warnings_count=99,
        suggestions_count=99,
        unverified_count=99,
        refs_with_errors=99,
        refs_with_warnings_only=99,
        refs_verified=99,
        results=results,
        status="completed",
        refs_with_suggestions_only=99,
        hallucination_count=99,
        ai_detection=ai_detection,
    ))

    history_item = _run(db.get_history(limit=1))[0]
    detail_item = _run(db.get_check_by_id(check_id))

    expected = {
        "processed_refs": 5,
        "errors_count": 1,
        "warnings_count": 2,
        "suggestions_count": 2,
        "unverified_count": 2,
        "hallucination_count": 1,
        "refs_with_errors": 1,
        "refs_with_warnings_only": 1,
        "refs_with_suggestions_only": 1,
        "refs_verified": 2,
    }

    for key, value in expected.items():
        assert history_item[key] == value
        assert detail_item[key] == value

    # History cards need the same reference objects as the detail view so
    # frontend citation-style/cosmetic filtering cannot change their badges
    # merely because the user clicked the row.
    assert history_item["results"] == detail_item["results"]
    assert [
        {key: value for key, value in row.items() if key != "ref_uid"}
        for row in history_item["results"]
    ] == results
    assert history_item["ai_detection"] == detail_item["ai_detection"] == ai_detection
    assert history_item["ai_detection_score"] == detail_item["ai_detection_score"] == 0.73
    assert history_item["ai_detection_band"] == detail_item["ai_detection_band"] == "high"


def test_in_progress_history_counts_processed_unverified_refs_pending_hallucination(tmp_path):
    db = Database(str(tmp_path / "history.db"))
    _run(db.init_db())

    results = [
        {
            "index": 1,
            "status": "verified",
            "errors": [],
            "warnings": [],
            "suggestions": [],
        },
        {
            "index": 2,
            "status": "unverified",
            "errors": [{"error_type": "unverified", "error_details": "Not found"}],
            "warnings": [],
            "suggestions": [],
            "hallucination_check_pending": True,
        },
        {
            "index": 2,
            "status": "unverified",
            "errors": [{"error_type": "unverified", "error_details": "Not found"}],
            "warnings": [],
            "suggestions": [],
            "hallucination_check_pending": False,
            "hallucination_assessment": {"verdict": "UNLIKELY"},
        },
    ]

    check_id = _run(db.create_pending_check(
        paper_title="In-progress paper",
        paper_source="https://openreview.net/forum?id=example",
        source_type="url",
    ))

    _run(db.update_check_progress(
        check_id=check_id,
        total_refs=3,
        errors_count=0,
        warnings_count=0,
        suggestions_count=0,
        unverified_count=0,
        hallucination_count=0,
        refs_with_errors=0,
        refs_with_warnings_only=0,
        refs_verified=0,
        results=results,
    ))

    history_item = _run(db.get_history(limit=1))[0]
    detail_item = _run(db.get_check_by_id(check_id))

    assert history_item["processed_refs"] == 2
    assert detail_item["processed_refs"] == 2
    assert history_item["unverified_count"] == 1
    assert detail_item["unverified_count"] == 1


def test_in_progress_history_does_not_count_transient_unverified_refs(tmp_path):
    db = Database(str(tmp_path / "history.db"))
    _run(db.init_db())

    results = [
        {
            "index": 1,
            "status": "verified",
            "errors": [],
            "warnings": [],
            "suggestions": [],
        },
        {
            "index": 2,
            "status": "unverified",
            "errors": [{"error_type": "unverified", "error_details": "Not found"}],
            "warnings": [],
            "suggestions": [],
            "hallucination_check_pending": True,
        },
    ]

    check_id = _run(db.create_pending_check(
        paper_title="In-progress paper",
        paper_source="https://openreview.net/forum?id=example",
        source_type="url",
    ))

    _run(db.update_check_progress(
        check_id=check_id,
        total_refs=2,
        errors_count=0,
        warnings_count=0,
        suggestions_count=0,
        unverified_count=1,
        hallucination_count=0,
        refs_with_errors=0,
        refs_with_warnings_only=0,
        refs_verified=1,
        results=results,
    ))

    history_item = _run(db.get_history(limit=1))[0]
    detail_item = _run(db.get_check_by_id(check_id))

    assert history_item["processed_refs"] == 2
    assert detail_item["processed_refs"] == 2
    assert history_item["unverified_count"] == 0
    assert detail_item["unverified_count"] == 0
