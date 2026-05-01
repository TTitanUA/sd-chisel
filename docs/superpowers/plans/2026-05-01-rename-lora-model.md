# Rename LoRA / Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow renaming the `name` (primary key) of a LoRA or a Model in place, preserving FK references in `lora_vec_map`, `session_pinned_loras`, and `sessions.model_name`. The LoRA embedding is not recomputed.

**Architecture:** Two new `POST /{name}/rename` endpoints (one per resource). Each opens a single transaction with `PRAGMA defer_foreign_keys = ON`, updates the parent row, then updates child FK columns. UI: inline `Rename…` block under the locked Name input in the form, separate from `Save`.

**Tech Stack:** FastAPI, Pydantic v2, SQLite, sqlite-vec, React 18, TanStack Query, react-router-dom v6, Vitest, pytest.

---

## File Structure

**Backend — modified:**
- `backend/app/models/library.py` — add `RenameRequest`.
- `backend/app/storage/library_repo.py` — add `rename_lora`, `rename_model`.
- `backend/app/services/library_service.py` — add `rename_lora` wrapper.
- `backend/app/api/library.py` — add two endpoints + register `RenameRequest` import.
- `backend/tests/test_library_repo.py` — repo tests.
- `backend/tests/test_library_service.py` — service test (no embedder call).
- `backend/tests/test_library_api.py` — API tests.

**Frontend — modified:**
- `frontend/src/api/library.ts` — `renameLora`, `renameModel`.
- `frontend/src/components/organisms/LoraForm.tsx` — inline rename block + `onRename` props.
- `frontend/src/components/organisms/ModelForm.tsx` — inline rename block + `onRename` props.
- `frontend/src/components/organisms/libraryForm.module.css` — small styles for the inline block.
- `frontend/src/routes/library/loras.tsx` — rename mutation + handler.
- `frontend/src/routes/library/models.tsx` — rename mutation + handler.
- `frontend/src/routes/library/libraryRoutes.test.tsx` — UI test for the rename flow.

---

## Backend

### Task 1: Add `RenameRequest` Pydantic model

**Files:**
- Modify: `backend/app/models/library.py` (append at end)

- [ ] **Step 1: Add the model**

Append at the end of `backend/app/models/library.py`:

```python
class RenameRequest(StrictModel):
    new_name: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[a-zA-Z0-9_.-]+$",
    )
```

- [ ] **Step 2: Verify import works**

Run: `cd backend && python -c "from app.models.library import RenameRequest; RenameRequest(new_name='ok_v2')"`
Expected: no output (success). A bad slug should raise:
`python -c "from app.models.library import RenameRequest; RenameRequest(new_name='bad name')"` — raises ValidationError.

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/library.py
git commit -m "feat(library): add RenameRequest pydantic model"
```

---

### Task 2: Implement `library_repo.rename_lora`

**Files:**
- Modify: `backend/app/storage/library_repo.py`
- Test: `backend/tests/test_library_repo.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_library_repo.py`:

```python
def test_rename_lora_updates_pk_and_child_fks(conn):
    library_repo.create_lora(
        conn, name="old_slug", display_name="Old", description="d",
        tags=[], trigger_words=[], family_id="sdxl",
    )
    conn.execute("INSERT INTO lora_vec_map(lora_name, rowid) VALUES (?, ?)",
                 ("old_slug", 1))
    # session_pinned_loras needs a real session row to satisfy FK
    conn.execute(
        "INSERT INTO projects(id, name, created_at, updated_at) "
        "VALUES ('p1', 'P', 1, 1)",
    )
    conn.execute(
        "INSERT INTO sessions(id, project_id, created_at, updated_at) "
        "VALUES ('s1', 'p1', 1, 1)",
    )
    conn.execute(
        "INSERT INTO session_pinned_loras(session_id, lora_name, weight_override) "
        "VALUES ('s1', 'old_slug', 0.7)",
    )

    out = library_repo.rename_lora(conn, "old_slug", "new_slug")

    assert out is not None
    assert out["name"] == "new_slug"
    assert library_repo.get_lora(conn, "old_slug") is None
    assert library_repo.get_lora(conn, "new_slug") is not None

    vec_rows = list(conn.execute(
        "SELECT lora_name FROM lora_vec_map WHERE lora_name = ?", ("new_slug",),
    ))
    assert len(vec_rows) == 1
    assert list(conn.execute(
        "SELECT lora_name FROM lora_vec_map WHERE lora_name = ?", ("old_slug",),
    )) == []

    pin_rows = list(conn.execute(
        "SELECT lora_name FROM session_pinned_loras WHERE lora_name = ?",
        ("new_slug",),
    ))
    assert len(pin_rows) == 1


