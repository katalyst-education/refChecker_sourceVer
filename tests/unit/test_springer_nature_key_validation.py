import httpx
from fastapi.testclient import TestClient

from backend import main as backend_main
from backend.auth import UserInfo, require_user


def test_springer_nature_key_validation_uses_meta_v2(monkeypatch):
    app = backend_main.app
    app.dependency_overrides[require_user] = lambda: UserInfo(id=1, provider="test")
    captured = {}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, headers=None, params=None):
            captured.update({"url": url, "headers": headers, "params": params})
            return httpx.Response(200, json={"records": []})

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    try:
        response = TestClient(app).post(
            "/api/settings/springer-nature/validate",
            json={"api_key": "springer-key"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["valid"] is True
    assert captured["url"] == "https://api.springernature.com/meta/v2/json"
    assert captured["params"]["api_key"] == "springer-key"
    assert captured["params"]["q"] == "doi:10.1007/978-3-030-58259-3_6"


def test_springer_nature_key_validation_explains_inactive_subscription(monkeypatch):
    app = backend_main.app
    app.dependency_overrides[require_user] = lambda: UserInfo(id=1, provider="test")

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            return httpx.Response(401, json={"message": "Authentication failed"})

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    try:
        response = TestClient(app).post(
            "/api/settings/springer-nature/validate",
            json={"api_key": "inactive-key"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "invalid or has no active subscription" in response.json()["detail"]
    assert "API metric" in response.json()["detail"]


def test_springer_nature_key_validation_accepts_content_limited_key(monkeypatch):
    app = backend_main.app
    app.dependency_overrides[require_user] = lambda: UserInfo(id=1, provider="test")

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            return httpx.Response(403, json={"message": "Forbidden"})

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    try:
        response = TestClient(app).post(
            "/api/settings/springer-nature/validate",
            json={"api_key": "recognized-key"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["valid"] is True
    assert "accepted the key" in response.json()["message"]
    assert "content rights" in response.json()["message"]
