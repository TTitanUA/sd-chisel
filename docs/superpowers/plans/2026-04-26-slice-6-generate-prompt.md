# Slice 6 — Generate-prompt (two-step) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the full MVP loop: from a session that already has a source image, a `vl_summary`, and chat history, hitting **Generate prompt** runs a two-step LLM flow (intent extraction → vector retrieval + pinned LoRAs → final prompt composition) that returns a structured `GeneratedPrompt`. The result is persisted to the existing `prompts` table verbatim and rendered in a new `PromptPane` with copy buttons, a debug pane, and prompt history.

**Architecture:** Four new backend modules, no schema migration. `app/services/retriever.py` is pure SQL — embeds an intent query through `embedder.embed`, runs sqlite-vec `MATCH … k=K`, joins back to `loras`, and applies optional family/tag filters. `app/services/prompt_builder.py` is pure string assembly per spec §4.5 and §4.1 — given session row, vl_summary, last-N messages, distinct tag list, and candidate LoRAs, it returns the system+user message arrays for both LLM calls. `app/services/prompt_orchestrator.py` is the only place that knows about both the LLM client and the retriever — it owns the two-call sequence, JSON parsing, error mapping, and persistence. `app/api/prompt.py` adds two endpoints (`POST /api/sessions/{id}/generate-prompt`, `GET /api/sessions/{id}/prompts`). On the frontend, a new `PromptPane` organism replaces the workspace placeholder and is fed by a new `useGeneratePrompt` mutation + `usePrompts` query; the existing disabled "Generate prompt" button in `ChatPane` is enabled and wired to the mutation.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, existing `lm_client` (raw `httpx`, OpenAI-compat), `embedder.embed` (lazy bge-m3, 1024-dim), `sqlite-vec` `vec0` virtual table, pytest with `monkeypatch` + `httpx.MockTransport`. Frontend: React 18 + TS + TanStack Query (no new deps), reusing existing `Button` / `Badge` / `Icon` / `Slider` atoms+molecules.

**Reference docs checked while writing this plan:**
- Roadmap §4 Slice 6 (scope, boundaries, acceptance, handoff): [docs/superpowers/specs/2026-04-23-mvp-roadmap-design.md](docs/superpowers/specs/2026-04-23-mvp-roadmap-design.md)
- Spec §4.1 (intent rewriting), §4.4 (`GeneratedPrompt` schema), §4.5 (composition system prompt): [docs/spec/technical_specifications.md](docs/spec/technical_specifications.md)
- `prompts` table & cascade rules already in [backend/migrations/001_init.sql:88-98](backend/migrations/001_init.sql:88)
- `lm_client.chat_stream` pattern + `LmError` (mirror for new `chat_complete`): [backend/app/services/lm_client.py:131-182](backend/app/services/lm_client.py:131)
- `indexer.upsert_lora_vector` for the exact `sqlite_vec.serialize_float32` + `vec_loras` MATCH conventions: [backend/app/services/indexer.py:20-53](backend/app/services/indexer.py:20)
- `chat.py` SSE endpoint as the template for dependency injection, model validation, and message assembly: [backend/app/api/chat.py:34-136](backend/app/api/chat.py:34)
- Slice-5 plan structure & test patterns: [docs/superpowers/plans/2026-04-26-slice-5-embedder-indexer.md](docs/superpowers/plans/2026-04-26-slice-5-embedder-indexer.md)

---

## Pre-flight: state at start of slice

After Slice 5 the codebase has:

- `prompts(id, session_id, positive, negative, loras_json, intents_json, retrieved_loras_json, created_at)` already created with FK cascade and `idx_prompts_session` ([backend/migrations/001_init.sql:88-98](backend/migrations/001_init.sql:88)). **Currently unused** — no `append_prompt` / `list_prompts` exist in `session_repo.py`.
- `vec_loras` (virtual `vec0(embedding FLOAT[1024])`) and `lora_vec_map(lora_name PK FK→loras CASCADE, rowid UNIQUE)` are populated by Slice 5; reading them back follows the same `sqlite_vec.serialize_float32` convention used in [backend/app/services/indexer.py:20-53](backend/app/services/indexer.py:20).
- `lm_client.chat_stream` exists ([backend/app/services/lm_client.py:131-182](backend/app/services/lm_client.py:131)) and yields content chunks. **No non-streaming chat helper.** Slice 6 adds `chat_complete(*, endpoint, model, messages, response_format=None) -> str` next to it.
- `embedder.embed(text) -> list[float]` is the lazy bge-m3 wrapper ([backend/app/services/embedder.py](backend/app/services/embedder.py)). Tests already monkeypatch this seam through `tests/conftest.py` (autouse fake from Slice 5).
- Sessions carry `prompt_model_name`, `vl_summary`, `model_name`, `use_negative`, `pinned_loras` ([backend/app/models/session.py](backend/app/models/session.py); see also `session_repo.get_session_with_pinned`). The chat endpoint already validates that `prompt_model_name` is a known, enabled `lm_models` row with role in `("prompt","both")` ([backend/app/api/chat.py:34-45](backend/app/api/chat.py:34)) — Slice 6 reuses that validator verbatim.
- `library_repo.get_lora`, `get_model`, `get_family`, `list_all_lora_names` exist; `list_distinct_tags` does NOT — Slice 6 adds it.
- `library_service.list_loras` returns hydrated rows with `is_indexed`. We do NOT use the service in Slice 6 retriever — the retriever queries directly through repo helpers because we need the vector distance alongside the row.
- Frontend: `Session` type already has `pinned_loras`, `model_name`, `vl_summary`, `prompt_model_name`. A `streamChat` helper exists ([frontend/src/api/chat.ts](frontend/src/api/chat.ts)). No `prompts.ts`, no `PromptPane`. The workspace right-hand pane is a literal placeholder div ([frontend/src/routes/workspace.tsx:70](frontend/src/routes/workspace.tsx:70)). The "Generate prompt" button in ChatPane is rendered with `disabled` + `title="Generate prompt — available in Slice 6"` ([frontend/src/components/molecules/ChatPane.tsx:128-135](frontend/src/components/molecules/ChatPane.tsx:128)).
- `frontend/src/components/atoms/` exposes `Button`, `Badge`, `Icon`. `frontend/src/components/molecules/Slider.tsx` exposes `<Slider label min max step value onChange unit hint />`.

These are the assumed inputs; do not re-implement them.

---

## File Structure

Create or modify only the files below.

```
backend/
├── app/
│   ├── services/
│   │   ├── lm_client.py                     # modify: add chat_complete()
│   │   ├── retriever.py                     # NEW — top-K per intent + family/tag pre-filter
│   │   ├── prompt_builder.py                # NEW — system + user message assembly per §4.5
│   │   └── prompt_orchestrator.py           # NEW — owns the two-step flow + persistence
│   ├── api/
│   │   ├── prompt.py                        # NEW — POST generate-prompt, GET prompts
│   │   └── deps.py                          # unchanged (we reuse get_conn)
│   ├── storage/
│   │   ├── session_repo.py                  # modify: add append_prompt, list_prompts
│   │   └── library_repo.py                  # modify: add list_distinct_tags, get_loras_by_names
│   ├── models/
│   │   └── prompts.py                       # NEW — Intent, IntentList, LoraSpec,
│   │                                        #         GeneratedPrompt, RetrievedLora,
│   │                                        #         RetrievedIntent, PromptOut,
│   │                                        #         GeneratePromptResponse, PromptsResponse
│   └── main.py                              # modify: include prompt router
└── tests/
    ├── test_lm_client_complete.py           # NEW — chat_complete success / json_object / errors
    ├── test_session_repo_prompts.py         # NEW — append_prompt, list_prompts round-trip
    ├── test_library_repo_extras.py          # NEW — list_distinct_tags, get_loras_by_names
    ├── test_retriever.py                    # NEW — top-K, dedupe, family filter, k cap
    ├── test_prompt_builder.py               # NEW — message shape, schema in user prompt,
    │                                        #         use_negative branch
    ├── test_prompt_orchestrator.py          # NEW — two-step flow with fake LLM + fake retriever
    └── test_prompt_api.py                   # NEW — /generate-prompt + /prompts integration

frontend/
└── src/
    ├── api/
    │   └── prompts.ts                       # NEW — types + useGeneratePrompt + usePrompts
    ├── components/
    │   └── organisms/
    │       ├── PromptPane.tsx               # NEW
    │       ├── PromptPane.module.css        # NEW
    │       ├── PromptPane.test.tsx          # NEW
    │       └── PromptLoraRow.tsx            # NEW (kept in same dir; small helper)
    ├── components/molecules/
    │   └── ChatPane.tsx                     # modify: enable Generate prompt button
    └── routes/
        └── workspace.tsx                    # modify: replace placeholder with <PromptPane>
```

No DB migration. No new backend dep (uses existing `httpx`, `sqlite-vec`, `embedder`). No new frontend dep.

---

## API Contract

Two new endpoints. Both live under the existing `/api/sessions/{session_id}/...` namespace.

### `POST /api/sessions/{session_id}/generate-prompt`

Body: empty (no fields). Returns `200` with the generated prompt + debug payload, or one of the typed errors below.

```jsonc
// 200 — fresh generation persisted, full debug bundle inline
{
  "prompt_id": 17,
  "prompt": {
    "positive": "string, non-empty",
    "negative": "string | null",                  // null iff session.use_negative = false
    "loras": [
      { "name": "string", "weight": -2.0..2.0 }
    ]
  },
  "intents": [
    { "kind": "style",  "query": "dramatic moody anime lighting" }
  ],
  "retrieved": [
    {
      "intent_index": 0,
      "intent_query": "dramatic moody anime lighting",
      "results": [
        { "name": "noir-anime-lighting-v2", "distance": 0.18 },
        { "name": "moody-cinematic-style",  "distance": 0.27 }
      ]
    }
  ],
  "created_at": 1745763221
}

// 404 — session not found
// 409 — config / data missing (one detail at a time):
//          "LMStudio base_url is not configured"
//          "session has no prompt_model_name selected"
//          "prompt_model_name {n!r} is not enabled or wrong role"
//          "session has no source image analysis (vl_summary) yet"
//          "session has no model_name; cannot resolve family"   (only if model lookup actually needed AND missing)
// 502 — upstream LLM failure (LmError kind=upstream/timeout/shape; detail propagated)
//          "intent extraction returned malformed JSON"
//          "prompt composition returned malformed JSON or schema mismatch"
```

### `GET /api/sessions/{session_id}/prompts`

```jsonc
// 200 — newest first
{
  "prompts": [
    {
      "id": 17,
      "session_id": "ses_…",
      "prompt": { "positive": "...", "negative": null, "loras": [ ... ] },
      "intents": [ ... ] | null,
      "retrieved": [ ... ] | null,
      "created_at": 1745763221
    }
  ]
}

// 404 — session not found
```

`intents` and `retrieved` are nullable in `GET` even though they are always populated by `POST`, because we tolerate older / hand-inserted rows where the JSON columns were left NULL.

`use_negative` semantics:
- `true` → `negative` MUST be a non-empty string (validated server-side; on schema mismatch we return 502 — we do not silently rewrite the model output).
- `false` → `negative` MUST be `null` (we coerce `""` → `null` to keep the schema clean; any other shape is 502).

Unknown LoRAs (i.e. names the model emits that are not in the `loras` table) are persisted **verbatim** in `loras_json` per spec §4.4. The frontend resolves "known vs unknown" client-side using its existing LoRA list — we do NOT add a server-side cross-check.

---

## Cross-cutting design notes

- **Two LLM calls, one transaction-free path.** Persisting only happens once at the end (single `INSERT INTO prompts`). If the first or second LLM call fails we return the error and write nothing — the user just sees an error toast. No partial state. This avoids any rollback dance.

