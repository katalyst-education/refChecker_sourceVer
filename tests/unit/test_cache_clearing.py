import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import backend.main as api_main
from backend.database import Database
from backend.main import _clear_cache_directory


def test_clear_cache_directory_removes_cached_files_but_preserves_protected_database(tmp_path):
    cache_dir = tmp_path / "cache"
    ai_cache = cache_dir / "llm_responses" / "response.json"
    reference_cache = cache_dir / "arxiv_1234.5678" / "bibliography.json"
    database_file = cache_dir / "nested" / "refchecker.db"

    for path in (ai_cache, reference_cache, database_file):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("cached", encoding="utf-8")

    removed = _clear_cache_directory(cache_dir, [database_file])

    assert removed == 2
    assert not ai_cache.exists()
    assert not reference_cache.exists()
    assert database_file.read_text(encoding="utf-8") == "cached"


def test_clear_cached_files_keeps_api_keys_and_check_history(tmp_path, monkeypatch):
    database = Database(str(tmp_path / "refchecker.db"))
    asyncio.run(database.init_db())
    asyncio.run(database.set_setting("semantic_scholar_api_key", "secret-key"))
    check_id = asyncio.run(
        database.create_pending_check("Paper", "paper.pdf", "file")
    )

    cache_dir = tmp_path / "cache"
    cached_response = cache_dir / "llm_responses" / "response.json"
    cached_response.parent.mkdir(parents=True)
    cached_response.write_text("cached", encoding="utf-8")

    async def configured_cache_dir():
        return str(cache_dir)

    monkeypatch.setattr(api_main, "db", database)
    monkeypatch.setattr(api_main, "_get_configured_cache_dir", configured_cache_dir)

    result = asyncio.run(api_main.clear_cached_files(SimpleNamespace(is_admin=True)))

    assert result["disk_count"] == 1
    assert not cached_response.exists()
    assert asyncio.run(database.get_setting("semantic_scholar_api_key")) == "secret-key"
    with sqlite3.connect(database.db_path) as connection:
        assert connection.execute(
            "SELECT id FROM check_history WHERE id = ?", (check_id,)
        ).fetchone() == (check_id,)
