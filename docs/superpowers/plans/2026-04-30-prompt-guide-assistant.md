# Prompt Guide Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an AI assistant sidebar to the family create/edit form that helps users collaboratively write prompt guides via chat, with automatic artifact updates to the form field.

**Architecture:** New stateless SSE endpoint on the backend proxies messages + tool definitions to LMStudio. A new `chat_stream_with_tools()` method in `lmstudio_client` handles OpenAI-compatible tool-call streaming. The frontend adds an `AssistantPane` component (reusing `ds-chat-*` styles) as a collapsible right sidebar in `FamilyForm`, with a `streamAssist()` API client that parses extended SSE events including `artifact` type.

**Tech Stack:** Python/FastAPI (backend), React/TypeScript (frontend), httpx (LLM proxy), Vitest (frontend tests), pytest (backend tests)

---

### Task 1: `chat_stream_with_tools()` in lmstudio_client

**Files:**
- Modify: `backend/app/services/lmstudio_client.py:175-217`
- Test: `backend/tests/test_lmstudio_client.py`

This method is like `chat_stream()` but accepts a `tools` parameter and yields structured event dicts instead of raw text strings. It must handle the OpenAI streaming format for tool calls: `delta.tool_calls[0].function.name` and `delta.tool_calls[0].function.arguments` accumulated across chunks.

- [ ] **Step 1: Write the failing test for text-only streaming with tools param**

In `backend/tests/test_lmstudio_client.py`, add:

```python
# --- chat_stream_with_tools ---

def _sse_lines(*events: str) -> str:
    return "".join(f"data: {e}\n\n" for e in events) + "data: [DONE]\n\n"


def _text_delta(content: str) -> str:
    return json.dumps({
        "choices": [{"delta": {"content": content}, "finish_reason": None}],
    })


def _tool_call_delta(*, name: str | None = None, arguments: str = "") -> str:
    tc: dict[str, Any] = {"index": 0, "function": {}}
    if name is not None:
        tc["id"] = "call_1"
        tc["type"] = "function"
        tc["function"]["name"] = name
    if arguments:
        tc["function"]["arguments"] = arguments
    return json.dumps({
        "choices": [{"delta": {"tool_calls": [tc]}, "finish_reason": None}],
    })


def test_chat_stream_with_tools_yields_text_deltas():
    body = _sse_lines(_text_delta("hello "), _text_delta("world"))

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert "tools" in payload
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    events = list(lmstudio_client.chat_stream_with_tools(
        endpoint=ENDPOINT,
        model="m",
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "noop", "parameters": {}}}],
        transport=_make_transport(handler),
    ))
    assert events == [
        {"type": "delta", "content": "hello "},
        {"type": "delta", "content": "world"},
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_lmstudio_client.py::test_chat_stream_with_tools_yields_text_deltas -v`
Expected: FAIL with `AttributeError: module 'app.services.lmstudio_client' has no attribute 'chat_stream_with_tools'`

- [ ] **Step 3: Implement `chat_stream_with_tools()`**

In `backend/app/services/lmstudio_client.py`, add after `chat_stream()` (after line 217):