def test_rename_lora_noop_when_same_name(conn):
    library_repo.create_lora(
        conn, name="same", display_name="S", description="d",
        tags=[], trigger_words=[], family_id="sdxl",
    )
    out = library_repo.rename_lora(conn, "same", "same")
    assert out is not None
    assert out["name"] == "same"


def test_rename_lora_returns_none_when_missing(conn):
    assert library_repo.rename_lora(conn, "ghost", "still_ghost") is None


def test_rename_lora_collision_raises(conn):
    library_repo.create_lora(
        conn, name="a", display_name="A", description="d",
        tags=[], trigger_words=[], family_id="sdxl",
    )
    library_repo.create_lora(
        conn, name="b", display_name="B", description="d",
        tags=[], trigger_words=[], family_id="sdxl",
    )
    with pytest.raises(sqlite3.IntegrityError):
        library_repo.rename_lora(conn, "a", "b")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_library_repo.py -k rename_lora -v`
Expected: FAIL — `rename_lora` is not defined.

- [ ] **Step 3: Implement `rename_lora`**

Append to `backend/app/storage/library_repo.py` (before the `def list_all_lora_names` line so it sits with the other lora helpers, but anywhere in the loras section is fine):

```python
def rename_lora(
    conn: sqlite3.Connection, old_name: str, new_name: str,
) -> dict[str, Any] | None:
    """Rename a LoRA's primary key and update FK child columns.

    Uses ``PRAGMA defer_foreign_keys`` so the parent UPDATE can land before
    children are rewritten — both must be consistent at COMMIT.
    """
    if old_name == new_name:
        return get_lora(conn, old_name)
    conn.execute("PRAGMA defer_foreign_keys = ON")
    cur = conn.execute(
        "UPDATE loras SET name = ?, updated_at = ? WHERE name = ?",
        (new_name, _now(), old_name),
    )
    if cur.rowcount == 0:
        return None
    conn.execute(
        "UPDATE lora_vec_map SET lora_name = ? WHERE lora_name = ?",
        (new_name, old_name),
    )
    conn.execute(
        "UPDATE session_pinned_loras SET lora_name = ? WHERE lora_name = ?",
        (new_name, old_name),
    )
    return get_lora(conn, new_name)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_library_repo.py -k rename_lora -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/storage/library_repo.py backend/tests/test_library_repo.py
git commit -m "feat(library/repo): rename_lora updates PK and child FKs"
```

---

### Task 3: Implement `library_repo.rename_model`

**Files:**
- Modify: `backend/app/storage/library_repo.py`
- Test: `backend/tests/test_library_repo.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_library_repo.py`:

```python
def test_rename_model_updates_pk_and_session_fk(conn):
    library_repo.create_model(
        conn, name="old_ckpt", display_name="Old", family_id="sdxl",
    )
    conn.execute(
        "INSERT INTO projects(id, name, created_at, updated_at) "
        "VALUES ('p1', 'P', 1, 1)",
    )
    conn.execute(
        "INSERT INTO sessions(id, project_id, model_name, created_at, updated_at) "
        "VALUES ('s1', 'p1', 'old_ckpt', 1, 1)",
    )

    out = library_repo.rename_model(conn, "old_ckpt", "new_ckpt")

    assert out is not None
    assert out["name"] == "new_ckpt"
    assert library_repo.get_model(conn, "old_ckpt") is None

    sessions = list(conn.execute(
        "SELECT model_name FROM sessions WHERE id = 's1'",
    ))
    assert sessions[0]["model_name"] == "new_ckpt"


