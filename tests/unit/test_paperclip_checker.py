from __future__ import annotations

import sys
import types

from refchecker.checkers.paperclip import PaperclipReferenceChecker


def test_paperclip_init_supports_auth_strategy_constructor(monkeypatch):
    class FakeAPIKeyAuth:
        def __init__(self, api_key: str):
            self.api_key = api_key

    class FakePaperclipClient:
        def __init__(self, auth):
            self.auth = auth

    fake_module = types.SimpleNamespace(
        APIKeyAuth=FakeAPIKeyAuth,
        PaperclipClient=FakePaperclipClient,
    )
    monkeypatch.setitem(sys.modules, "gxl_paperclip", fake_module)

    checker = PaperclipReferenceChecker(api_key="pc-auth-key")

    assert checker.enabled is True
    assert checker.client is not None
    assert isinstance(checker.client.auth, FakeAPIKeyAuth)
    assert checker.client.auth.api_key == "pc-auth-key"


def test_paperclip_init_supports_legacy_api_key_constructor(monkeypatch):
    seen: dict[str, str] = {}

    class FakePaperclipClient:
        def __init__(self, api_key: str):
            seen["api_key"] = api_key

    fake_module = types.SimpleNamespace(PaperclipClient=FakePaperclipClient)
    monkeypatch.setitem(sys.modules, "gxl_paperclip", fake_module)

    checker = PaperclipReferenceChecker(api_key="pc-legacy-key")

    assert checker.enabled is True
    assert seen["api_key"] == "pc-legacy-key"


def test_safe_call_reads_execute_result_papers(monkeypatch):
    class FakeAPIKeyAuth:
        def __init__(self, api_key: str):
            self.api_key = api_key

    class FakeExecuteResult:
        @property
        def papers(self):
            return [{"doi": "10.1000/example"}]

    class FakePaperclipClient:
        def __init__(self, auth):
            self.auth = auth

        def lookup(self, *_args, **_kwargs):
            return FakeExecuteResult()

    fake_module = types.SimpleNamespace(
        APIKeyAuth=FakeAPIKeyAuth,
        PaperclipClient=FakePaperclipClient,
    )
    monkeypatch.setitem(sys.modules, "gxl_paperclip", fake_module)

    checker = PaperclipReferenceChecker(api_key="pc-auth-key")
    results = checker.lookup_by_doi("10.1000/example")

    assert results == [{"doi": "10.1000/example"}]