```python
def chat_stream_with_tools(
    *,
    endpoint: dict[str, Any],
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    transport: httpx.BaseTransport | None = None,
) -> Iterator[dict[str, Any]]:
    if not model.strip():
        raise LmError("config", "model is required")
    if not messages:
        raise LmError("config", "messages must not be empty")
    server_root, headers = _resolve(endpoint)
    payload = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "stream": True,
    }
    tool_name = ""
    tool_args_buf: list[str] = []
    try:
        with httpx.Client(transport=transport, timeout=CHAT_TIMEOUT) as client:
            with client.stream(
                "POST", f"{server_root}/v1/chat/completions",
                headers=headers, json=payload,
            ) as resp:
                if resp.status_code >= 400:
                    body = resp.read().decode("utf-8", errors="replace")
                    raise LmError("upstream", f"{resp.status_code}: {body[:200]}")
                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except ValueError:
                        continue
                    try:
                        delta = chunk["choices"][0].get("delta") or {}
                    except (KeyError, IndexError, TypeError):
                        continue
                    content = delta.get("content")
                    if isinstance(content, str) and content:
                        yield {"type": "delta", "content": content}
                    tool_calls = delta.get("tool_calls")
                    if tool_calls:
                        tc = tool_calls[0]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            tool_name = fn["name"]
                        if fn.get("arguments"):
                            tool_args_buf.append(fn["arguments"])
        if tool_name and tool_args_buf:
            raw_args = "".join(tool_args_buf)
            try:
                parsed = json.loads(raw_args)
            except ValueError:
                raise LmError("shape", f"invalid tool call JSON: {raw_args[:200]}")
            yield {"type": "tool_call", "name": tool_name, "arguments": parsed}
    except httpx.TimeoutException as exc:
        raise LmError("timeout", str(exc)) from exc
    except httpx.HTTPError as exc:
        raise LmError("upstream", str(exc)) from exc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_lmstudio_client.py::test_chat_stream_with_tools_yields_text_deltas -v`
Expected: PASS

- [ ] **Step 5: Write the failing test for tool call streaming**

In `backend/tests/test_lmstudio_client.py`, add:

```python
def test_chat_stream_with_tools_yields_tool_call():
    body = _sse_lines(
        _text_delta("Here is the guide."),
        _tool_call_delta(name="update_prompt_guide", arguments='{"conte'),
        _tool_call_delta(arguments='nt": "the guide"}'),
    )

    def handler(r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    events = list(lmstudio_client.chat_stream_with_tools(
        endpoint=ENDPOINT,
        model="m",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        transport=_make_transport(handler),
    ))
    assert events == [
        {"type": "delta", "content": "Here is the guide."},
        {"type": "tool_call", "name": "update_prompt_guide", "arguments": {"content": "the guide"}},
    ]
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_lmstudio_client.py::test_chat_stream_with_tools_yields_tool_call -v`
Expected: PASS (implementation already handles this)

- [ ] **Step 7: Write test for upstream error**

In `backend/tests/test_lmstudio_client.py`, add:

```python
def test_chat_stream_with_tools_raises_on_upstream_error():
    transport = _make_transport(lambda r: httpx.Response(500, text="internal"))

    with pytest.raises(lmstudio_client.LmError) as exc:
        list(lmstudio_client.chat_stream_with_tools(
            endpoint=ENDPOINT,
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
            transport=transport,
        ))
    assert exc.value.kind == "upstream"
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_lmstudio_client.py::test_chat_stream_with_tools_raises_on_upstream_error -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/lmstudio_client.py backend/tests/test_lmstudio_client.py
git commit -m "feat(client): add chat_stream_with_tools() for tool-call streaming"
```

---

### Task 2: AssistRequest model + assist endpoint

**Files:**
- Modify: `backend/app/models/library.py`
- Modify: `backend/app/api/library.py`
- Test: `backend/tests/test_library_api.py`

- [ ] **Step 1: Add `AssistRequest` and `AssistMessage` pydantic models**

In `backend/app/models/library.py`, add at the end:

```python
class AssistMessage(StrictModel):
    role: str = Field(pattern=r"^(user|assistant)$")
    content: str = Field(min_length=1)


class AssistRequest(StrictModel):
    model: str = Field(min_length=1)
    messages: list[AssistMessage] = Field(min_length=1)
```

- [ ] **Step 2: Write the failing test for the assist endpoint**

In `backend/tests/test_library_api.py`, add:

```python
import json

from app.services import lmstudio_client


def test_assist_streams_text_and_artifact(client, conn):
    from app.storage import settings_repo
    settings_repo.set_lmstudio(conn, url="http://localhost:1234", api_key=None)
    settings_repo.upsert_lm_models(conn, models=[
        {"name": "tool-model", "vision": False, "tool_use": True, "reasoning": False},
    ])

    fake_events = [
        {"type": "delta", "content": "I'll write a guide."},
        {"type": "tool_call", "name": "update_prompt_guide", "arguments": {"content": "# Guide\nUse tags."}},
    ]

    def fake_stream(**kwargs):
        return iter(fake_events)

    import app.api.library as lib_mod
    original = lmstudio_client.chat_stream_with_tools
    lmstudio_client.chat_stream_with_tools = fake_stream
    try:
        resp = client.post(
            "/api/library/families/assist",
            json={
                "model": "tool-model",
                "messages": [{"role": "user", "content": "help me write a guide"}],
            },
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

        events = []
        for line in resp.text.strip().split("\n\n"):
            for part in line.split("\n"):
                if part.startswith("data:"):
                    events.append(json.loads(part[len("data:"):].strip()))

        types = [e["type"] for e in events]
        assert "delta" in types
        assert "artifact" in types
        assert "done" in types

        artifact = next(e for e in events if e["type"] == "artifact")
        assert artifact["content"] == "# Guide\nUse tags."
    finally:
        lmstudio_client.chat_stream_with_tools = original
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_library_api.py::test_assist_streams_text_and_artifact -v`
Expected: FAIL with 404 (endpoint doesn't exist yet)

- [ ] **Step 4: Implement the assist endpoint**

In `backend/app/api/library.py`, add the following imports at the top:

```python
import json
from starlette.responses import StreamingResponse
from app.models.library import AssistRequest
from app.storage import settings_repo
```

Then add the endpoint before the models section:

```python
ASSIST_SYSTEM_PROMPT = (
    "You are a prompt-guide writing assistant for generative image model families. "
    "Help the user write a prompt guide — a set of rules that the LLM will follow "
    "when generating prompts for this family in both text-to-image (t2i) and "
    "image-to-image (i2i) workflows.\n\n"
    "You have a tool `update_prompt_guide` — call it whenever you have a draft or "
    "update of the prompt guide. The user will see the result in real-time in the editor.\n\n"
    "When the user provides documentation links, read them using your MCP tools and "
    "extract relevant information about the model's prompting style, supported tags, "
    "quality tokens, and any family-specific syntax.\n\n"
    "Keep the prompt guide concise and actionable. Focus on:\n"
    "- Tag syntax and formatting rules\n"
    "- Quality/style tokens specific to this family\n"
    "- Token limits or recommendations\n"
    "- LoRA interaction patterns\n"
    "- Negative prompt conventions\n"
    "- Any differences between t2i and i2i prompting for this family"
)

ASSIST_TOOLS = [
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
                        "description": "The full prompt guide markdown content",
                    },
                },
                "required": ["content"],
            },
        },
    },
]


def _assist_sse(payload: dict) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


@router.post("/families/assist")
def assist(body: AssistRequest, conn: Conn) -> StreamingResponse:
    cfg = settings_repo.get_lmstudio(conn)
    if not cfg["lmstudio_url"]:
        raise HTTPException(status_code=409, detail="LMStudio base_url is not configured")

    row = settings_repo.get_lm_model(conn, body.model)
    if row is None or not row["enabled"]:
        raise HTTPException(status_code=409, detail=f"model {body.model!r} is not enabled")
    if not row["tool_use"]:
        raise HTTPException(status_code=409, detail=f"model {body.model!r} does not support tool use")

    endpoint = {
        "server_root": cfg["lmstudio_url"],
        "api_key": cfg["lmstudio_api_key"],
    }
    payload_messages: list[dict] = [{"role": "system", "content": ASSIST_SYSTEM_PROMPT}]
    for m in body.messages:
        payload_messages.append({"role": m.role, "content": m.content})

    def gen():
        try:
            for event in lmstudio_client.chat_stream_with_tools(
                endpoint=endpoint,
                model=body.model,
                messages=payload_messages,
                tools=ASSIST_TOOLS,
            ):
                if event["type"] == "delta":
                    yield _assist_sse({"type": "delta", "content": event["content"]})
                elif event["type"] == "tool_call" and event["name"] == "update_prompt_guide":
                    content = event["arguments"].get("content", "")
                    yield _assist_sse({"type": "artifact", "content": content})
        except lmstudio_client.LmError as exc:
            yield _assist_sse({"type": "error", "detail": str(exc)})
            return
        yield _assist_sse({"type": "done"})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
```

**Important:** This endpoint must be registered BEFORE the `/families/{family_id}` routes in the file so FastAPI doesn't match `assist` as a `family_id`. Place it right after the `create_family` endpoint (after line 63).

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_library_api.py::test_assist_streams_text_and_artifact -v`
Expected: PASS

- [ ] **Step 6: Write test for validation — model without tool_use rejected**

In `backend/tests/test_library_api.py`, add:

```python
def test_assist_rejects_model_without_tool_use(client, conn):
    from app.storage import settings_repo
    settings_repo.set_lmstudio(conn, url="http://localhost:1234", api_key=None)
    settings_repo.upsert_lm_models(conn, models=[
        {"name": "no-tools", "vision": False, "tool_use": False, "reasoning": False},
    ])

    resp = client.post(
        "/api/library/families/assist",
        json={
            "model": "no-tools",
            "messages": [{"role": "user", "content": "help"}],
        },
    )
    assert resp.status_code == 409
    assert "tool use" in resp.json()["detail"]
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_library_api.py::test_assist_rejects_model_without_tool_use -v`
Expected: PASS

- [ ] **Step 8: Run full backend test suite**

Run: `cd backend && uv run pytest -x -q`
Expected: All tests pass

- [ ] **Step 9: Commit**

```bash
git add backend/app/models/library.py backend/app/api/library.py backend/tests/test_library_api.py
git commit -m "feat(api): add POST /api/library/families/assist SSE endpoint"
```

---

### Task 3: Frontend API client — `streamAssist()`

**Files:**
- Create: `frontend/src/api/assist.ts`

- [ ] **Step 1: Create `frontend/src/api/assist.ts`**

```typescript
import { API_BASE, ApiError } from "./client";

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
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/library/families/assist`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ model, messages }),
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
      else if (evt.type === "artifact") cb.onArtifact(evt.content);
      else if (evt.type === "done") cb.onDone();
      else if (evt.type === "error") cb.onError(evt.detail);
    }
  }
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/assist.ts
git commit -m "feat(api): add streamAssist() SSE client for assistant"
```

---

### Task 4: AssistantPane component

**Files:**
- Create: `frontend/src/components/molecules/AssistantPane.tsx`
- Create: `frontend/src/components/molecules/AssistantPane.module.css`

- [ ] **Step 1: Create `frontend/src/components/molecules/AssistantPane.module.css`**

```css
.pane {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg);
  overflow: hidden;
  border-left: 1px solid var(--border);
  width: 380px;
  flex-shrink: 0;
}

.head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  height: 38px;
  box-sizing: border-box;
  background: var(--bg);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.title {
  font-family: var(--font-ui);
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-subtle);
}

.spacer {
  flex: 1;
  min-width: 0;
}

.modelSelect {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-subtle);
  background: var(--bg-raised);
  border: 1px solid var(--border);
  border-radius: var(--r-xs);
  padding: 2px 6px;
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.scroll {
  flex: 1;
  overflow-y: auto;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.empty {
  padding: 24px 8px;
  text-align: center;
  color: var(--text-subtle);
  font-size: 12.5px;
  line-height: 1.6;
}

.error {
  margin: 0 18px 8px;
  padding: 8px 10px;
  background: color-mix(in oklab, var(--danger, #c33) 8%, transparent);
  border: 1px solid color-mix(in oklab, var(--danger, #c33) 30%, var(--border));
  border-radius: var(--r-xs);
  color: var(--danger, #c33);
  font-size: 12px;
}

.composer {
  border-top: 1px solid var(--border);
  padding: 10px 12px 12px;
  background: var(--bg);
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
}

.textarea {
  width: 100%;
  min-height: 56px;
  max-height: 160px;
  resize: none;
  border: 1px solid var(--border);
  background: var(--bg-raised);
  border-radius: var(--r-sm);
  padding: 8px 10px;
  font-family: var(--font-ui);
  font-size: 13px;
  color: var(--text);
  outline: none;
  box-sizing: border-box;
}

.textarea:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px color-mix(in oklab, var(--accent) 18%, transparent);
}

.textarea:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.composerRow {
  display: flex;
  align-items: center;
  gap: 6px;
}

.hint {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-subtle);
}

.msgContent {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text);
  white-space: pre-wrap;
  word-wrap: break-word;
}

.typing {
  display: inline-flex;
  gap: 3px;
  padding: 4px 8px;
  background: var(--accent-subtle);
  border-radius: var(--r-full);
}

.typing span {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--accent);
  animation: typing-bounce 1.2s infinite ease-in-out;
}

.typing span:nth-child(2) { animation-delay: 0.15s; }
.typing span:nth-child(3) { animation-delay: 0.3s; }

@keyframes typing-bounce {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.5; }
  30% { transform: translateY(-3px); opacity: 1; }
}
```

- [ ] **Step 2: Create `frontend/src/components/molecules/AssistantPane.tsx`**

```tsx
import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { streamAssist, type AssistantMessage } from "@/api/assist";
import { useLmModels } from "@/api/settings";
import styles from "./AssistantPane.module.css";

const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPod|iPad/i.test(navigator.platform);
const SEND_HINT = isMac ? "⌘↵ to send" : "Ctrl↵ to send";

export function AssistantPane({
  onArtifact,
}: {
  onArtifact: (content: string) => void;
}) {
  const allModels = useLmModels();
  const toolModels = useMemo(
    () => (allModels.data ?? []).filter((m) => m.enabled && m.tool_use),
    [allModels.data],
  );

  const [model, setModel] = useState("");
  const [messages, setMessages] = useState<AssistantMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [streaming, setStreaming] = useState("");
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!model && toolModels.length > 0) {
      setModel(toolModels[0].name);
    }
  }, [model, toolModels]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight });
  }, [messages.length, streaming]);

  async function send() {
    const content = draft.trim();
    if (!content || pending || !model) return;

    const userMsg: AssistantMessage = { role: "user", content };
    const updated = [...messages, userMsg];
    setMessages(updated);
    setDraft("");
    setStreaming("");
    setError(null);
    setPending(true);

    let assistantText = "";
    try {
      await streamAssist(model, updated, {
        onDelta: (chunk) => {
          assistantText += chunk;
          setStreaming(assistantText);
        },
        onArtifact: (artifactContent) => {
          onArtifact(artifactContent);
        },
        onDone: () => {},
        onError: (detail) => setError(detail),
      });
    } catch (err) {
      setError(String(err));
    } finally {
      if (assistantText) {
        setMessages((prev) => [...prev, { role: "assistant", content: assistantText }]);
      }
      setPending(false);
      setStreaming("");
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      void send();
    }
  }

  const showThinking = pending && streaming.length === 0;
  const showStreaming = pending && streaming.length > 0;

  return (
    <div className={styles.pane}>
      <div className={styles.head}>
        <span className={styles.title}>Assistant</span>
        <div className={styles.spacer} />
        <select
          className={styles.modelSelect}
          value={model}
          onChange={(e) => setModel(e.target.value)}
          disabled={pending}
        >
          {toolModels.length === 0 && <option value="">No tool_use models</option>}
          {toolModels.map((m) => (
            <option key={m.name} value={m.name}>{m.name}</option>
          ))}
        </select>
      </div>
      <div className={styles.body}>
        <div className={styles.scroll} ref={scrollRef}>
          {messages.length === 0 && !showThinking && !showStreaming && (
            <div className={styles.empty}>
              Paste documentation or describe the model family to get started.
            </div>
          )}
          {messages.map((m, i) => (
            <Bubble key={i} role={m.role} content={m.content} />
          ))}
          {showStreaming && <Bubble role="assistant" content={streaming} streaming />}
          {showThinking && <ThinkingBubble />}
        </div>
        {error && <div className={styles.error} role="alert">{error}</div>}
        <div className={styles.composer}>
          <textarea
            className={styles.textarea}
            placeholder="Describe the family or paste docs…"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            disabled={pending}
          />
          <div className={styles.composerRow}>
            <span className={styles.hint}>{SEND_HINT}</span>
            <div className={styles.spacer} />
            <Button
              size="sm"
              variant="primary"
              icon={<Icon name="Send" size={12} />}
              onClick={() => void send()}
              disabled={pending || draft.trim().length === 0 || !model}
            >
              {pending ? "Sending…" : "Send"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Bubble({
  role,
  content,
  streaming = false,
}: {
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
}) {
  const variantClass = role === "user" ? "ds-chat-user" : "ds-chat-assistant";
  return (
    <div className={`ds-chat ${variantClass}`}>
      {role !== "user" && (
        <div className="ds-chat-avatar" aria-hidden="true">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M3 11L7 3L11 11L7 8.5L3 11Z" fill="currentColor" />
          </svg>
        </div>
      )}
      <div className="ds-chat-body">
        <div className="ds-chat-meta">
          {role === "user" ? "You" : "Assistant"}
        </div>
        <div className={styles.msgContent}>
          {content}
          {streaming && <span className="ds-chat-cursor" />}
        </div>
      </div>
    </div>
  );
}

function ThinkingBubble() {
  return (
    <div className="ds-chat ds-chat-assistant">
      <div className="ds-chat-avatar" aria-hidden="true">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <path d="M3 11L7 3L11 11L7 8.5L3 11Z" fill="currentColor" />
        </svg>
      </div>
      <div className="ds-chat-body">
        <div className="ds-chat-meta">Assistant · thinking</div>
        <div className={styles.typing}>
          <span /><span /><span />
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/molecules/AssistantPane.tsx frontend/src/components/molecules/AssistantPane.module.css
git commit -m "feat(ui): add AssistantPane chat sidebar component"
```

---

### Task 5: Integrate AssistantPane into FamilyForm

**Files:**
- Modify: `frontend/src/components/organisms/FamilyForm.tsx`
- Modify: `frontend/src/components/organisms/libraryForm.module.css`

- [ ] **Step 1: Add layout styles for the assistant sidebar**

In `frontend/src/components/organisms/libraryForm.module.css`, add before the `@media` query (before line 169):

```css
.formWithAssistant {
  display: flex;
  height: 100%;
  min-height: 0;
}

.formMain {
  flex: 1;
  min-width: 0;
  height: 100%;
  min-height: 0;
}
```

- [ ] **Step 2: Update FamilyForm to include assistant toggle and sidebar**

Replace the full content of `frontend/src/components/organisms/FamilyForm.tsx` with:

```tsx
import { useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { TextInput } from "@/components/molecules/FormField";
import { LibraryFormPage, LibraryFormSection } from "@/components/organisms/LibraryFormSection";
import libForm from "@/components/organisms/libraryForm.module.css";
import { MarkdownField } from "@/components/molecules/MarkdownField";
import { AssistantPane } from "@/components/molecules/AssistantPane";
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
  const [showAssistant, setShowAssistant] = useState(false);

  const isEdit = Boolean(family);
  const pageTitle = isEdit && family ? `Edit · ${family.display_name}` : "New family";

  const canSave = displayName.trim() !== "" && promptGuide.trim() !== "" && (Boolean(family) || id.trim() !== "");

  const form = (
    <form
      className={showAssistant ? libForm.formMain : libForm.formShell}
      onSubmit={(event) => {
        event.preventDefault();
        if (!canSave) return;
        const common = { display_name: displayName.trim(), prompt_guide: promptGuide.trim() };
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
            <span className={libForm.breadcrumbCurrent}>{isEdit ? family?.display_name : "New family"}</span>
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
          title="Prompt guide"
          subtitle="Base rules for this family. LLM sees this in every session."
        >
          <MarkdownField
            label="Content"
            value={promptGuide}
            onChange={setPromptGuide}
            hint="Syntax, quality tags, token style, and how LoRAs interact."
          />
        </LibraryFormSection>
      </LibraryFormPage>
    </form>
  );

  if (!showAssistant) return form;

  return (
    <div className={libForm.formWithAssistant}>
      {form}
      <AssistantPane onArtifact={setPromptGuide} />
    </div>
  );
}
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/organisms/FamilyForm.tsx frontend/src/components/organisms/libraryForm.module.css
git commit -m "feat(ui): integrate AssistantPane sidebar into FamilyForm"
```

---

### Task 6: Frontend test for AssistantPane

**Files:**
- Create: `frontend/src/components/molecules/AssistantPane.test.tsx`

- [ ] **Step 1: Create the test file**

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AssistantPane } from "./AssistantPane";

