"""CRUD for `session_source_images` rows.

Filesystem cleanup for the underlying image files lives in the API layer —
this module never touches disk. Callers in `app.api.sessions` are responsible
for writing the file on insert and unlinking it on delete.
"""
from __future__ import annotations

import sqlite3
import time
from typing import Any

from app.utils.ids import new_id


def _now() -> int:
    return int(time.time())


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["is_main"] = bool(d["is_main"])
    return d


def list_for_session(
    conn: sqlite3.Connection, session_id: str,
) -> list[dict[str, Any]]:
    """Main image first, then references in upload order. ROWID is used as a
    sub-second tiebreaker so the order is stable when multiple rows are
    inserted within the same epoch second."""
    return [
        _row_to_dict(r)
        for r in conn.execute(
            "SELECT * FROM session_source_images WHERE session_id = ? "
            "ORDER BY is_main DESC, created_at ASC, rowid ASC",
            (session_id,),
        )
    ]


def get(conn: sqlite3.Connection, image_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM session_source_images WHERE id = ?", (image_id,),
    ).fetchone()
    return _row_to_dict(row) if row else None


def count_for_session(conn: sqlite3.Connection, session_id: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM session_source_images WHERE session_id = ?",
        (session_id,),
    ).fetchone()[0]


def insert(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    image_id: str | None = None,
    path: str,
    original_filename: str,
    is_main: bool,
) -> dict[str, Any]:
    """Insert a row. Caller supplies `image_id` if the path needs to embed it
    (the standard pattern), otherwise one is generated."""
    now = _now()
    iid = image_id or new_id()
    conn.execute(
        "INSERT INTO session_source_images("
        "id, session_id, path, original_filename, is_main, "
        "analysis, analysis_prompt, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?)",
        (iid, session_id, path, original_filename, 1 if is_main else 0, now, now),
    )
    conn.execute(
        "UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id),
    )
    return get(conn, iid)  # type: ignore[return-value]


def delete(
    conn: sqlite3.Connection, image_id: str,
) -> dict[str, Any] | None:
    """Delete the row, return its previous contents (for caller-side file cleanup)."""
    existing = get(conn, image_id)
    if existing is None:
        return None
    conn.execute("DELETE FROM session_source_images WHERE id = ?", (image_id,))
    conn.execute(
        "UPDATE sessions SET updated_at = ? WHERE id = ?",
        (_now(), existing["session_id"]),
    )
    return existing


def set_main(
    conn: sqlite3.Connection, *, session_id: str, image_id: str,
) -> dict[str, Any] | None:
    """Make `image_id` the only main image for `session_id`. Returns updated row."""
    existing = get(conn, image_id)
    if existing is None or existing["session_id"] != session_id:
        return None
    now = _now()
    try:
        conn.execute("BEGIN")
        # Clear current main(s) first to avoid the unique-index conflict.
        conn.execute(
            "UPDATE session_source_images SET is_main = 0, updated_at = ? "
            "WHERE session_id = ? AND is_main = 1",
            (now, session_id),
        )
        conn.execute(
            "UPDATE session_source_images SET is_main = 1, updated_at = ? "
            "WHERE id = ?",
            (now, image_id),
        )
        conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id),
        )
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    return get(conn, image_id)


def promote_first_remaining(
    conn: sqlite3.Connection, session_id: str,
) -> dict[str, Any] | None:
    """If no row is currently main, promote the oldest. Returns the new main, or
    None when the session has no source images."""
    has_main = conn.execute(
        "SELECT 1 FROM session_source_images WHERE session_id = ? AND is_main = 1 LIMIT 1",
        (session_id,),
    ).fetchone()
    if has_main is not None:
        return None
    candidate = conn.execute(
        "SELECT id FROM session_source_images WHERE session_id = ? "
        "ORDER BY created_at ASC, rowid ASC LIMIT 1",
        (session_id,),
    ).fetchone()
    if candidate is None:
        return None
    return set_main(conn, session_id=session_id, image_id=candidate[0])


def set_analysis(
    conn: sqlite3.Connection,
    image_id: str,
    *,
    analysis: str,
    refining_prompt: str | None,
) -> dict[str, Any] | None:
    now = _now()
    cur = conn.execute(
        "UPDATE session_source_images SET analysis = ?, analysis_prompt = ?, "
        "updated_at = ? WHERE id = ?",
        (analysis, refining_prompt, now, image_id),
    )
    if cur.rowcount == 0:
        return None
    row = get(conn, image_id)
    if row is not None:
        conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (now, row["session_id"]),
        )
    return row