- **Why a new `chat_complete` instead of buffering `chat_stream`.** We need (a) `response_format={"type":"json_object"}` to get clean JSON out of LMStudio, and (b) an HTTP `read` timeout that doesn't hold a stream connection open. Buffering the streaming endpoint works but mixes layers — the lm_client already separates `analyze_image` (non-streaming) from `chat_stream`. Adding `chat_complete` keeps that separation. We do NOT pass `response_format` to a stream call; we do not need it for chat.

- **JSON parsing & fallback.** We try `json.loads` on the raw content first. If that fails, we extract the first balanced `{...}` block via a tiny `_extract_json_object(text)` helper (find first `{`, walk with depth counter, return slice) and retry. If both fail, raise `LmError("shape", ...)` and the API maps that to 502. We do NOT use the `instructor` library — too much surface for this slice.

- **Intent prompt is small and instruction-heavy.** It includes: the VL summary, last 10 chat messages (configurable constant `INTENT_HISTORY_LIMIT = 10`), and the deduplicated list of distinct tags pulled from `loras.tags` via `json_each`. The model is asked to emit a `{"intents":[{"kind":"...","query":"..."}]}` object with 1-6 entries. On cold-start the tag list is empty and we say so explicitly in the prompt — that matches roadmap §4.1 ("LLM генерит kind свободно").

- **Retrieval cap.** Top-K per intent is `RETRIEVAL_TOP_K = 12` (mid of the spec's 10-15 range). After dedup across intents, we cap the union at `RETRIEVAL_GLOBAL_CAP = 20` (drop by worst distance). Pinned LoRAs are then merged in **after** the cap so they always reach the composition step. This keeps the system prompt size bounded even on libraries with thousands of LoRAs.

- **Family pre-filter is best-effort.** sqlite-vec's `MATCH … k = ?` doesn't accept an external WHERE on the virtual table. We over-fetch (`k = RETRIEVAL_TOP_K * 4`), then filter `family_id` in the JOIN, then trim to `RETRIEVAL_TOP_K`. If `session.model_name` is NULL or the model row is gone, we skip the family filter entirely (no 409 — retrieval still works).

- **Composition system prompt** follows spec §4.5 exactly. The `# Available LoRAs` block is the **full markdown `description` of every candidate** (retrieved ∪ pinned), separated by `\n\n---\n\n`, plus a one-line metadata header per LoRA (`name`, `family_id`, `recommended_weight`, `trigger_words`) so the LLM can pick weight without re-reading the description. The candidate set is bounded — see retrieval cap above — so message size stays well inside any sensible context window.

- **`use_negative` is part of the user prompt, not the schema.** Pydantic models stay simple: `negative: str | None`. The user prompt explicitly says "Set `negative` to null because the user disabled negative prompting" or "Provide a non-empty `negative` string". Server validates the result before saving; mismatch → 502.

- **Persisted columns.**
  - `positive`: `prompt.positive`
  - `negative`: `prompt.negative` (nullable)
  - `loras_json`: `json.dumps([{"name":..,"weight":..}, ...], ensure_ascii=False)` — verbatim from LLM, including unknown names
  - `intents_json`: `json.dumps({"intents":[…]})`
  - `retrieved_loras_json`: `json.dumps([{intent_index, intent_query, results:[{name, distance}]}, …])`
  - `created_at`: `int(time.time())`

- **Frontend invalidation.** After a successful generate, we invalidate `["prompts", sessionId]` and the `useSession` query (the session's `updated_at` changes only via prompt persistence's optional touch; we keep it untouched in this slice — `prompts` are append-only, sessions don't get bumped, simpler).

- **No regenerate UX state machine.** "Regenerate" is just the same mutation called again — every result is a new row in `prompts`. The PromptPane shows the **most recent** prompt by default; a small history dropdown or list lets the user click into older ones. We use `prompts` order (`created_at DESC, id DESC`) to pick the head.

---

## Task 1 — Add `chat_complete` to `lm_client`

**Files:**
- Modify: `backend/app/services/lm_client.py`
- Create: `backend/tests/test_lm_client_complete.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_lm_client_complete.py`:

```python
from __future__ import annotations

import json

import httpx
import pytest

from app.services import lm_client


def _mock_response(payload: dict, status: int = 200) -> httpx.MockTransport:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)
    return httpx.MockTransport(handler)


def test_chat_complete_returns_assistant_content():
    transport = _mock_response({
        "choices": [{"message": {"role": "assistant", "content": "  hello  "}}],
    })
    out = lm_client.chat_complete(
        endpoint={"base_url": "http://x/v1", "api_key": None},
        model="m",
        messages=[{"role": "user", "content": "hi"}],
        transport=transport,
    )
    assert out == "hello"


def test_chat_complete_passes_response_format_when_supplied():
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.content.decode())
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "{}"}}],
        })

    out = lm_client.chat_complete(
        endpoint={"base_url": "http://x/v1", "api_key": None},
        model="m",
        messages=[{"role": "user", "content": "hi"}],
        response_format={"type": "json_object"},
        transport=httpx.MockTransport(handler),
    )
    assert out == "{}"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["body"]["stream"] is False


def test_chat_complete_omits_response_format_when_none():
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.content.decode())
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}}],
        })

    lm_client.chat_complete(
        endpoint={"base_url": "http://x/v1", "api_key": None},
        model="m",
        messages=[{"role": "user", "content": "hi"}],
        transport=httpx.MockTransport(handler),
    )
    assert "response_format" not in captured["body"]


def test_chat_complete_raises_upstream_on_4xx():
    transport = _mock_response({"error": "bad"}, status=400)
    with pytest.raises(lm_client.LmError) as exc:
        lm_client.chat_complete(
            endpoint={"base_url": "http://x/v1", "api_key": None},
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            transport=transport,
        )
    assert exc.value.kind == "upstream"


def test_chat_complete_raises_shape_on_empty_content():
    transport = _mock_response({
        "choices": [{"message": {"content": "   "}}],
    })
    with pytest.raises(lm_client.LmError) as exc:
        lm_client.chat_complete(
            endpoint={"base_url": "http://x/v1", "api_key": None},
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            transport=transport,
        )
    assert exc.value.kind == "shape"


def test_chat_complete_requires_model_and_messages():
    with pytest.raises(lm_client.LmError):
        lm_client.chat_complete(
            endpoint={"base_url": "http://x/v1", "api_key": None},
            model="  ",
            messages=[{"role": "user", "content": "hi"}],
        )
    with pytest.raises(lm_client.LmError):
        lm_client.chat_complete(
            endpoint={"base_url": "http://x/v1", "api_key": None},
            model="m",
            messages=[],
        )
```

- [ ] **Step 2: Verify tests fail**

```bash
cd backend && uv run pytest tests/test_lm_client_complete.py -v
```
Expected: `AttributeError: module 'app.services.lm_client' has no attribute 'chat_complete'`.

- [ ] **Step 3: Implement `chat_complete`**

Append to `backend/app/services/lm_client.py` after `chat_stream`:

```python
def chat_complete(
    *,
    endpoint: dict[str, Any],
    model: str,
    messages: list[dict[str, Any]],
    response_format: dict[str, Any] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> str:
    """Non-streaming OpenAI-compat chat. Returns the assistant content as a string.

    `response_format` is forwarded as-is when provided (e.g. ``{"type":
    "json_object"}``). LMStudio supports json_object on most prompt-tuned
    models; json_schema support is patchy, so callers should validate the
    parsed JSON themselves.
    """
    if not model.strip():
        raise LmError("config", "model is required")
    if not messages:
        raise LmError("config", "messages must not be empty")
    base_url, headers = _resolve(endpoint)
    payload: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
    if response_format is not None:
        payload["response_format"] = response_format
    resp = _request(
        "POST", f"{base_url}/chat/completions",
        headers=headers, json=payload, transport=transport, timeout=CHAT_TIMEOUT,
    )
    if resp.status_code >= 400:
        raise LmError("upstream", f"{resp.status_code}: {resp.text[:200]}")
    try:
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LmError("shape", f"unexpected response body: {exc}") from exc
    if not isinstance(content, str) or not content.strip():
        raise LmError("shape", "empty content from chat endpoint")
    return content.strip()
```

- [ ] **Step 4: Tests pass**

```bash
cd backend && uv run pytest tests/test_lm_client_complete.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/lm_client.py backend/tests/test_lm_client_complete.py
git commit -m "feat(slice-6): add lm_client.chat_complete for non-streaming JSON-mode calls"
```

---

## Task 2 — Pydantic schemas in `app/models/prompts.py`

**Files:**
- Create: `backend/app/models/prompts.py`

- [ ] **Step 1: Define the schemas**

Create `backend/app/models/prompts.py`:

```python
"""Schemas for the two-step generate-prompt flow.

Naming notes:
- ``Intent`` / ``IntentList`` are what the *intent rewriting* LLM emits.
- ``LoraSpec`` is the per-LoRA item the *composition* LLM emits inside
  ``GeneratedPrompt.loras``. We deliberately keep this generous (`extra="ignore"`)
  to absorb harmless extra fields some models add — the persisted column is the
  raw model output, so we don't lose information either way.
- ``RetrievedLora`` / ``RetrievedIntent`` are pure server-side debug payloads.
- ``PromptOut`` / ``GeneratePromptResponse`` / ``PromptsResponse`` are the API
  envelopes.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Intent(BaseModel):
    model_config = ConfigDict(extra="ignore")
    kind: str = Field(min_length=1, max_length=64)
    query: str = Field(min_length=1, max_length=400)


class IntentList(BaseModel):
    model_config = ConfigDict(extra="ignore")
    intents: list[Intent] = Field(min_length=1, max_length=8)


class LoraSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = Field(min_length=1)
    weight: float = Field(ge=-2.0, le=2.0)


class GeneratedPrompt(BaseModel):
    model_config = ConfigDict(extra="ignore")
    positive: str = Field(min_length=1)
    negative: str | None = None
    loras: list[LoraSpec] = Field(default_factory=list)


class RetrievedLora(BaseModel):
    name: str
    distance: float


class RetrievedIntent(BaseModel):
    intent_index: int
    intent_query: str
    results: list[RetrievedLora]


class PromptOut(BaseModel):
    id: int
    session_id: str
    prompt: GeneratedPrompt
    intents: list[Intent] | None
    retrieved: list[RetrievedIntent] | None
    created_at: int


class GeneratePromptResponse(BaseModel):
    prompt_id: int
    prompt: GeneratedPrompt
    intents: list[Intent]
    retrieved: list[RetrievedIntent]
    created_at: int


class PromptsResponse(BaseModel):
    prompts: list[PromptOut]
```

- [ ] **Step 2: Smoke test the schemas inline**

Append to `backend/tests/test_prompt_orchestrator.py` later — for now verify the module imports cleanly:

```bash
cd backend && uv run python -c "from app.models.prompts import GeneratedPrompt, IntentList, PromptOut, GeneratePromptResponse, PromptsResponse; print('ok')"
```
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/prompts.py
git commit -m "feat(slice-6): add Pydantic schemas for intents and generated prompts"
```

---

## Task 3 — Persistence helpers in `session_repo`

**Files:**
- Modify: `backend/app/storage/session_repo.py`
- Create: `backend/tests/test_session_repo_prompts.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_session_repo_prompts.py`:

```python
from __future__ import annotations

import json

from app.storage import library_repo, session_repo


def _bootstrap_session(conn) -> str:
    proj = session_repo.create_project(conn, name="p")
    sess = session_repo.create_session(conn, project_id=proj["id"], name="s")
    return sess["id"]


def test_append_prompt_round_trips_full_payload(conn):
    sid = _bootstrap_session(conn)
    row = session_repo.append_prompt(
        conn,
        session_id=sid,
        positive="a moody girl, dramatic",
        negative="blurry, lowres",
        loras=[{"name": "noir-v2", "weight": 0.6}],
        intents=[{"kind": "style", "query": "moody anime"}],
        retrieved=[{
            "intent_index": 0, "intent_query": "moody anime",
            "results": [{"name": "noir-v2", "distance": 0.1}],
        }],
    )
    assert row["id"] > 0
    assert row["positive"] == "a moody girl, dramatic"
    assert row["negative"] == "blurry, lowres"
    assert json.loads(row["loras_json"]) == [{"name": "noir-v2", "weight": 0.6}]
    assert json.loads(row["intents_json"]) == [{"kind": "style", "query": "moody anime"}]
    assert json.loads(row["retrieved_loras_json"])[0]["intent_index"] == 0
    assert isinstance(row["created_at"], int)


def test_append_prompt_persists_negative_null():
    pass  # placeholder — covered by the next test


def test_append_prompt_accepts_negative_none(conn):
    sid = _bootstrap_session(conn)
    row = session_repo.append_prompt(
        conn,
        session_id=sid,
        positive="x",
        negative=None,
        loras=[],
        intents=None,
        retrieved=None,
    )
    assert row["negative"] is None
    assert row["intents_json"] is None
    assert row["retrieved_loras_json"] is None
    assert json.loads(row["loras_json"]) == []


def test_list_prompts_returns_newest_first(conn):
    sid = _bootstrap_session(conn)
    a = session_repo.append_prompt(
        conn, session_id=sid, positive="a", negative=None,
        loras=[], intents=None, retrieved=None,
    )
    b = session_repo.append_prompt(
        conn, session_id=sid, positive="b", negative=None,
        loras=[], intents=None, retrieved=None,
    )
    rows = session_repo.list_prompts(conn, session_id=sid)
    assert [r["id"] for r in rows] == [b["id"], a["id"]]


def test_list_prompts_empty_for_unknown_session(conn):
    assert session_repo.list_prompts(conn, session_id="nope") == []
```

The fixture `conn` already exists in `backend/tests/conftest.py` (used by every other repo test) — it yields a fresh in-memory DB with all migrations applied.

- [ ] **Step 2: Verify tests fail**

```bash
cd backend && uv run pytest tests/test_session_repo_prompts.py -v
```
Expected: `AttributeError: module 'app.storage.session_repo' has no attribute 'append_prompt'`.

- [ ] **Step 3: Implement `append_prompt` and `list_prompts`**

Append to `backend/app/storage/session_repo.py` after `list_messages`:

```python
# --- prompts (append-only history) -----------------------------------------


def append_prompt(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    positive: str,
    negative: str | None,
    loras: list[dict[str, Any]],
    intents: list[dict[str, Any]] | None,
    retrieved: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    import json as _json

    now = _now()
    cur = conn.execute(
        "INSERT INTO prompts(session_id, positive, negative, loras_json, "
        "intents_json, retrieved_loras_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            session_id,
            positive,
            negative,
            _json.dumps(loras, ensure_ascii=False),
            _json.dumps(intents, ensure_ascii=False) if intents is not None else None,
            _json.dumps(retrieved, ensure_ascii=False) if retrieved is not None else None,
            now,
        ),
    )
    return _row(conn.execute(
        "SELECT * FROM prompts WHERE id = ?", (cur.lastrowid,),
    ).fetchone())  # type: ignore[return-value]


def list_prompts(
    conn: sqlite3.Connection, *, session_id: str,
) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM prompts WHERE session_id = ? "
            "ORDER BY created_at DESC, id DESC",
            (session_id,),
        )
    ]
