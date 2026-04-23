# Foundation Phase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bootstrap the sd-chisel repo with a working backend + frontend skeleton so that every subsequent vertical slice can start from "add a feature" rather than "set up the project".

**Architecture:** Two side-by-side apps in one repo. Backend = FastAPI + sqlite (with sqlite-vec VSS) + repository pattern + versioned `.sql` migrations. Frontend = Vite + React 18 + TS + PostCSS + CSS modules, atomic design, Radix headless primitives on demand. No business features in this phase — only migrations, seeds, routing shell, and a `/health` probe wired end-to-end.

**Tech Stack:**
- **Backend:** Python 3.11+, FastAPI, uvicorn, Pydantic v2, sqlite-vec, pytest, ruff. Package manager: `uv` (falls back to `pip install -e .` if unavailable).
- **Frontend:** Node 20+, pnpm, Vite 5, React 18, TypeScript, PostCSS (autoprefixer + postcss-nested), lucide-react, `@tanstack/react-query`, Zustand, `react-router-dom`, vitest. Radix primitives added later on demand.

**Reference docs:**
- Technical spec: [docs/spec/technical_specifications.md](../../spec/technical_specifications.md) — data model (§3), endpoints (§5), UI stack (§6), deps (§7)
- Roadmap: [docs/superpowers/specs/2026-04-23-mvp-roadmap-design.md](../specs/2026-04-23-mvp-roadmap-design.md) — why foundation-first, slice order, deviations
- UI source of truth: `mvp-ui-mock/` — static prototype. We **port** `app/ds/tokens.css` and portions of `app/ds/primitives.css` into the real frontend; DO NOT copy the `.jsx` files (they use Babel-standalone and global React).

**Convention:** Commit after each task is green. Never batch multiple tasks into one commit. Use Conventional Commit prefixes (`feat:`, `chore:`, `test:`, `docs:`).

---

## File Structure (final state after this plan)

```
sd-chisel/
├── README.md                              # [modify/create] dev instructions
├── backend/
│   ├── pyproject.toml                     # [create]
│   ├── ruff.toml                          # [create]
│   ├── app/
│   │   ├── __init__.py                    # [create]
│   │   ├── main.py                        # [create] FastAPI + /health
│   │   ├── config.py                      # [create] data-root resolver
│   │   ├── api/__init__.py                # [create] empty namespace
│   │   ├── services/__init__.py           # [create] empty namespace
│   │   ├── models/__init__.py             # [create] Pydantic schemas namespace
│   │   ├── storage/
│   │   │   ├── __init__.py                # [create]
│   │   │   ├── db.py                      # [create] connection factory
│   │   │   ├── migrations.py              # [create] .sql runner
│   │   │   ├── library_repo.py            # [create] families/models/loras CRUD
│   │   │   ├── session_repo.py            # [create] projects/sessions/... CRUD
│   │   │   └── images.py                  # [create] FS helpers
│   │   └── cli/
│   │       ├── __init__.py                # [create]
│   │       ├── init_db.py                 # [create] migrate + seed
│   │       └── reindex_all.py             # [create] stub (Slice 5)
│   ├── migrations/
│   │   ├── 001_init.sql                   # [create] all tables + indexes
│   │   └── 002_seed_families.sql          # [create] 10 families
│   └── tests/
│       ├── __init__.py                    # [create]
│       ├── conftest.py                    # [create] tmp-data-root fixture
│       ├── test_config.py                 # [create]
│       ├── test_migrations.py             # [create] smoke
│       ├── test_library_repo.py           # [create] happy path
│       ├── test_session_repo.py           # [create] happy path + delete cascade
│       ├── test_images.py                 # [create]
│       └── test_health.py                 # [create]
├── frontend/
│   ├── package.json                       # [create]
│   ├── pnpm-workspace.yaml                # [not needed — single package]
│   ├── tsconfig.json                      # [create]
│   ├── tsconfig.node.json                 # [create]
│   ├── vite.config.ts                     # [create]
│   ├── postcss.config.cjs                 # [create]
│   ├── index.html                         # [create]
│   ├── .eslintrc.cjs                      # [create]
│   ├── .prettierrc                        # [create]
│   └── src/
│       ├── main.tsx                       # [create] root render
│       ├── app.tsx                        # [create] RouterProvider
│       ├── vite-env.d.ts                  # [create]
│       ├── styles/
│       │   ├── tokens.css                 # [port] from mock
│       │   ├── primitives.css             # [port] from mock (trimmed)
│       │   └── global.css                 # [create] reset + imports
│       ├── routes/
│       │   ├── workspace.tsx              # [create] placeholder
│       │   └── library/
│       │       ├── families.tsx           # [create] placeholder
│       │       ├── models.tsx             # [create] placeholder
│       │       └── loras.tsx              # [create] placeholder
│       ├── components/
│       │   ├── atoms/
│       │   │   ├── Icon.tsx               # [create] lucide wrapper
│       │   │   ├── Button.tsx             # [create]
│       │   │   ├── Button.module.css      # [create]
│       │   │   ├── Badge.tsx              # [create]
│       │   │   └── Badge.module.css       # [create]
│       │   ├── molecules/.gitkeep         # [create]
│       │   ├── organisms/.gitkeep         # [create]
│       │   └── templates/
│       │       ├── AppShell.tsx           # [create] Topbar+Sidebar shell
│       │       ├── AppShell.module.css    # [create]
│       │       ├── WorkspaceLayout.tsx    # [create]
│       │       ├── WorkspaceLayout.module.css # [create]
│       │       ├── LibraryLayout.tsx      # [create]
│       │       └── LibraryLayout.module.css # [create]
│       ├── store/
│       │   └── index.ts                   # [create] Zustand skeleton
│       ├── api/
│       │   ├── client.ts                  # [create] fetch wrapper
│       │   └── health.ts                  # [create] useHealth hook
│       └── test/
│           └── setup.ts                   # [create] vitest setup
```

---

## Phase A — Backend skeleton

### Task 1: Backend project scaffold + /health

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/ruff.toml`
- Create: `backend/app/__init__.py` (empty)
- Create: `backend/app/main.py`
- Create: `backend/app/api/__init__.py` (empty)
- Create: `backend/app/services/__init__.py` (empty)
- Create: `backend/app/models/__init__.py` (empty)
- Create: `backend/tests/__init__.py` (empty)
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_health.py`

- [ ] **Step 1: Create `backend/pyproject.toml`**

```toml
[project]
name = "sd-chisel-backend"
version = "0.0.1"
description = "sd-chisel backend"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.32",
  "pydantic>=2.9",
  "sqlite-vec>=0.1.6",
  "numpy>=1.26",
  "python-multipart>=0.0.12",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.3",
  "httpx>=0.27",
  "ruff>=0.7",
]

[project.scripts]
sd-init-db = "app.cli.init_db:main"
sd-reindex-all = "app.cli.reindex_all:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["app"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra -q"
pythonpath = ["."]
```

- [ ] **Step 2: Create `backend/ruff.toml`**

```toml
line-length = 100
target-version = "py311"

[lint]
select = ["E", "F", "W", "I", "B", "UP"]
ignore = ["E501"]

[lint.per-file-ignores]
"tests/*" = ["B011"]
```

- [ ] **Step 3: Create `backend/app/main.py` with /health**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="sd-chisel", version="0.0.1")

# Local dev: frontend runs on 5173 by default.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 4: Create empty namespace `__init__.py` files**

Run (from `backend/`):
```bash
touch app/__init__.py app/api/__init__.py app/services/__init__.py app/models/__init__.py
touch tests/__init__.py
```

- [ ] **Step 5: Write the failing `/health` test**

Create `backend/tests/test_health.py`:
```python
from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_ok():
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

Create `backend/tests/conftest.py` (empty — placeholder for future fixtures):
```python
# pytest fixtures for sd-chisel backend tests
```

- [ ] **Step 6: Install deps + run tests**

Run (from `backend/`):
```bash
uv venv && uv pip install -e ".[dev]"
# or, if uv is unavailable:  python -m venv .venv && .venv/Scripts/activate && pip install -e ".[dev]"

