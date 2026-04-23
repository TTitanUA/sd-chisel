"""Raw CRUD over library tables. No business logic, no HTTP concerns.

Returns dicts (not sqlite3.Row) so the caller can JSON-serialize freely.
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any


def _now() -> int:
    return int(time.time())


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


# --- families ---------------------------------------------------------------


def list_families(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT * FROM families ORDER BY id")]


def get_family(conn: sqlite3.Connection, family_id: str) -> dict[str, Any] | None:
    return _row_to_dict(conn.execute(
        "SELECT * FROM families WHERE id = ?", (family_id,)
    ).fetchone())


# --- models -----------------------------------------------------------------


def list_models(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT * FROM models ORDER BY name")]


def get_model(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    return _row_to_dict(conn.execute(
        "SELECT * FROM models WHERE name = ?", (name,)
    ).fetchone())


def create_model(
    conn: sqlite3.Connection,
    *,
    name: str,
    display_name: str,
    family_id: str,
    description: str | None = None,
    author: str | None = None,
    version: str | None = None,
    source_url: str | None = None,
) -> dict[str, Any]:
    now = _now()
    conn.execute(
        "INSERT INTO models(name, display_name, family_id, description, author, version, "
        "source_url, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (name, display_name, family_id, description, author, version, source_url, now, now),
    )
    return get_model(conn, name)  # type: ignore[return-value]


# --- loras ------------------------------------------------------------------


def _hydrate_lora(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["tags"] = json.loads(d.get("tags") or "[]")
    d["trigger_words"] = json.loads(d.get("trigger_words") or "[]")
    d["family_compat"] = [
        r[0] for r in conn.execute(
            "SELECT family_id FROM lora_family_compat WHERE lora_name = ? ORDER BY family_id",
            (row["name"],),
        )
    ]
    return d


def list_loras(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM loras ORDER BY name").fetchall()
    return [_hydrate_lora(conn, r) for r in rows]


def get_lora(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM loras WHERE name = ?", (name,)).fetchone()
    return _hydrate_lora(conn, row) if row else None


def create_lora(
    conn: sqlite3.Connection,
    *,
    name: str,
    display_name: str,
    description: str,
    tags: list[str],
    trigger_words: list[str],
    family_compat: list[str],
    recommended_weight: float | None = None,
    author: str | None = None,
    version: str | None = None,
    source_url: str | None = None,
) -> dict[str, Any]:
    now = _now()
    try:
        conn.execute("BEGIN")
        conn.execute(
            "INSERT INTO loras(name, display_name, description, tags, trigger_words, "
            "recommended_weight, author, version, source_url, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                name, display_name, description,
                json.dumps(tags), json.dumps(trigger_words),
                recommended_weight, author, version, source_url, now, now,
            ),
        )
        for fam in family_compat:
            conn.execute(
                "INSERT INTO lora_family_compat(lora_name, family_id) VALUES (?, ?)",
                (name, fam),
            )
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    return get_lora(conn, name)  # type: ignore[return-value]


def delete_lora(conn: sqlite3.Connection, name: str) -> None:
    # vec_loras rowid cleanup is Slice 5's responsibility (requires the map entry);
    # here we only touch the main table. CASCADE handles lora_family_compat + lora_vec_map.
    conn.execute("DELETE FROM loras WHERE name = ?", (name,))
