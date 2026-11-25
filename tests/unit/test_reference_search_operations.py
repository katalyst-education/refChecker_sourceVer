import asyncio
import threading
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

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


@pytest.mark.asyncio
@pytest.mark.parametrize("found", [True, False])
async def test_review_lists_persist_by_row_and_return_through_a_successful_search(tmp_path, monkeypatch, found):
    from backend import main

    database = Database(str(tmp_path / "history.db"))
    await database.init_db()
    monkeypatch.setattr(main, "db", database)
    monkeypatch.setattr(main.manager, "send_message", AsyncMock())

    citations = [
        {"index": 21, "entry_number": 21, "title": "Duplicate title", "authors": ["A. First"]},
        {"index": 21, "entry_number": 21, "title": "Duplicate title", "authors": ["B. Second"]},
        {"index": 39, "entry_number": 39, "title": "Later title", "authors": ["C. Third"]},
    ]
    scanned = [
        project_verification_result(
            citation, {"title": citation["title"]},
            [{"error_type": "author", "error_details": "Author mismatch"}], None,
            enrich_enabled=False,
        )
        for citation in citations
    ]
    check_id = await database.save_check("Test paper", "", "file", 3, 3, 0, 0, 0, 3, 0, 0, scanned)
    rows = await database.get_check_references(check_id)
    uids = [row["ref_uid"] for row in rows]
    user = main.UserInfo(id=0, name="Local", provider="local", is_admin=True)

    class Checker:
        unavailable = False

        def _configured_database_names(self):
            return []

        def verify_reference(self, reference, force_all_databases=False):
            assert force_all_databases
            assert reference["authors"] == ["B. Second"]
            if self.unavailable:
                return None, [{
                    "error_type": "unverified", "verification_reason": "provider_failure", "sources_negative": 0,
                }], None
            if found:
                return {"title": reference["title"], "authors": reference["authors"]}, [], None
            return None, [{"error_type": "unverified", "error_details": "No match"}], None

    fake_checker = Checker()
    checker = AsyncMock(return_value=fake_checker)
    monkeypatch.setattr(main, "_create_reference_search_checker", checker)

    async def move(position, destination):
        response = await main.move_reference_to_review_list(
            check_id, f"uid:{uids[position]}", main._ReferenceReviewListRequest(destination=destination), user,
        )
        return response["reference"]

    later = await move(2, "could_not_find")
    second = await move(1, "further_checks")
    assert second["errors"] == rows[1]["errors"]
    reopened = await database.get_check_by_id(check_id)
    assert [ref["ref_uid"] for ref in reopened["results"]] == uids
    assert [ref.get("review_list") for ref in reopened["results"]] == [None, "further_checks", "could_not_find"]
    assert reopened["total_refs"] == 3
    assert reopened["refs_with_errors"] == 1

    marked = await move(2, "unverified")
    assert marked["status"] == "unverified"
    assert "review_list" not in marked
    assert marked["review_revision"] != later["review_revision"]
    assert marked["cited_metadata"] == later["cited_metadata"]
    assert marked["entry_number"] == 39
    checker.assert_not_awaited()

    async def search(suffix, *, expected, cancelled=False):
        key = f"uid:{uids[1]}"
        operation_id = f"operation-{suffix}"
        session_id = f"session-{suffix}"
        await database.create_reference_search_operation(operation_id, session_id, check_id, key, user_id=None)
        cancel_event = threading.Event()
        if cancelled:
            cancel_event.set()
        await main._run_reference_search_job(
            operation_id=operation_id, session_id=session_id, check_id=check_id, ref_id=key,
            reference_key=key, owner_id=None, expected_id=None, expected_index=39, expected_title="Duplicate title",
            expected_reference=expected, semantic_scholar_api_key=None, google_books_api_key=None,
            paperclip_api_key=None, cancel_event=cancel_event,
        )
        return await database.get_reference_search_operation(operation_id, None)

    reassigned = await move(1, "could_not_find")
    stale = await search("stale", expected=second)
    assert stale["error_code"] == "reference_changed"
    checker.assert_not_awaited()
    cancelled = await search("cancelled", expected=reassigned, cancelled=True)
    assert cancelled["status"] == "cancelled"
    assert (await database.get_check_references(check_id))[1] == reassigned

    fake_checker.unavailable = True
    failed = await search("failed", expected=reassigned)
    assert failed["status"] == "error"
    assert (await database.get_check_references(check_id))[1] == reassigned
    fake_checker.unavailable = False

    success = await search("completed", expected=reassigned)
    assert success["status"] == "completed"
    stored_rows = await database.get_check_references(check_id)
    assert [ref["ref_uid"] for ref in stored_rows] == uids
    assert [ref["index"] for ref in stored_rows] == [21, 21, 39]
    assert stored_rows[0] == rows[0]
    assert stored_rows[1]["status"] == ("verified" if found else "unverified")
    assert "review_list" not in stored_rows[1]
    assert stored_rows[2]["status"] == "unverified"
    cached = await database.lookup_verified_reference(stored_rows[1])
    assert "review_revision" not in cached["result"]