def test_rename_model_noop_when_same_name(conn):
    library_repo.create_model(
        conn, name="same_ckpt", display_name="S", family_id="sdxl",
    )
    out = library_repo.rename_model(conn, "same_ckpt", "same_ckpt")
    assert out is not None
    assert out["name"] == "same_ckpt"


def test_rename_model_returns_none_when_missing(conn):
    assert library_repo.rename_model(conn, "ghost", "still_ghost") is None


def test_rename_model_collision_raises(conn):
    library_repo.create_model(conn, name="a_ckpt", display_name="A", family_id="sdxl")
    library_repo.create_model(conn, name="b_ckpt", display_name="B", family_id="sdxl")
    with pytest.raises(sqlite3.IntegrityError):
        library_repo.rename_model(conn, "a_ckpt", "b_ckpt")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_library_repo.py -k rename_model -v`
Expected: FAIL — `rename_model` is not defined.

- [ ] **Step 3: Implement `rename_model`**

Append to `backend/app/storage/library_repo.py` in the models section (after `delete_model`):

```python
def rename_model(
    conn: sqlite3.Connection, old_name: str, new_name: str,
) -> dict[str, Any] | None:
    """Rename a Model's primary key and update sessions.model_name.

    Uses ``PRAGMA defer_foreign_keys`` so the parent UPDATE can land before
    sessions are rewritten — both must be consistent at COMMIT.
    """
    if old_name == new_name:
        return get_model(conn, old_name)
    conn.execute("PRAGMA defer_foreign_keys = ON")
    cur = conn.execute(
        "UPDATE models SET name = ?, updated_at = ? WHERE name = ?",
        (new_name, _now(), old_name),
    )
    if cur.rowcount == 0:
        return None
    conn.execute(
        "UPDATE sessions SET model_name = ? WHERE model_name = ?",
        (new_name, old_name),
    )
    return get_model(conn, new_name)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_library_repo.py -k rename_model -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/storage/library_repo.py backend/tests/test_library_repo.py
git commit -m "feat(library/repo): rename_model updates PK and sessions FK"
```

---

### Task 4: Implement `library_service.rename_lora`

**Files:**
- Modify: `backend/app/services/library_service.py`
- Test: `backend/tests/test_library_service.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_library_service.py`:

```python
def test_rename_lora_succeeds_and_does_not_call_embedder(conn, monkeypatch):
    library_service.create_lora(conn, name="old_slug", **CREATE_KW)

    calls = []
    real_embed = embedder.embed
    def spy(text):
        calls.append(text)
        return real_embed(text)
    monkeypatch.setattr(embedder, "embed", spy)

    out = library_service.rename_lora(conn, "old_slug", "new_slug")
    assert out is not None
    assert out["name"] == "new_slug"
    assert out["is_indexed"] is True
    assert calls == [], "rename must not recompute the embedding"

    # Vector mapping followed the rename
    rows = conn.execute(
        "SELECT rowid FROM lora_vec_map WHERE lora_name = ?", ("new_slug",),
    ).fetchall()
    assert len(rows) == 1


def test_rename_lora_returns_none_when_missing(conn):
    assert library_service.rename_lora(conn, "ghost", "still_ghost") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_library_service.py -k rename_lora -v`
Expected: FAIL — `library_service.rename_lora` is not defined.

- [ ] **Step 3: Implement the service wrapper**

Append to `backend/app/services/library_service.py`:

```python
def rename_lora(
    conn: sqlite3.Connection, old_name: str, new_name: str,
) -> dict[str, Any] | None:
    """Rename a LoRA's primary key. The embedding is preserved (the text
    fed to the embedder does not contain ``name``)."""
    conn.execute("BEGIN")
    try:
        renamed = library_repo.rename_lora(conn, old_name, new_name)
        conn.execute("COMMIT")
    except Exception:
        _rollback(conn)
        raise
    return _hydrated_with_index_status(conn, renamed)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_library_service.py -k rename_lora -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/library_service.py backend/tests/test_library_service.py
