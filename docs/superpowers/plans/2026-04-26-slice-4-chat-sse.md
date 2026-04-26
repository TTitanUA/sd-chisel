# Slice 4 — Chat SSE — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every session a streaming chat that reuses the global LMStudio config and the per-session `prompt_model_name`. User sees assistant tokens appear as they arrive, full message history persists in `messages`, and reload restores the conversation. The Generate-prompt button is rendered but disabled with a "Slice 6" hint — chat itself never calls generate-prompt.

**Architecture:** One new FastAPI router (`app/api/chat.py`) with two endpoints — `GET /api/sessions/{id}/messages` and `POST /api/sessions/{id}/chat` (SSE). Streaming is plain `StreamingResponse` with manual `data: ...\n\n` framing — no new dependency; if Windows uvicorn buffering bites, the fallback (switch to `sse-starlette.EventSourceResponse`) is a one-line change documented at the bottom. The user message is INSERTed before opening the upstream stream so it survives mid-stream failures; the assistant message is INSERTed only after the upstream stream completes successfully. Upstream calls go through one new `lm_client.chat_stream` generator that yields content deltas, mirroring the existing `analyze_image` shape and error handling. Frontend uses `fetch` (not `EventSource`, because we POST a body) and parses SSE manually into a local "live token buffer" that snaps to canonical history on `done`.

**Tech Stack:** Python 3.11+, FastAPI `StreamingResponse`, Pydantic v2, `httpx` streaming (`client.stream(...)`), pytest/TestClient with monkeypatched `lm_client`; React 18, TypeScript, TanStack Query v5, native `fetch` ReadableStream, Vitest + RTL.

**Reference docs checked while writing this plan:**
- Roadmap §4 Slice 4 (boundaries, acceptance, handoff): `docs/superpowers/specs/2026-04-23-mvp-roadmap-design.md`
- Spec §3 (`messages` schema), §4.3 (chat is plain SSE; does NOT call generate-prompt), §4.5 (system-prompt skeleton): `docs/spec/technical_specifications.md`
- Slice-3 plan structure / conventions / test patterns: `docs/superpowers/plans/2026-04-25-slice-3-settings-and-vl.md`
- Existing `lm_client` and `sessions.analyze_source` for endpoint config / error translation pattern: `backend/app/services/lm_client.py`, `backend/app/api/sessions.py:241-296`

---

## Pre-flight: state at start of slice

After Slice 3 the codebase has:

- `messages` table (created in `001_init.sql:79-86`) plus `session_repo.append_message(...)` and `session_repo.list_messages(...)` (`backend/app/storage/session_repo.py:258-275`). Slice 4 only consumes them — no schema change.
- `app_settings` row (singleton) with `lmstudio_base_url` / `lmstudio_api_key` (slice 3, migration `003_settings.sql`); `settings_repo.get_lmstudio(conn)` returns the row dict.
- `lm_models` cache table; `settings_repo.get_lm_model(conn, name)` returns `{name, role, enabled, last_seen}` or `None`.
- `sessions.prompt_model_name TEXT` column (slice 3); already PATCH-able through `session_repo.update_session(...)`. SessionOut already exposes it.
- `app/services/lm_client.py` with `_resolve(endpoint)`, `_request(...)`, `list_models(...)`, `analyze_image(...)`, and an `LmError` class with kinds `upstream | timeout | shape | config`. Slice 4 ADDS one method — `chat_stream(...)` — alongside.
- `app/api/sessions.py` has `_validated_vl_model(conn, name)` (`sessions.py:241-253`). Slice 4 introduces the symmetric `_validated_prompt_model` in the new `chat.py` router (do NOT move the VL one — duplicate is fine, two callers, two roles).
- Frontend: `Session.prompt_model_name` already on the type; `SessionSettingsDrawer` already has the prompt-model dropdown (slice 3). `routes/workspace.tsx:68` is the placeholder line `<div className={styles.placeholder}>Chat pane · coming in Slice 4</div>` — that's where `<ChatPane>` goes.
- Frontend: `apiFetch` (`frontend/src/api/client.ts`) is JSON-only and not suitable for streaming — Slice 4 uses raw `fetch` for `/chat`, `apiFetch` for `/messages`.
- No existing chat code on the frontend — no `api/chat.ts`, no `ChatPane`, no chat-related store or query keys.

These are the assumed inputs; do not pre-implement them.

---

## File Structure

Create or modify only the files below.

```
backend/
├── app/
│   ├── api/
│   │   └── chat.py                          # NEW — /api/sessions/{id}/messages, /chat (SSE)
│   ├── main.py                              # include chat router
│   ├── models/
│   │   └── chat.py                          # NEW — ChatRequest, MessageOut
│   └── services/
│       └── lm_client.py                     # extend: chat_stream() + _CHAT_TIMEOUT
└── tests/
    ├── test_lm_client_chat.py               # NEW — chat_stream wire format + errors
    └── test_chat_api.py                     # NEW — /messages + /chat endpoints

frontend/
└── src/
    ├── api/
    │   └── chat.ts                          # NEW — types, listMessages, streamChat, hooks
    ├── components/
    │   └── molecules/
    │       ├── ChatPane.tsx                 # NEW
    │       ├── ChatPane.module.css          # NEW
    │       └── ChatPane.test.tsx            # NEW
    └── routes/
        └── workspace.tsx                    # replace placeholder with <ChatPane />
```

No DS-token changes. No new shared atoms. No new migration. No backend dependency additions.

---

## API Contract (delta vs Slice 3)

```
GET    /api/sessions/{session_id}/messages
    -> { messages: MessageOut[] }            # ordered by created_at, id ASC
    404 — session not found

POST   /api/sessions/{session_id}/chat
    body: { content: string }                # min length 1, max length 8000 after strip
    response: text/event-stream
        event 1..N:  data: {"type":"delta","content":"<chunk>"}\n\n
        final:       data: {"type":"done","message_id":<int>}\n\n
        on error:    data: {"type":"error","detail":"<msg>"}\n\n   then close
    409 — no LMStudio config / no prompt_model_name on session / model disabled or wrong role
    404 — session not found
    422 — empty content
    The user message is persisted (synchronously, before the stream opens) regardless of
    upstream success. The assistant message is persisted only after a successful stream.
```

Types:

```ts
type MessageOut = {
  id: number;
  session_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: number;
};

type ChatStreamEvent =
  | { type: "delta"; content: string }
  | { type: "done"; message_id: number }
  | { type: "error"; detail: string };
```

No other endpoint shapes change.

---

## Cross-cutting design notes

- **Context window.** Each request builds the upstream payload as: a fixed system prompt (chat-mode), then an optional `# Source image analysis\n{vl_summary}` system message if `session.vl_summary` is non-empty, then up to **30** most-recent prior messages (chronological), then the new user message. Constant: `CHAT_HISTORY_LIMIT = 30`. No retrieval, no LoRA context, no prompt composition — that is Slice 6.
- **Persistence rules.** User message INSERT happens before opening the upstream stream. If the upstream call fails before any delta arrives, we still emit a single `{"type":"error", "detail":...}` event and close — the user message stays in DB so they don't lose what they typed. Assistant message INSERT happens once after the upstream stream completes, with the full accumulated content. If the stream errors mid-flight (after deltas), we emit the `error` event and do NOT save a partial assistant message — Slice 4 keeps assistant rows clean. `session_repo.append_message` does not bump `session.updated_at`; matching slice-3 behavior, that's fine for now (the session list ordering picks up the next time anything else PATCHes the session).
- **SSE framing.** Plain FastAPI `StreamingResponse(media_type="text/event-stream")`. Each event is `data: <json>\n\n` (the leading `data:` and the trailing blank line are required by the SSE spec). No `event:` field — we discriminate via the JSON `type`. Headers include `X-Accel-Buffering: no` and `Cache-Control: no-cache` to suppress proxy buffering. Roadmap §5 calls out Windows uvicorn buffering as a risk; Task 8 is a manual smoke that verifies tokens trickle in and not all-at-once.
- **Why fetch and not EventSource on the frontend.** `EventSource` is GET-only and re-connects on close — neither fits a one-shot POST chat turn. We use `fetch` + `body.getReader()` + a tiny SSE line parser. This is the same pattern OpenAI's web client uses.
- **Why no openai SDK.** Same reasoning as Slice 3 — two methods, raw httpx is small and fully testable via `MockTransport`. The streaming branch reads `response.iter_lines()` and parses LMStudio's OpenAI-compatible `data: {...}` lines.

---

## Task 1 — Pydantic schemas for chat

**Files:**
- Create: `backend/app/models/chat.py`
- Test: `backend/tests/test_chat_api.py` (new file; first test in it)

- [ ] **Step 1: Write the failing schema test**

Create `backend/tests/test_chat_api.py` with:

```python
import pytest
from pydantic import ValidationError

from app.models.chat import ChatRequest, MessageOut


def test_chat_request_strips_and_rejects_empty():
    assert ChatRequest(content="  hi  ").content == "hi"
    with pytest.raises(ValidationError):
        ChatRequest(content="   ")
    with pytest.raises(ValidationError):
        ChatRequest(content="")


def test_chat_request_rejects_oversize():
    with pytest.raises(ValidationError):
        ChatRequest(content="x" * 8001)


def test_message_out_round_trip():
    m = MessageOut(id=1, session_id="s", role="user", content="hi", created_at=10)
    assert m.model_dump() == {
        "id": 1, "session_id": "s", "role": "user", "content": "hi", "created_at": 10,
    }
```

- [ ] **Step 2: Run test to verify failure**

From `backend/`:
```bash
pytest tests/test_chat_api.py::test_chat_request_strips_and_rejects_empty -v
```
Expected: `ModuleNotFoundError: No module named 'app.models.chat'`.

- [ ] **Step 3: Implement the schemas**

Create `backend/app/models/chat.py`:

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatRequest(StrictModel):
    content: str = Field(min_length=1, max_length=8000)

    @field_validator("content")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("content must not be blank")
        return stripped


class MessageOut(StrictModel):
    id: int
    session_id: str
    role: Literal["user", "assistant", "system"]
    content: str
    created_at: int
```

- [ ] **Step 4: Run schema tests to verify pass**

```bash
pytest tests/test_chat_api.py -v -k "ChatRequest or MessageOut or chat_request or message_out"
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/chat.py backend/tests/test_chat_api.py
git commit -m "feat(chat): pydantic schemas for chat request/message"
```

---

## Task 2 — `lm_client.chat_stream` with httpx streaming

**Files:**
- Modify: `backend/app/services/lm_client.py`
- Create: `backend/tests/test_lm_client_chat.py`

- [ ] **Step 1: Write the failing wire-format test**

Create `backend/tests/test_lm_client_chat.py`:

```python
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.services import lm_client


def _sse_bytes(events: list[dict[str, Any] | str]) -> bytes:
    """Serialize a list of OpenAI-style SSE chat-completion chunks to wire bytes."""
    out: list[str] = []
    for ev in events:
        payload = ev if isinstance(ev, str) else json.dumps(ev)
        out.append(f"data: {payload}\n\n")
    return "".join(out).encode()


def _stream_response(events: list[dict[str, Any] | str]) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=_sse_bytes(events),
    )


