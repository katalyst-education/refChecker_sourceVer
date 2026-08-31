import asyncio
import threading

from backend import main as backend_main
from refchecker.checkers import enhanced_hybrid_checker


def test_search_all_checker_receives_configured_local_databases_and_cache(monkeypatch):
    """Search-all must not silently downgrade to remote-only verification."""
    configured_paths = {
        "s2": "C:/reference-data/semantic-scholar.db",
        "openalex": "C:/reference-data/openalex.db",
        "crossref": "C:/reference-data/crossref.db",
    }
    captured = {}

    class FakeChecker:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    async def fake_database_paths():
        return configured_paths

    async def fake_cache_dir():
        return "C:/reference-cache"

    monkeypatch.setattr(backend_main, "_get_configured_database_paths", fake_database_paths)
    monkeypatch.setattr(backend_main, "_get_configured_cache_dir", fake_cache_dir)
    monkeypatch.setattr(enhanced_hybrid_checker, "EnhancedHybridReferenceChecker", FakeChecker)

    callback = lambda _event: None
    cancel_event = threading.Event()
    checker = asyncio.run(backend_main._create_reference_search_checker(
        semantic_scholar_api_key="s2-key",
        google_books_api_key="books-key",
        paperclip_api_key="paperclip-key",
        progress_callback=callback,
        cancel_event=cancel_event,
    ))

    assert isinstance(checker, FakeChecker)
    assert captured["db_path"] == configured_paths["s2"]
    assert captured["db_paths"] == configured_paths
    assert captured["cache_dir"] == "C:/reference-cache"
    assert captured["progress_callback"] is callback
    assert captured["cancel_event"] is cancel_event