git commit -m "feat(library/service): rename_lora wrapper preserves embedding"
```

---

### Task 5: Add `POST /api/library/loras/{name}/rename`

**Files:**
- Modify: `backend/app/api/library.py`
- Test: `backend/tests/test_library_api.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_library_api.py` (use the existing `_make_lora_payload` helper already defined in the file):

```python
def test_rename_lora_http_success(client, conn):
    client.post("/api/library/loras", json=_make_lora_payload())
    resp = client.post(
        "/api/library/loras/cinelight/rename",
        json={"new_name": "cinelight_v2"},
    )
    assert resp.status_code == 200, resp.json()
    assert resp.json()["name"] == "cinelight_v2"
    assert resp.json()["is_indexed"] is True
    assert client.get("/api/library/loras/cinelight").status_code == 404
    assert client.get("/api/library/loras/cinelight_v2").status_code == 200
    assert conn.execute(
        "SELECT COUNT(*) FROM lora_vec_map WHERE lora_name = 'cinelight_v2'",
    ).fetchone()[0] == 1


def test_rename_lora_http_not_found(client):
    resp = client.post(
        "/api/library/loras/ghost/rename",
        json={"new_name": "ghost2"},
    )
    assert resp.status_code == 404


def test_rename_lora_http_conflict(client):
    client.post("/api/library/loras", json=_make_lora_payload(name="a_lora"))
    client.post("/api/library/loras", json=_make_lora_payload(name="b_lora"))
    resp = client.post(
        "/api/library/loras/a_lora/rename",
        json={"new_name": "b_lora"},
    )
    assert resp.status_code == 409