def test_chat_stream_yields_content_deltas_until_done():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return _stream_response([
            {"choices": [{"delta": {"content": "Hel"}}]},
            {"choices": [{"delta": {"content": "lo"}}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            "[DONE]",
        ])

    chunks = list(lm_client.chat_stream(
        endpoint={"base_url": "http://h/v1", "api_key": "k"},
        model="m",
        messages=[{"role": "user", "content": "hi"}],
        transport=httpx.MockTransport(handler),
    ))
    assert chunks == ["Hel", "lo"]
    assert captured["url"] == "http://h/v1/chat/completions"
    assert captured["body"]["model"] == "m"
    assert captured["body"]["stream"] is True
    assert captured["body"]["messages"] == [{"role": "user", "content": "hi"}]


def test_chat_stream_skips_non_content_deltas():
    def handler(_request: httpx.Request) -> httpx.Response:
        return _stream_response([
            {"choices": [{"delta": {"role": "assistant"}}]},   # role-only first chunk
            {"choices": [{"delta": {"content": "ok"}}]},
            "[DONE]",
        ])

    chunks = list(lm_client.chat_stream(
        endpoint={"base_url": "http://h/v1", "api_key": None},
        model="m", messages=[{"role": "user", "content": "x"}],
        transport=httpx.MockTransport(handler),
    ))
    assert chunks == ["ok"]


def test_chat_stream_raises_lm_error_on_non_2xx():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="busy")

    with pytest.raises(lm_client.LmError) as exc:
        list(lm_client.chat_stream(
            endpoint={"base_url": "http://h/v1", "api_key": None},
            model="m", messages=[{"role": "user", "content": "x"}],
            transport=httpx.MockTransport(handler),
        ))
    assert exc.value.kind == "upstream"


def test_chat_stream_raises_lm_error_on_timeout():
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with pytest.raises(lm_client.LmError) as exc:
        list(lm_client.chat_stream(
            endpoint={"base_url": "http://h/v1", "api_key": None},
            model="m", messages=[{"role": "user", "content": "x"}],
            transport=httpx.MockTransport(handler),
        ))
    assert exc.value.kind == "timeout"


def test_chat_stream_ignores_garbage_lines():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=(
                b": ping comment\n\n"
                b"data: {not json\n\n"
                b'data: {"choices": [{"delta": {"content": "ok"}}]}\n\n'
                b"data: [DONE]\n\n"
            ),
        )

    chunks = list(lm_client.chat_stream(
        endpoint={"base_url": "http://h/v1", "api_key": None},
        model="m", messages=[{"role": "user", "content": "x"}],
        transport=httpx.MockTransport(handler),
    ))
    assert chunks == ["ok"]