.venv/Scripts/python -m pytest
```
Expected: 1 passed.

- [ ] **Step 7: Verify uvicorn serves /health**

Run (from `backend/`):
```bash
.venv/Scripts/python -m uvicorn app.main:app --port 8000 &
sleep 2
curl -s http://127.0.0.1:8000/health
kill %1
```
Expected: `{"status":"ok"}`.

- [ ] **Step 8: Commit**

```bash
git add backend/pyproject.toml backend/ruff.toml backend/app backend/tests
git commit -m "feat(backend): scaffold FastAPI app with /health endpoint"
```

---

### Task 2: Config / data-root resolver

**Files:**
- Create: `backend/app/config.py`
- Create: `backend/tests/test_config.py`

- [ ] **Step 1: Write failing test for resolver**

Create `backend/tests/test_config.py`:
```python
from pathlib import Path

import pytest

from app.config import resolve_data_root


def test_resolve_data_root_returns_repo_data_dir(tmp_path, monkeypatch):
    # Simulate: project at tmp_path/repo with backend/app/main.py
    repo = tmp_path / "repo"
    (repo / "backend" / "app").mkdir(parents=True)
    (repo / ".git").mkdir()
    fake_main = repo / "backend" / "app" / "main.py"
    fake_main.write_text("# fake main")

    assert resolve_data_root(anchor_file=fake_main) == repo / "data"


def test_resolve_data_root_raises_when_no_repo_root(tmp_path):
    # No .git, no pyproject in the walk up
    orphan = tmp_path / "orphan" / "main.py"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("")
    with pytest.raises(RuntimeError, match="repo root"):
        resolve_data_root(anchor_file=orphan)


def test_resolve_data_root_creates_dir(tmp_path):
    repo = tmp_path / "repo"
    (repo / "backend" / "app").mkdir(parents=True)
    (repo / ".git").mkdir()
    fake_main = repo / "backend" / "app" / "main.py"
    fake_main.write_text("")

    root = resolve_data_root(anchor_file=fake_main)
    assert root.exists()
    assert root.is_dir()
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: ImportError / ModuleNotFoundError for `app.config`.

- [ ] **Step 3: Implement `app/config.py`**

```python
from __future__ import annotations

from pathlib import Path

_REPO_MARKERS = {".git", "pyproject.toml"}


def _find_repo_root(start: Path) -> Path:
    """Walk up from `start` until a directory containing a repo marker is found."""
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for candidate in [current, *current.parents]:
        if any((candidate / marker).exists() for marker in _REPO_MARKERS):
            # If the marker is inside `backend/`, keep walking to find the repo root.
            if candidate.name == "backend":
                continue
            return candidate
    raise RuntimeError(f"Could not find repo root walking up from {start}")


def resolve_data_root(anchor_file: Path | None = None) -> Path:
    """Return `<repo_root>/data`, creating it if missing.

    `anchor_file` defaults to this module; tests can override it.
    """
    anchor = anchor_file or Path(__file__)
    repo_root = _find_repo_root(anchor)
    data = repo_root / "data"
    data.mkdir(parents=True, exist_ok=True)
    return data
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_config.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/tests/test_config.py
git commit -m "feat(backend): add data-root resolver (walk-up from app/main.py)"
```

---

### Task 3: DB connection factory (sqlite-vec, WAL, FK)

**Files:**
- Create: `backend/app/storage/__init__.py`
- Create: `backend/app/storage/db.py`

No test in this task — `db.py` is exercised by the migrations test in Task 4.

- [ ] **Step 1: Create `backend/app/storage/__init__.py`** (empty)

- [ ] **Step 2: Create `backend/app/storage/db.py`**

```python
from __future__ import annotations

import sqlite3
from pathlib import Path

import sqlite_vec

from app.config import resolve_data_root


def db_path(data_root: Path | None = None) -> Path:
    return (data_root or resolve_data_root()) / "app.db"


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open a connection with WAL, FK on, sqlite-vec loaded.

    Returns a connection with row_factory=sqlite3.Row for dict-like access.
    """
    target = path or db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, isolation_level=None)  # manual transactions
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn
```

- [ ] **Step 3: Manual smoke-check**

Run (from `backend/`):
```bash
.venv/Scripts/python -c "from app.storage.db import connect; c = connect(); print([r[0] for r in c.execute('SELECT sqlite_version()')]); c.close()"
```
Expected: version string, no errors. If sqlite-vec fails to load on Windows, the error surfaces here — investigate wheel compatibility before continuing.

- [ ] **Step 4: Commit**

```bash
git add backend/app/storage
git commit -m "feat(backend): add sqlite connection factory with sqlite-vec + WAL + FK"
```

---

### Task 4: Migrations runner + 001_init.sql

**Files:**
- Create: `backend/app/storage/migrations.py`
- Create: `backend/migrations/001_init.sql`
- Create: `backend/tests/test_migrations.py`

- [ ] **Step 1: Write the failing migrations test**

Create `backend/tests/test_migrations.py`:
```python
from pathlib import Path

import pytest

from app.storage import db as db_mod
from app.storage.migrations import apply_pending, applied_versions


@pytest.fixture
def fresh_conn(tmp_path):
    conn = db_mod.connect(tmp_path / "test.db")
    yield conn
    conn.close()


def test_apply_pending_creates_schema_migrations_and_runs_all(fresh_conn, tmp_path):
    # Use the repo's real migrations directory — we test they apply cleanly.
    migrations_dir = Path(__file__).parent.parent / "migrations"
    applied = apply_pending(fresh_conn, migrations_dir)
    assert applied >= 1

    # schema_migrations table exists and has at least one row
    rows = list(fresh_conn.execute("SELECT version FROM schema_migrations ORDER BY version"))
    assert len(rows) == applied

    # All required tables exist
    tables = {r[0] for r in fresh_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    expected = {
        "schema_migrations",
        "families", "models", "loras", "lora_family_compat",
        "lora_vec_map",
        "projects", "sessions", "session_pinned_loras",
        "messages", "prompts",
    }
    assert expected.issubset(tables)

    # vec_loras virtual table exists
    vtables = {r[0] for r in fresh_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='vec_loras'"
    )}
    assert "vec_loras" in vtables


def test_apply_pending_is_idempotent(fresh_conn, tmp_path):
    migrations_dir = Path(__file__).parent.parent / "migrations"
    first = apply_pending(fresh_conn, migrations_dir)
    second = apply_pending(fresh_conn, migrations_dir)
    assert second == 0
    assert applied_versions(fresh_conn) == list(range(1, first + 1))


def test_foreign_keys_enforced(fresh_conn, tmp_path):
    migrations_dir = Path(__file__).parent.parent / "migrations"
    apply_pending(fresh_conn, migrations_dir)

    # Inserting a model with a non-existent family must fail.
    with pytest.raises(Exception):
        fresh_conn.execute(
            "INSERT INTO models(name, display_name, family_id, created_at, updated_at) "
            "VALUES (?, ?, ?, 0, 0)",
            ("m1", "M1", "does-not-exist"),
        )
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_migrations.py -v`
Expected: ModuleNotFoundError for `app.storage.migrations`.

- [ ] **Step 3: Implement `app/storage/migrations.py`**

