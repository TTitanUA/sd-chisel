# Mode-specific Prompt Guides Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split a family's single `prompt_guide` field into three (`prompt_guide`, `prompt_i2i`, `prompt_t2i`); the assistant updates each via its own tool call, sees current values via a snapshot block on every turn.

**Architecture:** Additive DB migration adds two `TEXT NOT NULL DEFAULT ''` columns to `families`. Pydantic models, repo, and HTTP handlers gain the two fields. Assist endpoint exposes three function tools; SSE artifact event carries a `field` discriminator. Frontend form has three stacked sections; the assistant pane gets a `getCurrentState()` snapshot getter and a field-aware `onArtifact` callback. Detail view renders all three sections, hiding empty ones. Generation-time orchestrator stays unchanged (still reads only `prompt_guide`).

**Tech Stack:** Python (FastAPI, Pydantic, SQLite), TypeScript (React, React Query), pytest, Vitest.

**Spec:** `docs/superpowers/specs/2026-04-30-mode-specific-prompt-guides-design.md`.

---

## File map

**Backend create:**
- `backend/migrations/003_mode_prompt_guides.sql` — new migration adding `prompt_i2i`, `prompt_t2i`.

**Backend modify:**
- `backend/app/models/library.py` — add fields to `FamilyOut`/`FamilyCreate`/`FamilyUpdate`; add `AssistFieldsSnapshot`; extend `AssistRequest`.
- `backend/app/storage/library_repo.py` — `create_family`/`update_family` accept new fields; `list_families` `q` covers them.
- `backend/app/api/library.py` — rewrite `ASSIST_SYSTEM_PROMPT`; replace `ASSIST_TOOLS` with three function tools + Playwright; assist endpoint maps each tool name to its `field`; injects `current_state` snapshot block into the user message.

**Backend tests modify:**
- `backend/tests/test_library_repo.py` — extend family CRUD test; add a search-coverage assertion for the new columns.
- `backend/tests/test_library_api.py` — extend HTTP CRUD test to include new fields.

**Frontend modify:**
- `frontend/src/api/library.ts` — `Family`/`FamilyCreate`/`FamilyUpdate` gain `prompt_i2i`, `prompt_t2i`.
- `frontend/src/api/assist.ts` — `AssistFieldName`, `AssistFieldsSnapshot`; `artifact` event carries `field`; `streamAssist` accepts `currentState`.
- `frontend/src/components/molecules/AssistantPane.tsx` — prop `getCurrentState`; `onArtifact(field, content)`; tool-name → label map.
- `frontend/src/components/organisms/FamilyForm.tsx` — three states/sections; passes getter + field-aware artifact handler to the pane.
- `frontend/src/routes/library/families.tsx` — detail view renders all three guides as separate `LibraryDetailBlock`s, hiding empty mode-specific ones.

**Frontend tests modify:**
- `frontend/src/routes/library/libraryRoutes.test.tsx` — extend existing family test data with new fields; add detail-view assertion for an empty-mode case.

---

## Task 1: Database migration for mode-specific guides

**Files:**
- Create: `backend/migrations/003_mode_prompt_guides.sql`
- Test: `backend/tests/test_library_repo.py` (extend `test_family_create_update_delete`)

- [ ] **Step 1: Write the failing test (extend `test_family_create_update_delete`)**

Replace the existing `test_family_create_update_delete` in `backend/tests/test_library_repo.py` with the following:

```python
def test_family_create_update_delete(conn):
    created = library_repo.create_family(
        conn,
        id="testfam",
        display_name="Test Family",
        prompt_guide="Use test syntax.",
        prompt_i2i="Preserve subject pose.",
        prompt_t2i="Compose full scene.",
    )
    assert created["id"] == "testfam"
    assert created["prompt_i2i"] == "Preserve subject pose."
    assert created["prompt_t2i"] == "Compose full scene."

    updated = library_repo.update_family(
        conn,
        "testfam",
        display_name="Test Family 2",
        prompt_guide="Updated guide.",
        prompt_i2i="",
        prompt_t2i="Refined t2i rules.",
    )
    assert updated is not None
    assert updated["display_name"] == "Test Family 2"
    assert updated["prompt_i2i"] == ""
    assert updated["prompt_t2i"] == "Refined t2i rules."
    assert updated["updated_at"] >= created["updated_at"]

    assert library_repo.delete_family(conn, "testfam") is True
    assert library_repo.get_family(conn, "testfam") is None
    assert library_repo.delete_family(conn, "testfam") is False
```

Also extend `test_list_families_filters_by_query` to assert search hits the new columns:

```python
def test_list_families_filters_by_query(conn):
    library_repo.create_family(conn, id="abcxyz", display_name="Needle Family", prompt_guide="x")
    library_repo.create_family(
        conn,
        id="i2i_fam",
        display_name="Other",
        prompt_guide="base",
        prompt_i2i="haystack i2i specifics",
        prompt_t2i="",
    )
    library_repo.create_family(
        conn,
        id="t2i_fam",
        display_name="Other2",
        prompt_guide="base2",
        prompt_i2i="",
        prompt_t2i="haystack t2i specifics",
    )
    assert [r["id"] for r in library_repo.list_families(conn, q="needle")] == ["abcxyz"]
    hay = sorted(r["id"] for r in library_repo.list_families(conn, q="haystack"))
    assert hay == ["i2i_fam", "t2i_fam"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_library_repo.py::test_family_create_update_delete tests/test_library_repo.py::test_list_families_filters_by_query -v`

