"""CRUD for ``comfy_session_agents`` — per-session, user-programmable
LLM agents that replace the single implicit composer call.

Validation (kind allow-list, single-bind across siblings, workflow-side
compatibility) lives in :mod:`app.services.comfy_agent_service`. This
repo only handles raw row ⇄ dict conversion + JSON encode/decode for
the few JSON-shaped columns.

See ``docs/comfy-agents-redesign.md`` for the design.
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from app.utils.ids import new_id


def _now() -> int:
    return int(time.time())


def _encode_json(value: Any | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _decode_json(text: str | None) -> Any | None:
    if text is None:
        return None
    return json.loads(text)


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    d = dict(row)
    d["loras_enabled"] = bool(d["loras_enabled"])
    d["model_params"] = _decode_json(d.pop("model_params_json"))
    d["source_ids"] = _decode_json(d.pop("source_ids_json"))
    d["output_slots"] = _decode_json(d.pop("output_slots_json")) or []
    return d


# --- read -----------------------------------------------------------------


def list_agents(
    conn: sqlite3.Connection, session_id: str,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM comfy_session_agents WHERE session_id = ? "
        "ORDER BY position, id",
        (session_id,),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]  # type: ignore[misc]


def get_agent(
    conn: sqlite3.Connection, agent_id: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM comfy_session_agents WHERE id = ?", (agent_id,),
    ).fetchone()
    return _row_to_dict(row)


def count_agents(conn: sqlite3.Connection, session_id: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM comfy_session_agents WHERE session_id = ?",
        (session_id,),
    ).fetchone()[0]


def _next_position(conn: sqlite3.Connection, session_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 FROM comfy_session_agents "
        "WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return int(row[0])


# --- write ----------------------------------------------------------------


def insert_agent(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    name: str,
    prompt: str = "",
    model_name: str | None = None,
    model_params: dict[str, Any] | None = None,
    source_scope: str = "all",
    source_ids: list[str] | None = None,
    loras_enabled: bool = False,
    output_slots: list[dict[str, Any]] | None = None,
    position: int | None = None,
) -> dict[str, Any]:
    """Append a new agent row. Returns the inserted row hydrated with
    JSON columns decoded.

    The repo does not validate against the workflow's slot map — the
    service layer does that and is also responsible for assigning ids
    to any output slots the caller passes without one. Output slots
    received here are persisted verbatim.
    """
    agent_id = new_id()
    now = _now()
    pos = position if position is not None else _next_position(conn, session_id)
    conn.execute(
        "INSERT INTO comfy_session_agents("
        "id, session_id, position, name, prompt, model_name, "
        "model_params_json, source_scope, source_ids_json, "
        "loras_enabled, output_slots_json, last_run_at, "
        "created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
        (
            agent_id, session_id, pos, name, prompt, model_name,
            _encode_json(model_params), source_scope,
            _encode_json(source_ids),
            1 if loras_enabled else 0,
            _encode_json(output_slots if output_slots is not None else []),
            now, now,
        ),
    )
    out = get_agent(conn, agent_id)
    assert out is not None  # just inserted
    return out


def update_agent(
    conn: sqlite3.Connection,
    agent_id: str,
    *,
    fields: dict[str, Any],
) -> dict[str, Any] | None:
    """Apply a partial update. ``fields`` keys correspond to the
    Pydantic ``AgentUpdate`` shape (``name``, ``prompt``, ``model_name``,
    ``model_params``, ``source_scope``, ``source_ids``,
    ``loras_enabled``, ``output_slots``, ``position``). Only keys
    present in the dict are changed; the call is a no-op write that
    bumps ``updated_at`` even if no other field is set.

    Returns the refreshed row, or ``None`` if the id is unknown.
    """
    if conn.execute(
        "SELECT 1 FROM comfy_session_agents WHERE id = ?", (agent_id,),
    ).fetchone() is None:
        return None

    sets: list[str] = []
    params: list[Any] = []
    if "name" in fields:
        sets.append("name = ?")
        params.append(fields["name"])
    if "prompt" in fields:
        sets.append("prompt = ?")
        params.append(fields["prompt"])
    if "model_name" in fields:
        sets.append("model_name = ?")
        params.append(fields["model_name"])
    if "model_params" in fields:
        sets.append("model_params_json = ?")
        params.append(_encode_json(fields["model_params"]))
    if "source_scope" in fields:
        sets.append("source_scope = ?")
        params.append(fields["source_scope"])
    if "source_ids" in fields:
        sets.append("source_ids_json = ?")
        params.append(_encode_json(fields["source_ids"]))
    if "loras_enabled" in fields:
        sets.append("loras_enabled = ?")
        params.append(1 if fields["loras_enabled"] else 0)
    if "output_slots" in fields:
        sets.append("output_slots_json = ?")
        params.append(_encode_json(fields["output_slots"]))
    if "position" in fields:
        sets.append("position = ?")
        params.append(fields["position"])

    sets.append("updated_at = ?")
    params.append(_now())
    params.append(agent_id)
    conn.execute(
        f"UPDATE comfy_session_agents SET {', '.join(sets)} WHERE id = ?",
        params,
    )
    return get_agent(conn, agent_id)


def touch_last_run_at(
    conn: sqlite3.Connection, agent_id: str, *, when: int | None = None,
) -> None:
    """Bump ``last_run_at`` after a successful per-agent run. Separate
    from :func:`update_agent` so the run path doesn't accidentally
    overwrite other fields when the user is editing concurrently."""
    ts = when if when is not None else _now()
    conn.execute(
        "UPDATE comfy_session_agents SET last_run_at = ?, updated_at = ? "
        "WHERE id = ?",
        (ts, ts, agent_id),
    )


def delete_agent(conn: sqlite3.Connection, agent_id: str) -> bool:
    cur = conn.execute(
        "DELETE FROM comfy_session_agents WHERE id = ?", (agent_id,),
    )
    return cur.rowcount > 0