def test_rename_lora_http_bad_slug(client):
    client.post("/api/library/loras", json=_make_lora_payload())
    resp = client.post(
        "/api/library/loras/cinelight/rename",
        json={"new_name": "bad name with spaces"},
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_library_api.py -k rename_lora_http -v`
Expected: FAIL — endpoint not registered.

- [ ] **Step 3: Wire endpoint and import**

In `backend/app/api/library.py`, add `RenameRequest` to the imports from `app.models.library`:

```python
from app.models.library import (
    AssistFieldsSnapshot,
    AssistRequest,
    CivitaiImportResult,
    FamilyCreate,
    FamilyOut,
    FamilyUpdate,
    LoraAssistFieldsSnapshot,
    LoraAssistRequest,
    LoraCreate,
    LoraOut,
    LoraUpdate,
    ModelCreate,
    ModelOut,
    ModelUpdate,
    RenameRequest,
)
```

Add the endpoint just before `@router.delete("/loras/{name}", ...)`:

```python
@router.post("/loras/{name}/rename", response_model=LoraOut)
def rename_lora(name: str, body: RenameRequest, conn: Conn):
    try:
        row = library_service.rename_lora(conn, name, body.new_name)
    except sqlite3.IntegrityError as exc:
        raise _conflict(exc) from exc
    if row is None:
        raise _not_found("lora", name)
    return row
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_library_api.py -k rename_lora_http -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/library.py backend/tests/test_library_api.py
git commit -m "feat(api): POST /loras/{name}/rename"
```

---

### Task 6: Add `POST /api/library/models/{name}/rename`

**Files:**
- Modify: `backend/app/api/library.py`
- Test: `backend/tests/test_library_api.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_library_api.py`:

```python
def test_rename_model_http_success(client, conn):
    client.post("/api/library/models", json={
        "name": "old_ckpt",
        "display_name": "Old",
        "family_id": "sdxl",
    })
    # Create a session that pins this model to verify FK update.
    conn.execute(
        "INSERT INTO projects(id, name, created_at, updated_at) "
        "VALUES ('p1', 'P', 1, 1)",
    )
    conn.execute(
        "INSERT INTO sessions(id, project_id, model_name, created_at, updated_at) "
        "VALUES ('s1', 'p1', 'old_ckpt', 1, 1)",
    )

    resp = client.post(
        "/api/library/models/old_ckpt/rename",
        json={"new_name": "new_ckpt"},
    )
    assert resp.status_code == 200, resp.json()
    assert resp.json()["name"] == "new_ckpt"
    assert client.get("/api/library/models/old_ckpt").status_code == 404
    assert conn.execute(
        "SELECT model_name FROM sessions WHERE id = 's1'",
    ).fetchone()["model_name"] == "new_ckpt"


def test_rename_model_http_not_found(client):
    resp = client.post(
        "/api/library/models/ghost/rename",
        json={"new_name": "ghost2"},
    )
    assert resp.status_code == 404


def test_rename_model_http_conflict(client):
    client.post("/api/library/models", json={
        "name": "a_ckpt", "display_name": "A", "family_id": "sdxl",
    })
    client.post("/api/library/models", json={
        "name": "b_ckpt", "display_name": "B", "family_id": "sdxl",
    })
    resp = client.post(
        "/api/library/models/a_ckpt/rename",
        json={"new_name": "b_ckpt"},
    )
    assert resp.status_code == 409


def test_rename_model_http_bad_slug(client):
    client.post("/api/library/models", json={
        "name": "ckpt_x", "display_name": "X", "family_id": "sdxl",
    })
    resp = client.post(
        "/api/library/models/ckpt_x/rename",
        json={"new_name": "bad name"},
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_library_api.py -k rename_model_http -v`
Expected: FAIL — endpoint not registered.

- [ ] **Step 3: Wire endpoint**

In `backend/app/api/library.py`, add the endpoint just before `@router.delete("/models/{name}", ...)`:

```python
@router.post("/models/{name}/rename", response_model=ModelOut)
def rename_model(name: str, body: RenameRequest, conn: Conn):
    try:
        row = library_repo.rename_model(conn, name, body.new_name)
    except sqlite3.IntegrityError as exc:
        raise _conflict(exc) from exc
    if row is None:
        raise _not_found("model", name)
    return row
```

`library_repo` is already imported (`from app.storage import library_repo, settings_repo`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_library_api.py -k rename_model_http -v`
Expected: 4 PASS.

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && pytest -q`
Expected: ALL PASS, no regressions.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/library.py backend/tests/test_library_api.py
git commit -m "feat(api): POST /models/{name}/rename"
```

---

## Frontend

### Task 7: Add `renameLora` and `renameModel` to API client

**Files:**
- Modify: `frontend/src/api/library.ts`

- [ ] **Step 1: Add the methods**

In `frontend/src/api/library.ts`, inside the `libraryApi = { ... }` object, add `renameModel` after `updateModel` and `renameLora` after `updateLora`:

```ts
  renameModel: (name: string, new_name: string) =>
    apiFetch<Model>(`/api/library/models/${encodeURIComponent(name)}/rename`, {
      method: "POST",
      body: JSON.stringify({ new_name }),
    }),
```

```ts
  renameLora: (name: string, new_name: string) =>
    apiFetch<Lora>(`/api/library/loras/${encodeURIComponent(name)}/rename`, {
      method: "POST",
      body: JSON.stringify({ new_name }),
    }),
```

- [ ] **Step 2: Verify typecheck**

Run: `cd frontend && pnpm exec tsc -b --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/library.ts
git commit -m "feat(api): rename methods for loras and models"
```

---

### Task 8: Add inline rename block to `LoraForm`

**Files:**
- Modify: `frontend/src/components/organisms/LoraForm.tsx`
- Modify: `frontend/src/components/organisms/libraryForm.module.css`

- [ ] **Step 1: Add CSS rules for the inline block**

Append at the end of `frontend/src/components/organisms/libraryForm.module.css`:

```css
.renameRow {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  margin-top: 6px;
}

.renameRow > :first-child {
  flex: 1;
  min-width: 0;
}

.renameToggle {
  align-self: flex-start;
  background: transparent;
  border: 0;
  padding: 0;
  margin-top: 4px;
  font-size: 12px;
  color: var(--accent);
  cursor: pointer;
  font-family: var(--font-ui);
}

.renameToggle:hover {
  text-decoration: underline;
}

.renameError {
  color: var(--danger);
  font-size: 11px;
  margin-top: 6px;
}
```

- [ ] **Step 2: Update the `LoraForm` props and add inline block**

In `frontend/src/components/organisms/LoraForm.tsx`:

a) Extend the prop type (the `function LoraForm` signature):

```tsx
export function LoraForm({
  lora,
  families,
  onCancel,
  onSubmit,
  isSaving,
  onRename,
  isRenaming,
  renameError,
}: {
  lora?: Lora;
  families: Family[];
  onCancel: () => void;
  onSubmit: (body: LoraCreate | LoraUpdate) => void;
  isSaving: boolean;
  onRename?: (newName: string) => void;
  isRenaming?: boolean;
  renameError?: string | null;
}) {
```

b) Add local state at the top of the function body, alongside the existing `useState` calls:

```tsx
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameValue, setRenameValue] = useState(lora?.name ?? "");
```

c) Add the slug regex constant near the top of the file (after imports):

```tsx
const SLUG_RE = /^[a-zA-Z0-9_.-]+$/;
```

d) Replace the `Name` `TextInput` block (currently lines ~242–248) with the input followed by the rename affordance:

```tsx
          <div>
            <TextInput
              label="Name"
              hint={isEdit ? "filename — locked, used as primary key" : "filename without .safetensors"}
              value={name}
              onChange={(e) => setName(e.currentTarget.value)}
              disabled={isEdit}
            />
            {isEdit && onRename && !renameOpen && (
              <button
                type="button"
                className={libForm.renameToggle}
                onClick={() => {
                  setRenameValue(lora?.name ?? "");
                  setRenameOpen(true);
                }}
              >
                Rename…
              </button>
            )}
            {isEdit && onRename && renameOpen && (
              <>
                <div className={libForm.renameRow}>
                  <TextInput
                    label="New filename slug"
                    value={renameValue}
                    onChange={(e) => setRenameValue(e.currentTarget.value)}
                    placeholder={lora?.name ?? ""}
                    autoFocus
                  />
                  <Button
                    type="button"
                    variant="primary"
                    size="sm"
                    disabled={
                      isRenaming ||
                      renameValue.trim() === "" ||
                      renameValue.trim() === lora?.name ||
                      !SLUG_RE.test(renameValue.trim())
                    }
                    onClick={() => onRename(renameValue.trim())}
                  >
                    {isRenaming ? "Renaming…" : "Save"}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setRenameOpen(false)}
                    disabled={isRenaming}
                  >
                    Cancel
                  </Button>
                </div>
                {renameError && (
                  <div role="alert" className={libForm.renameError}>
                    {renameError}
                  </div>
                )}
              </>
            )}
          </div>
```

- [ ] **Step 3: Verify typecheck and existing form tests still pass**

Run:
- `cd frontend && pnpm exec tsc -b --noEmit`
- `cd frontend && pnpm test -- libraryRoutes`

Expected: no type errors; existing tests pass (rename UI is opt-in via prop).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/organisms/LoraForm.tsx frontend/src/components/organisms/libraryForm.module.css
git commit -m "feat(LoraForm): inline Rename… block under Name input"
```

---

### Task 9: Add inline rename block to `ModelForm`

**Files:**
- Modify: `frontend/src/components/organisms/ModelForm.tsx`

- [ ] **Step 1: Update props and add the same inline block**

In `frontend/src/components/organisms/ModelForm.tsx`:

a) Extend the prop type:

```tsx
export function ModelForm({
  model,
  families,
  onCancel,
  onSubmit,
  isSaving,
  onRename,
  isRenaming,
  renameError,
}: {
  model?: Model;
  families: Family[];
  onCancel: () => void;
  onSubmit: (body: ModelCreate | ModelUpdate) => void;
  isSaving: boolean;
  onRename?: (newName: string) => void;
  isRenaming?: boolean;
  renameError?: string | null;
}) {
```

b) Add local state alongside the other `useState` calls:

```tsx
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameValue, setRenameValue] = useState(model?.name ?? "");
```

c) Add the slug regex near the imports:

```tsx
const SLUG_RE = /^[a-zA-Z0-9_.-]+$/;
```

d) Replace the `Name` `TextInput` block (currently lines ~86–92) with:

```tsx
          <div>
            <TextInput
              label="Name"
              hint={isEdit ? "filename — locked, used as primary key" : "filename without .safetensors"}
              value={name}
              onChange={(e) => setName(e.currentTarget.value)}
              disabled={isEdit}
            />
            {isEdit && onRename && !renameOpen && (
              <button
                type="button"
                className={libForm.renameToggle}
                onClick={() => {
                  setRenameValue(model?.name ?? "");
                  setRenameOpen(true);
                }}
              >
                Rename…
              </button>
            )}
            {isEdit && onRename && renameOpen && (
              <>
                <div className={libForm.renameRow}>
                  <TextInput
                    label="New filename slug"
                    value={renameValue}
                    onChange={(e) => setRenameValue(e.currentTarget.value)}
                    placeholder={model?.name ?? ""}
                    autoFocus
                  />
                  <Button
                    type="button"
                    variant="primary"
                    size="sm"
                    disabled={
                      isRenaming ||
                      renameValue.trim() === "" ||
                      renameValue.trim() === model?.name ||
                      !SLUG_RE.test(renameValue.trim())
                    }
                    onClick={() => onRename(renameValue.trim())}
                  >
                    {isRenaming ? "Renaming…" : "Save"}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setRenameOpen(false)}
                    disabled={isRenaming}
                  >
                    Cancel
                  </Button>
                </div>
                {renameError && (
                  <div role="alert" className={libForm.renameError}>
                    {renameError}
                  </div>
                )}
              </>
            )}
          </div>
