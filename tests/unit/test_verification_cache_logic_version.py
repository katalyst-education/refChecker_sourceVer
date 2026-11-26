#!/usr/bin/env python3
"""Cached verdicts must not outlive the logic that produced them.

The WebUI caches whole verification results keyed on a reference's identity and
replays them for any reference it has seen before. The cache had no notion of
*which code* produced a stored verdict, so a fixed bug was never visible for a
reference anyone had already checked — the stale verdict was replayed forever,
and even the "Re-verify" button replayed it.

Real case: reference 1 of the user's paper (a Kimi model card) kept reporting
"Cited URL does not reference this paper" from a cache entry written before the
blocked-URL fix, carrying ``from_cache: true``.

A logic-version stamp fixes this. Rows written by superseded logic stay in the
Seen References library but stop short-circuiting verification.
"""

import asyncio
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

import backend.database as backend_db  # noqa: E402
from backend.database import Database, cached_result_is_current  # noqa: E402
from refchecker.core.verification_logic_version import VERIFICATION_LOGIC_VERSION  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


KIMI = {
    'title': 'Kimi K3: Model weights and technical report',
    'authors': ['Moonshot AI'],
    'year': 2026,
    'venue': 'Open-weight release',
    'doi': '10.9/kimi-k3',
    'status': 'unverified',
    'errors': [{
        'error_type': 'url',
        'error_details': 'Cited URL does not reference this paper: https://huggingface.co/moonshotai/Kimi-K3',
    }],
}


class TestLogicVersionConstant:
    def test_version_is_a_positive_int(self):
        assert isinstance(VERIFICATION_LOGIC_VERSION, int)
        assert VERIFICATION_LOGIC_VERSION > 0

    def test_backend_reads_the_shared_core_value(self):
        """All three paths must agree on one value, so the backend reads the core."""
        assert backend_db.current_verification_logic_version() == VERIFICATION_LOGIC_VERSION


class TestCachedResultIsCurrent:
    def test_missing_stamp_is_stale(self):
        """Every row written before the stamp existed must be re-verified."""
        assert not cached_result_is_current({'logic_version': None})

    def test_absent_column_is_stale(self):
        """Can't prove currency without the column, so don't trust the row."""
        assert not cached_result_is_current({})

    def test_older_version_is_stale(self):
        assert not cached_result_is_current({'logic_version': VERIFICATION_LOGIC_VERSION - 1})

    def test_pre_arxiv_revision_year_verdict_is_stale(self):
        # Version 14 could warn about a year confirmed by the arXiv history.
        assert not cached_result_is_current({'logic_version': 14})

    def test_current_version_is_fresh(self):
        assert cached_result_is_current({'logic_version': VERIFICATION_LOGIC_VERSION})

    def test_unparseable_version_is_stale(self):
        assert not cached_result_is_current({'logic_version': 'banana'})