```python
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

_VERSION_RE = re.compile(r"^(\d{3,})_.+\.sql$")


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "  version INTEGER PRIMARY KEY,"
        "  applied_at INTEGER NOT NULL"
        ")"
    )


def applied_versions(conn: sqlite3.Connection) -> list[int]:
    _ensure_table(conn)
    return [r[0] for r in conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    )]


def _discover(migrations_dir: Path) -> list[tuple[int, Path]]:
    out: list[tuple[int, Path]] = []
    for f in sorted(migrations_dir.iterdir()):
        m = _VERSION_RE.match(f.name)
        if m:
            out.append((int(m.group(1)), f))
    return out


def apply_pending(conn: sqlite3.Connection, migrations_dir: Path) -> int:
    """Apply all migration files not yet in schema_migrations.

    Each file runs in its own transaction: BEGIN → executescript →
    INSERT schema_migrations → COMMIT. One transaction per file so that
    CREATE VIRTUAL TABLE (sqlite-vec) behaves predictably.
    Returns the count of newly applied migrations.
    """
    import time

    _ensure_table(conn)
    already = set(applied_versions(conn))
    applied = 0
    for version, path in _discover(migrations_dir):
        if version in already:
            continue
        sql = path.read_text(encoding="utf-8")
        try:
            conn.execute("BEGIN")
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (version, int(time.time())),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        applied += 1
    return applied
```

- [ ] **Step 4: Create `backend/migrations/001_init.sql`**

