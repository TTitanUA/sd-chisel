# LMStudio Capabilities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace manual `role` field with auto-detected model capabilities (vision, tool_use, reasoning) fetched from LMStudio's native `/api/v1/models` endpoint, merging both LM clients into a single `lmstudio_client.py` and storing the server root URL instead of the OpenAI-compat base URL.

**Architecture:** One unified `lmstudio_client.py` knows the full URL structure — OpenAI-compat calls go to `{server_root}/v1/...`, system calls go to `{server_root}/api/v1/...`. Settings store `lmstudio_url` (server root, e.g. `http://localhost:1234`). The `lm_models` table gains `vision/tool_use/reasoning` boolean columns; `role` is dropped. Capabilities are refreshed from the API on each Refresh; `enabled` is always preserved. Users can manually override capabilities between refreshes.

**Tech Stack:** FastAPI, SQLite, httpx, Pydantic v2, React + TanStack Query v5, TypeScript

---

## File Map

**Created:**
- `backend/app/services/lmstudio_client.py` — unified client (replaces `lm_client.py`)
- `backend/tests/test_lmstudio_client.py` — client unit tests (replaces `test_lm_client*.py`)

**Modified:**
- `backend/migrations/001_init.sql` — schema changes in-place (DB will be re-created)
- `backend/app/storage/settings_repo.py` — URL handling + model CRUD
- `backend/app/models/settings.py` — Pydantic models
- `backend/app/api/settings.py` — refresh + patch endpoints
- `backend/app/api/sessions.py` — validation + client import
- `backend/app/api/chat.py` — validation + client import
- `backend/app/api/prompt.py` — validation + client import
- `backend/app/services/prompt_orchestrator.py` — client import
- `backend/tests/test_settings_repo.py` — rewritten
- `backend/tests/test_settings_api.py` — rewritten
- `backend/tests/test_chat_api.py` — update mocks
- `backend/tests/test_prompt_api.py` — update mocks
- `backend/tests/test_sessions_analyze.py` — update mocks
- `backend/tests/test_prompt_orchestrator.py` — update mocks
- `frontend/src/api/settings.ts` — types + hooks
- `frontend/src/components/organisms/LmStudioSettings.tsx` — capabilities UI
- `frontend/src/components/organisms/LmStudioSettings.module.css` — grid
- `frontend/src/components/organisms/SessionSettingsDrawer.tsx` — hook rename

**Deleted:**
- `backend/app/services/lm_client.py`
- `backend/tests/test_lm_client.py`
- `backend/tests/test_lm_client_chat.py`
- `backend/tests/test_lm_client_complete.py`

---

## Task 1: Update DB Schema

**Files:**
- Modify: `backend/migrations/001_init.sql`

- [ ] **Step 1: Edit the `app_settings` table definition**

Find this block in `001_init.sql`:
```sql
CREATE TABLE app_settings (
  id                 INTEGER PRIMARY KEY CHECK (id = 1),
  lmstudio_base_url  TEXT,
  lmstudio_api_key   TEXT,
  updated_at         INTEGER NOT NULL DEFAULT 0
);
INSERT INTO app_settings (id) VALUES (1);
```

Replace with:
```sql
CREATE TABLE app_settings (
  id               INTEGER PRIMARY KEY CHECK (id = 1),
  lmstudio_url     TEXT,
  lmstudio_api_key TEXT,
  updated_at       INTEGER NOT NULL DEFAULT 0
);
INSERT INTO app_settings (id) VALUES (1);
```

- [ ] **Step 2: Edit the `lm_models` table definition**

Find:
```sql
CREATE TABLE lm_models (
  name        TEXT PRIMARY KEY,
  role        TEXT NOT NULL DEFAULT 'both' CHECK (role IN ('vl','prompt','both')),
  enabled     INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  last_seen   INTEGER NOT NULL
);
```

Replace with:
```sql
CREATE TABLE lm_models (
  name      TEXT PRIMARY KEY,
  enabled   INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
  last_seen INTEGER NOT NULL,
  vision    INTEGER NOT NULL DEFAULT 0 CHECK (vision IN (0,1)),
  tool_use  INTEGER NOT NULL DEFAULT 0 CHECK (tool_use IN (0,1)),
  reasoning INTEGER NOT NULL DEFAULT 0 CHECK (reasoning IN (0,1))
);
```

- [ ] **Step 3: Commit**

```bash
git add backend/migrations/001_init.sql
git commit -m "feat(db): replace role with vision/tool_use/reasoning; rename lmstudio_url"
```

---

## Task 2: Repo — URL Functions

**Files:**
- Modify: `backend/app/storage/settings_repo.py`
- Modify: `backend/tests/test_settings_repo.py`

- [ ] **Step 1: Write failing URL tests**

Replace the URL-related tests in `backend/tests/test_settings_repo.py` (the block from `test_default_lmstudio_settings_are_blank` through `test_set_lmstudio_can_clear_to_null`):

```python
def test_default_lmstudio_settings_are_blank(conn):
    cfg = settings_repo.get_lmstudio(conn)
    assert cfg["lmstudio_url"] is None
    assert cfg["lmstudio_api_key"] is None


def test_set_lmstudio_stores_server_root(conn):
    settings_repo.set_lmstudio(conn, url="http://localhost:1234", api_key="k")
    cfg = settings_repo.get_lmstudio(conn)
    assert cfg["lmstudio_url"] == "http://localhost:1234"
    assert cfg["lmstudio_api_key"] == "k"


def test_set_lmstudio_strips_trailing_slash(conn):
    settings_repo.set_lmstudio(conn, url="http://localhost:1234/", api_key=None)
    assert settings_repo.get_lmstudio(conn)["lmstudio_url"] == "http://localhost:1234"


def test_set_lmstudio_does_not_append_v1(conn):
    settings_repo.set_lmstudio(conn, url="http://localhost:1234", api_key=None)
    assert settings_repo.get_lmstudio(conn)["lmstudio_url"] == "http://localhost:1234"


def test_set_lmstudio_bumps_updated_at(conn):
    before = settings_repo.get_lmstudio(conn)["updated_at"]
    settings_repo.set_lmstudio(conn, url="http://h", api_key=None)
    assert settings_repo.get_lmstudio(conn)["updated_at"] >= before


def test_set_lmstudio_can_clear_to_null(conn):
    settings_repo.set_lmstudio(conn, url="http://h", api_key="k")
    settings_repo.set_lmstudio(conn, url=None, api_key=None)
    cfg = settings_repo.get_lmstudio(conn)
    assert cfg["lmstudio_url"] is None
    assert cfg["lmstudio_api_key"] is None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && uv run pytest tests/test_settings_repo.py -k "lmstudio" -v
```

