# Slice 3 — Settings + LMStudio + VL analyze-source — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make LMStudio a global, configurable thing — one endpoint, a refreshable list of models, per-session selection of which VL/prompt model to use — and on top of that wire up the single VL `analyze-source` call so a user can press *Analyze* on a source image and get a persisted summary.

**Architecture:** LMStudio endpoint moves from per-session JSON columns to a singleton `app_settings` row. A `lm_models` cache table stores models seen during *Refresh* with user-toggleable `enabled` and `role` (`vl` / `prompt` / `both`). Per-session, we keep only `vl_model_name` and `prompt_model_name` strings. A new route group `/settings/*` hosts the LMStudio config UI; the session drawer loses endpoint inputs and gains two model dropdowns. Backend gets one slim `lm_client.py` (OpenAI-compatible: `list_models` + `analyze_image`) and three new endpoint groups (`/api/settings/lmstudio*`, `/api/sessions/{id}/analyze-source`).

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, sqlite3 (3.35+ for `DROP COLUMN`), `httpx`, pytest/TestClient with monkeypatch; React 18, TypeScript, TanStack Query v5, React Router v6, Radix Dialog, CSS modules, Vitest + React Testing Library.

**Reference docs checked while writing this plan:**
- OpenAI-compatible chat-completions vision payload (LMStudio mirrors this 1:1): Context7 `/openai/openai-python` (we hand-roll the wire format with httpx instead of pulling the SDK)
- Slice-1 plan structure and conventions: `docs/superpowers/plans/2026-04-24-slice-1-library-crud.md`
- Roadmap §2.3 + §4 Slice 3 (current): `docs/superpowers/specs/2026-04-23-mvp-roadmap-design.md`
- Spec §3 (sessions, schema), §4.2 (analyze-source), §4.5 (system prompt convention): `docs/spec/technical_specifications.md`

---

## Pre-flight: state at start of slice

After Slice 2 the codebase has:

- `sessions` table with `vl_endpoint TEXT`, `prompt_endpoint TEXT`, `vl_summary TEXT`, `source_image_path TEXT` (foundation `001_init.sql`). Slice 3 drops the two endpoint columns and adds `vl_model_name`, `prompt_model_name`.
- `app/storage/session_repo.py` exposing `update_session(name, model_name, use_negative)` — must grow to also accept `vl_model_name` / `prompt_model_name`.
- `app/api/sessions.py` with `_session_to_api_dict` that intentionally excludes `vl_endpoint` / `prompt_endpoint`. After this slice those columns are gone; `vl_model_name` / `prompt_model_name` are exposed.
- `app/services/` is empty — slice 3 adds `lm_client.py`.
- Frontend: `Session` type already has `vl_summary: string | null`. `AppShell` topbar has hardcoded placeholder host/model strings (`PLACEHOLDER_LMSTUDIO_HOST`, `PLACEHOLDER_VL_MODEL`). `ProjectSidebar` foot has a Settings button that does nothing. `SessionSettingsDrawer` has model select + pinned LoRAs but no endpoint inputs (those never made it into Slice 2).
- Routing in `frontend/src/app.tsx` lists `/library/families`, `/library/models`, `/library/loras`, `/projects/...`. Slice 3 adds `/settings/lmstudio`.

These are the assumed inputs; do not pre-implement them.

---

## File Structure

Create or modify only the files below.

```
backend/
├── app/
│   ├── api/
│   │   ├── sessions.py                      # drop endpoint plumbing; add vl_model_name/prompt_model_name; add analyze-source
│   │   └── settings.py                      # NEW — /api/settings/lmstudio + lm_models endpoints
│   ├── main.py                              # include settings router
│   ├── models/
│   │   ├── session.py                       # extend SessionOut/Update with model picks
│   │   └── settings.py                      # NEW — LmStudioConfig, LmModel, etc.
│   ├── services/
│   │   └── lm_client.py                     # NEW — list_models + analyze_image
│   └── storage/
│       ├── session_repo.py                  # extend update_session + reads
│       └── settings_repo.py                 # NEW — app_settings + lm_models CRUD
├── migrations/
│   └── 003_settings.sql                     # NEW
└── tests/
    ├── test_settings_repo.py                # NEW
    ├── test_lm_client.py                    # NEW
    ├── test_settings_api.py                 # NEW
    ├── test_sessions_analyze.py             # NEW
    ├── test_sessions_api.py                 # extend: vl_model_name/prompt_model_name PATCH
    ├── test_session_repo.py                 # extend: model-name persistence
    └── test_migrations.py                   # extend: confirms 003 columns/tables present

frontend/
└── src/
    ├── api/
    │   ├── sessions.ts                      # drop endpoint type; add model picks
    │   └── settings.ts                      # NEW — LMStudio config + lm_models hooks
    ├── app.tsx                              # add /settings/* routes
    ├── components/
    │   ├── molecules/
    │   │   └── SourceImagePane.tsx          # Analyze button, summary, "VL · model" meta
    │   ├── organisms/
    │   │   ├── ProjectSidebar.tsx           # gear button → Link
    │   │   ├── SessionSettingsDrawer.tsx    # remove endpoint UI; add VL/Prompt model dropdowns
    │   │   └── LmStudioSettings.tsx         # NEW — endpoint form + refresh + models table
    │   └── templates/
    │       ├── AppShell.tsx                 # live host + connection dot
    │       ├── SettingsLayout.tsx           # NEW — wrapper similar to LibraryLayout
    │       └── SettingsLayout.module.css    # NEW
    └── routes/
        └── settings/
            └── lmstudio.tsx                 # NEW — page entry
```

No DS-token changes. No new shared atoms.

---

## API Contract (delta vs Slice 2)

```
GET    /api/settings/lmstudio
    -> { base_url: string|null, api_key: string|null, configured: boolean, updated_at: number }

PUT    /api/settings/lmstudio
    body: { base_url: string|null, api_key: string|null }
    -> same as GET

POST   /api/settings/lmstudio/refresh
    -> { models: LmModel[] }                  # 200 on success
    409 — endpoint not configured
    502 — LMStudio responded with non-2xx
    504 — timeout reaching LMStudio

GET    /api/settings/lmstudio/models
    -> { models: LmModel[] }

PATCH  /api/settings/lmstudio/models/{name}
    body: { enabled?: boolean, role?: 'vl'|'prompt'|'both' }
    -> LmModel

POST   /api/sessions/{id}/analyze-source
    -> SessionOut (with vl_summary populated)
    404 — session not found
    409 — no source image / no LMStudio config / no vl_model_name on session / vl_model_name not enabled or wrong role
    502/504 — upstream failure
```

Types:

```ts
type LmModel = {
  name: string;                    // e.g. "qwen2-vl-7b-instruct"
  role: "vl" | "prompt" | "both";
  enabled: boolean;
  last_seen: number;               // unix seconds
};

type Session = {
  // ...existing...
  vl_model_name: string | null;        // NEW
  prompt_model_name: string | null;    // NEW
  vl_summary: string | null;
  // vl_endpoint / prompt_endpoint REMOVED
};

type SessionUpdate = {
  // ...existing...
  vl_model_name: string | null;        // NEW
  prompt_model_name: string | null;    // NEW
  // vl_endpoint REMOVED
};
```

Existing endpoint contracts (`/api/projects`, `/api/sessions/{id}` GET/PATCH, `/source` upload) keep their shapes apart from the additions / removals above.

---

## Task 1: Migration 003 — drop endpoints, add model picks, settings tables

**Files:**
- Create: `backend/migrations/003_settings.sql`
- Modify: `backend/tests/test_migrations.py`

- [ ] **Step 1: Write the failing migration smoke test**

Append to `backend/tests/test_migrations.py`:

```python
def test_migration_003_drops_endpoint_columns_and_adds_settings_tables(tmp_path):
    import sqlite3
    from pathlib import Path

    from app.storage import db as db_mod
    from app.storage.migrations import apply_pending

    conn = db_mod.connect(tmp_path / "m.db")
    apply_pending(conn, Path(__file__).parent.parent / "migrations")

    cols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)")}
    assert "vl_endpoint" not in cols
    assert "prompt_endpoint" not in cols
    assert "vl_model_name" in cols
    assert "prompt_model_name" in cols

    # singleton row exists
    settings = list(conn.execute("SELECT id FROM app_settings"))
    assert settings == [(1,)]

    # lm_models exists with role check
    conn.execute(
        "INSERT INTO lm_models(name, role, enabled, last_seen) VALUES (?, 'both', 1, 0)",
        ("ok",),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO lm_models(name, role, enabled, last_seen) "
            "VALUES (?, 'bogus', 1, 0)",
            ("bad",),
        )
```

If `pytest` isn't already imported in this file, add `import pytest` at the top.

- [ ] **Step 2: Run the test to verify failure**

From `backend/`:

```bash
.venv/Scripts/python -m pytest tests/test_migrations.py -v
```

Expected: FAIL — migration 003 does not exist; columns and tables are missing.

- [ ] **Step 3: Create the migration**

Write `backend/migrations/003_settings.sql`:

```sql
-- 003_settings.sql — global LMStudio config + cached model list
-- Replaces per-session vl_endpoint / prompt_endpoint with global app_settings
-- and adds session.vl_model_name / session.prompt_model_name pointers.

ALTER TABLE sessions DROP COLUMN vl_endpoint;
ALTER TABLE sessions DROP COLUMN prompt_endpoint;

ALTER TABLE sessions ADD COLUMN vl_model_name TEXT;
ALTER TABLE sessions ADD COLUMN prompt_model_name TEXT;

-- Single-row table (id=1) — easier to reason about than KV pairs.
CREATE TABLE app_settings (
  id                  INTEGER PRIMARY KEY CHECK (id = 1),
  lmstudio_base_url   TEXT,
  lmstudio_api_key    TEXT,
  updated_at          INTEGER NOT NULL
);

INSERT INTO app_settings(id, lmstudio_base_url, lmstudio_api_key, updated_at)
  VALUES (1, NULL, NULL, CAST(strftime('%s','now') AS INTEGER));

-- LMStudio model cache. Populated by `/api/settings/lmstudio/refresh`.
-- role:    which session field this model can be picked into.
--   'vl'     — only vl_model_name
--   'prompt' — only prompt_model_name
--   'both'   — either field (default — user can narrow it later)
-- enabled: hides the model from session dropdowns when false.
CREATE TABLE lm_models (
  name        TEXT PRIMARY KEY,
  role        TEXT NOT NULL DEFAULT 'both' CHECK (role IN ('vl','prompt','both')),
  enabled     INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  last_seen   INTEGER NOT NULL
);
```

- [ ] **Step 4: Run the test and verify pass**

```bash
.venv/Scripts/python -m pytest tests/test_migrations.py -v
```

Expected: PASS. If `DROP COLUMN` fails, your local SQLite is older than 3.35 — check with `python -c "import sqlite3; print(sqlite3.sqlite_version)"`. CPython 3.11+ ships 3.37+. Do not work around this with a table rebuild — flag it instead.

- [ ] **Step 5: Run the *full* backend test suite**

```bash
.venv/Scripts/python -m pytest -q
```