Expected: both FAIL — `create_family` does not accept `prompt_i2i` keyword (TypeError), and the list-by-query test will fail because the new column doesn't exist yet.

- [ ] **Step 3: Create migration file**

Create `backend/migrations/003_mode_prompt_guides.sql`:

```sql
-- Mode-specific prompt guides on families.
-- prompt_guide stays the required base; the two new columns are optional
-- additions for image-to-image and text-to-image modes respectively.
ALTER TABLE families ADD COLUMN prompt_i2i TEXT NOT NULL DEFAULT '';
ALTER TABLE families ADD COLUMN prompt_t2i TEXT NOT NULL DEFAULT '';
```

- [ ] **Step 4: Update repo to accept and search the new columns**

Modify `backend/app/storage/library_repo.py`. Change the `list_families` `q` clause to include the two new columns, and change the `create_family` and `update_family` signatures and SQL.

`list_families` (replace the existing function):

```python
def list_families(conn: sqlite3.Connection, q: str | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM families"
    params: list[Any] = []
    if q:
        sql += (
            " WHERE lower(id) LIKE ? OR lower(display_name) LIKE ? "
            "OR lower(prompt_guide) LIKE ? OR lower(prompt_i2i) LIKE ? OR lower(prompt_t2i) LIKE ?"
        )
        like = _like(q)
        params.extend([like, like, like, like, like])
    sql += " ORDER BY id"
    return [dict(r) for r in conn.execute(sql, params)]
```

`create_family` (replace):

```python
def create_family(
    conn: sqlite3.Connection,
    *,
    id: str,
    display_name: str,
    prompt_guide: str,
    prompt_i2i: str = "",
    prompt_t2i: str = "",
) -> dict[str, Any]:
    now = _now()
    conn.execute(
        "INSERT INTO families(id, display_name, prompt_guide, prompt_i2i, prompt_t2i, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (id, display_name, prompt_guide, prompt_i2i, prompt_t2i, now, now),
    )
    return get_family(conn, id)  # type: ignore[return-value]
```

`update_family` (replace):

```python
def update_family(
    conn: sqlite3.Connection,
    family_id: str,
    *,
    display_name: str,
    prompt_guide: str,
    prompt_i2i: str = "",
    prompt_t2i: str = "",
) -> dict[str, Any] | None:
    now = _now()
    cur = conn.execute(
        "UPDATE families SET display_name = ?, prompt_guide = ?, prompt_i2i = ?, "
        "prompt_t2i = ?, updated_at = ? WHERE id = ?",
        (display_name, prompt_guide, prompt_i2i, prompt_t2i, now, family_id),
    )
    if cur.rowcount == 0:
        return None
    return get_family(conn, family_id)
```

Defaults of `""` on the two new params keep the existing `seed_default_families` test fixture (which calls `create_family` with only the legacy three kwargs) working.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_library_repo.py -v`

Expected: all repo tests pass.

- [ ] **Step 6: Run the full backend suite to catch regressions**

Run: `cd backend && pytest -q`

Expected: green. (The migration is additive; legacy code paths that still pass only `prompt_guide` continue to work.)

- [ ] **Step 7: Commit**

```bash
git add backend/migrations/003_mode_prompt_guides.sql backend/app/storage/library_repo.py backend/tests/test_library_repo.py
git commit -m "feat(library/families): add prompt_i2i and prompt_t2i columns"
```

---

## Task 2: Pydantic models for the new fields

**Files:**
- Modify: `backend/app/models/library.py`
- Test: `backend/tests/test_library_api.py` (extend `test_family_crud_http`)

- [ ] **Step 1: Write the failing test**

Replace `test_family_crud_http` in `backend/tests/test_library_api.py` with:

```python
def test_family_crud_http(client):
    create = client.post(
        "/api/library/families",
        json={
            "id": "api_fam",
            "display_name": "API Family",
            "prompt_guide": "Base guide",
            "prompt_i2i": "i2i specifics",
            "prompt_t2i": "t2i specifics",
        },
    )
    assert create.status_code == 201, create.json()
    body = create.json()
    assert body["id"] == "api_fam"
    assert body["prompt_i2i"] == "i2i specifics"
    assert body["prompt_t2i"] == "t2i specifics"

    # i2i/t2i are optional in create
    create2 = client.post(
        "/api/library/families",
        json={"id": "api_fam2", "display_name": "API Family 2", "prompt_guide": "Base"},
    )
    assert create2.status_code == 201, create2.json()
    assert create2.json()["prompt_i2i"] == ""
    assert create2.json()["prompt_t2i"] == ""

    duplicate = client.post(
        "/api/library/families",
        json={"id": "api_fam", "display_name": "API Family", "prompt_guide": "Guide"},
    )
    assert duplicate.status_code == 409

    listed = client.get("/api/library/families", params={"q": "api"})
    assert listed.status_code == 200
    assert sorted(f["id"] for f in listed.json()) == ["api_fam", "api_fam2"]

    update = client.put(
        "/api/library/families/api_fam",
        json={
            "display_name": "API Family v2",
            "prompt_guide": "Base v2",
            "prompt_i2i": "",
            "prompt_t2i": "t2i v2",
        },
    )
    assert update.status_code == 200, update.json()
    assert update.json()["display_name"] == "API Family v2"
    assert update.json()["prompt_i2i"] == ""
    assert update.json()["prompt_t2i"] == "t2i v2"

    delete = client.delete("/api/library/families/api_fam")
    assert delete.status_code == 204
    assert client.get("/api/library/families/api_fam").status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_library_api.py::test_family_crud_http -v`

Expected: FAIL — Pydantic `FamilyOut` rejects `prompt_i2i` (extra="forbid") OR the create-without-i2i call fails because the field is required.

- [ ] **Step 3: Update Pydantic models**

Modify `backend/app/models/library.py`. Replace `FamilyOut`, `FamilyCreate`, `FamilyUpdate`, and `AssistRequest` (and add `AssistFieldsSnapshot`):

```python
class FamilyOut(StrictModel):
    id: str
    display_name: str
    prompt_guide: str
    prompt_i2i: str
    prompt_t2i: str
    created_at: int
    updated_at: int


