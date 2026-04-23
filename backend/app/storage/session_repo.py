"""Raw CRUD over projects / sessions / messages / prompts / pinned loras.

Note: filesystem cleanup for `data/images/<session_id>/` is NOT handled here —
callers (API layer) must invoke `app.storage.images.remove_session_images`
before or after `delete_session`. Foundation plan keeps this split explicit;
Slice 2 adds a transactional wrapper in the API.
"""
from __future__ import annotations

import sqlite3
import time
from typing import Any


def _now() -> int:
    return int(time.time())


def _row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(r) if r is not None else None


# --- projects ---------------------------------------------------------------


def list_projects(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM projects ORDER BY updated_at DESC"
    )]


def get_project(conn: sqlite3.Connection, project_id: str) -> dict[str, Any] | None:
    return _row(conn.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone())


def create_project(conn: sqlite3.Connection, *, id: str, name: str) -> dict[str, Any]:
    now = _now()
    conn.execute(
        "INSERT INTO projects(id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (id, name, now, now),
    )
    return get_project(conn, id)  # type: ignore[return-value]


# --- sessions ---------------------------------------------------------------


def get_session(conn: sqlite3.Connection, session_id: str) -> dict[str, Any] | None:
    return _row(conn.execute(
        "SELECT * FROM sessions WHERE id = ?", (session_id,)
    ).fetchone())


def list_sessions(conn: sqlite3.Connection, project_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM sessions WHERE project_id = ? ORDER BY updated_at DESC",
        (project_id,),
    )]


def create_session(
    conn: sqlite3.Connection,
    *,
    id: str,
    project_id: str,
    name: str | None = None,
    model_name: str | None = None,
    use_negative: bool = True,
) -> dict[str, Any]:
    now = _now()
    conn.execute(
        "INSERT INTO sessions(id, project_id, name, model_name, use_negative, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (id, project_id, name, model_name, 1 if use_negative else 0, now, now),
    )
    return get_session(conn, id)  # type: ignore[return-value]


def delete_session(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


# --- messages ---------------------------------------------------------------


def append_message(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    role: str,
    content: str,
) -> dict[str, Any]:
    now = _now()
    cur = conn.execute(
        "INSERT INTO messages(session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (session_id, role, content, now),
    )
    return _row(conn.execute(
        "SELECT * FROM messages WHERE id = ?", (cur.lastrowid,)
    ).fetchone())  # type: ignore[return-value]


def list_messages(conn: sqlite3.Connection, *, session_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at, id",
        (session_id,),
    )]
