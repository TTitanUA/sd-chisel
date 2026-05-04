"""Catalog read/edit operations over comfy_packs / comfy_nodes /
comfy_node_overrides.

The library's Comfy Nodes section is read-mostly: rows are written by
the per-node import wizard (see future ``comfy_import_service``), and
the only mutation surface here is editing description / role hints /
category, which lands in ``comfy_node_overrides`` and is merged on
read so that the next re-import doesn't clobber user edits.
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any


def _now() -> int:
    return int(time.time())


# Sentinel for "kwarg not provided" — distinct from None, which means
# "clear this override". Used by ``set_override`` so callers can leave
# fields untouched without re-reading them first.
_UNSET: Any = object()


# --- packs ---------------------------------------------------------------


_PACK_COLS = (
    "name, display_name, description, version, repo_url, publisher_id, "
    "dir_path, readme_md, imported_at"
)


def list_packs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"SELECT {_PACK_COLS},"
        f"  (SELECT COUNT(*) FROM comfy_nodes n WHERE n.pack_name = comfy_packs.name) "
        f"    AS node_count "
        f"FROM comfy_packs ORDER BY name",
    ).fetchall()
    return [dict(r) for r in rows]


def get_pack(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {_PACK_COLS} FROM comfy_packs WHERE name = ?",
        (name,),
    ).fetchone()
    return dict(row) if row is not None else None


def upsert_pack(
    conn: sqlite3.Connection,
    *,
    name: str,
    display_name: str,
    description: str | None = None,
    version: str | None = None,
    repo_url: str | None = None,
    publisher_id: str | None = None,
    dir_path: str | None = None,
    readme_md: str | None = None,
) -> dict[str, Any]:
    now = _now()
    conn.execute(
        "INSERT INTO comfy_packs(name, display_name, description, version, "
        "  repo_url, publisher_id, dir_path, readme_md, imported_at) "
        "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET "
        "  display_name = excluded.display_name, "
        "  description  = excluded.description, "
        "  version      = excluded.version, "
        "  repo_url     = excluded.repo_url, "
        "  publisher_id = excluded.publisher_id, "
        "  dir_path     = excluded.dir_path, "
        "  readme_md    = excluded.readme_md",
        (
            name, display_name, description, version,
            repo_url, publisher_id, dir_path, readme_md, now,
        ),
    )
    out = get_pack(conn, name)
    assert out is not None
    return out


# --- nodes ---------------------------------------------------------------


_NODE_COLS = (
    "n.class_type, n.pack_name, n.display_name, n.category, "
    "n.inputs_raw_json, n.outputs_raw_json, n.inputs_semantic_json, "
    "n.description_md, n.requires_semantic_config, "
    "n.imported_at, n.last_seen_in_object_info_at, "
    "o.description_md       AS override_description_md, "
    "o.inputs_semantic_json AS override_inputs_semantic_json, "
    "o.category             AS override_category, "
    "o.updated_at           AS override_updated_at"
)


def _decode_node_row(row: sqlite3.Row) -> dict[str, Any]:
    """Apply override merge and decode JSON columns into Python objects."""
    base = dict(row)
    override_desc = base.pop("override_description_md")
    override_inputs = base.pop("override_inputs_semantic_json")
    override_cat = base.pop("override_category")
    override_at = base.pop("override_updated_at")

    description = override_desc if override_desc is not None else base["description_md"]
    inputs_semantic_raw = (
        override_inputs if override_inputs is not None else base["inputs_semantic_json"]
    )
    category = override_cat if override_cat is not None else base["category"]

    return {
        "class_type":               base["class_type"],
        "pack_name":                base["pack_name"],
        "display_name":             base["display_name"],
        "category":                 category,
        "description_md":           description,
        "inputs_raw":               json.loads(base["inputs_raw_json"]),
        "outputs_raw":              json.loads(base["outputs_raw_json"]),
        "inputs_semantic":          json.loads(inputs_semantic_raw),
        "requires_semantic_config": bool(base["requires_semantic_config"]),
        "imported_at":              base["imported_at"],
        "last_seen_in_object_info_at": base["last_seen_in_object_info_at"],
        "has_override":             override_at is not None,
        "override_updated_at":      override_at,
    }


def list_nodes(
    conn: sqlite3.Connection,
    *,
    q: str | None = None,
    pack: str | None = None,
    has_description: bool | None = None,
) -> list[dict[str, Any]]:
    """Return a compact summary list with override merge applied."""
    where: list[str] = []
    params: list[Any] = []
    if q:
        like = f"%{q.lower()}%"
        where.append(
            "(LOWER(n.class_type) LIKE ? OR LOWER(n.display_name) LIKE ? "
            " OR LOWER(COALESCE(o.description_md, n.description_md)) LIKE ?)"
        )
        params.extend([like, like, like])
    if pack:
        where.append("n.pack_name = ?")
        params.append(pack)
    if has_description is True:
        where.append(
            "TRIM(COALESCE(o.description_md, n.description_md)) != ''"
        )
    elif has_description is False:
        where.append(
            "TRIM(COALESCE(o.description_md, n.description_md)) = ''"
        )

    sql = (
        f"SELECT {_NODE_COLS} FROM comfy_nodes n "
        f"LEFT JOIN comfy_node_overrides o ON o.class_type = n.class_type"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY n.display_name COLLATE NOCASE, n.class_type"
    rows = conn.execute(sql, params).fetchall()
    return [_decode_node_row(r) for r in rows]


def get_node(conn: sqlite3.Connection, class_type: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {_NODE_COLS} FROM comfy_nodes n "
        f"LEFT JOIN comfy_node_overrides o ON o.class_type = n.class_type "
        f"WHERE n.class_type = ?",
        (class_type,),
    ).fetchone()
    return _decode_node_row(row) if row is not None else None


def upsert_node(
    conn: sqlite3.Connection,
    *,
    class_type: str,
    pack_name: str,
    display_name: str,
    category: str | None,
    inputs_raw: Any,
    outputs_raw: Any,
    inputs_semantic: Any,
    description_md: str,
    requires_semantic_config: bool = True,
) -> dict[str, Any]:
    now = _now()
    conn.execute(
        "INSERT INTO comfy_nodes(class_type, pack_name, display_name, category, "
        "  inputs_raw_json, outputs_raw_json, inputs_semantic_json, "
        "  description_md, requires_semantic_config, "
        "  imported_at, last_seen_in_object_info_at) "
        "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(class_type) DO UPDATE SET "
        "  pack_name                   = excluded.pack_name, "
        "  display_name                = excluded.display_name, "
        "  category                    = excluded.category, "
        "  inputs_raw_json             = excluded.inputs_raw_json, "
        "  outputs_raw_json            = excluded.outputs_raw_json, "
        "  inputs_semantic_json        = excluded.inputs_semantic_json, "
        "  description_md              = excluded.description_md, "
        "  requires_semantic_config    = excluded.requires_semantic_config, "
        "  last_seen_in_object_info_at = excluded.last_seen_in_object_info_at",
        (
            class_type, pack_name, display_name, category,
            json.dumps(inputs_raw, ensure_ascii=False),
            json.dumps(outputs_raw, ensure_ascii=False),
            json.dumps(inputs_semantic, ensure_ascii=False),
            description_md,
            1 if requires_semantic_config else 0,
            now, now,
        ),
    )
    out = get_node(conn, class_type)
    assert out is not None
    return out


def set_override(
    conn: sqlite3.Connection,
    *,
    class_type: str,
    description_md: Any = _UNSET,
    inputs_semantic: Any = _UNSET,
    category: Any = _UNSET,
) -> dict[str, Any] | None:
    """Write into comfy_node_overrides. Each kwarg uses a sentinel
    default so callers can clear an override (pass ``None``) or leave
    it untouched (don't pass the kwarg at all).

    Returns the merged node row or ``None`` if the class_type is unknown.
    """
    base = get_node(conn, class_type)
    if base is None:
        return None
    # Read the existing override row to preserve fields the caller
    # didn't mention.
    existing = conn.execute(
        "SELECT description_md, inputs_semantic_json, category "
        "FROM comfy_node_overrides WHERE class_type = ?",
        (class_type,),
    ).fetchone()

    new_desc = (
        description_md
        if description_md is not _UNSET
        else (existing["description_md"] if existing is not None else None)
    )
    if inputs_semantic is not _UNSET:
        new_inputs_obj = inputs_semantic
    elif existing is not None and existing["inputs_semantic_json"] is not None:
        new_inputs_obj = json.loads(existing["inputs_semantic_json"])
    else:
        new_inputs_obj = None
    new_cat = (
        category
        if category is not _UNSET
        else (existing["category"] if existing is not None else None)
    )

    new_inputs_str = (
        json.dumps(new_inputs_obj, ensure_ascii=False)
        if new_inputs_obj is not None else None
    )

    if new_desc is None and new_inputs_str is None and new_cat is None:
        # No overrides remain — drop the row.
        conn.execute(
            "DELETE FROM comfy_node_overrides WHERE class_type = ?",
            (class_type,),
        )
    else:
        conn.execute(
            "INSERT INTO comfy_node_overrides(class_type, description_md, "
            "  inputs_semantic_json, category, updated_at) "
            "VALUES(?, ?, ?, ?, ?) "
            "ON CONFLICT(class_type) DO UPDATE SET "
            "  description_md       = excluded.description_md, "
            "  inputs_semantic_json = excluded.inputs_semantic_json, "
            "  category             = excluded.category, "
            "  updated_at           = excluded.updated_at",
            (class_type, new_desc, new_inputs_str, new_cat, _now()),
        )
    return get_node(conn, class_type)
