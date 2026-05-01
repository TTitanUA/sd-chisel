# Rename LoRA / Model — design

Date: 2026-05-01
Status: approved
Scope: backend (FastAPI + SQLite) + frontend (React)

## Problem

`name` is the primary key for the `loras` and `models` tables. Users can
rename the underlying `.safetensors` file on disk; today the library has no
way to reflect that — the only path is delete + re-create, which loses
session pins, the vector embedding, and any references.

## Goal

Allow renaming a LoRA or a Model in place, preserving:

- the row itself (and `created_at`),
- `lora_vec_map` mapping (and the underlying `vec_loras` row),
- `session_pinned_loras` rows,
- `sessions.model_name` references,
- LoRA embedding vector (no recomputation needed — see below).

Out of scope:

- Renaming `families.id`. The user did not ask for it.
- Validating that a file with the new name exists on disk. The library is
  metadata-only.

## Approach

A dedicated rename endpoint per resource. Renaming the PK is a special
operation — making it explicit (separate URL, separate UI affordance)
prevents accidentally re-keying a row when editing other fields.

### Why not `ON UPDATE CASCADE`

Adding `ON UPDATE CASCADE` to the existing FKs would require dropping and
recreating `lora_vec_map`, `session_pinned_loras`, and `sessions` (SQLite
has no `ALTER TABLE ... DROP CONSTRAINT`). Heavy and irreversible.

`PRAGMA defer_foreign_keys = ON` (transaction-scoped) achieves the same
result at write time: the parent UPDATE is allowed to leave child rows
temporarily orphaned within the transaction, as long as everything is
consistent at COMMIT.

### Why no embedding recomputation for LoRA

`embedder.build_embedding_text` uses `description | tags | trigger_words`
only — `name` is not part of the text fed to the embedder. Renaming a LoRA
does not change its embedding. The `vec_loras` row is referenced by `rowid`
through `lora_vec_map`; we only update `lora_vec_map.lora_name` (the FK),
not the vector itself.

## Backend

### Endpoints

```
POST /api/library/loras/{name}/rename       body: {"new_name": "..."}
POST /api/library/models/{name}/rename      body: {"new_name": "..."}
```

Response: `LoraOut` / `ModelOut` at the new name.

Status codes:

- `200` — success (also when `new_name == name`, no-op).
- `400` — `new_name` fails slug validation.
- `404` — `name` not found.
- `409` — `new_name` is already taken.

Pydantic request model (`backend/app/models/library.py`):

```python
class RenameRequest(StrictModel):
    new_name: str = Field(min_length=1, max_length=120,
                          pattern=r"^[a-zA-Z0-9_.-]+$")
```

The pattern matches the existing `LoraCreate.name` / `ModelCreate.name`
validators. Pydantic returns `422` for malformed input by default; the
existing endpoints rely on that, we keep the same behavior (so "400" above
is really "422 from FastAPI validation"). No custom handling needed.

### Repo layer (`backend/app/storage/library_repo.py`)

Two new functions, same shape:

```python
def rename_lora(conn, old_name: str, new_name: str) -> dict | None:
    if old_name == new_name:
        return get_lora(conn, old_name)
    conn.execute("PRAGMA defer_foreign_keys = ON")
    cur = conn.execute(
        "UPDATE loras SET name = ?, updated_at = ? WHERE name = ?",
        (new_name, _now(), old_name),
    )
    if cur.rowcount == 0:
        return None
    conn.execute("UPDATE lora_vec_map SET lora_name = ? WHERE lora_name = ?",
                 (new_name, old_name))
    conn.execute("UPDATE session_pinned_loras SET lora_name = ? "
                 "WHERE lora_name = ?", (new_name, old_name))
    return get_lora(conn, new_name)

def rename_model(conn, old_name: str, new_name: str) -> dict | None:
    # Same shape. FKs to update: sessions.model_name only.
```

`sqlite3.IntegrityError` (PK collision) propagates up — the API layer
catches it via the existing `_conflict` helper and returns 409.

