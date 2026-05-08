"""CRUD for ``comfy_jobs`` and ``comfy_job_outputs`` — Single Run history.

A row is created in `running` state at the start of the Single Run
pipeline (after the validate + snapshot stages succeed). The
orchestrator updates `prompt_id`, `status`, `error_message`, and
`finished_at` in-place as it advances; output files become rows on
`comfy_job_outputs` as the WS consumer captures them.
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from app.utils.ids import new_id


def _now() -> int:
    return int(time.time())


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    d = dict(row)
    d["payload"] = json.loads(d.pop("payload_json") or "{}")
    d["slot_map_snapshot"] = json.loads(d.pop("slot_map_snapshot_json"))
    d["agents_snapshot"] = json.loads(d.pop("agents_snapshot_json") or "[]")
    return d


def _output_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


_JOB_COLS = (
    "id, session_id, workflow_id, prompt_id, generation_id, payload_json, "
    "slot_map_snapshot_json, agents_snapshot_json, status, error_message, "
    "started_at, finished_at"
)
_OUTPUT_COLS = (
    "id, job_id, slot_label, node_id, output_index, path, is_primary, created_at"
)


# --- create -------------------------------------------------------------


def create_job(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    workflow_id: str,
    generation_id: str,
    slot_map_snapshot: list[dict[str, Any]],
    agents_snapshot: list[dict[str, Any]],
) -> dict[str, Any]:
    """Insert a new job row in `running` state. The orchestrator fills
    `prompt_id` and `payload_json` as the pipeline advances; both
    default to None / "{}" until then so the row is usable for
    listing the moment it's created."""
    job_id = new_id()
    now = _now()
    conn.execute(
        "INSERT INTO comfy_jobs ("
        "  id, session_id, workflow_id, prompt_id, generation_id,"
        "  payload_json, slot_map_snapshot_json, agents_snapshot_json,"
        "  status, error_message, started_at, finished_at"
        ") VALUES (?, ?, ?, NULL, ?, '{}', ?, ?, 'running', NULL, ?, NULL)",
        (
            job_id, session_id, workflow_id, generation_id,
            json.dumps(slot_map_snapshot, ensure_ascii=False),
            json.dumps(agents_snapshot, ensure_ascii=False),
            now,
        ),
    )
    conn.commit()
    return get_job(conn, job_id)  # type: ignore[return-value]


# --- update -------------------------------------------------------------


def set_prompt_id(conn: sqlite3.Connection, job_id: str, prompt_id: str) -> None:
    conn.execute(
        "UPDATE comfy_jobs SET prompt_id = ? WHERE id = ?",
        (prompt_id, job_id),
    )
    conn.commit()


def set_payload(conn: sqlite3.Connection, job_id: str, payload: dict[str, Any]) -> None:
    conn.execute(
        "UPDATE comfy_jobs SET payload_json = ? WHERE id = ?",
        (json.dumps(payload, ensure_ascii=False), job_id),
    )
    conn.commit()


def set_status(
    conn: sqlite3.Connection,
    job_id: str,
    status: str,
    *,
    error_message: str | None = None,
) -> None:
    """Update the run's lifecycle state.

    `success` / `error` / `cancelled` also stamp `finished_at`. Other
    transitions leave it alone (the orchestrator only flips to running
    via create_job; queued is reserved for a future Batch Run path).
    """
    if status not in ("queued", "running", "success", "error", "cancelled"):
        raise ValueError(f"unknown status {status!r}")
    if status in ("success", "error", "cancelled"):
        conn.execute(
            "UPDATE comfy_jobs SET status = ?, error_message = ?, "
            "finished_at = ? WHERE id = ?",
            (status, error_message, _now(), job_id),
        )
    else:
        conn.execute(
            "UPDATE comfy_jobs SET status = ?, error_message = ? WHERE id = ?",
            (status, error_message, job_id),
        )
    conn.commit()


# --- read -----------------------------------------------------------------


def get_job(conn: sqlite3.Connection, job_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {_JOB_COLS} FROM comfy_jobs WHERE id = ?", (job_id,),
    ).fetchone()
    return _row_to_dict(row)


def list_jobs_for_session(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"SELECT {_JOB_COLS} FROM comfy_jobs "
        "WHERE session_id = ? "
        # ROWID is the sub-second tiebreaker — two jobs created in
        # the same epoch second still sort by insertion order.
        "ORDER BY started_at DESC, ROWID DESC "
        "LIMIT ? OFFSET ?",
        (session_id, limit, offset),
    ).fetchall()
    return [d for r in rows if (d := _row_to_dict(r)) is not None]


def find_running_job(
    conn: sqlite3.Connection, session_id: str,
) -> dict[str, Any] | None:
    """Used to enforce one-active-run-per-session at Single Run time."""
    row = conn.execute(
        f"SELECT {_JOB_COLS} FROM comfy_jobs "
        "WHERE session_id = ? AND status IN ('queued', 'running') "
        "ORDER BY started_at DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    return _row_to_dict(row)


# --- delete ---------------------------------------------------------------


def delete_job(conn: sqlite3.Connection, job_id: str) -> bool:
    """Remove a job row (and outputs via FK CASCADE). Returns False
    when the row didn't exist; the caller is responsible for unlinking
    on-disk files (the row only stores their relative paths)."""
    cur = conn.execute("DELETE FROM comfy_jobs WHERE id = ?", (job_id,))
    conn.commit()
    return cur.rowcount > 0


# --- outputs --------------------------------------------------------------


def add_output(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    slot_label: str | None,
    node_id: str,
    output_index: int,
    path: str,
    is_primary: bool,
) -> dict[str, Any]:
    out_id = new_id()
    conn.execute(
        "INSERT INTO comfy_job_outputs ("
        "  id, job_id, slot_label, node_id, output_index, path, is_primary,"
        "  created_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            out_id, job_id, slot_label, node_id, output_index, path,
            1 if is_primary else 0, _now(),
        ),
    )
    conn.commit()
    row = conn.execute(
        f"SELECT {_OUTPUT_COLS} FROM comfy_job_outputs WHERE id = ?", (out_id,),
    ).fetchone()
    return _output_row_to_dict(row)


def list_outputs(
    conn: sqlite3.Connection, job_id: str,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"SELECT {_OUTPUT_COLS} FROM comfy_job_outputs "
        "WHERE job_id = ? ORDER BY output_index, id",
        (job_id,),
    ).fetchall()
    return [_output_row_to_dict(r) for r in rows]