class TestCacheReplay:
    @pytest.mark.parametrize('lookup', ['lookup_verified_reference', 'find_verified_by_fuzzy'])
    @pytest.mark.parametrize('input_year,snapshot_year,result_year,hit', [
        (2025, 2026, 2026, False),
        (2026, 2025, 2026, False),
        (2025, 2025, 2026, False),
        (2026, None, 2026, False),
        (' 2026 ', 2026, 2026, True),
    ])
    def test_replay_checks_all_three_years(
        self, tmp_path, lookup, input_year, snapshot_year, result_year, hit,
    ):
        async def run():
            db = Database(str(tmp_path / 'years.db'))
            await db.init_db()
            cited = {
                'title': 'A technical report about publication versions',
                'authors': ['A. Author'], 'doi': '10.1234/test', 'year': input_year,
            }
            snapshot = dict(cited, year=snapshot_year) if snapshot_year else {'title': cited['title']}
            await db.upsert_verified_reference(dict(
                cited, year=result_year, cited_metadata=snapshot, status='verified',
            ))
            assert (await getattr(db, lookup)(cited) is not None) is hit

        _run(run())

    def test_fuzzy_rejects_other_dois_and_preprint_publication_pairs(self, tmp_path):
        async def run():
            db = Database(str(tmp_path / 'versions.db'))
            await db.init_db()
            published = {
                'title': 'A technical report about publication versions',
                'authors': ['A. Author'], 'doi': '10.1234/test', 'year': 2026,
            }
            await db.upsert_verified_reference(dict(published, status='verified'))
            for variant in (
                dict(published, doi='10.1234/other'),
                dict(published, doi=None, arxiv_id='2601.01234'),
            ):
                assert await db.find_verified_by_fuzzy(variant) is None

        _run(run())

    @pytest.mark.parametrize('input_ids,hit', [
        ({'cited_url': 'https://doi.org/10.1234/two'}, False),
        ({'cited_url': 'https://doi.org/10.1234/ONE?source=citation'}, True),
        ({'url': 'https://doi.org/10.1234/two'}, False),
        ({'cited_url': 'https://example.org/article', 'url': 'https://doi.org/10.1234/one'}, True),
        ({'cited_url': 'https://doi.org/10.1234/two', 'url': 'https://doi.org/10.1234/one'}, False),
        ({'doi': '10.1234/one', 'cited_url': 'https://doi.org/10.1234/two'}, True),
        ({'DOI': '10.1234/two', 'cited_url': 'https://doi.org/10.1234/one'}, False),
    ])
    @pytest.mark.parametrize('cached_ids', [
        {'doi': '10.1234/one'},
        {'authoritative_urls': [{'url': 'https://doi.org/10.1234/one'}]},
        {'cited_url': 'https://doi.org/10.1234/one'},
    ], ids=['doi', 'identity-doi', 'resolver-url'])
    def test_fuzzy_compares_dois_from_resolver_urls(self, tmp_path, input_ids, hit, cached_ids):
        async def run():
            db = Database(str(tmp_path / 'resolver-doi.db'))
            await db.init_db()
            citation = {
                'title': 'A technical report about publication versions',
                'authors': ['A. Author'], 'year': 2026,
            }
            identity = await db.upsert_verified_reference(dict(citation, **cached_ids, status='verified'))
            match = await db.find_verified_by_fuzzy(dict(citation, **input_ids))
            if hit:
                assert match is not None
                assert match['identity_key'] == identity
            else:
                assert match is None

        _run(run())

    def test_fuzzy_ranks_only_replayable_candidates(self, tmp_path):
        async def run():
            db = Database(str(tmp_path / 'candidates.db'))
            await db.init_db()
            cited = {
                'title': 'A technical report about publication versions',
                'authors': ['A. Author'], 'year': 2026,
            }
            await db.upsert_verified_reference(dict(
                cited, doi='10.1234/invalid', status='verified',
                cited_metadata=dict(cited, year=2025),
            ))
            await db.upsert_verified_reference(dict(
                cited, doi='10.1234/valid', status='warning', cited_metadata=cited,
            ))
            assert (await db.find_verified_by_fuzzy(cited))['doi'] == '10.1234/valid'

        _run(run())

    def test_identity_lookup_preserves_seen_count_after_replay_miss(self, tmp_path):
        async def run():
            db = Database(str(tmp_path / 'identity.db'))
            await db.init_db()
            await db.upsert_verified_reference(dict(KIMI))
            await db.upsert_verified_reference(dict(KIMI))
            changed = dict(KIMI, year=2025)
            assert await db.lookup_verified_reference(changed) is None
            assert (await db.lookup_reference_identity(changed))['times_seen'] == 2

        _run(run())

    def test_stale_entry_is_not_replayed_but_is_still_listed(self):
        tmp = tempfile.mktemp(suffix='.db')

        async def run():
            db = Database(tmp)
            await db.init_db()

            key = await db.upsert_verified_reference(dict(KIMI))
            assert key

            # Simulate an entry written by the previous release.
            import aiosqlite
            async with aiosqlite.connect(tmp) as raw:
                await raw.execute(
                    "UPDATE verified_reference_identity SET logic_version = NULL")
                await raw.commit()

            assert await db.lookup_verified_reference(dict(KIMI)) is None, \
                "A verdict from superseded logic must not short-circuit verification"
            assert await db.find_verified_by_fuzzy(dict(KIMI)) is None, \
                "The fuzzy lookup must respect the logic version too"

            # The library keeps showing it — we invalidate replay, not history.
            assert await db.count_verified_references() == 1
            rows = await db.list_verified_references()
            assert any(r.get('title') == KIMI['title'] for r in rows)

        try:
            _run(run())
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def test_current_entry_is_still_replayed(self):
        """The cache must keep working — it saves substantial network/LLM traffic."""
        tmp = tempfile.mktemp(suffix='.db')

        async def run():
            db = Database(tmp)
            await db.init_db()
            await db.upsert_verified_reference(dict(KIMI))

            cached = await db.lookup_verified_reference(dict(KIMI))
            assert cached is not None, "A freshly written entry must still be a cache hit"
            assert cached['result']['title'] == KIMI['title']

        try:
            _run(run())
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def test_reverify_overwrites_the_stale_row(self):
        """Re-checking a stale reference must refresh both the verdict and stamp."""
        tmp = tempfile.mktemp(suffix='.db')

        async def run():
            db = Database(tmp)
            await db.init_db()
            await db.upsert_verified_reference(dict(KIMI))

            import aiosqlite
            async with aiosqlite.connect(tmp) as raw:
                await raw.execute(
                    "UPDATE verified_reference_identity SET logic_version = NULL")
                await raw.commit()
            assert await db.lookup_verified_reference(dict(KIMI)) is None

            # The re-verification the cache miss forces, now clean.
            fixed = dict(KIMI, status='verified', errors=[])
            await db.upsert_verified_reference(fixed)

            cached = await db.lookup_verified_reference(dict(KIMI))
            assert cached is not None, "The refreshed entry must be usable again"
            assert cached['result']['errors'] == []
            assert await db.count_verified_references() == 1  # updated, not duplicated

        try:
            _run(run())
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)


class TestVerificationCacheKey:
    def test_key_changes_with_the_logic_version(self, monkeypatch):
        """The second cache is versioned via its key rather than a column."""
        db = Database(tempfile.mktemp(suffix='.db'))
        before = db._compute_reference_cache_key(dict(KIMI))

        monkeypatch.setattr(
            backend_db, 'current_verification_logic_version',
            lambda: VERIFICATION_LOGIC_VERSION + 1)
        after = db._compute_reference_cache_key(dict(KIMI))

        assert before != after, "Superseded results must stop being addressable"

    def test_key_is_stable_for_the_same_reference(self):
        db = Database(tempfile.mktemp(suffix='.db'))
        assert db._compute_reference_cache_key(dict(KIMI)) == \
            db._compute_reference_cache_key(dict(KIMI))
