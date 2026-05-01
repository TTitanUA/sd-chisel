"""Raw CRUD over projects / sessions / messages / prompts / pinned loras.

Filesystem cleanup for `data/images/<session_id>/` stays in the API layer —
this module never touches disk. Callers in `app.api.sessions` are responsible
for invoking `app.storage.images.remove_session_images` around the relevant
DB operations.
"""
from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterable
from typing import Any

from app.utils.ids import new_id


def _now() -> int:
    return int(time.time())


def _row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(r) if r is not None else None


# --- projects ---------------------------------------------------------------


def _project_payload(conn: sqlite3.Connection, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    d = dict(row)
    d["session_count"] = conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE project_id = ?",
        (d["id"],),
    ).fetchone()[0]
    d["hidden"] = bool(d.get("hidden", 0))
    return d


def list_projects(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
    return [_project_payload(conn, r) for r in rows]


def get_project(conn: sqlite3.Connection, project_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return _project_payload(conn, row) if row else None


def create_project(conn: sqlite3.Connection, *, name: str) -> dict[str, Any]:
    now = _now()
    pid = new_id()
    conn.execute(
        "INSERT INTO projects(id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (pid, name, now, now),
    )
    return get_project(conn, pid)  # type: ignore[return-value]


def update_project(
    conn: sqlite3.Connection, project_id: str, *, name: str
) -> dict[str, Any] | None:
    now = _now()
    cur = conn.execute(
        "UPDATE projects SET name = ?, updated_at = ? WHERE id = ?",
        (name, now, project_id),
    )
    if cur.rowcount == 0:
        return None
    return get_project(conn, project_id)


def delete_project(conn: sqlite3.Connection, project_id: str) -> bool:
    cur = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    return cur.rowcount > 0


def set_project_hidden(
    conn: sqlite3.Connection, project_id: str, *, hidden: bool,
) -> dict[str, Any] | None:
    cur = conn.execute(
        "UPDATE projects SET hidden = ?, updated_at = ? WHERE id = ?",
        (1 if hidden else 0, _now(), project_id),
    )
    if cur.rowcount == 0:
        return None
    return get_project(conn, project_id)


def delete_project_and_collect_sessions(
    conn: sqlite3.Connection, project_id: str,
) -> list[str] | None:
    """Return list of session ids that belonged to the project (pre-cascade), or
    None if project did not exist. The session rows are removed by FK cascade."""
    if get_project(conn, project_id) is None:
        return None
    session_ids = [
        r[0]
        for r in conn.execute(
            "SELECT id FROM sessions WHERE project_id = ?",
            (project_id,),
        )
    ]
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    return session_ids


# --- sessions ---------------------------------------------------------------


def list_sessions(conn: sqlite3.Connection, project_id: str) -> list[dict[str, Any]]:
    return [
        _session_row_to_dict(r)
        for r in conn.execute(
            "SELECT * FROM sessions WHERE project_id = ? ORDER BY updated_at DESC",
            (project_id,),
        )
    ]


def _session_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["use_negative"] = bool(d["use_negative"])
    d["hidden"] = bool(d.get("hidden", 0))
    return d


def get_session(conn: sqlite3.Connection, session_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return _session_row_to_dict(row) if row else None


def create_session(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    session_type: str = "i2i",
    name: str | None = None,
    model_name: str | None = None,
    use_negative: bool = True,
) -> dict[str, Any]:
    now = _now()
    sid = new_id()
    conn.execute(
        "INSERT INTO sessions(id, project_id, name, session_type, model_name, "
        "use_negative, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            sid, project_id, name, session_type, model_name,
            1 if use_negative else 0, now, now,
        ),
    )
    conn.execute(
        "UPDATE projects SET updated_at = ? WHERE id = ?",
        (now, project_id),
    )
    return get_session(conn, sid)  # type: ignore[return-value]


def update_session(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    name: str | None,
    model_name: str | None,
    use_negative: bool,
    vl_model_name: str | None = None,
    prompt_model_name: str | None = None,
) -> dict[str, Any] | None:
    now = _now()
    cur = conn.execute(
        "UPDATE sessions SET name = ?, model_name = ?, use_negative = ?, "
        "vl_model_name = ?, prompt_model_name = ?, updated_at = ? "
        "WHERE id = ?",
        (
            name, model_name, 1 if use_negative else 0,
            vl_model_name, prompt_model_name, now, session_id,
        ),
    )
    if cur.rowcount == 0:
        return None
    row = get_session(conn, session_id)
    if row:
        conn.execute(
            "UPDATE projects SET updated_at = ? WHERE id = ?",
            (now, row["project_id"]),
        )
    return row


def delete_session(conn: sqlite3.Connection, session_id: str) -> bool:
    cur = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    return cur.rowcount > 0


def set_session_hidden(
    conn: sqlite3.Connection, session_id: str, *, hidden: bool,
) -> dict[str, Any] | None:
    now = _now()
    cur = conn.execute(
        "UPDATE sessions SET hidden = ?, updated_at = ? WHERE id = ?",
        (1 if hidden else 0, now, session_id),
    )
    if cur.rowcount == 0:
        return None
    return get_session(conn, session_id)


def set_vl_summary(conn: sqlite3.Connection, session_id: str, summary: str) -> None:
    conn.execute(
        "UPDATE sessions SET vl_summary = ?, updated_at = ? WHERE id = ?",
        (summary, _now(), session_id),
    )


# --- pinned loras -----------------------------------------------------------


def list_pinned_loras(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT lora_name, weight_override FROM session_pinned_loras "
            "WHERE session_id = ? ORDER BY lora_name",
            (session_id,),
        )
    ]


def set_pinned_loras(
    conn: sqlite3.Connection,
    session_id: str,
    pinned: Iterable[dict[str, Any]],
) -> None:
    try:
        conn.execute("BEGIN")
        conn.execute(
            "DELETE FROM session_pinned_loras WHERE session_id = ?",
            (session_id,),
        )
        for p in pinned:
            conn.execute(
                "INSERT INTO session_pinned_loras(session_id, lora_name, weight_override) "
                "VALUES (?, ?, ?)",
                (session_id, p["lora_name"], p.get("weight_override")),
            )
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise


# --- source image path -----------------------------------------------------


def set_source_image(
    conn: sqlite3.Connection, session_id: str, rel_path: str,
) -> None:
    conn.execute(
        "UPDATE sessions SET source_image_path = ?, updated_at = ? WHERE id = ?",
        (rel_path, _now(), session_id),
    )


def clear_source_image(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute(
        "UPDATE sessions SET source_image_path = NULL, updated_at = ? WHERE id = ?",
        (_now(), session_id),
    )


# --- full hydrated session -------------------------------------------------


def get_session_with_pinned(
    conn: sqlite3.Connection, session_id: str,
) -> dict[str, Any] | None:
    row = get_session(conn, session_id)
    if row is None:
        return None
    row["pinned_loras"] = list_pinned_loras(conn, session_id)
    return row


# --- messages (kept from foundation; unchanged behaviour) ------------------


def append_message(
    conn: sqlite3.Connection, *, session_id: str, role: str, content: str,
) -> dict[str, Any]:
    now = _now()
    cur = conn.execute(
        "INSERT INTO messages(session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (session_id, role, content, now),
    )
    return _row(conn.execute(
        "SELECT * FROM messages WHERE id = ?", (cur.lastrowid,),
    ).fetchone())  # type: ignore[return-value]


def list_messages(conn: sqlite3.Connection, *, session_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at, id",
        (session_id,),
    )]


# --- prompts (append-only history) -----------------------------------------


def append_prompt(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    positive: str,
    negative: str | None,
    loras: list[dict[str, Any]],
    intents: list[dict[str, Any]] | None,
    retrieved: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    now = _now()
    cur = conn.execute(
        "INSERT INTO prompts(session_id, positive, negative, loras_json, "
        "intents_json, retrieved_loras_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            session_id,
            positive,
            negative,
            json.dumps(loras, ensure_ascii=False),
            json.dumps(intents, ensure_ascii=False) if intents is not None else None,
            json.dumps(retrieved, ensure_ascii=False) if retrieved is not None else None,
            now,
        ),
    )
    return _row(conn.execute(
        "SELECT * FROM prompts WHERE id = ?", (cur.lastrowid,),
    ).fetchone())  # type: ignore[return-value]


def list_prompts(
    conn: sqlite3.Connection, *, session_id: str,
) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM prompts WHERE session_id = ? "
            "ORDER BY created_at DESC, id DESC",
            (session_id,),
        )
    ]