```

- [ ] **Step 2: Verify typecheck**

Run: `cd frontend && pnpm exec tsc -b --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/organisms/ModelForm.tsx
git commit -m "feat(ModelForm): inline Rename… block under Name input"
```

---

### Task 10: Wire rename mutation in the LoRA route

**Files:**
- Modify: `frontend/src/routes/library/loras.tsx`

- [ ] **Step 1: Add the rename mutation and handler**

In `frontend/src/routes/library/loras.tsx`:

a) Add a new mutation alongside `create`, `update`, `remove`:

```tsx
  const rename = useMutation({
    mutationFn: ({ name, new_name }: { name: string; new_name: string }) =>
      libraryApi.renameLora(name, new_name),
    onSuccess: invalidate,
  });
```

b) Add the handler near `submit`:

```tsx
  function handleRename(newName: string) {
    if (!selected) return;
    rename.mutate(
      { name: selected.name, new_name: newName },
      {
        onSuccess: (lora: Lora) =>
          navigate(`${BASE}/${encodeURIComponent(lora.name)}/edit`, { replace: true }),
      },
    );
  }
```

c) Update the `error` aggregation to include rename:

```tsx
  const error = create.error ?? update.error ?? remove.error ?? rename.error ?? loras.error ?? families.error;
```

d) Pass new props to the `<LoraForm>` in the edit branch:

```tsx
        <LoraForm
          lora={selected}
          families={familyRows}
          onCancel={cancelForm}
          onSubmit={submit}
          isSaving={update.isPending}
          onRename={handleRename}
          isRenaming={rename.isPending}
          renameError={rename.error ? String(rename.error) : null}
        />
```

- [ ] **Step 2: Verify typecheck**

Run: `cd frontend && pnpm exec tsc -b --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/library/loras.tsx
git commit -m "feat(routes/loras): wire rename mutation and URL replace"
```

---

### Task 11: Wire rename mutation in the Model route

**Files:**
- Modify: `frontend/src/routes/library/models.tsx`

- [ ] **Step 1: Add the rename mutation and handler**

In `frontend/src/routes/library/models.tsx`:

a) Add a new mutation alongside `create`, `update`, `remove`:

```tsx
  const rename = useMutation({
    mutationFn: ({ name, new_name }: { name: string; new_name: string }) =>
      libraryApi.renameModel(name, new_name),
    onSuccess: invalidate,
  });
```

b) Add the handler near `submit`:

```tsx
  function handleRename(newName: string) {
    if (!selected) return;
    rename.mutate(
      { name: selected.name, new_name: newName },
      {
        onSuccess: (model: Model) =>
          navigate(`${BASE}/${encodeURIComponent(model.name)}/edit`, { replace: true }),
      },
    );
  }