Transcribe the schema from [technical_specifications.md §3](../../spec/technical_specifications.md#3-data-model) verbatim. The file must contain, in order:

```sql
-- 001_init.sql — initial schema for sd-chisel
-- Source of truth: docs/spec/technical_specifications.md §3

-- Library: families / models / loras
CREATE TABLE families (
  id            TEXT PRIMARY KEY,
  display_name  TEXT NOT NULL,
  prompt_guide  TEXT NOT NULL,
  created_at    INTEGER NOT NULL,
  updated_at    INTEGER NOT NULL
);

CREATE TABLE models (
  name          TEXT PRIMARY KEY,
  display_name  TEXT NOT NULL,
  family_id     TEXT NOT NULL REFERENCES families(id) ON DELETE RESTRICT,
  description   TEXT,
  author        TEXT,
  version       TEXT,
  source_url    TEXT,
  created_at    INTEGER NOT NULL,
  updated_at    INTEGER NOT NULL
);

CREATE TABLE loras (
  name                TEXT PRIMARY KEY,
  display_name        TEXT NOT NULL,
  description         TEXT NOT NULL,
  tags                TEXT NOT NULL DEFAULT '[]',
  trigger_words       TEXT NOT NULL DEFAULT '[]',
  recommended_weight  REAL,
  author              TEXT,
  version             TEXT,
  source_url          TEXT,
  created_at          INTEGER NOT NULL,
  updated_at          INTEGER NOT NULL
);

CREATE TABLE lora_family_compat (
  lora_name  TEXT NOT NULL REFERENCES loras(name)  ON DELETE CASCADE,
  family_id  TEXT NOT NULL REFERENCES families(id) ON DELETE RESTRICT,
  PRIMARY KEY (lora_name, family_id)
);

-- sqlite-vec virtual table. Dimension 1024 = BAAI/bge-m3 (spec §7).
CREATE VIRTUAL TABLE vec_loras USING vec0(embedding FLOAT[1024]);

CREATE TABLE lora_vec_map (
  lora_name  TEXT PRIMARY KEY REFERENCES loras(name) ON DELETE CASCADE,
  rowid      INTEGER NOT NULL UNIQUE
);

-- Projects / sessions / chat / prompt history
CREATE TABLE projects (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL
);

CREATE TABLE sessions (
  id                 TEXT PRIMARY KEY,
  project_id         TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name               TEXT,
  model_name         TEXT REFERENCES models(name) ON DELETE SET NULL,
  use_negative       INTEGER NOT NULL DEFAULT 1,
  vl_endpoint        TEXT,
  prompt_endpoint    TEXT,
  vl_summary         TEXT,
  source_image_path  TEXT,
  result_image_path  TEXT,
  created_at         INTEGER NOT NULL,
  updated_at         INTEGER NOT NULL
);
CREATE INDEX idx_sessions_project ON sessions(project_id, updated_at DESC);

CREATE TABLE session_pinned_loras (
  session_id       TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  lora_name        TEXT NOT NULL REFERENCES loras(name)  ON DELETE CASCADE,
  weight_override  REAL,
  PRIMARY KEY (session_id, lora_name)
);

CREATE TABLE messages (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  role        TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
  content     TEXT NOT NULL,
  created_at  INTEGER NOT NULL
);
CREATE INDEX idx_messages_session ON messages(session_id, created_at);

CREATE TABLE prompts (
  id                    INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id            TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  positive              TEXT NOT NULL,
  negative              TEXT,
  loras_json            TEXT NOT NULL,
  intents_json          TEXT,
  retrieved_loras_json  TEXT,
  created_at            INTEGER NOT NULL
);
CREATE INDEX idx_prompts_session ON prompts(session_id, created_at);
```

- [ ] **Step 5: Run tests**

Run (from `backend/`): `pytest tests/test_migrations.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/storage/migrations.py backend/migrations/001_init.sql backend/tests/test_migrations.py
git commit -m "feat(backend): add migrations runner + 001 initial schema"
```

---

### Task 5: Seed families + init-db CLI

**Files:**
- Create: `backend/migrations/002_seed_families.sql`
- Create: `backend/app/cli/__init__.py` (empty)
- Create: `backend/app/cli/init_db.py`
- Create: `backend/app/cli/reindex_all.py` (stub)

- [ ] **Step 1: Create `backend/migrations/002_seed_families.sql`**

Use the 10 families and their `prompt_guide` text from `mvp-ui-mock/app/data.js` lines 3-13 verbatim. Each INSERT uses `strftime('%s','now')` for timestamps. Use `INSERT OR IGNORE` so re-running is safe even though the migrations runner already guards against re-application:

```sql
-- 002_seed_families.sql — 10 closed-dictionary families (spec §3.1)
-- Source: mvp-ui-mock/app/data.js (FAMILIES array)

INSERT OR IGNORE INTO families(id, display_name, prompt_guide, created_at, updated_at) VALUES
  ('sdxl', 'SDXL',
   'SDXL base guide. Use natural language. Keep descriptions concise. Token weight syntax (keyword:1.2).',
   strftime('%s','now'), strftime('%s','now')),
  ('illustrious', 'Illustrious',
   'Illustrious XL. Booru-style tags work. Trigger words from LoRA take precedence over generic style cues.',
   strftime('%s','now'), strftime('%s','now')),
  ('pony', 'Pony',
   'Pony Diffusion. Score tags are required: score_9, score_8_up, score_7_up. Rating tag at the end.',
   strftime('%s','now'), strftime('%s','now')),
  ('flux', 'Flux',
   'Flux.1. Natural language strongly preferred. Avoid booru tags. No negative prompt needed in most cases.',
   strftime('%s','now'), strftime('%s','now')),
  ('sd15', 'SD 1.5',
   'Stable Diffusion 1.5. Short, comma-separated tags work best. CFG 7–12. Negative prompt is important.',
   strftime('%s','now'), strftime('%s','now')),
  ('sd21', 'SD 2.1',
   'Stable Diffusion 2.1. Similar to 1.5 but larger token space. Needs explicit quality tags.',
   strftime('%s','now'), strftime('%s','now')),
  ('cascade', 'Stable Cascade',
   'Stable Cascade. Natural language. Two-stage process; prompts at both stages merged. Highly coherent.',
   strftime('%s','now'), strftime('%s','now')),
  ('hunyuan', 'HunyuanDiT',
   'HunyuanDiT. Chinese and English prompts both work. Bilingual model with strong semantic understanding.',
   strftime('%s','now'), strftime('%s','now')),
  ('kolors', 'Kolors',
   'Kolors by Kuaishou. Chinese-English bilingual. Natural language, high fidelity faces.',
   strftime('%s','now'), strftime('%s','now')),
  ('auraflow', 'AuraFlow',
   'AuraFlow v0.3. Natural language, flow-based diffusion. Avoid overly long prompts; concise descriptions work best.',
   strftime('%s','now'), strftime('%s','now'));
```

- [ ] **Step 2: Create `backend/app/cli/__init__.py`** (empty)

- [ ] **Step 3: Create `backend/app/cli/init_db.py`**

```python
"""CLI: apply migrations against ./data/app.db.

Invoke:  python -m app.cli.init_db
         sd-init-db               (via project script entry point)
"""
from __future__ import annotations

from pathlib import Path

from app.storage import db as db_mod
from app.storage.migrations import apply_pending

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def main() -> None:
    conn = db_mod.connect()
    try:
        count = apply_pending(conn, MIGRATIONS_DIR)
        print(f"Applied {count} migration(s). DB at {db_mod.db_path()}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Create `backend/app/cli/reindex_all.py`** (stub for Slice 5)

```python
"""CLI: reindex all LoRAs into vec_loras. Implemented in Slice 5."""
from __future__ import annotations


def main() -> None:
    raise SystemExit(
        "reindex-all is not implemented yet. It will be added in Slice 5 "
        "(Embedder + Indexer). See docs/superpowers/specs/2026-04-23-mvp-roadmap-design.md."
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Add seed-check to `test_migrations.py`**

Append to `backend/tests/test_migrations.py`:
```python
def test_families_are_seeded(fresh_conn, tmp_path):
    migrations_dir = Path(__file__).parent.parent / "migrations"
    apply_pending(fresh_conn, migrations_dir)

    ids = {r[0] for r in fresh_conn.execute("SELECT id FROM families")}
    expected = {
        "sdxl", "illustrious", "pony", "flux",
        "sd15", "sd21", "cascade", "hunyuan", "kolors", "auraflow",
    }
    assert ids == expected
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_migrations.py -v`
Expected: 4 passed.

- [ ] **Step 7: Run the CLI end-to-end**

Run (from `backend/`):
```bash
rm -f ../data/app.db
.venv/Scripts/python -m app.cli.init_db
.venv/Scripts/python -c "import sqlite3; c=sqlite3.connect('../data/app.db'); print(list(c.execute('SELECT id FROM families')))"
```
Expected: list of 10 tuples, one per family.

- [ ] **Step 8: Commit**

```bash
git add backend/migrations/002_seed_families.sql backend/app/cli backend/tests/test_migrations.py
git commit -m "feat(backend): seed 10 families + add init-db / reindex-all CLI"
```

---

### Task 6: Library repository

**Files:**
- Create: `backend/app/storage/library_repo.py`
- Create: `backend/tests/test_library_repo.py`

Keep the repo MINIMAL. It exposes just enough for Slice 1 to build on top. Do NOT add pagination, search, or filters yet — those belong in Slice 1's plan.

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_library_repo.py`:
```python
from pathlib import Path

import pytest

from app.storage import db as db_mod
from app.storage import library_repo
from app.storage.migrations import apply_pending


@pytest.fixture
def conn(tmp_path):
    c = db_mod.connect(tmp_path / "t.db")
    apply_pending(c, Path(__file__).parent.parent / "migrations")
    yield c
    c.close()


def test_list_families_returns_seeded(conn):
    fams = library_repo.list_families(conn)
    ids = [f["id"] for f in fams]
    assert "sdxl" in ids and len(ids) == 10


def test_create_and_get_model(conn):
    library_repo.create_model(conn, name="juggernautXL_v10",
                              display_name="Juggernaut XL v10",
                              family_id="sdxl")
    m = library_repo.get_model(conn, "juggernautXL_v10")
    assert m is not None
    assert m["display_name"] == "Juggernaut XL v10"
    assert m["family_id"] == "sdxl"


def test_create_model_with_unknown_family_raises(conn):
    with pytest.raises(Exception):
        library_repo.create_model(conn, name="x", display_name="X", family_id="nope")


def test_create_and_get_lora_with_compat(conn):
    library_repo.create_lora(
        conn,
        name="cinematic_lighting_v2",
        display_name="Cinematic Lighting v2",
        description="Dramatic cinematic light.",
        tags=["light", "mood"],
        trigger_words=["cinematic", "rim light"],
        recommended_weight=0.85,
        family_compat=["sdxl", "illustrious"],
    )
    l = library_repo.get_lora(conn, "cinematic_lighting_v2")
    assert l is not None
    assert l["tags"] == ["light", "mood"]
    assert set(l["family_compat"]) == {"sdxl", "illustrious"}


def test_delete_lora_cascades_compat_and_vec_map(conn):
    library_repo.create_lora(
        conn, name="ltest", display_name="L", description="d",
        tags=[], trigger_words=[], family_compat=["sdxl"],
    )
    # Simulate vec_map row (indexer would populate this in Slice 5)
    conn.execute("INSERT INTO lora_vec_map(lora_name, rowid) VALUES (?, ?)", ("ltest", 1))
    library_repo.delete_lora(conn, "ltest")
    assert library_repo.get_lora(conn, "ltest") is None
    assert list(conn.execute("SELECT * FROM lora_family_compat WHERE lora_name='ltest'")) == []
    assert list(conn.execute("SELECT * FROM lora_vec_map WHERE lora_name='ltest'")) == []
```

- [ ] **Step 2: Run — verify failure**

Run: `pytest tests/test_library_repo.py -v`
Expected: ModuleNotFoundError for `app.storage.library_repo`.

- [ ] **Step 3: Implement `backend/app/storage/library_repo.py`**

```python
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
        conn.execute("ROLLBACK")
        raise
    return get_lora(conn, name)  # type: ignore[return-value]


def delete_lora(conn: sqlite3.Connection, name: str) -> None:
    # vec_loras rowid cleanup is Slice 5's responsibility (requires the map entry);
    # here we only touch the main table. CASCADE handles lora_family_compat + lora_vec_map.
    conn.execute("DELETE FROM loras WHERE name = ?", (name,))
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_library_repo.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/storage/library_repo.py backend/tests/test_library_repo.py
git commit -m "feat(backend): library repository (families/models/loras minimal CRUD)"
```

---

### Task 7: Session repository + image helpers

**Files:**
- Create: `backend/app/storage/images.py`
- Create: `backend/app/storage/session_repo.py`
- Create: `backend/tests/test_images.py`
- Create: `backend/tests/test_session_repo.py`

Same discipline as Task 6 — minimal surface, no features beyond what's needed to verify the layer works.

- [ ] **Step 1: Write failing test for images.py**

Create `backend/tests/test_images.py`:
```python
import pytest

from app.storage import images


def test_session_image_dir_creates(tmp_path):
    d = images.session_image_dir("abc", data_root=tmp_path)
    assert d.exists() and d.is_dir()
    assert d.name == "abc"


def test_remove_session_images_is_idempotent(tmp_path):
    d = images.session_image_dir("xyz", data_root=tmp_path)
    (d / "source.png").write_bytes(b"\x89PNG")
    images.remove_session_images("xyz", data_root=tmp_path)
    assert not d.exists()
    # Idempotent: calling twice doesn't raise.
    images.remove_session_images("xyz", data_root=tmp_path)


def test_remove_session_images_rejects_path_traversal(tmp_path):
    with pytest.raises(ValueError):
        images.remove_session_images("../evil", data_root=tmp_path)
```

- [ ] **Step 2: Run, verify failure**

Run: `pytest tests/test_images.py -v`
Expected: ImportError for `app.storage.images`.

- [ ] **Step 3: Implement `backend/app/storage/images.py`**

```python
from __future__ import annotations

import re
import shutil
from pathlib import Path

from app.config import resolve_data_root

_SAFE_ID = re.compile(r"^[A-Za-z0-9_\-]+$")


def _validate_session_id(session_id: str) -> None:
    if not _SAFE_ID.match(session_id):
        raise ValueError(f"unsafe session id: {session_id!r}")


def session_image_dir(session_id: str, *, data_root: Path | None = None) -> Path:
    _validate_session_id(session_id)
    root = data_root or resolve_data_root()
    d = root / "images" / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def remove_session_images(session_id: str, *, data_root: Path | None = None) -> None:
    _validate_session_id(session_id)
    root = data_root or resolve_data_root()
    d = root / "images" / session_id
    if d.exists():
        shutil.rmtree(d)
```

- [ ] **Step 4: Run images test**

Run: `pytest tests/test_images.py -v`
Expected: 3 passed.

- [ ] **Step 5: Write failing test for session_repo**

Create `backend/tests/test_session_repo.py`:
```python
from pathlib import Path

import pytest

from app.storage import db as db_mod
from app.storage import session_repo
from app.storage.migrations import apply_pending


@pytest.fixture
def conn(tmp_path):
    c = db_mod.connect(tmp_path / "t.db")
    apply_pending(c, Path(__file__).parent.parent / "migrations")
    yield c
    c.close()


def test_create_and_list_projects(conn):
    session_repo.create_project(conn, id="scrapyard", name="Scrapyard")
    session_repo.create_project(conn, id="portraits", name="Portraits")
    ps = session_repo.list_projects(conn)
    assert {p["id"] for p in ps} == {"scrapyard", "portraits"}


def test_create_session_and_append_message(conn):
    session_repo.create_project(conn, id="p1", name="P1")
    session_repo.create_session(conn, id="s1", project_id="p1", name="first")

    session_repo.append_message(conn, session_id="s1", role="user", content="hi")
    session_repo.append_message(conn, session_id="s1", role="assistant", content="hello")
    msgs = session_repo.list_messages(conn, session_id="s1")
    assert [m["role"] for m in msgs] == ["user", "assistant"]


def test_delete_session_cascades_messages(conn):
    session_repo.create_project(conn, id="p1", name="P1")
    session_repo.create_session(conn, id="s1", project_id="p1")
    session_repo.append_message(conn, session_id="s1", role="user", content="x")

    session_repo.delete_session(conn, "s1")

    assert session_repo.get_session(conn, "s1") is None
    assert list(conn.execute("SELECT * FROM messages WHERE session_id='s1'")) == []
```

- [ ] **Step 6: Implement `backend/app/storage/session_repo.py`**

```python
"""Raw CRUD over projects / sessions / messages / prompts / pinned loras.

Note: filesystem cleanup for `data/images/<session_id>/` is NOT handled here —
callers (API layer) must invoke `app.storage.images.remove_session_images`
before or after `delete_session`. Foundation plan keeps this split explicit;
Slice 2 adds a transactional wrapper in the API.
"""
from __future__ import annotations

import sqlite3
import time
from typing import Any


def _now() -> int:
    return int(time.time())


def _row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(r) if r is not None else None


# --- projects ---------------------------------------------------------------


def list_projects(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM projects ORDER BY updated_at DESC"
    )]


def get_project(conn: sqlite3.Connection, project_id: str) -> dict[str, Any] | None:
    return _row(conn.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone())


def create_project(conn: sqlite3.Connection, *, id: str, name: str) -> dict[str, Any]:
    now = _now()
    conn.execute(
        "INSERT INTO projects(id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (id, name, now, now),
    )
    return get_project(conn, id)  # type: ignore[return-value]


# --- sessions ---------------------------------------------------------------


def get_session(conn: sqlite3.Connection, session_id: str) -> dict[str, Any] | None:
    return _row(conn.execute(
        "SELECT * FROM sessions WHERE id = ?", (session_id,)
    ).fetchone())


def list_sessions(conn: sqlite3.Connection, project_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM sessions WHERE project_id = ? ORDER BY updated_at DESC",
        (project_id,),
    )]