class FamilyCreate(StrictModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=160)
    prompt_guide: str = Field(min_length=1)
    prompt_i2i: str = ""
    prompt_t2i: str = ""


class FamilyUpdate(StrictModel):
    display_name: str = Field(min_length=1, max_length=160)
    prompt_guide: str = Field(min_length=1)
    prompt_i2i: str = ""
    prompt_t2i: str = ""
```

And replace `AssistRequest` plus add the snapshot model just above it:

```python
class AssistFieldsSnapshot(StrictModel):
    prompt_guide: str = ""
    prompt_i2i: str = ""
    prompt_t2i: str = ""


class AssistRequest(StrictModel):
    model: str = Field(min_length=1)
    message: str = Field(min_length=1)
    previous_response_id: str | None = None
    current_state: AssistFieldsSnapshot = Field(default_factory=AssistFieldsSnapshot)
```

`current_state` defaults to an empty snapshot so the model doesn't fail on requests sent before the frontend update lands. The endpoint code (Task 3) will handle empty snapshots gracefully.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && pytest tests/test_library_api.py::test_family_crud_http -v`

Expected: PASS.

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && pytest -q`

Expected: green.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/library.py backend/tests/test_library_api.py
git commit -m "feat(library/families): expose prompt_i2i and prompt_t2i in API schemas"
```

---

## Task 3: Assist endpoint — three tools, snapshot injection, field-tagged artifacts

**Files:**
- Modify: `backend/app/api/library.py`

This task changes both the system prompt and the tool/event wiring of `POST /api/library/families/assist`. We do not add unit tests for the assist endpoint here — it is heavily LMStudio-dependent (the only existing coverage of `chat_responses_stream` is integration-level and lives outside this plan). We rely on the manual verification step at the end of Task 7.

- [ ] **Step 1: Replace `ASSIST_SYSTEM_PROMPT`**

In `backend/app/api/library.py`, replace the `ASSIST_SYSTEM_PROMPT` string (currently at lines 68-95) with:

```python
ASSIST_SYSTEM_PROMPT = (
    "You are writing prompt guides for a generative image model family. "
    "The guides you produce will be fed to ANOTHER LLM whose only job is to "
    "write image prompts (text-to-image and image-to-image) for this family.\n\n"
    "There are THREE separate guides you can update independently:\n\n"
    "[prompt_guide] — BASE rules shared across all modes:\n"
    "- REQUIRED: language the output prompt must be written in (e.g. "
    "English-only, Booru tags in English with descriptive prose in English, "
    "etc.). This is about the OUTPUT prompt language, not the user's chat "
    "language.\n"
    "- Tag/keyword syntax and formatting.\n"
    "- Quality and style tokens.\n"
    "- Token limits and recommended length.\n"
    "- LoRA interaction patterns and weight conventions.\n"
    "- Negative prompt conventions.\n\n"
    "[prompt_i2i] — IMAGE-TO-IMAGE-specific additions only:\n"
    "- What to preserve from the source image.\n"
    "- Transformation language (subtle vs aggressive edits).\n"
    "- Denoising / strength guidance, if family-specific.\n\n"
    "[prompt_t2i] — TEXT-TO-IMAGE-specific additions only:\n"
    "- Full scene composition rules.\n"
    "- Subject and background description conventions.\n"
    "- How to describe pose, framing, camera, etc.\n\n"
    "Use the corresponding tool to update each guide:\n"
    "- update_prompt_guide for the base guide.\n"
    "- update_prompt_i2i for the i2i additions.\n"
    "- update_prompt_t2i for the t2i additions.\n\n"
    "The base [prompt_guide] MUST include a section specifying the language "
    "the output prompt should be written in. If the user does not provide it, "
    "ask.\n\n"
    "Do not duplicate base rules into i2i/t2i guides. Mode-specific guides "
    "should contain ONLY what is specific to that mode.\n\n"
    "When the user provides documentation links, use your browser tools to "
    "navigate to the URL and read the content. Extract only the prompt-relevant "
    "facts.\n\n"
    "Strict rules for guide content:\n"
    "- No marketing prose, model history, benchmark numbers, or licensing notes.\n"
    "- No links, citations, or 'see docs at …' references.\n"
    "- No emojis.\n"
    "- No code examples, no API/SDK snippets, no curl/python/json blocks.\n"
    "- No filler like 'this section explains' — write the rule directly.\n"
    "- Prefer compact tables and bullet lists over paragraphs.\n\n"
    "The user's message will be preceded by a 'Current editor state:' block "
    "with the latest values of all three guides. Use it to know what is already "
    "written and what to change. Call the appropriate update_* tool with the "
    "FULL new content of that field (not a diff)."
)
```