```

- [ ] **Step 2: Run tests to verify failure**

From `backend/`:
```bash
pytest tests/test_lm_client_chat.py -v
```
Expected: `AttributeError: module 'app.services.lm_client' has no attribute 'chat_stream'` on every test.

- [ ] **Step 3: Implement `chat_stream`**

In `backend/app/services/lm_client.py`, ABOVE the existing `def list_models(...)` add:

```python
CHAT_TIMEOUT = httpx.Timeout(120.0, connect=5.0, read=120.0)
```

Then APPEND at the end of the file:

```python
def chat_stream(
    *,
    endpoint: dict[str, Any],
    model: str,
    messages: list[dict[str, Any]],
    transport: httpx.BaseTransport | None = None,
) -> Iterator[str]:
    """Yield assistant content chunks from an OpenAI-compatible streaming chat.

    Connects to ``{base_url}/chat/completions`` with ``stream=true``, parses
    Server-Sent Events line by line, and yields the ``choices[0].delta.content``
    string of each chunk that has one. The terminal ``data: [DONE]`` line ends
    iteration. Lines that aren't JSON or that have no content delta are
    skipped silently — LMStudio occasionally emits role-only or
    finish_reason-only chunks at the boundaries.
    """
    if not model.strip():
        raise LmError("config", "model is required")
    base_url, headers = _resolve(endpoint)
    payload = {"model": model, "messages": messages, "stream": True}
    try:
        with httpx.Client(transport=transport, timeout=CHAT_TIMEOUT) as client:
            with client.stream(
                "POST", f"{base_url}/chat/completions",
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
                        return
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
                        yield content
    except httpx.TimeoutException as exc:
        raise LmError("timeout", str(exc)) from exc
    except httpx.HTTPError as exc:
        raise LmError("upstream", str(exc)) from exc
```

Add `import json` and `from collections.abc import Iterator` to the imports if missing (`json` is used in the new branch, `Iterator` in the return type).

- [ ] **Step 4: Run streaming tests to verify pass**

```bash
pytest tests/test_lm_client_chat.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Run full lm_client suite to confirm no regression**

```bash
pytest tests/test_lm_client.py tests/test_lm_client_chat.py -v
```
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/lm_client.py backend/tests/test_lm_client_chat.py
git commit -m "feat(lm_client): add chat_stream generator with SSE parsing"
```

---

## Task 3 — Chat router skeleton + `/messages` endpoint

**Files:**
- Create: `backend/app/api/chat.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_chat_api.py` (extend)

- [ ] **Step 1: Write the failing /messages tests**

Append to `backend/tests/test_chat_api.py`:

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
    c = db_mod.connect(tmp_path / "chat.db")
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


def _make_session(client) -> str:
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    return client.post(
        f"/api/projects/{pid}/sessions",
        json={"name": "s", "model_name": None, "use_negative": True},
    ).json()["id"]


def test_messages_empty_for_fresh_session(client):
    sid = _make_session(client)
    resp = client.get(f"/api/sessions/{sid}/messages")
    assert resp.status_code == 200
    assert resp.json() == {"messages": []}


def test_messages_404_when_session_missing(client):
    assert client.get("/api/sessions/missing/messages").status_code == 404


def test_messages_returned_in_chronological_order(client, conn):
    from app.storage import session_repo
    sid = _make_session(client)
    session_repo.append_message(conn, session_id=sid, role="user", content="first")
    session_repo.append_message(conn, session_id=sid, role="assistant", content="second")

    body = client.get(f"/api/sessions/{sid}/messages").json()
    assert [m["content"] for m in body["messages"]] == ["first", "second"]
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][1]["role"] == "assistant"
```

- [ ] **Step 2: Run tests to verify failure**

```bash
pytest tests/test_chat_api.py -v -k "messages"
```
Expected: `404` on every request because the router isn't mounted yet (`Not Found` on `/api/sessions/.../messages`). One test will pass accidentally (`test_messages_404_when_session_missing`) — that's fine, it's still meaningful once the route exists; the other two must fail.

- [ ] **Step 3: Implement the chat router with `/messages` only**

Create `backend/app/api/chat.py`:

```python
from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_conn
from app.models.chat import MessageOut
from app.storage import session_repo

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

router = APIRouter(tags=["chat"])


def _not_found(session_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"session not found: {session_id}",
    )


@router.get("/api/sessions/{session_id}/messages")
def list_messages(session_id: str, conn: Conn) -> dict:
    if session_repo.get_session(conn, session_id) is None:
        raise _not_found(session_id)
    rows = session_repo.list_messages(conn, session_id=session_id)
    return {"messages": [MessageOut(**r).model_dump() for r in rows]}
```

- [ ] **Step 4: Mount the router in `main.py`**

In `backend/app/main.py`:

- Add `from app.api.chat import router as chat_router` next to the other router imports.
- Add `app.include_router(chat_router)` next to the other `include_router` calls.

- [ ] **Step 5: Run /messages tests to verify pass**

```bash
pytest tests/test_chat_api.py -v -k "messages"
```
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/chat.py backend/app/main.py backend/tests/test_chat_api.py
git commit -m "feat(chat): list-messages endpoint and router scaffolding"
```

---

## Task 4 — `/chat` SSE endpoint: success path

**Files:**
- Modify: `backend/app/api/chat.py`
- Test: `backend/tests/test_chat_api.py` (extend)

- [ ] **Step 1: Write the failing happy-path test**

Append to `backend/tests/test_chat_api.py`:

```python
from app.services import lm_client


def _bootstrap_chat_session(client, monkeypatch, *, prompt_model: str | None = "mistral") -> str:
    """Configure LMStudio + a prompt-role model + a session that points at it."""
    client.put("/api/settings/lmstudio", json={"base_url": "http://h/v1", "api_key": None})
    monkeypatch.setattr(lm_client, "list_models", lambda **_: ["mistral", "qwen-vl"])
    client.post("/api/settings/lmstudio/refresh")
    client.patch(
        "/api/settings/lmstudio/models/mistral",
        json={"role": "prompt", "enabled": True},
    )

    sid = _make_session(client)
    if prompt_model is not None:
        client.patch(
            f"/api/sessions/{sid}",
            json={
                "name": "s", "model_name": None, "use_negative": True,
                "pinned_loras": [],
                "vl_model_name": None,
                "prompt_model_name": prompt_model,
            },
        )
    return sid


def _parse_sse(body: bytes) -> list[dict]:
    import json as _json
    events: list[dict] = []
    for chunk in body.split(b"\n\n"):
        chunk = chunk.strip()
        if not chunk.startswith(b"data:"):
            continue
        events.append(_json.loads(chunk[len(b"data:"):].strip()))
    return events


def test_chat_streams_deltas_and_persists_both_messages(client, monkeypatch):
    sid = _bootstrap_chat_session(client, monkeypatch)

    captured: dict = {}

    def fake_stream(**kwargs):
        captured.update(kwargs)
        yield "Hel"
        yield "lo"

    monkeypatch.setattr(lm_client, "chat_stream", fake_stream)

    with client.stream(
        "POST", f"/api/sessions/{sid}/chat",
        json={"content": "hey"},
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = b"".join(resp.iter_bytes())

    events = _parse_sse(body)
    deltas = [e for e in events if e["type"] == "delta"]
    done = [e for e in events if e["type"] == "done"]
    errors = [e for e in events if e["type"] == "error"]
    assert [d["content"] for d in deltas] == ["Hel", "lo"]
    assert len(done) == 1 and isinstance(done[0]["message_id"], int)
    assert errors == []

    # Both messages persisted in order
    msgs = client.get(f"/api/sessions/{sid}/messages").json()["messages"]
    assert [(m["role"], m["content"]) for m in msgs] == [
        ("user", "hey"),
        ("assistant", "Hello"),
    ]
    # Done event references the assistant message id
    assert done[0]["message_id"] == msgs[-1]["id"]

    # Endpoint config + model name flowed into lm_client
    assert captured["model"] == "mistral"
    assert captured["endpoint"] == {"base_url": "http://h/v1", "api_key": None}
    # The most recent message in the upstream payload is the new user message
    assert captured["messages"][-1] == {"role": "user", "content": "hey"}
    # System prompt is prepended
    assert captured["messages"][0]["role"] == "system"


def test_chat_includes_vl_summary_and_recent_history(client, conn, monkeypatch):
    from app.storage import session_repo
    sid = _bootstrap_chat_session(client, monkeypatch)
    session_repo.set_vl_summary(conn, sid, "moody portrait, soft rim light")
    session_repo.append_message(conn, session_id=sid, role="user", content="prior-1")
    session_repo.append_message(conn, session_id=sid, role="assistant", content="prior-2")

    captured: dict = {}

    def fake_stream(**kwargs):
        captured.update(kwargs)
        yield "ok"

    monkeypatch.setattr(lm_client, "chat_stream", fake_stream)

    with client.stream("POST", f"/api/sessions/{sid}/chat", json={"content": "now"}) as r:
        b"".join(r.iter_bytes())

    msgs = captured["messages"]
    # system prompt + vl-summary system + 2 history + new user
    assert msgs[0]["role"] == "system"
    assert any("moody portrait" in m["content"] for m in msgs if m["role"] == "system")
    assert [(m["role"], m["content"]) for m in msgs[-3:]] == [
        ("user", "prior-1"),
        ("assistant", "prior-2"),
        ("user", "now"),
    ]


def test_chat_truncates_history_to_30(client, conn, monkeypatch):
    from app.storage import session_repo
    sid = _bootstrap_chat_session(client, monkeypatch)
    for i in range(40):
        session_repo.append_message(
            conn, session_id=sid, role="user" if i % 2 == 0 else "assistant",
            content=f"m{i}",
        )

    captured: dict = {}

    def fake_stream(**kwargs):
        captured.update(kwargs)
        yield "ok"

    monkeypatch.setattr(lm_client, "chat_stream", fake_stream)

    with client.stream("POST", f"/api/sessions/{sid}/chat", json={"content": "now"}) as r:
        b"".join(r.iter_bytes())

    history = [m for m in captured["messages"] if m["role"] in ("user", "assistant")]
    # 30 prior + 1 new
    assert len(history) == 31
    assert history[0]["content"] == "m10"
    assert history[-1]["content"] == "now"
```

- [ ] **Step 2: Run new tests to verify failure**

```bash
pytest tests/test_chat_api.py -v -k "chat_streams or vl_summary or truncates"
```
Expected: 405/404/etc — endpoint doesn't exist yet.

- [ ] **Step 3: Implement the streaming endpoint**

Append to `backend/app/api/chat.py`:

```python
import json

from fastapi import Response
from starlette.responses import StreamingResponse

from app.models.chat import ChatRequest
from app.services import lm_client
from app.storage import settings_repo


CHAT_HISTORY_LIMIT = 30
CHAT_SYSTEM_PROMPT = (
    "You are a chat assistant helping the user iterate on a Stable-Diffusion "
    "image-to-image idea. Discuss composition, lighting, style, mood, and "
    "concrete edits. Stay concise and concrete; do not write final prompt JSON."
)


def _validated_prompt_model(conn: sqlite3.Connection, name: str | None) -> str:
    if not name:
        raise HTTPException(
            status_code=409, detail="session has no prompt_model_name selected",
        )
    row = settings_repo.get_lm_model(conn, name)
    if row is None or not row["enabled"] or row["role"] not in ("prompt", "both"):
        raise HTTPException(
            status_code=409,
            detail=f"prompt_model_name {name!r} is not enabled or wrong role",
        )
    return name


def _build_payload_messages(
    conn: sqlite3.Connection, session_row: dict, user_content: str,
) -> list[dict]:
    msgs: list[dict] = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}]
    if session_row.get("vl_summary"):
        msgs.append({
            "role": "system",
            "content": f"# Source image analysis\n{session_row['vl_summary']}",
        })
    history = session_repo.list_messages(conn, session_id=session_row["id"])
    history = history[-CHAT_HISTORY_LIMIT:]
    for h in history:
        msgs.append({"role": h["role"], "content": h["content"]})
    msgs.append({"role": "user", "content": user_content})
    return msgs