Expected: multiple FAILED (KeyError `lmstudio_url`, wrong column names)

- [ ] **Step 3: Update URL functions in `settings_repo.py`**

Remove the `ROLE`, `_VALID_ROLES` module-level constants and the `_normalize_base_url` function. Add:

```python
def _normalize_url(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip().rstrip("/")
    return stripped or None
```

Replace `get_lmstudio`:

```python
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
```

Replace `set_lmstudio`:

```python
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
```

Also remove the `from urllib.parse import urlparse` import (no longer needed).

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd backend && uv run pytest tests/test_settings_repo.py -k "lmstudio" -v
```

Expected: all URL tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/storage/settings_repo.py backend/tests/test_settings_repo.py
git commit -m "feat(repo): simplify URL normalization — store server root, no /v1 append"
```

---

## Task 3: Repo — Model CRUD

**Files:**
- Modify: `backend/app/storage/settings_repo.py`
- Modify: `backend/tests/test_settings_repo.py`

- [ ] **Step 1: Write failing model tests**

Replace the model-related tests in `test_settings_repo.py` (from `test_lm_models_upsert_merge_keeps_user_flags` to end of file):

```python
def _make_model(name: str, vision=False, tool_use=False, reasoning=False):
    return {"name": name, "vision": vision, "tool_use": tool_use, "reasoning": reasoning}


def test_upsert_stores_capabilities(conn):
    models = [
        _make_model("qwen-vl", vision=True),
        _make_model("mistral", tool_use=True, reasoning=True),
    ]
    settings_repo.upsert_lm_models(conn, models=models, seen_at=100)
    by_name = {m["name"]: m for m in settings_repo.list_lm_models(conn)}
    assert by_name["qwen-vl"]["vision"] is True
    assert by_name["qwen-vl"]["tool_use"] is False
    assert by_name["qwen-vl"]["enabled"] is True  # default
    assert by_name["mistral"]["tool_use"] is True
    assert by_name["mistral"]["reasoning"] is True


def test_upsert_updates_capabilities_preserves_enabled(conn):
    settings_repo.upsert_lm_models(
        conn, models=[_make_model("m", vision=False)], seen_at=100,
    )
    settings_repo.patch_lm_model(conn, name="m", enabled=False)

    settings_repo.upsert_lm_models(
        conn, models=[_make_model("m", vision=True, tool_use=True)], seen_at=200,
    )
    m = settings_repo.get_lm_model(conn, "m")
    assert m["vision"] is True     # updated from API
    assert m["tool_use"] is True   # updated from API
    assert m["enabled"] is False   # preserved


def test_upsert_keeps_stale_rows_when_model_disappears(conn):
    settings_repo.upsert_lm_models(
        conn,
        models=[_make_model("a"), _make_model("b")],
        seen_at=100,
    )
    settings_repo.upsert_lm_models(conn, models=[_make_model("a")], seen_at=200)
    by_name = {m["name"]: m for m in settings_repo.list_lm_models(conn)}
    assert set(by_name) == {"a", "b"}
    assert by_name["a"]["last_seen"] == 200
    assert by_name["b"]["last_seen"] == 100  # stale but preserved


def test_patch_updates_vision(conn):
    settings_repo.upsert_lm_models(conn, models=[_make_model("m")], seen_at=0)
    settings_repo.patch_lm_model(conn, name="m", vision=True)
    assert settings_repo.get_lm_model(conn, "m")["vision"] is True


def test_patch_updates_enabled(conn):
    settings_repo.upsert_lm_models(conn, models=[_make_model("m")], seen_at=0)
    settings_repo.patch_lm_model(conn, name="m", enabled=False)
    assert settings_repo.get_lm_model(conn, "m")["enabled"] is False


def test_patch_returns_none_for_unknown(conn):
    assert settings_repo.patch_lm_model(conn, name="ghost", enabled=False) is None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && uv run pytest tests/test_settings_repo.py -k "upsert or patch" -v
```

Expected: FAILED (missing `patch_lm_model`, wrong `upsert_lm_models` signature)

- [ ] **Step 3: Update model CRUD functions in `settings_repo.py`**

Add a helper to convert a row dict, then replace the three model functions:

```python
def _model_row(r: sqlite3.Row) -> dict[str, Any]:
    d = dict(r)
    d["enabled"] = bool(d["enabled"])
    d["vision"] = bool(d["vision"])
    d["tool_use"] = bool(d["tool_use"])
    d["reasoning"] = bool(d["reasoning"])
    return d


def list_lm_models(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT name, enabled, last_seen, vision, tool_use, reasoning "
        "FROM lm_models ORDER BY name"
    ).fetchall()
    return [_model_row(r) for r in rows]


def get_lm_model(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT name, enabled, last_seen, vision, tool_use, reasoning "
        "FROM lm_models WHERE name = ?",
        (name,),
    ).fetchone()
    return _model_row(row) if row is not None else None


def upsert_lm_models(
    conn: sqlite3.Connection,
    *,
    models: list[dict[str, Any]],
    seen_at: int | None = None,
) -> None:
    """Insert new models with defaults; update capabilities + last_seen on conflict.

    Never touches `enabled` on conflict — preserves the user's choice.
    Models absent from the refresh remain in the cache with stale last_seen.
    """
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
) -> dict[str, Any] | None:
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
    if not sets:
        return get_lm_model(conn, name)
    params.append(name)
    cur = conn.execute(
        f"UPDATE lm_models SET {', '.join(sets)} WHERE name = ?", params,
    )
    if cur.rowcount == 0:
        return None
    return get_lm_model(conn, name)
```

Also delete the old `update_lm_model` function entirely.

- [ ] **Step 4: Run all repo tests**

```bash
cd backend && uv run pytest tests/test_settings_repo.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/storage/settings_repo.py backend/tests/test_settings_repo.py
git commit -m "feat(repo): replace role with capabilities; add patch_lm_model"
```