```

- [ ] **Step 4: Tests pass**

```bash
cd backend && uv run pytest tests/test_session_repo_prompts.py -v
```
Expected: 4 passed (the placeholder `test_append_prompt_persists_negative_null` passes trivially — leave it for clarity or delete; either is fine).

- [ ] **Step 5: Commit**

```bash
git add backend/app/storage/session_repo.py backend/tests/test_session_repo_prompts.py
git commit -m "feat(slice-6): persist generated prompts via session_repo.append_prompt/list_prompts"
```

---

## Task 4 — Library helpers used by retrieval & composition

**Files:**
- Modify: `backend/app/storage/library_repo.py`
- Create: `backend/tests/test_library_repo_extras.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_library_repo_extras.py`:

```python
from __future__ import annotations

import json

from app.storage import library_repo


def _seed(conn, *, name: str, family: str, tags: list[str]) -> None:
    library_repo.create_lora(
        conn,
        name=name,
        display_name=name,
        description=f"desc for {name}",
        tags=tags,
        trigger_words=[],
        family_id=family,
    )


def test_list_distinct_tags_returns_sorted_unique(conn):
    _seed(conn, name="a", family="sdxl", tags=["lighting", "style"])
    _seed(conn, name="b", family="sdxl", tags=["style", "character"])
    assert library_repo.list_distinct_tags(conn) == ["character", "lighting", "style"]


def test_list_distinct_tags_empty_when_no_loras(conn):
    assert library_repo.list_distinct_tags(conn) == []


def test_get_loras_by_names_preserves_input_order(conn):
    _seed(conn, name="a", family="sdxl", tags=[])
    _seed(conn, name="b", family="sdxl", tags=[])
    _seed(conn, name="c", family="sdxl", tags=[])
    rows = library_repo.get_loras_by_names(conn, ["c", "a", "missing", "b"])
    assert [r["name"] for r in rows] == ["c", "a", "b"]
    assert all("description" in r for r in rows)


def test_get_loras_by_names_empty_input_returns_empty(conn):
    assert library_repo.get_loras_by_names(conn, []) == []
```

- [ ] **Step 2: Verify tests fail**

```bash
cd backend && uv run pytest tests/test_library_repo_extras.py -v
```
Expected: AttributeError on missing helpers.

- [ ] **Step 3: Implement the helpers**

Append to `backend/app/storage/library_repo.py`:

```python
def list_distinct_tags(conn: sqlite3.Connection) -> list[str]:
    """Return every distinct tag string across all LoRAs, sorted ascending."""
    rows = conn.execute(
        "SELECT DISTINCT json_each.value AS tag "
        "FROM loras, json_each(loras.tags) "
        "ORDER BY tag",
    ).fetchall()
    return [r["tag"] for r in rows]


def get_loras_by_names(
    conn: sqlite3.Connection, names: list[str],
) -> list[dict[str, Any]]:
    """Return the hydrated LoRA rows whose ``name`` is in ``names``,
    preserving the input order. Unknown names are silently dropped."""
    if not names:
        return []
    placeholders = ",".join("?" for _ in names)
    rows = conn.execute(
        f"SELECT * FROM loras WHERE name IN ({placeholders})",
        names,
    ).fetchall()
    by_name = {r["name"]: _hydrate_lora(r) for r in rows}
    return [by_name[n] for n in names if n in by_name]
```

`_hydrate_lora` already exists in this file ([backend/app/storage/library_repo.py:160-164](backend/app/storage/library_repo.py:160)).

- [ ] **Step 4: Tests pass**

```bash
cd backend && uv run pytest tests/test_library_repo_extras.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/storage/library_repo.py backend/tests/test_library_repo_extras.py
git commit -m "feat(slice-6): add list_distinct_tags and get_loras_by_names to library_repo"
```

---

## Task 5 — Retriever service

**Files:**
- Create: `backend/app/services/retriever.py`
- Create: `backend/tests/test_retriever.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_retriever.py`:

```python
from __future__ import annotations

import pytest

from app.services import retriever
from app.services.embedder import EMBEDDING_DIM
from app.storage import library_repo


def _make_vector(seed: int) -> list[float]:
    # deterministic, non-zero, varied vector
    return [((seed + i) % 7) * 0.01 for i in range(EMBEDDING_DIM)]


def _seed_lora(conn, *, name, family, tags=None, vector_seed=1):
    library_repo.create_lora(
        conn, name=name, display_name=name, description=f"desc {name}",
        tags=tags or [], trigger_words=[], family_id=family,
    )
    # Reach into indexer directly — the test bypasses library_service to keep
    # this isolated from the embedder seam.
    from app.services import indexer
    indexer.upsert_lora_vector(conn, lora_name=name, vector=_make_vector(vector_seed))


def test_top_k_returns_at_most_k_with_distance(conn, monkeypatch):
    _seed_lora(conn, name="a", family="sdxl", vector_seed=1)
    _seed_lora(conn, name="b", family="sdxl", vector_seed=2)
    _seed_lora(conn, name="c", family="sdxl", vector_seed=3)

    monkeypatch.setattr(
        "app.services.retriever.embedder.embed",
        lambda text: _make_vector(1),
    )

    hits = retriever.top_k(conn, query="anything", k=2)
    assert len(hits) == 2
    assert all("name" in h and "distance" in h for h in hits)
    # Closest first
    assert hits[0]["distance"] <= hits[1]["distance"]


def test_top_k_family_filter_drops_other_families(conn, monkeypatch):
    _seed_lora(conn, name="a", family="sdxl", vector_seed=1)
    _seed_lora(conn, name="b", family="pony", vector_seed=2)

    monkeypatch.setattr(
        "app.services.retriever.embedder.embed",
        lambda text: _make_vector(1),
    )

    hits = retriever.top_k(conn, query="x", k=10, family_id="sdxl")
    assert [h["name"] for h in hits] == ["a"]


def test_top_k_no_loras_returns_empty(conn, monkeypatch):
    monkeypatch.setattr(
        "app.services.retriever.embedder.embed",
        lambda text: _make_vector(1),
    )
    assert retriever.top_k(conn, query="x", k=5) == []


def test_retrieve_for_intents_dedupes_across_intents(conn, monkeypatch):
    _seed_lora(conn, name="a", family="sdxl", vector_seed=1)
    _seed_lora(conn, name="b", family="sdxl", vector_seed=2)

    monkeypatch.setattr(
        "app.services.retriever.embedder.embed",
        lambda text: _make_vector(1),
    )

    intents = [
        {"kind": "style", "query": "x"},
        {"kind": "detail", "query": "y"},
    ]
    bundle = retriever.retrieve_for_intents(conn, intents=intents, k=10)

    # per-intent hits returned with intent_index
    assert {h["intent_index"] for h in bundle["per_intent"]} == {0, 1}
    # union deduped on name
    union_names = [c["name"] for c in bundle["candidates"]]
    assert sorted(union_names) == ["a", "b"]


def test_retrieve_for_intents_caps_global_union(conn, monkeypatch):
    for i in range(8):
        _seed_lora(conn, name=f"l{i}", family="sdxl", vector_seed=i + 1)

    monkeypatch.setattr(
        "app.services.retriever.embedder.embed",
        lambda text: _make_vector(1),
    )

    intents = [{"kind": "k", "query": "q"}]
    bundle = retriever.retrieve_for_intents(
        conn, intents=intents, k=10, global_cap=3,
    )
    assert len(bundle["candidates"]) == 3
```

- [ ] **Step 2: Verify tests fail**

```bash
cd backend && uv run pytest tests/test_retriever.py -v
```
Expected: import error on `app.services.retriever`.

- [ ] **Step 3: Implement the retriever**

Create `backend/app/services/retriever.py`:

```python
"""Top-K LoRA retrieval over sqlite-vec, per intent.

The retriever knows nothing about LLMs or the prompt builder. Given a set of
intents (each a {kind, query} dict), it embeds each query, runs vec_loras
MATCH, joins back to `loras` with an optional family filter, and returns:

- ``per_intent``: a flat list of hits with ``intent_index`` so callers can
  reconstruct which intent produced what (used for the debug payload).
- ``candidates``: the deduplicated union (by ``name``), capped at
  ``global_cap``, sorted by best (smallest) per-name distance.
- ``by_name``: ``dict[str, dict]`` mapping name → full hydrated LoRA row,
  used by the prompt builder to pull descriptions without re-querying.

Family pre-filter is best-effort: sqlite-vec MATCH does not honour external
WHERE clauses, so we over-fetch (k * 4) and filter in the join.
"""
from __future__ import annotations

