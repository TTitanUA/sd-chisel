"""Repository for global app settings and LMStudio model cache."""
from __future__ import annotations

import sqlite3
import time
from typing import Any

from app.services import action_settings as action_settings_svc


def _now() -> int:
    return int(time.time())


def _normalize_url(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip().rstrip("/")
    return stripped or None


_MODEL_COLS = "name, enabled, last_seen, vision, tool_use, reasoning, favorite, hidden"


def _model_row(r: sqlite3.Row) -> dict[str, Any]:
    d = dict(r)
    d["enabled"] = bool(d["enabled"])
    d["vision"] = bool(d["vision"])
    d["tool_use"] = bool(d["tool_use"])
    d["reasoning"] = bool(d["reasoning"])
    d["favorite"] = bool(d["favorite"])
    d["hidden"] = bool(d.get("hidden", 0))
    return d


# --- app_settings ---------------------------------------------------------


def get_lmstudio(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        "SELECT lmstudio_url, lmstudio_api_key, updated_at "
        "FROM app_settings WHERE id = 1",
    ).fetchone()
    return dict(row) if row is not None else {
        "lmstudio_url": None,
        "lmstudio_api_key": None,
        "updated_at": 0,
    }


def set_lmstudio(
    conn: sqlite3.Connection,
    *,
    url: str | None,
    api_key: str | None,
) -> dict[str, Any]:
    now = _now()
    conn.execute(
        "UPDATE app_settings SET lmstudio_url = ?, lmstudio_api_key = ?, "
        "updated_at = ? WHERE id = 1",
        (_normalize_url(url), (api_key or None), now),
    )
    return get_lmstudio(conn)


def get_comfyui(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        "SELECT comfyui_url, comfyui_path, comfyui_api_key, updated_at "
        "FROM app_settings WHERE id = 1",
    ).fetchone()
    return dict(row) if row is not None else {
        "comfyui_url": None,
        "comfyui_path": None,
        "comfyui_api_key": None,
        "updated_at": 0,
    }


def set_comfyui(
    conn: sqlite3.Connection,
    *,
    url: str | None,
    install_path: str | None,
    api_key: str | None,
) -> dict[str, Any]:
    now = _now()
    path_clean = (install_path or "").strip() or None
    conn.execute(
        "UPDATE app_settings SET comfyui_url = ?, comfyui_path = ?, "
        "comfyui_api_key = ?, updated_at = ? WHERE id = 1",
        (_normalize_url(url), path_clean, (api_key or None), now),
    )
    return get_comfyui(conn)


def get_privacy(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        "SELECT show_hidden, updated_at FROM app_settings WHERE id = 1",
    ).fetchone()
    if row is None:
        return {"show_hidden": False, "updated_at": 0}
    return {"show_hidden": bool(row["show_hidden"]), "updated_at": row["updated_at"]}


def set_privacy(
    conn: sqlite3.Connection, *, show_hidden: bool,
) -> dict[str, Any]:
    conn.execute(
        "UPDATE app_settings SET show_hidden = ?, updated_at = ? WHERE id = 1",
        (1 if show_hidden else 0, _now()),
    )
    return get_privacy(conn)


# --- per-action default sampling bundles ----------------------------------


def _column_for(action: str) -> str:
    if action not in action_settings_svc.ACTIONS:
        raise ValueError(f"unknown action: {action!r}")
    return f"default_{action}_settings"


def get_default_bundles(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """Return all four default bundles, decoded. Missing/NULL columns map to {}."""
    cols = ", ".join(f"default_{a}_settings" for a in action_settings_svc.ACTIONS)
    row = conn.execute(
        f"SELECT {cols} FROM app_settings WHERE id = 1",
    ).fetchone()
    out: dict[str, dict[str, Any]] = {}
    for a in action_settings_svc.ACTIONS:
        raw = row[f"default_{a}_settings"] if row is not None else None
        decoded = action_settings_svc.decode_bundle(raw)
        out[a] = decoded if decoded is not None else {}
    return out


def get_default_bundle(
    conn: sqlite3.Connection, action: str,
) -> dict[str, Any]:
    """Return the default bundle for a single action (empty dict if unset)."""
    col = _column_for(action)
    row = conn.execute(
        f"SELECT {col} FROM app_settings WHERE id = 1",
    ).fetchone()
    raw = row[col] if row is not None else None
    decoded = action_settings_svc.decode_bundle(raw)
    return decoded if decoded is not None else {}


def set_default_bundles(
    conn: sqlite3.Connection,
    *,
    bundles: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Update one or more action default bundles. Each value is validated.

    Pass ``{}`` for an action to clear all overrides for that action.
    Actions absent from ``bundles`` are left untouched.
    """
    sets: list[str] = []
    params: list[Any] = []
    for action, bundle in bundles.items():
        col = _column_for(action)
        validated = action_settings_svc.parse_bundle(bundle)
        encoded = action_settings_svc.encode_bundle(validated)
        sets.append(f"{col} = ?")
        params.append(encoded)
    if sets:
        sets.append("updated_at = ?")
        params.append(_now())
        params.append(1)
        conn.execute(
            f"UPDATE app_settings SET {', '.join(sets)} WHERE id = ?",
            params,
        )
    return get_default_bundles(conn)


# --- lm_models ------------------------------------------------------------


def list_lm_models(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"SELECT {_MODEL_COLS} FROM lm_models ORDER BY name"
    ).fetchall()
    return [_model_row(r) for r in rows]


def get_lm_model(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {_MODEL_COLS} FROM lm_models WHERE name = ?",
        (name,),
    ).fetchone()
    return _model_row(row) if row is not None else None


def get_favorite_lm_model(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute(
        f"SELECT {_MODEL_COLS} FROM lm_models "
        "WHERE favorite = 1 AND enabled = 1 LIMIT 1",
    ).fetchone()
    return _model_row(row) if row is not None else None


def upsert_lm_models(
    conn: sqlite3.Connection,
    *,
    models: list[dict[str, Any]],
    seen_at: int | None = None,
) -> None:
    ts = seen_at if seen_at is not None else _now()
    for m in models:
        conn.execute(
            "INSERT INTO lm_models(name, enabled, last_seen, vision, tool_use, reasoning) "
            "VALUES (?, 1, ?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET "
            "last_seen = excluded.last_seen, "
            "vision = excluded.vision, "
            "tool_use = excluded.tool_use, "
            "reasoning = excluded.reasoning",
            (m["name"], ts, int(m["vision"]), int(m["tool_use"]), int(m["reasoning"])),
        )


def patch_lm_model(
    conn: sqlite3.Connection,
    *,
    name: str,
    vision: bool | None = None,
    tool_use: bool | None = None,
    reasoning: bool | None = None,
    enabled: bool | None = None,
    favorite: bool | None = None,
    hidden: bool | None = None,
) -> dict[str, Any] | None:
    # favorite is exclusive — setting one clears the others.
    if favorite is True:
        if conn.execute("SELECT 1 FROM lm_models WHERE name = ?", (name,)).fetchone() is None:
            return None
        conn.execute("UPDATE lm_models SET favorite = 0 WHERE favorite = 1")
        conn.execute("UPDATE lm_models SET favorite = 1 WHERE name = ?", (name,))

    sets: list[str] = []
    params: list[Any] = []
    if vision is not None:
        sets.append("vision = ?"); params.append(1 if vision else 0)
    if tool_use is not None:
        sets.append("tool_use = ?"); params.append(1 if tool_use else 0)
    if reasoning is not None:
        sets.append("reasoning = ?"); params.append(1 if reasoning else 0)
    if enabled is not None:
        sets.append("enabled = ?"); params.append(1 if enabled else 0)
    if favorite is False:
        sets.append("favorite = ?"); params.append(0)
    if hidden is not None:
        sets.append("hidden = ?"); params.append(1 if hidden else 0)
    if not sets:
        return get_lm_model(conn, name)
    params.append(name)
    cur = conn.execute(
        f"UPDATE lm_models SET {', '.join(sets)} WHERE name = ?", params,
    )
    if cur.rowcount == 0 and favorite is not True:
        return None
    return get_lm_model(conn, name)