def _sse(payload: dict) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


@router.post("/api/sessions/{session_id}/chat")
def chat(session_id: str, body: ChatRequest, conn: Conn) -> Response:
    session_row = session_repo.get_session(conn, session_id)
    if session_row is None:
        raise _not_found(session_id)

    cfg = settings_repo.get_lmstudio(conn)
    if not cfg["lmstudio_base_url"]:
        raise HTTPException(status_code=409, detail="LMStudio base_url is not configured")
    model = _validated_prompt_model(conn, session_row.get("prompt_model_name"))

    # Persist the user message FIRST so it survives any upstream failure.
    session_repo.append_message(
        conn, session_id=session_id, role="user", content=body.content,
    )

    # Recompute messages AFTER the user INSERT so it's part of context too.
    payload_messages = _build_payload_messages(conn, session_row, body.content)
    endpoint = {
        "base_url": cfg["lmstudio_base_url"],
        "api_key": cfg["lmstudio_api_key"],
    }

    def gen():
        accumulated: list[str] = []
        try:
            for chunk in lm_client.chat_stream(
                endpoint=endpoint, model=model, messages=payload_messages,
            ):
                accumulated.append(chunk)
                yield _sse({"type": "delta", "content": chunk})
        except lm_client.LmError as exc:
            yield _sse({"type": "error", "detail": str(exc)})
            return

        full = "".join(accumulated).strip()
        if not full:
            yield _sse({"type": "error", "detail": "empty assistant response"})
            return

        row = session_repo.append_message(
            conn, session_id=session_id, role="assistant", content=full,
        )
        yield _sse({"type": "done", "message_id": row["id"]})

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

Note: `_validated_prompt_model` is intentionally a near-clone of `_validated_vl_model` from `app/api/sessions.py` — two callers, two role gates, no shared abstraction needed yet.

- [ ] **Step 4: Run happy-path tests to verify pass**

```bash
pytest tests/test_chat_api.py -v -k "chat_streams or vl_summary or truncates"
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/chat.py backend/tests/test_chat_api.py
git commit -m "feat(chat): SSE streaming chat endpoint with history + vl-summary context"
```

---

## Task 5 — `/chat` error and validation paths

**Files:**
- Test: `backend/tests/test_chat_api.py` (extend)
- (Implementation should already be correct; this task verifies and fills any gaps.)

- [ ] **Step 1: Write the failing error-path tests**

Append to `backend/tests/test_chat_api.py`:

```python
def test_chat_404_when_session_missing(client):
    assert client.post("/api/sessions/missing/chat", json={"content": "x"}).status_code == 404


def test_chat_409_when_no_lmstudio_config(client):
    sid = _make_session(client)
    resp = client.post(f"/api/sessions/{sid}/chat", json={"content": "x"})
    assert resp.status_code == 409
    assert "lmstudio" in resp.json()["detail"].lower() or "base_url" in resp.json()["detail"].lower()


def test_chat_409_when_no_prompt_model_on_session(client, monkeypatch):
    sid = _bootstrap_chat_session(client, monkeypatch, prompt_model=None)
    resp = client.post(f"/api/sessions/{sid}/chat", json={"content": "x"})
    assert resp.status_code == 409
    assert "prompt_model" in resp.json()["detail"]


def test_chat_409_when_prompt_model_disabled(client, monkeypatch):
    sid = _bootstrap_chat_session(client, monkeypatch)
    client.patch(
        "/api/settings/lmstudio/models/mistral", json={"enabled": False},
    )
    resp = client.post(f"/api/sessions/{sid}/chat", json={"content": "x"})
    assert resp.status_code == 409


def test_chat_409_when_prompt_model_role_is_vl_only(client, monkeypatch):
    sid = _bootstrap_chat_session(client, monkeypatch)
    client.patch(
        "/api/settings/lmstudio/models/mistral", json={"role": "vl"},
    )
    resp = client.post(f"/api/sessions/{sid}/chat", json={"content": "x"})
    assert resp.status_code == 409


def test_chat_422_on_blank_content(client, monkeypatch):
    sid = _bootstrap_chat_session(client, monkeypatch)
    assert client.post(f"/api/sessions/{sid}/chat", json={"content": "   "}).status_code == 422


def test_chat_emits_error_event_and_keeps_user_message_on_upstream_failure(client, monkeypatch):
    sid = _bootstrap_chat_session(client, monkeypatch)

    def fail(**_):
        raise lm_client.LmError("upstream", "boom")
        yield  # pragma: no cover  (make this a generator)

    monkeypatch.setattr(lm_client, "chat_stream", fail)

    with client.stream("POST", f"/api/sessions/{sid}/chat", json={"content": "hey"}) as resp:
        assert resp.status_code == 200  # SSE always opens 200
        body = b"".join(resp.iter_bytes())

    events = _parse_sse(body)
    assert any(e["type"] == "error" for e in events)
    assert all(e["type"] != "done" for e in events)

    # User message remains; assistant was NOT saved
    msgs = client.get(f"/api/sessions/{sid}/messages").json()["messages"]
    assert [m["role"] for m in msgs] == ["user"]
    assert msgs[0]["content"] == "hey"


def test_chat_does_not_persist_assistant_when_stream_yields_nothing(client, monkeypatch):
    sid = _bootstrap_chat_session(client, monkeypatch)

    def empty(**_):
        if False:
            yield ""  # pragma: no cover

    monkeypatch.setattr(lm_client, "chat_stream", empty)

    with client.stream("POST", f"/api/sessions/{sid}/chat", json={"content": "hey"}) as resp:
        body = b"".join(resp.iter_bytes())

    events = _parse_sse(body)
    assert any(e["type"] == "error" for e in events)
    msgs = client.get(f"/api/sessions/{sid}/messages").json()["messages"]
    assert [m["role"] for m in msgs] == ["user"]
```