def create_session(
    conn: sqlite3.Connection,
    *,
    id: str,
    project_id: str,
    name: str | None = None,
    model_name: str | None = None,
    use_negative: bool = True,
) -> dict[str, Any]:
    now = _now()
    conn.execute(
        "INSERT INTO sessions(id, project_id, name, model_name, use_negative, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (id, project_id, name, model_name, 1 if use_negative else 0, now, now),
    )
    return get_session(conn, id)  # type: ignore[return-value]


def delete_session(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


# --- messages ---------------------------------------------------------------


def append_message(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    role: str,
    content: str,
) -> dict[str, Any]:
    now = _now()
    cur = conn.execute(
        "INSERT INTO messages(session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (session_id, role, content, now),
    )
    return _row(conn.execute(
        "SELECT * FROM messages WHERE id = ?", (cur.lastrowid,)
    ).fetchone())  # type: ignore[return-value]


def list_messages(conn: sqlite3.Connection, *, session_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at, id",
        (session_id,),
    )]
```

- [ ] **Step 7: Run session_repo tests**

Run: `pytest tests/test_session_repo.py -v`
Expected: 3 passed.

- [ ] **Step 8: Full backend test run**

Run: `pytest`
Expected: all tests pass (test_health + test_config + test_migrations + test_library_repo + test_images + test_session_repo = 15+).

- [ ] **Step 9: Commit**

```bash
git add backend/app/storage/images.py backend/app/storage/session_repo.py backend/tests/test_images.py backend/tests/test_session_repo.py
git commit -m "feat(backend): session repository + image dir helpers"
```

---

## Phase B — Frontend skeleton

### Task 8: Frontend project scaffold (pnpm + Vite + React + TS)

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.node.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/postcss.config.cjs`
- Create: `frontend/index.html`
- Create: `frontend/.eslintrc.cjs`
- Create: `frontend/.prettierrc`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/app.tsx`
- Create: `frontend/src/vite-env.d.ts`

- [ ] **Step 1: Create `frontend/package.json`**

```json
{
  "name": "sd-chisel-frontend",
  "private": true,
  "version": "0.0.1",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest",
    "lint": "eslint src --ext .ts,.tsx",
    "format": "prettier --write src"
  },
  "dependencies": {
    "@tanstack/react-query": "^5.59.0",
    "lucide-react": "^0.460.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-resizable-panels": "^2.1.7",
    "react-router-dom": "^6.28.0",
    "zustand": "^5.0.0"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.6.0",
    "@testing-library/react": "^16.0.0",
    "@types/react": "^18.3.12",
    "@types/react-dom": "^18.3.1",
    "@typescript-eslint/eslint-plugin": "^7.18.0",
    "@typescript-eslint/parser": "^7.18.0",
    "@vitejs/plugin-react": "^4.3.3",
    "autoprefixer": "^10.4.20",
    "eslint": "^8.57.1",
    "eslint-plugin-react-hooks": "^4.6.2",
    "eslint-plugin-react-refresh": "^0.4.14",
    "jsdom": "^25.0.0",
    "postcss": "^8.4.49",
    "postcss-nested": "^7.0.0",
    "prettier": "^3.3.0",
    "typescript": "^5.6.0",
    "vite": "^5.4.0",
    "vitest": "^2.1.0"
  }
}
```

> Exact versions may shift by the time this plan runs — bump patch/minor as needed, keep majors pinned. Verify no breaking-change warnings after install.
>
> **Note on ESLint major:** pinned to v8 because this plan uses legacy `.eslintrc.cjs` config. ESLint 9 requires flat config (`eslint.config.js`) and breaks several plugins' compat — out of scope for foundation. Migration to v9 + flat config can be a separate task later.

- [ ] **Step 2: Create `frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "allowSyntheticDefaultImports": true,
    "baseUrl": "./src",
    "paths": {
      "@/*": ["*"]
    }
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

- [ ] **Step 3: Create `frontend/tsconfig.node.json`**

```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true
  },
  "include": ["vite.config.ts", "postcss.config.cjs"]
}
```

- [ ] **Step 4: Create `frontend/vite.config.ts`**

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
```

- [ ] **Step 5: Create `frontend/postcss.config.cjs`**

```js
module.exports = {
  plugins: {
    "postcss-nested": {},
    autoprefixer: {},
  },
};
```

- [ ] **Step 6: Create `frontend/index.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>sd-chisel</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet" />
</head>
<body data-theme="quarry">
  <div id="root"></div>
  <script type="module" src="/src/main.tsx"></script>