import sqlite3
from typing import Any

import sqlite_vec

from app.services import embedder
from app.storage import library_repo

OVERFETCH_FACTOR = 4
DEFAULT_GLOBAL_CAP = 20


def top_k(
    conn: sqlite3.Connection,
    *,
    query: str,
    k: int,
    family_id: str | None = None,
) -> list[dict[str, Any]]:
    """Embed `query`, return up to k {name, distance} hits, optionally
    filtered to `family_id`."""
    vec = embedder.embed(query)
    payload = sqlite_vec.serialize_float32(vec)
    fetch_k = max(k * OVERFETCH_FACTOR, k)

    rows = conn.execute(
        "WITH knn AS ("
        "  SELECT rowid, distance FROM vec_loras "
        "  WHERE embedding MATCH ? AND k = ? "
        "  ORDER BY distance"
        ") "
        "SELECT l.name AS name, knn.distance AS distance "
        "FROM knn "
        "JOIN lora_vec_map m ON m.rowid = knn.rowid "
        "JOIN loras l ON l.name = m.lora_name "
        + ("WHERE l.family_id = ? " if family_id else "")
        + "ORDER BY knn.distance",
        (payload, fetch_k, family_id) if family_id else (payload, fetch_k),
    ).fetchall()
    return [{"name": r["name"], "distance": float(r["distance"])} for r in rows[:k]]


def retrieve_for_intents(
    conn: sqlite3.Connection,
    *,
    intents: list[dict[str, Any]],
    k: int,
    family_id: str | None = None,
    global_cap: int = DEFAULT_GLOBAL_CAP,
) -> dict[str, Any]:
    """Run top_k for each intent, dedupe the union by name (keeping the
    smallest distance), cap at ``global_cap``, and return the bundle."""
    per_intent: list[dict[str, Any]] = []
    best_by_name: dict[str, float] = {}
    for idx, intent in enumerate(intents):
        hits = top_k(conn, query=intent["query"], k=k, family_id=family_id)
        for h in hits:
            per_intent.append({
                "intent_index": idx,
                "intent_query": intent["query"],
                "name": h["name"],
                "distance": h["distance"],
            })
            prev = best_by_name.get(h["name"])
            if prev is None or h["distance"] < prev:
                best_by_name[h["name"]] = h["distance"]

    ranked = sorted(best_by_name.items(), key=lambda kv: kv[1])[:global_cap]
    candidate_names = [name for name, _ in ranked]
    candidates = library_repo.get_loras_by_names(conn, candidate_names)
    by_name = {c["name"]: c for c in candidates}

    # Re-shape per_intent into the API debug payload
    grouped: dict[int, dict[str, Any]] = {}
    for hit in per_intent:
        bucket = grouped.setdefault(hit["intent_index"], {
            "intent_index": hit["intent_index"],
            "intent_query": hit["intent_query"],
            "results": [],
        })
        bucket["results"].append({"name": hit["name"], "distance": hit["distance"]})
    debug = [grouped[i] for i in sorted(grouped)]

    return {
        "per_intent": debug,
        "candidates": candidates,
        "by_name": by_name,
    }
```

- [ ] **Step 4: Tests pass**

```bash
cd backend && uv run pytest tests/test_retriever.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/retriever.py backend/tests/test_retriever.py
git commit -m "feat(slice-6): retriever service — top-K LoRA per intent over sqlite-vec"
```

---

## Task 6 — Prompt builder service

**Files:**
- Create: `backend/app/services/prompt_builder.py`
- Create: `backend/tests/test_prompt_builder.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_prompt_builder.py`:

```python
from __future__ import annotations

from app.services import prompt_builder


def _lora(name: str, **over) -> dict:
    base = {
        "name": name,
        "display_name": name,
        "description": f"# {name}\nhelpful description",
        "tags": ["lighting"],
        "trigger_words": [f"{name}_trigger"],
        "recommended_weight": 0.7,
        "family_id": "sdxl",
    }
    base.update(over)
    return base


def test_build_intent_messages_includes_summary_history_and_tags():
    msgs = prompt_builder.build_intent_messages(
        vl_summary="anime girl moody lighting",
        chat_messages=[
            {"role": "user", "content": "make it darker"},
            {"role": "assistant", "content": "ok"},
        ],
        distinct_tags=["lighting", "style"],
    )
    assert msgs[0]["role"] == "system"
    user = next(m for m in msgs if m["role"] == "user")
    assert "anime girl moody lighting" in user["content"]
    assert "make it darker" in user["content"]
    assert "lighting" in user["content"] and "style" in user["content"]
    # Schema instruction is in the system message
    assert '"intents"' in msgs[0]["content"]


def test_build_intent_messages_handles_empty_tags_explicitly():
    msgs = prompt_builder.build_intent_messages(
        vl_summary="x", chat_messages=[], distinct_tags=[],
    )
    user = next(m for m in msgs if m["role"] == "user")
    assert "no tags" in user["content"].lower()


def test_build_composition_messages_lists_loras_with_separator():
    msgs = prompt_builder.build_composition_messages(
        family_prompt_guide="GUIDE TEXT",
        model_description="MODEL DELTA",
        candidates=[_lora("a"), _lora("b")],
        vl_summary="VLS",
        chat_messages=[{"role": "user", "content": "go"}],
        use_negative=True,
    )
    sys = msgs[0]["content"]
    assert "GUIDE TEXT" in sys
    assert "MODEL DELTA" in sys
    assert "# Available LoRAs" in sys
    assert "\n---\n" in sys
    assert "# a" in sys and "# b" in sys
    assert "VLS" in sys


def test_build_composition_messages_omits_model_description_when_none():
    msgs = prompt_builder.build_composition_messages(
        family_prompt_guide="GUIDE",
        model_description=None,
        candidates=[],
        vl_summary="V",
        chat_messages=[],
        use_negative=False,
    )
    sys = msgs[0]["content"]
    assert "GUIDE" in sys
    # Should not produce a stray empty section
    assert "MODEL DELTA" not in sys


def test_build_composition_messages_use_negative_branch_in_user():
    msgs_on = prompt_builder.build_composition_messages(
        family_prompt_guide="g", model_description=None, candidates=[],
        vl_summary="v", chat_messages=[], use_negative=True,
    )
    msgs_off = prompt_builder.build_composition_messages(
        family_prompt_guide="g", model_description=None, candidates=[],
        vl_summary="v", chat_messages=[], use_negative=False,
    )
    assert "negative" in msgs_on[-1]["content"]
    assert "null" in msgs_off[-1]["content"]
```

- [ ] **Step 2: Verify tests fail**

```bash
cd backend && uv run pytest tests/test_prompt_builder.py -v
```
Expected: import error.

- [ ] **Step 3: Implement the builder**

Create `backend/app/services/prompt_builder.py`:

```python
"""Pure string assembly for the two LLM calls.

Source: spec §4.1 (intent rewriting) and §4.5 (composition system prompt).
This module knows nothing about the LLM client or the DB — every input is a
plain Python value the orchestrator already has on hand.
"""
from __future__ import annotations

from typing import Any

INTENT_SYSTEM = (
    "You are a planner that turns an image-to-image editing brief into a "
    "small list of search intents. For each intent emit a `kind` (a short "
    "tag like 'style', 'detail', 'character', or anything that matches a "
    "tag we tell you about) and a `query` — a poetic phrase describing the "
    "*effect* you want to find a LoRA for, NOT a literal description of the "
    "source image. Output must be a JSON object matching this schema:\n"
    '{"intents": [{"kind": "string", "query": "string"}, ...]}\n'
    "1 to 6 intents. No prose, no markdown — JSON only."
)

GENERATED_PROMPT_SCHEMA_HINT = (
    'Return a JSON object matching exactly:\n'
    '{"positive": "string, non-empty",\n'
    ' "negative": "string | null",\n'
    ' "loras": [{"name": "string", "weight": number in [-2.0, 2.0]}, ...]}\n'
    "No prose, no markdown, no comments — JSON only."
)


def _format_history(chat_messages: list[dict[str, Any]]) -> str:
    if not chat_messages:
        return "(no prior conversation)"
    lines = []
    for m in chat_messages:
        lines.append(f"{m['role']}: {m['content']}")
    return "\n".join(lines)


def build_intent_messages(
    *,
    vl_summary: str,
    chat_messages: list[dict[str, Any]],
    distinct_tags: list[str],
) -> list[dict[str, str]]:
    if distinct_tags:
        tag_block = (
            "Known tags (prefer one of these for `kind`, but invent a new one "
            "if none fit):\n" + ", ".join(distinct_tags)
        )
    else:
        tag_block = (
            "We have no tags yet (cold start) — choose any short `kind` you like."
        )
    user_content = (
        f"# Source image analysis\n{vl_summary}\n\n"
        f"# Recent conversation\n{_format_history(chat_messages)}\n\n"
        f"# {tag_block}"
    )
    return [
        {"role": "system", "content": INTENT_SYSTEM},
        {"role": "user", "content": user_content},
    ]


def _format_lora_block(lora: dict[str, Any]) -> str:
    triggers = ", ".join(lora.get("trigger_words") or []) or "(none)"
    weight = lora.get("recommended_weight")
    head = (
        f"# {lora['name']}\n"
        f"family: {lora['family_id']} | "
        f"recommended_weight: {weight if weight is not None else 'n/a'} | "
        f"triggers: {triggers}\n"
    )
    return head + (lora.get("description") or "")


def build_composition_messages(
    *,
    family_prompt_guide: str,
    model_description: str | None,
    candidates: list[dict[str, Any]],
    vl_summary: str,
    chat_messages: list[dict[str, Any]],
    use_negative: bool,
) -> list[dict[str, str]]:
    parts = [family_prompt_guide.strip()]
    if model_description and model_description.strip():
        parts.append(model_description.strip())
    if candidates:
        loras_section = "\n\n---\n\n".join(_format_lora_block(c) for c in candidates)
    else:
        loras_section = "(no candidate LoRAs)"
    parts.append("# Available LoRAs\n" + loras_section)
    parts.append(f"# Source image analysis\n{vl_summary}")
    parts.append(f"# Conversation\n{_format_history(chat_messages)}")
    parts.append("# Output\n" + GENERATED_PROMPT_SCHEMA_HINT)
    system = "\n\n".join(parts)

    if use_negative:
        user = (
            "Generate the prompt now. `negative` must be a non-empty string "
            "describing what to avoid (artifacts, anatomy issues, unwanted "
            "styles, etc.)."
        )
    else:
        user = (
            "Generate the prompt now. The user disabled negative prompting — "
            "set `negative` to null."
        )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
```

- [ ] **Step 4: Tests pass**

```bash
cd backend && uv run pytest tests/test_prompt_builder.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/prompt_builder.py backend/tests/test_prompt_builder.py
git commit -m "feat(slice-6): prompt_builder — assemble intent + composition messages per spec §4.5"
```

---

## Task 7 — Orchestrator (two-step flow)

**Files:**
- Create: `backend/app/services/prompt_orchestrator.py`
- Create: `backend/tests/test_prompt_orchestrator.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_prompt_orchestrator.py`:

```python
from __future__ import annotations

import json

import pytest

from app.services import prompt_orchestrator
from app.services.lm_client import LmError
from app.storage import library_repo, session_repo