Expected: existing slice-2 tests fail because they reference columns / fields that are now gone or unused. **Do not fix them yet** — Tasks 5–6 will replace those usages. Note which tests fail (mostly inside `test_session_repo.py` / `test_sessions_api.py`) and proceed.

- [ ] **Step 6: Commit**

```bash
git add backend/migrations/003_settings.sql backend/tests/test_migrations.py
git commit -m "feat(storage): migration 003 — global lmstudio settings + model cache"
```

---

## Task 2: settings_repo — app_settings and lm_models

**Files:**
- Create: `backend/app/storage/settings_repo.py`
- Create: `backend/tests/test_settings_repo.py`

- [ ] **Step 1: Write failing repo tests**

Create `backend/tests/test_settings_repo.py`:

```python
from pathlib import Path

import pytest

from app.storage import db as db_mod
from app.storage import settings_repo
from app.storage.migrations import apply_pending


@pytest.fixture
def conn(tmp_path):
    c = db_mod.connect(tmp_path / "s.db")
    apply_pending(c, Path(__file__).parent.parent / "migrations")
    yield c
    c.close()


def test_default_lmstudio_settings_are_blank(conn):
    cfg = settings_repo.get_lmstudio(conn)
    assert cfg["lmstudio_base_url"] is None
    assert cfg["lmstudio_api_key"] is None


def test_set_lmstudio_round_trips_and_bumps_updated_at(conn):
    before = settings_repo.get_lmstudio(conn)
    settings_repo.set_lmstudio(
        conn,
        base_url="http://localhost:1234/v1",
        api_key="lm-studio",
    )
    after = settings_repo.get_lmstudio(conn)
    assert after["lmstudio_base_url"] == "http://localhost:1234/v1"
    assert after["lmstudio_api_key"] == "lm-studio"
    assert after["updated_at"] >= before["updated_at"]


def test_set_lmstudio_strips_trailing_slash_in_base_url(conn):
    settings_repo.set_lmstudio(conn, base_url="http://h/v1/", api_key=None)
    assert settings_repo.get_lmstudio(conn)["lmstudio_base_url"] == "http://h/v1"


def test_set_lmstudio_can_clear_to_null(conn):
    settings_repo.set_lmstudio(conn, base_url="http://h/v1", api_key="k")
    settings_repo.set_lmstudio(conn, base_url=None, api_key=None)
    cfg = settings_repo.get_lmstudio(conn)
    assert cfg["lmstudio_base_url"] is None
    assert cfg["lmstudio_api_key"] is None


def test_lm_models_upsert_merge_keeps_user_flags(conn):
    settings_repo.upsert_lm_models(
        conn,
        names=["qwen2-vl-7b", "mistral-nemo-12b"],
        seen_at=100,
    )
    settings_repo.update_lm_model(conn, name="qwen2-vl-7b", role="vl", enabled=True)
    settings_repo.update_lm_model(conn, name="mistral-nemo-12b", role="prompt", enabled=False)

    settings_repo.upsert_lm_models(
        conn,
        names=["qwen2-vl-7b", "mistral-nemo-12b", "new-model"],
        seen_at=200,
    )

    by_name = {m["name"]: m for m in settings_repo.list_lm_models(conn)}
    assert by_name["qwen2-vl-7b"]["role"] == "vl"
    assert by_name["qwen2-vl-7b"]["enabled"] is True
    assert by_name["qwen2-vl-7b"]["last_seen"] == 200
    assert by_name["mistral-nemo-12b"]["role"] == "prompt"
    assert by_name["mistral-nemo-12b"]["enabled"] is False
    assert by_name["mistral-nemo-12b"]["last_seen"] == 200
    assert by_name["new-model"]["role"] == "both"      # default
    assert by_name["new-model"]["enabled"] is True     # default


def test_lm_models_upsert_keeps_stale_rows_when_disappear(conn):
    # Spec §2.3: stale models are kept on refresh so users still see disabled/old picks.
    settings_repo.upsert_lm_models(conn, names=["a", "b"], seen_at=100)
    settings_repo.upsert_lm_models(conn, names=["a"], seen_at=200)  # `b` disappears

    by_name = {m["name"]: m for m in settings_repo.list_lm_models(conn)}
    assert set(by_name) == {"a", "b"}            # `b` survives
    assert by_name["a"]["last_seen"] == 200      # `a` was refreshed
    assert by_name["b"]["last_seen"] == 100      # `b` keeps original timestamp


def test_update_lm_model_returns_none_for_unknown(conn):
    assert settings_repo.update_lm_model(conn, name="ghost", enabled=False) is None


def test_update_lm_model_rejects_bad_role(conn):
    settings_repo.upsert_lm_models(conn, names=["m"], seen_at=0)
    with pytest.raises(ValueError):
        settings_repo.update_lm_model(conn, name="m", role="bogus")
```

- [ ] **Step 2: Run and verify failure**

```bash
.venv/Scripts/python -m pytest tests/test_settings_repo.py -v
```

Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the repo**

Create `backend/app/storage/settings_repo.py`:

```python
"""Repository for global app settings and LMStudio model cache."""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterable
from typing import Any, Literal

ROLE = Literal["vl", "prompt", "both"]
_VALID_ROLES = {"vl", "prompt", "both"}


def _now() -> int:
    return int(time.time())


def _normalize_base_url(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip().rstrip("/")
    return stripped or None


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
```

- [ ] **Step 4: Run and verify pass**

```bash
.venv/Scripts/python -m pytest tests/test_settings_repo.py -v
```

Expected: all seven tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/storage/settings_repo.py backend/tests/test_settings_repo.py
git commit -m "feat(settings): repo for app_settings and lm_models"
```

---

## Task 3: lm_client service — list_models + analyze_image

**Files:**
- Create: `backend/app/services/lm_client.py`
- Create: `backend/tests/test_lm_client.py`
- Modify: `backend/pyproject.toml` (promote `httpx` to runtime dep)

- [ ] **Step 1: Promote httpx to runtime dep**

In `backend/pyproject.toml`, move `httpx>=0.27` out of `[project.optional-dependencies].dev` into `[project].dependencies`. Run from `backend/`:

```bash
uv sync
```

Expected: `uv.lock` updated.

- [ ] **Step 2: Write failing client tests**

Create `backend/tests/test_lm_client.py`:

```python
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.services import lm_client


def _models_response(names: list[str]) -> httpx.Response:
    return httpx.Response(
        200,
        json={"object": "list", "data": [{"id": n, "object": "model"} for n in names]},
    )


def _chat_response(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "x",
            "object": "chat.completion",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        },
    )


def test_list_models_hits_models_endpoint_and_returns_names():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        return _models_response(["qwen2-vl-7b-instruct", "mistral-nemo-12b"])

    out = lm_client.list_models(
        endpoint={"base_url": "http://localhost:1234/v1", "api_key": "lm-studio"},
        transport=httpx.MockTransport(handler),
    )
    assert out == ["mistral-nemo-12b", "qwen2-vl-7b-instruct"]  # sorted
    assert captured["url"] == "http://localhost:1234/v1/models"
    assert captured["headers"]["authorization"] == "Bearer lm-studio"


def test_list_models_omits_authorization_when_no_api_key():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        return _models_response([])

    lm_client.list_models(
        endpoint={"base_url": "http://h/v1", "api_key": None},
        transport=httpx.MockTransport(handler),
    )
    assert "authorization" not in captured["headers"]


def test_list_models_strips_trailing_slash():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return _models_response([])

    lm_client.list_models(
        endpoint={"base_url": "http://h/v1/", "api_key": None},
        transport=httpx.MockTransport(handler),
    )
    assert captured["url"] == "http://h/v1/models"


def test_list_models_raises_on_non_2xx():
    transport = httpx.MockTransport(lambda r: httpx.Response(503, text="busy"))
    with pytest.raises(lm_client.LmError) as exc:
        lm_client.list_models(
            endpoint={"base_url": "http://h/v1", "api_key": None},
            transport=transport,
        )
    assert exc.value.kind == "upstream"


def test_list_models_raises_on_timeout():
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("nope")

    with pytest.raises(lm_client.LmError) as exc:
        lm_client.list_models(
            endpoint={"base_url": "http://h/v1", "api_key": None},
            transport=httpx.MockTransport(handler),
        )
    assert exc.value.kind == "timeout"


def test_analyze_image_sends_chat_completions_with_data_url():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return _chat_response("a moody street at dusk")

    out = lm_client.analyze_image(
        endpoint={"base_url": "http://localhost:1234/v1", "api_key": "lm-studio"},
        model="qwen2-vl-7b-instruct",
        image_bytes=b"\x89PNG_fake",
        content_type="image/png",
        transport=httpx.MockTransport(handler),
    )
    assert out == "a moody street at dusk"
    assert captured["url"] == "http://localhost:1234/v1/chat/completions"
    assert captured["body"]["model"] == "qwen2-vl-7b-instruct"
    user = captured["body"]["messages"][-1]
    parts = user["content"]
    types = [p["type"] for p in parts]
    assert "text" in types and "image_url" in types
    assert parts[-1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_analyze_image_raises_on_shape_mismatch():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"choices": []}))
    with pytest.raises(lm_client.LmError) as exc:
        lm_client.analyze_image(
            endpoint={"base_url": "http://h/v1", "api_key": None},
            model="m",
            image_bytes=b"x",
            content_type="image/png",
            transport=transport,
        )
    assert exc.value.kind == "shape"


def test_analyze_image_propagates_timeout():
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with pytest.raises(lm_client.LmError) as exc:
        lm_client.analyze_image(
            endpoint={"base_url": "http://h/v1", "api_key": None},
            model="m", image_bytes=b"x", content_type="image/png",
            transport=httpx.MockTransport(handler),
        )
    assert exc.value.kind == "timeout"
```

- [ ] **Step 3: Run tests to verify failure**

```bash
.venv/Scripts/python -m pytest tests/test_lm_client.py -v
```

Expected: import error.

- [ ] **Step 4: Implement lm_client**

Create `backend/app/services/lm_client.py`:

```python
"""Thin OpenAI-compatible client for an LMStudio-style server.

We deliberately stay on raw httpx instead of pulling the openai SDK — slice 3
needs only two methods, and slice 4 (chat) will make its own decision on SSE.

`endpoint` shape used everywhere here: ``{"base_url": str, "api_key": str|None}``.
"""
from __future__ import annotations

import base64
from typing import Any, Literal

import httpx

DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=5.0)
LIST_TIMEOUT = httpx.Timeout(15.0, connect=5.0)

VL_SYSTEM_PROMPT = (
    "You describe images in terms useful for image-to-image generation. "
    "Be concise and concrete. Cover composition, subjects/objects, style, "
    "lighting, palette, and mood. Avoid speculation; do not invent text. "
    "Output a single paragraph of plain prose, no lists, no preamble."
)


class LmError(Exception):
    """Failure raised by lm_client. `slots=True` is intentionally NOT used —
    combining it with `Exception` triggers a layout conflict on CPython."""

    def __init__(self, kind: Literal["upstream", "timeout", "shape", "config"], detail: str) -> None:
        super().__init__(f"LmError({kind}): {detail}")
        self.kind = kind
        self.detail = detail