</body>
</html>
```

- [ ] **Step 7: Create `frontend/.eslintrc.cjs`**

```js
module.exports = {
  root: true,
  env: { browser: true, es2022: true },
  extends: [
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended",
    "plugin:react-hooks/recommended",
  ],
  parser: "@typescript-eslint/parser",
  parserOptions: { ecmaVersion: "latest", sourceType: "module" },
  plugins: ["react-refresh"],
  rules: {
    "react-refresh/only-export-components": "warn",
    "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
  },
};
```

- [ ] **Step 8: Create `frontend/.prettierrc`**

```json
{
  "semi": true,
  "singleQuote": false,
  "trailingComma": "all",
  "printWidth": 100
}
```

- [ ] **Step 9: Create `frontend/src/vite-env.d.ts`**

```ts
/// <reference types="vite/client" />
```

- [ ] **Step 10: Create minimal `frontend/src/main.tsx` + `app.tsx`** (will be replaced with real router in Task 11)

`frontend/src/main.tsx`:
```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

`frontend/src/app.tsx`:
```tsx
export function App() {
  return <div>sd-chisel — scaffolding…</div>;
}
```

- [ ] **Step 11: Install + verify build**

Run (from `frontend/`):
```bash
pnpm install
pnpm build
```
Expected: build succeeds, `dist/` is created, no TS errors.

- [ ] **Step 12: Verify dev server runs**

Run (from `frontend/`):
```bash
pnpm dev &
sleep 3
curl -s http://localhost:5173 | head -20
kill %1
```
Expected: HTML with `<div id="root">` visible.

- [ ] **Step 13: Commit**

```bash
git add frontend/package.json frontend/pnpm-lock.yaml frontend/tsconfig*.json frontend/vite.config.ts frontend/postcss.config.cjs frontend/index.html frontend/.eslintrc.cjs frontend/.prettierrc frontend/src
git commit -m "feat(frontend): scaffold Vite + React + TS + PostCSS with pnpm"
```

---

### Task 9: Port design tokens + global.css

**Files:**
- Create: `frontend/src/styles/tokens.css`  (port from `mvp-ui-mock/app/ds/tokens.css`)
- Create: `frontend/src/styles/primitives.css` (port from `mvp-ui-mock/app/ds/primitives.css` — trim UI-only bits)
- Create: `frontend/src/styles/global.css`

- [ ] **Step 1: Copy `tokens.css` verbatim**

```bash
cp mvp-ui-mock/app/ds/tokens.css frontend/src/styles/tokens.css
```

No edits needed — it's pure CSS custom properties, framework-agnostic.

- [ ] **Step 2: Copy `primitives.css` + remove dependencies we don't use yet**

```bash
cp mvp-ui-mock/app/ds/primitives.css frontend/src/styles/primitives.css
```

Then open `frontend/src/styles/primitives.css` and verify it contains no references to classes that would conflict with CSS modules (the mock uses global `.ds-*` class names — this is fine, they stay global). Leave content as-is; refinements happen as atoms are extracted.

- [ ] **Step 3: Create `frontend/src/styles/global.css`**

```css
@import "./tokens.css";
@import "./primitives.css";

*,
*::before,
*::after {
  box-sizing: border-box;
}

html,
body,
#root {
  height: 100%;
}

body {
  margin: 0;
  font-family: var(--font-ui);
  font-size: var(--text-base);
  line-height: var(--leading-normal);
  color: var(--text);
  background: var(--bg);
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

a {
  color: inherit;
}

button {
  font-family: inherit;
}
```

- [ ] **Step 4: Import global.css in `main.tsx`**

Modify `frontend/src/main.tsx` — add `import "./styles/global.css";` at the top, before the React imports.

- [ ] **Step 5: Verify build**

Run (from `frontend/`): `pnpm build`
Expected: build succeeds, CSS is bundled, no "unknown CSS variable" warnings.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/styles frontend/src/main.tsx
git commit -m "feat(frontend): port design tokens and primitives from mock"
```

---

### Task 10: Router + QueryClient + Zustand skeleton

**Files:**
- Create: `frontend/src/store/index.ts`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/health.ts`
- Create: `frontend/src/routes/workspace.tsx`
- Create: `frontend/src/routes/library/families.tsx`
- Create: `frontend/src/routes/library/models.tsx`
- Create: `frontend/src/routes/library/loras.tsx`
- Modify: `frontend/src/app.tsx` — add RouterProvider + QueryClientProvider

- [ ] **Step 1: Create `frontend/src/store/index.ts`** (placeholder Zustand store)

```ts
import { create } from "zustand";

// Placeholder global store. Feature-specific stores (session, drawer, etc.)
// are added in their respective slice plans.
type AppState = {
  theme: "quarry";
};

export const useAppStore = create<AppState>(() => ({
  theme: "quarry",
}));
```

- [ ] **Step 2: Create `frontend/src/api/client.ts`**

```ts
import { QueryClient } from "@tanstack/react-query";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: string,
  ) {
    super(`API ${status}: ${body.slice(0, 200)}`);
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    throw new ApiError(res.status, await res.text());
  }
  return res.json() as Promise<T>;
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});
```

- [ ] **Step 3: Create `frontend/src/api/health.ts`**

```ts
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";

type Health = { status: "ok" };

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => apiFetch<Health>("/health"),
    refetchInterval: 10_000,
    staleTime: 5_000,
  });
}
```

- [ ] **Step 4: Create route placeholders**

`frontend/src/routes/workspace.tsx`:
```tsx
export default function WorkspaceRoute() {
  return (
    <div style={{ padding: 24 }}>
      <h2>Workspace</h2>
      <p>4-pane workspace coming in Slice 2 (Projects & Sessions).</p>
    </div>
  );
}
```

`frontend/src/routes/library/families.tsx`:
```tsx
export default function FamiliesRoute() {
  return (
    <div style={{ padding: 24 }}>
      <h2>Families</h2>
      <p>Library CRUD coming in Slice 1.</p>
    </div>
  );
}
```

`frontend/src/routes/library/models.tsx`:
```tsx
export default function ModelsRoute() {
  return (
    <div style={{ padding: 24 }}>
      <h2>Models</h2>
      <p>Library CRUD coming in Slice 1.</p>
    </div>
  );
}
```

`frontend/src/routes/library/loras.tsx`:
```tsx
export default function LorasRoute() {
  return (
    <div style={{ padding: 24 }}>
      <h2>LoRAs</h2>
      <p>Library CRUD coming in Slice 1.</p>
    </div>
  );
}
```

- [ ] **Step 5: Update `frontend/src/app.tsx`**

Replace the scaffold contents with the full router + providers. `AppShell` is imported but does not exist yet — we create it in Task 12. For now, use a temporary inline wrapper:

```tsx
import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { queryClient } from "./api/client";
import WorkspaceRoute from "./routes/workspace";
import FamiliesRoute from "./routes/library/families";
import ModelsRoute from "./routes/library/models";
import LorasRoute from "./routes/library/loras";

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Navigate to="/projects/scrapyard/sessions/default" replace />} />
          <Route path="/projects/:projectId/sessions/:sessionId" element={<WorkspaceRoute />} />
          <Route path="/library/families" element={<FamiliesRoute />} />
          <Route path="/library/models" element={<ModelsRoute />} />
          <Route path="/library/loras" element={<LorasRoute />} />
          <Route path="*" element={<div>404</div>} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
```

- [ ] **Step 6: Verify build + dev**

Run (from `frontend/`): `pnpm build && pnpm dev &`, then `sleep 3 && curl -s http://localhost:5173/library/families | grep -q 'Families' && echo OK && kill %1`
Expected: `OK` (SPA serves the shell, client-side routing handles the rest at runtime — this check is just that Vite starts).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/store frontend/src/api frontend/src/routes frontend/src/app.tsx
git commit -m "feat(frontend): router + QueryClient + health hook + Zustand skeleton"
```

---

### Task 11: Atom components (Icon, Button, Badge)

**Files:**
- Create: `frontend/src/components/atoms/Icon.tsx`
- Create: `frontend/src/components/atoms/Button.tsx`
- Create: `frontend/src/components/atoms/Button.module.css`
- Create: `frontend/src/components/atoms/Badge.tsx`
- Create: `frontend/src/components/atoms/Badge.module.css`
- Create: `frontend/src/components/molecules/.gitkeep`
- Create: `frontend/src/components/organisms/.gitkeep`

- [ ] **Step 1: Create `Icon.tsx`** — thin wrapper over lucide with a typed name registry

```tsx
import {
  Check, ChevronDown, Copy, Folder, Link, Pin, Plus, Settings, Trash2, X,
  type LucideIcon,
} from "lucide-react";

