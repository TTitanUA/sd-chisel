# Slice 5 — Embedder + Indexer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every Library write (`POST/PUT/DELETE /api/library/loras`) keeps the `vec_loras` + `lora_vec_map` tables consistent with the canonical `loras` row, in one transaction. A new `reindex-all` CLI rebuilds the whole vector index for migration / cold-start. Embeddings come from a lazy-loaded `BAAI/bge-m3` (1024-dim) sentence-transformers model. Tests never download the model — they inject a fake embedder via a module-level monkeypatch hook.

**Architecture:** Three new backend modules. `app/services/embedder.py` wraps sentence-transformers behind a module-level `embed(text) -> list[float]` function with lazy model loading; this is the seam every test monkeypatches. `app/services/indexer.py` is pure SQL — given a connection + name + embedding bytes, it upserts/deletes the `vec_loras` row and the `lora_vec_map` mapping. `app/services/library_service.py` is the new transactional façade: it wraps `library_repo.{create,update,delete}_lora` + `indexer` in a single `BEGIN/COMMIT` so a failing embedder rolls back the whole write. `LoraOut` gets one derived field (`is_indexed: bool`) computed via a `LEFT JOIN lora_vec_map`; the frontend shows a small badge from it. The CLI just iterates all LoRAs and re-runs the upsert path. No schema migration — Foundation already created `vec_loras` and `lora_vec_map`.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, `sentence-transformers>=3.0` (pulls torch — Windows wheels exist on PyPI), `sqlite-vec` (already installed; uses `sqlite_vec.serialize_float32(...)` to bind FLOAT[1024] params), pytest with `monkeypatch`. Frontend: React 18 + TS + TanStack Query (no new deps). The embedder model `BAAI/bge-m3` is downloaded by sentence-transformers on first use to `~/.cache/huggingface/`; we do NOT bundle it and we do NOT preload at startup (lazy on first request).

**Reference docs checked while writing this plan:**
- Roadmap §4 Slice 5 (boundaries, acceptance, handoff): `docs/superpowers/specs/2026-04-23-mvp-roadmap-design.md`
- Spec §3 (vec_loras / lora_vec_map / cascade rules), §5 indexer behavior, §7 dep `BAAI/bge-m3`: `docs/spec/technical_specifications.md`
- Slice-4 plan structure / test patterns: `docs/superpowers/plans/2026-04-26-slice-4-chat-sse.md`
- Existing `library_repo`, `library` API and `tests/test_library_*.py` for transaction conventions: `backend/app/storage/library_repo.py`, `backend/app/api/library.py`, `backend/tests/test_library_repo.py`
- Foundation `reindex_all` stub it replaces: `backend/app/cli/reindex_all.py`

---

## Pre-flight: state at start of slice

After Slice 4 the codebase has:

- `vec_loras` virtual table (`vec0(embedding FLOAT[1024])`) and `lora_vec_map(lora_name PK FK→loras ON DELETE CASCADE, rowid INTEGER NOT NULL UNIQUE)` created in `001_init.sql:41-46`. **Currently unused** — no rows are ever written to either.
- `library_repo.create_lora` and `update_lora` each wrap their single SQL statement in their own `BEGIN/COMMIT` (`backend/app/storage/library_repo.py:217-243` and `:262-291`). Slice 5 strips those inner transactions so the new service can wrap repo+indexer in one outer transaction.
- `library_repo.delete_lora` is a single `DELETE` (no transaction). `lora_vec_map` already cascades by FK when a `loras` row is deleted — but `vec_loras` rows do NOT cascade (sqlite-vec virtual tables can't be FK targets). Slice 5 adds explicit `DELETE FROM vec_loras WHERE rowid = ?` driven by the mapping table, executed BEFORE the `loras` row is dropped (because the cascade wipes the mapping).
- `app/api/library.py` calls `library_repo` directly for all three LoRA endpoints (`backend/app/api/library.py:144-167`). Slice 5 redirects only the LoRA endpoints to `library_service`; family / model endpoints are untouched.
- `LoraOut` pydantic schema (`backend/app/models/library.py:60-72`) has 12 fields; Slice 5 adds `is_indexed: bool` (read-only — never accepted on create/update).
- `app/cli/reindex_all.py` is a `SystemExit` stub (`backend/app/cli/reindex_all.py:5-9`). Slice 5 replaces it with the real implementation.
- Frontend `Lora` type (`frontend/src/api/library.ts:30-43`) has 12 fields; Slice 5 adds `is_indexed: boolean`. `routes/library/loras.tsx` renders LoRA detail in a `LibraryCrud` block — Slice 5 adds one small badge to the existing meta cells.
- `backend/pyproject.toml` already has `sqlite-vec`, `numpy`, `httpx`. Slice 5 adds `sentence-transformers>=3.0`. No new frontend deps.

These are the assumed inputs; do not pre-implement them.

---

## File Structure

Create or modify only the files below.

```
backend/
├── pyproject.toml                                # add sentence-transformers
├── app/
│   ├── services/
│   │   ├── embedder.py                           # NEW — lazy bge-m3, module-level embed()
│   │   ├── indexer.py                            # NEW — pure vec_loras + lora_vec_map ops
│   │   └── library_service.py                    # NEW — transactional repo+indexer façade
│   ├── api/
│   │   └── library.py                            # modify: lora endpoints route to service
│   ├── cli/
│   │   └── reindex_all.py                        # replace stub with real impl
│   ├── storage/
│   │   └── library_repo.py                       # remove inner BEGIN/COMMIT from lora ops; add list_all_lora_names
│   └── models/
│       └── library.py                            # add is_indexed to LoraOut (read-only)
└── tests/
    ├── test_embedder.py                          # NEW — text builder + lazy-load seam
    ├── test_indexer.py                           # NEW — vec_loras / lora_vec_map round-trip
    ├── test_library_service.py                   # NEW — repo+indexer orchestration, rollback on embed fail
    ├── test_reindex_all.py                       # NEW — CLI smoke with fake embedder
    └── test_library_api.py                       # extend — is_indexed surfaced, embed failure → 500
└── conftest.py (project-level, NEW)              # NEW — autouse fake embedder for tests/

frontend/
└── src/
    ├── api/
    │   └── library.ts                            # add is_indexed?: boolean on Lora
    └── routes/
        └── library/
            ├── loras.tsx                         # add Indexed badge cell to detail meta
            └── libraryRoutes.test.tsx            # extend — assert badge renders for indexed lora
```

No DB migration. No new frontend dep. No new CSS file (badge reuses existing `Badge` atom).

---

## API Contract (delta vs Slice 4)

```
GET    /api/library/loras                  -> Lora[]     (each row gains is_indexed: bool)
GET    /api/library/loras/{name}           -> Lora       (is_indexed reflects current state)

POST   /api/library/loras                  -> Lora       (now also writes vec_loras + lora_vec_map)
PUT    /api/library/loras/{name}           -> Lora       (now also re-embeds + replaces vector)
DELETE /api/library/loras/{name}           -> 204        (now also deletes vec_loras row)

  500 — embedder failure (whole write rolled back, no orphan rows)
```

Type delta:

```ts
type Lora = {
  // ...existing 12 fields...
  is_indexed: boolean;   // NEW — true iff lora_vec_map has a row for this name
};
```

`LoraCreate` / `LoraUpdate` are NOT extended — `is_indexed` is server-derived only. Pydantic `extra="forbid"` keeps callers from sending it.

No other endpoint changes; no new endpoints in this slice.

---

## CLI contract (delta vs Slice 4)

```
uv run reindex-all
    Reads every row from `loras`, recomputes the embedding for each, replaces the
    matching vec_loras row + upserts lora_vec_map. Prints one line per LoRA
    (`indexed: <name>` or `failed: <name> — <reason>`) and a final summary
    (`indexed=<n> failed=<m> total=<n+m>`). Exits 0 if all succeed, 1 if any failed.
```

Already declared in `pyproject.toml`:

```toml
[project.scripts]
reindex-all = "app.cli.reindex_all:main"
```

(Foundation registered the script; Slice 5 only wires the body.) ⚠️ **Verify in Task 7**: the script may not be registered yet. If `[project.scripts]` is missing the entry, add it in that task — that file edit is part of Task 7.

---

## Cross-cutting design notes

- **The single seam.** Every test that would otherwise exercise sentence-transformers monkeypatches `app.services.embedder.embed`. To make sure no test ever pulls bge-m3, we add a project-level `tests/conftest.py` with an `autouse=True` fixture that replaces `embedder.embed` with a deterministic fake (`hash(text)` seeded → 1024 floats). Tests that want to control the value override per-test.
- **Why a `library_service` module instead of fattening the repo.** The repo is intentionally dumb (raw CRUD). The indexer is intentionally pure SQL (no embedder import). The service is the only place that knows about both — and the only place that opens an outer transaction. This keeps the repo and indexer independently testable and gives one obvious place to read for "what happens on a LoRA write".
- **Transaction model.** All sqlite connections in this codebase run with `isolation_level=None` (`backend/app/storage/db.py:22`) — i.e. autocommit mode. Transactions are explicit `BEGIN/COMMIT/ROLLBACK`. The service wraps every write in one such pair. The repo functions, after Slice 5, must NOT issue their own `BEGIN/COMMIT` — otherwise nested transactions raise `sqlite3.OperationalError: cannot start a transaction within a transaction`. The single-statement `INSERT INTO loras(...)` is already atomic on its own; removing the inner `BEGIN` does not weaken durability.
- **Vector serialization.** sqlite-vec ships `sqlite_vec.serialize_float32(list[float]) -> bytes`. Bind those bytes to a `?` placeholder against `vec_loras.embedding`. Direct list-of-floats binding does not work; JSON strings work but are wasteful.
- **Update strategy on `vec_loras`.** Virtual tables in sqlite-vec accept `UPDATE vec_loras SET embedding = ? WHERE rowid = ?` (verified by inspection of the `vec0` module — single-column update in-place). The service uses UPDATE when a `lora_vec_map` row exists for the name, INSERT + new mapping otherwise.
- **Embedding text builder.** `description + " | " + ", ".join(tags) + " | " + ", ".join(trigger_words)` (separators picked so bge-m3 sees three distinct chunks). `display_name` is intentionally NOT included — it's almost always either equal to `name` or a trivial casing variant, and adds no semantic value. Note the trailing-empty-tag list cases: `"desc | | "` is a valid string and embeds fine.
- **Why no `embedded_at` column.** Roadmap acceptance only asks for "appears/updates/disappears" — a derived `is_indexed` boolean is enough for both UI and CLI summary. Adding a timestamp column requires a migration and isn't used anywhere; YAGNI.
- **Why frontend stays minimal.** Roadmap §4 Slice 5 says "minimal status in LoRA form/list: indexing/indexed/error, if it doesn't bloat API; otherwise frontend only shows normal save success". Because the API is fully synchronous (no "indexing" mid-state — either the request returns 2xx with the row indexed, or it returns 500 with no row at all), the only value to surface is `is_indexed`. We render it as one badge in the detail view; no new component, no new query.
- **bge-m3 download disclaimer.** First call to `embedder.embed` in production triggers a ~2GB download to `~/.cache/huggingface/`. README gets a one-line note in Task 9. This matches roadmap §5 risk.

---

## Task 1 — Add sentence-transformers dependency

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Add the dep**

In `backend/pyproject.toml`, extend the `dependencies` list:

```toml
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.32",
  "pydantic>=2.9",
  "sqlite-vec>=0.1.6",
  "numpy>=1.26",
  "python-multipart>=0.0.12",
  "httpx>=0.27",
  "sentence-transformers>=3.0",
]
```

- [ ] **Step 2: Sync the lockfile**

From `backend/`:
```bash
uv sync
```
Expected: `sentence-transformers` (and its transitive `torch`, `transformers`, etc.) added to `uv.lock`. This may take several minutes the first time. If `uv` is unavailable, fall back to `pip install -e ".[dev]"`.

- [ ] **Step 3: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock
git commit -m "chore(deps): add sentence-transformers for slice-5 embedder"
```

---

## Task 2 — Embedder service (lazy bge-m3 wrapper)

**Files:**
- Create: `backend/app/services/embedder.py`
- Create: `backend/tests/test_embedder.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_embedder.py`:

```python
from __future__ import annotations

import pytest

from app.services import embedder


def test_build_embedding_text_joins_description_tags_triggers():
    text = embedder.build_embedding_text({
        "description": "moody portrait",
        "tags": ["portrait", "moody"],
        "trigger_words": ["dramatic light"],
    })
    assert text == "moody portrait | portrait, moody | dramatic light"


def test_build_embedding_text_handles_empty_lists():
    text = embedder.build_embedding_text({
        "description": "x",
        "tags": [],
        "trigger_words": [],
    })
    assert text == "x |  | "


def test_embed_calls_loaded_model_and_returns_list_of_floats(monkeypatch):
    captured: dict[str, object] = {}

    class FakeModel:
        def encode(self, text, normalize_embeddings=False):
            captured["text"] = text
            captured["normalize"] = normalize_embeddings
            return [0.1] * 1024

    monkeypatch.setattr(embedder, "_get_model", lambda: FakeModel())
    out = embedder.embed("hello")
    assert isinstance(out, list)
    assert len(out) == 1024
    assert all(isinstance(x, float) for x in out)
    assert captured["text"] == "hello"
    assert captured["normalize"] is True


def test_embed_raises_on_wrong_dimension(monkeypatch):
    class FakeModel:
        def encode(self, text, normalize_embeddings=False):
            return [0.0] * 768

    monkeypatch.setattr(embedder, "_get_model", lambda: FakeModel())
    with pytest.raises(embedder.EmbedderError):
        embedder.embed("hello")


def test_get_model_lazy_loads_once_and_caches(monkeypatch):
    embedder._reset_for_tests()
    calls = {"n": 0}

    def fake_loader():
        calls["n"] += 1
        return object()

    monkeypatch.setattr(embedder, "_load_sentence_transformer", fake_loader)
    a = embedder._get_model()
    b = embedder._get_model()
    assert a is b
    assert calls["n"] == 1
    embedder._reset_for_tests()
```

- [ ] **Step 2: Run tests to verify failure**

From `backend/`:
```bash
pytest tests/test_embedder.py -v
```
Expected: `ModuleNotFoundError: No module named 'app.services.embedder'`.

- [ ] **Step 3: Implement the embedder**

Create `backend/app/services/embedder.py`:

```python
"""Lazy wrapper around sentence-transformers `BAAI/bge-m3`.

The module-level `embed(text)` function is the seam every test monkeypatches —
no test code should ever cause sentence-transformers to actually load the model.
"""
from __future__ import annotations

from typing import Any

EMBEDDING_DIM = 1024  # BAAI/bge-m3 — must match `vec_loras` FLOAT[1024]
MODEL_NAME = "BAAI/bge-m3"

_model: Any | None = None


class EmbedderError(Exception):
    """Raised when embedding fails or returns an unexpected shape."""


def build_embedding_text(lora: dict[str, Any]) -> str:
    """Build the canonical text fed to the embedder for a LoRA row.

    Format: ``"<description> | <tag1, tag2, ...> | <trigger1, trigger2, ...>"``.
    `display_name` is intentionally excluded — it duplicates `name` semantically.
    """
    desc = str(lora.get("description") or "")
    tags = ", ".join(str(t) for t in (lora.get("tags") or []))
    triggers = ", ".join(str(t) for t in (lora.get("trigger_words") or []))
    return f"{desc} | {tags} | {triggers}"


def _load_sentence_transformer() -> Any:  # pragma: no cover — heavy I/O
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(MODEL_NAME)


def _get_model() -> Any:
    global _model
    if _model is None:
        _model = _load_sentence_transformer()
    return _model


def _reset_for_tests() -> None:
    global _model
    _model = None


def embed(text: str) -> list[float]:
    """Embed `text` → 1024-dim list of floats. Tests monkeypatch this."""
    model = _get_model()
    raw = model.encode(text, normalize_embeddings=True)
    vec = [float(x) for x in raw]
    if len(vec) != EMBEDDING_DIM:
        raise EmbedderError(
            f"unexpected embedding dim: got {len(vec)}, want {EMBEDDING_DIM}",
        )
    return vec
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/test_embedder.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/embedder.py backend/tests/test_embedder.py
git commit -m "feat(embedder): lazy bge-m3 wrapper with test-monkeypatch seam"
```

---

## Task 3 — Project-level test conftest with autouse fake embedder

**Files:**
- Create: `backend/tests/conftest.py` (replaces the comment-only stub)

The current `tests/conftest.py` is a comment-only file. We replace it with an autouse fixture that ensures no test code ever invokes the real sentence-transformers loader, even by accident through a code path we forgot to mock.

- [ ] **Step 1: Write a test that would fail without the autouse fixture**

Create `backend/tests/test_conftest_autouse.py`:

```python
from app.services import embedder


def test_embed_returns_fake_vector_in_tests():
    """Autouse fixture in conftest replaces embed with a deterministic fake."""
    out = embedder.embed("anything")
    assert isinstance(out, list)
    assert len(out) == 1024
    # Same input → same output across calls (deterministic fake)
    assert embedder.embed("anything") == out
    # Different inputs → different vectors
    assert embedder.embed("other") != out
```

- [ ] **Step 2: Run to confirm it fails (no autouse fixture yet)**

```bash
pytest tests/test_conftest_autouse.py -v
```
Expected: hangs or raises trying to download bge-m3, OR fails with network/import error. Cancel after a few seconds with Ctrl-C if it hangs — the failure is the point. This file gets deleted in Step 5.

- [ ] **Step 3: Implement the autouse fixture**

Replace the entire contents of `backend/tests/conftest.py` with:

```python
"""Project-wide pytest fixtures.

The `_fake_embedder` fixture is autouse so NO test ever loads the real
sentence-transformers model. Tests that need to control the embedding value
can re-monkeypatch `app.services.embedder.embed` per-test.
"""
from __future__ import annotations

import hashlib

import pytest

from app.services import embedder


def _deterministic_fake_vector(text: str) -> list[float]:
    """Return a 1024-float vector seeded by `text`. Stable across runs."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    # Cycle the digest until we have 1024 bytes; map each byte to [-1, 1).
    repeats = (1024 // len(digest)) + 1
    stretched = (digest * repeats)[:1024]
    return [(b - 128) / 128.0 for b in stretched]


@pytest.fixture(autouse=True)
def _fake_embedder(monkeypatch):
    monkeypatch.setattr(embedder, "embed", _deterministic_fake_vector)
    yield
    embedder._reset_for_tests()
```

- [ ] **Step 4: Run the autouse test to verify pass**

```bash
pytest tests/test_conftest_autouse.py -v
```
Expected: 1 passed.

- [ ] **Step 5: Drop the throwaway sanity test**

```bash
rm backend/tests/test_conftest_autouse.py
```

(Its only purpose was to prove the autouse fixture works; the next tasks all rely on it implicitly.)

- [ ] **Step 6: Sanity-check that the fake doesn't break the embedder unit tests**

```bash
pytest tests/test_embedder.py -v
```
Expected: 5 passed. (The embedder tests already monkeypatch `_get_model` per-test, so the autouse `embed` swap is irrelevant — they should still pass.)

- [ ] **Step 7: Commit**

```bash
git add backend/tests/conftest.py
git commit -m "test: autouse fake embedder so tests never download bge-m3"
```

---

## Task 4 — Indexer service (pure vec_loras + lora_vec_map ops)

**Files:**
- Create: `backend/app/services/indexer.py`
- Create: `backend/tests/test_indexer.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_indexer.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from app.services import indexer
from app.storage import db as db_mod
from app.storage import library_repo
from app.storage.migrations import apply_pending


@pytest.fixture
def conn(tmp_path):
    c = db_mod.connect(tmp_path / "indexer.db")
    apply_pending(c, Path(__file__).parent.parent / "migrations")
    yield c
    c.close()


def _make_lora(conn, name="l1") -> None:
    library_repo.create_lora(
        conn, name=name, display_name=name, description="d",
        tags=[], trigger_words=[], family_id="sdxl",
    )


def _vec(seed: int) -> list[float]:
    return [float(seed)] * 1024


def test_upsert_inserts_vector_and_mapping(conn):
    _make_lora(conn, "l1")
    indexer.upsert_lora_vector(conn, lora_name="l1", vector=_vec(1))

    mapping = conn.execute(
        "SELECT rowid FROM lora_vec_map WHERE lora_name = ?", ("l1",),
    ).fetchone()
    assert mapping is not None
    rowid = mapping[0]
    count = conn.execute(
        "SELECT COUNT(*) FROM vec_loras WHERE rowid = ?", (rowid,),
    ).fetchone()[0]
    assert count == 1


def test_upsert_replaces_existing_vector_in_place(conn):
    _make_lora(conn, "l1")
    indexer.upsert_lora_vector(conn, lora_name="l1", vector=_vec(1))
    rowid_before = conn.execute(
        "SELECT rowid FROM lora_vec_map WHERE lora_name = ?", ("l1",),
    ).fetchone()[0]

    indexer.upsert_lora_vector(conn, lora_name="l1", vector=_vec(2))
    mappings = conn.execute(
        "SELECT rowid FROM lora_vec_map WHERE lora_name = ?", ("l1",),
    ).fetchall()
    assert len(mappings) == 1
    assert mappings[0][0] == rowid_before  # same rowid, in-place update


def test_upsert_rejects_wrong_dimension(conn):
    _make_lora(conn, "l1")
    with pytest.raises(indexer.IndexerError):
        indexer.upsert_lora_vector(conn, lora_name="l1", vector=[0.0] * 768)


def test_delete_removes_vector_and_mapping(conn):
    _make_lora(conn, "l1")
    indexer.upsert_lora_vector(conn, lora_name="l1", vector=_vec(1))
    rowid = conn.execute(
        "SELECT rowid FROM lora_vec_map WHERE lora_name = ?", ("l1",),
    ).fetchone()[0]

    indexer.delete_lora_vector(conn, lora_name="l1")
    assert conn.execute(
        "SELECT COUNT(*) FROM lora_vec_map WHERE lora_name = ?", ("l1",),
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM vec_loras WHERE rowid = ?", (rowid,),
    ).fetchone()[0] == 0


def test_delete_is_noop_when_no_vector(conn):
    _make_lora(conn, "l1")
    # never indexed — delete should not raise
    indexer.delete_lora_vector(conn, lora_name="l1")


def test_is_indexed_helper(conn):
    _make_lora(conn, "l1")
    _make_lora(conn, "l2")
    indexer.upsert_lora_vector(conn, lora_name="l1", vector=_vec(1))
    assert indexer.is_indexed(conn, "l1") is True
    assert indexer.is_indexed(conn, "l2") is False
```

- [ ] **Step 2: Run tests to verify failure**

```bash
pytest tests/test_indexer.py -v
```
Expected: `ModuleNotFoundError: No module named 'app.services.indexer'`.

- [ ] **Step 3: Implement the indexer**

Create `backend/app/services/indexer.py`:

```python
"""Pure SQL ops over `vec_loras` + `lora_vec_map`.

This module knows nothing about the embedder, the repo, or HTTP — its only
job is to keep the two vector tables consistent with a given (name, vector)
pair under the caller's transaction.
"""
from __future__ import annotations

import sqlite3

import sqlite_vec

from app.services.embedder import EMBEDDING_DIM


class IndexerError(Exception):
    """Raised on shape violations or unexpected SQL state."""


def upsert_lora_vector(
    conn: sqlite3.Connection, *, lora_name: str, vector: list[float],
) -> None:
    """Insert or in-place update the vector for `lora_name`.

    Caller owns the transaction (this function issues no BEGIN/COMMIT).
    """
    if len(vector) != EMBEDDING_DIM:
        raise IndexerError(
            f"vector dim mismatch: got {len(vector)}, want {EMBEDDING_DIM}",
        )
    payload = sqlite_vec.serialize_float32(vector)

    existing = conn.execute(
        "SELECT rowid FROM lora_vec_map WHERE lora_name = ?", (lora_name,),
    ).fetchone()

    if existing is not None:
        conn.execute(
            "UPDATE vec_loras SET embedding = ? WHERE rowid = ?",
            (payload, existing[0]),
        )
        return

    cur = conn.execute(
        "INSERT INTO vec_loras(embedding) VALUES (?)", (payload,),
    )
    new_rowid = cur.lastrowid
    if new_rowid is None:
        raise IndexerError("vec_loras INSERT did not return a rowid")
    conn.execute(
        "INSERT INTO lora_vec_map(lora_name, rowid) VALUES (?, ?)",
        (lora_name, new_rowid),
    )


def delete_lora_vector(conn: sqlite3.Connection, *, lora_name: str) -> None:
    """Remove the vector + mapping for `lora_name`. No-op if not indexed.

    Must run BEFORE the `loras` row is deleted, because the FK cascade would
    drop the `lora_vec_map` row first and we'd lose the rowid we need to
    target `vec_loras`.
    """
    row = conn.execute(
        "SELECT rowid FROM lora_vec_map WHERE lora_name = ?", (lora_name,),
    ).fetchone()
    if row is None:
        return
    conn.execute("DELETE FROM vec_loras WHERE rowid = ?", (row[0],))
    conn.execute("DELETE FROM lora_vec_map WHERE lora_name = ?", (lora_name,))


def is_indexed(conn: sqlite3.Connection, lora_name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM lora_vec_map WHERE lora_name = ?", (lora_name,),
    ).fetchone() is not None
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/test_indexer.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/indexer.py backend/tests/test_indexer.py
git commit -m "feat(indexer): vec_loras + lora_vec_map upsert/delete primitives"
```

---

## Task 5 — Strip inner BEGIN/COMMIT from `library_repo` lora ops; add `list_all_lora_names`

**Files:**
- Modify: `backend/app/storage/library_repo.py`
- Modify: `backend/tests/test_library_repo.py`

- [ ] **Step 1: Write a failing test for the new helper and for transactionless behavior**

Append to `backend/tests/test_library_repo.py`:

```python
def test_list_all_lora_names_returns_sorted_keys(conn):
    library_repo.create_lora(
        conn, name="zeta", display_name="Z", description="d",
        tags=[], trigger_words=[], family_id="sdxl",
    )
    library_repo.create_lora(
        conn, name="alpha", display_name="A", description="d",
        tags=[], trigger_words=[], family_id="sdxl",
    )
    assert library_repo.list_all_lora_names(conn) == ["alpha", "zeta"]


def test_create_lora_inside_outer_transaction_does_not_nest(conn):
    """After Slice 5: caller may wrap create_lora in its own BEGIN/COMMIT."""
    conn.execute("BEGIN")
    library_repo.create_lora(
        conn, name="wrapped", display_name="W", description="d",
        tags=[], trigger_words=[], family_id="sdxl",
    )
    conn.execute("COMMIT")
    assert library_repo.get_lora(conn, "wrapped") is not None


def test_update_lora_inside_outer_transaction_does_not_nest(conn):
    library_repo.create_lora(
        conn, name="x", display_name="X", description="d",
        tags=[], trigger_words=[], family_id="sdxl",
    )
    conn.execute("BEGIN")
    library_repo.update_lora(
        conn, "x", display_name="X2", description="d2",
        tags=[], trigger_words=[], family_id="sdxl",
    )
    conn.execute("COMMIT")
    assert library_repo.get_lora(conn, "x")["display_name"] == "X2"
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_library_repo.py -v -k "list_all_lora_names or outer_transaction"
```
Expected: 1 missing-attribute, 2 `OperationalError: cannot start a transaction within a transaction` from the wrapper attempting nested `BEGIN`.

- [ ] **Step 3: Strip the inner BEGIN/COMMIT and add the helper**

In `backend/app/storage/library_repo.py`:

Replace the body of `create_lora` (currently `library_repo.py:215-244`) with:

```python
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
```

Replace the body of `update_lora` (currently `library_repo.py:247-292`) with:

```python
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
```

Append at the end of the file (after `delete_lora`):

```python
def list_all_lora_names(conn: sqlite3.Connection) -> list[str]:
    """Return every LoRA primary key, sorted. Used by `reindex-all` CLI."""
    return [r[0] for r in conn.execute("SELECT name FROM loras ORDER BY name")]
```

- [ ] **Step 4: Run all repo tests to verify no regression**

```bash
pytest tests/test_library_repo.py -v
```
Expected: all green (existing 11 + 3 new = 14 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/storage/library_repo.py backend/tests/test_library_repo.py
git commit -m "refactor(library_repo): drop inner tx from lora ops; add list_all_lora_names"
```

---

## Task 6 — `library_service` (transactional repo + indexer façade)

**Files:**
- Create: `backend/app/services/library_service.py`
- Create: `backend/tests/test_library_service.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_library_service.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from app.services import embedder, indexer, library_service
from app.storage import db as db_mod
from app.storage import library_repo
from app.storage.migrations import apply_pending


@pytest.fixture
def conn(tmp_path):
    c = db_mod.connect(tmp_path / "service.db")
    apply_pending(c, Path(__file__).parent.parent / "migrations")
    yield c
    c.close()


CREATE_KW = dict(
    display_name="Cinematic Light",
    description="dramatic rim light",
    tags=["light", "mood"],
    trigger_words=["cinematic"],
    family_id="sdxl",
    recommended_weight=0.8,
)


def test_create_writes_row_and_indexes_in_one_transaction(conn):
    out = library_service.create_lora(conn, name="cine", **CREATE_KW)
    assert out["name"] == "cine"
    assert out["is_indexed"] is True
    assert indexer.is_indexed(conn, "cine") is True


def test_create_rolls_back_when_embedder_fails(conn, monkeypatch):
    def boom(_text):
        raise embedder.EmbedderError("boom")

    monkeypatch.setattr(embedder, "embed", boom)
    with pytest.raises(embedder.EmbedderError):
        library_service.create_lora(conn, name="failrow", **CREATE_KW)
    # Neither the loras row nor any vector survived the failure
    assert library_repo.get_lora(conn, "failrow") is None
    assert indexer.is_indexed(conn, "failrow") is False


def test_update_re_embeds_in_place(conn):
    library_service.create_lora(conn, name="cine", **CREATE_KW)
    rowid_before = conn.execute(
        "SELECT rowid FROM lora_vec_map WHERE lora_name = ?", ("cine",),
    ).fetchone()[0]

    library_service.update_lora(
        conn, "cine",
        display_name="Cinematic Light v2",
        description="even more dramatic",
        tags=["light"],
        trigger_words=["cinematic", "drama"],
        family_id="sdxl",
        recommended_weight=0.85,
    )

    rowid_after = conn.execute(
        "SELECT rowid FROM lora_vec_map WHERE lora_name = ?", ("cine",),
    ).fetchone()[0]
    assert rowid_after == rowid_before


def test_update_rolls_back_when_embedder_fails(conn, monkeypatch):
    library_service.create_lora(conn, name="cine", **CREATE_KW)
    original = library_repo.get_lora(conn, "cine")

    def boom(_text):
        raise embedder.EmbedderError("boom")

    monkeypatch.setattr(embedder, "embed", boom)
    with pytest.raises(embedder.EmbedderError):
        library_service.update_lora(
            conn, "cine",
            display_name="changed",
            description="changed",
            tags=[], trigger_words=[],
            family_id="sdxl", recommended_weight=None,
        )

    after = library_repo.get_lora(conn, "cine")
    assert after["display_name"] == original["display_name"]
    assert after["description"] == original["description"]


def test_update_returns_none_when_lora_missing(conn):
    out = library_service.update_lora(
        conn, "missing",
        display_name="x", description="x",
        tags=[], trigger_words=[], family_id="sdxl",
        recommended_weight=None,
    )
    assert out is None


def test_delete_removes_row_and_vector_atomically(conn):
    library_service.create_lora(conn, name="cine", **CREATE_KW)
    assert library_service.delete_lora(conn, "cine") is True
    assert library_repo.get_lora(conn, "cine") is None
    assert indexer.is_indexed(conn, "cine") is False
    assert conn.execute(
        "SELECT COUNT(*) FROM vec_loras "
        "WHERE rowid IN (SELECT rowid FROM lora_vec_map WHERE lora_name = 'cine')",
    ).fetchone()[0] == 0


def test_delete_returns_false_when_missing(conn):
    assert library_service.delete_lora(conn, "missing") is False
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_library_service.py -v
```
Expected: `ModuleNotFoundError: No module named 'app.services.library_service'`.

- [ ] **Step 3: Implement the service**

Create `backend/app/services/library_service.py`:

```python
"""Coordinates `library_repo` and `indexer` under one outer transaction.

Every LoRA write goes through this module, never the repo directly. If the
embedder fails for create or update, we ROLLBACK so the database never has a
LoRA row without a matching vector (and vice versa).
"""
from __future__ import annotations

import sqlite3
from typing import Any

from app.services import embedder, indexer
from app.storage import library_repo


def _hydrated_with_index_status(
    conn: sqlite3.Connection, lora: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if lora is None:
        return None
    lora["is_indexed"] = indexer.is_indexed(conn, lora["name"])
    return lora


def _rollback(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("ROLLBACK")
    except sqlite3.OperationalError:
        pass


def create_lora(conn: sqlite3.Connection, **kwargs: Any) -> dict[str, Any]:
    conn.execute("BEGIN")
    try:
        row = library_repo.create_lora(conn, **kwargs)
        vector = embedder.embed(embedder.build_embedding_text(row))
        indexer.upsert_lora_vector(conn, lora_name=row["name"], vector=vector)
        conn.execute("COMMIT")
    except Exception:
        _rollback(conn)
        raise
    return _hydrated_with_index_status(conn, library_repo.get_lora(conn, row["name"]))  # type: ignore[return-value]


def update_lora(
    conn: sqlite3.Connection, name: str, **kwargs: Any,
) -> dict[str, Any] | None:
    conn.execute("BEGIN")
    try:
        updated = library_repo.update_lora(conn, name, **kwargs)
        if updated is None:
            conn.execute("COMMIT")  # nothing to roll back; still a clean exit
            return None
        vector = embedder.embed(embedder.build_embedding_text(updated))
        indexer.upsert_lora_vector(conn, lora_name=name, vector=vector)
        conn.execute("COMMIT")
    except Exception:
        _rollback(conn)
        raise
    return _hydrated_with_index_status(conn, library_repo.get_lora(conn, name))


def delete_lora(conn: sqlite3.Connection, name: str) -> bool:
    conn.execute("BEGIN")
    try:
        # vec_loras must be cleared BEFORE loras row goes away — the FK cascade
        # on lora_vec_map fires on the loras delete and would orphan vec_loras.
        indexer.delete_lora_vector(conn, lora_name=name)
        deleted = library_repo.delete_lora(conn, name)
        conn.execute("COMMIT")
    except Exception:
        _rollback(conn)
        raise
    return deleted


def reindex_one(conn: sqlite3.Connection, name: str) -> bool:
    """Re-embed and replace the vector for an existing LoRA. Used by `reindex-all`.

    Returns True on success, False if the LoRA is missing.
    """
    lora = library_repo.get_lora(conn, name)
    if lora is None:
        return False
    conn.execute("BEGIN")
    try:
        vector = embedder.embed(embedder.build_embedding_text(lora))
        indexer.upsert_lora_vector(conn, lora_name=name, vector=vector)
        conn.execute("COMMIT")
    except Exception:
        _rollback(conn)
        raise
    return True


def get_lora(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    """Read-through for the API layer — adds `is_indexed` to the row."""
    return _hydrated_with_index_status(conn, library_repo.get_lora(conn, name))


def list_loras(
    conn: sqlite3.Connection, *,
    family_id: str | None = None,
    tag: str | None = None,
    q: str | None = None,
) -> list[dict[str, Any]]:
    rows = library_repo.list_loras(conn, family_id=family_id, tag=tag, q=q)
    if not rows:
        return rows
    indexed = {
        r[0] for r in conn.execute(
            "SELECT lora_name FROM lora_vec_map WHERE lora_name IN ("
            + ",".join(["?"] * len(rows)) + ")",
            [row["name"] for row in rows],
        )
    }
    for r in rows:
        r["is_indexed"] = r["name"] in indexed
    return rows
```

- [ ] **Step 4: Run to verify pass**

```bash
pytest tests/test_library_service.py -v
```
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/library_service.py backend/tests/test_library_service.py
git commit -m "feat(library_service): transactional repo+indexer façade for lora writes"
```

---

## Task 7 — `is_indexed` on `LoraOut` + wire API to `library_service`

**Files:**
- Modify: `backend/app/models/library.py`
- Modify: `backend/app/api/library.py`
- Modify: `backend/tests/test_library_api.py`
- Modify: `backend/pyproject.toml` (verify `reindex-all` entry exists; add if missing)

- [ ] **Step 1: Write failing API tests**

Append to `backend/tests/test_library_api.py`:

```python
from app.services import embedder


def _make_lora_payload(**override):
    base = {
        "name": "cinelight",
        "display_name": "Cinematic Light",
        "description": "dramatic rim light",
        "tags": ["light"],
        "trigger_words": ["cinematic"],
        "family_id": "sdxl",
        "recommended_weight": 0.8,
        "author": None,
        "version": None,
        "source_url": None,
    }
    base.update(override)
    return base


def test_create_lora_returns_is_indexed_true(client):
    resp = client.post("/api/library/loras", json=_make_lora_payload())
    assert resp.status_code == 201
    body = resp.json()
    assert body["is_indexed"] is True


def test_list_loras_includes_is_indexed_for_each_row(client):
    client.post("/api/library/loras", json=_make_lora_payload(name="a"))
    client.post("/api/library/loras", json=_make_lora_payload(name="b"))
    rows = client.get("/api/library/loras").json()
    assert {r["name"]: r["is_indexed"] for r in rows} == {"a": True, "b": True}


def test_get_lora_includes_is_indexed(client):
    client.post("/api/library/loras", json=_make_lora_payload(name="z"))
    body = client.get("/api/library/loras/z").json()
    assert body["is_indexed"] is True


def test_update_lora_re_embeds_and_keeps_indexed(client):
    client.post("/api/library/loras", json=_make_lora_payload())
    resp = client.put(
        "/api/library/loras/cinelight",
        json={
            "display_name": "Cinematic Light 2",
            "description": "more drama",
            "tags": ["light"],
            "trigger_words": ["cinematic"],
            "family_id": "sdxl",
            "recommended_weight": 0.85,
            "author": None, "version": None, "source_url": None,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["is_indexed"] is True


def test_delete_lora_removes_vector_too(client, conn):
    client.post("/api/library/loras", json=_make_lora_payload())
    assert client.delete("/api/library/loras/cinelight").status_code == 204
    assert conn.execute(
        "SELECT COUNT(*) FROM lora_vec_map WHERE lora_name = 'cinelight'",
    ).fetchone()[0] == 0


def test_create_lora_returns_500_when_embedder_fails(client, conn, monkeypatch):
    def boom(_text):
        raise embedder.EmbedderError("simulated embedder failure")

    monkeypatch.setattr(embedder, "embed", boom)

    resp = client.post("/api/library/loras", json=_make_lora_payload(name="oops"))
    assert resp.status_code == 500
    # The whole write rolled back — no orphan loras row:
    assert conn.execute(
        "SELECT COUNT(*) FROM loras WHERE name = 'oops'",
    ).fetchone()[0] == 0


def test_lora_create_rejects_is_indexed_in_body(client):
    payload = _make_lora_payload()
    payload["is_indexed"] = True
    resp = client.post("/api/library/loras", json=payload)
    assert resp.status_code == 422
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_library_api.py -v -k "is_indexed or re_embeds or removes_vector or embedder_fails or rejects_is_indexed"
```
Expected: every new test fails (`is_indexed` missing from response, embedder failure returns 200, etc.).

- [ ] **Step 3: Add `is_indexed` to `LoraOut`**

In `backend/app/models/library.py`, modify `LoraOut`:

```python
class LoraOut(StrictModel):
    name: str
    display_name: str
    description: str
    tags: list[str]
    trigger_words: list[str]
    family_id: str
    recommended_weight: float | None
    author: str | None
    version: str | None
    source_url: str | None
    created_at: int
    updated_at: int
    is_indexed: bool = False
```

(Default `False` so that any code path that hands raw repo dicts to `LoraOut` doesn't 500. The service always sets it; the API only ever passes service-hydrated dicts.)

`LoraCreate` and `LoraUpdate` are NOT changed — `extra="forbid"` already rejects an `is_indexed` field on input, which the last new test verifies.

- [ ] **Step 4: Wire LoRA endpoints to `library_service`**

In `backend/app/api/library.py`:

- Add `from app.services import embedder, library_service` next to the existing `from app.storage import library_repo`.
- Add an exception translator near the other helpers:

```python
def _embedder_failure(exc: embedder.EmbedderError) -> HTTPException:
    return HTTPException(status_code=500, detail=f"embedder failed: {exc}")
```

- Replace `list_loras` (currently `library.py:125-132`):

```python
@router.get("/loras", response_model=list[LoraOut])
def list_loras(
    conn: Conn,
    family_id: str | None = None,
    tag: str | None = None,
    q: str | None = None,
):
    return library_service.list_loras(conn, family_id=family_id, tag=tag, q=q)
```

- Replace `get_lora` (currently `library.py:135-140`):

```python
@router.get("/loras/{name}", response_model=LoraOut)
def get_lora(name: str, conn: Conn):
    row = library_service.get_lora(conn, name)
    if row is None:
        raise _not_found("lora", name)
    return row
```

- Replace `create_lora` (currently `library.py:143-148`):

```python
@router.post("/loras", response_model=LoraOut, status_code=status.HTTP_201_CREATED)
def create_lora(body: LoraCreate, conn: Conn):
    try:
        return library_service.create_lora(conn, **_dump(body))
    except sqlite3.IntegrityError as exc:
        raise _conflict(exc) from exc
    except embedder.EmbedderError as exc:
        raise _embedder_failure(exc) from exc
```

- Replace `update_lora` (currently `library.py:151-159`):

```python
@router.put("/loras/{name}", response_model=LoraOut)
def update_lora(name: str, body: LoraUpdate, conn: Conn):
    try:
        row = library_service.update_lora(conn, name, **_dump(body))
    except sqlite3.IntegrityError as exc:
        raise _conflict(exc) from exc
    except embedder.EmbedderError as exc:
        raise _embedder_failure(exc) from exc
    if row is None:
        raise _not_found("lora", name)
    return row
```

- Replace `delete_lora` (currently `library.py:162-167`):

```python
@router.delete("/loras/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lora(name: str, conn: Conn):
    deleted = library_service.delete_lora(conn, name)
    if not deleted:
        raise _not_found("lora", name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

(Family and Model endpoints are unchanged — they still call `library_repo` directly.)

- [ ] **Step 5: Verify the `reindex-all` script entry**

Open `backend/pyproject.toml` and confirm `[project.scripts]` includes:

```toml
[project.scripts]
db-init = "app.cli.init_db:main"
dev = "app.cli.dev:main"
dev-seed = "app.cli.dev_seed:main"
reindex-all = "app.cli.reindex_all:main"
```

If `reindex-all` is missing, add the line. If you added it, also extend `tests/test_cli_scripts.py::test_pyproject_exposes_short_uv_scripts` to include the new entry:

```python
assert pyproject["project"]["scripts"] == {
    "db-init": "app.cli.init_db:main",
    "dev": "app.cli.dev:main",
    "dev-seed": "app.cli.dev_seed:main",
    "reindex-all": "app.cli.reindex_all:main",
}
```

- [ ] **Step 6: Run to verify all green**

```bash
pytest tests/test_library_api.py tests/test_cli_scripts.py -v
```
Expected: all green (existing + 7 new API tests).

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/library.py backend/app/api/library.py backend/pyproject.toml backend/tests/test_library_api.py backend/tests/test_cli_scripts.py
git commit -m "feat(library): wire indexer into lora endpoints; expose is_indexed"
```

---

## Task 8 — `reindex-all` CLI

**Files:**
- Modify: `backend/app/cli/reindex_all.py` (replace stub)
- Create: `backend/tests/test_reindex_all.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_reindex_all.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from app.cli import reindex_all
from app.services import embedder, indexer
from app.storage import db as db_mod
from app.storage import library_repo
from app.storage.migrations import apply_pending


@pytest.fixture
def conn(tmp_path):
    c = db_mod.connect(tmp_path / "rx.db")
    apply_pending(c, Path(__file__).parent.parent / "migrations")
    yield c
    c.close()


def _seed(conn, name: str) -> None:
    library_repo.create_lora(
        conn, name=name, display_name=name, description=f"d-{name}",
        tags=[], trigger_words=[], family_id="sdxl",
    )


def test_run_reindex_indexes_every_lora(conn):
    _seed(conn, "a")
    _seed(conn, "b")
    summary = reindex_all.run(conn)
    assert summary == {"indexed": 2, "failed": 0, "total": 2, "errors": []}
    assert indexer.is_indexed(conn, "a")
    assert indexer.is_indexed(conn, "b")


def test_run_reindex_replaces_existing_vectors_in_place(conn):
    _seed(conn, "a")
    # Initial index, then re-run — rowid stays the same
    reindex_all.run(conn)
    rowid_before = conn.execute(
        "SELECT rowid FROM lora_vec_map WHERE lora_name = 'a'",
    ).fetchone()[0]

    reindex_all.run(conn)
    rowid_after = conn.execute(
        "SELECT rowid FROM lora_vec_map WHERE lora_name = 'a'",
    ).fetchone()[0]
    assert rowid_after == rowid_before


def test_run_reindex_records_failures_and_continues(conn, monkeypatch):
    _seed(conn, "ok")
    _seed(conn, "bad")

    def selective(text):
        if "bad" in text:
            raise embedder.EmbedderError("nope")
        return [0.0] * 1024

    monkeypatch.setattr(embedder, "embed", selective)

    summary = reindex_all.run(conn)
    assert summary["indexed"] == 1
    assert summary["failed"] == 1
    assert summary["total"] == 2
    assert any("bad" in e for e in summary["errors"])
    assert indexer.is_indexed(conn, "ok") is True
    assert indexer.is_indexed(conn, "bad") is False


def test_main_exits_zero_on_full_success(conn, monkeypatch, capsys):
    _seed(conn, "a")
    monkeypatch.setattr(reindex_all, "_open_conn", lambda: conn)
    rc = reindex_all.main()
    assert rc == 0
    captured = capsys.readouterr()
    assert "indexed=1" in captured.out
    assert "failed=0" in captured.out


def test_main_exits_one_when_any_failed(conn, monkeypatch, capsys):
    _seed(conn, "bad")
    monkeypatch.setattr(reindex_all, "_open_conn", lambda: conn)

    def boom(_text):
        raise embedder.EmbedderError("nope")

    monkeypatch.setattr(embedder, "embed", boom)
    rc = reindex_all.main()
    assert rc == 1
    captured = capsys.readouterr()
    assert "failed=1" in captured.out
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_reindex_all.py -v
```
Expected: `AttributeError: module 'app.cli.reindex_all' has no attribute 'run'`.

- [ ] **Step 3: Replace the stub**

Replace the entire contents of `backend/app/cli/reindex_all.py` with:

```python
"""CLI: reindex every LoRA into vec_loras + lora_vec_map.

Invoke:  uv run reindex-all
"""
from __future__ import annotations

import sqlite3
import sys

from app.services import embedder, library_service
from app.storage import db as db_mod
from app.storage import library_repo


def _open_conn() -> sqlite3.Connection:
    return db_mod.connect()


def run(conn: sqlite3.Connection) -> dict:
    names = library_repo.list_all_lora_names(conn)
    indexed = 0
    failed = 0
    errors: list[str] = []
    for name in names:
        try:
            ok = library_service.reindex_one(conn, name)
        except embedder.EmbedderError as exc:
            failed += 1
            errors.append(f"{name}: {exc}")
            print(f"failed: {name} — {exc}", file=sys.stderr)
            continue
        if ok:
            indexed += 1
            print(f"indexed: {name}")
        else:
            failed += 1
            errors.append(f"{name}: row vanished mid-reindex")
    return {
        "indexed": indexed, "failed": failed,
        "total": len(names), "errors": errors,
    }


def main() -> int:
    conn = _open_conn()
    try:
        summary = run(conn)
    finally:
        conn.close()
    print(
        f"indexed={summary['indexed']} "
        f"failed={summary['failed']} "
        f"total={summary['total']}"
    )
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/test_reindex_all.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Run the full backend suite to confirm no regression**

```bash
pytest
```
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backend/app/cli/reindex_all.py backend/tests/test_reindex_all.py
git commit -m "feat(cli): real reindex-all that walks loras and rebuilds vec_loras"
```

---

## Task 9 — README note on first-run model download

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a short note**

Open `README.md` and append (or insert near the dev-seed note, if one exists) a section like:

```markdown
### First LoRA write triggers a model download

The indexer uses `BAAI/bge-m3` (≈2 GB) via `sentence-transformers`. The model
is downloaded the **first time** any of these happen:

- `POST` / `PUT` / `DELETE` on `/api/library/loras`
- `uv run reindex-all`

The download lands in the standard HuggingFace cache (`~/.cache/huggingface/`).
Subsequent calls are warm. Tests inject a fake embedder via
`backend/tests/conftest.py` and never hit the network.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: note that first lora write downloads bge-m3 (~2GB)"
```

---

## Task 10 — Frontend `Lora.is_indexed` field + detail badge

**Files:**
- Modify: `frontend/src/api/library.ts`
- Modify: `frontend/src/routes/library/loras.tsx`
- Modify: `frontend/src/routes/library/libraryRoutes.test.tsx`

- [ ] **Step 1: Write a failing UI test**

Open `frontend/src/routes/library/libraryRoutes.test.tsx` and find the existing test that mocks LoRA list/detail responses (look for `/api/library/loras` references). Add a new `it(...)` block at the bottom of the LoRA `describe`:

```tsx
it("renders an Indexed badge in the LoRA detail meta", async () => {
  // Reuse whatever fetch-mock pattern the existing tests use; the key bits are:
  //   GET /api/library/families  -> [{ id: "sdxl", display_name: "SDXL", prompt_guide: "" , created_at:0, updated_at:0 }]
  //   GET /api/library/loras     -> [{ ...indexed lora row..., is_indexed: true }]
  // After navigating to /library/loras and selecting the row:
  expect(await screen.findByText(/indexed/i)).toBeInTheDocument();
});
```

If the existing test file uses MSW handlers, extend the LoRA list handler to include `is_indexed: true` in every returned row. If it uses raw `vi.stubGlobal("fetch", …)` like `ChatPane.test.tsx` does, mirror that pattern. Either way: make sure your fixture `Lora` rows have `is_indexed: true` and that the detail render asserts the badge text appears.

- [ ] **Step 2: Run to verify failure**

From `frontend/`:
```bash
pnpm vitest run src/routes/library/libraryRoutes.test.tsx
```
Expected: the new "Indexed badge" test fails (no badge rendered yet); existing tests pass.

- [ ] **Step 3: Add `is_indexed` to the type**

In `frontend/src/api/library.ts`, extend the `Lora` type:

```ts
export type Lora = {
  name: string;
  display_name: string;
  description: string;
  tags: string[];
  trigger_words: string[];
  family_id: string;
  recommended_weight: number | null;
  author: string | null;
  version: string | null;
  source_url: string | null;
  created_at: number;
  updated_at: number;
  is_indexed: boolean;
};
```

`LoraCreate` and `LoraUpdate` both derive from `Lora`:

```ts
export type LoraCreate = Omit<Lora, "created_at" | "updated_at" | "is_indexed">;
export type LoraUpdate = Omit<LoraCreate, "name">;
```

(Add `| "is_indexed"` to the existing `Omit` clauses; don't let the field leak into create/update payloads.)

- [ ] **Step 4: Render the badge in the LoRA detail meta**

In `frontend/src/routes/library/loras.tsx`, find the `cells={[...]}` array passed to `<LibraryDetailMeta>` (around `loras.tsx:184-207`). Insert a new cell BEFORE the `Updated` cell:

```tsx
{
  label: "Index",
  value: (
    <Badge variant={selected.is_indexed ? "accent" : "neutral"}>
      {selected.is_indexed ? "Indexed" : "Not indexed"}
    </Badge>
  ),
},
```

`Badge` is already imported at the top of the file. No other changes.

- [ ] **Step 5: Run the UI test to verify pass**

```bash
pnpm vitest run src/routes/library/libraryRoutes.test.tsx
```
Expected: all tests pass.

- [ ] **Step 6: Run the full frontend test suite**

```bash
pnpm vitest run
```
Expected: all green. If `LoraForm`-related tests fail because of the `Omit` change widening the create/update payload type, fix the test fixtures by removing the implicit `is_indexed` from the LoRA literal they pass to the form.

- [ ] **Step 7: Type-check**

```bash
pnpm tsc --noEmit
```
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api/library.ts frontend/src/routes/library/loras.tsx frontend/src/routes/library/libraryRoutes.test.tsx
git commit -m "feat(library-ui): show Indexed/Not indexed badge in LoRA detail"
```

---

## Task 11 — End-to-end manual smoke (real bge-m3, real LoRA round-trip)

Per `~/.claude/rules/manual-testing.md`, drive the UI yourself instead of asking the user to. This is the only place the real model is allowed to load — every other check uses the autouse fake.

- [ ] **Step 1: Boot the backend in the background**

From `backend/`:
```bash
uv run uvicorn app.main:app --reload --port 8000
```
(`run_in_background: true`)

- [ ] **Step 2: Boot the frontend dev server**

Use `preview_start` against the frontend dev server (`pnpm dev` in `frontend/`).

- [ ] **Step 3: Drive the LoRA flow in the browser**

1. Navigate to `/library/loras`.
2. Click `New` and create a LoRA: `name=smoke_lora`, `display_name=Smoke Test`, `description=warm cinematic light`, `tags=[light]`, `trigger_words=[smoke]`, `family_id=sdxl`, `recommended_weight=0.7`.
3. Submit. **First submit will hang ~30–120 s while bge-m3 downloads** — this is expected. Confirm the request eventually returns 201 by watching `preview_network`.
4. Take a `preview_snapshot`. Verify the detail panel for `smoke_lora` shows the `Indexed` badge.
5. Edit the LoRA, change description to `cool cinematic light`, save. Verify the row remains `Indexed` and the rowid in `lora_vec_map` did not change (run `sqlite3 backend/../data/app.db "SELECT rowid FROM lora_vec_map WHERE lora_name='smoke_lora'"` from a separate shell — same value before/after edit).
6. Delete `smoke_lora`. Verify `lora_vec_map` row is gone (`SELECT * FROM lora_vec_map WHERE lora_name='smoke_lora'` returns 0 rows) and so is the `vec_loras` row.
7. Recreate `smoke_lora`, then run `uv run reindex-all` from `backend/`. Verify stdout shows `indexed=1 failed=0 total=1` and exit code is 0.

- [ ] **Step 4: Take a screenshot for the record**

Use `preview_screenshot` on the LoRA detail page with the `Indexed` badge visible.

- [ ] **Step 5: Tear down**

Kill the background `uvicorn` (Windows: `taskkill /F /PID <pid>`) and stop the frontend preview.

- [ ] **Step 6: Commit (no code changes — empty if everything passed)**

If you fixed anything during smoke, commit those fixes individually with a clear message. If nothing needed fixing, skip this step.

---

## Risks & fallbacks

- **bge-m3 download.** ~2 GB on first call. Documented in README. If a dev cannot afford it, they can monkeypatch `embedder._load_sentence_transformer` to return a deterministic fake at runtime — but only for local dev, never as a fallback in production code.
- **sqlite-vec UPDATE on virtual table.** If `UPDATE vec_loras SET embedding = ? WHERE rowid = ?` raises `Operation not supported`, the indexer falls back to `DELETE` + `INSERT` and rewrites the `lora_vec_map.rowid` accordingly. Detect during Task 4 tests; if needed, change `upsert_lora_vector` to always delete-and-reinsert (a few extra lines, no API change). Roadmap risk §5.
- **Embedder cold start blocking the request loop.** First call takes 10–30 s (model load) plus download time on cold cache. For Slice 5 we accept this — single-user local app. Post-MVP could preload at startup or move embedding to a worker queue.
- **Torch wheels on Windows.** sentence-transformers pulls torch; PyPI ships precompiled CPU wheels for Windows on Python 3.11/3.12. If install fails, `uv add --index-url https://download.pytorch.org/whl/cpu torch` first, then retry `uv sync`.

---

## Self-review

**Spec coverage.** Each acceptance bullet from roadmap §4 Slice 5 maps to a task:

| Acceptance | Covered by |
|---|---|
| After create LoRA, vector row appears | Task 6 (service test) + Task 7 (API test) |
| After update LoRA, vector row updates in place | Task 6 (`test_update_re_embeds_in_place`) |
| After delete LoRA, vector row gone | Task 6 (`test_delete_removes_row_and_vector_atomically`) + Task 7 (`test_delete_lora_removes_vector_too`) |
| `reindex-all` recalculates all LoRA | Task 8 (`test_run_reindex_indexes_every_lora`) |
| With fake embedder, tests don't download bge-m3 | Task 3 (autouse `_fake_embedder` fixture) |
| Indexer error: LoRA must not look "indexed" | Task 6 (rollback tests) + Task 7 (500 + no orphan row) + `is_indexed=false` if a manually-corrupted state ever arises |
| Frontend minimal status | Task 10 (Indexed badge) |

**Boundary respected.** No retriever endpoint, no generate-prompt UI, no semantic search exposed to the user, no alternate embedding model behind a flag. Those land in Slice 6 / post-MVP per roadmap §4 Slice 5 boundary.

**Handoff.** After Slice 5, Slice 6 inherits: `vec_loras`/`lora_vec_map` populated for every LoRA, `library_service.list_loras` returning `is_indexed`, `embedder.embed` as the canonical embedding entrypoint, and `library_service.reindex_one` if Slice 6 ever needs to retry indexing on a single row.

---

## Execution

Plan complete and saved to `docs/superpowers/plans/2026-04-26-slice-5-embedder-indexer.md`. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task with two-stage review between tasks.
2. **Inline Execution** — run tasks in this session via `superpowers:executing-plans`, batch with checkpoints.

Which approach?
