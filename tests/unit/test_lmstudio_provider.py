from types import SimpleNamespace

import openai
import requests

from refchecker.llm.base import create_llm_provider
from refchecker.llm.providers import LMStudioProvider
from refchecker.utils.config_validator import ConfigValidator


def _fake_openai_client(calls, content='["Example reference"]'):
    class Completions:
        @staticmethod
        def create(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=content, reasoning_content=""),
                        finish_reason="stop",
                    )
                ],
                usage=None,
            )

    return SimpleNamespace(chat=SimpleNamespace(completions=Completions()))


def test_lmstudio_defaults_to_disabled_reasoning(monkeypatch):
    calls = []
    monkeypatch.setattr(openai, "OpenAI", lambda **_kwargs: _fake_openai_client(calls))

    provider = LMStudioProvider({
        "model": "qwen/test",
        "endpoint": "http://localhost:1234/v1",
    })

    assert provider.server_url == "http://localhost:1234"
    assert provider._call_llm("Extract the references") == '["Example reference"]'
    assert calls[0]["extra_body"] == {"reasoning_effort": "none"}


def test_lmstudio_server_default_omits_reasoning_override(monkeypatch):
    calls = []
    monkeypatch.setattr(openai, "OpenAI", lambda **_kwargs: _fake_openai_client(calls))

    provider = LMStudioProvider({
        "model": "qwen/test",
        "reasoning_effort": "default",
    })
    provider._call_llm("Extract the references")

    assert "extra_body" not in calls[0]


def test_lmstudio_uses_configured_generation_timeout(monkeypatch):
    client_config = {}

    def fake_client(**kwargs):
        client_config.update(kwargs)
        return _fake_openai_client([])

    monkeypatch.setattr(openai, "OpenAI", fake_client)
    provider = LMStudioProvider({
        "model": "qwen/test",
        "timeout_seconds": 21600,
    })

    assert provider.timeout_seconds == 21600
    assert client_config["timeout"].read == 21600
    assert client_config["timeout"].connect == 5


def test_lmstudio_retries_reasoning_only_response_with_reasoning_disabled(monkeypatch):
    calls = []

    class Completions:
        @staticmethod
        def create(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                message = SimpleNamespace(content="", reasoning_content="thinking " * 100)
                finish_reason = "length"
            else:
                message = SimpleNamespace(content='["Recovered reference"]', reasoning_content="")
                finish_reason = "stop"
            return SimpleNamespace(
                choices=[SimpleNamespace(message=message, finish_reason=finish_reason)],
                usage=None,
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    monkeypatch.setattr(openai, "OpenAI", lambda **_kwargs: client)
    provider = LMStudioProvider({
        "model": "qwen/test",
        "reasoning_effort": "high",
    })

    assert provider._call_llm("Extract the references") == '["Recovered reference"]'
    assert calls[0]["extra_body"] == {"reasoning_effort": "high"}
    assert calls[1]["extra_body"] == {"reasoning_effort": "none"}


def test_lmstudio_is_registered_and_requires_model(monkeypatch):
    calls = []
    monkeypatch.setattr(openai, "OpenAI", lambda **_kwargs: _fake_openai_client(calls))

    provider = create_llm_provider("lmstudio", {"model": "loaded-model"})

    assert isinstance(provider, LMStudioProvider)
    assert create_llm_provider("lmstudio", {}) is None


def test_lmstudio_config_validation():
    validator = ConfigValidator()

    valid = validator._validate_llm_provider_config(
        "lmstudio",
        {"server_url": "http://localhost:1234", "reasoning_effort": "none"},
    )
    invalid = validator._validate_llm_provider_config(
        "lmstudio",
        {
            "server_url": "localhost:1234",
            "reasoning_effort": "extreme",
            "timeout_seconds": 5,
        },
    )

    assert valid.is_valid
    assert not invalid.is_valid
    assert len(invalid.errors) == 3


def test_lmstudio_reloads_selected_model_when_context_changes(monkeypatch):
    calls = []
    monkeypatch.setattr(openai, "OpenAI", lambda **_kwargs: _fake_openai_client([]))

    class Response:
        def __init__(self, payload=None):
            self._payload = payload or {}

        def json(self):
            return self._payload

        @staticmethod
        def raise_for_status():
            return None

    model_payload = {
        "models": [{
            "key": "qwen/test",
            "max_context_length": 262144,
            "loaded_instances": [{
                "id": "qwen/test",
                "config": {
                    "context_length": 8192,
                    "eval_batch_size": 512,
                    "flash_attention": True,
                },
            }],
        }],
    }
    monkeypatch.setattr(requests, "get", lambda *_args, **_kwargs: Response(model_payload))

    def fake_post(url, **kwargs):
        calls.append((url, kwargs["json"]))
        return Response()

    monkeypatch.setattr(requests, "post", fake_post)
    provider = LMStudioProvider({
        "model": "qwen/test",
        "endpoint": "http://localhost:1234",
        "context_length": 16384,
        "max_tokens": 4000,
    })

    assert provider.is_available()
    assert calls == [
        (
            "http://localhost:1234/api/v1/models/unload",
            {"instance_id": "qwen/test"},
        ),
        (
            "http://localhost:1234/api/v1/models/load",
            {
                "model": "qwen/test",
                "context_length": 16384,
                "echo_load_config": True,
                "eval_batch_size": 512,
                "flash_attention": True,
            },
        ),
    ]


def test_lmstudio_chunk_budget_uses_context_and_output_limits(monkeypatch):
    monkeypatch.setattr(openai, "OpenAI", lambda **_kwargs: _fake_openai_client([]))
    provider = LMStudioProvider({
        "model": "qwen/test",
        "context_length": 8192,
        "max_tokens": 4000,
    })
    observed = {}
    monkeypatch.setattr(provider, "is_available", lambda: True)

    def fake_chunk(_text, max_tokens):
        observed["max_input_tokens"] = max_tokens
        return ["chunk"]

    monkeypatch.setattr(provider, "_chunk_bibliography", fake_chunk)
    monkeypatch.setattr(provider, "_process_chunks_parallel", lambda _chunks: [])

    provider.extract_references_with_chunking("x" * 20000)

    assert observed["max_input_tokens"] == 3892
