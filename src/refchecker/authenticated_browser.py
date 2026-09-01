"""Local, user-controlled browser sessions for authenticated source checks.

Credentials are entered directly into a visible browser window.  RefChecker
never receives passwords or MFA values; Selenium only exposes the rendered
page after the user has completed the site's normal login flow.  Browser
cookies remain in Chrome's dedicated on-disk profile and are never copied into
verification results, caches, logs, or LLM prompts.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import logging
import os
from pathlib import Path
import re
import sys
import threading
from typing import Dict, Iterator, Mapping, Optional


logger = logging.getLogger(__name__)

_LOADING_TITLE_PATTERN = re.compile(
    r"\b(?:loading|wird\s+geladen|chargement|cargando|caricamento|laden)\b",
    re.IGNORECASE,
)


_profile_context: ContextVar[Optional[str]] = ContextVar(
    "refchecker_authenticated_browser_profile", default=None
)


def _default_profile_root() -> Path:
    configured = os.environ.get("REFCHECKER_AUTH_BROWSER_DIR")
    if configured:
        return Path(configured).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "refchecker" / "authenticated-browser"


@dataclass(frozen=True)
class BrowserPageResponse:
    """Small ``requests.Response``-compatible page snapshot."""

    url: str
    content: bytes
    status_code: int = 200
    headers: Mapping[str, str] = None

    def __post_init__(self) -> None:
        if self.headers is None:
            object.__setattr__(self, "headers", {"content-type": "text/html; charset=utf-8"})


@dataclass
class _BrowserSession:
    driver: object
    requested_url: str
    lock: threading.RLock


class AuthenticatedBrowserUnavailable(RuntimeError):
    """Raised when the optional local browser runtime cannot be started."""


class AuthenticatedBrowserManager:
    """Own visible, persistent Chrome sessions keyed by local app profile."""

    def __init__(self, profile_root: Optional[Path] = None):
        self.profile_root = Path(profile_root or _default_profile_root())
        self._sessions: Dict[str, _BrowserSession] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _safe_key(profile_key: str) -> str:
        value = str(profile_key or "local")
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]

    def _profile_dir(self, profile_key: str) -> Path:
        path = self.profile_root / self._safe_key(profile_key)
        path.mkdir(parents=True, exist_ok=True)
        return path.resolve()

    def _new_driver(self, profile_key: str):
        try:
            from selenium import webdriver
        except ImportError as exc:
            raise AuthenticatedBrowserUnavailable(
                "Authenticated browser support is not installed. Install the WebUI extras again."
            ) from exc

        options = webdriver.ChromeOptions()
        options.add_argument(f"--user-data-dir={self._profile_dir(profile_key)}")
        options.add_argument("--profile-directory=Default")
        options.add_argument("--start-maximized")
        options.add_argument("--disable-background-networking")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        try:
            driver = webdriver.Chrome(options=options)
            driver.set_page_load_timeout(45)
            return driver
        except Exception as exc:
            raise AuthenticatedBrowserUnavailable(
                "Could not start Chrome for authenticated browsing. Ensure Chrome is installed and try again."
            ) from exc

    @staticmethod
    def _page_snapshot_is_ready(snapshot: object) -> bool:
        if not isinstance(snapshot, dict):
            return False
        if str(snapshot.get("ready") or "").casefold() != "complete":
            return False
        title = str(snapshot.get("title") or "").strip()
        body_text = str(snapshot.get("body_text") or "").strip()
        if not body_text or len(body_text) < 50:
            return False
        return _LOADING_TITLE_PATTERN.search(title) is None

    def _wait_for_dynamic_content(self, driver: object) -> None:
        """Wait for a navigated JavaScript page to replace its loading shell."""
        try:
            from selenium.common.exceptions import TimeoutException
            from selenium.webdriver.support.ui import WebDriverWait
        except ImportError:
            return

        try:
            def page_ready(active_driver):
                snapshot = active_driver.execute_script("""
                    return {
                        ready: document.readyState,
                        title: document.title || '',
                        body_text: document.body ? document.body.innerText : ''
                    };
                """)
                return self._page_snapshot_is_ready(snapshot)

            WebDriverWait(driver, 30, poll_frequency=0.25).until(page_ready)
        except TimeoutException:
            # Preserve the best available snapshot. The verifier can still
            # classify a genuine login/error page after a slow site times out.
            logger.debug("Authenticated page did not finish dynamic loading within 30 seconds")
        except Exception as exc:
            # Driver implementations without script execution should not make
            # an otherwise usable page unreadable.
            logger.debug("Could not wait for dynamic page content: %s", exc)

    def _get_or_create_session(self, key: str, url: str) -> _BrowserSession:
        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                driver = self._new_driver(key)
                if driver is None:
                    raise AuthenticatedBrowserUnavailable(
                        "Chrome did not create a session. Restart the backend and try again."
                    )
                session = _BrowserSession(
                    driver=driver,
                    requested_url=url,
                    lock=threading.RLock(),
                )
                self._sessions[key] = session
            return session

    def _discard_session(self, key: str, session: _BrowserSession) -> None:
        """Forget a dead driver without removing a newer replacement."""
        with self._lock:
            if self._sessions.get(key) is session:
                self._sessions.pop(key, None)
        try:
            with session.lock:
                session.driver.quit()
        except Exception:
            pass

    @staticmethod
    def _is_closed_session_error(exc: Exception) -> bool:
        """Recognize Selenium errors caused by a user closing the window."""
        closed_exception_names = {
            "InvalidSessionIdException",
            "NoSuchWindowException",
        }
        current: Optional[BaseException] = exc
        while current is not None:
            if type(current).__name__ in closed_exception_names:
                return True
            message = str(current).casefold()
            if any(marker in message for marker in (
                "invalid session id",
                "no such window",
                "target window already closed",
                "disconnected: not connected to devtools",
            )):
                return True
            current = current.__cause__ or current.__context__
        return False

    def open_login(self, profile_key: str, url: str) -> Dict[str, object]:
        """Open *url* in a visible browser and leave it open for manual login."""
        key = str(profile_key or "local")
        for attempt in range(2):
            session = self._get_or_create_session(key, url)
            try:
                with session.lock:
                    session.requested_url = url
                    session.driver.get(url)
                    return {
                        "active": True,
                        "requested_url": url,
                        "current_url": str(session.driver.current_url or url),
                    }
            except Exception as exc:
                if attempt == 0 and self._is_closed_session_error(exc):
                    self._discard_session(key, session)
                    continue
                raise
        raise AuthenticatedBrowserUnavailable("Could not reopen the authenticated browser session.")

    def fetch(self, profile_key: str, url: str) -> BrowserPageResponse:
        """Navigate the active authenticated browser and snapshot its HTML."""
        key = str(profile_key or "local")
        for attempt in range(2):
            # CLI/bulk runs can reuse a profile established previously in the
            # WebUI. The window remains visible so any expired SSO/MFA state is
            # obvious and can be renewed by the user.
            session = self._get_or_create_session(key, url)
            try:
                with session.lock:
                    session.requested_url = url
                    session.driver.get(url)
                    self._wait_for_dynamic_content(session.driver)
                    html = session.driver.page_source or ""
                    current_url = str(session.driver.current_url or url)
                return BrowserPageResponse(url=current_url, content=html.encode("utf-8"))
            except Exception as exc:
                if attempt == 0 and self._is_closed_session_error(exc):
                    self._discard_session(key, session)
                    continue
                raise
        raise AuthenticatedBrowserUnavailable("Could not reopen the authenticated browser session.")

    def status(self, profile_key: str) -> Dict[str, object]:
        key = str(profile_key or "local")
        with self._lock:
            session = self._sessions.get(key)
        if session is None:
            return {"active": False}
        try:
            with session.lock:
                return {
                    "active": True,
                    "requested_url": session.requested_url,
                    "current_url": str(session.driver.current_url or ""),
                }
        except Exception:
            self.close(key)
            return {"active": False}

    def requested_url(self, profile_key: str) -> Optional[str]:
        key = str(profile_key or "local")
        with self._lock:
            session = self._sessions.get(key)
            return session.requested_url if session else None

    def close(self, profile_key: str) -> bool:
        key = str(profile_key or "local")
        with self._lock:
            session = self._sessions.pop(key, None)
        if session is None:
            return False
        try:
            with session.lock:
                session.driver.quit()
        except Exception:
            pass
        return True

    def close_all(self) -> None:
        with self._lock:
            keys = list(self._sessions)
        for key in keys:
            self.close(key)


_manager = AuthenticatedBrowserManager()


def get_authenticated_browser_manager() -> AuthenticatedBrowserManager:
    return _manager


def configure_authenticated_browser_dir(path: Path) -> None:
    """Configure storage before any browser session is created."""
    global _manager
    with _manager._lock:
        if _manager._sessions:
            return
        _manager = AuthenticatedBrowserManager(Path(path))


def current_authenticated_browser_profile() -> Optional[str]:
    return _profile_context.get() or os.environ.get("REFCHECKER_AUTH_BROWSER_PROFILE")


@contextmanager
def authenticated_browser_profile(profile_key: Optional[str]) -> Iterator[None]:
    token = _profile_context.set(str(profile_key) if profile_key else None)
    try:
        yield
    finally:
        _profile_context.reset(token)
