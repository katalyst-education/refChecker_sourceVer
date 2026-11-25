import asyncio
import threading
from unittest.mock import AsyncMock

import pytest

from backend.database import Database, ReferenceSearchLimitReached
from backend.reference_result import project_verification_result


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


def test_search_and_reopened_check_keep_the_same_findings_and_counts(tmp_path, monkeypatch):
    from backend import export, main

    database = Database(str(tmp_path / 'history.db'))
    mismatch = {'error_type': 'author', 'error_details': 'no matching authors'}
    match = {'title': 'A study of thin films', '_matched_database': 'DNB Catalogue'}

    class Checker:
        findings = [mismatch]

        def _configured_database_names(self):
            return []

        def verify_reference(self, reference, force_all_databases=False):
            assert force_all_databases
            return match, self.findings, None

    checker = Checker()
    monkeypatch.setattr(main, 'db', database)
    monkeypatch.setattr(main, '_create_reference_search_checker', AsyncMock(return_value=checker))
    send = AsyncMock()
    monkeypatch.setattr(main.manager, 'send_message', send)

    async def check():
        await database.init_db()
        citations = [
            {'index': 139, 'title': match['title'], 'authors': ['M. Hassan']},
            {'index': 140, 'title': 'A study of optical coatings', 'authors': ['A. Example']},
        ]
        scanned = [
            project_verification_result(citation, match, findings, None, enrich_enabled=False)
            for citation, findings in zip(citations, ([mismatch], []))
        ]
        check_id = await database.save_check('Test paper', '', 'file', 2, 1, 0, 0, 0, 1, 0, 1, scanned)
        initial = await database.get_check_by_id(check_id)
        assert initial['errors_count'] == initial['refs_with_errors'] == 1
        assert initial['results'][0]['errors'][0]['error_details'] == mismatch['error_details']
        assert initial['results'][0]['status'] == 'error'

        async def search(position, attempt):
            uid = initial['results'][position]['ref_uid']
            key = f'uid:{uid}'
            operation_id = f'op-{position}-{attempt}'
            session_id = f'session-{position}-{attempt}'
            await database.create_reference_search_operation(operation_id, session_id, check_id, key, user_id=None)
            await main._run_reference_search_job(
                operation_id=operation_id, session_id=session_id, check_id=check_id, ref_id=key,
                reference_key=key, owner_id=None, expected_id=None, expected_index=None,
                expected_title=None, semantic_scholar_api_key=None, google_books_api_key=None,
                paperclip_api_key=None, cancel_event=threading.Event(),
            )
            operation = await database.get_reference_search_operation(operation_id, None)
            assert operation['status'] == 'completed', operation.get('error_message')
            return operation['reference']

        results = await asyncio.gather(search(0, 1), search(1, 1))
        reopened = await database.get_check_by_id(check_id)
        assert reopened['results'] == results
        assert [ref['status'] for ref in reopened['results']] == ['error', 'error']
        assert reopened['errors_count'] == reopened['refs_with_errors'] == 2
        report, _, _ = export.render_export(reopened, 'md')
        assert mismatch['error_details'] in report

        checker.findings = []
        corrected = await search(0, 2)
        reopened = await database.get_check_by_id(check_id)
        assert reopened['results'][0] == corrected
        assert corrected['status'] == 'verified'
        assert corrected['errors'] == []
        assert reopened['results'][1]['status'] == 'error'
        assert reopened['errors_count'] == reopened['refs_with_errors'] == 1
        completions = [call.args[2]['reference'] for call in send.await_args_list if call.args[1] == 'reference_search_completed']
        assert completions[-1] == corrected

    run(check())