def _resolve(endpoint: dict[str, Any]) -> tuple[str, dict[str, str]]:
    base_url = str(endpoint.get("base_url") or "").strip().rstrip("/")
    if not base_url:
        raise LmError("config", "lmstudio base_url is not configured")
    headers = {"Content-Type": "application/json"}
    api_key = endpoint.get("api_key") or None
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return base_url, headers


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


def list_models(
    *,
    endpoint: dict[str, Any],
    transport: httpx.BaseTransport | None = None,
) -> list[str]:
    base_url, headers = _resolve(endpoint)
    resp = _request(
        "GET", f"{base_url}/models",
        headers=headers, json=None, transport=transport, timeout=LIST_TIMEOUT,
    )
    if resp.status_code >= 400:
        raise LmError("upstream", f"{resp.status_code}: {resp.text[:200]}")
    try:
        body = resp.json()
        names = sorted(item["id"] for item in body["data"])
    except (ValueError, KeyError, TypeError) as exc:
        raise LmError("shape", f"unexpected /models body: {exc}") from exc
    return names


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

    base_url, headers = _resolve(endpoint)
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
        "POST", f"{base_url}/chat/completions",
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
```

- [ ] **Step 5: Run tests and verify pass**

```bash
.venv/Scripts/python -m pytest tests/test_lm_client.py -v
```

Expected: all eight tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/lm_client.py backend/tests/test_lm_client.py backend/pyproject.toml backend/uv.lock
git commit -m "feat(services): OpenAI-compat lm_client (list_models + analyze_image)"
```

---

## Task 4: Pydantic models for settings + sessions delta

**Files:**
- Create: `backend/app/models/settings.py`
- Modify: `backend/app/models/session.py`

- [ ] **Step 1: Create settings models**

Create `backend/app/models/settings.py`:

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


Role = Literal["vl", "prompt", "both"]


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
    role: Role
    enabled: bool
    last_seen: int


class LmModelsOut(StrictModel):
    models: list[LmModelOut]


class LmModelPatch(StrictModel):
    role: Role | None = None
    enabled: bool | None = None
```

- [ ] **Step 2: Extend session models**

Replace the contents of `backend/app/models/session.py` with:

```python
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PinnedLoraIn(StrictModel):
    lora_name: str = Field(min_length=1)
    weight_override: float | None = Field(default=None, ge=-2.0, le=2.0)


class PinnedLoraOut(StrictModel):
    lora_name: str
    weight_override: float | None


class ProjectOut(StrictModel):
    id: str
    name: str
    session_count: int
    created_at: int
    updated_at: int


class ProjectCreate(StrictModel):
    name: str = Field(min_length=1, max_length=160)


class ProjectUpdate(StrictModel):
    name: str = Field(min_length=1, max_length=160)


class SessionOut(StrictModel):
    id: str
    project_id: str
    name: str | None
    model_name: str | None
    use_negative: bool
    pinned_loras: list[PinnedLoraOut]
    source_image_path: str | None
    source_image_url: str | None
    vl_summary: str | None
    vl_model_name: str | None
    prompt_model_name: str | None
    created_at: int
    updated_at: int


class SessionCreate(StrictModel):
    name: str | None = Field(default=None, max_length=160)
    model_name: str | None = None
    use_negative: bool = True


class SessionUpdate(StrictModel):
    name: str | None = Field(default=None, max_length=160)
    model_name: str | None = None
    use_negative: bool
    pinned_loras: list[PinnedLoraIn] = Field(default_factory=list)
    vl_model_name: str | None = None
    prompt_model_name: str | None = None
```

- [ ] **Step 3: Smoke-check imports**

```bash
.venv/Scripts/python -c "from app.models.settings import LmStudioConfigOut, LmModelOut, LmModelPatch; from app.models.session import SessionOut, SessionUpdate; print('ok')"
```

Expected: prints `ok`. Don't run pytest — sessions tests still reference removed columns; Tasks 5–6 fix that.

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/settings.py backend/app/models/session.py
git commit -m "feat(models): settings schemas + session model picks"
```

---

## Task 5: session_repo — drop endpoint references, add model picks; set_vl_summary

**Files:**
- Modify: `backend/app/storage/session_repo.py`
- Modify: `backend/tests/test_session_repo.py`

- [ ] **Step 1: Update repo tests**

Open `backend/tests/test_session_repo.py`. Find the test fixture / functions that touch `vl_endpoint` or `prompt_endpoint` (they no longer exist). Remove or rewrite them. Then append new tests:

```python
def test_update_session_persists_model_picks(conn):
    pid = session_repo.create_project(conn, name="P")["id"]
    sid = session_repo.create_session(conn, project_id=pid)["id"]

    session_repo.update_session(
        conn,
        sid,
        name=None,
        model_name=None,
        use_negative=True,
        vl_model_name="qwen2-vl-7b-instruct",
        prompt_model_name="mistral-nemo-12b",
    )

    fetched = session_repo.get_session_with_pinned(conn, sid)
    assert fetched["vl_model_name"] == "qwen2-vl-7b-instruct"
    assert fetched["prompt_model_name"] == "mistral-nemo-12b"


def test_update_session_can_clear_model_picks(conn):
    pid = session_repo.create_project(conn, name="P")["id"]
    sid = session_repo.create_session(conn, project_id=pid)["id"]
    session_repo.update_session(
        conn, sid, name=None, model_name=None, use_negative=True,
        vl_model_name="m", prompt_model_name="m",
    )
    session_repo.update_session(
        conn, sid, name=None, model_name=None, use_negative=True,
        vl_model_name=None, prompt_model_name=None,
    )
    after = session_repo.get_session_with_pinned(conn, sid)
    assert after["vl_model_name"] is None
    assert after["prompt_model_name"] is None


def test_set_vl_summary_persists_and_bumps_updated_at(conn):
    pid = session_repo.create_project(conn, name="P")["id"]
    created = session_repo.create_session(conn, project_id=pid)
    sid = created["id"]

    session_repo.set_vl_summary(conn, sid, "moody portrait")
    after = session_repo.get_session_with_pinned(conn, sid)
    assert after["vl_summary"] == "moody portrait"
    assert after["updated_at"] >= created["updated_at"]
```

- [ ] **Step 2: Patch the repo**

In `backend/app/storage/session_repo.py`:

1. `_session_row_to_dict` requires no changes — it only converts `use_negative` to `bool` and slice 3 doesn't add any new JSON columns. Skim it and move on.

2. Replace `update_session` with this signature — model picks default to `None` so existing keyword-less callers in tests fail loud (they should pass them explicitly):

```python
def update_session(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    name: str | None,
    model_name: str | None,
    use_negative: bool,
    vl_model_name: str | None = None,
    prompt_model_name: str | None = None,
) -> dict[str, Any] | None:
    now = _now()
    cur = conn.execute(
        "UPDATE sessions SET name = ?, model_name = ?, use_negative = ?, "
        "vl_model_name = ?, prompt_model_name = ?, updated_at = ? "
        "WHERE id = ?",
        (
            name, model_name, 1 if use_negative else 0,
            vl_model_name, prompt_model_name, now, session_id,
        ),
    )
    if cur.rowcount == 0:
        return None
    row = get_session(conn, session_id)
    if row:
        conn.execute(
            "UPDATE projects SET updated_at = ? WHERE id = ?",
            (now, row["project_id"]),
        )
    return row
```

3. Add at the bottom of the file:

```python
def set_vl_summary(conn: sqlite3.Connection, session_id: str, summary: str) -> None:
    conn.execute(
        "UPDATE sessions SET vl_summary = ?, updated_at = ? WHERE id = ?",
        (summary, _now(), session_id),
    )
```

- [ ] **Step 3: Run repo tests**

```bash
.venv/Scripts/python -m pytest tests/test_session_repo.py -v
```

Expected: all PASS — including pre-existing tests, after the endpoint-touching tests are deleted/rewritten.

- [ ] **Step 4: Commit**

```bash
git add backend/app/storage/session_repo.py backend/tests/test_session_repo.py
git commit -m "feat(sessions): vl_model_name/prompt_model_name + set_vl_summary"
```

---

## Task 6: API — settings + sessions analyze + sessions PATCH update

**Files:**
- Create: `backend/app/api/settings.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/api/sessions.py`
- Modify: `backend/tests/test_sessions_api.py`
- Create: `backend/tests/test_settings_api.py`
- Create: `backend/tests/test_sessions_analyze.py`

- [ ] **Step 1: Implement the settings router**

Create `backend/app/api/settings.py`:

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
from app.services import lm_client
from app.storage import settings_repo

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

router = APIRouter(tags=["settings"])


def _to_config_out(row: dict) -> dict:
    return {
        "base_url": row["lmstudio_base_url"],
        "api_key": row["lmstudio_api_key"],
        "configured": bool(row["lmstudio_base_url"]),
        "updated_at": row["updated_at"],
    }


def _endpoint_from_row(row: dict) -> dict:
    return {
        "base_url": row["lmstudio_base_url"],
        "api_key": row["lmstudio_api_key"],
    }


