"""Saved checks reuse model endpoints during single-reference extraction."""

import asyncio
import threading
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from backend.database import Database


@pytest.fixture
def configured_app(tmp_path, monkeypatch):
    monkeypatch.setenv('REFCHECKER_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('REFCHECKER_MULTIUSER', 'false')
    from backend import main

    database = Database(str(tmp_path / 'history.db'))
    asyncio.run(database.init_db())
    monkeypatch.setattr(main, 'db', database)
    monkeypatch.setattr('refchecker.config.settings.resolve_endpoint', lambda provider: None)
    return main, database


def resolve(main, **overrides):
    return main._resolve_llm_config_for_request(**{
        'user_id': None,
        'use_llm': True,
        'llm_config_id': None,
        'llm_provider': 'vllm',
        'llm_model': 'ds41',
        'api_key': None,
        **overrides,
    })


def create_config(database, *, is_default=False, **kwargs):
    config_id = asyncio.run(database.create_llm_config(**kwargs))
    if is_default:
        asyncio.run(database.set_default_llm_config(config_id, user_id=kwargs.get('user_id')))
    return config_id


def test_history_model_reuses_full_saved_configuration(configured_app):
    main, database = configured_app
    config_id = create_config(database,
        name='Remote model', provider='vllm', model='ds41',
        endpoint='http://model-server.test:8001', is_default=True,
        reasoning_effort='none', max_tokens=8000,
        context_length=32000, timeout_seconds=600,
    )

    by_id = asyncio.run(resolve(main, llm_config_id=config_id))
    by_history = asyncio.run(resolve(main))

    assert by_history == by_id == (
        'vllm', 'ds41', None, 'http://model-server.test:8001',
        'none', 8000, 32000, 600,
    )
    from refchecker.llm.providers import vLLMProvider

    provider = vLLMProvider({
        'model': by_history[1], 'endpoint': by_history[3], 'skip_initialization': True,
    })
    assert provider.server_url == 'http://model-server.test:8001'
    assert provider.auto_start_server is False


def test_matching_default_config_precedes_newer_same_model(configured_app):
    main, database = configured_app
    create_config(database,
        name='Default', provider='vllm', model='ds41',
        endpoint='http://default.test:8001', is_default=True,
    )
    other_id = asyncio.run(database.create_llm_config(
        name='Other', provider='vllm', model='ds41',
        endpoint='http://other.test:8002',
    ))

    assert asyncio.run(resolve(main))[3] == 'http://default.test:8001'
    assert asyncio.run(resolve(main, llm_config_id=other_id))[3] == 'http://other.test:8002'


def test_history_model_uses_latest_matching_config_without_default(configured_app):
    main, database = configured_app
    for endpoint in ('http://old.test:8001', 'http://latest.test:8001'):
        asyncio.run(database.create_llm_config(
            name='Model', provider='vllm', model='ds41', endpoint=endpoint,
        ))

    assert asyncio.run(resolve(main))[3] == 'http://latest.test:8001'


@pytest.mark.parametrize('provider,model', [('vllm', 'other-model'), ('lmstudio', 'ds41')])
def test_history_model_matches_both_provider_and_model(configured_app, provider, model):
    main, database = configured_app
    create_config(database,
        name='Unrelated', provider=provider, model=model,
        endpoint='http://unrelated.test:8001', is_default=True,
    )

    assert asyncio.run(resolve(main))[3] is None


def test_request_key_precedes_matching_saved_key(configured_app):
    main, database = configured_app
    asyncio.run(database.create_llm_config(
        name='Remote', provider='openai', model='test-model',
        endpoint='https://models.example.test/v1', api_key='stored-test-key',
    ))

    resolved = asyncio.run(resolve(
        main, llm_provider='openai', llm_model='test-model', api_key='request-test-key',
    ))
    assert resolved[2] == 'request-test-key'
    assert resolved[3] == 'https://models.example.test/v1'


def test_matching_configuration_is_user_scoped(configured_app):
    main, database = configured_app
    for user_id, endpoint in [(1, 'http://mine.test:8001'), (2, 'http://other.test:8001')]:
        create_config(database,
            name='Remote', provider='vllm', model='ds41', endpoint=endpoint,
            user_id=user_id, is_default=True,
        )

    assert asyncio.run(resolve(main, user_id=1))[3] == 'http://mine.test:8001'


def test_reverify_initializes_provider_off_event_loop_with_saved_endpoint(configured_app, monkeypatch):
    main, database = configured_app
    from backend import refchecker_wrapper

    create_config(database,
        name='Remote', provider='vllm', model='ds41',
        endpoint='http://model-server.test:8001', is_default=True,
    )
    target = {'index': 21, 'ref_uid': 'ref-test', 'title': 'A solar cell article'}
    monkeypatch.setattr(database, 'get_check_references', AsyncMock(return_value=[target]))
    monkeypatch.setattr(database, 'get_check_by_id', AsyncMock(return_value={
        'id': 25, 'llm_provider': 'vllm', 'llm_model': 'ds41',
    }))
    captured = {}
    event_loop_thread = threading.get_ident()

    class StopAfterInitialization:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            captured['thread'] = threading.get_ident()
            raise RuntimeError('stop after observing provider initialization')

    monkeypatch.setattr(refchecker_wrapper, 'ProgressRefChecker', StopAfterInitialization)
    local_user = main.UserInfo(id=0, name='Local', provider='local', is_admin=True)
    with pytest.raises(HTTPException, match='stop after observing'):
        asyncio.run(main.verify_single_reference(
            25, 'uid:ref-test', body=main._VerifySingleRequest(reextract_from_document=True), current_user=local_user,
        ))

    assert captured['endpoint'] == 'http://model-server.test:8001'
    assert captured['llm_provider'] == 'vllm'
    assert captured['llm_model'] == 'ds41'
    assert captured['thread'] != event_loop_thread