const ICONS = {
  Check, ChevronDown, Copy, Folder, Link, Pin, Plus, Settings, Trash2, X,
} as const satisfies Record<string, LucideIcon>;

export type IconName = keyof typeof ICONS;

export function Icon({
  name,
  size = 14,
  strokeWidth = 1.75,
  ...rest
}: {
  name: IconName;
  size?: number;
  strokeWidth?: number;
  className?: string;
  "aria-label"?: string;
}) {
  const Cmp = ICONS[name];
  return <Cmp size={size} strokeWidth={strokeWidth} {...rest} />;
}
```

> More icons get added here by name as slices need them. This keeps the import surface audited and the tree-shake predictable.

- [ ] **Step 2: Create `Button.module.css`** (minimal — neutral + primary + sizes)

```css
.button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  font-size: var(--text-sm);
  font-weight: 500;
  cursor: pointer;
  transition: background 120ms ease, border-color 120ms ease;
}

.button:hover {
  background: var(--surface-hover, var(--bg-muted));
}

.button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.primary {
  background: var(--accent);
  border-color: var(--accent);
  color: var(--accent-contrast, #fff);
}

.sm {
  padding: 4px 10px;
  font-size: var(--text-xs);
}

.lg {
  padding: 8px 16px;
  font-size: var(--text-base);
}
```

- [ ] **Step 3: Create `Button.tsx`**

```tsx
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import styles from "./Button.module.css";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "secondary" | "primary";
  size?: "sm" | "md" | "lg";
  icon?: ReactNode;
};

export const Button = forwardRef<HTMLButtonElement, Props>(
  ({ variant = "secondary", size = "md", icon, className, children, ...rest }, ref) => {
    const cls = [
      styles.button,
      variant === "primary" ? styles.primary : null,
      size === "sm" ? styles.sm : size === "lg" ? styles.lg : null,
      className,
    ]
      .filter(Boolean)
      .join(" ");
    return (
      <button ref={ref} className={cls} {...rest}>
        {icon}
        {children}
      </button>
    );
  },
);
Button.displayName = "Button";
```

- [ ] **Step 4: Create `Badge.module.css` + `Badge.tsx`**

`Badge.module.css`:
```css
.badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--surface);
  font-size: var(--text-2xs);
  font-weight: 500;
  color: var(--text-muted, var(--text));
  text-transform: none;
}

.accent {
  background: color-mix(in srgb, var(--accent) 14%, transparent);
  border-color: color-mix(in srgb, var(--accent) 40%, transparent);
  color: var(--accent);
}
```

`Badge.tsx`:
```tsx
import type { ReactNode } from "react";
import styles from "./Badge.module.css";

type Props = {
  variant?: "neutral" | "accent";
  icon?: ReactNode;
  children: ReactNode;
};

export function Badge({ variant = "neutral", icon, children }: Props) {
  const cls = [styles.badge, variant === "accent" ? styles.accent : null].filter(Boolean).join(" ");
  return (
    <span className={cls}>
      {icon}
      {children}
    </span>
  );
}
```

- [ ] **Step 5: Create `.gitkeep` placeholders for molecules/organisms**

```bash
mkdir -p frontend/src/components/molecules frontend/src/components/organisms
touch frontend/src/components/molecules/.gitkeep frontend/src/components/organisms/.gitkeep
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/atoms frontend/src/components/molecules frontend/src/components/organisms
git commit -m "feat(frontend): add atom components (Icon, Button, Badge)"
```

---

### Task 12: Template layouts (AppShell, WorkspaceLayout, LibraryLayout)

**Files:**
- Create: `frontend/src/components/templates/AppShell.tsx`
- Create: `frontend/src/components/templates/AppShell.module.css`
- Create: `frontend/src/components/templates/WorkspaceLayout.tsx`
- Create: `frontend/src/components/templates/WorkspaceLayout.module.css`
- Create: `frontend/src/components/templates/LibraryLayout.tsx`
- Create: `frontend/src/components/templates/LibraryLayout.module.css`
- Modify: `frontend/src/app.tsx` — wrap routes with AppShell / layouts

- [ ] **Step 1: Create `AppShell.module.css`**

```css
.shell {
  display: grid;
  grid-template-columns: 220px 1fr;
  grid-template-rows: 48px 1fr;
  grid-template-areas:
    "topbar topbar"
    "sidebar main";
  height: 100vh;
}

.topbar {
  grid-area: topbar;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}

.brand {
  font-weight: 600;
  letter-spacing: 0.02em;
}

.healthDot {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-xs);
  color: var(--text-muted, var(--text));
}

.healthDot::before {
  content: "";
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-muted);
}

.healthDot[data-status="ok"]::before {
  background: #4f7d3a;
}

.healthDot[data-status="down"]::before {
  background: #c96442;
}

.sidebar {
  grid-area: sidebar;
  border-right: 1px solid var(--border);
  background: var(--surface);
  overflow-y: auto;
  padding: 12px;
}

