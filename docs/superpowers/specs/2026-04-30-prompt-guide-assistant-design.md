# Prompt Guide Assistant — Design Spec

## Overview

An AI assistant sidebar on the family create/edit page (`/library/families/new`, `/library/families/:id/edit`) that helps users write prompt guides through a conversational chat interface. The assistant can read documentation from user-provided URLs (via MCP/Playwright on the LMStudio side) and automatically update the prompt guide field in the form.

Families are not limited to Stable Diffusion — they can represent any generative model family (Flux, Midjourney, etc.). The prompt guide covers both image-to-image (i2i) and text-to-image (t2i) workflows.

## Requirements

- Users can chat with an LLM to collaboratively write a prompt guide
- Users can paste documentation links; the LLM fetches content via its MCP/Playwright tools
- Users can paste documentation text directly into the chat
- The assistant automatically updates the `prompt_guide` field in the form (artifact pattern)
- Chat history is ephemeral (in-memory, no database persistence)
- Uses the same LMStudio backend as existing session chat
- Requires a model with `tool_use` capability

## Architecture

### Backend

**New endpoint:** `POST /api/library/families/assist`

Stateless SSE streaming endpoint. The frontend sends the full message history on every request; the backend adds the system prompt and tool definitions, then proxies to LMStudio.

**Request body:**
```json
{
  "model": "model-name",
  "messages": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."},
    ...
  ]
}
```

**New method in `lmstudio_client.py`:** `chat_stream_with_tools()`

Like `chat_stream()` but accepts a `tools` parameter and yields structured events instead of raw text chunks. Handles the OpenAI-compatible streaming format for tool calls where `delta` contains `tool_calls` array with `function.name` and `function.arguments` accumulated across chunks.

**SSE event protocol:**
| Event type | Payload | Description |
|---|---|---|
| `delta` | `{"type": "delta", "content": "..."}` | Text chunk from assistant |
| `artifact` | `{"type": "artifact", "content": "..."}` | Result of `update_prompt_guide` tool call |
| `done` | `{"type": "done"}` | Stream complete |
| `error` | `{"type": "error", "detail": "..."}` | Error occurred |

**System prompt:**
```
You are a prompt-guide writing assistant for generative image model families.
Help the user write a prompt guide — a set of rules that the LLM will follow
when generating prompts for this family in both text-to-image (t2i) and
image-to-image (i2i) workflows.

You have a tool `update_prompt_guide` — call it whenever you have a draft or
update of the prompt guide. The user will see the result in real-time in the
editor.

When the user provides documentation links, read them using your MCP tools and
extract relevant information about the model's prompting style, supported tags,
quality tokens, and any family-specific syntax.

Keep the prompt guide concise and actionable. Focus on:
- Tag syntax and formatting rules
- Quality/style tokens specific to this family
- Token limits or recommendations
- LoRA interaction patterns
- Negative prompt conventions
- Any differences between t2i and i2i prompting for this family
```

**Tool definition (OpenAI function calling format):**
```json
{
  "type": "function",
  "function": {
    "name": "update_prompt_guide",
    "description": "Update the prompt guide content in the editor. Call this whenever you have a new or revised version of the prompt guide.",
    "parameters": {
      "type": "object",
      "properties": {
        "content": {
          "type": "string",
          "description": "The full prompt guide markdown content"
        }
      },
      "required": ["content"]
    }
  }
}
```

**Tool call handling in the stream:** When the LLM response contains a tool call to `update_prompt_guide`, the backend accumulates the `function.arguments` chunks, parses the JSON, extracts `content`, and emits `{"type": "artifact", "content": "..."}` as an SSE event. The tool call ends the current response — no follow-up `tool` role message is sent back to the LLM. The frontend appends the artifact content to the assistant's message history so subsequent requests include it as context.

### Frontend

**Layout change in `FamilyForm`:**

The form gets an optional right sidebar for the assistant. A wrapper div `.formWithAssistant` uses flexbox row layout. The form occupies `flex: 1`, the assistant sidebar has `width: 380px` with a left border. A toggle button in the form header opens/closes the sidebar.

**New component: `AssistantPane`** (`frontend/src/components/molecules/AssistantPane.tsx`)

Reuses the `ds-chat-*` design system classes from the existing `ChatPane`. Key differences from `ChatPane`:
- Messages stored in `useState<AssistantMessage[]>` (not React Query, no DB)
- No "Generate prompt" button in the composer
- Model selector dropdown in the header, filtered to `tool_use === true` models
- SSE parser handles the additional `artifact` event type
- Calls `onArtifact(content)` callback when artifact events arrive
- Empty state: "Paste documentation or describe the model family to get started"

**New API client:** `frontend/src/api/assist.ts`

```typescript
export type AssistantMessage = {
  role: "user" | "assistant";
  content: string;
};

export type AssistStreamEvent =
  | { type: "delta"; content: string }
  | { type: "artifact"; content: string }
  | { type: "done" }
  | { type: "error"; detail: string };

export type AssistStreamCallbacks = {
  onDelta: (chunk: string) => void;
  onArtifact: (content: string) => void;
  onDone: () => void;
  onError: (detail: string) => void;
};

export async function streamAssist(
  model: string,
  messages: AssistantMessage[],
  cb: AssistStreamCallbacks,
  signal?: AbortSignal,
): Promise<void> { ... }
```

**Integration with FamilyForm:**

`FamilyForm` gains:
- `showAssistant` state (boolean toggle)
- When `AssistantPane` emits `onArtifact(content)`, `setPromptGuide(content)` is called, updating the markdown editor in real-time

The assistant is available on both create and edit modes.

### File changes summary

| File | Change |
|---|---|
| `backend/app/services/lmstudio_client.py` | Add `chat_stream_with_tools()` method |
| `backend/app/api/library.py` | Add `POST /api/library/families/assist` endpoint |
| `backend/app/models/library.py` | Add `AssistRequest` pydantic model |
| `frontend/src/api/assist.ts` | New file — `streamAssist()` + types |
| `frontend/src/components/molecules/AssistantPane.tsx` | New file — chat sidebar component |
| `frontend/src/components/molecules/AssistantPane.module.css` | New file — sidebar-specific styles |
| `frontend/src/components/organisms/FamilyForm.tsx` | Add assistant sidebar toggle + layout |
| `frontend/src/components/organisms/libraryForm.module.css` | Add `.formWithAssistant` layout styles |

### Prerequisites

- LMStudio must have MCP/Playwright configured for URL fetching (document in README)
- User must select a model with `tool_use` capability for the assistant to work

## Future: mode-specific prompt guides

This spec implements a single `prompt_guide` field. A planned follow-up will split guidance into three fields:

- **`prompt_guide`** (base) — shared rules: tag syntax, quality tokens, LoRA patterns, negative prompt conventions
- **`prompt_i2i`** — i2i-specific additions: what to preserve from the source, transformation language, denoising guidance
- **`prompt_t2i`** — t2i-specific additions: full scene composition, subject description conventions

At generation time the system prompt will be assembled as `prompt_guide` + `prompt_i2i` or `prompt_guide` + `prompt_t2i` depending on the session mode. The assistant will be extended to work with all three fields via separate tool calls (`update_prompt_guide`, `update_prompt_i2i`, `update_prompt_t2i`).

This is a separate change requiring a DB migration, API updates, and form changes — not part of the current scope.