@pytest.mark.asyncio
async def test_custom_lists_are_scoped_to_a_check_and_preserve_citations_on_delete(tmp_path, monkeypatch):
    from backend import main

    database = Database(str(tmp_path / "history.db"))
    await database.init_db()
    monkeypatch.setattr(main, "db", database)
    verifier = AsyncMock()
    monkeypatch.setattr(main, "_create_reference_search_checker", verifier)
    user = main.UserInfo(id=0, name="Local", provider="local", is_admin=True)
    check_id = await database.create_pending_check("Paper A", "", "file")
    other_check_id = await database.create_pending_check("Paper B", "", "file")
    refs = [
        {"index": 7, "entry_number": 7, "title": "First citation", "status": "verified"},
        {"index": 9, "entry_number": 9, "title": "Later citation", "status": "verified"},
    ]
    await database.replace_check_references(check_id, refs)
    before = await database.get_check_by_id(check_id)
    assert [item["name"] for item in before["reference_lists"]] == ["Further Checks", "Could not Find"]
    marked_id = f"uid:{before['results'][1]['ref_uid']}"

    def name_request(name):
        return main._ReferenceListNameRequest(name=name)

    custom = (await main.create_reference_list(check_id, name_request("  Ask librarian  "), user))["list"]
    with pytest.raises(HTTPException) as duplicate:
        await main.create_reference_list(check_id, name_request("ASK LIBRARIAN"), user)
    assert duplicate.value.status_code == 409
    assert custom["name"] == "Ask librarian"
    assert all(item["id"] != custom["id"] for item in (await database.get_check_by_id(other_check_id))["reference_lists"])

    async def move():
        body = main._ReferenceReviewListRequest(destination=custom["id"])
        return await main.move_reference_to_review_list(check_id, marked_id, body, user)

    await move()
    renamed = await main.rename_reference_list(check_id, custom["id"], name_request("Check print edition"), user)
    assert renamed["list"] == {"id": custom["id"], "name": "Check print edition"}
    reopened = await Database(database.db_path).get_check_by_id(check_id)
    assert reopened["results"][1]["review_list"] == custom["id"]
    assert reopened["reference_lists"][-1] == renamed["list"]

    deleted = await main.delete_reference_list(check_id, custom["id"], user)
    assert [ref["status"] for ref in deleted["references"]] == ["unverified"]
    with pytest.raises(HTTPException) as missing:
        await move()
    assert missing.value.status_code == 404
    for item in before["reference_lists"]:
        await main.delete_reference_list(check_id, item["id"], user)
    reopened = await database.get_check_by_id(check_id)
    assert reopened["reference_lists"] == []
    assert [ref["entry_number"] for ref in reopened["results"]] == [7, 9]
    assert reopened["results"][0] == before["results"][0]
    assert reopened["results"][1]["title"] == "Later citation"
    assert reopened["unverified_count"] == 1
    verifier.assert_not_awaited()
