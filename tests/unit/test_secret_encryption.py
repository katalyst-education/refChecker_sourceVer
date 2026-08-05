import asyncio
import importlib.util
import sqlite3
from pathlib import Path

import pytest


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def database_module(tmp_path, monkeypatch):
    monkeypatch.setenv("REFCHECKER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REFCHECKER_SECRET_KEY", "test-secret-key")
    module_path = Path(__file__).resolve().parents[2] / "backend" / "database.py"
    spec = importlib.util.spec_from_file_location(f"test_backend_database_{id(tmp_path)}", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._fernet_instance = None
    return module


def test_llm_config_keys_are_encrypted_at_rest(database_module, tmp_path):
    db_path = tmp_path / "secrets.db"
    db = database_module.Database(str(db_path))
    _run(db.init_db())

    config_id = _run(db.create_llm_config(
        name="Local config",
        provider="anthropic",
        api_key="super-secret-key",
    ))

    with sqlite3.connect(db_path) as conn:
        stored_value = conn.execute(
            "SELECT api_key_encrypted FROM llm_configs WHERE id = ?",
            (config_id,),
        ).fetchone()[0]

    assert stored_value != "super-secret-key"
    assert stored_value.startswith(database_module.SECRET_VALUE_PREFIX)

    config = _run(db.get_llm_config_by_id(config_id))
    assert config["api_key"] == "super-secret-key"


def test_llm_config_persists_lmstudio_runtime_settings(database_module, tmp_path):
    db = database_module.Database(str(tmp_path / "reasoning.db"))
    _run(db.init_db())

    config_id = _run(db.create_llm_config(
        name="LM Studio",
        provider="lmstudio",
        model="qwen/test",
        endpoint="http://localhost:1234",
        reasoning_effort="none",
        max_tokens=4000,
        context_length=8192,
        timeout_seconds=300,
    ))

    saved = _run(db.get_llm_config_by_id(config_id))
    listed = _run(db.get_llm_configs())
    assert saved["reasoning_effort"] == "none"
    assert saved["max_tokens"] == 4000
    assert saved["context_length"] == 8192
    assert saved["timeout_seconds"] == 300
    assert listed[0]["reasoning_effort"] == "none"
    assert listed[0]["max_tokens"] == 4000
    assert listed[0]["context_length"] == 8192
    assert listed[0]["timeout_seconds"] == 300

    assert _run(db.update_llm_config(
        config_id,
        reasoning_effort="low",
        max_tokens=6000,
        context_length=16384,
        timeout_seconds=21600,
    ))
    updated = _run(db.get_llm_config_by_id(config_id))
    assert updated["reasoning_effort"] == "low"
    assert updated["max_tokens"] == 6000
    assert updated["context_length"] == 16384
    assert updated["timeout_seconds"] == 21600

    assert _run(db.update_llm_config(
        config_id,
        clear_context_length=True,
        clear_timeout_seconds=True,
    ))
    cleared = _run(db.get_llm_config_by_id(config_id))
    assert cleared["context_length"] is None
    assert cleared["timeout_seconds"] is None


def test_app_settings_are_encrypted_at_rest(database_module, tmp_path):
    db_path = tmp_path / "settings.db"
    db = database_module.Database(str(db_path))
    _run(db.init_db())

    _run(db.set_setting("service_token", "ss-secret"))

    with sqlite3.connect(db_path) as conn:
        stored_value = conn.execute(
            "SELECT value_encrypted FROM app_settings WHERE key = ?",
            ("service_token",),
        ).fetchone()[0]

    assert stored_value != "ss-secret"
    assert stored_value.startswith(database_module.SECRET_VALUE_PREFIX)
    assert _run(db.get_setting("service_token")) == "ss-secret"


def test_init_db_migrates_legacy_plaintext_secrets(database_module, tmp_path):
    db_path = tmp_path / "legacy.db"
    db = database_module.Database(str(db_path))
    _run(db.init_db())

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO llm_configs (name, provider, api_key_encrypted) VALUES (?, ?, ?)",
            ("Legacy config", "anthropic", "legacy-key"),
        )
        conn.execute(
            "INSERT INTO app_settings (key, value_encrypted) VALUES (?, ?)",
            ("service_token", "legacy-setting"),
        )
        conn.commit()

    _run(db.init_db())

    with sqlite3.connect(db_path) as conn:
        config_secret = conn.execute(
            "SELECT api_key_encrypted FROM llm_configs WHERE name = ?",
            ("Legacy config",),
        ).fetchone()[0]
        setting_secret = conn.execute(
            "SELECT value_encrypted FROM app_settings WHERE key = ?",
            ("service_token",),
        ).fetchone()[0]

    assert config_secret.startswith(database_module.SECRET_VALUE_PREFIX)
    assert setting_secret.startswith(database_module.SECRET_VALUE_PREFIX)

    legacy_config = _run(db.get_llm_config_by_id(1))
    assert legacy_config["api_key"] == "legacy-key"
    assert _run(db.get_setting("service_token")) == "legacy-setting"