---

## Task 4: Pydantic Models

**Files:**
- Modify: `backend/app/models/settings.py`

- [ ] **Step 1: Rewrite `settings.py`**

Replace the entire file content:

```python
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LmStudioConfig(StrictModel):
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=500)


class LmStudioConfigOut(StrictModel):
    base_url: str | None
    api_key: str | None
    configured: bool
    updated_at: int


class LmModelOut(StrictModel):
    name: str
    vision: bool
    tool_use: bool
    reasoning: bool
    enabled: bool
    last_seen: int


class LmModelsOut(StrictModel):
    models: list[LmModelOut]


class LmModelPatch(StrictModel):
    vision: bool | None = None
    tool_use: bool | None = None
    reasoning: bool | None = None
    enabled: bool | None = None
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/models/settings.py
git commit -m "feat(models): replace role with vision/tool_use/reasoning in LmModel types"
```

---

## Task 5: Unified LMStudio Client

**Files:**
- Create: `backend/app/services/lmstudio_client.py`
- Create: `backend/tests/test_lmstudio_client.py`
- Delete: `backend/app/services/lm_client.py`
- Delete: `backend/tests/test_lm_client.py`
- Delete: `backend/tests/test_lm_client_chat.py`
- Delete: `backend/tests/test_lm_client_complete.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_lmstudio_client.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

from app.services import lmstudio_client

ENDPOINT = {"server_root": "http://localhost:1234", "api_key": None}
ENDPOINT_WITH_KEY = {"server_root": "http://localhost:1234", "api_key": "lm-key"}


def _make_transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _models_body(items: list[dict]) -> dict:
    return {"data": items}


def _llm_item(name: str, vision=False, tool_use=False, reasoning_opts=None) -> dict:
    caps: dict[str, Any] = {"vision": vision, "trained_for_tool_use": tool_use}
    if reasoning_opts is not None:
        caps["reasoning"] = {"allowed_options": reasoning_opts, "default": reasoning_opts[0]}
    return {"id": name, "type": "llm", "capabilities": caps}


def _chat_response(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}]
        },
    )


# --- list_models ---

def test_list_models_hits_api_v1_models_endpoint():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=_models_body([_llm_item("m")]))

    lmstudio_client.list_models(endpoint=ENDPOINT, transport=_make_transport(handler))
    assert captured["url"] == "http://localhost:1234/api/v1/models"


def test_list_models_returns_capabilities():
    items = [
        _llm_item("qwen-vl", vision=True),
        _llm_item("mistral", tool_use=True, reasoning_opts=["disabled", "enabled"]),
    ]

    def handler(r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_models_body(items))

    models = lmstudio_client.list_models(endpoint=ENDPOINT, transport=_make_transport(handler))
    by_name = {m.name: m for m in models}

    assert by_name["qwen-vl"].vision is True
    assert by_name["qwen-vl"].tool_use is False
    assert by_name["qwen-vl"].reasoning is False

    assert by_name["mistral"].vision is False
    assert by_name["mistral"].tool_use is True
    assert by_name["mistral"].reasoning is True


def test_list_models_filters_out_embeddings():
    items = [
        {"id": "bert-embed", "type": "embedding"},
        _llm_item("llama"),
    ]

    def handler(r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_models_body(items))

    models = lmstudio_client.list_models(endpoint=ENDPOINT, transport=_make_transport(handler))
    assert len(models) == 1
    assert models[0].name == "llama"


def test_list_models_handles_missing_capabilities():
    items = [{"id": "llama", "type": "llm"}]

    def handler(r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_models_body(items))

    models = lmstudio_client.list_models(endpoint=ENDPOINT, transport=_make_transport(handler))
    m = models[0]
    assert m.vision is False
    assert m.tool_use is False
    assert m.reasoning is False


def test_list_models_sends_auth_header():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=_models_body([]))

    lmstudio_client.list_models(endpoint=ENDPOINT_WITH_KEY, transport=_make_transport(handler))
    assert captured["auth"] == "Bearer lm-key"


def test_list_models_raises_on_non_2xx():
    transport = _make_transport(lambda r: httpx.Response(503, text="busy"))
    with pytest.raises(lmstudio_client.LmError) as exc:
        lmstudio_client.list_models(endpoint=ENDPOINT, transport=transport)
    assert exc.value.kind == "upstream"


def test_list_models_raises_on_timeout():
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("nope")

    with pytest.raises(lmstudio_client.LmError) as exc:
        lmstudio_client.list_models(endpoint=ENDPOINT, transport=_make_transport(handler))
    assert exc.value.kind == "timeout"


# --- unload_model ---

def test_unload_model_hits_correct_endpoint():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"instance_id": "inst-1"})

    lmstudio_client.unload_model(
        endpoint=ENDPOINT, instance_id="inst-1", transport=_make_transport(handler),
    )
    assert captured["url"] == "http://localhost:1234/api/v1/models/unload"
    assert captured["body"] == {"instance_id": "inst-1"}


# --- analyze_image ---

def test_analyze_image_sends_to_v1_chat_completions():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return _chat_response("a moody street")

    out = lmstudio_client.analyze_image(
        endpoint=ENDPOINT,
        model="qwen-vl",
        image_bytes=b"\x89PNG_fake",
        content_type="image/png",
        transport=_make_transport(handler),
    )
    assert out == "a moody street"
    assert captured["url"] == "http://localhost:1234/v1/chat/completions"
    assert captured["body"]["model"] == "qwen-vl"
    parts = captured["body"]["messages"][-1]["content"]
    assert any(p.get("type") == "image_url" for p in parts)


# --- chat_complete ---

def test_chat_complete_sends_to_v1_chat_completions():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return _chat_response("hello")

    out = lmstudio_client.chat_complete(
        endpoint=ENDPOINT,
        model="mistral",
        messages=[{"role": "user", "content": "hi"}],
        transport=_make_transport(handler),
    )
    assert out == "hello"
    assert captured["url"] == "http://localhost:1234/v1/chat/completions"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && uv run pytest tests/test_lmstudio_client.py -v
```

Expected: FAILED with `ModuleNotFoundError: No module named 'app.services.lmstudio_client'`

