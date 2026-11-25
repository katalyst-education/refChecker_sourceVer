import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from backend.database import Database
from backend.refchecker_wrapper import ProgressRefChecker


@pytest.fixture
def setup_batch(tmp_path, monkeypatch):
    monkeypatch.setenv('REFCHECKER_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('REFCHECKER_MULTIUSER', 'false')
    from backend import main

    database = Database(str(tmp_path / 'batch.db'))
    asyncio.run(database.init_db())
    check_id = asyncio.run(database.create_pending_check('Solar paper', str(tmp_path / 'paper.pdf'), source_type='file'))
    rows = [
        {'index': i, 'title': f'Article number {i}', 'authors': ['Unknown Author'] if i < 3 else ['A. Author'],
         'status': status, 'errors': [], 'warnings': []}
        for i, status in enumerate(['error', 'unverified', 'verified', 'warning'], 1)
    ]
    asyncio.run(database.replace_check_references(check_id, rows))
    monkeypatch.setattr(main, 'db', database)
    monkeypatch.setattr(main, '_reference_search_global_lane', asyncio.Semaphore(2))
    monkeypatch.setattr(main, '_reference_search_lanes', {})
    monkeypatch.setattr(main, 'active_reference_searches', {})
    monkeypatch.setattr(main, 'manager', SimpleNamespace(send_message=AsyncMock()))
    monkeypatch.setattr(main, '_source_pdf_path_for_check', AsyncMock(return_value=str(tmp_path / 'paper.pdf')))
    text = 'Introduction\nText.\n\nReferences\n' + '\n'.join(
        f'[{i}] A. Author, “Article number {i},” Solar energy, 2020.' for i in range(1, 5)
    )
    extractor = ProgressRefChecker.__new__(ProgressRefChecker)
    extractor.llm = None
    extractor.extraction_mode = 'cascade'
    extractor.check_id = check_id
    extractor.cancel_event = threading.Event()
    extractor.progress_callback = None
    extractor._extract_pdf_text_scoped = Mock(return_value=text)
    monkeypatch.setattr(main, '_create_document_reextractor', AsyncMock(return_value=extractor))
    user = main.UserInfo(id=0, name='Local', provider='local', is_admin=True)
    return main, database, check_id, extractor, user


def test_batch_reads_source_once_and_only_updates_errors_and_unverified(setup_batch, monkeypatch):
    main, database, check_id, extractor, user = setup_batch
    verified_uids = []

    async def verify(_check_id, ref_id, body, _user, *, source_reference, cancel_event, expected_reference):
        rows = await database.get_check_references(check_id)
        old = next(ref for ref in rows if f'uid:{ref["ref_uid"]}' == ref_id)
        assert old == expected_reference
        updated = {**old, **source_reference, 'status': 'verified'}
        assert body.force_all_databases
        assert not body.reextract_from_document
        assert await database.replace_check_reference_if_unchanged(check_id, old, updated) == 'saved'
        verified_uids.append(old['ref_uid'])
        return {'reference': updated}

    monkeypatch.setattr(main, '_verify_single_reference_impl', verify)

    async def scenario():
        rows = await database.get_check_references(check_id)
        rows[2].update(status='unverified', review_list='further_checks')
        await database.replace_check_references(check_id, rows)
        before = await database.get_check_references(check_id)
        await database.create_reference_search_operation('op', 'session', check_id, 'check:reextract-errors')
        await main._run_reference_reextraction_job(
            operation_id='op', session_id='session', check_id=check_id,
            current_user=user, cancel_event=threading.Event(),
        )
        after = await database.get_check_references(check_id)
        assert len(after) == len(before)
        assert [ref['ref_uid'] for ref in after] == [ref['ref_uid'] for ref in before]
        assert verified_uids == [ref['ref_uid'] for ref in before[:2]]
        assert after[2:] == before[2:]
        assert [ref['authors'] for ref in after[:2]] == [['A. Author'], ['A. Author']]
        operation = await database.get_reference_search_operation('op')
        assert operation['status'] == 'completed'
        assert operation['progress']['updated'] == operation['progress']['total'] == 2
        assert operation['progress']['failures'] == []

    asyncio.run(scenario())
    extractor._extract_pdf_text_scoped.assert_called_once()
    main._create_document_reextractor.assert_awaited_once()


def test_batch_keeps_failed_reference_and_continues(setup_batch, monkeypatch):
    main, database, check_id, extractor, user = setup_batch
    original = extractor._extract_references_for_reverification

    async def partial(text, numbers, **kwargs):
        refs, _ = await original(text, numbers, **kwargs)
        return refs[1:], [{'index': 1, 'message': 'Model returned no final answer text.'}]

    monkeypatch.setattr(extractor, '_extract_references_for_reverification', partial)
    verify = AsyncMock(return_value={'reference': {'index': 2, 'title': 'Article number 2'}})
    monkeypatch.setattr(main, '_verify_single_reference_impl', verify)

    async def scenario():
        before = await database.get_check_references(check_id)
        await database.create_reference_search_operation('op', 'session', check_id, 'check:reextract-errors')
        await main._run_reference_reextraction_job(
            operation_id='op', session_id='session', check_id=check_id,
            current_user=user, cancel_event=threading.Event(),
        )
        after = await database.get_check_references(check_id)
        assert after[0] == before[0]
        operation = await database.get_reference_search_operation('op')
        assert operation['progress']['completed'] == 2
        assert operation['progress']['updated'] == 1
        assert operation['progress']['failures'][0]['index'] == 1
    asyncio.run(scenario())
    assert verify.await_count == 1


@pytest.mark.parametrize('changed_title', [None, 'Correctly re-extracted title'])
def test_batch_searches_only_changed_records_and_preserves_unchanged_results(setup_batch, monkeypatch, changed_title):
    main, database, check_id, extractor, user = setup_batch
    verify = AsyncMock(return_value={'reference': {'index': 2, 'title': changed_title}})
    monkeypatch.setattr(main, '_verify_single_reference_impl', verify)
    original_extract = extractor._extract_references_for_reverification

    async def scenario():
        # Save the same citation data that a fresh source parse will produce,
        # retaining the original error and unverified results.
        fresh, _ = await original_extract(extractor._extract_pdf_text_scoped.return_value, [1, 2])
        rows = await database.get_check_references(check_id)
        for i in range(2):
            rows[i].update(title=fresh[i]['title'], authors=fresh[i]['authors'], year=fresh[i]['year'])
        rows[0]['cited_metadata'] = {
            'title': fresh[0]['title'], 'authors': fresh[0]['authors'], 'year': fresh[0]['year'],
        }
        rows[0]['authors'] = ['Display Author']
        rows[0]['doi'] = '10.1000/verified'
        rows[1].update(index=99, entry_number=2)
        rows[0]['errors'] = [{'error_type': 'author', 'error_details': 'Existing finding'}]
        rows[1]['errors'] = [{'error_type': 'unverified', 'error_details': 'Existing lookup result'}]
        await database.replace_check_references(check_id, rows)
        before = await database.get_check_references(check_id)

        async def reextract(text, numbers, **kwargs):
            parsed, failures = await original_extract(text, numbers, **kwargs)
            if changed_title:
                parsed[1]['title'] = changed_title
            return parsed, failures

        monkeypatch.setattr(extractor, '_extract_references_for_reverification', reextract)
        await database.create_reference_search_operation('op', 'session', check_id, 'check:reextract-errors')
        await main._run_reference_reextraction_job(
            operation_id='op', session_id='session', check_id=check_id,
            current_user=user, cancel_event=threading.Event(),
        )
        operation = await database.get_reference_search_operation('op')
        assert operation['status'] == 'completed'
        assert operation['progress']['unchanged'] == (1 if changed_title else 2)
        assert operation['progress']['updated'] == (1 if changed_title else 0)
        assert operation['progress']['failures'] == []
        after = await database.get_check_references(check_id)
        assert after[0]['errors'] == before[0]['errors']
        assert after[0]['authors'] == ['Display Author']
        assert after[0]['extraction_provenance']['source_text'].startswith('[1]')
        if changed_title:
            assert verify.await_count == 1
            assert verify.call_args.args[2].force_all_databases is True
            assert verify.call_args.kwargs['source_reference']['title'] == changed_title
        else:
            verify.assert_not_awaited()
            assert after[1]['errors'] == before[1]['errors']
            assert after[1]['extraction_provenance']['source_text'].startswith('[2]')

    asyncio.run(scenario())
    extractor._extract_pdf_text_scoped.assert_called_once()


def test_batch_cancellation_prevents_source_reads_and_updates(setup_batch):
    main, database, check_id, extractor, user = setup_batch
    cancelled = threading.Event()
    cancelled.set()

    async def scenario():
        await database.create_reference_search_operation('op', 'session', check_id, 'check:reextract-errors')
        await main._run_reference_reextraction_job(
            operation_id='op', session_id='session', check_id=check_id,
            current_user=user, cancel_event=cancelled,
        )
        assert (await database.get_reference_search_operation('op'))['status'] == 'cancelled'
    asyncio.run(scenario())
    extractor._extract_pdf_text_scoped.assert_not_called()


def test_central_action_is_owner_scoped_and_recovers_duplicate_job(setup_batch, monkeypatch):
    main, database, check_id, _extractor, user = setup_batch

    async def scenario():
        await database.create_reference_search_operation('op', 'session', check_id, 'check:reextract-errors')
        main.active_reference_searches['session'] = {'operation_id': 'op'}
        response = await main.start_reference_reextraction(check_id, user)
        assert response['operation_id'] == 'op'
        assert response['operation_type'] == 'reextract-errors'
        monkeypatch.setattr(main, 'get_user_id_filter', lambda _user: 999)
        with pytest.raises(HTTPException) as exc:
            await main.start_reference_reextraction(check_id, user)
        assert exc.value.status_code == 404
    asyncio.run(scenario())


def test_saved_reextraction_history_restores_active_and_completed_runs(setup_batch, monkeypatch):
    main, database, check_id, _extractor, user = setup_batch

    async def scenario():
        await database.create_reference_search_operation('finished', 'session-old', check_id, 'check:reextract-errors')
        await database.update_reference_search_operation('finished', status='completed', terminal=True,
            progress={'message': '53 of 73 verified; 20 need review.', 'completed': 73, 'updated': 53})
        await database.create_reference_search_operation('running', 'session-live', check_id, 'check:reextract-errors')
        await database.update_reference_search_operation('running', status='running',
            progress={'sequence': 20, 'completed': 5, 'total': 73, 'message': 'Re-extracting…'})
        result = await main.get_reference_reextractions(check_id, user)
        assert [op['operation_id'] for op in result['operations']] == ['running', 'finished']
        assert result['operations'][0]['progress']['completed'] == 5
        assert result['operations'][1]['progress']['updated'] == 53
        # Read-only restoration preserves the live job and its saved progress.
        assert (await database.get_reference_search_operation('running'))['status'] == 'running'
        monkeypatch.setattr(main, 'get_user_id_filter', lambda _user: 999)
        with pytest.raises(HTTPException) as exc:
            await main.get_reference_reextractions(check_id, user)
        assert exc.value.status_code == 404
        assert await database.list_reference_search_operations_for_check(check_id, 'check:reextract-errors', 999) == []
    asyncio.run(scenario())


def test_atomic_single_row_updates_preserve_other_rows_and_reject_stale_data(setup_batch):
    _main, database, check_id, _extractor, _user = setup_batch

    async def scenario():
        rows = await database.get_check_references(check_id)
        decisions = await asyncio.gather(*[
            database.replace_check_reference_if_unchanged(check_id, row, {**row, 'status': 'verified'})
            for row in rows[:2]
        ])
        assert decisions == ['saved', 'saved']
        assert await database.replace_check_reference_if_unchanged(check_id, rows[0], {**rows[0], 'title': 'Stale title'}) == 'reference_changed'
        stored = await database.get_check_references(check_id)
        assert [row['status'] for row in stored[:2]] == ['verified', 'verified']
        assert stored[2:] == rows[2:]
    asyncio.run(scenario())


def test_ordinary_card_reverification_runs_fresh_without_document_extraction(setup_batch, monkeypatch):
    main, database, check_id, _extractor, user = setup_batch
    from refchecker.core.refchecker import ArxivReferenceChecker

    verifier = Mock(return_value=({'unused': 'unused'}, None, None))
    # The service consumes the shared verifier's (findings, URL, metadata) tuple.
    verifier.return_value = ([], 'https://example.test/article', {'title': 'Article number 1'})
    monkeypatch.setattr(ArxivReferenceChecker, 'verify_reference_standard', verifier)
    monkeypatch.setattr(main, '_create_reference_search_checker', AsyncMock(return_value=object()))
    monkeypatch.setattr(main, 'project_verification_result', lambda target, *_args, **_kwargs: {
        **target, 'status': 'verified', 'errors': [], 'warnings': [],
    })
    lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(database, 'lookup_verified_reference', lookup)

    async def scenario():
        rows = await database.get_check_references(check_id)
        response = await main.verify_single_reference(check_id, f'uid:{rows[0]["ref_uid"]}', main._VerifySingleRequest(), user)
        assert response['reference']['status'] == 'verified'
        assert response['reference']['authors'] == rows[0]['authors']
        assert len(await database.get_check_references(check_id)) == len(rows)
    asyncio.run(scenario())
    main._create_document_reextractor.assert_not_awaited()
    lookup.assert_not_awaited()
    verifier.assert_called_once()