function makeStreamResponse(events: string[]) {
  const enc = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const e of events) controller.enqueue(enc.encode(e));
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "content-type": "text/event-stream" },
  });
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function withClient(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{ui}</QueryClientProvider>;
}

const MODELS_RESPONSE = {
  models: [
    { name: "tool-model", vision: false, tool_use: true, reasoning: false, enabled: true, last_seen: 1 },
    { name: "no-tools", vision: false, tool_use: false, reasoning: false, enabled: true, last_seen: 1 },
  ],
};

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AssistantPane", () => {
  it("renders empty state and model selector with tool_use models only", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.includes("/lmstudio/models")) return jsonResponse(MODELS_RESPONSE);
      throw new Error(`unexpected fetch: ${url}`);
    }));

    const onArtifact = vi.fn();
    render(withClient(<AssistantPane onArtifact={onArtifact} />));

    await waitFor(() => expect(screen.getByText(/paste documentation/i)).toBeInTheDocument());
    const select = screen.getByRole("combobox");
    const options = Array.from(select.querySelectorAll("option"));
    expect(options.map((o) => o.value)).toEqual(["tool-model"]);
  });

  it("sends message and calls onArtifact when artifact event received", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.includes("/lmstudio/models")) return jsonResponse(MODELS_RESPONSE);
      if (url.includes("/families/assist") && init?.method === "POST") {
        return makeStreamResponse([
          'data: {"type":"delta","content":"Here is a guide."}\n\n',
          'data: {"type":"artifact","content":"# My Guide"}\n\n',
          'data: {"type":"done"}\n\n',
        ]);
      }
      throw new Error(`unexpected fetch: ${url}`);
    }));

    const onArtifact = vi.fn();
    render(withClient(<AssistantPane onArtifact={onArtifact} />));

    const input = await screen.findByRole("textbox");
    await userEvent.type(input, "help me");
    await userEvent.click(screen.getByRole("button", { name: /^send$/i }));

    await waitFor(() => expect(onArtifact).toHaveBeenCalledWith("# My Guide"));
    await waitFor(() => expect(screen.getByText(/here is a guide/i)).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run tests**

Run: `cd frontend && npx vitest run src/components/molecules/AssistantPane.test.tsx`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/molecules/AssistantPane.test.tsx
git commit -m "test: add AssistantPane component tests"
```

---

### Task 7: Verify end-to-end in browser

**Files:** None (manual verification)

- [ ] **Step 1: Start backend**

Run: `cd backend && uv run uvicorn app.main:app --reload --port 8000`

- [ ] **Step 2: Start frontend**

Run: `cd frontend && pnpm dev`

- [ ] **Step 3: Open browser and verify**

Navigate to `http://localhost:5173/library/families/new`. Verify:
1. The form renders normally (ID, Display name, Prompt guide fields)
2. There is an "Assistant" button in the footer
3. Clicking it opens the right sidebar with the chat
4. The model selector shows only `tool_use`-capable models
5. Clicking "Hide assistant" closes the sidebar
6. If LMStudio is running with a tool_use model: type a message, send it, verify streaming works and artifact updates the prompt guide field

- [ ] **Step 4: Run full test suites**

Run: `cd backend && uv run pytest -x -q`
Run: `cd frontend && npx vitest run`
Run: `cd frontend && npx tsc --noEmit`
Expected: All pass

- [ ] **Step 5: Commit any fixes from verification**

If any fixes were needed, commit them with descriptive messages.
