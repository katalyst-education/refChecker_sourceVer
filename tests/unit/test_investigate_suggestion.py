import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from backend import main
from backend.auth import UserInfo
from refchecker.core.refchecker import ArxivReferenceChecker


def test_investigation_uses_shared_verifier_without_saving(monkeypatch):
    original = {'id': '1', 'title': 'Original citation'}
    monkeypatch.setattr(main.db, 'get_check_references', AsyncMock(return_value=[original]))
    save = AsyncMock()
    monkeypatch.setattr(main.db, 'replace_check_references', save)
    monkeypatch.setattr(main.db, 'upsert_verified_reference', save)
    commit = AsyncMock(return_value='recorded')
    monkeypatch.setattr(main.db, 'commit_reference_investigation', commit)
    for name in ('_resolve_semantic_scholar_api_key', '_resolve_google_books_api_key', '_resolve_paperclip_api_key'):
        monkeypatch.setattr(main, name, AsyncMock(return_value=None))
    checker = object()
    monkeypatch.setattr(main, '_create_reference_search_checker', AsyncMock(return_value=checker))
    candidate = main._InvestigateSuggestionRequest(
        title='Selected candidate', authors=['An Author'], year=2007,
        url='https://university.example/report',
    )

    def verify(self, paper, reference, force_all_databases=False):
        assert self.non_arxiv_checker is checker
        assert force_all_databases is True
        assert reference['title'] == 'Selected candidate'
        assert reference['url'] == candidate.url
        return [], candidate.url, {**reference, '_matched_database': 'Semantic Scholar'}

    monkeypatch.setattr(ArxivReferenceChecker, 'verify_reference_standard', verify)
    result = asyncio.run(main.investigate_reference_suggestion(
        42, '1', candidate, UserInfo(id=1, provider='test'),
    ))
    assert result['saved'] is False
    assert result['reference']['status'] == 'verified'
    assert result['reference']['matched_database'] == 'Semantic Scholar'
    assert original == {'id': '1', 'title': 'Original citation'}
    save.assert_not_called()
    assert commit.await_args.args[2] is None
    assert commit.await_args.args[3]['retrieved_metadata']['title'] == 'Selected candidate'


def test_investigation_requires_access_to_original_reference(monkeypatch):
    monkeypatch.setattr(main.db, 'get_check_references', AsyncMock(return_value=None))
    create = AsyncMock()
    monkeypatch.setattr(main, '_create_reference_search_checker', create)
    with pytest.raises(HTTPException) as error:
        asyncio.run(main.investigate_reference_suggestion(
            42, '1', main._InvestigateSuggestionRequest(title='Candidate'), UserInfo(id=1, provider='test'),
        ))
    assert error.value.status_code == 404
    create.assert_not_called()


def test_investigation_history_requires_the_owned_reference(monkeypatch):
    original = {'id': '1', 'ref_uid': 'ref-1', 'title': 'Original citation'}
    monkeypatch.setattr(main.db, 'get_check_references', AsyncMock(return_value=[original]))
    history = AsyncMock(return_value=[{
        'id': 'evidence-1',
        'decision': 'recorded',
        'created_at': '2026-10-12 10:00:00',
        'evidence': {'selected_suggestion': {'title': 'Candidate'}},
    }])
    monkeypatch.setattr(main.db, 'list_reference_investigations', history)

    result = asyncio.run(main.list_reference_investigations(
        42, 'uid:ref-1', UserInfo(id=1, provider='test'),
    ))

    assert result['investigations'][0]['id'] == 'evidence-1'
    history.assert_awaited_once_with(42, 'ref-1', user_id=1)


