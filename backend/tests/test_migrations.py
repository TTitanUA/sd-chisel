from pathlib import Path

import pytest

from app.storage import db as db_mod
from app.storage.migrations import apply_pending, applied_versions



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
        "families", "models", "loras", "lora_family_compat",
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
    assert applied_versions(fresh_conn) == list(range(1, first + 1))


def test_foreign_keys_enforced(fresh_conn, tmp_path):
    migrations_dir = Path(__file__).parent.parent / "migrations"
    apply_pending(fresh_conn, migrations_dir)

    # Inserting a model with a non-existent family must fail.
    with pytest.raises(Exception):
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

    with pytest.raises(Exception):
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