- [ ] **Step 3: Create `lmstudio_client.py`**

Create `backend/app/services/lmstudio_client.py`:

```python
"""Unified LMStudio client.

Handles both OpenAI-compat endpoints ({server_root}/v1/...) and
LMStudio-native system endpoints ({server_root}/api/v1/...).

`endpoint` shape: {"server_root": str, "api_key": str | None}
"""
from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal

import httpx

DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=5.0)
LIST_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
CHAT_TIMEOUT = httpx.Timeout(120.0, connect=5.0, read=120.0)

VL_SYSTEM_PROMPT = (
    "You describe images in terms useful for image-to-image generation. "
    "Be concise and concrete. Cover composition, subjects/objects, style, "
    "lighting, palette, and mood. Avoid speculation; do not invent text. "
    "Output a single paragraph of plain prose, no lists, no preamble."
)


@dataclass
class LmsModel:
    name: str
    vision: bool
    tool_use: bool
    reasoning: bool


class LmError(Exception):
    def __init__(self, kind: Literal["upstream", "timeout", "shape", "config"], detail: str) -> None:
        super().__init__(f"LmError({kind}): {detail}")
        self.kind = kind
        self.detail = detail


def _resolve(endpoint: dict[str, Any]) -> tuple[str, dict[str, str]]:
    server_root = str(endpoint.get("server_root") or "").strip().rstrip("/")
    if not server_root:
        raise LmError("config", "lmstudio server URL is not configured")
    headers = {"Content-Type": "application/json"}
    api_key = endpoint.get("api_key") or None
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return server_root, headers


def _request(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    json: dict[str, Any] | None,
    transport: httpx.BaseTransport | None,
    timeout: httpx.Timeout,
) -> httpx.Response:
    try:
        with httpx.Client(transport=transport, timeout=timeout) as client:
            return client.request(method, url, headers=headers, json=json)
    except httpx.TimeoutException as exc:
        raise LmError("timeout", str(exc)) from exc
    except httpx.HTTPError as exc:
        raise LmError("upstream", str(exc)) from exc


# ---------------------------------------------------------------------------
# System methods (LMStudio-native /api/v1/...)
# ---------------------------------------------------------------------------

def list_models(
    *,
    endpoint: dict[str, Any],
    transport: httpx.BaseTransport | None = None,
) -> list[LmsModel]:
    server_root, headers = _resolve(endpoint)
    resp = _request(
        "GET", f"{server_root}/api/v1/models",
        headers=headers, json=None, transport=transport, timeout=LIST_TIMEOUT,
    )
    if resp.status_code >= 400:
        raise LmError("upstream", f"{resp.status_code}: {resp.text[:200]}")
    try:
        body = resp.json()
        items = body["data"]
    except (ValueError, KeyError, TypeError) as exc:
        raise LmError("shape", f"unexpected /api/v1/models body: {exc}") from exc

    models: list[LmsModel] = []
    for item in items:
        if item.get("type") != "llm":
            continue
        caps = item.get("capabilities") or {}
        reasoning_obj = caps.get("reasoning") or {}
        models.append(LmsModel(
            name=item["id"],
            vision=bool(caps.get("vision", False)),
            tool_use=bool(caps.get("trained_for_tool_use", False)),
            reasoning=bool(reasoning_obj.get("allowed_options")),
        ))
    return sorted(models, key=lambda m: m.name)


def unload_model(
    *,
    endpoint: dict[str, Any],
    instance_id: str,
    transport: httpx.BaseTransport | None = None,
) -> None:
    server_root, headers = _resolve(endpoint)
    resp = _request(
        "POST", f"{server_root}/api/v1/models/unload",
        headers=headers, json={"instance_id": instance_id},
        transport=transport, timeout=DEFAULT_TIMEOUT,
    )
    if resp.status_code >= 400:
        raise LmError("upstream", f"{resp.status_code}: {resp.text[:200]}")


# ---------------------------------------------------------------------------
# OpenAI-compat methods ({server_root}/v1/...)
# ---------------------------------------------------------------------------

def analyze_image(
    *,
    endpoint: dict[str, Any],
    model: str,
    image_bytes: bytes,
    content_type: str,
    transport: httpx.BaseTransport | None = None,
) -> str:
    if not model.strip():
        raise LmError("config", "model is required")
    server_root, headers = _resolve(endpoint)
    b64 = base64.b64encode(image_bytes).decode("ascii")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": VL_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this image for i2i prompt building."},
                    {"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{b64}"}},
                ],
            },
        ],
        "stream": False,
    }
    resp = _request(
        "POST", f"{server_root}/v1/chat/completions",
        headers=headers, json=payload, transport=transport, timeout=DEFAULT_TIMEOUT,
    )
    if resp.status_code >= 400:
        raise LmError("upstream", f"{resp.status_code}: {resp.text[:200]}")
    try:
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LmError("shape", f"unexpected response body: {exc}") from exc
    if not isinstance(content, str) or not content.strip():
        raise LmError("shape", "empty content from VL endpoint")
    return content.strip()


def chat_stream(
    *,
    endpoint: dict[str, Any],
    model: str,
    messages: list[dict[str, Any]],
    transport: httpx.BaseTransport | None = None,
) -> Iterator[str]:
    if not model.strip():
        raise LmError("config", "model is required")
    if not messages:
        raise LmError("config", "messages must not be empty")
    server_root, headers = _resolve(endpoint)
    payload = {"model": model, "messages": messages, "stream": True}
    try:
        with httpx.Client(transport=transport, timeout=CHAT_TIMEOUT) as client:
            with client.stream(
                "POST", f"{server_root}/v1/chat/completions",
                headers=headers, json=payload,
            ) as resp:
                if resp.status_code >= 400:
                    body = resp.read().decode("utf-8", errors="replace")
                    raise LmError("upstream", f"{resp.status_code}: {body[:200]}")
                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if data == "[DONE]":
                        return
                    try:
                        chunk = json.loads(data)
                    except ValueError:
                        continue
                    try:
                        delta = chunk["choices"][0].get("delta") or {}
                    except (KeyError, IndexError, TypeError):
                        continue
                    content = delta.get("content")
                    if isinstance(content, str) and content:
                        yield content
    except httpx.TimeoutException as exc:
        raise LmError("timeout", str(exc)) from exc
    except httpx.HTTPError as exc:
        raise LmError("upstream", str(exc)) from exc


def chat_complete(
    *,
    endpoint: dict[str, Any],
    model: str,
    messages: list[dict[str, Any]],
    response_format: dict[str, Any] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> str:
    if not model.strip():
        raise LmError("config", "model is required")
    if not messages:
        raise LmError("config", "messages must not be empty")
    server_root, headers = _resolve(endpoint)
    payload: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
    if response_format is not None:
        payload["response_format"] = response_format
    resp = _request(
        "POST", f"{server_root}/v1/chat/completions",
        headers=headers, json=payload, transport=transport, timeout=CHAT_TIMEOUT,
    )
    if resp.status_code >= 400:
        raise LmError("upstream", f"{resp.status_code}: {resp.text[:200]}")
    try:
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LmError("shape", f"unexpected response body: {exc}") from exc
    if content is None:
        raise LmError("shape", "content is null — model may have returned a tool call")
    if not isinstance(content, str) or not content.strip():
        raise LmError("shape", "empty content from chat endpoint")
    return content.strip()
```