```

c) Update the `error` aggregation to include rename:

```tsx
  const error = create.error ?? update.error ?? remove.error ?? rename.error ?? models.error ?? families.error;
```

d) Pass new props to the `<ModelForm>` in the edit branch:

```tsx
        <ModelForm
          model={selected}
          families={familyRows}
          onCancel={cancelForm}
          onSubmit={submit}
          isSaving={update.isPending}
          onRename={handleRename}
          isRenaming={rename.isPending}
          renameError={rename.error ? String(rename.error) : null}
        />
```

- [ ] **Step 2: Verify typecheck**

Run: `cd frontend && pnpm exec tsc -b --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/library/models.tsx
git commit -m "feat(routes/models): wire rename mutation and URL replace"
```

---

### Task 12: Frontend integration test for rename flow

**Files:**
- Modify: `frontend/src/routes/library/libraryRoutes.test.tsx`

- [ ] **Step 1: Write the test**

Append to `frontend/src/routes/library/libraryRoutes.test.tsx`:

```tsx
  it("renames a LoRA from the edit page and navigates to the new URL", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.includes("/families")) {
        return json([{ id: "sdxl", display_name: "SDXL", prompt_guide: "G", prompt_i2i: "", prompt_t2i: "", created_at: 1, updated_at: 1 }]);
      }
      if (url.includes("/rename") && init?.method === "POST") {
        return json({
          name: "cinematic_light_v2",
          display_name: "Cinematic Light",
          description: "Rim light",
          tags: ["light"],
          trigger_words: ["cinematic light"],
          family_id: "sdxl",
          recommended_weight: 0.75,
          author: null, version: null, source_url: null,
          created_at: 1, updated_at: 2, is_indexed: true,
        });
      }
      // GET /loras
      return json([
        {
          name: "cinematic_light",
          display_name: "Cinematic Light",
          description: "Rim light",
          tags: ["light"],
          trigger_words: ["cinematic light"],
          family_id: "sdxl",
          recommended_weight: 0.75,
          author: null, version: null, source_url: null,
          created_at: 1, updated_at: 1, is_indexed: true,
        },
      ]);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderRoute(<LorasRoute />, "/library/loras/cinematic_light/edit");

    const renameToggle = await screen.findByRole("button", { name: /rename…/i });
    fireEvent.click(renameToggle);

    const slugInput = await screen.findByLabelText(/new filename slug/i);
    fireEvent.change(slugInput, { target: { value: "cinematic_light_v2" } });

    const saveBtn = screen.getByRole("button", { name: /^save$/i });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      const renameCalls = fetchMock.mock.calls.filter(
        ([url, init]) =>
          typeof url === "string" &&
          url.includes("/api/library/loras/cinematic_light/rename") &&
          (init as RequestInit | undefined)?.method === "POST",
      );
      expect(renameCalls.length).toBe(1);
      const body = JSON.parse((renameCalls[0][1] as RequestInit).body as string);
      expect(body).toEqual({ new_name: "cinematic_light_v2" });
    });
  });
```

- [ ] **Step 2: Run frontend tests**

Run: `cd frontend && pnpm test -- libraryRoutes`
Expected: all tests pass, including the new one.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/library/libraryRoutes.test.tsx
git commit -m "test(routes/loras): cover rename flow"
```

---

## Final Verification

- [ ] **Step 1: Backend full suite**

Run: `cd backend && pytest -q`
Expected: ALL PASS.

- [ ] **Step 2: Frontend typecheck + tests**

Run:
- `cd frontend && pnpm exec tsc -b --noEmit`
- `cd frontend && pnpm test`

Expected: typecheck clean; all tests pass.

- [ ] **Step 3: Manual smoke test**

Start the backend (`cd backend && uvicorn app.main:app --reload`) and the frontend (`cd frontend && pnpm dev`). In the browser:

1. Open `/library/loras`, pick an existing LoRA, hit **Edit**.
2. Click **Rename…**, enter a new slug, click **Save**.
3. Confirm the URL updates to the new slug and the form loads the renamed LoRA.
4. Repeat at `/library/models`.
5. Try a duplicate name → expect inline error.
