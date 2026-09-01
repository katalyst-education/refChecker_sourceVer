from refchecker.authenticated_browser import (
    AuthenticatedBrowserManager,
    AuthenticatedBrowserUnavailable,
    BrowserPageResponse,
    authenticated_browser_profile,
    current_authenticated_browser_profile,
)
from refchecker.checkers.webpage_checker import WebPageChecker
from refchecker.core.refchecker import ArxivReferenceChecker
from backend.reference_status import classify_verification_result, split_errors_and_warnings
from backend.reference_result import project_verification_result


def test_authenticated_profile_scope_does_not_leak(monkeypatch):
    monkeypatch.delenv("REFCHECKER_AUTH_BROWSER_PROFILE", raising=False)
    assert current_authenticated_browser_profile() is None
    with authenticated_browser_profile("local-test"):
        assert current_authenticated_browser_profile() == "local-test"
    assert current_authenticated_browser_profile() is None


def test_webpage_fetch_uses_scoped_browser_session(monkeypatch):
    class FakeManager:
        def fetch(self, profile_key, url):
            assert profile_key == "local-test"
            return BrowserPageResponse(
                url="https://example.org/record",
                content=b"<html><title>Authenticated record</title></html>",
            )

    monkeypatch.setattr(
        "refchecker.authenticated_browser.get_authenticated_browser_manager",
        lambda: FakeManager(),
    )
    checker = WebPageChecker(request_delay=0)
    monkeypatch.setattr(
        checker.session,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("ordinary HTTP fetch used")),
    )

    with authenticated_browser_profile("local-test"):
        response = checker._respectful_request("https://example.org/record")

    assert response.url == "https://example.org/record"
    assert b"Authenticated record" in response.content


def test_browser_manager_reuses_one_visible_session(tmp_path, monkeypatch):
    class FakeDriver:
        current_url = ""
        page_source = "<html><title>Protected record</title></html>"
        quit_calls = 0

        def get(self, url):
            self.current_url = url

        def quit(self):
            self.quit_calls += 1

    driver = FakeDriver()
    manager = AuthenticatedBrowserManager(tmp_path)
    monkeypatch.setattr(manager, "_new_driver", lambda profile_key: driver)

    manager.open_login("local", "https://example.org/login")
    page = manager.fetch("local", "https://example.org/record")

    assert page.url == "https://example.org/record"
    assert b"Protected record" in page.content
    assert manager.status("local")["active"] is True
    assert manager.close("local") is True
    assert driver.quit_calls == 1


def test_browser_manager_rejects_empty_driver(tmp_path, monkeypatch):
    manager = AuthenticatedBrowserManager(tmp_path)
    monkeypatch.setattr(manager, "_new_driver", lambda profile_key: None)

    try:
        manager.open_login("local", "https://example.org/login")
    except AuthenticatedBrowserUnavailable as exc:
        assert "did not create a session" in str(exc)
    else:
        raise AssertionError("An empty browser driver was accepted")


def test_browser_manager_reopens_after_user_closes_window(tmp_path, monkeypatch):
    class InvalidSessionIdException(Exception):
        pass

    class FakeDriver:
        def __init__(self):
            self.current_url = ""
            self.page_source = "<html><title>Protected record</title></html>"
            self.closed = False
            self.quit_calls = 0

        def get(self, url):
            if self.closed:
                raise InvalidSessionIdException("invalid session id")
            self.current_url = url

        def quit(self):
            self.closed = True
            self.quit_calls += 1

    first = FakeDriver()
    replacement = FakeDriver()
    drivers = iter((first, replacement))
    manager = AuthenticatedBrowserManager(tmp_path)
    monkeypatch.setattr(manager, "_new_driver", lambda profile_key: next(drivers))

    manager.open_login("local", "https://example.org/login")
    first.closed = True  # The user closes Chrome directly.
    state = manager.open_login("local", "https://example.org/login-again")

    assert first.quit_calls == 1
    assert replacement.current_url == "https://example.org/login-again"
    assert state["active"] is True
    assert manager.status("local")["active"] is True


def test_dynamic_page_readiness_rejects_loading_shell():
    assert AuthenticatedBrowserManager._page_snapshot_is_ready({
        "ready": "complete",
        "title": "Wird geladen ... - Research Databases",
        "body_text": "A temporary loading page with enough placeholder text to exceed the minimum.",
    }) is False
    assert AuthenticatedBrowserManager._page_snapshot_is_ready({
        "ready": "complete",
        "title": "Big Data - Fluch oder Segen?",
        "body_text": "Big Data - Fluch oder Segen? Ronald Bachmann Guido Kemper Thomas Gerzer 2014",
    }) is True


def test_fetch_snapshots_page_after_dynamic_wait(tmp_path, monkeypatch):
    class FakeDriver:
        current_url = "https://catalogue.example.org/record"
        page_source = "<html><title>Loading...</title></html>"

        def get(self, url):
            self.current_url = url

        def quit(self):
            pass

    driver = FakeDriver()
    manager = AuthenticatedBrowserManager(tmp_path)
    monkeypatch.setattr(manager, "_new_driver", lambda profile_key: driver)

    def finish_loading(active_driver):
        active_driver.page_source = "<html><h1>Authenticated record</h1></html>"

    monkeypatch.setattr(manager, "_wait_for_dynamic_content", finish_loading)

    page = manager.fetch("local", "https://catalogue.example.org/record")

    assert b"Authenticated record" in page.content


def test_shared_cli_webpage_path_preserves_authentication_action(monkeypatch):
    issue = {
        "warning_type": "authentication",
        "warning_details": "Authentication required: sign in first.",
        "requires_authentication": True,
        "authentication_domain": "example.org",
        "authentication_url": "https://example.org/record",
    }
    monkeypatch.setattr(
        WebPageChecker,
        "verify_reference",
        lambda self, reference: (None, [issue], reference["url"]),
    )
    checker = ArxivReferenceChecker.__new__(ArxivReferenceChecker)

    errors, url, data = checker.verify_webpage_reference({
        "title": "Protected record",
        "url": "https://example.org/record",
    })

    assert data is None
    assert url == "https://example.org/record"
    assert errors == [issue]


def test_webui_projection_preserves_authenticated_retry_metadata():
    issue = {
        "warning_type": "authentication",
        "warning_details": "Authentication required: sign in first.",
        "requires_authentication": True,
        "authentication_domain": "example.org",
        "authentication_url": "https://example.org/record",
    }

    status, sanitized = classify_verification_result(
        {"title": "Protected record", "url": issue["authentication_url"]},
        None,
        [issue],
        issue["authentication_url"],
    )
    errors, warnings = split_errors_and_warnings(sanitized)

    assert status == "warning"
    assert errors == []
    assert warnings[0]["requires_authentication"] is True
    assert warnings[0]["authentication_domain"] == "example.org"
    assert warnings[0]["authentication_url"] == issue["authentication_url"]

    projected = project_verification_result(
        {"title": "Protected record", "url": issue["authentication_url"]},
        None,
        [issue],
        issue["authentication_url"],
        enrich_enabled=False,
    )
    assert projected["warnings"][0]["requires_authentication"] is True
    assert projected["warnings"][0]["authentication_url"] == issue["authentication_url"]