- [ ] **Step 4: Run client tests**

```bash
cd backend && uv run pytest tests/test_lmstudio_client.py -v
```

Expected: all PASS

- [ ] **Step 5: Delete old client files**

```bash
rm backend/app/services/lm_client.py
rm backend/tests/test_lm_client.py
rm backend/tests/test_lm_client_chat.py
rm backend/tests/test_lm_client_complete.py
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/lmstudio_client.py backend/tests/test_lmstudio_client.py
git add -u  # stage deletions
git commit -m "feat(client): unified lmstudio_client.py with system + chat methods"
```

---

## Task 6: API — Settings

**Files:**
- Modify: `backend/app/api/settings.py`
- Modify: `backend/tests/test_settings_api.py`

- [ ] **Step 1: Rewrite `test_settings_api.py`**

Replace the entire file:

```python
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_conn
from app.main import app
from app.services import lmstudio_client
from app.storage import db as db_mod
from app.storage.migrations import apply_pending


@pytest.fixture
def conn(tmp_path):
    c = db_mod.connect(tmp_path / "s.db")
    apply_pending(c, Path(__file__).parent.parent / "migrations")
    yield c
    c.close()


@pytest.fixture
def client(conn):
    app.dependency_overrides[get_conn] = lambda: conn
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_get_lmstudio_returns_blank_by_default(client):
    body = client.get("/api/settings/lmstudio").json()
    assert body == {
        "base_url": None,
        "api_key": None,
        "configured": False,
        "updated_at": body["updated_at"],
    }


def test_put_lmstudio_persists(client):
    resp = client.put(
        "/api/settings/lmstudio",
        json={"base_url": "http://localhost:1234/", "api_key": "k"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["base_url"] == "http://localhost:1234"  # trailing slash stripped
    assert body["configured"] is True

    again = client.get("/api/settings/lmstudio").json()
    assert again["base_url"] == "http://localhost:1234"


def test_refresh_409_when_unconfigured(client):
    assert client.post("/api/settings/lmstudio/refresh").status_code == 409


def _fake_model(name: str, vision=False, tool_use=False, reasoning=False):
    return lmstudio_client.LmsModel(
        name=name, vision=vision, tool_use=tool_use, reasoning=reasoning,
    )


def test_refresh_populates_models(client, monkeypatch):
    client.put("/api/settings/lmstudio", json={"base_url": "http://h", "api_key": None})

    captured: dict[str, Any] = {}

    def fake_list(*, endpoint, transport=None):
        captured["endpoint"] = endpoint
        return [
            _fake_model("qwen-vl", vision=True),
            _fake_model("mistral", tool_use=True, reasoning=True),
        ]

    monkeypatch.setattr(lmstudio_client, "list_models", fake_list)

    body = client.post("/api/settings/lmstudio/refresh").json()
    by_name = {m["name"]: m for m in body["models"]}
    assert by_name["qwen-vl"]["vision"] is True
    assert by_name["qwen-vl"]["tool_use"] is False
    assert by_name["qwen-vl"]["enabled"] is True
    assert by_name["mistral"]["tool_use"] is True
    assert by_name["mistral"]["reasoning"] is True
    assert captured["endpoint"] == {"server_root": "http://h", "api_key": None}


def test_refresh_502_on_upstream_error(client, monkeypatch):
    client.put("/api/settings/lmstudio", json={"base_url": "http://h", "api_key": None})

    def fake(*, endpoint, transport=None):
        raise lmstudio_client.LmError("upstream", "503: busy")

    monkeypatch.setattr(lmstudio_client, "list_models", fake)
    assert client.post("/api/settings/lmstudio/refresh").status_code == 502


def test_refresh_504_on_timeout(client, monkeypatch):
    client.put("/api/settings/lmstudio", json={"base_url": "http://h", "api_key": None})

    def fake(*, endpoint, transport=None):
        raise lmstudio_client.LmError("timeout", "ConnectTimeout")

    monkeypatch.setattr(lmstudio_client, "list_models", fake)
    assert client.post("/api/settings/lmstudio/refresh").status_code == 504


def test_patch_lm_model_capabilities(client, monkeypatch):
    client.put("/api/settings/lmstudio", json={"base_url": "http://h", "api_key": None})
    monkeypatch.setattr(lmstudio_client, "list_models", lambda **_: [_fake_model("m", vision=True)])
    client.post("/api/settings/lmstudio/refresh")

    resp = client.patch(
        "/api/settings/lmstudio/models/m",
        json={"vision": False, "enabled": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["vision"] is False
    assert body["enabled"] is False
    assert body["tool_use"] is False


def test_patch_lm_model_404_for_unknown(client):
    resp = client.patch("/api/settings/lmstudio/models/ghost", json={"enabled": False})
    assert resp.status_code == 404


def test_refresh_updates_capabilities_preserves_enabled(client, monkeypatch):
    client.put("/api/settings/lmstudio", json={"base_url": "http://h", "api_key": None})
    monkeypatch.setattr(lmstudio_client, "list_models", lambda **_: [_fake_model("m")])
    client.post("/api/settings/lmstudio/refresh")
    client.patch("/api/settings/lmstudio/models/m", json={"enabled": False})

    monkeypatch.setattr(
        lmstudio_client, "list_models", lambda **_: [_fake_model("m", vision=True)],
    )
    body = client.post("/api/settings/lmstudio/refresh").json()
    [m] = body["models"]
    assert m["vision"] is True   # updated from API
    assert m["enabled"] is False  # preserved
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && uv run pytest tests/test_settings_api.py -v
```

