# Mode-specific prompt guides — Design Spec

## Overview

Split the single `prompt_guide` field on a family into three separate fields:

- **`prompt_guide`** (base, required) — shared rules: language of the output prompt, tag syntax, quality tokens, LoRA conventions, negative prompt conventions.
- **`prompt_i2i`** (image-to-image additions, optional) — what to preserve from the source, transformation language, denoising/strength guidance.
- **`prompt_t2i`** (text-to-image additions, optional) — full scene composition, subject/background description, framing/camera conventions.

Extend the family form to edit all three fields and the assistant to update them via three separate tool calls.

**Out of scope.** Generation-time integration (`prompt_orchestrator.py`, sessions, session mode) is intentionally untouched. The orchestrator continues to read only `family.prompt_guide` (the base). Mode-aware assembly of `prompt_guide + prompt_i2i` or `prompt_guide + prompt_t2i` will happen in a later change once sessions gain an explicit mode field.

## Database

New migration `backend/migrations/002_mode_prompt_guides.sql`:

```sql
ALTER TABLE families ADD COLUMN prompt_i2i TEXT NOT NULL DEFAULT '';
ALTER TABLE families ADD COLUMN prompt_t2i TEXT NOT NULL DEFAULT '';
```

- `prompt_guide` keeps its existing constraints (`NOT NULL`, min_length=1).
- Existing rows get empty strings for the new columns; users fill them in later if needed.
- No automatic content split — too risky to chop existing guides up by heuristics.

## Backend API

### Pydantic models (`backend/app/models/library.py`)

```python
class FamilyOut(BaseModel):
    id: str
    display_name: str
    prompt_guide: str
    prompt_i2i: str
    prompt_t2i: str
    created_at: int
    updated_at: int

class FamilyCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    display_name: str = Field(..., min_length=1, max_length=160)
    prompt_guide: str = Field(..., min_length=1)
    prompt_i2i: str = ""
    prompt_t2i: str = ""

class FamilyUpdate(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=160)
    prompt_guide: str = Field(..., min_length=1)
    prompt_i2i: str = ""
    prompt_t2i: str = ""

class AssistFieldsSnapshot(BaseModel):
    prompt_guide: str = ""
    prompt_i2i: str = ""
    prompt_t2i: str = ""

class AssistRequest(BaseModel):
    model: str = Field(min_length=1)
    message: str = Field(min_length=1)
    previous_response_id: str | None = None
    current_state: AssistFieldsSnapshot
```

`current_state` is required on every assist request. The frontend always sends a fresh snapshot so the assistant sees user-side edits made between turns.

### Repository (`backend/app/storage/library_repo.py`)

- `create_family(conn, *, id, display_name, prompt_guide, prompt_i2i, prompt_t2i)` — inserts all five fields plus timestamps.
- `update_family(conn, family_id, *, display_name, prompt_guide, prompt_i2i, prompt_t2i)` — updates all four content fields plus `updated_at`.
- `get_family` and `list_families` row-mappers include the two new columns in the returned dict.
- The `q` search in `list_families` matches against `id | display_name | prompt_guide | prompt_i2i | prompt_t2i` (case-insensitive `LIKE`).

### Assist endpoint (`backend/app/api/library.py`)

#### System prompt (rewritten)

