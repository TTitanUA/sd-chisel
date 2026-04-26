"""Raw CRUD over library tables. No HTTP concerns.

Returns dicts (not sqlite3.Row) so callers can JSON-serialize freely.
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


def _like(value: str) -> str:
    return f"%{value.lower()}%"


# --- families ---------------------------------------------------------------


def list_families(conn: sqlite3.Connection, q: str | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM families"
    params: list[Any] = []
    if q:
        sql += " WHERE lower(id) LIKE ? OR lower(display_name) LIKE ? OR lower(prompt_guide) LIKE ?"
        params.extend([_like(q), _like(q), _like(q)])
    sql += " ORDER BY id"
    return [dict(r) for r in conn.execute(sql, params)]


def get_family(conn: sqlite3.Connection, family_id: str) -> dict[str, Any] | None:
    return _row_to_dict(conn.execute("SELECT * FROM families WHERE id = ?", (family_id,)).fetchone())


def create_family(
    conn: sqlite3.Connection,
    *,
    id: str,
    display_name: str,
    prompt_guide: str,
) -> dict[str, Any]:
    now = _now()
    conn.execute(
        "INSERT INTO families(id, display_name, prompt_guide, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (id, display_name, prompt_guide, now, now),
    )
    return get_family(conn, id)  # type: ignore[return-value]


def update_family(
    conn: sqlite3.Connection,
    family_id: str,
    *,
    display_name: str,
    prompt_guide: str,
) -> dict[str, Any] | None:
    now = _now()
    cur = conn.execute(
        "UPDATE families SET display_name = ?, prompt_guide = ?, updated_at = ? WHERE id = ?",
        (display_name, prompt_guide, now, family_id),
    )
    if cur.rowcount == 0:
        return None
    return get_family(conn, family_id)


def delete_family(conn: sqlite3.Connection, family_id: str) -> bool:
    cur = conn.execute("DELETE FROM families WHERE id = ?", (family_id,))
    return cur.rowcount > 0


# --- models -----------------------------------------------------------------


def list_models(
    conn: sqlite3.Connection,
    *,
    family_id: str | None = None,
    q: str | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if family_id:
        clauses.append("family_id = ?")
        params.append(family_id)
    if q:
        clauses.append(
            "(lower(name) LIKE ? OR lower(display_name) LIKE ? OR lower(coalesce(description, '')) LIKE ?)"
        )
        params.extend([_like(q), _like(q), _like(q)])
    sql = "SELECT * FROM models"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY name"
    return [dict(r) for r in conn.execute(sql, params)]


def get_model(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    return _row_to_dict(conn.execute("SELECT * FROM models WHERE name = ?", (name,)).fetchone())


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


def update_model(
    conn: sqlite3.Connection,
    name: str,
    *,
    display_name: str,
    family_id: str,
    description: str | None = None,
    author: str | None = None,
    version: str | None = None,
    source_url: str | None = None,
) -> dict[str, Any] | None:
    now = _now()
    cur = conn.execute(
        "UPDATE models SET display_name = ?, family_id = ?, description = ?, author = ?, "
        "version = ?, source_url = ?, updated_at = ? WHERE name = ?",
        (display_name, family_id, description, author, version, source_url, now, name),
    )
    if cur.rowcount == 0:
        return None
    return get_model(conn, name)


def delete_model(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute("DELETE FROM models WHERE name = ?", (name,))
    return cur.rowcount > 0


# --- loras ------------------------------------------------------------------


def _hydrate_lora(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["tags"] = json.loads(d.get("tags") or "[]")
    d["trigger_words"] = json.loads(d.get("trigger_words") or "[]")
    return d


def list_loras(
    conn: sqlite3.Connection,
    *,
    family_id: str | None = None,
    tag: str | None = None,
    q: str | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if family_id:
        clauses.append("family_id = ?")
        params.append(family_id)
    if tag:
        clauses.append("EXISTS (SELECT 1 FROM json_each(loras.tags) WHERE value = ?)")
        params.append(tag)
    if q:
        clauses.append(
            "(lower(name) LIKE ? OR lower(display_name) LIKE ? OR lower(description) LIKE ? "
            "OR lower(tags) LIKE ? OR lower(trigger_words) LIKE ?)"
        )
        params.extend([_like(q), _like(q), _like(q), _like(q), _like(q)])
    sql = "SELECT * FROM loras"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY name"
    rows = conn.execute(sql, params).fetchall()
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
    family_id: str,
    recommended_weight: float | None = None,
    author: str | None = None,
    version: str | None = None,
    source_url: str | None = None,
) -> dict[str, Any]:
    now = _now()
    conn.execute(
        "INSERT INTO loras(name, display_name, description, tags, trigger_words, "
        "recommended_weight, author, version, source_url, created_at, updated_at, family_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            name,
            display_name,
            description,
            json.dumps(tags),
            json.dumps(trigger_words),
            recommended_weight,
            author,
            version,
            source_url,
            now,
            now,
            family_id,
        ),
    )
    return get_lora(conn, name)  # type: ignore[return-value]


def update_lora(
    conn: sqlite3.Connection,
    name: str,
    *,
    display_name: str,
    description: str,
    tags: list[str],
    trigger_words: list[str],
    family_id: str,
    recommended_weight: float | None = None,
    author: str | None = None,
    version: str | None = None,
    source_url: str | None = None,
) -> dict[str, Any] | None:
    now = _now()
    cur = conn.execute(
        "UPDATE loras SET display_name = ?, description = ?, tags = ?, trigger_words = ?, "
        "recommended_weight = ?, author = ?, version = ?, source_url = ?, updated_at = ?, family_id = ? "
        "WHERE name = ?",
        (
            display_name,
            description,
            json.dumps(tags),
            json.dumps(trigger_words),
            recommended_weight,
            author,
            version,
            source_url,
            now,
            family_id,
            name,
        ),
    )
    if cur.rowcount == 0:
        return None
    return get_lora(conn, name)


def delete_lora(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute("DELETE FROM loras WHERE name = ?", (name,))
    return cur.rowcount > 0


def list_all_lora_names(conn: sqlite3.Connection) -> list[str]:
    """Return every LoRA primary key, sorted. Used by `reindex-all` CLI."""
    return [r[0] for r in conn.execute("SELECT name FROM loras ORDER BY name")]
