"""Repository for global app settings and LMStudio model cache."""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterable
from typing import Any, Literal
from urllib.parse import urlparse

ROLE = Literal["vl", "prompt", "both"]
_VALID_ROLES = {"vl", "prompt", "both"}


def _now() -> int:
    return int(time.time())


def _normalize_base_url(value: str | None) -> str | None:
    """Strip trailing slash, then auto-append `/v1` when no path is given.

    LMStudio (and the OpenAI spec generally) expose the model API under `/v1`.
    Users routinely paste `http://localhost:1234` from the LMStudio UI, which
    silently fails with a shape error on refresh. Appending `/v1` only when
    the path is empty avoids surprising users who legitimately use a
    reverse-proxied prefix like `/proxy/openai/v1`.
    """
    if value is None:
        return None
    stripped = value.strip().rstrip("/")
    if not stripped:
        return None
    parsed = urlparse(stripped)
    if parsed.scheme and parsed.netloc and parsed.path in ("", "/"):
        return f"{stripped}/v1"
    return stripped


# --- app_settings ---------------------------------------------------------


def get_lmstudio(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        "SELECT lmstudio_base_url, lmstudio_api_key, updated_at "
        "FROM app_settings WHERE id = 1",
    ).fetchone()
    return dict(row) if row is not None else {
        "lmstudio_base_url": None,
        "lmstudio_api_key": None,
        "updated_at": 0,
    }


def set_lmstudio(
    conn: sqlite3.Connection,
    *,
    base_url: str | None,
    api_key: str | None,
) -> dict[str, Any]:
    now = _now()
    conn.execute(
        "UPDATE app_settings SET lmstudio_base_url = ?, lmstudio_api_key = ?, "
        "updated_at = ? WHERE id = 1",
        (_normalize_base_url(base_url), (api_key or None), now),
    )
    return get_lmstudio(conn)


# --- lm_models ------------------------------------------------------------


def list_lm_models(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT name, role, enabled, last_seen FROM lm_models ORDER BY name"
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        d["enabled"] = bool(d["enabled"])
        out.append(d)
    return out


def get_lm_model(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT name, role, enabled, last_seen FROM lm_models WHERE name = ?",
        (name,),
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["enabled"] = bool(d["enabled"])
    return d


def upsert_lm_models(
    conn: sqlite3.Connection,
    *,
    names: Iterable[str],
    seen_at: int | None = None,
) -> None:
    """Add new models with defaults; refresh `last_seen` on existing rows.

    Never clobbers user-set role / enabled flags. Models that are no longer
    reported by LMStudio remain in the cache so the user can still see them
    (with stale `last_seen`) — operationally less surprising than dropping
    rows on every refresh.
    """
    ts = seen_at if seen_at is not None else _now()
    for name in names:
        conn.execute(
            "INSERT INTO lm_models(name, role, enabled, last_seen) "
            "VALUES (?, 'both', 1, ?) "
            "ON CONFLICT(name) DO UPDATE SET last_seen = excluded.last_seen",
            (name, ts),
        )


def update_lm_model(
    conn: sqlite3.Connection,
    *,
    name: str,
    role: ROLE | None = None,
    enabled: bool | None = None,
) -> dict[str, Any] | None:
    if role is not None and role not in _VALID_ROLES:
        raise ValueError(f"invalid role: {role!r}")
    if role is None and enabled is None:
        return get_lm_model(conn, name)

    sets: list[str] = []
    params: list[Any] = []
    if role is not None:
        sets.append("role = ?")
        params.append(role)
    if enabled is not None:
        sets.append("enabled = ?")
        params.append(1 if enabled else 0)
    params.append(name)
    cur = conn.execute(
        f"UPDATE lm_models SET {', '.join(sets)} WHERE name = ?",
        params,
    )
    if cur.rowcount == 0:
        return None
    return get_lm_model(conn, name)
