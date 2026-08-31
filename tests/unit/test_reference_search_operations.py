import asyncio

import pytest

from backend.database import Database, ReferenceSearchLimitReached


def run(coro):
    return asyncio.run(coro)


def test_reference_search_operation_lifecycle(tmp_path):
    database = Database(str(tmp_path / "history.db"))
    run(database.init_db())

    created, is_new = run(database.create_reference_search_operation(
        "operation-1", "session-1", 17, "id:ref-1", user_id=None,
    ))
    assert is_new is True
    assert created["status"] == "queued"

    duplicate, is_new = run(database.create_reference_search_operation(
        "operation-2", "session-2", 17, "id:ref-1", user_id=None,
    ))
    assert is_new is False
    assert duplicate["operation_id"] == "operation-1"

    progress = {"sequence": 2, "sources": {"crossref": {"status": "matched"}}}
    reference = {"id": "ref-1", "status": "verified"}
    assert run(database.update_reference_search_operation(
        "operation-1", status="completed", progress=progress,
        reference=reference, terminal=True,
    ))

    stored = run(database.get_reference_search_operation("operation-1", None))
    assert stored["status"] == "completed"
    assert stored["progress"] == progress
    assert stored["reference"] == reference
    assert stored["completed_at"] is not None


def test_reference_search_operations_are_owner_scoped(tmp_path):
    database = Database(str(tmp_path / "history.db"))
    run(database.init_db())
    run(database.create_reference_search_operation(
        "operation-1", "session-1", 17, "id:ref-1", user_id=4,
    ))

    assert run(database.get_reference_search_operation("operation-1", 4)) is not None
    assert run(database.get_reference_search_operation("operation-1", 5)) is None


def test_reference_search_limit_is_atomic_per_user(tmp_path):
    database = Database(str(tmp_path / "history.db"))
    run(database.init_db())

    run(database.create_reference_search_operation(
        "operation-1", "session-1", 17, "id:ref-1", user_id=4,
        max_active_per_user=1,
    ))

    with pytest.raises(ReferenceSearchLimitReached):
        run(database.create_reference_search_operation(
            "operation-2", "session-2", 17, "id:ref-2", user_id=4,
            max_active_per_user=1,
        ))

    created, is_new = run(database.create_reference_search_operation(
        "operation-3", "session-3", 17, "id:ref-1", user_id=4,
        max_active_per_user=1,
    ))
    assert is_new is False
    assert created["operation_id"] == "operation-1"
