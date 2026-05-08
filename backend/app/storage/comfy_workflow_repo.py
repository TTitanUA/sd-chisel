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
    raw_output_map = d.pop("output_slot_map_json", None)
    d["output_slot_map"] = (
        json.loads(raw_output_map) if raw_output_map else None
    )
    return d


_WORKFLOW_COLS = (
    "id, name, graph_json, graph_hash, slot_map_json, "
    "output_slot_map_json, created_at"
)


def get_workflow(conn: sqlite3.Connection, workflow_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {_WORKFLOW_COLS} FROM comfy_workflows WHERE id = ?",
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
        f"SELECT {_WORKFLOW_COLS} FROM comfy_workflows "
        "WHERE graph_hash = ? ORDER BY created_at LIMIT 1",
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

    ``slot_map`` is the JSON payload to write verbatim. Phase 2.5
    writes ``{"version": 2, "slots": [...]}``; older Phase 2 rows
    carry the legacy three-key dict and are upgraded on read by
    :func:`app.services.comfy_slot_map_service.upgrade_slot_map`. The
    repo doesn't validate the payload against the graph — the API
    layer does that. Passing ``None`` clears the column.
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


def set_output_slot_map(
    conn: sqlite3.Connection,
    *,
    workflow_id: str,
    output_slot_map: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Persist an output slot map for the workflow. Returns the
    refreshed row, or None if the workflow id is unknown.

    ``output_slot_map`` is the JSON payload to write verbatim. PR-2
    writes ``{"version": 1, "outputs": [...]}``. Passing ``None`` clears
    the column — read-time falls back to
    :func:`comfy_output_slot_service.auto_default_outputs`.
    """
    if conn.execute(
        "SELECT 1 FROM comfy_workflows WHERE id = ?", (workflow_id,),
    ).fetchone() is None:
        return None
    encoded = (
        None
        if output_slot_map is None
        else json.dumps(
            output_slot_map, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False,
        )
    )
    conn.execute(
        "UPDATE comfy_workflows SET output_slot_map_json = ? WHERE id = ?",
        (encoded, workflow_id),
    )
    return get_workflow(conn, workflow_id)