@pytest.mark.parametrize('retrieved_year, should_save', [(2007, True), (2008, False), (None, False)])
def test_promotion_compares_original_to_retrieved_record_not_suggestion(monkeypatch, retrieved_year, should_save):
    original = {'id': '1', 'title': 'The original work', 'authors': ['An Author'], 'year': 2007}
    monkeypatch.setattr(main.db, 'get_check_references', AsyncMock(return_value=[original]))
    commit = AsyncMock(return_value='saved' if should_save else 'recorded')
    monkeypatch.setattr(main.db, 'commit_reference_investigation', commit)
    cache = AsyncMock(return_value='identity')
    monkeypatch.setattr(main.db, 'upsert_verified_reference', cache)
    for name in ('_resolve_semantic_scholar_api_key', '_resolve_google_books_api_key', '_resolve_paperclip_api_key'):
        monkeypatch.setattr(main, name, AsyncMock(return_value=None))
    monkeypatch.setattr(main, '_create_reference_search_checker', AsyncMock(return_value=object()))
    monkeypatch.setattr(ArxivReferenceChecker, 'verify_reference_standard', lambda *args, **kwargs: (
        [{'warning_type': 'year', 'warning_details': 'The suggestion has the wrong year'}],
        'https://example.org/source', {**original, 'year': retrieved_year, '_matched_database': 'CrossRef'},
    ))
    request = main._InvestigateSuggestionRequest(title=original['title'], authors=['An Author'], year=2008, source='llm')
    result = asyncio.run(main.investigate_reference_suggestion(42, '1', request, UserInfo(id=1, provider='test')))
    assert result['saved'] is should_save
    evidence = commit.await_args.args[3]
    assert evidence['selected_suggestion']['year'] == 2008
    assert evidence['retrieved_metadata']['year'] == retrieved_year
    assert evidence['comparison']['confirmed'] is should_save
    if should_save:
        assert result['updated_reference']['year'] == 2007
        assert result['updated_reference']['warnings'] == []
        assert result['updated_reference']['verification_evidence']['source_url'] == 'https://example.org/source'
    else:
        assert commit.await_args.args[2] is None
        cache.assert_not_called()


@pytest.mark.parametrize('changed, cache_failure, web_metadata', [
    (False, False, None), (True, False, None), (False, True, None),
    (False, False, {'status_code': 403, 'access_blocked': True}),
    (False, False, {'status_code': 200, 'content_type': 'application/pdf'}),
])
def test_confirmed_original_is_saved_without_overwriting_concurrent_edits(monkeypatch, changed, cache_failure, web_metadata):
    original = {'id': '1', 'title': 'Original citation', 'authors': ['An Author'], 'year': 2007}
    current = {**original, 'title': 'User edit'} if changed else dict(original)
    monkeypatch.setattr(main.db, 'get_check_references', AsyncMock(side_effect=[[dict(original)], [current]]))
    save = AsyncMock(return_value=True)
    cache = AsyncMock(side_effect=RuntimeError('Cache unavailable')) if cache_failure else AsyncMock(return_value='identity')
    monkeypatch.setattr(main.db, 'replace_check_references', save)
    monkeypatch.setattr(main.db, 'upsert_verified_reference', cache)
    commit = AsyncMock(return_value='reference_changed' if changed else 'recorded' if web_metadata else 'saved')
    monkeypatch.setattr(main.db, 'commit_reference_investigation', commit)
    for name in ('_resolve_semantic_scholar_api_key', '_resolve_google_books_api_key', '_resolve_paperclip_api_key'):
        monkeypatch.setattr(main, name, AsyncMock(return_value=None))
    monkeypatch.setattr(main, '_create_reference_search_checker', AsyncMock(return_value=object()))
    monkeypatch.setattr(ArxivReferenceChecker, 'verify_reference_standard', lambda *args, **kwargs: (
        [], 'https://example.org/confirmed', {**original, '_matched_database': 'CrossRef', 'web_metadata': web_metadata},
    ))
    request = main._InvestigateSuggestionRequest(title=original['title'], authors=original['authors'], year=2007)
    if changed:
        with pytest.raises(HTTPException) as error:
            asyncio.run(main.investigate_reference_suggestion(42, '1', request, UserInfo(id=1, provider='test')))
        assert error.value.status_code == 409
        save.assert_not_called()
        cache.assert_not_called()
    else:
        result = asyncio.run(main.investigate_reference_suggestion(42, '1', request, UserInfo(id=1, provider='test')))
        if web_metadata:
            assert result['saved'] is False
            assert result['save_reason'] == 'source_accessibility_only'
            save.assert_not_called()
            cache.assert_not_called()
            return
        assert result['saved'] is True
        assert result['cache_saved'] is not cache_failure
        assert result['updated_reference']['status'] == 'verified'
        assert result['updated_reference']['title'] == original['title']
        save.assert_not_called()
        commit.assert_awaited_once()
        assert commit.await_args.args[2]['verification_evidence']['comparison']['confirmed'] is True
        cache.assert_awaited_once()
