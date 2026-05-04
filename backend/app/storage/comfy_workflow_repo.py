"""CRUD for ``comfy_workflows`` — API-format ComfyUI workflow JSONs the
user uploads or selects when creating a comfy session.

The graph_hash is the canonicalised sha256 of the workflow content used
to detect duplicate uploads (Phase 1 prompts replace/rename in that
case). Workflows are intentionally lightweight here — slot mapping and
session-binding semantics live in the API layer in later phases.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from typing import Any

from app.utils.ids import new_id


def _now() -> int:
    return int(time.time())


def canonicalise_graph(graph: dict[str, Any]) -> str:
    """Stable JSON encoding used for hashing.

    Sorts dict keys recursively and uses tight separators so that two
    semantically-identical workflows hash to the same value regardless
    of how their JSON was originally formatted.
    """
    return json.dumps(graph, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def hash_graph(graph: dict[str, Any]) -> str:
    return hashlib.sha256(canonicalise_graph(graph).encode("utf-8")).hexdigest()


# --- read -----------------------------------------------------------------


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    d = dict(row)
    d["graph"] = json.loads(d.pop("graph_json"))
    raw_slot_map = d.pop("slot_map_json", None)
    d["slot_map"] = json.loads(raw_slot_map) if raw_slot_map else None
    return d


def get_workflow(conn: sqlite3.Connection, workflow_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, name, graph_json, graph_hash, slot_map_json, created_at "
        "FROM comfy_workflows WHERE id = ?",
        (workflow_id,),
    ).fetchone()
    return _row_to_dict(row)


def list_workflows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, name, graph_hash, created_at FROM comfy_workflows "
        "ORDER BY created_at DESC, id",
    ).fetchall()
    return [dict(r) for r in rows]


def find_by_hash(conn: sqlite3.Connection, graph_hash: str) -> dict[str, Any] | None:
    """First (oldest) workflow with this hash, or None. Used for
    upload-time collision detection."""
    row = conn.execute(
        "SELECT id, name, graph_json, graph_hash, slot_map_json, created_at "
        "FROM comfy_workflows WHERE graph_hash = ? ORDER BY created_at LIMIT 1",
        (graph_hash,),
    ).fetchone()
    return _row_to_dict(row)


# --- write ----------------------------------------------------------------


def _encode_graph(graph: dict[str, Any]) -> str:
    """Storage encoding — uses the same canonicalised form so the column
    is always sorted/stable regardless of the upload's original
    formatting."""
    return canonicalise_graph(graph)


def insert_workflow(
    conn: sqlite3.Connection,
    *,
    name: str,
    graph: dict[str, Any],
) -> dict[str, Any]:
    workflow_id = new_id()
    digest = hash_graph(graph)
    conn.execute(
        "INSERT INTO comfy_workflows(id, name, graph_json, graph_hash, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (workflow_id, name, _encode_graph(graph), digest, _now()),
    )
    out = get_workflow(conn, workflow_id)
    assert out is not None  # just inserted
    return out


def replace_workflow(
    conn: sqlite3.Connection,
    *,
    workflow_id: str,
    name: str,
    graph: dict[str, Any],
) -> dict[str, Any] | None:
    """Overwrite an existing row in place. Returns None if the id is
    unknown."""
    if conn.execute(
        "SELECT 1 FROM comfy_workflows WHERE id = ?", (workflow_id,),
    ).fetchone() is None:
        return None
    digest = hash_graph(graph)
    conn.execute(
        "UPDATE comfy_workflows SET name = ?, graph_json = ?, graph_hash = ? "
        "WHERE id = ?",
        (name, _encode_graph(graph), digest, workflow_id),
    )
    return get_workflow(conn, workflow_id)


def delete_workflow(conn: sqlite3.Connection, workflow_id: str) -> bool:
    cur = conn.execute(
        "DELETE FROM comfy_workflows WHERE id = ?", (workflow_id,),
    )
    return cur.rowcount > 0


def set_slot_map(
    conn: sqlite3.Connection,
    *,
    workflow_id: str,
    slot_map: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Persist a slot map for the workflow. Returns the refreshed row,
    or None if the workflow id is unknown.

    ``slot_map`` shape: a dict whose keys are sd-chisel logical slot
    names (``positive_prompt``, ``negative_prompt``, ``main_image``,
    …) and whose values are either ``None`` (slot left unassigned) or
    ``{"node_id": str, "input_name": str}``. The repo doesn't validate
    those references against the graph — the API layer does that.
    Passing ``None`` clears the column.
    """
    if conn.execute(
        "SELECT 1 FROM comfy_workflows WHERE id = ?", (workflow_id,),
    ).fetchone() is None:
        return None
    encoded = (
        None
        if slot_map is None
        else json.dumps(slot_map, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    )
    conn.execute(
        "UPDATE comfy_workflows SET slot_map_json = ? WHERE id = ?",
        (encoded, workflow_id),
    )
    return get_workflow(conn, workflow_id)