Expected: FAILED (import errors, wrong field names)

- [ ] **Step 3: Rewrite `api/settings.py`**

Replace the entire file:

```python
from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_conn
from app.models.settings import (
    LmModelOut,
    LmModelPatch,
    LmModelsOut,
    LmStudioConfig,
    LmStudioConfigOut,
)
from app.services import lmstudio_client
from app.storage import settings_repo

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

router = APIRouter(tags=["settings"])


def _to_config_out(row: dict) -> dict:
    return {
        "base_url": row["lmstudio_url"],
        "api_key": row["lmstudio_api_key"],
        "configured": bool(row["lmstudio_url"]),
        "updated_at": row["updated_at"],
    }


def _endpoint_from_row(row: dict) -> dict:
    return {
        "server_root": row["lmstudio_url"],
        "api_key": row["lmstudio_api_key"],
    }


def _vl_translate(exc: lmstudio_client.LmError) -> HTTPException:
    if exc.kind == "timeout":
        return HTTPException(status_code=504, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


@router.get("/api/settings/lmstudio", response_model=LmStudioConfigOut)
def get_lmstudio(conn: Conn) -> dict:
    return _to_config_out(settings_repo.get_lmstudio(conn))


@router.put("/api/settings/lmstudio", response_model=LmStudioConfigOut)
def put_lmstudio(body: LmStudioConfig, conn: Conn) -> dict:
    return _to_config_out(
        settings_repo.set_lmstudio(conn, url=body.base_url, api_key=body.api_key),
    )


@router.post("/api/settings/lmstudio/refresh", response_model=LmModelsOut)
def refresh_lmstudio_models(conn: Conn) -> dict:
    cfg = settings_repo.get_lmstudio(conn)
    if not cfg["lmstudio_url"]:
        raise HTTPException(status_code=409, detail="LMStudio URL is not configured")
    try:
        lms_models = lmstudio_client.list_models(endpoint=_endpoint_from_row(cfg))
    except lmstudio_client.LmError as exc:
        raise _vl_translate(exc) from exc
    settings_repo.upsert_lm_models(
        conn,
        models=[
            {"name": m.name, "vision": m.vision, "tool_use": m.tool_use, "reasoning": m.reasoning}
            for m in lms_models
        ],
    )
    return {"models": settings_repo.list_lm_models(conn)}


@router.get("/api/settings/lmstudio/models", response_model=LmModelsOut)
def list_lm_models(conn: Conn) -> dict:
    return {"models": settings_repo.list_lm_models(conn)}


@router.patch("/api/settings/lmstudio/models/{name}", response_model=LmModelOut)
def patch_lm_model(name: str, body: LmModelPatch, conn: Conn) -> dict:
    if all(v is None for v in [body.vision, body.tool_use, body.reasoning, body.enabled]):
        raise HTTPException(status_code=422, detail="provide at least one field")
    row = settings_repo.patch_lm_model(
        conn, name=name,
        vision=body.vision, tool_use=body.tool_use,
        reasoning=body.reasoning, enabled=body.enabled,
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown model: {name}")
    return row
```

- [ ] **Step 4: Run settings API tests**

```bash
cd backend && uv run pytest tests/test_settings_api.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/settings.py backend/tests/test_settings_api.py
git commit -m "feat(api): settings — use lmstudio_client, capabilities in refresh/patch"
```

---

## Task 7: API — Sessions, Chat, Prompt, Orchestrator

**Files:**
- Modify: `backend/app/api/sessions.py`
- Modify: `backend/app/api/chat.py`
- Modify: `backend/app/api/prompt.py`
- Modify: `backend/app/services/prompt_orchestrator.py`

- [ ] **Step 1: Update `api/sessions.py`**

Change the import at the top:
```python
# Remove:
from app.services import lm_client
# Add:
from app.services import lmstudio_client
```

Replace `_validated_vl_model`:
```python
def _validated_vl_model(conn: sqlite3.Connection, name: str | None) -> str:
    if not name:
        raise HTTPException(
            status_code=409,
            detail="session has no vl_model_name selected",
        )
    row = settings_repo.get_lm_model(conn, name)
    if row is None or not row["enabled"] or not row["vision"]:
        raise HTTPException(
            status_code=409,
            detail=f"vl_model_name {name!r} is not enabled or does not support vision",
        )
    return name
```

In `analyze_source`, replace the `cfg["lmstudio_base_url"]` check and client call:
```python
    cfg = settings_repo.get_lmstudio(conn)
    if not cfg["lmstudio_url"]:
        raise HTTPException(
            status_code=409, detail="LMStudio URL is not configured",
        )
    model = _validated_vl_model(conn, row.get("vl_model_name"))
    # ... image loading code unchanged ...
    try:
        summary = lmstudio_client.analyze_image(
            endpoint={
                "server_root": cfg["lmstudio_url"],
                "api_key": cfg["lmstudio_api_key"],
            },
            model=model,
            image_bytes=image_bytes,
            content_type=content_type,
        )
    except lmstudio_client.LmError as exc:
        if exc.kind == "timeout":
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
```

- [ ] **Step 2: Update `api/chat.py`**

Change the import:
```python
# Remove:
from app.services import lm_client
# Add:
from app.services import lmstudio_client
```

Replace `_validated_prompt_model` (now just checks enabled):
```python
def _validated_prompt_model(conn: sqlite3.Connection, name: str | None) -> str:
    if not name:
        raise HTTPException(
            status_code=409, detail="session has no prompt_model_name selected",
        )
    row = settings_repo.get_lm_model(conn, name)
    if row is None or not row["enabled"]:
        raise HTTPException(
            status_code=409,
            detail=f"prompt_model_name {name!r} is not enabled",
        )
    return name
```