def _vl_translate(exc: lm_client.LmError) -> HTTPException:
    if exc.kind == "timeout":
        return HTTPException(status_code=504, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


@router.get("/api/settings/lmstudio", response_model=LmStudioConfigOut)
def get_lmstudio(conn: Conn) -> dict:
    return _to_config_out(settings_repo.get_lmstudio(conn))


@router.put("/api/settings/lmstudio", response_model=LmStudioConfigOut)
def put_lmstudio(body: LmStudioConfig, conn: Conn) -> dict:
    return _to_config_out(
        settings_repo.set_lmstudio(conn, base_url=body.base_url, api_key=body.api_key),
    )


@router.post("/api/settings/lmstudio/refresh", response_model=LmModelsOut)
def refresh_lmstudio_models(conn: Conn) -> dict:
    cfg = settings_repo.get_lmstudio(conn)
    if not cfg["lmstudio_base_url"]:
        raise HTTPException(status_code=409, detail="LMStudio base_url is not configured")
    try:
        names = lm_client.list_models(endpoint=_endpoint_from_row(cfg))
    except lm_client.LmError as exc:
        raise _vl_translate(exc) from exc
    settings_repo.upsert_lm_models(conn, names=names)
    return {"models": settings_repo.list_lm_models(conn)}


@router.get("/api/settings/lmstudio/models", response_model=LmModelsOut)
def list_lm_models(conn: Conn) -> dict:
    return {"models": settings_repo.list_lm_models(conn)}


@router.patch("/api/settings/lmstudio/models/{name}", response_model=LmModelOut)
def patch_lm_model(name: str, body: LmModelPatch, conn: Conn) -> dict:
    if body.role is None and body.enabled is None:
        raise HTTPException(status_code=422, detail="provide role or enabled")
    row = settings_repo.update_lm_model(
        conn, name=name, role=body.role, enabled=body.enabled,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown model: {name}",
        )
    return row
```

- [ ] **Step 2: Wire the router**

In `backend/app/main.py`, add the import and include:

```python
from app.api.settings import router as settings_router
# ...
app.include_router(settings_router)
```

- [ ] **Step 3: Update sessions API — drop endpoint plumbing, expose model picks, add analyze**

In `backend/app/api/sessions.py`:

1. At the top of the file, add the imports needed for analyze-source:

```python
from app import config as app_config
from app.services import lm_client
from app.storage import settings_repo
```

2. Replace `_session_to_api_dict` to expose model picks and drop endpoint references:

```python
def _session_to_api_dict(row: dict) -> dict:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "name": row["name"],
        "model_name": row["model_name"],
        "use_negative": row["use_negative"],
        "pinned_loras": row.get("pinned_loras", []),
        "source_image_path": row.get("source_image_path"),
        "source_image_url": _session_url(row.get("source_image_path")),
        "vl_summary": row.get("vl_summary"),
        "vl_model_name": row.get("vl_model_name"),
        "prompt_model_name": row.get("prompt_model_name"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
```

3. Update the PATCH session route to forward model picks:

```python
@router.patch("/api/sessions/{session_id}", response_model=SessionOut)
def update_session(session_id: str, body: SessionUpdate, conn: Conn):
    row = session_repo.update_session(
        conn,
        session_id,
        name=body.name,
        model_name=body.model_name,
        use_negative=body.use_negative,
        vl_model_name=body.vl_model_name,
        prompt_model_name=body.prompt_model_name,
    )
    if row is None:
        raise _not_found("session", session_id)
    try:
        session_repo.set_pinned_loras(
            conn,
            session_id,
            [p.model_dump() for p in body.pinned_loras],
        )
    except sqlite3.IntegrityError as exc:
        raise _conflict(exc) from exc
    return _session_payload(conn, session_id)
```

4. Append the analyze-source endpoint and helpers at the bottom:

```python
_EXT_TO_CT: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def _content_type_from_ext(ext: str) -> str:
    if ext not in _EXT_TO_CT:
        raise HTTPException(
            status_code=409,
            detail=f"stored image has unsupported extension: {ext!r}",
        )
    return _EXT_TO_CT[ext]


def _validated_vl_model(conn: sqlite3.Connection, name: str | None) -> str:
    if not name:
        raise HTTPException(
            status_code=409,
            detail="session has no vl_model_name selected",
        )
    row = settings_repo.get_lm_model(conn, name)
    if row is None or not row["enabled"] or row["role"] not in ("vl", "both"):
        raise HTTPException(
            status_code=409,
            detail=f"vl_model_name {name!r} is not enabled or wrong role",
        )
    return name


@router.post("/api/sessions/{session_id}/analyze-source", response_model=SessionOut)
def analyze_source(session_id: str, conn: Conn) -> dict:
    row = session_repo.get_session_with_pinned(conn, session_id)
    if row is None:
        raise _not_found("session", session_id)
    if not row.get("source_image_path"):
        raise HTTPException(status_code=409, detail="session has no source image")

    cfg = settings_repo.get_lmstudio(conn)
    if not cfg["lmstudio_base_url"]:
        raise HTTPException(
            status_code=409, detail="LMStudio base_url is not configured",
        )
    model = _validated_vl_model(conn, row.get("vl_model_name"))

    data_root = app_config.resolve_data_root()
    image_path = (data_root / row["source_image_path"]).resolve()
    base = data_root.resolve()
    if not str(image_path).startswith(str(base)) or not image_path.is_file():
        raise HTTPException(status_code=409, detail="source image is missing on disk")

    content_type = _content_type_from_ext(image_path.suffix.lower())
    image_bytes = image_path.read_bytes()

    try:
        summary = lm_client.analyze_image(
            endpoint={
                "base_url": cfg["lmstudio_base_url"],
                "api_key": cfg["lmstudio_api_key"],
            },
            model=model,
            image_bytes=image_bytes,
            content_type=content_type,
        )
    except lm_client.LmError as exc:
        if exc.kind == "timeout":
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    session_repo.set_vl_summary(conn, session_id, summary)
    return _session_payload(conn, session_id)
```

- [ ] **Step 4: Update existing sessions tests**

In `backend/tests/test_sessions_api.py`, the existing PATCH-test bodies probably still pass — `SessionUpdate` defaults the new fields to `None`. Verify by running them; if any fail because the JSON they send is rejected as `extra="forbid"`, drop the offending old keys (`vl_endpoint` etc).

Append a new test:

```python
def test_patch_session_round_trips_vl_and_prompt_model_names(client):
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    sid = client.post(
        f"/api/projects/{pid}/sessions",
        json={"name": "s", "model_name": None, "use_negative": True},
    ).json()["id"]

    payload = {
        "name": "s",
        "model_name": None,
        "use_negative": True,
        "pinned_loras": [],
        "vl_model_name": "qwen2-vl-7b-instruct",
        "prompt_model_name": "mistral-nemo-12b",
    }
    resp = client.patch(f"/api/sessions/{sid}", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["vl_model_name"] == "qwen2-vl-7b-instruct"
    assert body["prompt_model_name"] == "mistral-nemo-12b"

    # null clears
    cleared = client.patch(
        f"/api/sessions/{sid}",
        json={**payload, "vl_model_name": None, "prompt_model_name": None},
    ).json()
    assert cleared["vl_model_name"] is None
    assert cleared["prompt_model_name"] is None
```

- [ ] **Step 5: Add settings API tests**

Create `backend/tests/test_settings_api.py`:

```python
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_conn
from app.main import app
from app.services import lm_client
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
        json={"base_url": "http://localhost:1234/v1/", "api_key": "lm-studio"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["base_url"] == "http://localhost:1234/v1"  # trailing slash stripped
    assert body["configured"] is True

    again = client.get("/api/settings/lmstudio").json()
    assert again["base_url"] == "http://localhost:1234/v1"


def test_refresh_409_when_unconfigured(client):
    assert client.post("/api/settings/lmstudio/refresh").status_code == 409


def test_refresh_populates_models(client, monkeypatch):
    client.put("/api/settings/lmstudio", json={"base_url": "http://h/v1", "api_key": None})

    captured: dict[str, Any] = {}

    def fake_list(*, endpoint, transport=None):
        captured["endpoint"] = endpoint
        return ["mistral-nemo-12b", "qwen2-vl-7b-instruct"]

    monkeypatch.setattr(lm_client, "list_models", fake_list)

    body = client.post("/api/settings/lmstudio/refresh").json()
    assert {m["name"] for m in body["models"]} == {
        "mistral-nemo-12b", "qwen2-vl-7b-instruct",
    }
    for m in body["models"]:
        assert m["role"] == "both"
        assert m["enabled"] is True
    assert captured["endpoint"] == {"base_url": "http://h/v1", "api_key": None}


def test_refresh_502_when_lm_client_upstream(client, monkeypatch):
    client.put("/api/settings/lmstudio", json={"base_url": "http://h/v1", "api_key": None})

    def fake(*, endpoint, transport=None):
        raise lm_client.LmError("upstream", "503: busy")
    monkeypatch.setattr(lm_client, "list_models", fake)

    assert client.post("/api/settings/lmstudio/refresh").status_code == 502


def test_refresh_504_on_timeout(client, monkeypatch):
    client.put("/api/settings/lmstudio", json={"base_url": "http://h/v1", "api_key": None})

    def fake(*, endpoint, transport=None):
        raise lm_client.LmError("timeout", "ConnectTimeout")
    monkeypatch.setattr(lm_client, "list_models", fake)

    assert client.post("/api/settings/lmstudio/refresh").status_code == 504


def test_patch_lm_model_role_and_enabled(client, monkeypatch):
    client.put("/api/settings/lmstudio", json={"base_url": "http://h/v1", "api_key": None})
    monkeypatch.setattr(lm_client, "list_models", lambda **_: ["qwen2-vl-7b-instruct"])
    client.post("/api/settings/lmstudio/refresh")

    resp = client.patch(
        "/api/settings/lmstudio/models/qwen2-vl-7b-instruct",
        json={"role": "vl", "enabled": False},
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "name": "qwen2-vl-7b-instruct",
        "role": "vl",
        "enabled": False,
        "last_seen": resp.json()["last_seen"],
    }


def test_patch_lm_model_404_for_unknown(client):
    resp = client.patch(
        "/api/settings/lmstudio/models/ghost", json={"enabled": False},
    )
    assert resp.status_code == 404


def test_refresh_does_not_clobber_user_flags(client, monkeypatch):
    client.put("/api/settings/lmstudio", json={"base_url": "http://h/v1", "api_key": None})
    monkeypatch.setattr(lm_client, "list_models", lambda **_: ["m"])
    client.post("/api/settings/lmstudio/refresh")
    client.patch("/api/settings/lmstudio/models/m", json={"role": "prompt", "enabled": False})

    body = client.post("/api/settings/lmstudio/refresh").json()
    [m] = body["models"]
    assert m["role"] == "prompt"
    assert m["enabled"] is False
```

- [ ] **Step 6: Add analyze-source tests**

Create `backend/tests/test_sessions_analyze.py`:

```python
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_conn
from app.main import app
from app.services import lm_client
from app.storage import db as db_mod
from app.storage.migrations import apply_pending

_PNG_1x1 = bytes.fromhex(
    "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C489"
    "0000000A49444154789C6300010000000500010D0A2DB40000000049454E44AE426082"
)


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "data"
    (root / "images").mkdir(parents=True)
    monkeypatch.setattr("app.config.resolve_data_root", lambda *a, **kw: root)
    monkeypatch.setattr("app.storage.images.resolve_data_root", lambda *a, **kw: root)
    monkeypatch.setattr("app.api.sessions.app_config.resolve_data_root", lambda *a, **kw: root)
    return root


@pytest.fixture
def conn(data_root):
    c = db_mod.connect(data_root / "app.db")
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


def _bootstrap(client, monkeypatch, *, vl_model: str | None = "qwen2-vl-7b-instruct") -> str:
    """Set lmstudio config, refresh-with-fake, mark a VL model, attach source."""
    client.put(
        "/api/settings/lmstudio",
        json={"base_url": "http://h/v1", "api_key": None},
    )
    monkeypatch.setattr(
        lm_client, "list_models",
        lambda **_: ["qwen2-vl-7b-instruct", "mistral-nemo-12b"],
    )
    client.post("/api/settings/lmstudio/refresh")
    client.patch(
        "/api/settings/lmstudio/models/qwen2-vl-7b-instruct",
        json={"role": "vl", "enabled": True},
    )

    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    sid = client.post(
        f"/api/projects/{pid}/sessions",
        json={"name": "s", "model_name": None, "use_negative": True},
    ).json()["id"]
    client.patch(
        f"/api/sessions/{sid}",
        json={
            "name": "s",
            "model_name": None,
            "use_negative": True,
            "pinned_loras": [],
            "vl_model_name": vl_model,
            "prompt_model_name": None,
        },
    )
    client.post(
        f"/api/sessions/{sid}/source",
        files={"file": ("source.png", _PNG_1x1, "image/png")},
    )
    return sid


def test_analyze_returns_summary_and_persists(client, monkeypatch):
    captured: dict[str, Any] = {}

    def fake_analyze(**kwargs):
        captured.update(kwargs)
        return "moody portrait, soft rim light"

    sid = _bootstrap(client, monkeypatch)
    monkeypatch.setattr(lm_client, "analyze_image", fake_analyze)

    resp = client.post(f"/api/sessions/{sid}/analyze-source")
    assert resp.status_code == 200
    assert resp.json()["vl_summary"] == "moody portrait, soft rim light"

    assert captured["model"] == "qwen2-vl-7b-instruct"
    assert captured["content_type"] == "image/png"
    assert captured["image_bytes"] == _PNG_1x1
    assert captured["endpoint"] == {"base_url": "http://h/v1", "api_key": None}

    again = client.get(f"/api/sessions/{sid}").json()
    assert again["vl_summary"] == "moody portrait, soft rim light"


def test_analyze_404_when_session_missing(client):
    assert client.post("/api/sessions/missing/analyze-source").status_code == 404


def test_analyze_409_when_no_lmstudio_config(client, monkeypatch):
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    sid = client.post(
        f"/api/projects/{pid}/sessions",
        json={"name": "s", "model_name": None, "use_negative": True},
    ).json()["id"]
    client.post(
        f"/api/sessions/{sid}/source",
        files={"file": ("source.png", _PNG_1x1, "image/png")},
    )

    resp = client.post(f"/api/sessions/{sid}/analyze-source")
    assert resp.status_code == 409
    assert "lmstudio" in resp.json()["detail"].lower() or "base_url" in resp.json()["detail"].lower()


def test_analyze_409_when_no_source_image(client, monkeypatch):
    client.put("/api/settings/lmstudio", json={"base_url": "http://h/v1", "api_key": None})
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    sid = client.post(
        f"/api/projects/{pid}/sessions",
        json={"name": "s", "model_name": None, "use_negative": True},
    ).json()["id"]
    resp = client.post(f"/api/sessions/{sid}/analyze-source")
    assert resp.status_code == 409
    assert "source" in resp.json()["detail"].lower()


def test_analyze_409_when_no_vl_model_on_session(client, monkeypatch):
    sid = _bootstrap(client, monkeypatch, vl_model=None)
    resp = client.post(f"/api/sessions/{sid}/analyze-source")
    assert resp.status_code == 409
    assert "vl_model" in resp.json()["detail"]


def test_analyze_409_when_vl_model_disabled(client, monkeypatch):
    sid = _bootstrap(client, monkeypatch)
    client.patch(
        "/api/settings/lmstudio/models/qwen2-vl-7b-instruct",
        json={"enabled": False},
    )
    resp = client.post(f"/api/sessions/{sid}/analyze-source")
    assert resp.status_code == 409


def test_analyze_409_when_vl_model_role_is_prompt_only(client, monkeypatch):
    sid = _bootstrap(client, monkeypatch)
    client.patch(
        "/api/settings/lmstudio/models/qwen2-vl-7b-instruct",
        json={"role": "prompt"},
    )
    resp = client.post(f"/api/sessions/{sid}/analyze-source")
    assert resp.status_code == 409


def test_analyze_502_on_upstream_error(client, monkeypatch):
    sid = _bootstrap(client, monkeypatch)

    def fake(**_): raise lm_client.LmError("upstream", "boom")
    monkeypatch.setattr(lm_client, "analyze_image", fake)

    assert client.post(f"/api/sessions/{sid}/analyze-source").status_code == 502


def test_analyze_504_on_timeout(client, monkeypatch):
    sid = _bootstrap(client, monkeypatch)

    def fake(**_): raise lm_client.LmError("timeout", "slow")
    monkeypatch.setattr(lm_client, "analyze_image", fake)

    assert client.post(f"/api/sessions/{sid}/analyze-source").status_code == 504


def test_analyze_failure_does_not_overwrite_existing_summary(client, monkeypatch):
    sid = _bootstrap(client, monkeypatch)
    monkeypatch.setattr(lm_client, "analyze_image", lambda **_: "first summary")
    assert client.post(f"/api/sessions/{sid}/analyze-source").status_code == 200

    def fake_fail(**_): raise lm_client.LmError("upstream", "boom")
    monkeypatch.setattr(lm_client, "analyze_image", fake_fail)

    assert client.post(f"/api/sessions/{sid}/analyze-source").status_code == 502
    assert client.get(f"/api/sessions/{sid}").json()["vl_summary"] == "first summary"
```

- [ ] **Step 7: Run all backend tests**

```bash
.venv/Scripts/python -m pytest -q
```

Expected: green. Address any remaining failures in pre-existing tests that still reference removed fields (`vl_endpoint` / `prompt_endpoint` in JSON bodies — drop those keys from test payloads).

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/settings.py backend/app/main.py backend/app/api/sessions.py backend/tests/test_settings_api.py backend/tests/test_sessions_api.py backend/tests/test_sessions_analyze.py
git commit -m "feat(api): settings router, analyze-source, session model picks"
```

---

## Task 7: Frontend API — settings.ts + sessions.ts delta

**Files:**
- Create: `frontend/src/api/settings.ts`
- Modify: `frontend/src/api/sessions.ts`

- [ ] **Step 1: Drop endpoint type, add model picks in `sessions.ts`**

Open `frontend/src/api/sessions.ts`:

1. Update `Session`:

```ts
export type Session = {
  id: string;
  project_id: string;
  name: string | null;
  model_name: string | null;
  use_negative: boolean;
  pinned_loras: PinnedLora[];
  source_image_path: string | null;
  source_image_url: string | null;
  vl_summary: string | null;
  vl_model_name: string | null;
  prompt_model_name: string | null;
  created_at: number;
  updated_at: number;
};
```

2. Update `SessionUpdate`:

```ts
export type SessionUpdate = {
  name: string | null;
  model_name: string | null;
  use_negative: boolean;
  pinned_loras: PinnedLora[];
  vl_model_name: string | null;
  prompt_model_name: string | null;
};
```

3. Add an analyzeSource method to `sessionsApi`:

```ts
analyzeSource: (id: string) =>
  apiFetch<Session>(`/api/sessions/${id}/analyze-source`, { method: "POST" }),
```

- [ ] **Step 2: Create `settings.ts`**

Create `frontend/src/api/settings.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";

export type LmRole = "vl" | "prompt" | "both";

export type LmStudioConfig = {
  base_url: string | null;
  api_key: string | null;
  configured: boolean;
  updated_at: number;
};

export type LmModel = {
  name: string;
  role: LmRole;
  enabled: boolean;
  last_seen: number;
};

export const settingsKeys = {
  lmstudio: () => ["settings", "lmstudio"] as const,
  lmModels: () => ["settings", "lmstudio", "models"] as const,
};

export const settingsApi = {
  getLmStudio: () => apiFetch<LmStudioConfig>("/api/settings/lmstudio"),
  putLmStudio: (body: { base_url: string | null; api_key: string | null }) =>
    apiFetch<LmStudioConfig>("/api/settings/lmstudio", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  refresh: () =>
    apiFetch<{ models: LmModel[] }>("/api/settings/lmstudio/refresh", {
      method: "POST",
    }),
  listModels: () =>
    apiFetch<{ models: LmModel[] }>("/api/settings/lmstudio/models"),
  patchModel: (
    name: string,
    body: { role?: LmRole; enabled?: boolean },
  ) =>
    apiFetch<LmModel>(`/api/settings/lmstudio/models/${encodeURIComponent(name)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
};

export function useLmStudioConfig() {
  return useQuery({
    queryKey: settingsKeys.lmstudio(),
    queryFn: settingsApi.getLmStudio,
  });
}

export function useLmModels() {
  return useQuery({
    queryKey: settingsKeys.lmModels(),
    queryFn: () => settingsApi.listModels().then((r) => r.models),
  });
}

export function useLmModelsByRole(role: "vl" | "prompt") {
  const all = useLmModels();
  return {
    ...all,
    data: (all.data ?? []).filter(
      (m) => m.enabled && (m.role === role || m.role === "both"),
    ),
  };
}

export function useSettingsInvalidation() {
  const client = useQueryClient();
  return {
    config: () => {
      void client.invalidateQueries({ queryKey: settingsKeys.lmstudio() });
    },
    models: () => {
      void client.invalidateQueries({ queryKey: settingsKeys.lmModels() });
    },
    all: () => {
      void client.invalidateQueries({ queryKey: ["settings"] });
    },
  };
}

export function useRefreshLmStudio() {
  const invalidate = useSettingsInvalidation();
  return useMutation({
    mutationFn: () => settingsApi.refresh(),
    onSuccess: () => {
      invalidate.models();
      invalidate.config();
    },
  });
}
```

- [ ] **Step 3: Type-check**

```bash
pnpm exec tsc --noEmit
```

Expected: errors point only at consumers we'll update in Tasks 8–10 (drawer, source-pane, app shell). Note them; do not fix here.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/settings.ts frontend/src/api/sessions.ts
git commit -m "feat(api): settings hooks; session model picks"
```

---

## Task 8: SettingsLayout + LMStudio page

**Files:**
- Create: `frontend/src/components/templates/SettingsLayout.tsx`
- Create: `frontend/src/components/templates/SettingsLayout.module.css`
- Create: `frontend/src/components/organisms/LmStudioSettings.tsx`
- Create: `frontend/src/components/organisms/LmStudioSettings.module.css`
- Create: `frontend/src/routes/settings/lmstudio.tsx`
- Modify: `frontend/src/components/atoms/Icon.tsx`

- [ ] **Step 1: Register new lucide icons**

This task and Task 11 reference `Server`, `RotateCw`, and `Sparkles` from `Icon.tsx`. Verified absent — add them now so the rest of this task type-checks.

In `frontend/src/components/atoms/Icon.tsx`, add to both the `import { … } from "lucide-react"` block and the `ICONS` map: `RotateCw`, `Server`, `Sparkles`. Keep alphabetical order.

- [ ] **Step 2: Build the layout shell**

Create `frontend/src/components/templates/SettingsLayout.module.css`:

```css
.layout {
  display: grid;
  grid-template-columns: 220px 1fr;
  height: 100%;
  min-height: 0;
}

.nav {
  border-right: 1px solid var(--border);
  padding: 16px 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.navTitle {
  font-size: 11px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-subtle);
  padding: 8px 8px 4px;
}

.navLink {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: var(--r-sm);
  color: var(--text-muted);
  text-decoration: none;
  font-size: var(--text-sm);
}

.navLink:hover {
  background: var(--bg-raised);
}

.navLinkActive {
  background: var(--bg-raised);
  color: var(--text);
}

.body {
  padding: 24px 28px;
  overflow: auto;
  min-width: 0;
}
```

Create `frontend/src/components/templates/SettingsLayout.tsx`:

```tsx
import { NavLink } from "react-router-dom";
import type { ReactNode } from "react";
import { Icon } from "@/components/atoms/Icon";
import styles from "./SettingsLayout.module.css";

const TABS = [{ to: "/settings/lmstudio", label: "LMStudio", icon: "Server" as const }];

export function SettingsLayout({ children }: { children: ReactNode }) {
  return (
    <div className={styles.layout}>
      <nav className={styles.nav} aria-label="Settings">
        <div className={styles.navTitle}>Settings</div>
        {TABS.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            className={({ isActive }) =>
              `${styles.navLink} ${isActive ? styles.navLinkActive : ""}`
            }
          >
            <Icon name={t.icon} size={12} />
            {t.label}
          </NavLink>
        ))}
      </nav>
      <main className={styles.body}>{children}</main>
    </div>
  );
}
```

- [ ] **Step 3: Build the LMStudio page organism**

Create `frontend/src/components/organisms/LmStudioSettings.module.css`:

```css
.page {
  display: flex;
  flex-direction: column;
  gap: 24px;
  max-width: 720px;
}

.section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.h {
  font-size: var(--text-md);
  font-weight: 600;
}

.sub {
  color: var(--text-subtle);
  font-size: var(--text-xs);
}

.row {
  display: flex;
  gap: 8px;
  align-items: flex-end;
}

.banner {
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  padding: 12px 14px;
  font-size: var(--text-sm);
  color: var(--text-muted);
  background: var(--bg-raised);
}

.banner[data-tone="error"] {
  border-color: var(--danger);
  color: var(--danger);
}

.modelTable {
  display: grid;
  grid-template-columns: 1fr 130px 90px 110px;
  gap: 0;
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  overflow: hidden;
}

.modelTable > div {
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  font-size: var(--text-sm);
  display: flex;
  align-items: center;
}

.modelTable > div:nth-last-child(-n+4) {
  border-bottom: 0;
}

.headCell {
  background: var(--bg-raised);
  color: var(--text-subtle);
  font-size: 11px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.modelRoleSelect {
  width: 100%;
  font-size: var(--text-sm);
}
```

Create `frontend/src/components/organisms/LmStudioSettings.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { TextInput } from "@/components/molecules/FormField";
import {
  settingsApi,
  useLmModels,
  useLmStudioConfig,
  useRefreshLmStudio,
  useSettingsInvalidation,
  type LmRole,
} from "@/api/settings";
import styles from "./LmStudioSettings.module.css";

const ROLES: LmRole[] = ["vl", "prompt", "both"];

export function LmStudioSettings() {
  const cfg = useLmStudioConfig();
  const models = useLmModels();
  const refresh = useRefreshLmStudio();
  const invalidate = useSettingsInvalidation();

  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);

  useEffect(() => {
    if (cfg.data) {
      setBaseUrl(cfg.data.base_url ?? "");
      setApiKey(cfg.data.api_key ?? "");
    }
  }, [cfg.data]);

  const save = useMutation({
    mutationFn: () =>
      settingsApi.putLmStudio({
        base_url: baseUrl.trim() || null,
        api_key: apiKey.trim() || null,
      }),
    onSuccess: () => invalidate.config(),
  });

  const patch = useMutation({
    mutationFn: (args: { name: string; role?: LmRole; enabled?: boolean }) =>
      settingsApi.patchModel(args.name, {
        ...(args.role !== undefined ? { role: args.role } : {}),
        ...(args.enabled !== undefined ? { enabled: args.enabled } : {}),
      }),
    onSuccess: () => invalidate.models(),
  });

  const configured = !!cfg.data?.configured;
  const refreshError = refresh.error ? String(refresh.error) : null;
  const noConnection = !configured || (refreshError && (models.data ?? []).length === 0);
  const refreshDisabled = !configured || refresh.isPending;

  return (
    <div className={styles.page}>
      <section className={styles.section}>
        <div className={styles.h}>LMStudio endpoint</div>
        <div className={styles.sub}>
          OpenAI-compatible base URL exposed by LMStudio. The API key is optional —
          LMStudio ignores it; leave empty unless your reverse proxy needs it.
        </div>
        <TextInput
          label="Base URL"
          placeholder="http://localhost:1234/v1"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.currentTarget.value)}
        />
        <div className={styles.row} style={{ alignItems: "flex-end" }}>
          <div style={{ flex: 1 }}>
            <TextInput
              label="API key (optional)"
              placeholder="leave empty for local LMStudio"
              type={showKey ? "text" : "password"}
              value={apiKey}
              onChange={(e) => setApiKey(e.currentTarget.value)}
            />
          </div>
          <Button size="sm" onClick={() => setShowKey((v) => !v)}>
            {showKey ? "Hide" : "Show"}
          </Button>
        </div>
        <div>
          <Button
            variant="primary"
            onClick={() => save.mutate()}
            disabled={save.isPending}
          >
            {save.isPending ? "Saving…" : "Save endpoint"}
          </Button>
        </div>
      </section>

      <section className={styles.section}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div className={styles.h}>Available models</div>
          <div style={{ flex: 1 }} />
          <Button
            size="sm"
            icon={<Icon name="RotateCw" size={12} />}
            onClick={() => refresh.mutate()}
            disabled={refreshDisabled}
          >
            {refresh.isPending ? "Refreshing…" : "Refresh from LMStudio"}
          </Button>
        </div>

        {!configured && (
          <div className={styles.banner}>
            Configure base URL above, then press Refresh to fetch the model list.
          </div>
        )}
        {configured && refreshError && (
          <div className={styles.banner} data-tone="error" role="alert">
            Refresh failed: {refreshError}
          </div>
        )}
        {configured && !refreshError && (models.data ?? []).length === 0 && (
          <div className={styles.banner}>
            No models cached yet. Press Refresh to fetch them from LMStudio.
          </div>
        )}

        {(models.data ?? []).length > 0 && (
          <div className={styles.modelTable} role="table">
            <div className={styles.headCell}>Model</div>
            <div className={styles.headCell}>Role</div>
            <div className={styles.headCell}>Enabled</div>
            <div className={styles.headCell}>Last seen</div>
            {(models.data ?? []).map((m) => (
              <Row key={m.name}>
                <div title={m.name}>{m.name}</div>
                <div>
                  <select
                    className={styles.modelRoleSelect}
                    value={m.role}
                    onChange={(e) =>
                      patch.mutate({ name: m.name, role: e.currentTarget.value as LmRole })
                    }
                  >
                    {ROLES.map((r) => (
                      <option key={r} value={r}>
                        {r}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <input
                    type="checkbox"
                    checked={m.enabled}
                    onChange={(e) =>
                      patch.mutate({ name: m.name, enabled: e.currentTarget.checked })
                    }
                  />
                </div>
                <div style={{ color: "var(--text-subtle)", fontSize: 12 }}>
                  {m.last_seen ? new Date(m.last_seen * 1000).toLocaleString() : "—"}
                </div>
              </Row>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function Row({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
```

- [ ] **Step 4: Create the route entry**

Create `frontend/src/routes/settings/lmstudio.tsx`:

```tsx
import { LmStudioSettings } from "@/components/organisms/LmStudioSettings";

export default function LmStudioRoute() {
  return <LmStudioSettings />;
}
```

- [ ] **Step 5: Wire the routes**

Edit `frontend/src/app.tsx`. Add the import and route:

```tsx
import { SettingsLayout } from "./components/templates/SettingsLayout";
import LmStudioRoute from "./routes/settings/lmstudio";
```

Inside the `<Routes>` block, after the library routes:

```tsx
<Route
  path="/settings"
  element={<Navigate to="/settings/lmstudio" replace />}
/>
<Route
  path="/settings/lmstudio"
  element={
    <SettingsLayout>
      <LmStudioRoute />
    </SettingsLayout>
  }
/>
```

- [ ] **Step 6: Type-check + dev smoke**

```bash
pnpm exec tsc --noEmit
pnpm dev   # then open http://localhost:5173/settings/lmstudio in a browser
```

Expected: tsc passes; the page renders with the “Configure base URL above…” banner. Don't drive the form yet — Task 11 covers manual smoke against a live LMStudio.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/templates/SettingsLayout.tsx frontend/src/components/templates/SettingsLayout.module.css frontend/src/components/organisms/LmStudioSettings.tsx frontend/src/components/organisms/LmStudioSettings.module.css frontend/src/routes/settings/lmstudio.tsx frontend/src/app.tsx frontend/src/components/atoms/Icon.tsx
git commit -m "feat(settings): /settings/lmstudio page and layout"
```

---

## Task 9: Sidebar gear → Link; AppShell live LMStudio chip

**Files:**
- Modify: `frontend/src/components/organisms/ProjectSidebar.tsx`
- Modify: `frontend/src/components/templates/AppShell.tsx`

- [ ] **Step 1: Replace the gear button with a Link**

In `ProjectSidebar.tsx`, change:

```tsx
<button type="button" className={styles.footBtn} title="Settings" aria-label="Settings">
  <Icon name="Settings" size={12} />
</button>
```

to:

```tsx
<Link
  to="/settings/lmstudio"
  className={styles.footBtn}
  title="Settings"
  aria-label="Settings"
>
  <Icon name="Settings" size={12} />
</Link>
```

Add `Link` to the existing `react-router-dom` import.

- [ ] **Step 2: Style: anchor matches button**

If clicking the new Link looks visually wrong (default underline / colour), add:

```css
/* in ProjectSidebar.module.css */
.footBtn {
  text-decoration: none;
  color: inherit;
}
```

- [ ] **Step 3: Live LMStudio chip in `AppShell`**

Replace the placeholder constants and `<span className={styles.topbarEndpoint}>` block. Replace the entire `AppShell.tsx` with:

```tsx
import { Link, Outlet, useLocation } from "react-router-dom";
import { ProjectSidebar } from "@/components/organisms/ProjectSidebar";
import { useLmStudioConfig } from "@/api/settings";
import styles from "./AppShell.module.css";

export function AppShell() {
  const { pathname } = useLocation();
  const inLibrary = pathname.startsWith("/library");
  const inSettings = pathname.startsWith("/settings");
  const cfg = useLmStudioConfig();

  const host = cfg.data?.base_url
    ? cfg.data.base_url.replace(/^https?:\/\//, "").replace(/\/v1\/?$/, "")
    : "(no endpoint)";
  const dot = cfg.data?.configured ? styles.endpointDotOn : styles.endpointDotOff;

  return (
    <div className={styles.shell}>
      <header className={styles.topbar}>
        <div className={styles.topbarLeft}>
          <div className={styles.brand}>
            <span className={styles.brandGlyph}>sd</span>
            <span className={styles.brandName}>sd-chisel</span>
          </div>
          <nav className={styles.topbarNav} aria-label="App mode">
            <Link
              to="/"
              className={`${styles.navPill} ${!inLibrary && !inSettings ? styles.navPillActive : ""}`}
            >
              Workspace
            </Link>
            <Link
              to="/library/loras"
              className={`${styles.navPill} ${inLibrary ? styles.navPillActive : ""}`}
            >
              Library
            </Link>
            <Link
              to="/settings/lmstudio"
              className={`${styles.navPill} ${inSettings ? styles.navPillActive : ""}`}
            >
              Settings
            </Link>
          </nav>
        </div>
        <div className={styles.topbarSpacer} />
        <div className={styles.topbarRight}>
          <Link
            to="/settings/lmstudio"
            className={styles.topbarEndpoint}
            title={
              cfg.data?.configured
                ? `LMStudio · ${cfg.data.base_url}`
                : "LMStudio endpoint not configured — click to set up"
            }
          >
            <span className={`${styles.endpointDot} ${dot}`} />
            {host}
          </Link>
        </div>
      </header>
      <div className={styles.sidebar}>
        <ProjectSidebar />
      </div>
      <main className={styles.main}>
        <Outlet />
      </main>
    </div>
  );
}
```

In `AppShell.module.css`, ensure the dot has on/off variants. Add or merge:

```css
.endpointDotOn {
  background: var(--ok, #4caf50);
}
.endpointDotOff {
  background: var(--danger, #ef5350);
}
```

(Replace the existing single `.endpointDot { background: ...; }` rule’s colour with `background: var(--text-subtle);` so it acts as a neutral default; keep size/shape rules.)

- [ ] **Step 4: Run frontend tests + tsc**

```bash
pnpm exec tsc --noEmit
pnpm vitest run
```

Existing `AppShell.test.tsx` may assert text from `PLACEHOLDER_LMSTUDIO_HOST`. Update the assertion: when `cfg.data` is undefined (the test probably renders without API), the chip reads `(no endpoint)`. Tweak the test to match.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/organisms/ProjectSidebar.tsx frontend/src/components/templates/AppShell.tsx frontend/src/components/templates/AppShell.module.css frontend/src/components/templates/AppShell.test.tsx
git commit -m "feat(shell): live LMStudio chip; sidebar gear opens settings"
```

---

## Task 10: SessionSettingsDrawer — VL/Prompt model dropdowns

**Files:**
- Modify: `frontend/src/components/organisms/SessionSettingsDrawer.tsx`
- Create: `frontend/src/components/organisms/SessionSettingsDrawer.test.tsx`

- [ ] **Step 1: Replace endpoint section with model pickers**

Replace the entire contents of `SessionSettingsDrawer.tsx` with:

```tsx
import * as Dialog from "@radix-ui/react-dialog";
import { Link } from "react-router-dom";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { TextInput } from "@/components/molecules/FormField";
import { useLoras, useModels, type Lora } from "@/api/library";
import {
  sessionsApi,
  useSessionInvalidation,
  type PinnedLora,
  type Session,
} from "@/api/sessions";
import { useLmModelsByRole } from "@/api/settings";
import styles from "./SessionSettingsDrawer.module.css";

export function SessionSettingsDrawer({
  session,
  open,
  onOpenChange,
}: {
  session: Session;
  open: boolean;
  onOpenChange: (value: boolean) => void;
}) {
  const models = useModels();
  const loras = useLoras();
  const vlChoices = useLmModelsByRole("vl");
  const promptChoices = useLmModelsByRole("prompt");
  const invalidate = useSessionInvalidation();

  const [name, setName] = useState(session.name ?? "");
  const [modelName, setModelName] = useState(session.model_name ?? "");
  const [useNegative, setUseNegative] = useState(session.use_negative);
  const [pinned, setPinned] = useState<PinnedLora[]>(session.pinned_loras);
  const [vlModel, setVlModel] = useState(session.vl_model_name ?? "");
  const [promptModel, setPromptModel] = useState(session.prompt_model_name ?? "");
  const [loraSearch, setLoraSearch] = useState("");

  const save = useMutation({
    mutationFn: () =>
      sessionsApi.updateSession(session.id, {
        name: name.trim() || null,
        model_name: modelName || null,
        use_negative: useNegative,
        pinned_loras: pinned,
        vl_model_name: vlModel || null,
        prompt_model_name: promptModel || null,
      }),
    onSuccess: () => {
      invalidate.session(session.id);
      onOpenChange(false);
    },
  });

  function togglePin(lora: Lora) {
    setPinned((current) =>
      current.some((p) => p.lora_name === lora.name)
        ? current.filter((p) => p.lora_name !== lora.name)
        : [...current, { lora_name: lora.name, weight_override: null }],
    );
  }

  const filteredLoras = (loras.data ?? []).filter((l) =>
    `${l.name} ${l.display_name}`.toLowerCase().includes(loraSearch.toLowerCase()),
  );

  const noLmModels =
    !vlChoices.isLoading
    && !promptChoices.isLoading
    && (vlChoices.data?.length ?? 0) === 0
    && (promptChoices.data?.length ?? 0) === 0;

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content className={styles.panel} aria-describedby={undefined}>
          <div className={styles.head}>
            <Dialog.Title className={styles.title}>Session settings</Dialog.Title>
            <Dialog.Close asChild>
              <button type="button" className={styles.closeBtn} aria-label="Close">
                <Icon name="X" />
              </button>
            </Dialog.Close>
          </div>
          <div className={styles.body}>
            <TextInput
              label="Session name"
              value={name}
              onChange={(e) => setName(e.currentTarget.value)}
            />
            <div className={styles.labelBlock}>
              <span>Base model (diffusion)</span>
              <select
                className={styles.select}
                value={modelName}
                onChange={(e) => setModelName(e.currentTarget.value)}
              >
                <option value="">(none)</option>
                {(models.data ?? []).map((m) => (
                  <option key={m.name} value={m.name}>
                    {m.display_name} · {m.family_id}
                  </option>
                ))}
              </select>
            </div>
            <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <input
                type="checkbox"
                checked={useNegative}
                onChange={(e) => setUseNegative(e.currentTarget.checked)}
              />
              Use negative prompt
            </label>

            <div className={styles.labelBlock}>
              <span>VL model (image analysis)</span>
              <select
                className={styles.select}
                value={vlModel}
                onChange={(e) => setVlModel(e.currentTarget.value)}
                disabled={(vlChoices.data?.length ?? 0) === 0}
              >
                <option value="">(not set)</option>
                {(vlChoices.data ?? []).map((m) => (
                  <option key={m.name} value={m.name}>{m.name}</option>
                ))}
              </select>
            </div>

            <div className={styles.labelBlock}>
              <span>Prompt model (text LLM)</span>
              <select
                className={styles.select}
                value={promptModel}
                onChange={(e) => setPromptModel(e.currentTarget.value)}
                disabled={(promptChoices.data?.length ?? 0) === 0}
              >
                <option value="">(not set)</option>
                {(promptChoices.data ?? []).map((m) => (
                  <option key={m.name} value={m.name}>{m.name}</option>
                ))}
              </select>
            </div>

            {noLmModels && (
              <div style={{
                fontSize: 12, color: "var(--text-subtle)",
                border: "1px dashed var(--border)", borderRadius: 6, padding: 10,
              }}>
                No enabled LMStudio models yet.{" "}
                <Link to="/settings/lmstudio" onClick={() => onOpenChange(false)}>
                  Configure LMStudio →
                </Link>
              </div>
            )}

            <div>
              <div style={{ marginBottom: 6 }}>Pinned LoRAs ({pinned.length})</div>
              <TextInput
                label="Search LoRAs"
                placeholder="Type to filter…"
                value={loraSearch}
                onChange={(e) => setLoraSearch(e.currentTarget.value)}
              />
              <div className={styles.loraList}>
                {filteredLoras.map((l) => {
                  const isPinned = pinned.some((p) => p.lora_name === l.name);
                  return (
                    <button
                      key={l.name}
                      type="button"
                      className={`${styles.loraRow} ${isPinned ? styles.pinned : ""}`}
                      onClick={() => togglePin(l)}
                    >
                      {isPinned && <Icon name="Pin" size={12} />}
                      <span className={styles.loraName}>{l.display_name}</span>
                      <span className={styles.loraMeta}>{l.family_id}</span>
                    </button>
                  );
                })}
                {filteredLoras.length === 0 && (
                  <div style={{ padding: 12, color: "var(--text-subtle)" }}>No LoRAs match.</div>
                )}
              </div>
            </div>
          </div>
          <div className={styles.foot}>
            <Button type="button" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="primary"
              onClick={() => save.mutate()}
              disabled={save.isPending}
            >
              {save.isPending ? "Saving..." : "Save changes"}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
```

- [ ] **Step 2: Vitest test for dropdown filtering**

Create `frontend/src/components/organisms/SessionSettingsDrawer.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { SessionSettingsDrawer } from "./SessionSettingsDrawer";
import * as settingsApi from "@/api/settings";
import * as libraryApi from "@/api/library";
import type { Session } from "@/api/sessions";

const baseSession: Session = {
  id: "s1",
  project_id: "p1",
  name: null,
  model_name: null,
  use_negative: true,
  vl_model_name: null,
  prompt_model_name: null,
  vl_summary: null,
  source_image_path: null,
  source_image_url: null,
  result_image_path: null,
  pinned_loras: [],
  created_at: 0,
  updated_at: 0,
};

function renderDrawer() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <SessionSettingsDrawer session={baseSession} open={true} onOpenChange={() => {}} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SessionSettingsDrawer model pickers", () => {
  beforeEach(() => {
    vi.spyOn(libraryApi, "useLoras").mockReturnValue({ data: [] } as any);
    vi.spyOn(libraryApi, "useModels").mockReturnValue({ data: [] } as any);
  });
  afterEach(() => vi.restoreAllMocks());

  it("VL select offers vl + both, hides prompt-only", () => {
    vi.spyOn(settingsApi, "useLmModelsByRole").mockImplementation((role) =>
      ({
        data: role === "vl"
          ? [{ name: "qwen-vl", role: "vl", enabled: true, last_seen: 0 },
             { name: "any-model", role: "both", enabled: true, last_seen: 0 }]
          : [{ name: "any-model", role: "both", enabled: true, last_seen: 0 }],
      } as any),
    );
    renderDrawer();
    const vlSelect = screen.getByLabelText(/vl model/i) as HTMLSelectElement;
    const optionTexts = Array.from(vlSelect.options).map((o) => o.value);
    expect(optionTexts).toContain("qwen-vl");
    expect(optionTexts).toContain("any-model");
    expect(optionTexts).not.toContain("mistral-prompt");
  });

  it("shows 'Configure LMStudio' link when no models cached", () => {
    vi.spyOn(settingsApi, "useLmModelsByRole").mockReturnValue({ data: [] } as any);
    renderDrawer();
    expect(screen.getByRole("link", { name: /configure lmstudio/i })).toBeInTheDocument();
  });
});
```

Run:

```bash
pnpm vitest run src/components/organisms/SessionSettingsDrawer.test.tsx
```

Expected: PASS (after Step 1's drawer rewrite is in place).

- [ ] **Step 3: Type-check**

```bash
pnpm exec tsc --noEmit
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/organisms/SessionSettingsDrawer.tsx frontend/src/components/organisms/SessionSettingsDrawer.test.tsx
git commit -m "feat(workspace): VL/Prompt model dropdowns in session drawer"
```

---

## Task 11: SourceImagePane — Analyze button, summary, model meta

**Files:**
- Modify: `frontend/src/components/molecules/SourceImagePane.tsx`
- Modify: `frontend/src/components/molecules/SourceImagePane.module.css`
- Create: `frontend/src/components/molecules/SourceImagePane.test.tsx`

- [ ] **Step 1: Add the failing component test**

Create `frontend/src/components/molecules/SourceImagePane.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SourceImagePane } from "./SourceImagePane";
import { sessionsApi, type Session } from "@/api/sessions";
import { settingsApi } from "@/api/settings";

const baseSession: Session = {
  id: "sess1",
  project_id: "proj1",
  name: "S",
  model_name: null,
  use_negative: true,
  pinned_loras: [],
  source_image_path: "images/sess1/source.png",
  source_image_url: "/media/images/sess1/source.png",
  vl_summary: null,
  vl_model_name: "qwen2-vl-7b-instruct",
  prompt_model_name: null,
  created_at: 0,
  updated_at: 0,
};

function withClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderWith(session: Session, configured = true) {
  vi.spyOn(settingsApi, "getLmStudio").mockResolvedValue({
    base_url: configured ? "http://h/v1" : null,
    api_key: null,
    configured,
    updated_at: 0,
  });
  const qc = withClient();
  return render(
    <QueryClientProvider client={qc}>
      <SourceImagePane session={session} />
    </QueryClientProvider>,
  );
}

describe("SourceImagePane analyze flow", () => {
  beforeEach(() => vi.restoreAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("shows the VL model in the meta line", () => {
    renderWith(baseSession);
    expect(screen.getByText(/qwen2-vl-7b-instruct/)).toBeInTheDocument();
  });

  it("disables Analyze when no vl_model_name on session", () => {
    renderWith({ ...baseSession, vl_model_name: null });
    const btn = screen.getByRole("button", { name: /analyze/i });
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute("title", expect.stringMatching(/vl model/i));
  });

  it("disables Analyze when LMStudio not configured", async () => {
    renderWith(baseSession, false);
    const btn = await screen.findByRole("button", { name: /analyze/i });
    expect(btn).toBeDisabled();
  });

  it("calls analyzeSource on click", async () => {
    const spy = vi.spyOn(sessionsApi, "analyzeSource").mockResolvedValue({
      ...baseSession, vl_summary: "moody portrait",
    });
    renderWith(baseSession);
    await userEvent.click(await screen.findByRole("button", { name: /analyze/i }));
    expect(spy).toHaveBeenCalledWith("sess1");
  });

  it("renders existing vl_summary when present", () => {
    renderWith({ ...baseSession, vl_summary: "previously analyzed scene" });
    expect(screen.getByText(/previously analyzed scene/)).toBeInTheDocument();
  });

  it("shows error when analyzeSource rejects", async () => {
    vi.spyOn(sessionsApi, "analyzeSource").mockRejectedValue(
      new Error("API 502: upstream timeout"),
    );
    renderWith(baseSession);
    await userEvent.click(await screen.findByRole("button", { name: /analyze/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/502|upstream/i);
  });
});
```


- [ ] **Step 2: Verify failure**

```bash
pnpm vitest run src/components/molecules/SourceImagePane.test.tsx
```

Expected: FAIL.

- [ ] **Step 3: Implement**

Replace `frontend/src/components/molecules/SourceImagePane.tsx`:

```tsx
import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import {
  buildSourceImageSrc,
  sessionsApi,
  useSessionInvalidation,
  type Session,
} from "@/api/sessions";
import { useLmStudioConfig } from "@/api/settings";
import styles from "./SourceImagePane.module.css";

export function SourceImagePane({ session }: { session: Session }) {
  const [over, setOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const invalidate = useSessionInvalidation();
  const cfg = useLmStudioConfig();

  const upload = useMutation({
    mutationFn: (file: File) => sessionsApi.uploadSource(session.id, file),
    onSuccess: () => {
      setError(null);
      invalidate.session(session.id);
    },
    onError: (err) => setError(String(err)),
  });
  const clear = useMutation({
    mutationFn: () => sessionsApi.clearSource(session.id),
    onSuccess: () => invalidate.session(session.id),
  });
  const analyze = useMutation({
    mutationFn: () => sessionsApi.analyzeSource(session.id),
    onSuccess: () => {
      setError(null);
      invalidate.session(session.id);
    },
    onError: (err) => setError(String(err)),
  });

  const src = buildSourceImageSrc(session);
  const hasImage = !!src;
  const lmConfigured = !!cfg.data?.configured;
  const hasVlModel = !!session.vl_model_name;
  const reason =
    !hasImage ? "Upload a source image first" :
    !lmConfigured ? "LMStudio is not configured — open Settings" :
    !hasVlModel ? "No VL model selected — open Session settings" :
    "Run VL analyze";

  function pickFile(file: File | undefined) {
    if (!file) return;
    if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
      setError(`Unsupported type: ${file.type}`);
      return;
    }
    upload.mutate(file);
  }

  return (
    <div className={styles.pane}>
      <div className={styles.head}>
        <span className={styles.title}>Source</span>
        {hasImage && session.vl_summary && <span className={styles.sub}>· VL-analyzed</span>}
        {hasImage && !session.vl_summary && <span className={styles.sub}>· {session.source_image_path}</span>}
        <span className={styles.sub} style={{ marginLeft: "auto" }}>
          VL · {session.vl_model_name ?? "(not set)"}
        </span>
        {hasImage && (
          <Button
            size="sm"
            icon={<Icon name="Sparkles" size={12} />}
            onClick={() => analyze.mutate()}
            disabled={!hasImage || !lmConfigured || !hasVlModel || analyze.isPending}
            title={reason}
          >
            {analyze.isPending ? "Analyzing…" : session.vl_summary ? "Re-analyze" : "Analyze"}
          </Button>
        )}
        {hasImage && (
          <Button
            size="sm"
            icon={<Icon name="Trash2" size={12} />}
            onClick={() => clear.mutate()}
          >
            Clear
          </Button>
        )}
      </div>
      <div className={styles.body}>
        {src ? (
          <div className={styles.stack}>
            <div className={styles.frame}>
              <img src={src} alt="source" />
            </div>
            {analyze.isPending && (
              <div className={styles.summary} data-state="pending">
                <div className={styles.summaryHead}>VL analyzing…</div>
              </div>
            )}
            {!analyze.isPending && session.vl_summary && (
              <div className={styles.summary} data-state="done">
                <div className={styles.summaryHead}>VL summary</div>
                <div className={styles.summaryBody}>{session.vl_summary}</div>
              </div>
            )}
            {error && <div className={styles.error} role="alert">{error}</div>}
          </div>
        ) : (
          <div
            className={styles.drop}
            data-over={over}
            onDragOver={(e) => { e.preventDefault(); setOver(true); }}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setOver(false);
              pickFile(e.dataTransfer.files?.[0]);
            }}
          >
            <Icon name="Folder" size={28} />
            <div className={styles.dropTitle}>Drop source image</div>
            <div className={styles.dropSub}>
              PNG/JPEG/WEBP. Stored under <code>data/images/&lt;session&gt;/</code>.
            </div>
            <Button
              size="sm"
              variant="primary"
              onClick={() => inputRef.current?.click()}
              disabled={upload.isPending}
            >
              {upload.isPending ? "Uploading..." : "Choose file"}
            </Button>
            <input
              ref={inputRef}
              hidden
              type="file"
              accept="image/png,image/jpeg,image/webp"
              onChange={(event) => pickFile(event.currentTarget.files?.[0] ?? undefined)}
            />
            {error && <div className={styles.error} role="alert">{error}</div>}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Add styles for the summary block**

Append to `SourceImagePane.module.css`:

```css
.stack {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
  align-items: stretch;
}

.summary {
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  padding: 10px 12px;
  background: var(--bg-subtle, var(--bg-raised));
  font-size: var(--text-xs);
  line-height: 1.5;
}

.summary[data-state="pending"] {
  font-style: italic;
  color: var(--text-muted);
}

.summaryHead {
  font-weight: 600;
  margin-bottom: 4px;
  color: var(--text-subtle);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  font-size: 10px;
}

.summaryBody {
  white-space: pre-wrap;
}
```

(`Sparkles` was added to `Icon.tsx` in Task 8 Step 1.)

- [ ] **Step 5: Run the test**

```bash
pnpm vitest run src/components/molecules/SourceImagePane.test.tsx
```

Expected: all six tests PASS. If a test still fails because the queryClient hasn't resolved `useLmStudioConfig` before assertion, await `screen.findByRole(...)` instead of `getByRole(...)`.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/molecules/SourceImagePane.tsx frontend/src/components/molecules/SourceImagePane.module.css frontend/src/components/molecules/SourceImagePane.test.tsx frontend/src/components/atoms/Icon.tsx
git commit -m "feat(workspace): wire Analyze + summary on source pane"
```

---

## Task 12: Manual smoke + lint

This task is verification-only. No new code.

- [ ] **Step 1: Boot both apps**

```bash
# terminal 1
cd backend && .venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
# terminal 2
cd frontend && pnpm dev
```

- [ ] **Step 2: Drive the full flow**

1. Open `http://localhost:5173/` — topbar dot is red, label `(no endpoint)`.
2. Click Settings (sidebar gear or topbar pill) → `/settings/lmstudio`. Banner: "Configure base URL above…".
3. Enter `http://localhost:1234/v1`, leave api key empty, Save → topbar dot turns green.
4. Press *Refresh from LMStudio*. With LMStudio running: the model list appears.
5. For one model, set role=`vl`, leave another at `both`, disable a third.
6. Open a session → Session settings → VL model dropdown only shows enabled `vl`/`both` models. Pick `qwen2-vl-7b-instruct`. Save.
7. Drag a source image. Press *Analyze* → spinner → summary appears. Reload page → summary persists.
8. Stop LMStudio → press *Re-analyze* → red error banner; summary remains.
9. Disable the VL model in Settings → drawer dropdown loses it; if it was the chosen one, the next save reads `vl_model_name = (not set)`; Analyze becomes disabled with "No VL model selected" tooltip.

If LMStudio isn't available, exercise Steps 1–3 (banner + save endpoint) and verify the Refresh button shows a 502/504 banner without crashing.

- [ ] **Step 3: Lint**

```bash
cd backend && .venv/Scripts/python -m ruff check .
cd ../frontend && pnpm exec eslint src --max-warnings=0
```

Expected: clean. Fix root causes, do not silence with comments.

---

## Slice 3 Acceptance Checklist

Verify against §4 Slice 3 of `docs/superpowers/specs/2026-04-23-mvp-roadmap-design.md` (post-update):

- [ ] LMStudio endpoint is configurable from `/settings/lmstudio`; persists across reloads.
- [ ] Refresh fetches model list and surfaces upstream errors (502/504) clearly without losing the cached list.
- [ ] User flags (`enabled`, `role`) survive subsequent refreshes.
- [ ] Drawer’s VL/Prompt dropdowns show only enabled models filtered by role; empty state links to `/settings/lmstudio`.
- [ ] `POST /api/sessions/{id}/analyze-source` succeeds → summary persists; 409 covers all four pre-conditions (no source / no LMStudio / no vl_model_name / disabled-or-wrong-role); upstream errors map to 502/504 and don’t overwrite the previous summary.
- [ ] `vl_endpoint` and `prompt_endpoint` are gone from the schema (verified by `test_migration_003_drops_endpoint_columns_and_adds_settings_tables`).
- [ ] Topbar shows live endpoint chip; sidebar gear navigates to settings.
- [ ] Out of scope (chat, prompt composition, result-image flow, automatic analyze-on-upload, inline model pickers in chat/VL panels) is *not* implemented.

When `pytest -q` + `pnpm vitest run` + lint commands are green, hand off to Slice 4.
