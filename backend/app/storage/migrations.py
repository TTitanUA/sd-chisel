from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path

_VERSION_RE = re.compile(r"^(\d{3,})_.+\.sql$")


# Resolved path of the bundled migrations dir (``backend/migrations/``).
# Both the ``db-init`` CLI and the FastAPI startup hook read from this
# constant so the two code paths can never drift to different
# directories. ``Path(__file__)`` walks: storage → app → backend →
# migrations.
DEFAULT_MIGRATIONS_DIR: Path = (
    Path(__file__).resolve().parent.parent.parent / "migrations"
)


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

    Strips `--` line comments and splits on `;` only when the `;` is outside
    a single-quoted string literal. Inside a literal, `''` is SQL's escape
    for a single quote — we stay inside the literal when we see it.
    """
    no_comments = "\n".join(
        line for line in sql.splitlines()
        if not line.lstrip().startswith("--")
    )
    statements: list[str] = []
    buf: list[str] = []
    in_str = False
    i = 0
    n = len(no_comments)
    while i < n:
        ch = no_comments[i]
        if in_str:
            buf.append(ch)
            if ch == "'":
                # Escaped quote inside a literal: '' means one literal quote.
                if i + 1 < n and no_comments[i + 1] == "'":
                    buf.append(no_comments[i + 1])
                    i += 2
                    continue
                in_str = False
            i += 1
            continue
        if ch == "'":
            in_str = True
            buf.append(ch)
            i += 1
            continue
        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf.clear()
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


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
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        applied += 1
    return applied
