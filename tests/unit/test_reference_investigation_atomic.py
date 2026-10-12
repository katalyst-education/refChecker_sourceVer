import asyncio
import json
import sqlite3

import aiosqlite
import pytest

from backend.database import Database


async def create_database(path):
    database = Database(str(path))
    await database.init_db()
    rows = [{'id': str(i), 'title': f'Work {i}', 'authors': ['An Author'], 'year': 2007, 'status': 'unverified'} for i in (1, 2)]
    async with aiosqlite.connect(database.db_path) as conn:
        await conn.execute("INSERT INTO check_history (id, paper_title, paper_source, results_json) VALUES (1, 'Paper', 'test', ?)", (json.dumps(rows),))
        await conn.commit()
    return database, await database.get_check_references(1)


def test_concurrent_updates_to_different_rows_preserve_both_and_their_evidence(tmp_path):
    async def scenario():
        database, rows = await create_database(tmp_path / 'atomic.db')
        async def update(i):
            evidence = {'id': f'evidence-{i}', 'source_url': f'https://example.org/{i}', 'retrieved_metadata': {'title': rows[i]['title']}, 'comparison': {'confirmed': True}}
            return await database.commit_reference_investigation(1, rows[i], {**rows[i], 'status': 'verified', 'verification_evidence': evidence}, evidence)
        assert await asyncio.gather(update(0), update(1)) == ['saved', 'saved']
        stored = await database.get_check_references(1)
        assert all(row['status'] == 'verified' for row in stored)
        assert stored[0]['verification_evidence']['source_url'] == 'https://example.org/0'
        async with aiosqlite.connect(database.db_path) as conn:
            counts = await (await conn.execute('SELECT refs_verified, unverified_count FROM check_history WHERE id = 1')).fetchone()
            assert counts == (2, 0)
            assert (await (await conn.execute('SELECT COUNT(*) FROM reference_investigation_evidence')).fetchone())[0] == 2
        identity = await database.upsert_verified_reference(stored[0], check_id=1)
        assert identity
        cached = await database.lookup_verified_reference(stored[0])
        assert cached['result']['verification_evidence'] == stored[0]['verification_evidence']
    asyncio.run(scenario())


def test_stale_same_row_is_not_overwritten_and_audit_survives(tmp_path):
    async def scenario():
        database, rows = await create_database(tmp_path / 'stale.db')
        assert await database.commit_reference_investigation(1, rows[0], {**rows[0], 'status': 'verified'}, {'id': 'first'}) == 'saved'
        assert await database.commit_reference_investigation(1, rows[0], {**rows[0], 'title': 'Stale change'}, {'id': 'second'}) == 'reference_changed'
        assert (await database.get_check_references(1))[0]['title'] == rows[0]['title']
        async with aiosqlite.connect(database.db_path) as conn:
            assert (await (await conn.execute("SELECT decision FROM reference_investigation_evidence WHERE id = 'second'")).fetchone())[0] == 'reference_changed'
    asyncio.run(scenario())


def test_evidence_failure_rolls_back_reference_update_and_respects_ownership(tmp_path):
    async def scenario():
        database, rows = await create_database(tmp_path / 'rollback.db')
        assert await database.commit_reference_investigation(1, rows[0], None, {'id': 'once'}) == 'recorded'
        with pytest.raises(sqlite3.IntegrityError):
            await database.commit_reference_investigation(1, rows[0], {**rows[0], 'status': 'verified'}, {'id': 'once'})
        assert (await database.get_check_references(1))[0]['status'] == 'unverified'
        assert await database.commit_reference_investigation(1, rows[0], None, {'id': 'unauthorized'}, user_id=999) == 'not_found'
    asyncio.run(scenario())


def test_investigation_history_is_newest_first_and_owner_scoped(tmp_path):
    async def scenario():
        database, rows = await create_database(tmp_path / 'history.db')
        async with aiosqlite.connect(database.db_path) as conn:
            await conn.execute('UPDATE check_history SET user_id = 7 WHERE id = 1')
            await conn.commit()

        reference_key = str(rows[0].get('ref_uid') or rows[0]['id'])
        first = {
            'id': 'first',
            'selected_suggestion': {'title': 'First candidate'},
            'comparison': {'fields': []},
        }
        second = {
            'id': 'second',
            'selected_suggestion': {'title': 'Second candidate'},
            'comparison': {'fields': []},
        }
        assert await database.commit_reference_investigation(1, rows[0], None, first, user_id=7) == 'recorded'
        assert await database.commit_reference_investigation(1, rows[0], None, second, user_id=7) == 'recorded'

        history = await database.list_reference_investigations(1, reference_key, user_id=7)
        assert [entry['id'] for entry in history] == ['second', 'first']
        assert history[0]['evidence']['selected_suggestion']['title'] == 'Second candidate'
        assert await database.list_reference_investigations(1, reference_key, user_id=8) == []
    asyncio.run(scenario())