In `chat`, replace the config check and endpoint dict:
```python
    cfg = settings_repo.get_lmstudio(conn)
    if not cfg["lmstudio_url"]:
        raise HTTPException(status_code=409, detail="LMStudio URL is not configured")
    model = _validated_prompt_model(conn, session_row.get("prompt_model_name"))
    payload_messages = _build_payload_messages(conn, session_row, body.content)
    endpoint = {
        "server_root": cfg["lmstudio_url"],
        "api_key": cfg["lmstudio_api_key"],
    }
```

In `gen()`, replace `lm_client` with `lmstudio_client`:
```python
    def gen():
        accumulated: list[str] = []
        try:
            for chunk in lmstudio_client.chat_stream(
                endpoint=endpoint, model=model, messages=payload_messages,
            ):
                accumulated.append(chunk)
                yield _sse({"type": "delta", "content": chunk})
        except lmstudio_client.LmError as exc:
            yield _sse({"type": "error", "detail": str(exc)})
            return
        # rest of gen() unchanged
```

- [ ] **Step 3: Update `api/prompt.py`**

Change the import:
```python
# Remove:
from app.services import lm_client, prompt_orchestrator
# Add:
from app.services import lmstudio_client, prompt_orchestrator
```

Replace `_validated_prompt_model` (same as chat.py):
```python
def _validated_prompt_model(conn: sqlite3.Connection, name: str | None) -> str:
    if not name:
        raise HTTPException(
            status_code=409, detail="session has no prompt_model_name selected",
        )
    row = settings_repo.get_lm_model(conn, name)
    if row is None or not row["enabled"]:
        raise HTTPException(
            status_code=409,
            detail=f"prompt_model_name {name!r} is not enabled",
        )
    return name
```

In `generate_prompt`, replace the config check and endpoint dict:
```python
    cfg = settings_repo.get_lmstudio(conn)
    if not cfg["lmstudio_url"]:
        raise HTTPException(
            status_code=409, detail="LMStudio URL is not configured",
        )
    model = _validated_prompt_model(conn, session.get("prompt_model_name"))
    endpoint = {
        "server_root": cfg["lmstudio_url"],
        "api_key": cfg["lmstudio_api_key"],
    }
    try:
        out = prompt_orchestrator.generate(
            conn,
            session_id=session_id,
            endpoint=endpoint,
            prompt_model=model,
        )
    except prompt_orchestrator.PreconditionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except lmstudio_client.LmError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
```

- [ ] **Step 4: Update `prompt_orchestrator.py`**

Change the import (one line):
```python
# Remove:
from app.services import lm_client, prompt_builder, retriever
# Add:
from app.services import lmstudio_client, prompt_builder, retriever
```

Then replace every `lm_client.` reference in the file with `lmstudio_client.`. The function signatures and logic stay exactly the same — only the module name changes.

- [ ] **Step 5: Run tests to check for import errors**

```bash
cd backend && uv run pytest tests/ -v --ignore=tests/test_chat_api.py --ignore=tests/test_prompt_api.py --ignore=tests/test_sessions_analyze.py --ignore=tests/test_prompt_orchestrator.py 2>&1 | tail -20
```

Expected: no import errors, all non-ignored tests pass

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/sessions.py backend/app/api/chat.py backend/app/api/prompt.py backend/app/services/prompt_orchestrator.py
git commit -m "feat(api): migrate sessions/chat/prompt to lmstudio_client; vision-based validation"
```

---

## Task 8: Update Remaining Test Files

**Files:**
- Modify: `backend/tests/test_chat_api.py`
- Modify: `backend/tests/test_prompt_api.py`
- Modify: `backend/tests/test_sessions_analyze.py`
- Modify: `backend/tests/test_prompt_orchestrator.py`

The pattern is the same across all four files:

- [ ] **Step 1: Globally replace `lm_client` → `lmstudio_client` in each file**

```bash
# In each file, the import changes from:
from app.services import lm_client
# to:
from app.services import lmstudio_client

# And every attribute access:
lm_client.chat_stream  →  lmstudio_client.chat_stream
lm_client.chat_complete  →  lmstudio_client.chat_complete
lm_client.analyze_image  →  lmstudio_client.analyze_image
lm_client.LmError  →  lmstudio_client.LmError
lm_client.list_models  →  lmstudio_client.list_models
```

Use sed or do it manually — every occurrence of `lm_client` becomes `lmstudio_client`.

- [ ] **Step 2: Fix `list_models` mocks — return type changed**

In any test that has:
```python
monkeypatch.setattr(lmstudio_client, "list_models", lambda **_: ["model-a", "model-b"])
```

Replace with (returns `list[LmsModel]` now):
```python
monkeypatch.setattr(
    lmstudio_client, "list_models",
    lambda **_: [
        lmstudio_client.LmsModel(name="model-a", vision=True, tool_use=False, reasoning=False),
        lmstudio_client.LmsModel(name="model-b", vision=False, tool_use=True, reasoning=False),
    ],
)
```

Adjust the model names and capabilities to match what each specific test expects (use `vision=True` for models used as VL models, any values for prompt models).

- [ ] **Step 3: Fix endpoint dict assertions**

Any assertion like:
```python
assert captured["endpoint"] == {"base_url": "...", "api_key": ...}
```

Changes to:
```python
assert captured["endpoint"] == {"server_root": "...", "api_key": ...}
```

And any test that calls `client.put("/api/settings/lmstudio", json={"base_url": "http://h/v1", ...})` should be updated to:
```python
client.put("/api/settings/lmstudio", json={"base_url": "http://h", "api_key": None})
```
(server root, no `/v1` suffix)

- [ ] **Step 4: Fix role-related assertions**

Any assertion like `assert m["role"] == "prompt"` or validation error messages mentioning "wrong role" need to be removed or updated. The prompt model validation now only checks `enabled`, not role.

Any test that sets up a session with a prompt model should ensure the model has `enabled=True` (the default after upsert, so no change needed unless explicitly testing role rejection).

- [ ] **Step 5: Run all tests**

```bash
cd backend && uv run pytest tests/ -v 2>&1 | tail -30
```

Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/tests/
git commit -m "test: migrate all test mocks from lm_client to lmstudio_client"
```

---

## Task 9: Frontend

**Files:**
- Modify: `frontend/src/api/settings.ts`
- Modify: `frontend/src/components/organisms/LmStudioSettings.tsx`
- Modify: `frontend/src/components/organisms/LmStudioSettings.module.css`
- Modify: `frontend/src/components/organisms/SessionSettingsDrawer.tsx`