- [ ] **Step 2: Run error-path tests**

```bash
pytest tests/test_chat_api.py -v
```
Expected: all green. If any fail, fix `chat.py` (most likely culprits: missing 409 detail wording, or the assistant message getting saved on empty stream).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_chat_api.py
git commit -m "test(chat): error and validation paths for /chat endpoint"
```

---

## Task 6 — Frontend chat API module

**Files:**
- Create: `frontend/src/api/chat.ts`

- [ ] **Step 1: Write the API helpers**

Create `frontend/src/api/chat.ts`:

```typescript
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { API_BASE, ApiError, apiFetch } from "./client";

export type ChatMessage = {
  id: number;
  session_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: number;
};

export type ChatStreamEvent =
  | { type: "delta"; content: string }
  | { type: "done"; message_id: number }
  | { type: "error"; detail: string };

export const chatKeys = {
  messages: (sessionId: string) => ["sessions", sessionId, "messages"] as const,
};

export const chatApi = {
  listMessages: (sessionId: string) =>
    apiFetch<{ messages: ChatMessage[] }>(`/api/sessions/${sessionId}/messages`),
};

export function useMessages(sessionId: string | undefined) {
  return useQuery({
    enabled: !!sessionId,
    queryKey: sessionId ? chatKeys.messages(sessionId) : ["sessions", "__noop", "messages"],
    queryFn: async () => (await chatApi.listMessages(sessionId as string)).messages,
  });
}

export function useChatInvalidation() {
  const client = useQueryClient();
  return {
    messages: (sessionId: string) =>
      void client.invalidateQueries({ queryKey: chatKeys.messages(sessionId) }),
  };
}

export type StreamCallbacks = {
  onDelta: (chunk: string) => void;
  onDone: (messageId: number) => void;
  onError: (detail: string) => void;
};

/**
 * POST a chat turn and parse the SSE response into typed callbacks.
 * Resolves once the stream closes (success OR error). Does NOT throw on
 * application-level errors — callers handle them via onError.
 */
export async function streamChat(
  sessionId: string,
  content: string,
  cb: StreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ content }),
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
  while (true) {
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
      let evt: ChatStreamEvent;
      try {
        evt = JSON.parse(data) as ChatStreamEvent;
      } catch {
        continue;
      }
      if (evt.type === "delta") cb.onDelta(evt.content);
      else if (evt.type === "done") cb.onDone(evt.message_id);
      else if (evt.type === "error") cb.onError(evt.detail);
    }
  }
}
```

- [ ] **Step 2: Type-check**

From `frontend/`:
```bash
pnpm tsc --noEmit
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/chat.ts
git commit -m "feat(chat): frontend API module with SSE stream parser"
```

---

## Task 7 — `ChatPane` component

**Files:**
- Modify: `frontend/src/components/atoms/Icon.tsx`
- Create: `frontend/src/components/molecules/ChatPane.tsx`
- Create: `frontend/src/components/molecules/ChatPane.module.css`
- Create: `frontend/src/components/molecules/ChatPane.test.tsx`

- [ ] **Step 0: Add `Send` to the icon map**

In `frontend/src/components/atoms/Icon.tsx`, extend the lucide imports and the `ICONS` map to include `Send`:

```tsx
import {
  Check,
  ChevronDown,
  // ... existing imports
  Send,
  // ... existing imports
} from "lucide-react";

const ICONS = {
  Check,
  ChevronDown,
  // ... existing entries
  Send,
  // ... existing entries
} as const satisfies Record<string, LucideIcon>;
```

The `IconName` union derives from the map, so `<Icon name="Send" />` becomes type-valid after this.

- [ ] **Step 1: Write the failing component test (after Step 0)**

Create `frontend/src/components/molecules/ChatPane.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatPane } from "./ChatPane";
import type { Session } from "@/api/sessions";

const SESSION: Session = {
  id: "s1",
  project_id: "p1",
  name: "demo",
  model_name: null,
  use_negative: true,
  pinned_loras: [],
  source_image_path: null,
  source_image_url: null,
  vl_summary: null,
  vl_model_name: null,
  prompt_model_name: "mistral",
  created_at: 0,
  updated_at: 0,
};

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

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ChatPane", () => {
  it("renders empty state and the disabled Generate button", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.endsWith("/messages")) return jsonResponse({ messages: [] });
      throw new Error(`unexpected fetch: ${url}`);
    }));

    render(withClient(<ChatPane session={SESSION} />));
    await waitFor(() => expect(screen.getByPlaceholderText(/message/i)).toBeInTheDocument());
    const gen = screen.getByRole("button", { name: /generate prompt/i });
    expect(gen).toBeDisabled();
    expect(gen).toHaveAttribute("title", expect.stringMatching(/slice 6/i));
  });

  it("streams assistant deltas and refetches history on done", async () => {
    let messagesCallCount = 0;
    const initialMsgs = { messages: [] as unknown[] };
    const finalMsgs = {
      messages: [
        { id: 1, session_id: "s1", role: "user", content: "hi", created_at: 1 },
        { id: 2, session_id: "s1", role: "assistant", content: "hello there", created_at: 2 },
      ],
    };

    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.endsWith("/messages")) {
        messagesCallCount += 1;
        return jsonResponse(messagesCallCount === 1 ? initialMsgs : finalMsgs);
      }
      if (url.endsWith("/chat") && init?.method === "POST") {
        return makeStreamResponse([
          'data: {"type":"delta","content":"hello "}\n\n',
          'data: {"type":"delta","content":"there"}\n\n',
          'data: {"type":"done","message_id":2}\n\n',
        ]);
      }
      throw new Error(`unexpected fetch: ${url}`);
    }));

    render(withClient(<ChatPane session={SESSION} />));
    const input = await screen.findByPlaceholderText(/message/i);
    await userEvent.type(input, "hi");
    await userEvent.click(screen.getByRole("button", { name: /^send$/i }));

    // optimistic user message visible immediately
    expect(await screen.findByText("hi")).toBeInTheDocument();

    // assistant streamed content visible during stream
    await waitFor(() => expect(screen.getByText(/hello there/)).toBeInTheDocument());

    // history refetched at least once after done
    await waitFor(() => expect(messagesCallCount).toBeGreaterThanOrEqual(2));
  });

  it("disables send while in flight and shows error event", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.endsWith("/messages")) return jsonResponse({ messages: [] });
      if (url.endsWith("/chat") && init?.method === "POST") {
        return makeStreamResponse([
          'data: {"type":"error","detail":"upstream blew up"}\n\n',
        ]);
      }
      throw new Error(`unexpected fetch: ${url}`);
    }));

    render(withClient(<ChatPane session={SESSION} />));
    const input = await screen.findByPlaceholderText(/message/i);
    await userEvent.type(input, "hi");
    await userEvent.click(screen.getByRole("button", { name: /^send$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/upstream blew up/);
  });
});
```

- [ ] **Step 2: Run test to verify failure**

From `frontend/`:
```bash
pnpm vitest run src/components/molecules/ChatPane.test.tsx
```
Expected: `Cannot find module './ChatPane'`.

- [ ] **Step 3: Implement `ChatPane`**

Create `frontend/src/components/molecules/ChatPane.module.css`:

```css
.pane {
  display: grid;
  grid-template-rows: auto 1fr auto auto;
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  background: var(--bg);
  min-height: 0;
  overflow: hidden;
}