.sidebarNav {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.sidebarLink {
  padding: 6px 10px;
  border-radius: 4px;
  text-decoration: none;
  color: var(--text);
  font-size: var(--text-sm);
}

.sidebarLink:hover {
  background: var(--bg-muted);
}

.sidebarLink.active {
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  color: var(--accent);
}

.main {
  grid-area: main;
  overflow: auto;
}
```

- [ ] **Step 2: Create `AppShell.tsx`**

```tsx
import { NavLink, Outlet } from "react-router-dom";
import { useHealth } from "@/api/health";
import styles from "./AppShell.module.css";

export function AppShell() {
  const health = useHealth();
  const status = health.isError ? "down" : health.data?.status === "ok" ? "ok" : "pending";
  return (
    <div className={styles.shell}>
      <header className={styles.topbar}>
        <span className={styles.brand}>sd-chisel</span>
        <span className={styles.healthDot} data-status={status}>
          backend {status}
        </span>
      </header>
      <aside className={styles.sidebar}>
        <nav className={styles.sidebarNav}>
          <NavLink
            to="/projects/scrapyard/sessions/default"
            className={({ isActive }) =>
              isActive ? `${styles.sidebarLink} ${styles.active}` : styles.sidebarLink
            }
          >
            Workspace
          </NavLink>
          <NavLink
            to="/library/families"
            className={({ isActive }) =>
              isActive ? `${styles.sidebarLink} ${styles.active}` : styles.sidebarLink
            }
          >
            Library — Families
          </NavLink>
          <NavLink
            to="/library/models"
            className={({ isActive }) =>
              isActive ? `${styles.sidebarLink} ${styles.active}` : styles.sidebarLink
            }
          >
            Library — Models
          </NavLink>
          <NavLink
            to="/library/loras"
            className={({ isActive }) =>
              isActive ? `${styles.sidebarLink} ${styles.active}` : styles.sidebarLink
            }
          >
            Library — LoRAs
          </NavLink>
        </nav>
      </aside>
      <main className={styles.main}>
        <Outlet />
      </main>
    </div>
  );
}
```

- [ ] **Step 3: Create `WorkspaceLayout.module.css`**

```css
.layout {
  height: 100%;
  display: flex;
  flex-direction: column;
}
```

- [ ] **Step 4: Create `WorkspaceLayout.tsx`**

```tsx
import type { ReactNode } from "react";
import styles from "./WorkspaceLayout.module.css";

export function WorkspaceLayout({ children }: { children: ReactNode }) {
  return <div className={styles.layout}>{children}</div>;
}
```

- [ ] **Step 5: Create `LibraryLayout.module.css` + `LibraryLayout.tsx`**

`LibraryLayout.module.css`:
```css
.layout {
  padding: 24px;
  max-width: 1200px;
  margin: 0 auto;
}
```

`LibraryLayout.tsx`:
```tsx
import type { ReactNode } from "react";
import styles from "./LibraryLayout.module.css";

export function LibraryLayout({ children }: { children: ReactNode }) {
  return <div className={styles.layout}>{children}</div>;
}
```

- [ ] **Step 6: Update `frontend/src/app.tsx` to use AppShell via nested routes**

```tsx
import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { queryClient } from "./api/client";
import { AppShell } from "./components/templates/AppShell";
import { WorkspaceLayout } from "./components/templates/WorkspaceLayout";
import { LibraryLayout } from "./components/templates/LibraryLayout";
import WorkspaceRoute from "./routes/workspace";
import FamiliesRoute from "./routes/library/families";
import ModelsRoute from "./routes/library/models";
import LorasRoute from "./routes/library/loras";

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route
              path="/"
              element={<Navigate to="/projects/scrapyard/sessions/default" replace />}
            />
            <Route
              path="/projects/:projectId/sessions/:sessionId"
              element={
                <WorkspaceLayout>
                  <WorkspaceRoute />
                </WorkspaceLayout>
              }
            />
            <Route
              path="/library/families"
              element={
                <LibraryLayout>
                  <FamiliesRoute />
                </LibraryLayout>
              }
            />
            <Route
              path="/library/models"
              element={
                <LibraryLayout>
                  <ModelsRoute />
                </LibraryLayout>
              }
            />
            <Route
              path="/library/loras"
              element={
                <LibraryLayout>
                  <LorasRoute />
                </LibraryLayout>
              }
            />
            <Route path="*" element={<div style={{ padding: 24 }}>404</div>} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
```

- [ ] **Step 7: Verify build**

Run (from `frontend/`): `pnpm build`
Expected: passes, no TS errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/templates frontend/src/app.tsx
git commit -m "feat(frontend): AppShell + Workspace/Library layouts with backend health dot"
```

---

### Task 13: Vitest sanity + AppShell smoke test

**Files:**
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/src/components/templates/AppShell.test.tsx`

- [ ] **Step 1: Create `frontend/src/test/setup.ts`**

```ts
import "@testing-library/jest-dom";
```

- [ ] **Step 2: Write smoke test for AppShell**

Create `frontend/src/components/templates/AppShell.test.tsx`:
```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { AppShell } from "./AppShell";

function renderWithShell() {
  // Don't let useHealth fire a real fetch — tests mock it to return pending.
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<div>child</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AppShell", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
  });

  it("renders the brand, sidebar nav links, and the child outlet", () => {
    renderWithShell();
    expect(screen.getByText("sd-chisel")).toBeInTheDocument();
    expect(screen.getByText("Workspace")).toBeInTheDocument();
    expect(screen.getByText(/Library — Families/)).toBeInTheDocument();
    expect(screen.getByText("child")).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run vitest**

Run (from `frontend/`): `pnpm test`
Expected: 1 file, 1 test passed.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/test frontend/src/components/templates/AppShell.test.tsx
git commit -m "test(frontend): vitest setup + AppShell smoke test"
```

---

## Phase C — Integration

### Task 14: End-to-end health probe check

Verify that the frontend's `useHealth` hook actually talks to the backend `/health` endpoint through the Vite proxy.

- [ ] **Step 1: Start backend**

Run (from `backend/`):
```bash
.venv/Scripts/python -m uvicorn app.main:app --port 8000 &
```

- [ ] **Step 2: Start frontend dev server**

Run (from `frontend/`):
```bash
pnpm dev &
sleep 3
```

- [ ] **Step 3: Probe via proxy**

Run:
```bash
curl -s http://localhost:5173/health
```
Expected: `{"status":"ok"}` (proxied from backend:8000).

- [ ] **Step 4: Open the app in a browser** (manual)

Navigate to `http://localhost:5173/` → should redirect to the workspace route, show the AppShell with sidebar, and the health dot should show `backend ok` once the poll fires.

- [ ] **Step 5: Stop servers**

Run:
```bash
kill %1 %2 2>/dev/null
```

- [ ] **Step 6: Commit** (nothing to commit — this is a verification task. If the probe failed, debug before moving on.)

---

### Task 15: README with dev instructions

**Files:**
- Modify (or create): `README.md` at repo root

- [ ] **Step 1: Write README**

Create `README.md` with:

```markdown
# sd-chisel

Local Windows prompt-writer for Stable Diffusion i2i via ComfyUI. Library of LoRAs and models, VL image analysis, chat-driven prompt generation.

See:
- [Technical spec](docs/spec/technical_specifications.md)
- [Roadmap](docs/superpowers/specs/2026-04-23-mvp-roadmap-design.md)

## Prerequisites

- Python 3.11+
- Node.js 20+ with pnpm (`npm i -g pnpm`)
- `uv` recommended (`pip install uv`); plain pip works too
- LMStudio (or any OpenAI-compatible endpoint) running locally — required in Slice 3+, not for foundation

## First-time setup

```bash
# Backend
cd backend
uv venv
uv pip install -e ".[dev]"
python -m app.cli.init_db          # applies migrations, seeds 10 families

# Frontend
cd ../frontend
pnpm install
```

## Day-to-day

Two terminals:

```bash
# Terminal 1 — backend
cd backend && .venv/Scripts/python -m uvicorn app.main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend && pnpm dev
```

Open http://localhost:5173/.

## Tests

```bash
# Backend
cd backend && .venv/Scripts/python -m pytest

# Frontend
cd frontend && pnpm test
```

## Data

All runtime state — sqlite DB + uploaded images — lives under `./data/` at the repo root. This directory is git-ignored. Delete it to reset everything.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README with dev setup instructions"
```

---

### Task 16: Final verification pass

- [ ] **Step 1: Run backend tests**

Run (from `backend/`): `pytest`
Expected: all green. Count = 15+.

- [ ] **Step 2: Run frontend tests**

Run (from `frontend/`): `pnpm test`
Expected: all green.

- [ ] **Step 3: Run lints**

Run:
```bash
(cd backend && .venv/Scripts/python -m ruff check .)
(cd frontend && pnpm lint)
```
Expected: no errors (warnings ok).

- [ ] **Step 4: Run `pnpm build` + uvicorn smoke** once more

Run:
```bash
(cd frontend && pnpm build)
(cd backend && .venv/Scripts/python -m uvicorn app.main:app --port 8000 &)
sleep 2
curl -s http://127.0.0.1:8000/health
kill %1
```
Expected: frontend build green, `/health` returns `{"status":"ok"}`.

- [ ] **Step 5: Verify `data/` contents**

Run: `ls ../data && ls ../data/images 2>/dev/null || echo "(no images yet — expected)"`
Expected: `app.db` exists, `images/` may be absent (created lazily).

- [ ] **Step 6: Final commit** (only if anything dangling)

```bash
git status
# If clean, we're done. Otherwise commit with an appropriate message.
```

---

## Done criteria

Foundation phase is complete when:

1. `pnpm dev` + `uvicorn app.main:app` both start cleanly.
2. Browser at http://localhost:5173/ shows AppShell with a live-polling backend health indicator.
3. All routes (`/projects/:p/sessions/:s`, `/library/{families,models,loras}`) render placeholder content inside the shell.
4. `python -m app.cli.init_db` applies both migrations, 10 families are seeded.
5. `pytest` (backend) + `pnpm test` (frontend) are green.
6. `data/app.db` exists and is git-ignored.
7. No business features exist — no upload, no chat, no generate-prompt, no library CRUD endpoints. That's intentional: those are Slice 1+.

Next step after this plan: brainstorming → writing-plans for **Slice 1 (Library CRUD)**.
