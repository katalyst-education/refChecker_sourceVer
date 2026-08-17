"""Suggest-alternative must not hard-fail when Semantic Scholar rate-limits."""

import asyncio

import httpx
from fastapi.testclient import TestClient

from backend import main as backend_main
from backend.auth import UserInfo, require_user


def test_suggest_alternative_uses_fallback_on_s2_429(monkeypatch):
    app = backend_main.app
    app.dependency_overrides[require_user] = lambda: UserInfo(id=1, provider="test")

    async def _get_check_references(check_id, user_id=None):
        if check_id != 42:
            return None
        return [{
            "id": "1",
            "index": 1,
            "title": "A deep dive into OpenStreetMap research since its inception (2008-2024): contributors, topics, and future trends",
            "authors": ["Someone"],
            "year": 2024,
        }]

    async def _no_default_llm(user_id=None):
        return None

    async def _no_api_key(_user_id):
        return None

    async def _fast_sleep(_seconds):
        return None

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params=None, headers=None, timeout=None):
            if "semanticscholar.org/graph/v1/paper/search" in url:
                return httpx.Response(429, headers={"Retry-After": "0"})
            if "api.crossref.org/works" in url:
                return httpx.Response(
                    200,
                    json={
                        "message": {
                            "items": [{
                                "DOI": "10.1000/osm.2024.1",
                                "title": ["OpenStreetMap at Scale"],
                                "author": [{"given": "Ada", "family": "Lovelace"}],
                                "issued": {"date-parts": [[2024, 1, 1]]},
                                "container-title": ["Journal of Mapping"],
                            }]
                        }
                    },
                )
            if "api.openalex.org/works" in url:
                return httpx.Response(200, json={"results": []})
            return httpx.Response(200, json={})

    monkeypatch.setattr(backend_main.db, "get_check_references", _get_check_references)
    monkeypatch.setattr(backend_main.db, "get_default_llm_config", _no_default_llm)
    monkeypatch.setattr(backend_main, "_resolve_semantic_scholar_api_key", _no_api_key)
    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    client = TestClient(app)
    try:
        resp = client.post("/api/history/42/references/1/suggest-alternative")
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("rate_limited") is True
        candidates = body.get("candidates") or []
        assert any(c.get("source") == "crossref" for c in candidates)
    finally:
        app.dependency_overrides.clear()
