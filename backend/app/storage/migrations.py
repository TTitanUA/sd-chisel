from __future__ import annotations

import re
import sqlite3
from pathlib import Path

_VERSION_RE = re.compile(r"^(\d{3,})_.+\.sql$")


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "  version INTEGER PRIMARY KEY,"
        "  applied_at INTEGER NOT NULL"
        ")"
    )


def applied_versions(conn: sqlite3.Connection) -> list[int]:
    _ensure_table(conn)
    return [r[0] for r in conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    )]


def _discover(migrations_dir: Path) -> list[tuple[int, Path]]:
    out: list[tuple[int, Path]] = []
    for f in sorted(migrations_dir.iterdir()):
        m = _VERSION_RE.match(f.name)
        if m:
            out.append((int(m.group(1)), f))
    return out


def apply_pending(conn: sqlite3.Connection, migrations_dir: Path) -> int:
    """Apply all migration files not yet in schema_migrations.

    Each file runs in its own transaction. sqlite3.Connection.executescript()
    always issues an implicit COMMIT before running, so we cannot wrap it in a
    manual BEGIN/COMMIT. Instead we let executescript handle its own
    transaction for the SQL file, then record the version in a separate
    transaction using the connection as a context manager.
    Returns the count of newly applied migrations.
    """
    import time

    _ensure_table(conn)
    already = set(applied_versions(conn))
    applied = 0
    for version, path in _discover(migrations_dir):
        if version in already:
            continue
        sql = path.read_text(encoding="utf-8")
        # executescript issues an implicit COMMIT first, then wraps the
        # statements in its own BEGIN/COMMIT, so we must NOT open a
        # transaction before calling it.
        conn.executescript(sql)
        with conn:
            conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (version, int(time.time())),
            )
        applied += 1
    return applied