.head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
  color: var(--text-subtle);
}

.title {
  color: var(--text);
  font-weight: 600;
}

.body {
  overflow-y: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
}

.empty {
  color: var(--text-subtle);
  text-align: center;
  margin: auto 0;
  font-size: 13px;
}

.msg {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 13px;
  line-height: 1.45;
}

.role {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-subtle);
}

.user {
  align-self: flex-end;
  max-width: 80%;
  background: var(--bg-elevated, var(--bg));
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  padding: 6px 8px;
  white-space: pre-wrap;
}

.assistant {
  align-self: flex-start;
  max-width: 90%;
  white-space: pre-wrap;
}

.error {
  color: var(--danger, #c33);
  padding: 6px 12px;
  font-size: 12px;
  border-top: 1px solid var(--border);
}

.composer {
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: 6px;
  padding: 8px 8px 8px 12px;
  border-top: 1px solid var(--border);
  align-items: center;
}

.input {
  resize: none;
  min-height: 32px;
  max-height: 140px;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  background: var(--bg);
  color: var(--text);
  font: inherit;
}
```

Create `frontend/src/components/molecules/ChatPane.tsx`:

```tsx
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import {
  streamChat,
  useChatInvalidation,
  useMessages,
  type ChatMessage,
} from "@/api/chat";
import type { Session } from "@/api/sessions";
import styles from "./ChatPane.module.css";

export function ChatPane({ session }: { session: Session }) {
  const messages = useMessages(session.id);
  const invalidate = useChatInvalidation();
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [optimistic, setOptimistic] = useState<ChatMessage | null>(null);
  const [streaming, setStreaming] = useState("");
  const [error, setError] = useState<string | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);

  const rows = messages.data ?? [];
  const showOptimistic = optimistic && !rows.some((r) => r.id === optimistic.id);
  const showStreaming = pending && streaming.length > 0;

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight });
  }, [rows.length, streaming, optimistic?.id]);

  async function send() {
    const content = draft.trim();
    if (!content || pending) return;
    const tempUser: ChatMessage = {
      id: -Date.now(),
      session_id: session.id,
      role: "user",
      content,
      created_at: Math.floor(Date.now() / 1000),
    };
    setOptimistic(tempUser);
    setStreaming("");
    setDraft("");
    setError(null);
    setPending(true);
    try {
      await streamChat(session.id, content, {
        onDelta: (chunk) => setStreaming((s) => s + chunk),
        onDone: () => {
          invalidate.messages(session.id);
        },
        onError: (detail) => setError(detail),
      });
    } catch (err) {
      setError(String(err));
    } finally {
      setPending(false);
      setStreaming("");
      setOptimistic(null);
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  }

  return (
    <div className={styles.pane}>
      <div className={styles.head}>
        <span className={styles.title}>Chat</span>
        <span>· prompt model: {session.prompt_model_name ?? "(not set)"}</span>
      </div>
      <div className={styles.body} ref={bodyRef}>
        {rows.length === 0 && !showOptimistic && !showStreaming && (
          <div className={styles.empty}>No messages yet. Say hi.</div>
        )}
        {rows.map((m) => (
          <div key={m.id} className={styles.msg}>
            <span className={styles.role}>{m.role}</span>
            <div className={m.role === "user" ? styles.user : styles.assistant}>
              {m.content}
            </div>
          </div>
        ))}
        {showOptimistic && optimistic && (
          <div className={styles.msg}>
            <span className={styles.role}>{optimistic.role}</span>
            <div className={styles.user}>{optimistic.content}</div>
          </div>
        )}
        {showStreaming && (
          <div className={styles.msg}>
            <span className={styles.role}>assistant</span>
            <div className={styles.assistant}>{streaming}</div>
          </div>
        )}
      </div>
      {error && <div className={styles.error} role="alert">{error}</div>}
      <div className={styles.composer}>
        <textarea
          className={styles.input}
          placeholder="Message…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          rows={1}
          disabled={pending}
        />
        <Button
          size="sm"
          variant="primary"
          icon={<Icon name="Send" size={12} />}
          onClick={() => void send()}
          disabled={pending || draft.trim().length === 0}
        >
          {pending ? "Sending…" : "Send"}
        </Button>
        <Button
          size="sm"
          icon={<Icon name="Sparkles" size={12} />}
          disabled
          title="Generate prompt — available in Slice 6"
        >
          Generate prompt
        </Button>
      </div>
    </div>
  );
}
```

`Sparkles` is already in the icon map (used in `SourceImagePane.tsx:73`); `Send` was added in Step 0.

- [ ] **Step 4: Run component tests to verify pass**

```bash
pnpm vitest run src/components/molecules/ChatPane.test.tsx
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/atoms/Icon.tsx frontend/src/components/molecules/ChatPane.tsx frontend/src/components/molecules/ChatPane.module.css frontend/src/components/molecules/ChatPane.test.tsx
git commit -m "feat(chat): ChatPane with streaming UI and history hydration"
```

---

## Task 8 — Wire ChatPane into the workspace + manual smoke

**Files:**
- Modify: `frontend/src/routes/workspace.tsx`
- Modify: `frontend/src/routes/workspaceRoute.test.tsx` (only if it references the chat placeholder string)

- [ ] **Step 1: Replace the placeholder**

In `frontend/src/routes/workspace.tsx`:

- Add `import { ChatPane } from "@/components/molecules/ChatPane";` next to `SourceImagePane`'s import.
- Replace line 68 (`<div className={styles.placeholder}>Chat pane · coming in Slice 4</div>`) with `<ChatPane session={s} />`.

- [ ] **Step 2: Update workspace route test if it asserts the old placeholder**

Open `frontend/src/routes/workspaceRoute.test.tsx`. If a test asserts the literal string "Chat pane · coming in Slice 4", change the assertion to look for the chat placeholder element by role (e.g. `screen.getByPlaceholderText(/message/i)` or `screen.getByRole("button", { name: /generate prompt/i })`). Stub `/messages` calls in the existing fetch mock to return `{ messages: [] }`.

- [ ] **Step 3: Run frontend test suite**

From `frontend/`:
```bash
pnpm vitest run
```
Expected: all green.

- [ ] **Step 4: Run backend test suite**

From `backend/`:
```bash
pytest
```
Expected: all green.

- [ ] **Step 5: Manual browser smoke (Windows-buffering check)**

Per `~/.claude/rules/manual-testing.md`, drive the UI yourself. Don't ask the user.

1. Start backend in background: `uv run uvicorn app.main:app --reload --port 8000` (from `backend/`).
2. Start frontend dev server via `preview_start` (uses `frontend/.claude/launch.json` if present; otherwise `pnpm dev` in background and `preview_start` against `http://localhost:5173`).
3. In LMStudio (or stub), have at least one chat-capable model loaded.
4. Navigate to `/settings/lmstudio`, set base URL, Refresh, mark a model with `role=prompt` and `enabled=true`.
5. Create a project and a session. Open Session settings, pick the prompt model.
6. Land on the workspace. In `ChatPane`, type "hello" and Send.
7. Verify deltas arrive **incrementally** (not as one block) — this is the Windows-buffering check the roadmap §5 calls out. Use `preview_console_logs` and `preview_network` to confirm the chunked `text/event-stream` response.
8. Reload the page; confirm both messages still display via `/messages`.
9. Click Generate prompt — confirm it stays disabled and the title says "available in Slice 6".
10. `preview_screenshot` for the record.