- [ ] **Step 2: Replace `ASSIST_TOOLS` with three function tools**

In `backend/app/api/library.py`, replace `ASSIST_TOOLS` (currently at lines 97-120) with:

```python
def _function_tool(name: str, description: str) -> dict:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Full markdown content for this guide.",
                },
            },
            "required": ["content"],
            "additionalProperties": False,
        },
    }


ASSIST_FIELD_BY_TOOL = {
    "update_prompt_guide": "prompt_guide",
    "update_prompt_i2i": "prompt_i2i",
    "update_prompt_t2i": "prompt_t2i",
}

ASSIST_TOOLS = [
    _function_tool(
        "update_prompt_guide",
        "Update the BASE prompt guide (shared rules across all modes).",
    ),
    _function_tool(
        "update_prompt_i2i",
        "Update the IMAGE-TO-IMAGE-specific additions to the prompt guide.",
    ),
    _function_tool(
        "update_prompt_t2i",
        "Update the TEXT-TO-IMAGE-specific additions to the prompt guide.",
    ),
    # Reference Playwright MCP from LMStudio's mcp.json. The "Allow calling
    # servers from mcp.json" setting must be enabled in LMStudio Server Settings.
    {"type": "mcp", "server_label": "playwright"},
]
```

- [ ] **Step 3: Add a snapshot-block builder**

Still in `backend/app/api/library.py`, add this helper above the `assist` function (between `_assist_sse` and `@router.post("/families/assist")`):

```python
def _format_snapshot(snap) -> str:
    """Render the editor state block prepended to the user message.

    `snap` is an `AssistFieldsSnapshot` instance. Empty fields show as
    "(empty)" so the model knows there's nothing yet rather than guessing.
    """
    def section(label: str, value: str) -> str:
        return f"[{label}]\n{value if value.strip() else '(empty)'}"

    return (
        "Current editor state:\n"
        + section("prompt_guide", snap.prompt_guide)
        + "\n\n"
        + section("prompt_i2i", snap.prompt_i2i)
        + "\n\n"
        + section("prompt_t2i", snap.prompt_t2i)
    )
```

- [ ] **Step 4: Wire the snapshot and tool dispatch into the `assist` handler**

Inside `assist()` in `backend/app/api/library.py`, replace the `_stream_pass` inner function and the `gen()` initial `user_input` line. The relevant change:

Before:

```python
def _stream_pass(user_input, prev_id):
    ...
    for event in lmstudio_client.chat_responses_stream(
        ...
    ):
        ...
        elif etype == "function_call":
            if event.get("name") == "update_prompt_guide":
                content = event.get("arguments", {}).get("content", "")
                yield ("sse", {"type": "artifact", "content": content}, "")
            yield ("call", { ... })
        ...

def gen():
    user_input: Any = body.message
    ...
```

After:

```python
def _stream_pass(user_input, prev_id):
    """Run one /v1/responses pass and yield (sse_event, function_call_outputs, response_id)."""
    for event in lmstudio_client.chat_responses_stream(
        endpoint=endpoint,
        model=body.model,
        instructions=ASSIST_SYSTEM_PROMPT,
        user_input=user_input,
        tools=ASSIST_TOOLS,
        previous_response_id=prev_id,
    ):
        etype = event["type"]
        if etype == "delta":
            yield ("sse", {"type": "delta", "content": event["content"]}, "")
        elif etype == "mcp_status":
            yield ("sse", {
                "type": "tool_status",
                "tool": event.get("tool", ""),
                "status": event.get("status", ""),
            }, "")
        elif etype == "function_call":
            tool_name = event.get("name") or ""
            field = ASSIST_FIELD_BY_TOOL.get(tool_name)
            if field is not None:
                content = event.get("arguments", {}).get("content", "")
                yield ("sse", {"type": "artifact", "field": field, "content": content}, "")
            yield ("call", {
                "type": "function_call_output",
                "call_id": event.get("call_id", ""),
                "output": "ok",
            }, "")
        elif etype == "completed":
            yield ("done", {}, event.get("response_id", ""))

def gen():
    user_input: Any = f"{_format_snapshot(body.current_state)}\n\n---\n{body.message}"
    prev_id = body.previous_response_id
    last_response_id = prev_id or ""
    try:
        for _ in range(8):  # cap follow-up loops
            ...
```

(The body of `gen()` after the first line is unchanged.)

