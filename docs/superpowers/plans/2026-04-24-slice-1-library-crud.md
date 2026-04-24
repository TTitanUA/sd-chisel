# Slice 1 Library CRUD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the foundation Library placeholders into a working CRUD flow for families, models, and LoRAs, without embeddings or session usage counts.

**Architecture:** Backend exposes `/api/library/*` FastAPI routers over the existing sqlite repository layer, with Pydantic request/response schemas and explicit 404/409 behavior. Frontend adds typed API functions and TanStack Query hooks, then replaces the three placeholder routes with read-first table/detail/form screens ported from `mvp-ui-mock/app/library.jsx`. This slice owns library CRUD only; vector indexing remains Slice 5.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, sqlite3, pytest/TestClient; React 18, TypeScript, Vite, TanStack Query v5, React Router v6, CSS modules, `@uiw/react-md-editor`, Testing Library/Vitest.

**Reference docs checked while writing this plan:**
- FastAPI body validation, APIRouter, HTTPException, dependency patterns: Context7 `/fastapi/fastapi`
- TanStack Query v5 `useQuery`, `useMutation`, `invalidateQueries`: Context7 `/tanstack/query`
- React Router v6 nested app-shell routing: Context7 `/websites/reactrouter_6_30_3`

---

## File Structure

Create or modify only the files below.

```
backend/
├── app/
│   ├── main.py                         # include library router
│   ├── api/
│   │   ├── deps.py                     # sqlite connection dependency
│   │   └── library.py                  # /api/library routers
│   ├── models/
│   │   └── library.py                  # Pydantic schemas
│   └── storage/
│       └── library_repo.py             # complete CRUD + filters
└── tests/
    ├── test_library_repo.py            # expand existing repo tests
    └── test_library_api.py             # new HTTP tests

frontend/
├── package.json                        # add @uiw/react-md-editor
├── pnpm-lock.yaml                      # pnpm updates it
└── src/
    ├── api/
    │   └── library.ts                  # typed API + query hooks
    ├── components/
    │   ├── molecules/
    │   │   ├── FormField.module.css
    │   │   ├── FormField.tsx
    │   │   ├── LibraryList.module.css
    │   │   ├── LibraryList.tsx
    │   │   ├── MarkdownField.tsx
    │   │   └── TextListInput.tsx
    │   └── organisms/
    │       ├── FamilyForm.tsx
    │       ├── LibraryCrud.module.css
    │       ├── LibraryCrud.tsx
    │       ├── LoraForm.tsx
    │       └── ModelForm.tsx
    └── routes/
        └── library/
            ├── families.tsx
            ├── loras.tsx
            └── models.tsx
```

---

## API Contract

All endpoints are JSON. All `POST` endpoints return `201`; all `PUT` endpoints return `200`; all deletes return `204`. Duplicate primary keys and FK delete restrictions return `409`. Missing rows return `404`. Pydantic validation failures return FastAPI's normal `422`.

```
GET    /api/library/families?q=
GET    /api/library/families/{family_id}
POST   /api/library/families
PUT    /api/library/families/{family_id}
DELETE /api/library/families/{family_id}

GET    /api/library/models?family_id=&q=
GET    /api/library/models/{name}
POST   /api/library/models
PUT    /api/library/models/{name}
DELETE /api/library/models/{name}

GET    /api/library/loras?family_id=&tag=&q=
GET    /api/library/loras/{name}
POST   /api/library/loras
PUT    /api/library/loras/{name}
DELETE /api/library/loras/{name}
```

Response shapes:

```ts
type Family = {
  id: string;
  display_name: string;
  prompt_guide: string;
  created_at: number;
  updated_at: number;
};

type Model = {
  name: string;
  display_name: string;
  family_id: string;
  description: string | null;
  author: string | null;
  version: string | null;
  source_url: string | null;
  created_at: number;
  updated_at: number;
};

type Lora = {
  name: string;
  display_name: string;
  description: string;
  tags: string[];
  trigger_words: string[];
  family_compat: string[];
  recommended_weight: number | null;
  author: string | null;
  version: string | null;
  source_url: string | null;
  created_at: number;
  updated_at: number;
};
```

---

## Task 1: Backend Repository CRUD Completion

**Files:**
- Modify: `backend/app/storage/library_repo.py`
- Modify: `backend/tests/test_library_repo.py`

- [ ] **Step 1: Add failing repository tests**

Append these tests to `backend/tests/test_library_repo.py`:

```python
def test_family_create_update_delete(conn):
    created = library_repo.create_family(
        conn,
        id="testfam",
        display_name="Test Family",
        prompt_guide="Use test syntax.",
    )
    assert created["id"] == "testfam"

    updated = library_repo.update_family(
        conn,
        "testfam",
        display_name="Test Family 2",
        prompt_guide="Updated guide.",
    )
    assert updated is not None
    assert updated["display_name"] == "Test Family 2"
    assert updated["updated_at"] >= created["updated_at"]

    assert library_repo.delete_family(conn, "testfam") is True
    assert library_repo.get_family(conn, "testfam") is None
    assert library_repo.delete_family(conn, "testfam") is False


def test_list_families_filters_by_query(conn):
    library_repo.create_family(conn, id="abcxyz", display_name="Needle Family", prompt_guide="x")
    rows = library_repo.list_families(conn, q="needle")
    assert [r["id"] for r in rows] == ["abcxyz"]


def test_model_update_delete_and_filters(conn):
    library_repo.create_model(
        conn,
        name="model_a",
        display_name="Model A",
        family_id="sdxl",
        description="alpha",
    )
    library_repo.create_model(conn, name="model_b", display_name="Model B", family_id="pony")

    filtered = library_repo.list_models(conn, family_id="sdxl", q="alpha")
    assert [m["name"] for m in filtered] == ["model_a"]

    updated = library_repo.update_model(
        conn,
        "model_a",
        display_name="Model A2",
        family_id="sdxl",
        description="beta",
        author="me",
        version="v1",
        source_url="https://example.test/model",
    )
    assert updated is not None
    assert updated["display_name"] == "Model A2"
    assert updated["description"] == "beta"

    assert library_repo.delete_model(conn, "model_a") is True
    assert library_repo.get_model(conn, "model_a") is None
    assert library_repo.delete_model(conn, "model_a") is False


def test_lora_update_delete_and_filters(conn):
    library_repo.create_lora(
        conn,
        name="detail_boost",
        display_name="Detail Boost",
        description="Adds crisp detail.",
        tags=["detail", "portrait"],
        trigger_words=["detail boost"],
        recommended_weight=0.7,
        family_compat=["sdxl"],
    )
    library_repo.create_lora(
        conn,
        name="linework",
        display_name="Linework",
        description="Adds line art.",
        tags=["line"],
        trigger_words=["line art"],
        family_compat=["pony"],
    )

    by_family = library_repo.list_loras(conn, family_id="sdxl")
    assert [l["name"] for l in by_family] == ["detail_boost"]

    by_tag = library_repo.list_loras(conn, tag="detail")
    assert [l["name"] for l in by_tag] == ["detail_boost"]

    by_query = library_repo.list_loras(conn, q="crisp")
    assert [l["name"] for l in by_query] == ["detail_boost"]

    updated = library_repo.update_lora(
        conn,
        "detail_boost",
        display_name="Detail Boost 2",
        description="Adds controlled detail.",
        tags=["detail"],
        trigger_words=["detail boost", "sharp detail"],
        family_compat=["sdxl", "illustrious"],
        recommended_weight=0.8,
        author="me",
        version="v2",
        source_url="https://example.test/lora",
    )
    assert updated is not None
    assert updated["display_name"] == "Detail Boost 2"
    assert updated["tags"] == ["detail"]
    assert set(updated["family_compat"]) == {"sdxl", "illustrious"}

    assert library_repo.delete_lora(conn, "detail_boost") is True
    assert library_repo.get_lora(conn, "detail_boost") is None
    assert library_repo.delete_lora(conn, "detail_boost") is False
```