If tokens arrive in one block (buffering), follow the documented fallback at the bottom of this plan.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/workspace.tsx frontend/src/routes/workspaceRoute.test.tsx
git commit -m "feat(workspace): mount ChatPane in slice-4 chat pane slot"
```

---

## Task 9 — Final verification & branch wrap-up

- [ ] **Step 1: Lint + type-check**

```bash
# from backend/
ruff check .
# from frontend/
pnpm tsc --noEmit
pnpm eslint .
```
Expected: clean.

- [ ] **Step 2: Full test sweep**

```bash
# from backend/
pytest
# from frontend/
pnpm vitest run
```
Expected: 0 failures.

- [ ] **Step 3: Acceptance walk-through**

Confirm against the roadmap acceptance bullets for Slice 4:

1. Send a message → assistant tokens stream in chunked → final message persists.
2. Reload page → both user and assistant messages reappear from `/messages`.
3. LLM endpoint failing (turn off LMStudio mid-test) → user message stays, assistant row is NOT created, error banner shows.
4. Empty content rejected by 422 (composer disables it client-side too).
5. Without a prompt model selected → 409, surfaced as a readable error in the UI.
6. Generate-prompt button visible but disabled with "Slice 6" title.

- [ ] **Step 4: Hand off via finishing-a-development-branch**

Use the `superpowers:finishing-a-development-branch` skill to decide between merge / PR / cleanup. Do not push or open a PR without explicit user approval.

---

## Risks and fallbacks

- **Windows uvicorn buffering.** If Task 8 step 5 shows tokens arriving as one block, switch the response in `chat.py` from FastAPI's `StreamingResponse` to `sse_starlette.EventSourceResponse`. The change is:
  - Add `sse-starlette>=2.1` to `backend/pyproject.toml` `[project] dependencies`.
  - In `chat.py`, replace the `StreamingResponse(...)` call with:
    ```python
    from sse_starlette.sse import EventSourceResponse

    async def aiter():
        for evt in gen():
            # gen() already emits "data: ...\n\n" — strip and re-emit just the JSON
            yield evt.decode("utf-8").removeprefix("data: ").strip().rstrip("\n")
    return EventSourceResponse(aiter())
    ```
  - Tests can keep parsing `data: ...` because `EventSourceResponse` writes the same wire format; the `_parse_sse` helper continues to work.
- **httpx streaming + MockTransport on Windows.** The Task 2 tests rely on `httpx.MockTransport` returning a fully-buffered `Response`; `iter_lines()` works against that synthetic body identically on every OS. No platform-specific guard needed.
- **`chat_stream` consuming `Iterator` vs `Generator`.** The endpoint code calls the generator inside `gen()`, which is itself a generator passed to `StreamingResponse`. FastAPI consumes it lazily; do not wrap it in `list(...)` anywhere or buffering will defeat the purpose.

---

## Out of scope (do NOT add)

- Tool-calling, function-calling, structured JSON output. Those are Slice 6.
- Auto-trigger of generate-prompt from a chat turn. Slice 6 only, and only via explicit user button.
- Retriever / vector search / LoRA picking inside chat context. That is Slice 5/6.
- Resuming a half-finished assistant message after upstream timeout. Slice 4 explicitly drops the partial.
- Per-message regeneration / edit. Append-only is the spec.
- Per-session system-prompt customisation UI. Constant string in code is fine for MVP.
