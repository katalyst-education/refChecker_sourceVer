"""Regression tests for the total_refs over-count bug.

BUG (reproduced live): the progress read "Checking references (28/23) · 122%
complete" and history rows showed "59/43" — processed_refs exceeded total_refs,
so progress went past 100%. Root cause: total_refs was an EARLY estimate (the
initial extraction count) while the actual number of references checked could be
higher (de-dup / merge / re-extraction), so processed overshot the denominator.

The fix reconciles total_refs to the REAL final reference count: it is raised to
at least processed_refs once the reference set is known, so progress can never
exceed 100%. These tests pin that invariant at the database recompute layer
(``_compute_reference_buckets_from_results`` + the read paths that consume it).
"""
import asyncio

from backend.database import Database, _compute_reference_buckets_from_results


def _run(coro):
    return asyncio.run(coro)


def _verified_refs(n):
    """n distinct, finalized 'verified' reference results."""
    return [
        {"index": i + 1, "status": "verified", "errors": [], "warnings": [], "suggestions": []}
        for i in range(n)
    ]


def test_pure_recompute_raises_total_to_processed():
    """The reconciled total is never below the real processed count, even when
    the stored estimate (43) lagged the actual reference set (59)."""
    results = _verified_refs(59)

    buckets = _compute_reference_buckets_from_results(
        results, is_complete=True, stored_total_refs=43,
    )

    assert buckets["processed_refs"] == 59
    # total_refs reconciled UP to the real count — no more "59/43".
    assert buckets["total_refs"] == 59
    assert buckets["total_refs"] >= buckets["processed_refs"]


def test_pure_recompute_keeps_larger_stored_total():
    """When the stored total already exceeds processed (refs still streaming in),
    the larger stored total is preserved — we never shrink the denominator."""
    results = _verified_refs(10)

    buckets = _compute_reference_buckets_from_results(
        results, is_complete=False, stored_total_refs=23,
    )

    assert buckets["processed_refs"] == 10
    assert buckets["total_refs"] == 23
    assert buckets["total_refs"] >= buckets["processed_refs"]


def test_pure_recompute_handles_missing_stored_total():
    """With no stored total, total_refs falls back to the processed count."""
    results = _verified_refs(7)

    buckets = _compute_reference_buckets_from_results(results, is_complete=True)

    assert buckets["processed_refs"] == 7
    assert buckets["total_refs"] == 7