- [ ] **Step 1: Update `api/settings.ts`**

Replace the type definitions and filter hook:

```typescript
// Remove LmRole type entirely.
// Replace LmModel:
export type LmModel = {
  name: string;
  vision: boolean;
  tool_use: boolean;
  reasoning: boolean;
  enabled: boolean;
  last_seen: number;
};

// Keep settingsKeys, LmStudioConfig, useLmStudioConfig, useLmModels,
// useSettingsInvalidation, useRefreshLmStudio unchanged.

// Replace patchModel signature:
export const settingsApi = {
  // ... existing methods unchanged except patchModel:
  patchModel: (
    name: string,
    patch: { vision?: boolean; tool_use?: boolean; reasoning?: boolean; enabled?: boolean },
  ) =>
    apiFetch<LmModel>(`/api/settings/lmstudio/models/${encodeURIComponent(name)}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
};

// Remove useLmModelsByRole. Add:
export function useLmModelsForVision() {
  const all = useLmModels();
  return {
    ...all,
    data: (all.data ?? []).filter((m) => m.enabled && m.vision),
  };
}

export function useLmModelsForChat() {
  const all = useLmModels();
  return {
    ...all,
    data: (all.data ?? []).filter((m) => m.enabled),
  };
}
```

- [ ] **Step 2: Update `SessionSettingsDrawer.tsx`**

Change the import:
```typescript
// Remove:
import { useLmModelsByRole } from "@/api/settings";
// Add:
import { useLmModelsForVision, useLmModelsForChat } from "@/api/settings";
```

Change the hook calls:
```typescript
// Remove:
const vlChoices = useLmModelsByRole("vl");
const promptChoices = useLmModelsByRole("prompt");
// Add:
const vlChoices = useLmModelsForVision();
const promptChoices = useLmModelsForChat();
```

- [ ] **Step 3: Update `LmStudioSettings.tsx` — URL default and capabilities table**

Change the default URL constant:
```typescript
const LM_STUDIO_DEFAULT_URL = "http://localhost:1234";
```

Replace the model table section. The current "Role" column (with `<select>`) becomes a "Capabilities" column with three inline checkboxes:

```tsx
{/* In the table header row, replace: */}
<div className={styles.headCell}>Role</div>
{/* With: */}
<div className={styles.headCell}>Capabilities</div>

{/* In the model rows, replace the Role cell: */}
{/* OLD: */}
<div>
  <select
    className={styles.modelRoleSelect}
    value={m.role}
    onChange={(e) =>
      patch.mutate({ name: m.name, role: e.currentTarget.value as LmRole })
    }
  >
    {ROLES.map((r) => (
      <option key={r} value={r}>{r}</option>
    ))}
  </select>
</div>

{/* NEW: */}
<div className={styles.capabilities}>
  {(["vision", "tool_use", "reasoning"] as const).map((cap) => (
    <label key={cap} className={styles.capLabel}>
      <input
        type="checkbox"
        checked={m[cap]}
        onChange={(e) =>
          patch.mutate({ name: m.name, [cap]: e.currentTarget.checked })
        }
      />
      {cap === "tool_use" ? "tools" : cap}
    </label>
  ))}
</div>
```

Also remove `const ROLES: LmRole[] = ["vl", "prompt", "both"]` and the `LmRole` import from `@/api/settings`.

Update the `patch.mutate` call type: remove `role` from the mutation args (it no longer exists). The patch mutation already accepts any object — no type change needed in the mutation definition itself since `settingsApi.patchModel` now accepts the new fields.

Also update the `TextInput` placeholder:
```tsx
<TextInput
  label="Base URL"
  placeholder="http://localhost:1234"
  value={baseUrl}
  onChange={(e) => setBaseUrl(e.currentTarget.value)}
/>
```

- [ ] **Step 4: Update `LmStudioSettings.module.css`**

Remove `.modelRoleSelect`. Update the grid to fit the new capabilities column (it's wider than the old role select):

```css
.modelTable {
  display: grid;
  grid-template-columns: 1fr 220px 90px 110px;
  /* was: 1fr 130px 90px 110px */
  ...
}
```

Add styles for the capabilities cell:
```css
.capabilities {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.capLabel {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: var(--text-xs);
  color: var(--text-muted);
  cursor: pointer;
  white-space: nowrap;
}
```

- [ ] **Step 5: Verify TypeScript compiles**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/settings.ts frontend/src/components/organisms/
git commit -m "feat(frontend): replace role with capabilities — vision/tools/reasoning checkboxes"
```

---

## Task 10: DB Reset + Smoke Test

- [ ] **Step 1: Stop the backend if running**

Kill any running `uvicorn` process.

- [ ] **Step 2: Drop the existing database**

```bash
rm -f backend/data/app.db
```

- [ ] **Step 3: Re-initialize the database**

```bash
cd backend && uv run db-init
```

Expected output: something like `Applied migration: 001_init.sql`

- [ ] **Step 4: Run full test suite**

```bash
cd backend && uv run pytest tests/ -v 2>&1 | tail -20
```

Expected: all PASS, no references to `lm_client` anywhere

- [ ] **Step 5: Start backend + frontend**

```bash
# In one terminal:
cd backend && uv run uvicorn app.main:app --reload

# In another terminal:
cd frontend && pnpm dev
```

- [ ] **Step 6: Open the settings page**

Navigate to `http://localhost:5173/settings/lmstudio`.

Verify:
- "Use default" button fills `http://localhost:1234` (no `/v1`)
- Placeholder shows `http://localhost:1234`

- [ ] **Step 7: Enter server URL and save**

Enter `http://localhost:1234` (or your LMStudio URL), click "Save endpoint".

Verify the config saves and `configured` turns true in the header indicator.

- [ ] **Step 8: Press Refresh**

Click "Refresh from LMStudio".

Verify:
- Model list appears with Vision / Tools / Reasoning checkboxes auto-populated from LMStudio
- Embedding models are absent from the list

- [ ] **Step 9: Manual override test**

Uncheck Vision on a model that has it, save. Verify the unchecked state persists. Press Refresh again — capability resets to the API-reported value.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "chore: drop and re-init DB with new lm_models schema"
```
