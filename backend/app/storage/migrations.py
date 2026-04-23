from __future__ import annotations

import re
import sqlite3
import time
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


def _split_statements(sql: str) -> list[str]:
    """Split a SQL script into individual statements.

    Strips line comments (`-- ...`) and splits on `;`. Migration scripts must
    not contain `;` inside string literals or identifiers.
    """
    stripped = "\n".join(
        line for line in sql.splitlines()
        if not line.lstrip().startswith("--")
    )
    return [s.strip() for s in stripped.split(";") if s.strip()]


def apply_pending(conn: sqlite3.Connection, migrations_dir: Path) -> int:
    """Apply all migration files not yet in schema_migrations.

    Each file's DDL and the corresponding schema_migrations INSERT run inside
    a single manual BEGIN/COMMIT so a partial failure rolls back cleanly.
    Returns the count of newly applied migrations.
    """
    _ensure_table(conn)
    already = set(applied_versions(conn))
    applied = 0
    for version, path in _discover(migrations_dir):
        if version in already:
            continue
        statements = _split_statements(path.read_text(encoding="utf-8"))
        try:
            conn.execute("BEGIN")
            for stmt in statements:
                conn.execute(stmt)
            conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (version, int(time.time())),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        applied += 1
    return applied
