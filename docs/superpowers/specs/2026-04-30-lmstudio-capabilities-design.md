# LMStudio Capabilities — Design Spec
_2026-04-30_

## Context

The current model management uses a manually-set `role` field (`vl / prompt / both`) to control which models appear in which dropdowns. This requires user configuration after every Refresh and gives no information about actual model capabilities (tool use, reasoning). The goal is to replace the role field with automatically-detected capabilities fetched from LMStudio's native REST API, with manual override per model.

Additionally, the two existing LM clients (`lm_client.py` for chat and a planned `lmstudio_client.py` for system ops) are merged into one. Settings store only the server root URL (`http://localhost:1234`), not the OpenAI-compat base URL.

---

## 1. Settings URL Change

**Before:** `lmstudio_base_url` stores `http://localhost:1234/v1`
**After:** `lmstudio_url` stores `http://localhost:1234` (server root)

- `settings_repo.py` normalization: strip trailing slash only, no `/v1` auto-append
- `001_init.sql`: rename column (DB is dropped and re-created, so edit in place)
- Frontend default URL button: `http://localhost:1234`
- Frontend placeholder: `http://localhost:1234`

---

## 2. Database Schema

Edit `001_init.sql` in place (DB will be dropped and re-initialized):

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

`role` column removed. `lmstudio_url` replaces `lmstudio_base_url` in the `settings` table (or equivalent storage).

---

## 3. Unified LMStudio Client

**File:** `backend/app/services/lmstudio_client.py` (replaces `lm_client.py`)

URL construction from `server_root = "http://localhost:1234"`:
- OpenAI-compat: `{server_root}/v1/chat/completions`, `{server_root}/v1/models`
- LMStudio system: `{server_root}/api/v1/models`, `{server_root}/api/v1/models/unload`

### Dataclass

```python
@dataclass
class LmsModel:
    name: str
    vision: bool
    tool_use: bool
    reasoning: bool
```

### System methods

**`list_models(server_root, headers) -> list[LmsModel]`**
- `GET {server_root}/api/v1/models`
- Filter: skip items where `type != "llm"` (excludes embeddings)
- Map capabilities:
  - `vision` ← `capabilities.vision`
  - `tool_use` ← `capabilities.trained_for_tool_use`
  - `reasoning` ← `bool(capabilities.reasoning.get("allowed_options"))`
- Model name ← `item["id"]`

**`unload_model(server_root, headers, instance_id: str) -> None`**
- `POST {server_root}/api/v1/models/unload` with `{"instance_id": instance_id}`

### Chat methods (migrated from `lm_client.py`)

- `chat_stream(server_root, headers, model, messages, ...) -> Iterator[str]`
- `chat_complete(server_root, headers, model, messages, ...) -> str`
- `analyze_image(server_root, headers, model, image_b64, ...) -> str`

All use `{server_root}/v1/chat/completions`.

`lm_client.py` is deleted after migration.

---

## 4. Backend Changes

### `settings_repo.py`

- `upsert_lm_models(conn, *, models: list[LmsModel])`:
  - On INSERT: set capabilities from API, `enabled=1`
  - On CONFLICT (existing model): update `last_seen`, `vision`, `tool_use`, `reasoning` — **do not touch `enabled`**
- `patch_lm_model(conn, name, *, enabled=None, vision=None, tool_use=None, reasoning=None)`: applies only provided fields
- URL helpers: use `lmstudio_url` (server root) everywhere, remove `/v1` suffix handling

### `models/settings.py`

```python
class LmModelOut(StrictModel):
    name: str
    vision: bool
    tool_use: bool
    reasoning: bool
    enabled: bool
    last_seen: int
```

Remove `Role` type and `role` field.

### `api/settings.py`

- Refresh calls `lmstudio_client.list_models()` instead of `lm_client.list_models()`
- PATCH body: `{ vision?: bool, tool_use?: bool, reasoning?: bool, enabled?: bool }`

### Validation functions

**`sessions.py` — `_validated_vl_model()`:**
```python
if row is None or not row["enabled"] or not row["vision"]:
    raise HTTPException(409, detail=f"model {name!r} is not enabled or does not support vision")
```

**`chat.py` / `prompt.py` — `_validated_prompt_model()`:**
```python
if row is None or not row["enabled"]:
    raise HTTPException(409, detail=f"model {name!r} is not enabled")
```

---

## 5. Frontend Changes

### `api/settings.ts`

```typescript
export type LmModel = {
  name: string;
  vision: boolean;
  tool_use: boolean;
  reasoning: boolean;
  enabled: boolean;
  last_seen: number;
};

// Replace useLmModelsByRole
export function useLmModelsForVision() { /* filter: enabled && vision */ }
export function useLmModelsForChat()   { /* filter: enabled */ }
```

Remove `LmRole` type and `useLmModelsByRole`.

### `LmStudioSettings.tsx`

- URL field placeholder + default button value: `http://localhost:1234`
- Model table: replace "Role" column (select) with "Capabilities" column
  - Three inline checkboxes per row: Vision / Tools / Reasoning
  - Each checkbox calls PATCH on change (same pattern as existing enabled checkbox)
- Grid: adjust `grid-template-columns` to fit new column

### `SessionSettingsDrawer.tsx`

- `useLmModelsByRole("vl")` → `useLmModelsForVision()`
- `useLmModelsByRole("prompt")` → `useLmModelsForChat()`

---

## 6. DB Re-initialization

Before starting implementation, drop and re-create the database:
- Stop the backend server
- Delete the SQLite DB file
- Restart — migrations run automatically on startup

---

## 7. Verification

1. Start backend + frontend
2. Go to `/settings/lmstudio`, enter `http://localhost:1234`, save
3. Press Refresh — models appear with auto-detected capabilities (vision/tool_use/reasoning checkboxes)
4. Manually uncheck Vision on a VL model — next Refresh resets it back (API is authoritative on refresh)
5. Try to use a non-vision model for image analysis → 409 with clear error
6. Chat with a prompt-only model → works fine
7. Confirm embedding models do NOT appear in the list