The snapshot is prepended only to the **first** user input of the call. Follow-up iterations (when the model called a tool) reuse `pending_outputs` as `user_input`, which is correct — the model already has the snapshot in its context from the first turn of this request, and `previous_response_id` carries it forward across requests (alongside the assistant's own messages). The next user-initiated turn will rebuild the snapshot from the request, which is exactly what we want — fresh edits propagate.

- [ ] **Step 5: Smoke-test the endpoint via the existing backend test runner**

There are no API-level tests for the assist endpoint in the suite, but the model parsing path is exercised by import. Run:

```bash
cd backend && pytest tests/test_library_api.py -q
```

Expected: green. (The test for `AssistRequest` itself is implicit — Pydantic will reject the stale Family fixtures only if our new code is malformed.)

Then a Python import check to make sure the new symbols are importable:

```bash
cd backend && python -c "from app.api.library import ASSIST_FIELD_BY_TOOL, ASSIST_TOOLS, _format_snapshot; assert set(ASSIST_FIELD_BY_TOOL) == {'update_prompt_guide','update_prompt_i2i','update_prompt_t2i'}; print('ok')"
```

Expected: prints `ok`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/library.py
git commit -m "feat(library/assist): three tools and current-state snapshot"
```

---

## Task 4: Frontend types and SSE client

**Files:**
- Modify: `frontend/src/api/library.ts`
- Modify: `frontend/src/api/assist.ts`

- [ ] **Step 1: Extend the `Family` types**

Replace the `Family` / `FamilyCreate` / `FamilyUpdate` block at the top of `frontend/src/api/library.ts`:

```typescript
export type Family = {
  id: string;
  display_name: string;
  prompt_guide: string;
  prompt_i2i: string;
  prompt_t2i: string;
  created_at: number;
  updated_at: number;
};

export type FamilyCreate = Pick<Family, "id" | "display_name" | "prompt_guide" | "prompt_i2i" | "prompt_t2i">;
export type FamilyUpdate = Pick<Family, "display_name" | "prompt_guide" | "prompt_i2i" | "prompt_t2i">;
```

No other changes in this file.

- [ ] **Step 2: Update the SSE client**

Replace the entire contents of `frontend/src/api/assist.ts` with:

```typescript
import { API_BASE, ApiError } from "./client";

export type AssistFieldName = "prompt_guide" | "prompt_i2i" | "prompt_t2i";

export type AssistFieldsSnapshot = {
  prompt_guide: string;
  prompt_i2i: string;
  prompt_t2i: string;
};

export type AssistStreamEvent =
  | { type: "delta"; content: string }
  | { type: "artifact"; field: AssistFieldName; content: string }
  | { type: "tool_status"; tool: string; status: string }
  | { type: "done"; response_id: string }
  | { type: "error"; detail: string };

export type AssistStreamCallbacks = {
  onDelta: (chunk: string) => void;
  onArtifact: (field: AssistFieldName, content: string) => void;
  onToolStatus?: (tool: string, status: string) => void;
  onDone: (responseId: string) => void;
  onError: (detail: string) => void;
};

export async function streamAssist(
  model: string,
  message: string,
  previousResponseId: string | null,
  currentState: AssistFieldsSnapshot,
  cb: AssistStreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const body: Record<string, unknown> = {
    model,
    message,
    current_state: currentState,
  };
  if (previousResponseId) body.previous_response_id = previousResponseId;

  const res = await fetch(`${API_BASE}/api/library/families/assist`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) {
    throw new ApiError(res.status, await res.text());
  }
  const reader = res.body?.getReader();
  if (!reader) {
    cb.onError("no response body");
    return;
  }
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const line = raw.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      const data = line.slice("data:".length).trim();
      if (!data) continue;
      let evt: AssistStreamEvent;
      try {
        evt = JSON.parse(data) as AssistStreamEvent;
      } catch {
        continue;
      }
      if (evt.type === "delta") cb.onDelta(evt.content);
      else if (evt.type === "artifact") cb.onArtifact(evt.field, evt.content);
      else if (evt.type === "tool_status") cb.onToolStatus?.(evt.tool, evt.status);
      else if (evt.type === "done") cb.onDone(evt.response_id);
      else if (evt.type === "error") cb.onError(evt.detail);
    }
  }
}
```

- [ ] **Step 3: Run the type-checker**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: TS errors in `AssistantPane.tsx` and `FamilyForm.tsx` (their `onArtifact` and `streamAssist` calls no longer match the new signatures). These will be fixed in Tasks 5 and 6.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/library.ts frontend/src/api/assist.ts
git commit -m "feat(api): assist artifact carries field; new types for mode guides"
```

---

## Task 5: Assistant pane — getCurrentState prop and field-aware artifact

**Files:**
- Modify: `frontend/src/components/molecules/AssistantPane.tsx`

- [ ] **Step 1: Update the props and tool labels, and rewire `send()`**

Replace the prop type and the body of `AssistantPane` in `frontend/src/components/molecules/AssistantPane.tsx`:

Top of file — add the import for the new types alongside `streamAssist`:

```typescript
import { streamAssist, type AssistFieldName, type AssistFieldsSnapshot } from "@/api/assist";
```

Below `SEND_HINT` (around line 11), add the tool→label map:

```typescript
const TOOL_LABELS: Record<string, string> = {
  update_prompt_guide: "updating base guide",
  update_prompt_i2i: "updating i2i guide",
  update_prompt_t2i: "updating t2i guide",
};
```

Replace the component signature and the `send()` function. The new component header:

```typescript
export function AssistantPane({
  getCurrentState,
  onArtifact,
}: {
  getCurrentState: () => AssistFieldsSnapshot;
  onArtifact: (field: AssistFieldName, content: string) => void;
}) {
```

Inside `send()`, replace the existing `await streamAssist(...)` call with:

```typescript
    const snapshot = getCurrentState();
    let assistantText = "";
    try {
      await streamAssist(model, content, responseId, snapshot, {
        onDelta: (chunk) => {
          assistantText += chunk;
          setStreaming(assistantText);
        },
        onArtifact: (field, artifactContent) => {
          onArtifact(field, artifactContent);
        },
        onToolStatus: (tool, status) => {
          if (status === "running") {
            setCurrentTool(tool || "tool");
          } else {
            setCurrentTool(null);
            if (status === "done" || status === "failed") {
              setToolCount((n) => n + 1);
            }
          }
        },
        onDone: (rid) => {
          if (rid) setResponseId(rid);
        },
        onError: (detail) => setError(detail),
      });
    } catch (err) {
      setError(String(err));
    } finally {
      const cleaned = normalizeAssistantText(assistantText);
      if (cleaned) {
        setMessages((prev) => [...prev, { role: "assistant", content: cleaned }]);
      }
      setPending(false);
      setStreaming("");
      setCurrentTool(null);
    }
```

Update the `statusLabel` calculation (just below the `send()` function) to map tool names to friendly labels:

```typescript
  const toolLabel = currentTool
    ? (TOOL_LABELS[currentTool] ?? `running ${currentTool}…`)
    : "";
  const statusLabel = currentTool
    ? toolLabel
    : showStreaming
      ? "writing reply…"
      : "thinking…";
```

(Note: function-call tool names like `update_prompt_guide` come through the same `mcp_status` channel only if the LMStudio backend forwards them; in practice the function-tool calls produce `function_call` events that we render via the artifact event, not via `currentTool`. The `currentTool` slot is still used by the Playwright MCP tool. The map above handles the rare case where a future backend forwards function-tool status — fine to have, costs nothing.)

- [ ] **Step 2: Run the type-checker**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: TS errors only in `FamilyForm.tsx` (because it passes `onArtifact={setPromptGuide}` — a `(string) => void`, not the new `(field, string) => void` shape). Will be fixed in Task 6.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/molecules/AssistantPane.tsx
git commit -m "feat(assist): pane takes snapshot getter and field-aware artifact"
```

---

## Task 6: Family form — three sections, snapshot getter, field-aware artifact

**Files:**
- Modify: `frontend/src/components/organisms/FamilyForm.tsx`

- [ ] **Step 1: Replace the form**

Replace the entire contents of `frontend/src/components/organisms/FamilyForm.tsx` with:

```typescript
import { useCallback, useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { TextInput } from "@/components/molecules/FormField";
import { LibraryFormPage, LibraryFormSection } from "@/components/organisms/LibraryFormSection";
import libForm from "@/components/organisms/libraryForm.module.css";
import { MarkdownField } from "@/components/molecules/MarkdownField";
import { AssistantPane } from "@/components/molecules/AssistantPane";
import type { AssistFieldName, AssistFieldsSnapshot } from "@/api/assist";
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
  const [promptI2i, setPromptI2i] = useState(family?.prompt_i2i ?? "");
  const [promptT2i, setPromptT2i] = useState(family?.prompt_t2i ?? "");
  const [showAssistant, setShowAssistant] = useState(false);

  const isEdit = Boolean(family);
  const pageTitle = isEdit && family ? `Edit · ${family.display_name}` : "New family";

  const canSave =
    displayName.trim() !== "" &&
    promptGuide.trim() !== "" &&
    (Boolean(family) || id.trim() !== "");

  const handleArtifact = useCallback((field: AssistFieldName, content: string) => {
    if (field === "prompt_guide") setPromptGuide(content);
    else if (field === "prompt_i2i") setPromptI2i(content);
    else if (field === "prompt_t2i") setPromptT2i(content);
  }, []);

  const getCurrentState = useCallback(
    (): AssistFieldsSnapshot => ({
      prompt_guide: promptGuide,
      prompt_i2i: promptI2i,
      prompt_t2i: promptT2i,
    }),
    [promptGuide, promptI2i, promptT2i],
  );

  const form = (
    <form
      className={showAssistant ? libForm.formMain : libForm.formShell}
      onSubmit={(event) => {
        event.preventDefault();
        if (!canSave) return;
        const common = {
          display_name: displayName.trim(),
          prompt_guide: promptGuide.trim(),
          prompt_i2i: promptI2i.trim(),
          prompt_t2i: promptT2i.trim(),
        };
        onSubmit(family ? common : { id: id.trim(), ...common });
      }}
    >
      <LibraryFormPage
        title={pageTitle}
        breadcrumb={
          <>
            <button type="button" className={libForm.breadcrumbButton} onClick={onCancel}>
              Library
            </button>
            <Icon name="ChevronRight" size={10} aria-hidden />
            <button type="button" className={libForm.breadcrumbButton} onClick={onCancel}>
              Families
            </button>
            <Icon name="ChevronRight" size={10} aria-hidden />
            <span className={libForm.breadcrumbCurrent}>
              {isEdit ? family?.display_name : "New family"}
            </span>
          </>
        }
        foot={
          <>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              icon={<Icon name="MessageSquare" size={12} />}
              onClick={() => setShowAssistant((v) => !v)}
            >
              {showAssistant ? "Hide assistant" : "Assistant"}
            </Button>
            <div style={{ flex: 1 }} />
            <Button type="button" variant="ghost" onClick={onCancel}>
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              disabled={!canSave || isSaving}
              icon={<Icon name="Check" />}
            >
              {isSaving ? "Saving…" : isEdit ? "Save changes" : "Create family"}
            </Button>
          </>
        }
      >
        <LibraryFormSection title="Identity" subtitle="ID in code and the display name in the UI.">
          <TextInput
            label="ID"
            hint="slug, lowercase"
            value={id}
            placeholder="sdxl"
            onChange={(e) => setId(e.currentTarget.value)}
            disabled={isEdit}
          />
          <TextInput
            label="Display name"
            value={displayName}
            placeholder="SDXL"
            onChange={(e) => setDisplayName(e.currentTarget.value)}
          />
        </LibraryFormSection>

        <LibraryFormSection
          title="Prompt guide (base)"
          subtitle="Shared rules for this family. The downstream LLM sees this in every session."
        >
          <MarkdownField
            label="Content"
            value={promptGuide}
            onChange={setPromptGuide}
            hint="Output language, tag syntax, quality tokens, LoRA conventions, negative prompt rules."
          />
        </LibraryFormSection>

        <LibraryFormSection
          title="Image-to-image additions"
          subtitle="Optional. Shown only when the session is i2i."
        >
          <MarkdownField
            label="Content (optional)"
            value={promptI2i}
            onChange={setPromptI2i}
            hint="What to preserve from the source, transformation language, denoising guidance."
          />
        </LibraryFormSection>

        <LibraryFormSection
          title="Text-to-image additions"
          subtitle="Optional. Shown only when the session is t2i."
        >
          <MarkdownField
            label="Content (optional)"
            value={promptT2i}
            onChange={setPromptT2i}
            hint="Scene composition, subject and background description, framing/camera."
          />
        </LibraryFormSection>
      </LibraryFormPage>
    </form>
  );

  if (!showAssistant) return form;

  return (
    <div className={libForm.formWithAssistant}>
      {form}
      <AssistantPane onArtifact={handleArtifact} getCurrentState={getCurrentState} />
    </div>
  );
}
```

- [ ] **Step 2: Run the type-checker**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: should now be green for `FamilyForm.tsx` and `AssistantPane.tsx`. The remaining failure (if any) is the detail view in `routes/library/families.tsx`, which is fine — Task 7 fixes that.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/organisms/FamilyForm.tsx
git commit -m "feat(library/families): three guide sections in form"
```