`PRAGMA defer_foreign_keys` is transaction-scoped and resets at COMMIT, so
no cleanup is needed.

### Service layer (`backend/app/services/library_service.py`)

Add a thin `rename_lora` wrapper that opens the same `BEGIN ... COMMIT`
transaction the existing `update_lora` uses, then delegates to
`library_repo.rename_lora`. No embedder call. Keeping it in the service
layer matches the existing rule "all LoRA writes go through
library_service".

For models there is no service layer — the API calls `library_repo`
directly, same as `update_model` does today.

### API layer (`backend/app/api/library.py`)

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

## Frontend

### API client (`frontend/src/api/library.ts`)

```ts
renameLora: (name: string, new_name: string) =>
  apiFetch<Lora>(
    `/api/library/loras/${encodeURIComponent(name)}/rename`,
    { method: "POST", body: JSON.stringify({ new_name }) },
  ),
renameModel: (name: string, new_name: string) =>
  apiFetch<Model>(
    `/api/library/models/${encodeURIComponent(name)}/rename`,
    { method: "POST", body: JSON.stringify({ new_name }) },
  ),
```

### Form components (`LoraForm.tsx`, `ModelForm.tsx`)

- The `Name` input stays `disabled={isEdit}` — unchanged.
- In edit mode, render a small `Rename…` button under the Name hint.
- Clicking it toggles an inline block with: a TextInput pre-filled with
  the current `name`, plus `Save` / `Cancel` buttons.
- Slug validation on the client mirrors the backend regex
  (`^[a-zA-Z0-9_.-]+$`); `Save` disabled when invalid, empty, or equal to
  current name.
- On `Save`, call the new `onRename(newName)` form prop. The form does
  **not** submit the rest of the form — rename is a separate operation.
- A small inline error (from `renameError` prop) renders next to the
  buttons on failure.

No new modal abstraction. The codebase uses inline UI + `window.confirm`
elsewhere; an inline block matches existing style.

New form props:

```ts
LoraForm:  { ..., onRename?: (newName: string) => void,
             isRenaming?: boolean, renameError?: string | null }
ModelForm: { ..., onRename?: (newName: string) => void,
             isRenaming?: boolean, renameError?: string | null }
```

`onRename` is undefined in create mode → the `Rename…` affordance is not
rendered.

### Routes (`routes/library/loras.tsx`, `routes/library/models.tsx`)

Add a `useMutation` for rename per resource:

```ts
const rename = useMutation({
  mutationFn: ({ name, new_name }: { name: string; new_name: string }) =>
    libraryApi.renameLora(name, new_name),
  onSuccess: invalidate,
});

function handleRename(newName: string) {
  if (!selected) return;
  rename.mutate(
    { name: selected.name, new_name: newName },
    {
      onSuccess: (lora) =>
        navigate(`${BASE}/${encodeURIComponent(lora.name)}/edit`,
                 { replace: true }),
    },
  );
}
```

Pass `onRename`, `isRenaming`, `renameError` to the form. `replace: true`
keeps the old URL out of browser history.

## Tests

Backend (`backend/tests/`):

- `test_library_repo.py` — `rename_lora` updates `loras`, `lora_vec_map`,
  `session_pinned_loras`; `rename_model` updates `sessions.model_name`;
  no-op when `old == new`; returns `None` when missing; raises
  `IntegrityError` on collision.
- `test_library_service.py` — `rename_lora` succeeds end-to-end without
  invoking the embedder (assert `embedder.embed` is not called).
- `test_library_api.py` — `POST /loras/{name}/rename` and
  `/models/{name}/rename` return 200 with the new payload, 404 for
  missing, 409 for collision, 422 for bad slug.

Frontend:

- Extend existing `LoraForm` test (and add a `ModelForm` test if missing)
  to cover: `Rename…` button visible only in edit mode; clicking it shows
  the inline block; `Save` disabled when input matches current name or is
  empty / fails the regex; calling `onRename` with the trimmed value.

## Migration / data

No schema migration. `PRAGMA defer_foreign_keys` is a session pragma, set
inside the rename transaction.