@pytest.fixture
def session_id(conn) -> str:
    fam = library_repo.get_family(conn, "sdxl")
    assert fam is not None
    library_repo.create_model(
        conn, name="m1", display_name="m1", family_id="sdxl",
        description="model delta",
    )
    library_repo.create_lora(
        conn, name="lora-a", display_name="lora-a",
        description="A description", tags=["style"], trigger_words=["a_t"],
        family_id="sdxl",
    )
    proj = session_repo.create_project(conn, name="p")
    sess = session_repo.create_session(
        conn, project_id=proj["id"], name="s", model_name="m1",
    )
    session_repo.set_vl_summary(conn, sess["id"], "moody girl, dramatic")
    return sess["id"]


def _fake_lm_responses(intent_payload: str, composition_payload: str):
    calls = {"i": 0}
    def fake(*, endpoint, model, messages, response_format=None, transport=None):
        calls["i"] += 1
        if calls["i"] == 1:
            return intent_payload
        return composition_payload
    return fake


def test_generate_returns_persisted_response(conn, session_id, monkeypatch):
    monkeypatch.setattr(
        "app.services.retriever.embedder.embed",
        lambda text: [0.001] * 1024,
    )
    monkeypatch.setattr(
        "app.services.prompt_orchestrator.lm_client.chat_complete",
        _fake_lm_responses(
            intent_payload=json.dumps({"intents": [
                {"kind": "style", "query": "moody"},
            ]}),
            composition_payload=json.dumps({
                "positive": "moody girl, dramatic",
                "negative": "blurry",
                "loras": [{"name": "lora-a", "weight": 0.6}],
            }),
        ),
    )

    out = prompt_orchestrator.generate(
        conn,
        session_id=session_id,
        endpoint={"base_url": "http://x/v1", "api_key": None},
        prompt_model="m1",
    )

    assert out["prompt"]["positive"] == "moody girl, dramatic"
    assert out["prompt"]["negative"] == "blurry"
    assert out["prompt"]["loras"] == [{"name": "lora-a", "weight": 0.6}]
    assert out["intents"] == [{"kind": "style", "query": "moody"}]
    rows = session_repo.list_prompts(conn, session_id=session_id)
    assert rows[0]["positive"] == "moody girl, dramatic"


def test_generate_use_negative_false_forces_null(conn, session_id, monkeypatch):
    session_repo.update_session(
        conn, session_id, name="s", model_name="m1",
        use_negative=False,
    )
    monkeypatch.setattr(
        "app.services.retriever.embedder.embed",
        lambda text: [0.001] * 1024,
    )
    # Composition returns negative as empty string — orchestrator must coerce to null
    monkeypatch.setattr(
        "app.services.prompt_orchestrator.lm_client.chat_complete",
        _fake_lm_responses(
            intent_payload=json.dumps({"intents": [{"kind": "k", "query": "q"}]}),
            composition_payload=json.dumps({
                "positive": "p", "negative": "", "loras": [],
            }),
        ),
    )
    out = prompt_orchestrator.generate(
        conn, session_id=session_id,
        endpoint={"base_url": "http://x/v1", "api_key": None},
        prompt_model="m1",
    )
    assert out["prompt"]["negative"] is None


def test_generate_use_negative_true_rejects_null_negative(conn, session_id, monkeypatch):
    monkeypatch.setattr(
        "app.services.retriever.embedder.embed",
        lambda text: [0.001] * 1024,
    )
    monkeypatch.setattr(
        "app.services.prompt_orchestrator.lm_client.chat_complete",
        _fake_lm_responses(
            intent_payload=json.dumps({"intents": [{"kind": "k", "query": "q"}]}),
            composition_payload=json.dumps({
                "positive": "p", "negative": None, "loras": [],
            }),
        ),
    )
    with pytest.raises(LmError) as exc:
        prompt_orchestrator.generate(
            conn, session_id=session_id,
            endpoint={"base_url": "http://x/v1", "api_key": None},
            prompt_model="m1",
        )
    assert exc.value.kind == "shape"


def test_generate_recovers_from_extra_prose_around_json(conn, session_id, monkeypatch):
    monkeypatch.setattr(
        "app.services.retriever.embedder.embed",
        lambda text: [0.001] * 1024,
    )
    monkeypatch.setattr(
        "app.services.prompt_orchestrator.lm_client.chat_complete",
        _fake_lm_responses(
            intent_payload=(
                'Here are the intents:\n'
                '{"intents": [{"kind":"k","query":"q"}]}\nHope this helps.'
            ),
            composition_payload=json.dumps({
                "positive": "p", "negative": "n", "loras": [],
            }),
        ),
    )
    out = prompt_orchestrator.generate(
        conn, session_id=session_id,
        endpoint={"base_url": "http://x/v1", "api_key": None},
        prompt_model="m1",
    )
    assert out["intents"][0]["query"] == "q"


def test_generate_raises_when_session_missing_vl_summary(conn, session_id, monkeypatch):
    conn.execute("UPDATE sessions SET vl_summary = NULL WHERE id = ?", (session_id,))
    with pytest.raises(prompt_orchestrator.PreconditionError) as exc:
        prompt_orchestrator.generate(
            conn, session_id=session_id,
            endpoint={"base_url": "http://x/v1", "api_key": None},
            prompt_model="m1",
        )
    assert "vl_summary" in str(exc.value)


def test_generate_raises_for_unknown_session(conn):
    with pytest.raises(prompt_orchestrator.PreconditionError):
        prompt_orchestrator.generate(
            conn, session_id="nope",
            endpoint={"base_url": "http://x/v1", "api_key": None},
            prompt_model="m1",
        )


def test_generate_persists_pinned_loras_into_candidates(conn, session_id, monkeypatch):
    library_repo.create_lora(
        conn, name="pinned-x", display_name="pinned-x",
        description="pinned desc", tags=[], trigger_words=[], family_id="sdxl",
    )
    session_repo.set_pinned_loras(
        conn, session_id, [{"lora_name": "pinned-x", "weight_override": 0.9}],
    )
    monkeypatch.setattr(
        "app.services.retriever.embedder.embed",
        lambda text: [0.001] * 1024,
    )
    captured: dict = {}

    def fake_complete(*, endpoint, model, messages, response_format=None, transport=None):
        captured.setdefault("calls", []).append(messages)
        if len(captured["calls"]) == 1:
            return json.dumps({"intents": [{"kind": "k", "query": "q"}]})
        return json.dumps({"positive": "p", "negative": "n", "loras": []})

    monkeypatch.setattr(
        "app.services.prompt_orchestrator.lm_client.chat_complete", fake_complete,
    )
    prompt_orchestrator.generate(
        conn, session_id=session_id,
        endpoint={"base_url": "http://x/v1", "api_key": None},
        prompt_model="m1",
    )
    composition_system = captured["calls"][1][0]["content"]
    assert "pinned-x" in composition_system
