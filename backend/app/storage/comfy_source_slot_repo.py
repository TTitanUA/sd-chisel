"""CRUD for ``comfy_session_source_slots`` — per-session named slots
that map to ``session_source_images`` rows.

The table replaces a localStorage-backed mock that lost data on
browser switches. Workflow slot maps and agent input slots reference
slots by id; clients may pass an explicit ``id`` when creating to
preserve those references during the one-time migration from
localStorage.
"""
from __future__ import annotations

import sqlite3
import time
from typing import Any

from app.utils.ids import new_id

VALID_PURPOSES = ("main", "ref_in_scene", "ref_text_only")

_SLOT_COLS = (
    "id, session_id, position, key, purpose, description, "
    "source_image_id, created_at, updated_at"
)


def _now() -> int:
    return int(time.time())


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


# --- read -----------------------------------------------------------------


def list_for_session(
    conn: sqlite3.Connection, session_id: str,
) -> list[dict[str, Any]]:
    """Slots in display order. ROWID is the sub-second tiebreaker so
    two slots created in the same epoch second still sort by insertion
    order — same pattern source_image_repo and comfy_jobs_repo use."""
    rows = conn.execute(
        f"SELECT {_SLOT_COLS} FROM comfy_session_source_slots "
        "WHERE session_id = ? ORDER BY position ASC, ROWID ASC",
        (session_id,),
    ).fetchall()
    return [d for r in rows if (d := _row_to_dict(r)) is not None]


def get(
    conn: sqlite3.Connection, session_id: str, slot_id: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {_SLOT_COLS} FROM comfy_session_source_slots "
        "WHERE session_id = ? AND id = ?",
        (session_id, slot_id),
    ).fetchone()
    return _row_to_dict(row)


# --- write ----------------------------------------------------------------


def create(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    key: str,
    purpose: str = "main",
    description: str | None = None,
    source_image_id: str | None = None,
    position: int | None = None,
    slot_id: str | None = None,
) -> dict[str, Any]:
    """Create a new slot. ``slot_id`` is accepted (and required-shape,
    not random) for the localStorage migration path so workflow /
    agent references that already point at a SourceSlot id keep
    resolving; otherwise falls back to ``new_id()``.

    ``position`` defaults to "after the last existing slot". ``key``
    must be unique within the session — the table CHECK enforces it
    and we surface a ValueError on conflict so the API can return 409.
    """
    if purpose not in VALID_PURPOSES:
        raise ValueError(f"invalid purpose {purpose!r}")
    sid = slot_id or new_id()
    now = _now()
    if position is None:
        next_pos = conn.execute(
            "SELECT COALESCE(MAX(position) + 1, 0) FROM "
            "comfy_session_source_slots WHERE session_id = ?",
            (session_id,),
        ).fetchone()[0]
        position = int(next_pos)
    try:
        conn.execute(
            "INSERT INTO comfy_session_source_slots ("
            "  id, session_id, position, key, purpose, description, "
            "  source_image_id, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, session_id, position, key, purpose, description,
             source_image_id, now, now),
        )
    except sqlite3.IntegrityError as exc:
        # UNIQUE on (session_id, key) — convert to a domain error so
        # the API can surface 409 with a useful message.
        if "UNIQUE" in str(exc):
            raise ValueError(f"slot key {key!r} already used in session") from exc
        raise
    conn.commit()
    return get(conn, session_id, sid)  # type: ignore[return-value]


_UNSET: Any = object()
"""Sentinel for "leave this field alone" on update(). Distinguishes a
missing PATCH field from an explicit `null` clear (description and
source_image_id are both nullable; the PATCH endpoint can set or
clear them independently)."""


def update(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    slot_id: str,
    key: str | None = None,
    purpose: str | None = None,
    description: Any = _UNSET,
    source_image_id: Any = _UNSET,
    position: int | None = None,
) -> dict[str, Any] | None:
    """Patch the slot. Returns the refreshed row, or None when the
    slot doesn't exist."""
    existing = get(conn, session_id, slot_id)
    if existing is None:
        return None
    sets: list[str] = []
    args: list[Any] = []
    if key is not None and key != existing["key"]:
        sets.append("key = ?")
        args.append(key)
    if purpose is not None and purpose != existing["purpose"]:
        if purpose not in VALID_PURPOSES:
            raise ValueError(f"invalid purpose {purpose!r}")
        sets.append("purpose = ?")
        args.append(purpose)
    if description is not _UNSET:
        sets.append("description = ?")
        args.append(description)
    if source_image_id is not _UNSET:
        sets.append("source_image_id = ?")
        args.append(source_image_id)
    if position is not None and position != existing["position"]:
        sets.append("position = ?")
        args.append(int(position))
    if not sets:
        return existing
    sets.append("updated_at = ?")
    args.append(_now())
    args.extend((session_id, slot_id))
    try:
        conn.execute(
            f"UPDATE comfy_session_source_slots SET {', '.join(sets)} "
            "WHERE session_id = ? AND id = ?",
            args,
        )
    except sqlite3.IntegrityError as exc:
        if "UNIQUE" in str(exc):
            raise ValueError(
                f"slot key {key!r} already used in session",
            ) from exc
        raise
    conn.commit()
    return get(conn, session_id, slot_id)


def delete(
    conn: sqlite3.Connection, session_id: str, slot_id: str,
) -> bool:
    cur = conn.execute(
        "DELETE FROM comfy_session_source_slots "
        "WHERE session_id = ? AND id = ?",
        (session_id, slot_id),
    )
    conn.commit()
    return cur.rowcount > 0
