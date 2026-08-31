from backend.database import ensure_reference_uids
from backend.main import _find_ref_index, _find_ref_index_precise


def test_uid_route_targets_duplicate_index_row_exactly():
    rows = ensure_reference_uids([
        {"index": 26, "title": "First work"},
        {"index": 26, "title": "Second work"},
    ])

    assert _find_ref_index(rows, f"uid:{rows[1]['ref_uid']}") == 1


def test_typed_duplicate_index_fails_closed():
    rows = ensure_reference_uids([
        {"index": 26, "title": "First work"},
        {"index": 26, "title": "Second work"},
    ])

    assert _find_ref_index(rows, "index:26") is None


def test_ambiguous_precise_hints_fail_closed():
    rows = ensure_reference_uids([
        {"index": 26, "title": "Same work"},
        {"index": 26, "title": "Same work"},
    ])

    assert _find_ref_index_precise(
        rows,
        "26",
        expected_index=26,
        expected_title="Same work",
    ) is None