---

## Task 7: Family detail view — show all three guides

**Files:**
- Modify: `frontend/src/routes/library/families.tsx`
- Test: `frontend/src/routes/library/libraryRoutes.test.tsx` (extend existing tests if they reference family fixtures)

- [ ] **Step 1: Inspect the existing route tests**

Run: `cd frontend && pnpm vitest run libraryRoutes`

Expected: existing tests pass (we haven't changed the routes file yet, but the tests may reference Family fixtures that now miss the new fields). Note any failures — they are fixture-shape failures and the diagnostics will tell you exactly what to add.

- [ ] **Step 2: Update the test fixtures and add a detail-render assertion**

Open `frontend/src/routes/library/libraryRoutes.test.tsx`. For every literal that constructs a `Family` (or array of families) returned by a mocked API, add `prompt_i2i: ""` and `prompt_t2i: ""` so it matches the new `Family` shape. The TS compiler in test mode will tell you which lines need the addition.

Then add a new test below the existing family-detail render test (search for the existing test that asserts the prompt-guide markdown shows up; add a sibling test that asserts both i2i and t2i sections also render). Use the same render helper that the existing test uses. The assertion shape:

```typescript
it("renders all three prompt guides on the family detail view, hiding empty mode-specific ones", async () => {
  // ... use the same render helper as the existing family detail test, but
  // mock the family payload to:
  //   prompt_guide: "BASE rules"
  //   prompt_i2i: "I2I additions"
  //   prompt_t2i: ""
  // After the route renders the detail view:
  expect(await screen.findByText(/BASE rules/i)).toBeInTheDocument();
  expect(screen.getByText(/I2I additions/i)).toBeInTheDocument();
  // The empty t2i section should not render at all — use queryByText.
  expect(screen.queryByText(/text-to-image additions/i)).toBeNull();
});
```

If the existing test file does not currently have a "renders detail" test, skip the addition here and just fix the fixture shapes — Task 8's manual verification will cover the rendering.

- [ ] **Step 3: Update the detail view to render three sections**

In `frontend/src/routes/library/families.tsx`, replace the existing detail block (currently a single `<LibraryDetailBlock label="Prompt guide" isLast>`):

Find this block (around lines 171-176):

```typescript
<LibraryDetailBlock label="Prompt guide" isLast>
  {selected.prompt_guide
    ? <MarkdownView value={selected.prompt_guide} />
    : <p className={detailStyles.desc}>—</p>}
</LibraryDetailBlock>
```

Replace it with:

```typescript
<LibraryDetailBlock label="Prompt guide (base)">
  {selected.prompt_guide
    ? <MarkdownView value={selected.prompt_guide} />
    : <p className={detailStyles.desc}>—</p>}
</LibraryDetailBlock>
{selected.prompt_i2i.trim() !== "" && (
  <LibraryDetailBlock label="Image-to-image additions">
    <MarkdownView value={selected.prompt_i2i} />
  </LibraryDetailBlock>
)}
{selected.prompt_t2i.trim() !== "" && (
  <LibraryDetailBlock label="Text-to-image additions" isLast>
    <MarkdownView value={selected.prompt_t2i} />
  </LibraryDetailBlock>
)}
{selected.prompt_i2i.trim() === "" && selected.prompt_t2i.trim() === "" && (
  // Reapply isLast on the base block when no mode-specific additions exist.
  // This is a no-op visual hint; CSS spacing depends on isLast on the LAST block.
  null
)}
```

This leaves a small wart: when both i2i and t2i are empty, the base block doesn't have `isLast`. Fix this cleanly by computing the "last" flag once:

Replace the previous block again with:

```typescript
{(() => {
  const i2iFilled = selected.prompt_i2i.trim() !== "";
  const t2iFilled = selected.prompt_t2i.trim() !== "";
  return (
    <>
      <LibraryDetailBlock label="Prompt guide (base)" isLast={!i2iFilled && !t2iFilled}>
        {selected.prompt_guide
          ? <MarkdownView value={selected.prompt_guide} />
          : <p className={detailStyles.desc}>—</p>}
      </LibraryDetailBlock>
      {i2iFilled && (
        <LibraryDetailBlock label="Image-to-image additions" isLast={!t2iFilled}>
          <MarkdownView value={selected.prompt_i2i} />
        </LibraryDetailBlock>
      )}
      {t2iFilled && (
        <LibraryDetailBlock label="Text-to-image additions" isLast>
          <MarkdownView value={selected.prompt_t2i} />
        </LibraryDetailBlock>
      )}
    </>
  );
})()}
```

- [ ] **Step 4: Run the type-checker and tests**

Run: `cd frontend && pnpm tsc --noEmit && pnpm vitest run libraryRoutes`

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/library/families.tsx frontend/src/routes/library/libraryRoutes.test.tsx
git commit -m "feat(library/families): render three guides on detail view"
```

---

## Task 8: Manual verification

This task is not skippable — the assist endpoint has no automated coverage and the wiring goes through LMStudio.

- [ ] **Step 1: Apply the migration on a dev DB**

If you have a long-lived dev DB, the next backend startup will run `apply_pending` and add the columns. To force-check:

```bash
cd backend && python -c "import sqlite3, pathlib; \
from app.storage.migrations import apply_pending; \
c = sqlite3.connect('chisel.db'); \
c.row_factory = sqlite3.Row; \
apply_pending(c, pathlib.Path('migrations')); \
cols = [r[1] for r in c.execute('PRAGMA table_info(families)')]; \
assert 'prompt_i2i' in cols and 'prompt_t2i' in cols; \
print('migrated:', cols)"
```

Expected: prints a list including `prompt_i2i` and `prompt_t2i`.

- [ ] **Step 2: Start backend and frontend**

In two background shells:

```bash
cd backend && uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend && pnpm dev
```

- [ ] **Step 3: Drive the form in chrome-devtools MCP**

Use `mcp__chrome-devtools__new_page` to open `http://localhost:5173/library/families/new`. Then:

1. `take_snapshot` — verify the three sections "Prompt guide (base)", "Image-to-image additions", "Text-to-image additions" all render.
2. `fill` the ID, Display name, and the base prompt guide; click "Create family".
3. Edit the just-created family. `take_snapshot` — confirm the form pre-populates the base guide and the two new fields show up empty.
4. Open the assistant pane. Send a message like: "Make a base guide for SDXL. Output prompts must be in English with Booru tags." Watch the base section update via the artifact stream.
5. Send a follow-up: "Add an i2i guide: preserve the source pose, denoising 0.4-0.6." Confirm the i2i section populates without touching the base section.
6. Edit the t2i section by hand in the editor. Without sending another message, click into the assistant and send "Refine t2i for full-scene composition." Confirm the assistant sees the manual edit (because the snapshot is read at send time) and updates only t2i.
7. Save changes. Reopen the detail view — all three sections should render as markdown; clear t2i in another edit and confirm the t2i block disappears from the detail view.

- [ ] **Step 4: Smoke-test errors**

Without LMStudio configured, hit the assistant — confirm a clear error appears in the pane (the existing precondition errors still apply: model must be `enabled` and `tool_use`).

- [ ] **Step 5: Stop the dev servers**

`taskkill /F /PID …` (Windows) for the two background shells.

- [ ] **Step 6: Commit any test fixture or doc fixes discovered during verification**

If verification surfaced minor issues (typo in hint text, missing copy, etc.), fix and commit:

```bash
git add -A
git commit -m "chore(library/families): polish from manual verification"
```

If nothing needs fixing, skip the commit.

---

## Self-review summary

- **Spec coverage:** DB migration (Task 1), Pydantic + repo (Tasks 1–2), system prompt + tools + snapshot + artifact (Task 3), TS types and SSE client (Task 4), pane (Task 5), form sections (Task 6), detail view (Task 7), manual verification (Task 8). Out-of-scope items (orchestrator, sessions) are noted in the spec and respected here.
- **Placeholders:** None — every step contains the actual code or command.
- **Type consistency:** `AssistFieldName` is referenced consistently across `assist.ts`, `AssistantPane.tsx`, and `FamilyForm.tsx`. `AssistFieldsSnapshot` keys match the backend `AssistFieldsSnapshot` model exactly. The `ASSIST_FIELD_BY_TOOL` mapping uses the same `prompt_guide` / `prompt_i2i` / `prompt_t2i` strings emitted in the SSE `field` payload, which the frontend reads via the same string union.
