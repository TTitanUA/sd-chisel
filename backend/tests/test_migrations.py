import sqlite3
from pathlib import Path

import pytest

from app.storage import db as db_mod
from app.storage.migrations import applied_versions, apply_pending


@pytest.fixture
def fresh_conn(tmp_path):
    conn = db_mod.connect(tmp_path / "test.db")
    yield conn
    conn.close()


def test_apply_pending_creates_schema_migrations_and_runs_all(fresh_conn, tmp_path):
    # Use the repo's real migrations directory — we test they apply cleanly.
    migrations_dir = Path(__file__).parent.parent / "migrations"
    applied = apply_pending(fresh_conn, migrations_dir)
    assert applied >= 1

    # schema_migrations table exists and has at least one row
    rows = list(fresh_conn.execute("SELECT version FROM schema_migrations ORDER BY version"))
    assert len(rows) == applied

    # All required tables exist
    tables = {r[0] for r in fresh_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    expected = {
        "schema_migrations",
        "families", "models", "loras",
        "lora_vec_map",
        "projects", "sessions", "session_pinned_loras",
        "messages", "prompts",
    }
    assert expected.issubset(tables)

    # vec_loras virtual table exists
    vtables = {r[0] for r in fresh_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='vec_loras'"
    )}
    assert "vec_loras" in vtables


def test_apply_pending_is_idempotent(fresh_conn, tmp_path):
    migrations_dir = Path(__file__).parent.parent / "migrations"
    first = apply_pending(fresh_conn, migrations_dir)
    second = apply_pending(fresh_conn, migrations_dir)
    assert second == 0
    versions = applied_versions(fresh_conn)
    assert len(versions) == first
    assert versions == sorted(versions)


def test_foreign_keys_enforced(fresh_conn, tmp_path):
    migrations_dir = Path(__file__).parent.parent / "migrations"
    apply_pending(fresh_conn, migrations_dir)

    # Inserting a model with a non-existent family must fail.
    with pytest.raises(sqlite3.IntegrityError):
        fresh_conn.execute(
            "INSERT INTO models(name, display_name, family_id, created_at, updated_at) "
            "VALUES (?, ?, ?, 0, 0)",
            ("m1", "M1", "does-not-exist"),
        )


def test_apply_pending_rolls_back_on_partial_failure(fresh_conn, tmp_path):
    # Craft a migration whose second statement fails.
    bad_dir = tmp_path / "bad_migrations"
    bad_dir.mkdir()
    (bad_dir / "001_bad.sql").write_text(
        "CREATE TABLE ok (id INTEGER);\n"
        "CREATE TABLE bad (id INTEGER REFERENCES missing(id));\n"
        "INSERT INTO SYNTAX ERROR;\n",
        encoding="utf-8",
    )

    with pytest.raises(sqlite3.OperationalError):
        apply_pending(fresh_conn, bad_dir)

    # Neither `ok` nor `bad` should exist; schema_migrations should be empty.
    tables = {
        r[0] for r in fresh_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert "ok" not in tables
    assert "bad" not in tables
    assert applied_versions(fresh_conn) == []


def test_split_statements_preserves_semicolons_in_string_literals(tmp_path, fresh_conn):
    # A migration whose INSERT has `;` and escaped `''` inside its string values.
    from app.storage.migrations import _split_statements

    sql = (
        "CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT);\n"
        "INSERT INTO t(id, v) VALUES (1, 'a;b');\n"
        "INSERT INTO t(id, v) VALUES (2, 'it''s;fine');\n"
    )
    stmts = _split_statements(sql)
    assert len(stmts) == 3
    assert stmts[1] == "INSERT INTO t(id, v) VALUES (1, 'a;b')"
    assert stmts[2] == "INSERT INTO t(id, v) VALUES (2, 'it''s;fine')"


def test_settings_schema_present_with_correct_session_columns(tmp_path):
    import sqlite3
    from pathlib import Path

    from app.storage import db as db_mod
    from app.storage.migrations import apply_pending

    conn = db_mod.connect(tmp_path / "m.db")
    apply_pending(conn, Path(__file__).parent.parent / "migrations")

    cols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)")}
    assert "vl_endpoint" not in cols
    assert "prompt_endpoint" not in cols
    assert "vl_model_name" in cols
    assert "prompt_model_name" in cols

    # singleton row exists
    settings = list(conn.execute("SELECT id FROM app_settings"))
    assert len(settings) == 1 and settings[0]["id"] == 1

    # lm_models exists with capability columns
    lm_cols = {r[1] for r in conn.execute("PRAGMA table_info(lm_models)")}
    assert "vision" in lm_cols
    assert "tool_use" in lm_cols
    assert "reasoning" in lm_cols
    assert "role" not in lm_cols
    conn.execute(
        "INSERT INTO lm_models(name, enabled, last_seen, vision, tool_use, reasoning) "
        "VALUES (?, 1, 0, 0, 0, 0)",
        ("ok",),
    )


def test_default_migrations_dir_points_at_bundled_files():
    """``DEFAULT_MIGRATIONS_DIR`` must resolve to ``backend/migrations``
    so the FastAPI startup hook and the ``db-init`` CLI agree on
    where to look. Regression guard against future refactors that
    move the storage package."""
    from app.storage.migrations import DEFAULT_MIGRATIONS_DIR

    assert DEFAULT_MIGRATIONS_DIR.name == "migrations"
    # Bundled migrations must be discoverable through the constant.
    sql_files = sorted(p.name for p in DEFAULT_MIGRATIONS_DIR.glob("*.sql"))
    assert "001_init.sql" in sql_files
    assert any(name.startswith("018_") for name in sql_files)


def test_app_lifespan_applies_migrations_to_fresh_db(tmp_path, monkeypatch):
    """Lifespan must bring an empty ``data/app.db`` up to head before
    serving any request. Use ``TestClient`` as a context manager so
    FastAPI actually triggers ``lifespan``."""
    from fastapi.testclient import TestClient

    from app import config as app_config
    from app.storage import db as db_mod

    # Redirect both `data/` and the DB target to a tmp location so the
    # test never touches the real repo. ``db_mod`` does
    # ``from app.config import resolve_data_root`` at import time, so we
    # patch the binding on ``db_mod`` directly (and on ``app_config``
    # too for any other consumer that re-imports it).
    data_root = tmp_path / "data"
    monkeypatch.setattr(app_config, "resolve_data_root", lambda: data_root)
    monkeypatch.setattr(db_mod, "resolve_data_root", lambda: data_root)
    # The TaskRegistry / lora_reindex hooks need a fully-migrated DB.
    # By the time they run, our migrations call must have already
    # populated it — that's exactly what we're verifying here.
    from app import main as app_main

    with TestClient(app_main.app):
        # Inside the `with` block the lifespan startup has finished.
        conn = db_mod.connect(data_root / "app.db")
        try:
            tables = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'",
                )
            }
            assert "schema_migrations" in tables
            assert "sessions" in tables
            # Migration 018 lands the comfy_input_cleanup column;
            # migration 021 lands the comfy_restart_after_run column.
            session_cols = {
                r[1] for r in conn.execute("PRAGMA table_info(sessions)")
            }
            assert "comfy_input_cleanup" in session_cols
            assert "comfy_restart_after_run" in session_cols
        finally:
            conn.close()