- [ ] **Step 2: Run tests and verify failure**

Run from `backend/`:

```bash
.venv/Scripts/python -m pytest tests/test_library_repo.py -v
```

Expected: fails with missing `create_family`, `update_family`, `delete_family`, `update_model`, `delete_model`, and changed filter signatures.

- [ ] **Step 3: Replace `backend/app/storage/library_repo.py` with complete CRUD**

```python
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
    d["family_compat"] = [
        r[0]
        for r in conn.execute(
            "SELECT family_id FROM lora_family_compat WHERE lora_name = ? ORDER BY family_id",
            (row["name"],),
        )
    ]
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
        clauses.append(
            "EXISTS (SELECT 1 FROM lora_family_compat c "
            "WHERE c.lora_name = loras.name AND c.family_id = ?)"
        )
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


def update_lora(
    conn: sqlite3.Connection,
    name: str,
    *,
    display_name: str,
    description: str,
    tags: list[str],
    trigger_words: list[str],
    family_compat: list[str],
    recommended_weight: float | None = None,
    author: str | None = None,
    version: str | None = None,
    source_url: str | None = None,
) -> dict[str, Any] | None:
    now = _now()
    try:
        conn.execute("BEGIN")
        cur = conn.execute(
            "UPDATE loras SET display_name = ?, description = ?, tags = ?, trigger_words = ?, "
            "recommended_weight = ?, author = ?, version = ?, source_url = ?, updated_at = ? "
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
                name,
            ),
        )
        if cur.rowcount == 0:
            conn.execute("ROLLBACK")
            return None
        conn.execute("DELETE FROM lora_family_compat WHERE lora_name = ?", (name,))
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
    return get_lora(conn, name)


def delete_lora(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute("DELETE FROM loras WHERE name = ?", (name,))
    return cur.rowcount > 0
```

- [ ] **Step 4: Run repository tests**

Run from `backend/`:

```bash
.venv/Scripts/python -m pytest tests/test_library_repo.py -v
```

Expected: all repository tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/storage/library_repo.py backend/tests/test_library_repo.py
git commit -m "feat(backend): complete library repository CRUD"
```

---

## Task 2: Backend Schemas, API Router, and HTTP Tests

**Files:**
- Create: `backend/app/models/library.py`
- Create: `backend/app/api/deps.py`
- Create: `backend/app/api/library.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_library_api.py`

- [ ] **Step 1: Create failing HTTP tests**

Create `backend/tests/test_library_api.py`:

```python
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_conn
from app.main import app
from app.storage import db as db_mod
from app.storage.migrations import apply_pending


@pytest.fixture
def conn(tmp_path):
    c = db_mod.connect(tmp_path / "api.db")
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


def test_family_crud_http(client):
    create = client.post(
        "/api/library/families",
        json={"id": "api_fam", "display_name": "API Family", "prompt_guide": "Guide"},
    )
    assert create.status_code == 201
    assert create.json()["id"] == "api_fam"

    duplicate = client.post(
        "/api/library/families",
        json={"id": "api_fam", "display_name": "API Family", "prompt_guide": "Guide"},
    )
    assert duplicate.status_code == 409

    listed = client.get("/api/library/families", params={"q": "api"})
    assert listed.status_code == 200
    assert [f["id"] for f in listed.json()] == ["api_fam"]

    update = client.put(
        "/api/library/families/api_fam",
        json={"display_name": "API Family 2", "prompt_guide": "Guide 2"},
    )
    assert update.status_code == 200
    assert update.json()["display_name"] == "API Family 2"

    delete = client.delete("/api/library/families/api_fam")
    assert delete.status_code == 204
    assert client.get("/api/library/families/api_fam").status_code == 404


def test_model_crud_http_and_fk_conflict(client):
    missing_family = client.post(
        "/api/library/models",
        json={"name": "bad", "display_name": "Bad", "family_id": "missing"},
    )
    assert missing_family.status_code == 409

    create = client.post(
        "/api/library/models",
        json={
            "name": "juggernaut",
            "display_name": "Juggernaut",
            "family_id": "sdxl",
            "description": "General SDXL model",
        },
    )
    assert create.status_code == 201
    assert create.json()["family_id"] == "sdxl"

    listed = client.get("/api/library/models", params={"family_id": "sdxl", "q": "general"})
    assert [m["name"] for m in listed.json()] == ["juggernaut"]

    update = client.put(
        "/api/library/models/juggernaut",
        json={
            "display_name": "Juggernaut XL",
            "family_id": "sdxl",
            "description": "Updated",
            "author": "RunDiffusion",
            "version": "v10",
            "source_url": "https://example.test/juggernaut",
        },
    )
    assert update.status_code == 200
    assert update.json()["version"] == "v10"

    assert client.delete("/api/library/models/juggernaut").status_code == 204
    assert client.delete("/api/library/models/juggernaut").status_code == 404


def test_lora_crud_http(client):
    create = client.post(
        "/api/library/loras",
        json={
            "name": "cinematic_light",
            "display_name": "Cinematic Light",
            "description": "Rim light and cinematic contrast.",
            "tags": ["light", "mood"],
            "trigger_words": ["cinematic light"],
            "family_compat": ["sdxl", "illustrious"],
            "recommended_weight": 0.8,
            "author": "me",
        },
    )
    assert create.status_code == 201
    assert create.json()["tags"] == ["light", "mood"]

    listed = client.get("/api/library/loras", params={"family_id": "sdxl", "tag": "light"})
    assert [l["name"] for l in listed.json()] == ["cinematic_light"]

    update = client.put(
        "/api/library/loras/cinematic_light",
        json={
            "display_name": "Cinematic Light 2",
            "description": "Softer cinematic light.",
            "tags": ["light"],
            "trigger_words": ["soft cinematic light"],
            "family_compat": ["sdxl"],
            "recommended_weight": 0.65,
            "author": "me",
            "version": "v2",
            "source_url": None,
        },
    )
    assert update.status_code == 200
    assert update.json()["recommended_weight"] == 0.65

    assert client.delete("/api/library/loras/cinematic_light").status_code == 204
    assert client.get("/api/library/loras/cinematic_light").status_code == 404
```

- [ ] **Step 2: Run tests and verify failure**

Run from `backend/`:

```bash
.venv/Scripts/python -m pytest tests/test_library_api.py -v
```

Expected: fails because `app.api.deps` and the router do not exist.

- [ ] **Step 3: Create `backend/app/models/library.py`**

```python
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FamilyOut(StrictModel):
    id: str
    display_name: str
    prompt_guide: str
    created_at: int
    updated_at: int


class FamilyCreate(StrictModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=160)
    prompt_guide: str = Field(min_length=1)


class FamilyUpdate(StrictModel):
    display_name: str = Field(min_length=1, max_length=160)
    prompt_guide: str = Field(min_length=1)


class ModelOut(StrictModel):
    name: str
    display_name: str
    family_id: str
    description: str | None
    author: str | None
    version: str | None
    source_url: str | None
    created_at: int
    updated_at: int


class ModelCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=160)
    family_id: str = Field(min_length=1)
    description: str | None = None
    author: str | None = None
    version: str | None = None
    source_url: HttpUrl | None = None


class ModelUpdate(StrictModel):
    display_name: str = Field(min_length=1, max_length=160)
    family_id: str = Field(min_length=1)
    description: str | None = None
    author: str | None = None
    version: str | None = None
    source_url: HttpUrl | None = None


class LoraOut(StrictModel):
    name: str
    display_name: str
    description: str
    tags: list[str]
    trigger_words: list[str]
    family_compat: list[str]
    recommended_weight: float | None
    author: str | None
    version: str | None
    source_url: str | None
    created_at: int
    updated_at: int


class LoraCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    trigger_words: list[str] = Field(default_factory=list)
    family_compat: list[str] = Field(default_factory=list)
    recommended_weight: float | None = Field(default=None, ge=-2.0, le=2.0)
    author: str | None = None
    version: str | None = None
    source_url: HttpUrl | None = None


class LoraUpdate(StrictModel):
    display_name: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    trigger_words: list[str] = Field(default_factory=list)
    family_compat: list[str] = Field(default_factory=list)
    recommended_weight: float | None = Field(default=None, ge=-2.0, le=2.0)
    author: str | None = None
    version: str | None = None
    source_url: HttpUrl | None = None
```

- [ ] **Step 4: Create `backend/app/api/deps.py`**

```python
from __future__ import annotations

from collections.abc import Iterator
import sqlite3

from app.storage.db import connect


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
```

- [ ] **Step 5: Create `backend/app/api/library.py`**

```python
from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.deps import get_conn
from app.models.library import (
    FamilyCreate,
    FamilyOut,
    FamilyUpdate,
    LoraCreate,
    LoraOut,
    LoraUpdate,
    ModelCreate,
    ModelOut,
    ModelUpdate,
)
from app.storage import library_repo

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

router = APIRouter(prefix="/api/library", tags=["library"])


def _conflict(exc: sqlite3.IntegrityError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _not_found(kind: str, key: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{kind} not found: {key}")


def _dump(data):
    return data.model_dump(mode="json")


@router.get("/families", response_model=list[FamilyOut])
def list_families(conn: Conn, q: str | None = None):
    return library_repo.list_families(conn, q=q)


@router.get("/families/{family_id}", response_model=FamilyOut)
def get_family(family_id: str, conn: Conn):
    row = library_repo.get_family(conn, family_id)
    if row is None:
        raise _not_found("family", family_id)
    return row


@router.post("/families", response_model=FamilyOut, status_code=status.HTTP_201_CREATED)
def create_family(body: FamilyCreate, conn: Conn):
    try:
        return library_repo.create_family(conn, **body.model_dump())
    except sqlite3.IntegrityError as exc:
        raise _conflict(exc) from exc


@router.put("/families/{family_id}", response_model=FamilyOut)
def update_family(family_id: str, body: FamilyUpdate, conn: Conn):
    try:
        row = library_repo.update_family(conn, family_id, **body.model_dump())
    except sqlite3.IntegrityError as exc:
        raise _conflict(exc) from exc
    if row is None:
        raise _not_found("family", family_id)
    return row


@router.delete("/families/{family_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_family(family_id: str, conn: Conn):
    try:
        deleted = library_repo.delete_family(conn, family_id)
    except sqlite3.IntegrityError as exc:
        raise _conflict(exc) from exc
    if not deleted:
        raise _not_found("family", family_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/models", response_model=list[ModelOut])
def list_models(conn: Conn, family_id: str | None = None, q: str | None = None):
    return library_repo.list_models(conn, family_id=family_id, q=q)


@router.get("/models/{name}", response_model=ModelOut)
def get_model(name: str, conn: Conn):
    row = library_repo.get_model(conn, name)
    if row is None:
        raise _not_found("model", name)
    return row


@router.post("/models", response_model=ModelOut, status_code=status.HTTP_201_CREATED)
def create_model(body: ModelCreate, conn: Conn):
    try:
        return library_repo.create_model(conn, **_dump(body))
    except sqlite3.IntegrityError as exc:
        raise _conflict(exc) from exc


@router.put("/models/{name}", response_model=ModelOut)
def update_model(name: str, body: ModelUpdate, conn: Conn):
    try:
        row = library_repo.update_model(conn, name, **_dump(body))
    except sqlite3.IntegrityError as exc:
        raise _conflict(exc) from exc
    if row is None:
        raise _not_found("model", name)
    return row


@router.delete("/models/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_model(name: str, conn: Conn):
    try:
        deleted = library_repo.delete_model(conn, name)
    except sqlite3.IntegrityError as exc:
        raise _conflict(exc) from exc
    if not deleted:
        raise _not_found("model", name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/loras", response_model=list[LoraOut])
def list_loras(
    conn: Conn,
    family_id: str | None = None,
    tag: str | None = None,
    q: str | None = None,
):
    return library_repo.list_loras(conn, family_id=family_id, tag=tag, q=q)


@router.get("/loras/{name}", response_model=LoraOut)
def get_lora(name: str, conn: Conn):
    row = library_repo.get_lora(conn, name)
    if row is None:
        raise _not_found("lora", name)
    return row


@router.post("/loras", response_model=LoraOut, status_code=status.HTTP_201_CREATED)
def create_lora(body: LoraCreate, conn: Conn):
    try:
        return library_repo.create_lora(conn, **_dump(body))
    except sqlite3.IntegrityError as exc:
        raise _conflict(exc) from exc


@router.put("/loras/{name}", response_model=LoraOut)
def update_lora(name: str, body: LoraUpdate, conn: Conn):
    try:
        row = library_repo.update_lora(conn, name, **_dump(body))
    except sqlite3.IntegrityError as exc:
        raise _conflict(exc) from exc
    if row is None:
        raise _not_found("lora", name)
    return row


@router.delete("/loras/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lora(name: str, conn: Conn):
    deleted = library_repo.delete_lora(conn, name)
    if not deleted:
        raise _not_found("lora", name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 6: Include router in `backend/app/main.py`**

Add the import and include call:

```python
from app.api.library import router as library_router

# after middleware setup
app.include_router(library_router)
```

The resulting top of `main.py` should keep `/health` unchanged and include the router before path operations.

- [ ] **Step 7: Run backend tests**

Run from `backend/`:

```bash
.venv/Scripts/python -m pytest tests/test_library_repo.py tests/test_library_api.py -v
```

Expected: all selected tests pass.

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/library.py backend/app/api/deps.py backend/app/api/library.py backend/app/main.py backend/tests/test_library_api.py
git commit -m "feat(backend): expose library CRUD API"
```

---

## Task 3: Frontend Dependencies and Typed Library API

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/pnpm-lock.yaml`
- Create: `frontend/src/api/library.ts`

- [ ] **Step 1: Add markdown editor dependency**

Run from `frontend/`:

```bash
pnpm add @uiw/react-md-editor
```

Expected: `package.json` gains `@uiw/react-md-editor` and `pnpm-lock.yaml` is updated.

- [ ] **Step 2: Create `frontend/src/api/library.ts`**

```ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";

export type Family = {
  id: string;
  display_name: string;
  prompt_guide: string;
  created_at: number;
  updated_at: number;
};

export type FamilyCreate = Pick<Family, "id" | "display_name" | "prompt_guide">;
export type FamilyUpdate = Pick<Family, "display_name" | "prompt_guide">;

export type Model = {
  name: string;
  display_name: string;
  family_id: string;
  description: string | null;
  author: string | null;
  version: string | null;
  source_url: string | null;
  created_at: number;
  updated_at: number;
};

export type ModelCreate = Omit<Model, "created_at" | "updated_at">;
export type ModelUpdate = Omit<ModelCreate, "name">;

export type Lora = {
  name: string;
  display_name: string;
  description: string;
  tags: string[];
  trigger_words: string[];
  family_compat: string[];
  recommended_weight: number | null;
  author: string | null;
  version: string | null;
  source_url: string | null;
  created_at: number;
  updated_at: number;
};

export type LoraCreate = Omit<Lora, "created_at" | "updated_at">;
export type LoraUpdate = Omit<LoraCreate, "name">;

export const libraryKeys = {
  families: (q = "") => ["library", "families", q] as const,
  models: (familyId = "", q = "") => ["library", "models", familyId, q] as const,
  loras: (familyId = "", tag = "", q = "") => ["library", "loras", familyId, tag, q] as const,
};

function qs(params: Record<string, string | undefined>) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value) search.set(key, value);
  });
  const s = search.toString();
  return s ? `?${s}` : "";
}

export const libraryApi = {
  listFamilies: (q?: string) => apiFetch<Family[]>(`/api/library/families${qs({ q })}`),
  createFamily: (body: FamilyCreate) =>
    apiFetch<Family>("/api/library/families", { method: "POST", body: JSON.stringify(body) }),
  updateFamily: (id: string, body: FamilyUpdate) =>
    apiFetch<Family>(`/api/library/families/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteFamily: (id: string) =>
    apiFetch<void>(`/api/library/families/${encodeURIComponent(id)}`, { method: "DELETE" }),

  listModels: (params: { family_id?: string; q?: string } = {}) =>
    apiFetch<Model[]>(`/api/library/models${qs(params)}`),
  createModel: (body: ModelCreate) =>
    apiFetch<Model>("/api/library/models", { method: "POST", body: JSON.stringify(body) }),
  updateModel: (name: string, body: ModelUpdate) =>
    apiFetch<Model>(`/api/library/models/${encodeURIComponent(name)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteModel: (name: string) =>
    apiFetch<void>(`/api/library/models/${encodeURIComponent(name)}`, { method: "DELETE" }),

  listLoras: (params: { family_id?: string; tag?: string; q?: string } = {}) =>
    apiFetch<Lora[]>(`/api/library/loras${qs(params)}`),
  createLora: (body: LoraCreate) =>
    apiFetch<Lora>("/api/library/loras", { method: "POST", body: JSON.stringify(body) }),
  updateLora: (name: string, body: LoraUpdate) =>
    apiFetch<Lora>(`/api/library/loras/${encodeURIComponent(name)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteLora: (name: string) =>
    apiFetch<void>(`/api/library/loras/${encodeURIComponent(name)}`, { method: "DELETE" }),
};

export function useFamilies(q = "") {
  return useQuery({ queryKey: libraryKeys.families(q), queryFn: () => libraryApi.listFamilies(q) });
}

export function useModels(params: { family_id?: string; q?: string } = {}) {
  return useQuery({
    queryKey: libraryKeys.models(params.family_id ?? "", params.q ?? ""),
    queryFn: () => libraryApi.listModels(params),
  });
}

export function useLoras(params: { family_id?: string; tag?: string; q?: string } = {}) {
  return useQuery({
    queryKey: libraryKeys.loras(params.family_id ?? "", params.tag ?? "", params.q ?? ""),
    queryFn: () => libraryApi.listLoras(params),
  });
}

export function useLibraryInvalidation() {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: ["library"] });
}
```

- [ ] **Step 3: Fix `apiFetch` for 204 responses**

Modify `frontend/src/api/client.ts` so deletes do not try to parse an empty response:

```ts
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    throw new ApiError(res.status, await res.text());
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return res.json() as Promise<T>;
}
```

- [ ] **Step 4: Typecheck**

Run from `frontend/`:

```bash
pnpm build
```

Expected: build passes.

- [ ] **Step 5: Commit**

```bash
git add frontend/package.json frontend/pnpm-lock.yaml frontend/src/api/client.ts frontend/src/api/library.ts
git commit -m "feat(frontend): add typed library API client"
```

---

## Task 4: Shared Library UI Building Blocks

**Files:**
- Create: `frontend/src/components/molecules/FormField.module.css`
- Create: `frontend/src/components/molecules/FormField.tsx`
- Create: `frontend/src/components/molecules/MarkdownField.tsx`
- Create: `frontend/src/components/molecules/TextListInput.tsx`
- Create: `frontend/src/components/molecules/LibraryList.module.css`
- Create: `frontend/src/components/molecules/LibraryList.tsx`
- Create: `frontend/src/components/organisms/LibraryCrud.module.css`
- Create: `frontend/src/components/organisms/LibraryCrud.tsx`

- [ ] **Step 1: Create form field styles and component**

`frontend/src/components/molecules/FormField.module.css`:

```css
.field {
  display: grid;
  gap: 6px;
}

.label {
  color: var(--text-muted);
  font-size: var(--text-xs);
  font-weight: 600;
}

.control {
  width: 100%;
  min-height: 34px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  font: inherit;
  padding: 7px 10px;
}

.textarea {
  min-height: 120px;
  resize: vertical;
}

.hint {
  color: var(--text-subtle);
  font-size: var(--text-xs);
}

.error {
  color: var(--danger);
  font-size: var(--text-xs);
}
```

`frontend/src/components/molecules/FormField.tsx`:

```tsx
import type { InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from "react";
import styles from "./FormField.module.css";

type BaseProps = {
  label: string;
  hint?: string;
  error?: string;
  children?: ReactNode;
};

export function FormField({
  label,
  hint,
  error,
  children,
}: BaseProps) {
  return (
    <label className={styles.field}>
      <span className={styles.label}>{label}</span>
      {children}
      {hint && <span className={styles.hint}>{hint}</span>}
      {error && <span className={styles.error}>{error}</span>}
    </label>
  );
}

export function TextInput(props: BaseProps & InputHTMLAttributes<HTMLInputElement>) {
  const { label, hint, error, ...rest } = props;
  return (
    <FormField label={label} hint={hint} error={error}>
      <input className={styles.control} {...rest} />
    </FormField>
  );
}

export function TextArea(props: BaseProps & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const { label, hint, error, ...rest } = props;
  return (
    <FormField label={label} hint={hint} error={error}>
      <textarea className={`${styles.control} ${styles.textarea}`} {...rest} />
    </FormField>
  );
}
```

- [ ] **Step 2: Create `MarkdownField.tsx`**

```tsx
import MDEditor from "@uiw/react-md-editor";
import { FormField } from "./FormField";

export function MarkdownField({
  label,
  value,
  onChange,
  hint,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: string;
}) {
  return (
    <FormField label={label} hint={hint}>
      <div data-color-mode="dark">
        <MDEditor height={220} value={value} onChange={(next) => onChange(next ?? "")} />
      </div>
    </FormField>
  );
}
```

- [ ] **Step 3: Create `TextListInput.tsx`**

```tsx
import { TextInput } from "./FormField";

export function TextListInput({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string[];
  onChange: (value: string[]) => void;
  placeholder?: string;
}) {
  return (
    <TextInput
      label={label}
      value={value.join(", ")}
      placeholder={placeholder}
      onChange={(event) => {
        const next = event.currentTarget.value
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean);
        onChange([...new Set(next)]);
      }}
    />
  );
}
```

- [ ] **Step 4: Create list shell**

`frontend/src/components/molecules/LibraryList.module.css`:

```css
.list {
  border-right: 1px solid var(--border);
  min-width: 300px;
  max-width: 360px;
  background: var(--surface);
  display: grid;
  grid-template-rows: auto 1fr;
}

.head {
  padding: 14px;
  border-bottom: 1px solid var(--border);
  display: grid;
  gap: 10px;
}

.titleRow {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.title {
  margin: 0;
  font-size: var(--text-lg);
}

.search {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 10px;
  background: var(--bg);
  color: var(--text);
}

.rows {
  overflow: auto;
  padding: 8px;
}

.row {
  width: 100%;
  display: grid;
  gap: 4px;
  padding: 10px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--text);
  text-align: left;
  cursor: pointer;
}

.row:hover,
.selected {
  background: var(--bg-muted);
}

.rowName {
  font-weight: 600;
}

.rowMeta {
  color: var(--text-subtle);
  font-size: var(--text-xs);
}

.empty {
  padding: 20px;
  color: var(--text-subtle);
  font-size: var(--text-sm);
}
```

`frontend/src/components/molecules/LibraryList.tsx`:

```tsx
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import styles from "./LibraryList.module.css";

export type LibraryListItem = {
  id: string;
  title: string;
  meta?: string;
};

export function LibraryList({
  title,
  count,
  search,
  onSearch,
  selectedId,
  items,
  onSelect,
  onNew,
}: {
  title: string;
  count: number;
  search: string;
  onSearch: (value: string) => void;
  selectedId: string | null;
  items: LibraryListItem[];
  onSelect: (id: string) => void;
  onNew: () => void;
}) {
  return (
    <aside className={styles.list}>
      <div className={styles.head}>
        <div className={styles.titleRow}>
          <h2 className={styles.title}>{title}</h2>
          <Button size="sm" variant="primary" icon={<Icon name="Plus" />} onClick={onNew}>
            New
          </Button>
        </div>
        <input
          className={styles.search}
          value={search}
          placeholder={`Search ${title.toLowerCase()}...`}
          onChange={(event) => onSearch(event.currentTarget.value)}
        />
        <span className={styles.rowMeta}>{count} total</span>
      </div>
      <div className={styles.rows}>
        {items.length === 0 ? (
          <div className={styles.empty}>No matches</div>
        ) : (
          items.map((item) => (
            <button
              key={item.id}
              className={`${styles.row} ${item.id === selectedId ? styles.selected : ""}`}
              onClick={() => onSelect(item.id)}
            >
              <span className={styles.rowName}>{item.title}</span>
              {item.meta && <span className={styles.rowMeta}>{item.meta}</span>}
            </button>
          ))
        )}
      </div>
    </aside>
  );
}
```

- [ ] **Step 5: Create master/detail shell**

`frontend/src/components/organisms/LibraryCrud.module.css`:

```css
.page {
  height: calc(100vh - 48px);
  display: grid;
  grid-template-columns: minmax(300px, 360px) minmax(0, 1fr);
  border: 1px solid var(--border);
  background: var(--bg);
}

.detail {
  min-width: 0;
  overflow: auto;
  padding: 24px;
}

.detailHead {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 20px;
}

.eyebrow {
  color: var(--text-subtle);
  font-size: var(--text-xs);
  font-weight: 700;
  text-transform: uppercase;
}

.title {
  margin: 4px 0 0;
  font-size: var(--text-2xl);
}

.actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.body {
  display: grid;
  gap: 16px;
  max-width: 900px;
}

.form {
  display: grid;
  gap: 16px;
  max-width: 840px;
}

.grid2 {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.error {
  border: 1px solid var(--danger);
  color: var(--danger);
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  padding: 10px 12px;
  border-radius: 6px;
}
```

`frontend/src/components/organisms/LibraryCrud.tsx`:

```tsx
import type { ReactNode } from "react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { LibraryList, type LibraryListItem } from "@/components/molecules/LibraryList";
import styles from "./LibraryCrud.module.css";

export type CrudMode = "detail" | "create" | "edit";

export function LibraryCrud({
  title,
  count,
  search,
  onSearch,
  items,
  selectedId,
  onSelect,
  onNew,
  mode,
  detailTitle,
  detailEyebrow,
  onEdit,
  onDelete,
  children,
}: {
  title: string;
  count: number;
  search: string;
  onSearch: (value: string) => void;
  items: LibraryListItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  mode: CrudMode;
  detailTitle: string;
  detailEyebrow: string;
  onEdit?: () => void;
  onDelete?: () => void;
  children: ReactNode;
}) {
  return (
    <div className={styles.page}>
      <LibraryList
        title={title}
        count={count}
        search={search}
        onSearch={onSearch}
        selectedId={selectedId}
        items={items}
        onSelect={onSelect}
        onNew={onNew}
      />
      <section className={styles.detail}>
        <div className={styles.detailHead}>
          <div>
            <div className={styles.eyebrow}>{detailEyebrow}</div>
            <h1 className={styles.title}>{detailTitle}</h1>
          </div>
          {mode === "detail" && (
            <div className={styles.actions}>
              {onDelete && (
                <Button size="sm" icon={<Icon name="Trash2" />} onClick={onDelete}>
                  Delete
                </Button>
              )}
              {onEdit && (
                <Button size="sm" variant="primary" onClick={onEdit}>
                  Edit
                </Button>
              )}
            </div>
          )}
        </div>
        <div className={mode === "detail" ? styles.body : styles.form}>{children}</div>
      </section>
    </div>
  );
}

export const libraryCrudStyles = styles;
```

- [ ] **Step 6: Build**

Run from `frontend/`:

```bash
pnpm build
```

Expected: build passes.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/molecules frontend/src/components/organisms/LibraryCrud.module.css frontend/src/components/organisms/LibraryCrud.tsx
git commit -m "feat(frontend): add reusable library CRUD UI shell"
```

---

## Task 5: Families Route

**Files:**
- Create: `frontend/src/components/organisms/FamilyForm.tsx`
- Modify: `frontend/src/routes/library/families.tsx`

- [ ] **Step 1: Create `FamilyForm.tsx`**

```tsx
import { useState } from "react";
import { Button } from "@/components/atoms/Button";
import { TextInput } from "@/components/molecules/FormField";
import { MarkdownField } from "@/components/molecules/MarkdownField";
import type { Family, FamilyCreate, FamilyUpdate } from "@/api/library";

export function FamilyForm({
  family,
  onCancel,
  onSubmit,
  isSaving,
}: {
  family?: Family;
  onCancel: () => void;
  onSubmit: (body: FamilyCreate | FamilyUpdate) => void;
  isSaving: boolean;
}) {
  const [id, setId] = useState(family?.id ?? "");
  const [displayName, setDisplayName] = useState(family?.display_name ?? "");
  const [promptGuide, setPromptGuide] = useState(family?.prompt_guide ?? "");

  const canSave = displayName.trim() !== "" && promptGuide.trim() !== "" && (family || id.trim() !== "");

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (!canSave) return;
        const common = { display_name: displayName.trim(), prompt_guide: promptGuide.trim() };
        onSubmit(family ? common : { id: id.trim(), ...common });
      }}
    >
      {!family && (
        <TextInput
          label="ID"
          value={id}
          placeholder="sdxl"
          onChange={(event) => setId(event.currentTarget.value)}
        />
      )}
      <TextInput
        label="Display name"
        value={displayName}
        placeholder="SDXL"
        onChange={(event) => setDisplayName(event.currentTarget.value)}
      />
      <MarkdownField
        label="Prompt guide"
        value={promptGuide}
        onChange={setPromptGuide}
        hint="LLM sees this verbatim for every session using this family."
      />
      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <Button type="button" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={!canSave || isSaving}>
          {isSaving ? "Saving..." : "Save"}
        </Button>
      </div>
    </form>
  );
}
```

- [ ] **Step 2: Replace `frontend/src/routes/library/families.tsx`**

```tsx
import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  libraryApi,
  useFamilies,
  useLibraryInvalidation,
  type Family,
  type FamilyCreate,
  type FamilyUpdate,
} from "@/api/library";
import { FamilyForm } from "@/components/organisms/FamilyForm";
import { LibraryCrud, type CrudMode } from "@/components/organisms/LibraryCrud";

export default function FamiliesRoute() {
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mode, setMode] = useState<CrudMode>("detail");
  const invalidate = useLibraryInvalidation();
  const families = useFamilies(search);

  const selected = useMemo(() => {
    const rows = families.data ?? [];
    return rows.find((family) => family.id === selectedId) ?? rows[0] ?? null;
  }, [families.data, selectedId]);

  const create = useMutation({ mutationFn: libraryApi.createFamily, onSuccess: invalidate });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: FamilyUpdate }) => libraryApi.updateFamily(id, body),
    onSuccess: invalidate,
  });
  const remove = useMutation({ mutationFn: libraryApi.deleteFamily, onSuccess: invalidate });

  const rows = (families.data ?? []).map((family) => ({
    id: family.id,
    title: family.display_name,
    meta: family.id,
  }));

  function submit(body: FamilyCreate | FamilyUpdate) {
    if (mode === "create") {
      create.mutate(body as FamilyCreate, {
        onSuccess: (family: Family) => {
          setSelectedId(family.id);
          setMode("detail");
        },
      });
      return;
    }
    if (selected) {
      update.mutate(
        { id: selected.id, body: body as FamilyUpdate },
        { onSuccess: () => setMode("detail") },
      );
    }
  }

  const error = create.error ?? update.error ?? remove.error ?? families.error;

  return (
    <LibraryCrud
      title="Families"
      count={families.data?.length ?? 0}
      search={search}
      onSearch={setSearch}
      items={rows}
      selectedId={selected?.id ?? null}
      onSelect={(id) => {
        setSelectedId(id);
        setMode("detail");
      }}
      onNew={() => setMode("create")}
      mode={mode}
      detailEyebrow="Family"
      detailTitle={mode === "create" ? "New family" : selected?.display_name ?? "No family selected"}
      onEdit={selected ? () => setMode("edit") : undefined}
      onDelete={
        selected
          ? () => remove.mutate(selected.id, { onSuccess: () => setSelectedId(null) })
          : undefined
      }
    >
      {error && <div role="alert">{String(error)}</div>}
      {mode === "create" && (
        <FamilyForm onCancel={() => setMode("detail")} onSubmit={submit} isSaving={create.isPending} />
      )}
      {mode === "edit" && selected && (
        <FamilyForm
          family={selected}
          onCancel={() => setMode("detail")}
          onSubmit={submit}
          isSaving={update.isPending}
        />
      )}
      {mode === "detail" && selected && (
        <>
          <p>
            <strong>ID:</strong> {selected.id}
          </p>
          <pre style={{ whiteSpace: "pre-wrap" }}>{selected.prompt_guide}</pre>
        </>
      )}
    </LibraryCrud>
  );
}
```

- [ ] **Step 3: Run build**

Run from `frontend/`:

```bash
pnpm build
```

Expected: TypeScript build passes.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/organisms/FamilyForm.tsx frontend/src/routes/library/families.tsx
git commit -m "feat(frontend): implement families CRUD route"
```

---

## Task 6: Models Route

**Files:**
- Create: `frontend/src/components/organisms/ModelForm.tsx`
- Modify: `frontend/src/routes/library/models.tsx`

- [ ] **Step 1: Create `ModelForm.tsx`**

```tsx
import { useState } from "react";
import { Button } from "@/components/atoms/Button";
import { TextArea, TextInput } from "@/components/molecules/FormField";
import type { Family, Model, ModelCreate, ModelUpdate } from "@/api/library";

export function ModelForm({
  model,
  families,
  onCancel,
  onSubmit,
  isSaving,
}: {
  model?: Model;
  families: Family[];
  onCancel: () => void;
  onSubmit: (body: ModelCreate | ModelUpdate) => void;
  isSaving: boolean;
}) {
  const [name, setName] = useState(model?.name ?? "");
  const [displayName, setDisplayName] = useState(model?.display_name ?? "");
  const [familyId, setFamilyId] = useState(model?.family_id ?? families[0]?.id ?? "");
  const [description, setDescription] = useState(model?.description ?? "");
  const [author, setAuthor] = useState(model?.author ?? "");
  const [version, setVersion] = useState(model?.version ?? "");
  const [sourceUrl, setSourceUrl] = useState(model?.source_url ?? "");

  const canSave = displayName.trim() !== "" && familyId !== "" && (model || name.trim() !== "");

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (!canSave) return;
        const common = {
          display_name: displayName.trim(),
          family_id: familyId,
          description: description.trim() || null,
          author: author.trim() || null,
          version: version.trim() || null,
          source_url: sourceUrl.trim() || null,
        };
        onSubmit(model ? common : { name: name.trim(), ...common });
      }}
    >
      {!model && (
        <TextInput label="Name" value={name} onChange={(event) => setName(event.currentTarget.value)} />
      )}
      <TextInput
        label="Display name"
        value={displayName}
        onChange={(event) => setDisplayName(event.currentTarget.value)}
      />
      <label>
        <span>Family</span>
        <select value={familyId} onChange={(event) => setFamilyId(event.currentTarget.value)}>
          {families.map((family) => (
            <option key={family.id} value={family.id}>
              {family.display_name}
            </option>
          ))}
        </select>
      </label>
      <TextArea
        label="Description"
        value={description}
        onChange={(event) => setDescription(event.currentTarget.value)}
      />
      <TextInput label="Author" value={author} onChange={(event) => setAuthor(event.currentTarget.value)} />
      <TextInput label="Version" value={version} onChange={(event) => setVersion(event.currentTarget.value)} />
      <TextInput
        label="Source URL"
        value={sourceUrl}
        onChange={(event) => setSourceUrl(event.currentTarget.value)}
      />
      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <Button type="button" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={!canSave || isSaving}>
          {isSaving ? "Saving..." : "Save"}
        </Button>
      </div>
    </form>
  );
}
```

- [ ] **Step 2: Replace `frontend/src/routes/library/models.tsx`**

```tsx
import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  libraryApi,
  useFamilies,
  useLibraryInvalidation,
  useModels,
  type Model,
  type ModelCreate,
  type ModelUpdate,
} from "@/api/library";
import { LibraryCrud, type CrudMode } from "@/components/organisms/LibraryCrud";
import { ModelForm } from "@/components/organisms/ModelForm";

export default function ModelsRoute() {
  const [search, setSearch] = useState("");
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [mode, setMode] = useState<CrudMode>("detail");
  const invalidate = useLibraryInvalidation();
  const families = useFamilies();
  const models = useModels({ q: search });

  const selected = useMemo(() => {
    const rows = models.data ?? [];
    return rows.find((model) => model.name === selectedName) ?? rows[0] ?? null;
  }, [models.data, selectedName]);

  const create = useMutation({ mutationFn: libraryApi.createModel, onSuccess: invalidate });
  const update = useMutation({
    mutationFn: ({ name, body }: { name: string; body: ModelUpdate }) => libraryApi.updateModel(name, body),
    onSuccess: invalidate,
  });
  const remove = useMutation({ mutationFn: libraryApi.deleteModel, onSuccess: invalidate });

  function submit(body: ModelCreate | ModelUpdate) {
    if (mode === "create") {
      create.mutate(body as ModelCreate, {
        onSuccess: (model: Model) => {
          setSelectedName(model.name);
          setMode("detail");
        },
      });
      return;
    }
    if (selected) {
      update.mutate({ name: selected.name, body: body as ModelUpdate }, { onSuccess: () => setMode("detail") });
    }
  }

  const rows = (models.data ?? []).map((model) => ({
    id: model.name,
    title: model.display_name,
    meta: model.family_id,
  }));
  const familyRows = families.data ?? [];
  const error = create.error ?? update.error ?? remove.error ?? models.error ?? families.error;

  return (
    <LibraryCrud
      title="Models"
      count={models.data?.length ?? 0}
      search={search}
      onSearch={setSearch}
      items={rows}
      selectedId={selected?.name ?? null}
      onSelect={(id) => {
        setSelectedName(id);
        setMode("detail");
      }}
      onNew={() => setMode("create")}
      mode={mode}
      detailEyebrow="Model"
      detailTitle={mode === "create" ? "New model" : selected?.display_name ?? "No model selected"}
      onEdit={selected ? () => setMode("edit") : undefined}
      onDelete={
        selected ? () => remove.mutate(selected.name, { onSuccess: () => setSelectedName(null) }) : undefined
      }
    >
      {error && <div role="alert">{String(error)}</div>}
      {mode === "create" && (
        <ModelForm
          families={familyRows}
          onCancel={() => setMode("detail")}
          onSubmit={submit}
          isSaving={create.isPending}
        />
      )}
      {mode === "edit" && selected && (
        <ModelForm
          model={selected}
          families={familyRows}
          onCancel={() => setMode("detail")}
          onSubmit={submit}
          isSaving={update.isPending}
        />
      )}
      {mode === "detail" && selected && (
        <>
          <p><strong>Name:</strong> {selected.name}</p>
          <p><strong>Family:</strong> {selected.family_id}</p>
          <p>{selected.description ?? "No description"}</p>
        </>
      )}
    </LibraryCrud>
  );
}
```

- [ ] **Step 3: Run build**

Run from `frontend/`:

```bash
pnpm build
```

Expected: TypeScript build passes.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/organisms/ModelForm.tsx frontend/src/routes/library/models.tsx
git commit -m "feat(frontend): implement models CRUD route"
```

---

## Task 7: LoRAs Route

**Files:**
- Create: `frontend/src/components/organisms/LoraForm.tsx`
- Modify: `frontend/src/routes/library/loras.tsx`

- [ ] **Step 1: Create `LoraForm.tsx`**

```tsx
import { useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Badge } from "@/components/atoms/Badge";
import { TextInput } from "@/components/molecules/FormField";
import { MarkdownField } from "@/components/molecules/MarkdownField";
import { TextListInput } from "@/components/molecules/TextListInput";
import type { Family, Lora, LoraCreate, LoraUpdate } from "@/api/library";

export function LoraForm({
  lora,
  families,
  onCancel,
  onSubmit,
  isSaving,
}: {
  lora?: Lora;
  families: Family[];
  onCancel: () => void;
  onSubmit: (body: LoraCreate | LoraUpdate) => void;
  isSaving: boolean;
}) {
  const [name, setName] = useState(lora?.name ?? "");
  const [displayName, setDisplayName] = useState(lora?.display_name ?? "");
  const [description, setDescription] = useState(lora?.description ?? "");
  const [tags, setTags] = useState<string[]>(lora?.tags ?? []);
  const [triggerWords, setTriggerWords] = useState<string[]>(lora?.trigger_words ?? []);
  const [familyCompat, setFamilyCompat] = useState<string[]>(lora?.family_compat ?? []);
  const [recommendedWeight, setRecommendedWeight] = useState(
    lora?.recommended_weight === null || lora?.recommended_weight === undefined
      ? ""
      : String(lora.recommended_weight),
  );
  const [author, setAuthor] = useState(lora?.author ?? "");
  const [version, setVersion] = useState(lora?.version ?? "");
  const [sourceUrl, setSourceUrl] = useState(lora?.source_url ?? "");

  const canSave =
    displayName.trim() !== "" && description.trim() !== "" && familyCompat.length > 0 && (lora || name.trim() !== "");

  function toggleFamily(id: string) {
    setFamilyCompat((current) =>
      current.includes(id) ? current.filter((value) => value !== id) : [...current, id],
    );
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (!canSave) return;
        const weight = recommendedWeight.trim() === "" ? null : Number(recommendedWeight);
        const common = {
          display_name: displayName.trim(),
          description: description.trim(),
          tags,
          trigger_words: triggerWords,
          family_compat: familyCompat,
          recommended_weight: Number.isFinite(weight) ? weight : null,
          author: author.trim() || null,
          version: version.trim() || null,
          source_url: sourceUrl.trim() || null,
        };
        onSubmit(lora ? common : { name: name.trim(), ...common });
      }}
    >
      {!lora && <TextInput label="Name" value={name} onChange={(event) => setName(event.currentTarget.value)} />}
      <TextInput
        label="Display name"
        value={displayName}
        onChange={(event) => setDisplayName(event.currentTarget.value)}
      />
      <MarkdownField
        label="Description"
        value={description}
        onChange={setDescription}
        hint="Markdown. LLM sees this when picking LoRAs."
      />
      <TextListInput label="Tags" value={tags} onChange={setTags} placeholder="detail, light, portrait" />
      <TextListInput
        label="Trigger words"
        value={triggerWords}
        onChange={setTriggerWords}
        placeholder="cinematic light, rim light"
      />
      <div>
        <div style={{ marginBottom: 8 }}>Family compatibility</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {families.map((family) => (
            <button type="button" key={family.id} onClick={() => toggleFamily(family.id)}>
              <Badge variant={familyCompat.includes(family.id) ? "accent" : "neutral"}>
                {family.display_name}
              </Badge>
            </button>
          ))}
        </div>
      </div>
      <TextInput
        label="Recommended weight"
        type="number"
        step="0.05"
        min="-2"
        max="2"
        value={recommendedWeight}
        onChange={(event) => setRecommendedWeight(event.currentTarget.value)}
      />
      <TextInput label="Author" value={author} onChange={(event) => setAuthor(event.currentTarget.value)} />
      <TextInput label="Version" value={version} onChange={(event) => setVersion(event.currentTarget.value)} />
      <TextInput label="Source URL" value={sourceUrl} onChange={(event) => setSourceUrl(event.currentTarget.value)} />
      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <Button type="button" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={!canSave || isSaving}>
          {isSaving ? "Saving..." : "Save"}
        </Button>
      </div>
    </form>
  );
}
```

- [ ] **Step 2: Replace `frontend/src/routes/library/loras.tsx`**

```tsx
import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Badge } from "@/components/atoms/Badge";
import {
  libraryApi,
  useFamilies,
  useLibraryInvalidation,
  useLoras,
  type Lora,
  type LoraCreate,
  type LoraUpdate,
} from "@/api/library";
import { LibraryCrud, type CrudMode } from "@/components/organisms/LibraryCrud";
import { LoraForm } from "@/components/organisms/LoraForm";

export default function LorasRoute() {
  const [search, setSearch] = useState("");
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [mode, setMode] = useState<CrudMode>("detail");
  const invalidate = useLibraryInvalidation();
  const families = useFamilies();
  const loras = useLoras({ q: search });

  const selected = useMemo(() => {
    const rows = loras.data ?? [];
    return rows.find((lora) => lora.name === selectedName) ?? rows[0] ?? null;
  }, [loras.data, selectedName]);

  const create = useMutation({ mutationFn: libraryApi.createLora, onSuccess: invalidate });
  const update = useMutation({
    mutationFn: ({ name, body }: { name: string; body: LoraUpdate }) => libraryApi.updateLora(name, body),
    onSuccess: invalidate,
  });
  const remove = useMutation({ mutationFn: libraryApi.deleteLora, onSuccess: invalidate });

  function submit(body: LoraCreate | LoraUpdate) {
    if (mode === "create") {
      create.mutate(body as LoraCreate, {
        onSuccess: (lora: Lora) => {
          setSelectedName(lora.name);
          setMode("detail");
        },
      });
      return;
    }
    if (selected) {
      update.mutate({ name: selected.name, body: body as LoraUpdate }, { onSuccess: () => setMode("detail") });
    }
  }

  const rows = (loras.data ?? []).map((lora) => ({
    id: lora.name,
    title: lora.display_name,
    meta: `${lora.family_compat.join(", ")} | ${lora.tags.join(", ")}`,
  }));
  const familyRows = families.data ?? [];
  const error = create.error ?? update.error ?? remove.error ?? loras.error ?? families.error;

  return (
    <LibraryCrud
      title="LoRAs"
      count={loras.data?.length ?? 0}
      search={search}
      onSearch={setSearch}
      items={rows}
      selectedId={selected?.name ?? null}
      onSelect={(id) => {
        setSelectedName(id);
        setMode("detail");
      }}
      onNew={() => setMode("create")}
      mode={mode}
      detailEyebrow="LoRA"
      detailTitle={mode === "create" ? "New LoRA" : selected?.display_name ?? "No LoRA selected"}
      onEdit={selected ? () => setMode("edit") : undefined}
      onDelete={
        selected ? () => remove.mutate(selected.name, { onSuccess: () => setSelectedName(null) }) : undefined
      }
    >
      {error && <div role="alert">{String(error)}</div>}
      {mode === "create" && (
        <LoraForm
          families={familyRows}
          onCancel={() => setMode("detail")}
          onSubmit={submit}
          isSaving={create.isPending}
        />
      )}
      {mode === "edit" && selected && (
        <LoraForm
          lora={selected}
          families={familyRows}
          onCancel={() => setMode("detail")}
          onSubmit={submit}
          isSaving={update.isPending}
        />
      )}
      {mode === "detail" && selected && (
        <>
          <p><strong>Name:</strong> {selected.name}</p>
          <p><strong>Weight:</strong> {selected.recommended_weight ?? "none"}</p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {selected.family_compat.map((family) => <Badge key={family}>{family}</Badge>)}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {selected.tags.map((tag) => <Badge key={tag} variant="accent">{tag}</Badge>)}
          </div>
          <p><strong>Triggers:</strong> {selected.trigger_words.join(", ") || "none"}</p>
          <pre style={{ whiteSpace: "pre-wrap" }}>{selected.description}</pre>
        </>
      )}
    </LibraryCrud>
  );
}
```

- [ ] **Step 3: Run build**

Run from `frontend/`:

```bash
pnpm build
```

Expected: TypeScript build passes.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/organisms/LoraForm.tsx frontend/src/routes/library/loras.tsx
git commit -m "feat(frontend): implement LoRA CRUD route"
```

---

## Task 8: Frontend Route Smoke Tests

**Files:**
- Create: `frontend/src/routes/library/libraryRoutes.test.tsx`

- [ ] **Step 1: Add route smoke tests with mocked fetch**

Create `frontend/src/routes/library/libraryRoutes.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import FamiliesRoute from "./families";
import ModelsRoute from "./models";
import LorasRoute from "./loras";

function renderRoute(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

function json(data: unknown) {
  return Promise.resolve(new Response(JSON.stringify(data), { status: 200 }));
}

describe("library routes", () => {
  it("renders families from the API", async () => {
    vi.stubGlobal("fetch", vi.fn(() => json([
      { id: "sdxl", display_name: "SDXL", prompt_guide: "Guide", created_at: 1, updated_at: 1 },
    ])));

    renderRoute(<FamiliesRoute />);
    await waitFor(() => expect(screen.getByText("SDXL")).toBeInTheDocument());
    expect(screen.getByText(/Guide/)).toBeInTheDocument();
  });

  it("renders models from the API", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url.includes("/families")) {
        return json([{ id: "sdxl", display_name: "SDXL", prompt_guide: "Guide", created_at: 1, updated_at: 1 }]);
      }
      return json([
        {
          name: "juggernaut",
          display_name: "Juggernaut",
          family_id: "sdxl",
          description: "General model",
          author: null,
          version: null,
          source_url: null,
          created_at: 1,
          updated_at: 1,
        },
      ]);
    }));

    renderRoute(<ModelsRoute />);
    await waitFor(() => expect(screen.getByText("Juggernaut")).toBeInTheDocument());
    expect(screen.getByText(/General model/)).toBeInTheDocument();
  });

  it("renders loras from the API", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url.includes("/families")) {
        return json([{ id: "sdxl", display_name: "SDXL", prompt_guide: "Guide", created_at: 1, updated_at: 1 }]);
      }
      return json([
        {
          name: "cinematic_light",
          display_name: "Cinematic Light",
          description: "Rim light",
          tags: ["light"],
          trigger_words: ["cinematic light"],
          family_compat: ["sdxl"],
          recommended_weight: 0.8,
          author: null,
          version: null,
          source_url: null,
          created_at: 1,
          updated_at: 1,
        },
      ]);
    }));

    renderRoute(<LorasRoute />);
    await waitFor(() => expect(screen.getByText("Cinematic Light")).toBeInTheDocument());
    expect(screen.getByText(/Rim light/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run frontend tests**

Run from `frontend/`:

```bash
pnpm test
```

Expected: route smoke tests and existing AppShell test pass.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/library/libraryRoutes.test.tsx
git commit -m "test(frontend): add library route smoke tests"
```

---

## Task 9: Full Slice Verification

**Files:**
- Modify only if verification finds a defect.

- [ ] **Step 1: Run backend test suite**

Run from `backend/`:

```bash
.venv/Scripts/python -m pytest
```

Expected: all tests pass.

- [ ] **Step 2: Run frontend tests and build**

Run from `frontend/`:

```bash
pnpm test
pnpm build
```

Expected: all tests pass and build completes.

- [ ] **Step 3: Run lint checks**

Run:

```bash
cd backend
.venv/Scripts/python -m ruff check .
cd ../frontend
pnpm lint
```

Expected: no errors.

- [ ] **Step 4: Manual backend API smoke**

Run from `backend/`:

```bash
.venv/Scripts/python -m app.cli.init_db
.venv/Scripts/python -m uvicorn app.main:app --port 8000
```

In a second terminal:

```bash
curl -s http://127.0.0.1:8000/api/library/families
curl -s -X POST http://127.0.0.1:8000/api/library/models -H "Content-Type: application/json" -d "{\"name\":\"smoke_model\",\"display_name\":\"Smoke Model\",\"family_id\":\"sdxl\"}"
curl -s -X POST http://127.0.0.1:8000/api/library/loras -H "Content-Type: application/json" -d "{\"name\":\"smoke_lora\",\"display_name\":\"Smoke LoRA\",\"description\":\"Smoke description\",\"tags\":[\"smoke\"],\"trigger_words\":[\"smoke\"],\"family_compat\":[\"sdxl\"],\"recommended_weight\":0.6}"
curl -s http://127.0.0.1:8000/api/library/loras?q=smoke
```

Expected: families JSON includes seeded rows; model and LoRA POSTs return created JSON; LoRA search returns `smoke_lora`.

- [ ] **Step 5: Manual UI acceptance smoke**

Start backend and frontend:

```bash
cd backend
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend
pnpm dev
```

Open `http://localhost:5173/library/families`, then verify:

1. Create a family with id `ui_smoke`.
2. Navigate to `/library/models`, create a model using `ui_smoke`.
3. Navigate to `/library/loras`, create a LoRA compatible with `ui_smoke`.
4. Refresh the page; family, model, and LoRA remain visible.
5. Delete the LoRA; refresh; it stays deleted.

Expected: acceptance scenario from roadmap Slice 1 passes.

- [ ] **Step 6: Commit verification fixes or leave tree clean**

Run:

```bash
git status --short
```

If verification required fixes, commit them with a focused message:

```bash
git add <changed-files>
git commit -m "fix: stabilize Slice 1 library CRUD verification"
```

---

## Done Criteria

Slice 1 is complete when:

1. `/api/library/families`, `/api/library/models`, and `/api/library/loras` support list/get/create/update/delete.
2. API returns `404` for missing rows, `409` for duplicate keys and FK conflicts, and `422` for invalid request bodies.
3. Frontend pages `/library/families`, `/library/models`, and `/library/loras` show real API data, search, detail, create, edit, and delete flows.
4. Family -> model -> LoRA can be created through the UI and survives backend/frontend restart.
5. No embeddings or `vec_loras` writes happen in this slice.
6. Backend tests, frontend tests, frontend build, and lint checks pass.
7. Handoff to Slice 2 is stable: `GET /api/library/models`, `GET /api/library/loras`, and `GET /api/library/families` can power the upcoming `SessionSettingsDrawer`.

## Self-Review Notes

- Spec coverage: covers Slice 1 backend, frontend, no-embedding boundary, and acceptance from `docs/superpowers/specs/2026-04-23-mvp-roadmap-design.md`.
- Placeholder scan: no unfinished-work markers; every task has concrete files, commands, expected results, and commit messages.
- Type consistency: backend `Family/Model/Lora` response fields match frontend `Family/Model/Lora` types and API contract above.