```
You are writing prompt guides for a generative image model family. The guides
you produce will be fed to ANOTHER LLM whose only job is to write image
prompts (text-to-image and image-to-image) for this family.

There are THREE separate guides you can update independently:

[prompt_guide] — BASE rules shared across all modes:
- REQUIRED: language the output prompt must be written in (e.g. English-only,
  Booru tags in English with descriptive prose in English, etc.). This is
  about the OUTPUT prompt language, not the user's chat language.
- Tag/keyword syntax and formatting
- Quality and style tokens
- Token limits and length recommendations
- LoRA interaction patterns and weight conventions
- Negative prompt conventions

[prompt_i2i] — IMAGE-TO-IMAGE-specific additions only:
- What to preserve from the source image
- Transformation language (subtle vs aggressive edits)
- Denoising / strength guidance, if family-specific

[prompt_t2i] — TEXT-TO-IMAGE-specific additions only:
- Full scene composition rules
- Subject and background description conventions
- How to describe pose, framing, camera, etc.

Use the corresponding tool to update each guide:
- update_prompt_guide for the base guide
- update_prompt_i2i for the i2i additions
- update_prompt_t2i for the t2i additions

The base [prompt_guide] MUST include a section specifying the language the
output prompt should be written in. If the user does not provide it, ask.

Do not duplicate base rules into i2i/t2i guides. Mode-specific guides should
contain ONLY what is specific to that mode.

When the user provides documentation links, use your browser tools to navigate
to the URL and read the content. Extract only the prompt-relevant facts.

Strict rules for guide content:
- No marketing prose, model history, benchmark numbers, or licensing notes.
- No links, citations, or 'see docs at …' references.
- No emojis.
- No code examples, no API/SDK snippets, no curl/python/json blocks.
- No filler like 'this section explains' — write the rule directly.
- Prefer compact tables and bullet lists over paragraphs.

The user's message will be preceded by a "Current editor state:" block with
the latest values of all three guides. Use it to know what is already written
and what to change. Call the appropriate update_* tool with the FULL new
content of that field (not a diff).
```

#### Tools (three function tools)

```json
[
  {
    "type": "function",
    "function": {
      "name": "update_prompt_guide",
      "description": "Update the BASE prompt guide (shared rules across all modes).",
      "parameters": {
        "type": "object",
        "properties": {
          "content": {"type": "string", "description": "Full markdown content of the base guide."}
        },
        "required": ["content"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "update_prompt_i2i",
      "description": "Update the IMAGE-TO-IMAGE-specific additions to the prompt guide.",
      "parameters": {
        "type": "object",
        "properties": {
          "content": {"type": "string", "description": "Full markdown content for the i2i guide."}
        },
        "required": ["content"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "update_prompt_t2i",
      "description": "Update the TEXT-TO-IMAGE-specific additions to the prompt guide.",
      "parameters": {
        "type": "object",
        "properties": {
          "content": {"type": "string", "description": "Full markdown content for the t2i guide."}
        },
        "required": ["content"]
      }
    }
  }
]
```

The MCP `playwright` tool stays as-is (used for URL fetching).

#### `current_state` injection

The endpoint composes the user input passed into `chat_responses_stream` like so:

```
Current editor state:
[prompt_guide]
{current_state.prompt_guide or "(empty)"}

[prompt_i2i]
{current_state.prompt_i2i or "(empty)"}

[prompt_t2i]
{current_state.prompt_t2i or "(empty)"}

---
{message}
```

Sent on every turn (not only the first). `previous_response_id` continues to chain context, but the snapshot block is always rebuilt from the request, so user-side edits propagate.

#### SSE event protocol changes

| Event | Payload | Notes |
|---|---|---|
| `delta` | `{"type": "delta", "content": "..."}` | unchanged |
| `artifact` | `{"type": "artifact", "field": "prompt_guide" \| "prompt_i2i" \| "prompt_t2i", "content": "..."}` | **field added** |
| `tool_status` | `{"type": "tool_status", "tool": "...", "status": "..."}` | unchanged |
| `done` | `{"type": "done", "response_id": "..."}` | unchanged |
| `error` | `{"type": "error", "detail": "..."}` | unchanged |

The endpoint maps each of the three function-call names to the corresponding `field` value when emitting the artifact. The 8-iteration follow-up loop is unchanged.

## Frontend

### `frontend/src/api/assist.ts`

```typescript
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
): Promise<void>;
```

### `frontend/src/components/molecules/AssistantPane.tsx`

New props:

```typescript
type AssistantPaneProps = {
  getCurrentState: () => AssistFieldsSnapshot;
  onArtifact: (field: AssistFieldName, content: string) => void;
};
```

`getCurrentState` is a function-getter (not a value) so the snapshot is read at the moment of `send()` — capturing user edits made between turns.

Tool-status labels:

```typescript
const TOOL_LABELS: Record<string, string> = {
  update_prompt_guide: "updating base guide",
  update_prompt_i2i: "updating i2i guide",
  update_prompt_t2i: "updating t2i guide",
};
```

Falls back to the raw tool name if not in the map.

### `frontend/src/components/organisms/FamilyForm.tsx`

State:

```typescript
const [promptGuide, setPromptGuide] = useState(family?.prompt_guide ?? "");
const [promptI2i, setPromptI2i] = useState(family?.prompt_i2i ?? "");
const [promptT2i, setPromptT2i] = useState(family?.prompt_t2i ?? "");
```

Three sections, in order: Identity → "Prompt guide (base)" → "Image-to-image additions" → "Text-to-image additions". Each new section uses the same `<MarkdownField>` component and the same section/grid layout as the existing prompt-guide section. Hints:

- Base — "Shared rules: language, tag syntax, quality tokens, LoRA conventions."
- i2i — "i2i-specific rules: what to preserve from the source, transformation language, denoising guidance."
- t2i — "t2i-specific rules: scene composition, subject/background description."

Both i2i and t2i labels say "Content (optional)".

Artifact handler:

```typescript
const handleArtifact = (field: AssistFieldName, content: string) => {
  if (field === "prompt_guide") setPromptGuide(content);
  else if (field === "prompt_i2i") setPromptI2i(content);
  else if (field === "prompt_t2i") setPromptT2i(content);
};

const getCurrentState = useCallback(() => ({
  prompt_guide: promptGuide,
  prompt_i2i: promptI2i,
  prompt_t2i: promptT2i,
}), [promptGuide, promptI2i, promptT2i]);

<AssistantPane onArtifact={handleArtifact} getCurrentState={getCurrentState} />
```

Submit body includes all three fields:

```typescript
const common = {
  display_name: displayName.trim(),
  prompt_guide: promptGuide.trim(),
  prompt_i2i: promptI2i.trim(),
  prompt_t2i: promptT2i.trim(),
};
```

`canSave` rule unchanged: `display_name` non-empty and `prompt_guide` non-empty (i2i/t2i may be empty).

### `frontend/src/api/library.ts`

`Family`, `FamilyCreate`, `FamilyUpdate` TypeScript types each gain `prompt_i2i: string` and `prompt_t2i: string`.

### Family detail view

The detail view (currently rendering `prompt_guide` as markdown) gets two more sections — `prompt_i2i` and `prompt_t2i` — rendered with the same markdown component. Each mode-specific section is hidden when its content is empty.

## File changes summary

| File | Change |
|---|---|
| `backend/migrations/002_mode_prompt_guides.sql` | new — `ALTER TABLE families` adds two columns |
| `backend/app/models/library.py` | add fields to `FamilyOut`/`FamilyCreate`/`FamilyUpdate`; add `AssistFieldsSnapshot`; extend `AssistRequest` with `current_state` |
| `backend/app/storage/library_repo.py` | extend create/update/get/list to handle the two new columns; extend `q` search |
| `backend/app/api/library.py` | new system prompt; three function tools; artifact event with `field`; inject `current_state` block before user message |
| `frontend/src/api/assist.ts` | new types `AssistFieldName`/`AssistFieldsSnapshot`; artifact event carries `field`; new `currentState` parameter on `streamAssist` |
| `frontend/src/components/molecules/AssistantPane.tsx` | new prop `getCurrentState`; tool-name → label map for the status bar |
| `frontend/src/components/organisms/FamilyForm.tsx` | three states/sections; pass `getCurrentState` and field-aware `onArtifact` to the pane |
| `frontend/src/api/library.ts` | extend `Family`/`FamilyCreate`/`FamilyUpdate` TS types |
| Family detail page | render i2i and t2i sections (hidden when empty) |

## Open items / non-goals

- No generation-time integration in this change. `prompt_orchestrator.py` continues to read only `family.prompt_guide`.
- No automatic content migration of existing `prompt_guide` text into i2i/t2i.
- No backwards-compat shim on the API: the frontend ships in lockstep with the backend; older clients (none in practice) would simply not see the new fields.