```

- [ ] **Step 2: Verify tests fail**

```bash
cd backend && uv run pytest tests/test_prompt_orchestrator.py -v
```
Expected: import error.

- [ ] **Step 3: Implement the orchestrator**

Create `backend/app/services/prompt_orchestrator.py`:

```python
"""Two-step generate-prompt flow.

Owns the only place that calls both ``lm_client`` and ``retriever``. Lives
above ``services/`` peers because it composes them; nothing else imports it
except ``app.api.prompt``.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.models.prompts import GeneratedPrompt, IntentList
from app.services import lm_client, prompt_builder, retriever
from app.storage import library_repo, session_repo

_M = TypeVar("_M", bound=BaseModel)

CHAT_HISTORY_LIMIT = 10
RETRIEVAL_TOP_K = 12
RETRIEVAL_GLOBAL_CAP = 20


class PreconditionError(Exception):
    """Raised when input state cannot be turned into a valid LLM call.
    The API layer maps this to HTTP 409.
    """


def _extract_json_object(text: str) -> str:
    """Walk for the first balanced {...} block. Used as a recovery for models
    that wrap JSON in chatty prose."""
    start = text.find("{")
    if start < 0:
        raise lm_client.LmError("shape", "no JSON object in LLM output")
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise lm_client.LmError("shape", "unbalanced JSON object in LLM output")


def _parse_json(text: str, model_cls: type[_M]) -> _M:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        raw = json.loads(_extract_json_object(text))
    try:
        return model_cls.model_validate(raw)
    except ValidationError as exc:
        raise lm_client.LmError("shape", f"schema mismatch: {exc.errors()[:3]}") from exc


def _last_n_messages(conn: sqlite3.Connection, session_id: str, n: int) -> list[dict[str, Any]]:
    msgs = session_repo.list_messages(conn, session_id=session_id)
    return msgs[-n:]


def _coerce_negative(prompt: GeneratedPrompt, *, use_negative: bool) -> GeneratedPrompt:
    neg = prompt.negative
    if not use_negative:
        if neg is None or (isinstance(neg, str) and neg.strip() == ""):
            return prompt.model_copy(update={"negative": None})
        raise lm_client.LmError(
            "shape", "use_negative=false but model returned a non-empty negative",
        )
    # use_negative = True
    if neg is None or not str(neg).strip():
        raise lm_client.LmError(
            "shape", "use_negative=true but model returned null/empty negative",
        )
    return prompt


def generate(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    endpoint: dict[str, Any],
    prompt_model: str,
) -> dict[str, Any]:
    session = session_repo.get_session_with_pinned(conn, session_id)
    if session is None:
        raise PreconditionError(f"session not found: {session_id}")
    if not session.get("vl_summary"):
        raise PreconditionError(
            "session has no source image analysis (vl_summary) yet",
        )

    # Resolve family for retrieval pre-filter (best-effort)
    family_id: str | None = None
    family_prompt_guide = ""
    model_description: str | None = None
    if session.get("model_name"):
        model_row = library_repo.get_model(conn, session["model_name"])
        if model_row is not None:
            family_id = model_row["family_id"]
            model_description = model_row.get("description")
            family_row = library_repo.get_family(conn, family_id)
            if family_row is not None:
                family_prompt_guide = family_row["prompt_guide"]
    if not family_prompt_guide:
        # Cold-start safety: no model selected, no family guide. Use a tiny
        # generic stub so the composition prompt still has structure.
        family_prompt_guide = (
            "You are writing a Stable Diffusion image-to-image prompt. Be "
            "concrete and concise. Use comma-separated tags."
        )

    chat_messages = _last_n_messages(conn, session_id, CHAT_HISTORY_LIMIT)
    distinct_tags = library_repo.list_distinct_tags(conn)

    # ---- Step 1: intents -------------------------------------------------
    intent_messages = prompt_builder.build_intent_messages(
        vl_summary=session["vl_summary"],
        chat_messages=chat_messages,
        distinct_tags=distinct_tags,
    )
    intent_raw = lm_client.chat_complete(
        endpoint=endpoint,
        model=prompt_model,
        messages=intent_messages,
        response_format={"type": "json_object"},
    )
    intents_obj = _parse_json(intent_raw, IntentList)

    # ---- Step 2: retrieval ----------------------------------------------
    bundle = retriever.retrieve_for_intents(
        conn,
        intents=[i.model_dump() for i in intents_obj.intents],
        k=RETRIEVAL_TOP_K,
        family_id=family_id,
        global_cap=RETRIEVAL_GLOBAL_CAP,
    )

    # Merge pinned LoRAs into candidates (no double-include)
    pinned = session.get("pinned_loras") or []
    pinned_names = [p["lora_name"] for p in pinned]
    pinned_rows = library_repo.get_loras_by_names(conn, pinned_names)
    seen = {c["name"] for c in bundle["candidates"]}
    for row in pinned_rows:
        if row["name"] not in seen:
            bundle["candidates"].append(row)
            seen.add(row["name"])

    # ---- Step 3: composition --------------------------------------------
    comp_messages = prompt_builder.build_composition_messages(
        family_prompt_guide=family_prompt_guide,
        model_description=model_description,
        candidates=bundle["candidates"],
        vl_summary=session["vl_summary"],
        chat_messages=chat_messages,
        use_negative=session["use_negative"],
    )
    comp_raw = lm_client.chat_complete(
        endpoint=endpoint,
        model=prompt_model,
        messages=comp_messages,
        response_format={"type": "json_object"},
    )
    prompt_obj = _parse_json(comp_raw, GeneratedPrompt)
    prompt_obj = _coerce_negative(prompt_obj, use_negative=session["use_negative"])

    # ---- Persist ---------------------------------------------------------
    intents_dump = [i.model_dump() for i in intents_obj.intents]
    retrieved_dump = bundle["per_intent"]
    row = session_repo.append_prompt(
        conn,
        session_id=session_id,
        positive=prompt_obj.positive,
        negative=prompt_obj.negative,
        loras=[lora.model_dump() for lora in prompt_obj.loras],
        intents=intents_dump,
        retrieved=retrieved_dump,
    )

    return {
        "prompt_id": row["id"],
        "prompt": prompt_obj.model_dump(),
        "intents": intents_dump,
        "retrieved": retrieved_dump,
        "created_at": row["created_at"],
    }
```

- [ ] **Step 4: Tests pass**

```bash
cd backend && uv run pytest tests/test_prompt_orchestrator.py -v
```
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/prompt_orchestrator.py backend/tests/test_prompt_orchestrator.py
git commit -m "feat(slice-6): orchestrator — two-step intent + composition flow with persistence"
```

---

## Task 8 — API endpoints + router wiring

**Files:**
- Create: `backend/app/api/prompt.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_prompt_api.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_prompt_api.py`:

```python
from __future__ import annotations

import json

import pytest

from app.services import prompt_orchestrator
from app.services.lm_client import LmError
from app.storage import library_repo, session_repo, settings_repo


def _bootstrap(client, conn) -> str:
    settings_repo.set_lmstudio(
        conn, base_url="http://lm/v1", api_key=None,
    )
    settings_repo.upsert_lm_models(conn, names=["pm-1"])
    settings_repo.update_lm_model(
        conn, name="pm-1", role="prompt", enabled=True,
    )
    library_repo.create_model(
        conn, name="m1", display_name="m1", family_id="sdxl", description=None,
    )
    library_repo.create_lora(
        conn, name="lo", display_name="lo", description="d",
        tags=[], trigger_words=[], family_id="sdxl",
    )
    proj = session_repo.create_project(conn, name="p")
    sess = session_repo.create_session(
        conn, project_id=proj["id"], name="s",
        model_name="m1",
    )
    session_repo.update_session(
        conn, sess["id"], name="s", model_name="m1",
        use_negative=True, prompt_model_name="pm-1",
    )
    session_repo.set_vl_summary(conn, sess["id"], "summary text")
    return sess["id"]


def test_generate_prompt_returns_persisted_payload(client, conn, monkeypatch):
    sid = _bootstrap(client, conn)
    monkeypatch.setattr(prompt_orchestrator, "generate", lambda *a, **kw: {
        "prompt_id": 99,
        "prompt": {"positive": "p", "negative": "n", "loras": []},
        "intents": [{"kind": "k", "query": "q"}],
        "retrieved": [{"intent_index": 0, "intent_query": "q", "results": []}],
        "created_at": 1700000000,
    })
    resp = client.post(f"/api/sessions/{sid}/generate-prompt")
    assert resp.status_code == 200
    body = resp.json()
    assert body["prompt_id"] == 99
    assert body["prompt"]["positive"] == "p"
    assert body["intents"][0]["kind"] == "k"


def test_generate_prompt_404_when_session_unknown(client):
    resp = client.post("/api/sessions/nope/generate-prompt")
    assert resp.status_code == 404


def test_generate_prompt_409_when_lmstudio_not_configured(client, conn):
    sid = _bootstrap(client, conn)
    settings_repo.set_lmstudio(conn, base_url=None, api_key=None)
    resp = client.post(f"/api/sessions/{sid}/generate-prompt")
    assert resp.status_code == 409
    assert "base_url" in resp.json()["detail"]


def test_generate_prompt_409_when_prompt_model_not_set(client, conn):
    sid = _bootstrap(client, conn)
    session_repo.update_session(
        conn, sid, name="s", model_name="m1",
        use_negative=True, prompt_model_name=None,
    )
    resp = client.post(f"/api/sessions/{sid}/generate-prompt")
    assert resp.status_code == 409
    assert "prompt_model_name" in resp.json()["detail"]


def test_generate_prompt_409_for_precondition(client, conn, monkeypatch):
    sid = _bootstrap(client, conn)
    monkeypatch.setattr(
        prompt_orchestrator, "generate",
        lambda *a, **kw: (_ for _ in ()).throw(
            prompt_orchestrator.PreconditionError("session has no vl_summary"),
        ),
    )
    resp = client.post(f"/api/sessions/{sid}/generate-prompt")
    assert resp.status_code == 409
    assert "vl_summary" in resp.json()["detail"]


def test_generate_prompt_502_for_lm_error(client, conn, monkeypatch):
    sid = _bootstrap(client, conn)
    monkeypatch.setattr(
        prompt_orchestrator, "generate",
        lambda *a, **kw: (_ for _ in ()).throw(LmError("upstream", "boom")),
    )
    resp = client.post(f"/api/sessions/{sid}/generate-prompt")
    assert resp.status_code == 502
    assert "boom" in resp.json()["detail"]


def test_list_prompts_returns_newest_first(client, conn):
    sid = _bootstrap(client, conn)
    session_repo.append_prompt(
        conn, session_id=sid, positive="old", negative=None,
        loras=[], intents=None, retrieved=None,
    )
    session_repo.append_prompt(
        conn, session_id=sid, positive="new", negative=None,
        loras=[{"name": "lo", "weight": 0.5}],
        intents=[{"kind": "k", "query": "q"}],
        retrieved=[{"intent_index": 0, "intent_query": "q", "results": []}],
    )
    resp = client.get(f"/api/sessions/{sid}/prompts")
    assert resp.status_code == 200
    rows = resp.json()["prompts"]
    assert [r["prompt"]["positive"] for r in rows] == ["new", "old"]
    assert rows[0]["intents"] == [{"kind": "k", "query": "q"}]
    assert rows[1]["intents"] is None


def test_list_prompts_404_for_unknown_session(client):
    resp = client.get("/api/sessions/nope/prompts")
    assert resp.status_code == 404
```

The fixtures `client` and `conn` already exist in `backend/tests/conftest.py` and share the same TestClient + DB connection.

- [ ] **Step 2: Verify tests fail**

```bash
cd backend && uv run pytest tests/test_prompt_api.py -v
```
Expected: 404 on every `/generate-prompt` call (router not registered).

- [ ] **Step 3: Implement the API**

Create `backend/app/api/prompt.py`:

```python
"""HTTP layer for the two-step generate-prompt flow."""
from __future__ import annotations

import json
import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_conn
from app.models.prompts import (
    GeneratedPrompt,
    GeneratePromptResponse,
    Intent,
    PromptOut,
    PromptsResponse,
    RetrievedIntent,
)
from app.services import lm_client, prompt_orchestrator
from app.storage import session_repo, settings_repo

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

router = APIRouter(tags=["prompt"])


def _not_found(session_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"session not found: {session_id}",
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


@router.post(
    "/api/sessions/{session_id}/generate-prompt",
    response_model=GeneratePromptResponse,
)
def generate_prompt(session_id: str, conn: Conn) -> GeneratePromptResponse:
    session = session_repo.get_session(conn, session_id)
    if session is None:
        raise _not_found(session_id)

    cfg = settings_repo.get_lmstudio(conn)
    if not cfg["lmstudio_base_url"]:
        raise HTTPException(
            status_code=409, detail="LMStudio base_url is not configured",
        )
    model = _validated_prompt_model(conn, session.get("prompt_model_name"))
    endpoint = {
        "base_url": cfg["lmstudio_base_url"],
        "api_key": cfg["lmstudio_api_key"],
    }

    try:
        out = prompt_orchestrator.generate(
            conn,
            session_id=session_id,
            endpoint=endpoint,
            prompt_model=model,
        )
    except prompt_orchestrator.PreconditionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except lm_client.LmError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return GeneratePromptResponse(
        prompt_id=out["prompt_id"],
        prompt=GeneratedPrompt.model_validate(out["prompt"]),
        intents=[Intent.model_validate(i) for i in out["intents"]],
        retrieved=[RetrievedIntent.model_validate(r) for r in out["retrieved"]],
        created_at=out["created_at"],
    )


def _row_to_prompt_out(row: dict[str, Any]) -> PromptOut:
    return PromptOut(
        id=row["id"],
        session_id=row["session_id"],
        prompt=GeneratedPrompt.model_validate({
            "positive": row["positive"],
            "negative": row["negative"],
            "loras": json.loads(row["loras_json"]),
        }),
        intents=(
            [Intent.model_validate(i) for i in json.loads(row["intents_json"])]
            if row["intents_json"] else None
        ),
        retrieved=(
            [
                RetrievedIntent.model_validate(r)
                for r in json.loads(row["retrieved_loras_json"])
            ]
            if row["retrieved_loras_json"] else None
        ),
        created_at=row["created_at"],
    )


@router.get(
    "/api/sessions/{session_id}/prompts",
    response_model=PromptsResponse,
)
def list_prompts(session_id: str, conn: Conn) -> PromptsResponse:
    if session_repo.get_session(conn, session_id) is None:
        raise _not_found(session_id)
    rows = session_repo.list_prompts(conn, session_id=session_id)
    return PromptsResponse(prompts=[_row_to_prompt_out(r) for r in rows])
```

- [ ] **Step 4: Register the router**

In `backend/app/main.py`, find the existing router includes and add the prompt router:

```python
from app.api.chat import router as chat_router
from app.api.library import router as library_router
from app.api.prompt import router as prompt_router          # NEW
from app.api.sessions import router as sessions_router
from app.api.settings import router as settings_router

# ...

app.include_router(chat_router)
app.include_router(library_router)
app.include_router(prompt_router)                            # NEW
app.include_router(sessions_router)
app.include_router(settings_router)
```

- [ ] **Step 5: Tests pass**

```bash
cd backend && uv run pytest tests/test_prompt_api.py -v
```
Expected: 8 passed.

- [ ] **Step 6: Full backend test suite is green**

```bash
cd backend && uv run pytest -q
```
Expected: every test passes (including all pre-existing tests).

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/prompt.py backend/app/main.py backend/tests/test_prompt_api.py
git commit -m "feat(slice-6): expose POST /generate-prompt and GET /prompts"
```

---

## Task 9 — Frontend types & data hooks

**Files:**
- Create: `frontend/src/api/prompts.ts`

- [ ] **Step 1: Define types and hooks**

Create `frontend/src/api/prompts.ts`:

```typescript
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";

export type LoraSpec = { name: string; weight: number };

export type GeneratedPrompt = {
  positive: string;
  negative: string | null;
  loras: LoraSpec[];
};

export type Intent = { kind: string; query: string };

export type RetrievedLora = { name: string; distance: number };

export type RetrievedIntent = {
  intent_index: number;
  intent_query: string;
  results: RetrievedLora[];
};

export type Prompt = {
  id: number;
  session_id: string;
  prompt: GeneratedPrompt;
  intents: Intent[] | null;
  retrieved: RetrievedIntent[] | null;
  created_at: number;
};

export type GeneratePromptResponse = {
  prompt_id: number;
  prompt: GeneratedPrompt;
  intents: Intent[];
  retrieved: RetrievedIntent[];
  created_at: number;
};

const promptsKey = (sessionId: string) => ["prompts", sessionId] as const;

export function usePrompts(sessionId: string | undefined) {
  return useQuery({
    queryKey: promptsKey(sessionId ?? ""),
    enabled: Boolean(sessionId),
    queryFn: async () => {
      const body = await apiFetch<{ prompts: Prompt[] }>(
        `/api/sessions/${sessionId}/prompts`,
      );
      return body.prompts;
    },
  });
}

export function useGeneratePrompt(sessionId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<GeneratePromptResponse>(
        `/api/sessions/${sessionId}/generate-prompt`,
        { method: "POST" },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: promptsKey(sessionId) });
    },
  });
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/prompts.ts
git commit -m "feat(slice-6): frontend hooks useGeneratePrompt + usePrompts"
```

---

## Task 10 — `PromptPane` organism

**Files:**
- Create: `frontend/src/components/organisms/PromptPane.tsx`
- Create: `frontend/src/components/organisms/PromptPane.module.css`
- Create: `frontend/src/components/organisms/PromptLoraRow.tsx`
- Create: `frontend/src/components/organisms/PromptPane.test.tsx`

- [ ] **Step 1: Implement `PromptLoraRow`**

Create `frontend/src/components/organisms/PromptLoraRow.tsx`:

```tsx
import { Badge } from "@/components/atoms/Badge";
import { Slider } from "@/components/molecules/Slider";
import type { LoraSpec } from "@/api/prompts";
import type { Lora } from "@/api/library";

export type LoraRowKind = "pinned" | "retrieved" | "picked" | "unknown";

export function classifyLora(
  spec: LoraSpec,
  refs: {
    knownByName: Record<string, Lora>;
    pinnedNames: Set<string>;
    retrievedNames: Set<string>;
  },
): LoraRowKind {
  if (!(spec.name in refs.knownByName)) return "unknown";
  if (refs.pinnedNames.has(spec.name)) return "pinned";
  if (refs.retrievedNames.has(spec.name)) return "retrieved";
  return "picked";
}

export function PromptLoraRow({
  spec,
  kind,
  triggers,
  weight,
  onWeightChange,
}: {
  spec: LoraSpec;
  kind: LoraRowKind;
  triggers: string[];
  weight: number;
  onWeightChange: (next: number) => void;
}) {
  const variant = kind === "unknown" ? "accent" : "neutral";
  const label = kind === "unknown" ? "⚠ unknown" : kind;
  return (
    <div data-kind={kind} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Badge variant={variant}>{label}</Badge>
        <code style={{ fontFamily: "var(--font-mono)" }}>{spec.name}</code>
        {triggers.length > 0 && (
          <span style={{ color: "var(--text-subtle)", fontSize: 12 }}>
            ({triggers.join(", ")})
          </span>
        )}
      </div>
      <Slider
        label={`weight`}
        min={-2}
        max={2}
        step={0.05}
        value={weight}
        onChange={onWeightChange}
      />
    </div>
  );
}
```

The slider edits a *local* override that feeds the copy string and "Copy all" — it does **not** mutate the persisted prompt row. Regenerate / picking another history entry resets overrides.

- [ ] **Step 2: Implement `PromptPane.module.css`**

Create `frontend/src/components/organisms/PromptPane.module.css`:

```css
.pane {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: auto;
  height: 100%;
}

.section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.sectionHeader {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-subtle);
}

.textarea {
  width: 100%;
  min-height: 80px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px;
  color: var(--text);
  font-family: var(--font-mono);
  font-size: 12px;
  resize: vertical;
}

.loraList {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.copyRow {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.empty {
  color: var(--text-subtle);
  font-size: 13px;
}

.error {
  color: var(--danger);
  font-size: 13px;
}

.debug {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px;
  font-family: var(--font-mono);
  font-size: 11px;
  white-space: pre-wrap;
}

.history {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.historyItem {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text);
  text-align: left;
  padding: 6px 8px;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
}

.historyItem[aria-selected="true"] {
  border-color: var(--accent);
}
```

- [ ] **Step 3: Implement `PromptPane.tsx`**

Create `frontend/src/components/organisms/PromptPane.tsx`:

```tsx
import { useMemo, useState } from "react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { useLoras, type Lora } from "@/api/library";
import {
  useGeneratePrompt,
  usePrompts,
  type Prompt,
  type GeneratedPrompt,
  type Intent,
  type RetrievedIntent,
} from "@/api/prompts";
import type { Session } from "@/api/sessions";
import { classifyLora, PromptLoraRow } from "./PromptLoraRow";
import styles from "./PromptPane.module.css";

export function PromptPane({ session }: { session: Session }) {
  const prompts = usePrompts(session.id);
  const generate = useGeneratePrompt(session.id);
  const loras = useLoras();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [debugOpen, setDebugOpen] = useState(false);

  const list = prompts.data ?? [];
  const head: Prompt | null = list[0] ?? null;
  const visible: Prompt | null =
    selectedId == null ? head : list.find((p) => p.id === selectedId) ?? head;

  // Per-row weight override. Reset when the visible prompt changes.
  const [weights, setWeights] = useState<Record<string, number>>({});
  const visibleId = visible?.id ?? null;
  useMemo(() => {
    setWeights({});
  }, [visibleId]);
  const effectiveWeight = (spec: LoraSpec) =>
    weights[spec.name] ?? spec.weight;

  const knownByName = useMemo<Record<string, Lora>>(() => {
    const out: Record<string, Lora> = {};
    for (const l of loras.data ?? []) out[l.name] = l;
    return out;
  }, [loras.data]);

  const pinnedNames = useMemo(
    () => new Set(session.pinned_loras.map((p) => p.lora_name)),
    [session.pinned_loras],
  );
  const retrievedNames = useMemo(
    () => new Set((visible?.retrieved ?? []).flatMap((r) => r.results.map((h) => h.name))),
    [visible],
  );

  const loraString = useMemo(
    () =>
      (visible?.prompt.loras ?? [])
        .map((l) => `<lora:${l.name}:${effectiveWeight(l).toFixed(2)}>`)
        .join(" "),
    [visible, weights],
  );
  const fullString = useMemo(() => {
    if (!visible) return "";
    const p = visible.prompt;
    const parts = [p.positive, loraString].filter(Boolean);
    return parts.join("\n\n") + (p.negative ? `\n\nNEGATIVE:\n${p.negative}` : "");
  }, [visible, loraString]);

  const generateError =
    generate.error instanceof Error ? generate.error.message : null;

  function copy(text: string) {
    if (!text) return;
    void navigator.clipboard?.writeText(text);
  }

  return (
    <div className={styles.pane} aria-label="Prompt pane">
      <div className={styles.copyRow}>
        <Button
          size="sm"
          variant="primary"
          icon={<Icon name="Sparkles" size={12} />}
          onClick={() => generate.mutate()}
          disabled={generate.isPending || !session.vl_summary}
          title={
            !session.vl_summary
              ? "Run Analyze on the source image first"
              : visible
                ? "Regenerate"
                : "Generate prompt"
          }
        >
          {generate.isPending ? "Generating…" : visible ? "Regenerate" : "Generate"}
        </Button>
      </div>

      {generateError && (
        <div className={styles.error} role="alert">
          {generateError}
        </div>
      )}

      {!visible && !generate.isPending && (
        <div className={styles.empty}>
          No prompt yet. Click <b>Generate</b> to produce one from the current
          chat + source analysis.
        </div>
      )}

      {visible && (
        <>
          <PositiveSection prompt={visible.prompt} onCopy={copy} />
          {visible.prompt.negative !== null && (
            <NegativeSection prompt={visible.prompt} onCopy={copy} />
          )}
          <LoraSection
            prompt={visible.prompt}
            knownByName={knownByName}
            pinnedNames={pinnedNames}
            retrievedNames={retrievedNames}
            weights={weights}
            onWeightChange={(name, w) =>
              setWeights((prev) => ({ ...prev, [name]: w }))
            }
          />
          <div className={styles.copyRow}>
            <Button size="sm" onClick={() => copy(loraString)} disabled={!loraString}>
              Copy LoRA string
            </Button>
            <Button size="sm" onClick={() => copy(fullString)} disabled={!fullString}>
              Copy all
            </Button>
          </div>

          <div className={styles.section}>
            <div className={styles.sectionHeader}>
              <span>Debug</span>
              <Button size="sm" variant="ghost" onClick={() => setDebugOpen((v) => !v)}>
                {debugOpen ? "hide" : "show"}
              </Button>
            </div>
            {debugOpen && (
              <pre className={styles.debug}>
                {formatDebug(visible.intents, visible.retrieved)}
              </pre>
            )}
          </div>
        </>
      )}

      {list.length > 1 && (
        <div className={styles.section}>
          <div className={styles.sectionHeader}>History</div>
          <div className={styles.history}>
            {list.map((p) => (
              <button
                key={p.id}
                className={styles.historyItem}
                aria-selected={(visible?.id ?? -1) === p.id}
                onClick={() => setSelectedId(p.id)}
              >
                #{p.id} · {new Date(p.created_at * 1000).toLocaleTimeString()} ·{" "}
                {p.prompt.loras.length} lora
                {p.prompt.loras.length === 1 ? "" : "s"}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function PositiveSection({
  prompt, onCopy,
}: { prompt: GeneratedPrompt; onCopy: (s: string) => void }) {
  return (
    <div className={styles.section}>
      <div className={styles.sectionHeader}>
        <span>Positive</span>
        <Button size="sm" variant="ghost" onClick={() => onCopy(prompt.positive)}>
          copy
        </Button>
      </div>
      <textarea readOnly className={styles.textarea} value={prompt.positive} />
    </div>
  );
}

function NegativeSection({
  prompt, onCopy,
}: { prompt: GeneratedPrompt; onCopy: (s: string) => void }) {
  const value = prompt.negative ?? "";
  return (
    <div className={styles.section}>
      <div className={styles.sectionHeader}>
        <span>Negative</span>
        <Button size="sm" variant="ghost" onClick={() => onCopy(value)}>
          copy
        </Button>
      </div>
      <textarea readOnly className={styles.textarea} value={value} />
    </div>
  );
}

function LoraSection({
  prompt,
  knownByName,
  pinnedNames,
  retrievedNames,
  weights,
  onWeightChange,
}: {
  prompt: GeneratedPrompt;
  knownByName: Record<string, Lora>;
  pinnedNames: Set<string>;
  retrievedNames: Set<string>;
  weights: Record<string, number>;
  onWeightChange: (name: string, next: number) => void;
}) {
  return (
    <div className={styles.section}>
      <div className={styles.sectionHeader}>LoRAs ({prompt.loras.length})</div>
      <div className={styles.loraList}>
        {prompt.loras.map((spec) => {
          const kind = classifyLora(spec, {
            knownByName, pinnedNames, retrievedNames,
          });
          const triggers = knownByName[spec.name]?.trigger_words ?? [];
          return (
            <PromptLoraRow
              key={spec.name}
              spec={spec}
              kind={kind}
              triggers={triggers}
              weight={weights[spec.name] ?? spec.weight}
              onWeightChange={(w) => onWeightChange(spec.name, w)}
            />
          );
        })}
      </div>
    </div>
  );
}

function formatDebug(
  intents: Intent[] | null, retrieved: RetrievedIntent[] | null,
): string {
  if (!intents) return "(no intent debug — older prompt row)";
  const lines: string[] = [];
  for (const i of intents) {
    lines.push(`• ${i.kind}: ${i.query}`);
    const ri = retrieved?.find((r) => r.intent_query === i.query);
    if (ri) {
      for (const h of ri.results) {
        lines.push(`    - ${h.name}  (d=${h.distance.toFixed(3)})`);
      }
    }
  }
  return lines.join("\n");
}
```

- [ ] **Step 4: Implement the test**

Create `frontend/src/components/organisms/PromptPane.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PromptPane } from "./PromptPane";
import type { Session } from "@/api/sessions";
import * as promptsApi from "@/api/prompts";
import * as libraryApi from "@/api/library";

const session: Session = {
  id: "ses1",
  project_id: "p1",
  name: "s",
  model_name: "m1",
  use_negative: true,
  pinned_loras: [{ lora_name: "pinned-x", weight_override: null }],
  source_image_path: null,
  source_image_url: null,
  vl_summary: "summary",
  vl_model_name: null,
  prompt_model_name: "pm-1",
  created_at: 0,
  updated_at: 0,
};

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  vi.spyOn(libraryApi, "useLoras").mockReturnValue({
    data: [
      {
        name: "lora-known",
        display_name: "lora-known",
        description: "",
        tags: [],
        trigger_words: ["k_t"],
        family_id: "sdxl",
        recommended_weight: 0.5,
        author: null, version: null, source_url: null,
        created_at: 0, updated_at: 0, is_indexed: true,
      },
    ] as libraryApi.Lora[],
  } as ReturnType<typeof libraryApi.useLoras>);
});

describe("PromptPane", () => {
  it("renders empty state when no prompts and disables generate without vl_summary", () => {
    vi.spyOn(promptsApi, "usePrompts").mockReturnValue({
      data: [],
    } as ReturnType<typeof promptsApi.usePrompts>);
    vi.spyOn(promptsApi, "useGeneratePrompt").mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      error: null,
    } as unknown as ReturnType<typeof promptsApi.useGeneratePrompt>);

    wrap(<PromptPane session={{ ...session, vl_summary: null }} />);
    expect(screen.getByText(/No prompt yet/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Generate/i })).toBeDisabled();
  });

  it("renders positive, negative, and known + unknown LoRA badges", () => {
    vi.spyOn(promptsApi, "usePrompts").mockReturnValue({
      data: [
        {
          id: 1,
          session_id: session.id,
          prompt: {
            positive: "moody girl",
            negative: "blurry",
            loras: [
              { name: "lora-known", weight: 0.5 },
              { name: "ghost-lora", weight: 0.7 },
            ],
          },
          intents: [{ kind: "style", query: "moody" }],
          retrieved: [{ intent_index: 0, intent_query: "moody", results: [{ name: "lora-known", distance: 0.1 }] }],
          created_at: 0,
        },
      ],
    } as ReturnType<typeof promptsApi.usePrompts>);
    vi.spyOn(promptsApi, "useGeneratePrompt").mockReturnValue({
      mutate: vi.fn(), isPending: false, error: null,
    } as unknown as ReturnType<typeof promptsApi.useGeneratePrompt>);

    wrap(<PromptPane session={session} />);
    expect(screen.getByDisplayValue("moody girl")).toBeInTheDocument();
    expect(screen.getByDisplayValue("blurry")).toBeInTheDocument();
    expect(screen.getByText("lora-known")).toBeInTheDocument();
    expect(screen.getByText("ghost-lora")).toBeInTheDocument();
    expect(screen.getByText(/unknown/i)).toBeInTheDocument();
  });

  it("calls generate when Regenerate is clicked", () => {
    const mutate = vi.fn();
    vi.spyOn(promptsApi, "usePrompts").mockReturnValue({
      data: [{
        id: 9, session_id: session.id, intents: null, retrieved: null,
        prompt: { positive: "p", negative: "n", loras: [] }, created_at: 0,
      }],
    } as ReturnType<typeof promptsApi.usePrompts>);
    vi.spyOn(promptsApi, "useGeneratePrompt").mockReturnValue({
      mutate, isPending: false, error: null,
    } as unknown as ReturnType<typeof promptsApi.useGeneratePrompt>);

    wrap(<PromptPane session={session} />);
    fireEvent.click(screen.getByRole("button", { name: /Regenerate/i }));
    expect(mutate).toHaveBeenCalledTimes(1);
  });

  it("renders error from generate mutation", () => {
    vi.spyOn(promptsApi, "usePrompts").mockReturnValue({
      data: [],
    } as ReturnType<typeof promptsApi.usePrompts>);
    vi.spyOn(promptsApi, "useGeneratePrompt").mockReturnValue({
      mutate: vi.fn(), isPending: false, error: new Error("boom"),
    } as unknown as ReturnType<typeof promptsApi.useGeneratePrompt>);

    wrap(<PromptPane session={session} />);
    expect(screen.getByRole("alert")).toHaveTextContent("boom");
  });
});
```

- [ ] **Step 5: Tests pass**

```bash
cd frontend && pnpm vitest run src/components/organisms/PromptPane.test.tsx
```
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/organisms/PromptPane.tsx \
        frontend/src/components/organisms/PromptPane.module.css \
        frontend/src/components/organisms/PromptLoraRow.tsx \
        frontend/src/components/organisms/PromptPane.test.tsx
git commit -m "feat(slice-6): PromptPane organism with positive/negative/loras/copy/debug/history"
```

---

## Task 11 — Wire PromptPane into the workspace + enable ChatPane button

**Files:**
- Modify: `frontend/src/routes/workspace.tsx`
- Modify: `frontend/src/components/molecules/ChatPane.tsx`

- [ ] **Step 1: Replace the placeholder in `workspace.tsx`**

Find:

```tsx
<div className={styles.placeholder}>Prompt pane · coming in Slice 6</div>
```

Replace with:

```tsx
<PromptPane session={s} />
```

And add the import at the top:

```tsx
import { PromptPane } from "@/components/organisms/PromptPane";
```

- [ ] **Step 2: Wire the ChatPane button**

In `frontend/src/components/molecules/ChatPane.tsx`, change the disabled placeholder Button into a real action. Replace lines 128-135:

```tsx
<Button
  size="sm"
  icon={<Icon name="Sparkles" size={12} />}
  disabled
  title="Generate prompt — available in Slice 6"
>
  Generate prompt
</Button>
```

with:

```tsx
<Button
  size="sm"
  icon={<Icon name="Sparkles" size={12} />}
  onClick={() => generate.mutate()}
  disabled={generate.isPending || !session.vl_summary}
  title={
    !session.vl_summary
      ? "Run Analyze on the source image first"
      : "Generate prompt"
  }
>
  {generate.isPending ? "Generating…" : "Generate prompt"}
</Button>
```

Add at the top of `ChatPane.tsx`:

```tsx
import { useGeneratePrompt } from "@/api/prompts";
```

Inside `ChatPane(...)`, near the other hooks:

```tsx
const generate = useGeneratePrompt(session.id);
```

The mutation invalidates `["prompts", sessionId]`; PromptPane already subscribes to that via `usePrompts`, so the new prompt appears as soon as the mutation resolves. No extra wiring needed.

- [ ] **Step 3: Update `ChatPane.test.tsx` if it asserts the disabled state**

Open `frontend/src/components/molecules/ChatPane.test.tsx`. If a test asserts the literal title "Generate prompt — available in Slice 6", update it to assert that the button now becomes disabled only when `vl_summary` is missing. (If no such assertion exists, skip this step — record that you checked.)

- [ ] **Step 4: Smoke build + tests**

```bash
cd frontend && pnpm tsc --noEmit && pnpm vitest run
```
Expected: every test passes; type check is clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/workspace.tsx frontend/src/components/molecules/ChatPane.tsx
# include the test file only if you actually edited it
git commit -m "feat(slice-6): wire PromptPane into workspace; enable Generate prompt in ChatPane"
```

---

## Task 12 — Manual smoke (foreground browser walk-through)

**Files:** none (verification only).

This task verifies the full MVP loop end-to-end the same way a user will run it. **Do not skip.** Every previous task has unit-test coverage but the only test for "the whole thing works on the user's machine" is this walk-through.

- [ ] **Step 1: Start the backend in the background**

```bash
cd backend && uv run uvicorn app.main:app --port 8001
```
Run via `run_in_background: true`. Wait for `Application startup complete.`

- [ ] **Step 2: Start the frontend in the background**

```bash
cd frontend && pnpm dev --port 5173
```
Run via `run_in_background: true`. Wait for the Vite ready line.

- [ ] **Step 3: Drive the browser via chrome-devtools**

Open `http://localhost:5173/`. Through `take_snapshot` + `click` + `fill`:

1. **LMStudio settings:** Settings → LMStudio. Set `base_url=http://127.0.0.1:1234/v1`, click *Refresh from LMStudio*, enable a `prompt`-role model.
2. **Library:** create one Family (or reuse seeded `sdxl`), one Model under it, and at least 3 LoRAs with non-empty `description` + `tags`. Verify each new LoRA shows the `Indexed` badge (Slice-5 acceptance).
3. **Project & session:** create a project, create a session, pick the model, optionally pin one LoRA, set `use_negative=true`, set `prompt_model_name` in the drawer.
4. **Source:** drop a small JPEG into `SourceImagePane`, click *Analyze*; wait for the `vl_summary` chip.
5. **Chat:** send one message ("make it darker and more cinematic") and wait for the SSE stream to finish.
6. **Generate prompt:** click *Generate prompt* in `PromptPane` (or the button in `ChatPane`). Observe loading state, then a populated `positive`, `negative`, and LoRA list.
7. **Copy buttons:** click each copy button — `positive`, `negative`, `Copy LoRA string`, `Copy all`. Each must place expected text on the clipboard (use `evaluate_script` with `navigator.clipboard.readText()` if needed).
8. **Debug pane:** open it; verify intents → retrieved LoRAs are listed.
9. **Regenerate:** click again; verify a new prompt appears at the top of *History* and old one is selectable.
10. **Reload:** refresh the page; the most recent prompt and history must come back from `GET /prompts`.
11. **Unknown LoRA tolerance:** edit one persisted prompt's `loras_json` via `sqlite3` to include `{"name":"made-up","weight":0.7}`. Reload — that row must show with the ⚠ unknown badge but not crash the pane.

- [ ] **Step 4: Console + network checks**

`list_console_messages` — there must be no unhandled errors during the flow. `list_network_requests` — `/api/sessions/<id>/generate-prompt` should be 200; `/api/sessions/<id>/prompts` should be 200; no 4xx/5xx unless deliberately induced.

- [ ] **Step 5: Stop the background servers**

Stop both background processes (taskkill on Windows). Close the chrome-devtools page(s).

- [ ] **Step 6: Commit a one-line note in the README**

In repo-root `README.md`, under the existing "Running" or "Status" section (whichever is closer), add one line:

```
- Slice 6 (generate-prompt) shipped — full MVP loop is complete (see docs/superpowers/specs/2026-04-23-mvp-roadmap-design.md §4 Slice 6).
```

```bash
git add README.md
git commit -m "docs(slice-6): note that the full MVP generate-prompt loop is shipped"
```

---

## Acceptance checklist (mirror of roadmap §4 Slice 6)

After Task 12 is committed, all of the following must hold. Run the commands and confirm results before declaring the slice done.

- [ ] `cd backend && uv run pytest -q` → all green.
- [ ] `cd frontend && pnpm vitest run && pnpm tsc --noEmit` → all green.
- [ ] Manual walk-through (Task 12 Step 3) produced a structured prompt the user can paste into ComfyUI: positive + (optional) negative + `<lora:name:weight> ...` string.
- [ ] After full-page reload, both the latest prompt and the history list survive.
- [ ] An unknown LoRA in `prompts.loras_json` renders with a warning badge but is **not** dropped.
- [ ] If the LLM endpoint is offline, *Generate prompt* surfaces a 502 error message (visible in PromptPane), and **no** half-row appears in the `prompts` table.

---

## Out-of-scope reminders

If during implementation you find yourself reaching for any of these — **stop and leave them for a Post-MVP plan**:

- ComfyUI HTTP / WebSocket integration to actually run the prompt.
- VL critique of a result image (Step 6 in the original concept).
- Tool-calling / agent-style "model decides when to regenerate" wiring.
- Importing LoRA library from a folder of `.md` files.
- Auto-regenerate after every chat message.
- Migrating `tags` / `trigger_words` to junction tables for performance.

These are explicitly listed as roadmap §4 Slice 6 *Boundary*. Surface any of them as scope-creep risks in the PR description, do not implement.
