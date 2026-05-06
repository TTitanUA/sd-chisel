# sd-chisel — technical specifications

**Status:** living specification of the application's current state. Describes
behavior, not code. Updated after every completed task (see `CLAUDE.md` at
the repo root).

Supersedes the technical sections of `doc/concept.md` (the concept doc is
kept as the original motivation and prose rationale).

---

## 1. Goal and scope

A local Windows app — a prompt-writing assistant for i2i / t2i generation in
Stable Diffusion / ComfyUI. It owns:

1. Describing source images via a VL model in terms useful for generation.
2. Storing the user's library of LoRAs, checkpoints, and model families
   together with prompting rules (including mode-specific guidance for i2i
   and t2i).
3. A chat in which the agent picks suitable LoRAs from the library and
   produces ready-to-use positive / negative / LoRA strings.
4. AI assistants that help populate the library: they write a prompt guide
   for a family and metadata for a LoRA, including imports from Civitai.

Heavy work (indexing, assistants, imports) runs in the background through a
task registry, with live status updates pushed to the UI over SSE.

**MVP** (Slice 6) is shipped — the full loop `source → analyze → chat →
generate → copy structured prompt` works. Post-MVP work already in the tree:
LMStudio model capability detection, library assistants, Civitai import,
background tasks, privacy flags, rename flow for models and LoRAs.

**Out of MVP:** generation execution against ComfyUI (Phase 3 — node
catalog and slot mapping shipped, the queue/websocket cycle is
pending — see §10), VL critique of the result (step 6 — only an
architectural placeholder).

---

## 2. Architecture (high level)

- **Frontend:** Vite + React 18 + TypeScript SPA. Talks to the backend over
  REST for CRUD and over SSE for chat streaming and background tasks.
- **Backend:** FastAPI + uvicorn, single process. All LLM/VL calls go to a
  local LMStudio over OpenAI-compatible HTTP (via a direct `httpx` client,
  not the `openai` SDK).
- **LMStudio:** hosts LLM/VL models. Configured globally (base URL +
  optional API key); the models used for VL and prompt-writer calls are
  picked **per-session** by name from a cached list.
- **Storage:** a single `data/app.db` file (SQLite + sqlite-vec, foreign
  keys enabled, WAL mode for concurrent read/write during chat streaming
  and background tasks). Binary files (source images and optional results)
  live on disk separately.
- **Data path** — `./data/` relative to the repo root, fixed, no env vars.
  The backend resolves the path deterministically (walk up from the entry
  point). The whole `data/` folder is in `.gitignore`.

---

## 3. Data model

All structured state lives in `data/app.db`. Outside the DB, only image
binaries remain on disk under `data/images/<session_id>/`. The schema is
versioned by SQL migrations in `backend/migrations/`; the `db-init` command
applies them to an empty or existing DB.

### 3.1. Library: families, models, LoRAs

- **`families`** — a closed reference list of model families (sdxl, pony,
  illustrious, flux, etc.). Holds `display_name` and three prompt-guide
  fields: `prompt_guide` (general, required), `prompt_i2i` and `prompt_t2i`
  (optional, mode-specific). The LLM sees the relevant guide verbatim
  during prompt composition.
- **`models`** — checkpoints. PK is the file name without `.safetensors`.
  Stores `display_name`, a reference to the family (`ON DELETE RESTRICT`),
  optional `description` (delta rules on top of `family.prompt_guide`),
  `author`, `version`, `source_url`.
- **`loras`** — LoRAs. PK is the name used inside `<lora:name:weight>`.
  Stores `display_name`, a required markdown `description` (the LLM sees it
  verbatim), `tags` and `trigger_words` as JSON arrays,
  `recommended_weight`, a reference to the family (`ON DELETE RESTRICT`),
  plus optional `author` / `version` / `source_url`.
- **`vec_loras`** — sqlite-vec virtual table with embeddings of
  `description + tags + trigger_words`. The dimension is fixed by the chosen
  embedding model (`BAAI/bge-m3`, 1024-dim). Changing the embedding model =
  the `reindex-all` CLI: DROP + CREATE with the new dimension and a full
  reindex of all LoRAs.
- **`lora_vec_map`** — explicit `lora_name ↔ rowid` mapping for `vec_loras`
  (sqlite-vec does not allow FKs from a virtual table). `ON DELETE CASCADE`
  from `loras`.

**Conventions:**

- `tags` and `trigger_words` are JSON arrays; filtering goes through
  `json_each()`. Normalization into junction tables is deferred until there
  is a real need.
- Deleting a LoRA cascades into `lora_vec_map`; the row in `vec_loras` is
  dropped explicitly in the same transaction.
- Deleting a family is blocked by RESTRICT as long as models or LoRAs
  reference it.
- **Rename** for a model or LoRA is a dedicated flow (see §5.3): it changes
  the PK and updates all FKs atomically; the LoRA embedding is preserved
  (only `lora_vec_map.lora_name` is updated).

### 3.2. Projects, sessions, chat, prompt history

- **`projects`** — slug + display name and timestamps.
- **`sessions`** — belong to a project (`ON DELETE CASCADE`). Hold:
  - `name` (optional), `model_name` (FK → `models`, `ON DELETE SET NULL`).
  - `session_type` — `i2i` or `t2i`. Chosen at creation time and
    immutable thereafter (no PATCH path accepts it; the `SessionUpdate`
    schema has no field for it). Defaults to `i2i` for rows that
    pre-date the migration.
  - `use_negative` (0/1) — a workflow property: when `0`, the LLM returns
    `negative: null` and the frontend hides the block.
  - `vl_model_name` and `prompt_model_name` — *names* of the LMStudio
    models picked for the VL call and for the prompt-writer call. Base URL
    and API key are global (see §3.3).
  - `analyze_settings`, `chat_settings`, `summarize_settings`,
    `generate_settings` — per-action sampling-bundle JSON columns
    (nullable). Each holds an open-ended object whose keys are a subset
    of `temperature`, `top_p`, `top_k`, `max_tokens`,
    `presence_penalty`, `frequency_penalty`, `repeat_penalty`, `seed`.
    A NULL column means "inherit the entire app default" for that
    action; a non-NULL column inherits only the keys it does not
    specify (per-key fallback). See §4.4.
  - `result_image_path` — relative path to the rendered result binary
    (placeholder for step 6).
- **`session_source_images`** — child rows under a session (`ON DELETE
  CASCADE`). Each row is one uploaded source image with its own VL analysis.
  Fields: `id` (random hex), `session_id`, `path` (relative to `data/`),
  `original_filename` (kept for tooltips and downloads), `image_number`
  (1-based ordinal, unique per session, **never reused**: a new upload
  always gets `MAX(image_number) + 1`, so deletions leave permanent gaps —
  this is what guarantees that `Image_N` references in chat / prompt
  context stay unambiguous across delete + re-upload), `is_main` (0/1;
  for `i2i` exactly one row per session is main; for `t2i` every row
  is `is_main=0` — the unique partial index on `is_main = 1` permits
  zero-main sessions), `analysis` (free VL text, NULL until analyzed;
  overwritten by every re-analysis), and `analysis_prompt` (the
  optional refining instruction the user typed for the last run, NULL
  when none was provided). Both `i2i` and `t2i` sessions can hold rows
  here; for `t2i` every uploaded image is a reference. The canonical
  user- and LLM-facing identifier for each image is
  `Image_<image_number>` (e.g. `Image_3`); `original_filename` is
  metadata.
- **`session_pinned_loras`** — required LoRAs for a session: always added
  to the LLM context on top of the retrieved set. Optional `weight_override`
  on top of `recommended_weight`.
- **`messages`** — chat log, `role ∈ {user, assistant, system}`. Normally
  append-only; the one mutation is **history compaction** invoked from
  the Generate modal when the user opts in: every existing row is
  replaced atomically by a single assistant row whose content is the
  brief that fed the just-completed generation, prefixed with `Summary
  of previous discussion:`. The point is to keep the chat-context
  payload small for local models on subsequent turns.
- **`prompts`** — append-only history of final prompts. Two shapes
  share the same row:
  - **Legacy i2i / t2i** rows carry `positive` (required, possibly
    empty for `use_negative=0`), `negative` (NULL when
    `use_negative=0`), and `loras_json` (the LLM's verbatim LoRA
    list, no filtering of unknowns). `payload_json` is NULL.
  - **Comfy** rows carry `payload_json` — a JSON object keyed by the
    session's slot labels (each value matches the slot's `kind`) plus
    a reserved `__loras` key holding the LoRA list. `loras_json`
    mirrors `__loras` so the prompt panel's LoRA widget is
    shape-agnostic; `positive` is stored as `""` (the column is NOT
    NULL); `negative` is NULL. The read path treats `payload_json IS
    NOT NULL` as the discriminator.
  - Debug fields shared by both shapes: `intents_json`,
    `retrieved_loras_json`, and `brief` (the chat summary that fed
    this run, when one was supplied — NULL for manual generate calls
    without a brief).

**Session deletion** is transactional on both sides: cascade in the DB
(messages, prompts, pins) plus an application-level hook removes
`data/images/<session_id>/`.

### 3.3. Global settings and LMStudio model cache

- **`app_settings`** — single-row table (`id=1`):
  - `lmstudio_url`, `lmstudio_api_key` — the global LMStudio endpoint.
  - `show_hidden` — UI flag: whether to show hidden items across all
    lists.
  - `default_analyze_settings`, `default_chat_settings`,
    `default_summarize_settings`, `default_generate_settings` —
    app-wide default sampling bundles per action (JSON, nullable).
    Used as the live fallback for any session column left as
    inherit; see §4.4.
- **`lm_models`** — a cache of models known to LMStudio. Populated via a
  manual refresh from the UI:
  - `enabled` — hides the model from per-session dropdowns without
    removing it from the cache.
  - `last_seen` — when LMStudio last returned it from `/v1/models`.
  - `vision`, `tool_use`, `reasoning` — capabilities, auto-detected from
    the LMStudio metadata.
  - `favorite` — UI preference (lifts the model to the top of the list).

### 3.4. Privacy / hidden flags

Every entity that shows up in a list (projects, sessions, families, models,
loras, lm_models) carries a `hidden` column (0/1). When
`app_settings.show_hidden` is `0`, hidden records are filtered out
everywhere — not just in UI lists. For LoRAs specifically the gate is
enforced server-side in three places: the `GET /api/library/loras`
endpoint, the retriever's vector search, and the pinned-LoRA merge inside
the prompt orchestrator. The prompt LLM never sees a hidden LoRA as a
candidate while the toggle is off, even if the session has it pinned.
Setting `show_hidden=1` reveals hidden items globally without mutating
per-row state. The point is privacy for demo sessions and NSFW content in
the library without deleting data.

### 3.5. Binaries

Per-session image directory: `data/images/<session_id>/`. Inside it,
source images live in `data/images/<session_id>/sources/<image_id>.<ext>`
(one file per `session_source_images` row, named after its random id).
The optional `result.<ext>` for step 6 still sits at the session-dir
root. Flat structure keyed by `session_id`, no nesting under projects.
Deleting a session removes the entire folder; deleting a single source
image only unlinks its own file.

---

## 4. LLM flows

### 4.1. `analyze-source`

A single VL call against an LMStudio model with the `vision` capability,
run **per source image**. The system message is always present and
instructs the model to describe the image in terms useful for i2i
(composition, style, lighting, objects, mood). The user message depends
on whether the user typed a refining instruction when launching the
analysis:

- **No user instruction.** The user message is the standard "Describe
  this image for i2i prompt building."
- **User instruction provided.** The user message is the user's
  instruction sent verbatim — no default framing, no "additional
  guidance" wrapper. The user fully controls the user-side ask while the
  i2i-oriented system framing still applies.

The result is free text, stored on the row in
`session_source_images.analysis`. The refining instruction is also
persisted in `analysis_prompt` so the next re-analysis dialog can
pre-fill it. Re-running overwrites both fields. Both `i2i` and `t2i`
sessions can run analyse-source — for `t2i` every uploaded image is a
reference and consumed as such by the downstream chat / summarizer /
orchestrator.

Prompt and chat composition consume the analyses differently per
mode:

- **i2i** — the main row's text is the primary "Source image
  analysis" labelled with its `Image_<image_number>` identifier;
  every reference row that has its own completed analysis is
  appended under a "Reference images" block as
  `- Image_<image_number>: <analysis>` lines.
- **t2i** — there is no main row. Every analysed source image is
  rendered under a single "Reference images" block in the same
  bullet form. When no images have been analysed yet, the block is
  omitted entirely (pure text-to-image is legitimate).

References with no analysis yet are silently skipped in either mode.
The chat system prompt also tells the model that the user may refer
to images as `@Image_N` and that the model must use the same form
when referring back to them, never an `original_filename`.

### 4.2. `chat` (SSE)

Pure streaming chat for discussing the desired changes — no tools, no
agent. History is normally append-only in `messages` (see §3.2 for the
one exception: history compaction). The endpoint speaks
Server-Sent Events with three payload types: `delta` (assistant text
chunks), `done` (final message id), `error`. The `prompt_model_name`
selected on the session is the only model used — `tool_use` capability
is no longer a requirement for chat (the field still exists on
`lm_models` and is consulted by library assistants).

The chat system prompt has two variants picked by mode: an
`i2i` framing ("iterate on a Stable-Diffusion image-to-image idea")
and a `t2i` framing ("iterate on a text-to-image idea"). For `i2i` the
context block emits a labelled "Source image analysis (Image_N, main)"
followed by an optional "Reference images" bullet list. For `t2i` the
context block has no main label — every analysed source image goes
into a single "Reference images" block. With zero analysed sources
the context block is omitted entirely.

For comfy sessions mode is **inferred** from the bound workflow's
slot map (any wired `binding=user_image` slot ⇒ `i2i`, otherwise
`t2i`) — same rule the generate flow uses. Chat against a comfy
session also gets a slot-awareness block appended after the
mode framing: a one-line-per-slot list of `(group/label, kind,
description)` plus an explicit instruction to keep replies in plain
prose and never emit JSON or `slot: value` structures (composition
is a separate step). The block is omitted for comfy sessions whose
slot map is empty or unsaved, and for legacy `i2i` / `t2i` sessions.

The user message is persisted before streaming begins, but **rolled
back on any upstream failure** (LMStudio error or empty response). This
keeps retries clean — without rollback, a failed turn would leave an
orphan user row, and the next attempt would feed two consecutive user
messages to the model, which strict-template models reject. The frontend
restores the typed text into the input on error so nothing is lost.

Connection lifecycle for the streaming endpoint: validations and the
initial user-row insert run on the request-scoped connection; the
streaming generator opens its own short-lived connection (to the same
db file) for the assistant-row insert and the rollback path. The
request-scoped dependency is torn down before Starlette starts iterating
the response body, so the generator cannot reuse it.

When the chat history starts with assistant rows (which happens after
modal-driven compaction has replaced history with the brief recap), the
chat payload promotes those leading assistant rows to system messages
before the user turn. Some local models use jinja templates that fail
with "No user query found in messages" if the first non-system turn is
the assistant.

The chat exposes two delete operations and one edit-and-resend mode
alongside `POST .../chat`:

- `DELETE /api/sessions/{s}/messages/{id}` — remove a single message.
  Restricted to `role = "user"` rows; assistant/system rows return 409.
- `DELETE /api/sessions/{s}/messages` — drop every message in the
  session (clear chat).
- `POST .../chat` accepts an optional `replace_message_id`. When set,
  the request is treated as an *edit* of that user message: the server
  replaces its content with `body.content`, truncates every later
  message in the session (cascade by id), and streams a single fresh
  assistant reply — all atomically. No new user row is appended, so
  the history can never contain two consecutive user turns. On upstream
  failure the truncate+replace stays committed (the user explicitly
  asked for the edit); only the assistant reply is missing, and a
  follow-up regular send will produce one. The 404/409 rules match the
  delete endpoint: target must exist in the session and be a user row.

The frontend surfaces this through composer-driven editing rather than
inline bubble editing:

- The user bubble shows hover-revealed pencil and trash icons.
- Clicking the pencil sets the bubble's content into the composer
  textarea, highlights the bubble (accent outline + an "editing" tag
  in the meta line), and shows a banner above the composer with a
  cancel (×) button. Pressing Esc in the composer also cancels.
- The Send button changes to "Save & send"; pressing it issues `POST
  /chat` with `replace_message_id`. On success the editing state
  clears; on failure the messages query is invalidated and editing
  state is dropped (the truncate+replace landed; only the assistant
  reply is missing, and the user can re-send normally).
- A "Clear" button in the chat header calls the collection-DELETE
  endpoint after a confirm prompt.

Generation never fires from the chat itself. The user reaches a
direction in conversation and then clicks the explicit Generate button
on the prompt panel, which opens the Generate modal (§4.3.1).

### 4.3. Generate flow

#### 4.3.1. Modal-driven UX

Generation always goes through the Generate modal on the prompt panel.
Opening the modal triggers `POST /api/sessions/{s}/summarize-chat`,
which makes one LLM call (same `prompt_model_name`) to converge the
chat history plus the main image analysis into a brief of **user
intent** — what the user wants to change (i2i) or create (t2i).
The summarizer is deliberately model-agnostic and does not re-describe
the source image; the orchestrator already has the VL analyses and
family prompt guides for that. The output is plain markdown with a
`## Goal` paragraph and an optional `## Constraints` bullet list,
returned to the client together with a read-only context preview
(mode, model name + family, pinned LoRAs, `use_negative`, source-image
analyses, model description). Family prompt guides are deliberately
omitted from the preview — they belong to the model side of the
contract.

The brief is rendered as a **read-only** markdown preview — the
editing affordance is the chat itself. To refine the brief, the user
cancels the modal and continues the discussion; re-opening the modal
re-runs summarization against the updated chat. Cancelling makes no
server-side changes. Confirming sends
`POST /api/sessions/{s}/generate-prompt` with body
`{brief, compact_history}`, where `compact_history` is an opt-in
checkbox that, on success, invokes the §3.2 history compaction so the
chat starts from a clean summary on the next turn. The modal stays
open with disabled controls while the orchestrator runs, then closes
on success; failures stay inline for retry.

The modal is the only generation entry point — even with empty chat,
opening the modal still runs summarization (the brief falls back to a
neutral derivative of the source-image analysis) so the user has a
unified place to launch and review.

#### 4.3.2. Orchestrator stages

The orchestrator accepts an optional `brief` input. When set (the
modal flow always supplies one), the brief **replaces** chat history
in both the intent and the composition LLM payloads as a dedicated
`# User brief` block. Without a brief, the orchestrator falls back to
the last N chat messages as before.

**Step 1 — intent rewriting.** The LLM gets the VL summary, the last N
chat messages (or the brief, when provided), and an aggregated list of
known tags from `loras.tags`. It
returns a structured list of intents: `[{kind, query}]`, where:

- `kind` is a free-form string. The backend asks the LLM to reuse an
  existing tag if it fits; otherwise to invent a new one. The retriever
  uses `kind` as a pre-filter only when it matches an existing tag
  exactly; otherwise it ignores `kind` and retrieves by `query` without a
  filter. On cold start (empty library) the tag list is empty and the LLM
  generates `kind` freely.
- `query` is a search phrase in terms of *effect*, not a description of
  the picture.

**Step 2 — retrieval.** For each `intent`:

1. `query` is embedded (`BAAI/bge-m3`, multilingual).
2. Top-K against `vec_loras` (K ≈ 10–15 per intent), with an optional
   pre-filter by `family_id` of the chosen model and/or by a matching
   `kind` tag.
3. Results are merged and deduplicated by LoRA name.
4. The session's `pinned_loras` are added to the set.

**Step 3 — prompt composition.** A second LLM call receives:

- `family.prompt_guide` with the relevant `prompt_i2i` or `prompt_t2i`
  *appended* (when non-empty) — substitution is not used; the
  mode-specific text is additive on top of the general guide. The
  composition system message is also tagged with an explicit
  `# Mode: <i2i|t2i>` header so the LLM sees the mode unambiguously.
- `model.description` (when not null).
- Full `description` for every candidate (retrieved + pinned).
- The VL summary, plus either the last N chat messages or the
  `# User brief` block when the orchestrator was invoked with a brief.
- The instruction to return JSON conforming to a fixed schema.

The orchestrator branches on `session_type` for both the schema
shape and the precondition rules:

- **Legacy i2i / t2i sessions** return `GeneratedPrompt`:
  - `positive` — required non-empty string.
  - `negative` — string or `null` (when `session.use_negative = 0`).
  - `loras` — array of `{name, weight}` with weight in `[-2.0, 2.0]`;
    may be empty.
- **Comfy sessions** return `GeneratedPayload` — a JSON object whose
  keys are the session's slot labels (one field per `binding=llm`
  slot, typed by the slot's `kind`) plus a reserved `__loras` field
  with the same `[{name, weight}]` shape as the legacy LoRA list.
  The schema is built per-session from the workflow's slot map at
  composition time; the system message inlines a per-slot
  description (label, group, kind, binding) so the LLM understands
  the full workflow context, including frozen / image / lora slots
  it does not fill itself. See §10.7 for the dynamic-schema
  derivation rules. As with legacy composition, the response is
  parsed with the brace-matching JSON extractor (LMStudio's
  `json_schema` mode is unreliable on reasoning-distilled models).

**Mode handling.**

- **Legacy i2i** — requires a main source image with a completed
  analysis; the main analysis is rendered as the primary "Source
  image analysis" block, and any other analysed sources are
  appended as references.
- **Legacy t2i** — no main image is required; the orchestrator may
  even run with zero source images (pure text-to-image). Every
  analysed source goes under "Reference images". The composition
  system prompt picks up `# Mode: t2i` and the family's `prompt_t2i`
  appended on top of `prompt_guide` (vs. `prompt_i2i` for i2i). The
  intent-step system message also has a t2i-specific framing
  ("planner that turns a text-to-image brief…").
- **Comfy** — the mode (`i2i` / `t2i`) is **inferred** from the
  bound workflow's slot map at composition time: any wired
  `binding=user_image` slot ⇒ `i2i`, otherwise `t2i`. The same
  family-guide append rule applies (mode-specific text on top of
  `prompt_guide`). Comfy sessions never gate on a main source image
  — image bindings are wired by the patcher (Phase 3) — but any
  source-image analyses still feed the composition message when
  available.

**Conventions:**

- A LoRA whose `name` is missing from the `loras` table — the frontend
  shows ⚠ but still assembles the `<lora:name:weight>` string (lenient
  validation: the LLM may suggest a useful signal — a LoRA the user does
  not have yet).
- The backend writes `loras_json` into `prompts` verbatim, without
  filtering unknowns. Validation is purely formal (schema, weight range).
- Parameters (sampler / cfg / steps / denoise / size / seed) are **not**
  part of the schema — that is the user's / ComfyUI's concern.
- Explanations of "why this" go into a regular assistant chat message, not
  into the JSON.
- Conflicts between `family.prompt_guide` and a specific LoRA description
  are resolved in favor of the LoRA (trigger words win over general rules)
  — this is stated inside the prompt_guide itself.

### 4.4. Per-action sampling settings

Every LLM action the user can trigger — `analyze` (VL captioning),
`chat`, `summarize`, `generate` — has its own configurable bundle of
OpenAI-compatible sampling parameters (`temperature`, `top_p`,
`top_k`, `max_tokens`, `presence_penalty`, `frequency_penalty`,
`repeat_penalty`, `seed`). The schema is intentionally open-ended so
adding a new key is a UI-only change.

Two layers of storage:

- **App-wide defaults** in `app_settings.default_<action>_settings`
  (JSON, nullable). Edited from the LMStudio settings page. Empty
  means "let the model decide".
- **Per-session overrides** in `sessions.<action>_settings` (JSON,
  nullable). Edited from a gear button placed next to each
  action trigger (Send in chat, Analyze in the source-image modal,
  Summarize and Generate in the generate modal).

Resolution at request time: per-key merge — the session value wins
when present, otherwise the matching key from the app default is used.
A NULL session column means "inherit the full default bundle"; a
non-NULL session column inherits only the keys it does not specify.
The merged bundle is appended to the LMStudio chat-completions
payload. With both bundles empty no sampling keys are sent (matches
the historical behavior).

The same `generate` bundle is applied to both internal LLM calls in
the prompt orchestrator (intent extraction and composition) — they
share one tunable.

### 4.5. Library assistants

Help populate the library without manual copy-paste. They run as background
tasks (see §5.4) with live status streamed over SSE.

- **Family prompt guide assistant.** Takes the family name/description
  plus optional links or hand-written notes, and returns filled-in
  `prompt_guide`, `prompt_i2i`, `prompt_t2i`. Requires a `tool_use`-capable
  model.
- **LoRA metadata assistant.** Takes a Civitai URL or AIR (or manual
  data) and returns a filled-out card: `description` (markdown), `tags`,
  `trigger_words`, `recommended_weight`, `author`, `version`,
  `source_url`, and a `family_id` suggestion. Uses the Civitai importer
  (see §5.5) and the LLM to normalize the text.

---

## 5. Backend

**Stack:** Python 3.11+, FastAPI + uvicorn[standard], Pydantic v2, `httpx`
(direct LMStudio calls, no `openai` SDK), `sentence-transformers`,
`sqlite-vec`, `numpy`, `python-multipart`. Dev: `pytest`, `ruff`. There are
**no** dependencies on `langchain`, `llamaindex`, `watchdog`, `chromadb`,
`instructor` — see the concept doc for rationale; structured LLM output
goes through LMStudio's native `response_format`.

CLI commands (run via `uv run …` from `backend/`):

- `db-init` — applies migrations to `data/app.db`.
- `dev` — runs the API on `localhost:8000`.
- `reindex-all` — rebuilds `vec_loras` for every LoRA (cold start or
  embedding model change).

### 5.1. API surface (REST + SSE)

Prefix is `/api/`. Endpoints are grouped by domain.

- **Projects:** list, create, partial update, delete, toggle `hidden`.
- **Sessions:** list per project, create, read, partial update, delete,
  toggle `hidden`. The create payload requires `session_type`
  (`"i2i"` | `"t2i"`); it is not accepted on PATCH and cannot be
  changed after creation. Source images form a sub-resource at
  `/sessions/{s}/sources`: `GET` lists them (also embedded in the
  session payload), `POST` accepts a multipart upload (PNG/JPEG/WEBP)
  and creates one row — the first uploaded image is automatically
  marked `main`, later uploads are references; per-image `DELETE`
  removes the row plus its file (and promotes the oldest remaining row
  to `main` if the deleted one was main); `PATCH /sources/{id}/main`
  flips the main flag to that row; `POST /sources/{id}/analyze` accepts
  a JSON body `{ "refining_prompt": string | null }` and runs the VL
  call against that row's image. Chat (`POST /sessions/{s}/chat`, SSE).
  Chat summarization (`POST /sessions/{s}/summarize-chat`) — runs one
  LLM call to converge the chat plus main image analysis into a brief,
  returns `{brief, context}` where context is a read-only preview of
  what generation will see. Prompt generation
  (`POST /sessions/{s}/generate-prompt`) — body
  `{brief?: string, compact_history?: bool}`; `brief` (when present
  and non-empty) replaces chat history in the orchestrator pipeline,
  and `compact_history=true` triggers the §3.2 message compaction on
  success. Returns `prompt_id` + `GeneratedPrompt` + `intents` +
  `retrieved` + `brief` inline in a single response. Both `i2i` and
  `t2i` are wired end-to-end. For `i2i`, generation returns 409 when
  the session has no main image with a completed analysis. For
  `t2i`, no main image is required and generation may run with zero
  source images (pure text-to-image). The
  `PATCH /sources/{id}/main` endpoint returns 409 for `t2i` sessions
  ("t2i sessions have no main image"); uploads to a `t2i` session
  always store rows with `is_main = 0`.
- **Library / families:** list, read, create, replace, delete, toggle
  `hidden`, `POST /families/assist` (kicks off the assistant, returns a
  task id).
- **Library / models:** list, read, create, replace, delete, toggle
  `hidden`, `POST /models/{name}/rename` (atomic rename).
- **Library / loras:** list with filters (tag, family), read, create,
  replace, delete, toggle `hidden`, `POST /loras/{name}/rename`,
  `GET /loras/civitai-import` (preview by AIR/URL), `POST /loras/assist`.
- **Settings / LMStudio:** read/write `lmstudio_url` and `api_key`,
  `POST /refresh` (pulls the current model list into `lm_models` and
  refreshes capability flags), `POST /unload-all` (asks LMStudio to
  unload every loaded instance — to free VRAM), the `lm_models` list,
  partial updates of model flags (`enabled`, `favorite`, `hidden`,
  manual capability overrides).
- **Settings / Privacy:** read/write `show_hidden`.
- **Settings / Action defaults:** `GET /api/settings/action-defaults`
  returns the current four bundles (analyze, chat, summarize, generate).
  `PUT` accepts a partial body — only fields the client sends are
  persisted; passing an empty object clears all overrides for that
  action. Validation rejects unknown keys and out-of-range values with
  400. Per-session bundles are accepted on the regular session PATCH
  as optional fields (`analyze_settings`, `chat_settings`,
  `summarize_settings`, `generate_settings`); `null` clears the
  per-session override for that action.
- **Tasks:** `GET /api/tasks` (snapshot of all known tasks),
  `GET /api/tasks/stream` (SSE with deltas for creation / progress /
  completion).

For step 6 (post-MVP): `POST /sessions/{s}/result`,
`POST /sessions/{s}/analyze-result` — only an architectural placeholder
with a frontend stub.

### 5.2. LoRA indexer

- Triggers on every write/delete through `/api/library/loras` and on
  rename.
- The embedded text is `description + tags + trigger_words` joined by a
  separator.
- Upsert into `vec_loras` + `lora_vec_map` happens in the same transaction
  as the write to `loras`.
- Application startup runs a sweep: it finds LoRAs without an entry in
  `lora_vec_map` and queues them for reindex (as a background task). This
  covers the case where indexing earlier failed because the embedder was
  unavailable.
- The `reindex-all` CLI hands the task runner a full reindex (DROP +
  recreate the vec table when the dimension changes).

### 5.3. Renaming a model or LoRA

The name is the PK, so rename is non-trivial:

- Single transaction: check that the new name is unique, write the row
  with the new PK, update every FK (`models.name` → `sessions.model_name`;
  `loras.name` → `session_pinned_loras.lora_name` +
  `lora_vec_map.lora_name`), delete the old row.
- The embedding is preserved: `vec_loras.rowid` stays the same and only
  `lora_vec_map.lora_name` changes. There is no need to recompute the
  embedding for a pure rename.

### 5.4. Background task registry

A general-purpose mechanism for long-running operations (reindex, Civitai
import, assistants).

- An in-process registry with a unique id, status (`pending` / `running` /
  `done` / `error`), progress, last message, and an optional result.
- A pub/sub channel that the SSE endpoint `/api/tasks/stream` relays to
  the frontend.
- On subscribe the client gets the current snapshot of all known tasks
  plus deltas as events occur. The UI surfaces them in a global indicator
  and embeds them into assistant forms (the parent task → status streamed
  into the drawer).
- Startup sweep: queues a reindex for LoRAs missing an embedding plus any
  retry cases, so the user does not depend on running the CLI manually.

### 5.5. LMStudio client and Civitai importer

- **`lmstudio_client`** — a direct HTTP client over LMStudio's
  OpenAI-compatible endpoints: `/v1/models`, `/v1/chat/completions`,
  `/v1/completions` (for vision — chat completions with image content). It
  also uses LMStudio-specific endpoints to list loaded instances and to
  unload models (for the Unload all button). Capability detection is a
  combination of LMStudio metadata and manual overrides from `lm_models`.
- **`civitai`** — a parser for Civitai AIR identifiers and URLs, fetches
  the public model/version through the Civitai API, converts the
  description HTML to markdown, and normalizes `trigger_words` and `tags`.
  Used by both the manual import button and the LoRA assistant.

### 5.6. LLM round-trip logging

Every public `lmstudio_client` call emits one structured record to
`data/llm_log/<YYYY-MM-DD>.jsonl` (UTC date) with: timestamp, `run_id`,
call kind (`chat_stream`, `chat_stream_with_tools`, `chat_complete`,
`analyze_image`, `chat_responses_stream`, `list_models`,
`list_loaded_instance_ids`, `unload_model`), model name, full request
payload, assembled response (text deltas joined into a single string,
plus any tool call payload), duration, and any error. A `run_id`
context variable groups every call within a single user-facing turn —
one chat message produces up to four records (the user-visible
streaming reply plus, when a tool call fires, the orchestrator's intent
and composition completions plus the closing follow-up stream) all
sharing the same `run_id` so the whole flow is greppable as one logical
unit. Image binaries inside chat messages are redacted to
`<base64:Nb>` placeholders before they hit disk so the log stays
readable. Logging is on by default and can be disabled with
`SDCHISEL_LLM_LOG=0`; the test suite force-disables it via the
conftest.

A companion CLI at `scripts/debug_chat.py` drives a real session
through chat / summarization / orchestrator without going through the
HTTP layer. Modes: `list-sessions`, `inspect <id>`,
`chat <id> --message "..."`, `summarize <id>`,
`orchestrator <id> --brief "..."` (with optional `--no-persist`),
`tail-log [--follow]`. The harness is read-only against `data/app.db`
(chat mode never persists messages; orchestrator mode writes to
`prompts` unless `--no-persist`) and reuses the same logging path as
the live endpoints.

---

## 6. Frontend

**Stack:** Vite + React 18 + TypeScript, Radix UI (only the headless
primitives we need — Dialog), `lucide-react` (icons), Zustand (client
state), TanStack Query (server data, invalidation after mutations),
`react-router-dom`, `react-resizable-panels`, `@uiw/react-md-editor`
(markdown editor for description-like fields). CSS: PostCSS (autoprefixer
+ nested), per-component CSS modules + a shared `global.css` with design
tokens. No Tailwind, no shadcn. Package manager: pnpm.

### 6.1. Decomposition

Atomic design + per-feature folders:

- `components/atoms/` — global primitives (Button, Badge, Icon).
- `components/molecules/` — genuinely shared composites (ChatPane,
  Slider, FormField, ImageLightbox, MarkdownField, MentionPopover,
  SourceImageCard, AnalyzeImageModal, AnalysisDetailModal,
  TaskListPopover, …).
- `components/organisms/` — cross-feature organisms used by two or
  more features (ProjectSidebar, SessionSettingsDrawer,
  ActionSettingsModal, PromptPane, GenerateModal, SourceImagesPane,
  PromptLoraRow), plus library/settings page organisms (LibraryCrud,
  FamilyForm, ModelForm, LoraForm, LmStudioSettings, ComfyUiSettings).
- `components/templates/` — shell layouts (AppShell, WorkspaceLayout,
  LibraryLayout, SettingsLayout).
- `features/` — one folder per session type (`features/i2i/`,
  `features/t2i/`, `features/comfy/`). Each owns its workspace shell
  and any session-type-specific components (drawers, columns,
  inspector tabs, readiness gate, slot-map panel). The bias is
  **≥ 2 features ⇒ `components/`, exactly 1 feature ⇒ `features/`**.

Pages (`routes/`) are assembled from templates + features +
organisms; data flows in through TanStack Query hooks in `src/api/`.
`routes/workspace.tsx` is a thin three-way dispatch by
`session.session_type`.

### 6.2. Screens

- **Workspace** (`/projects/:p/sessions/:s`) — the main four-pane area:
  ProjectSidebar, SourceImagesPane, ResultImagePane (placeholder for
  step 6), ChatPane, PromptPane. The Sources pane shows a drag-drop
  zone (multi-file) plus a list of cards — one per uploaded image.
  Each card has the image preview on the left (with a star toggle that
  flips the `main` flag and a `main` badge on whichever row is main);
  clicking the preview opens a fullscreen lightbox (Radix Dialog) that
  shows the image at full size with ←/→ keys and chevron buttons to
  cycle through every source image in the session in `image_number`
  order, plus an `Image_N · n / total` counter and ESC to close. The
  card's centre column shows the canonical name `Image_<image_number>`
  on top, the original filename below it as a subdued subtitle, and a
  3-line clamped excerpt of the analysis (clicking the excerpt opens a
  modal with the full text). Per-row Analyze / Re-analyze + Delete
  buttons sit on the right. Analyze opens a modal with an optional
  refining-instruction textarea; the modal disables itself while the
  request is in flight and auto-closes on success (errors keep it open
  for retry). The header carries a session-type badge (`i2i` / `t2i`)
  next to the model and pinned-loras chips. The same three-pane grid
  renders for both modes; `t2i` sessions hide the per-card star
  toggle and the "main" badge (every uploaded image is a reference)
  and the empty-state hint switches to a t2i-specific copy. Generate
  in PromptPane is gated on a main-image analysis only for `i2i`;
  for `t2i` Generate is always reachable (subject to LMStudio /
  reindex availability), and the orchestrator may run with zero
  source images (pure text-to-image). The ChatPane composer supports an `@`-mention picker:
  typing `@` at the start of a token (start-of-input or after
  whitespace) opens a popover above the textarea listing every source
  image in the session as `Image_N` with the original filename as a
  subtitle. The query (substring after `@`) filters the list against
  `Image_N`, the bare number, and the original filename. ↑/↓ navigate,
  Enter or Tab inserts `@Image_N ` (with trailing space) replacing the
  trigger token, ESC dismisses, whitespace or moving the caret outside
  the token also closes it. The literal `@Image_N` text is sent to the
  backend verbatim; the LLM sees the matching identifier in its system
  prompt and is instructed to refer back to images using the same form.
  Assistant messages render as Markdown (GFM: headings, lists, tables,
  inline / fenced code, blockquotes); user messages are rendered as plain
  text so `@Image_N` and similar literals stay verbatim.
  A small **gear button** sits next to the Send button (chat) and next
  to the Analyze button in the per-image analyze modal; the Generate
  modal carries two gears in its header (one for Summarize, one for
  Generate). Each opens an `ActionSettingsModal` over the current
  session, where the user toggles Inherit / Override per sampling key
  with inline help text and a doc link. See §4.4.
- **New session** (`/projects/:p/sessions/new`) — a small form: pick
  the session type (i2i / t2i radio cards) and an optional name.
  Submitting POSTs to the sessions endpoint and navigates to the new
  workspace. The "New session" button in the sidebar links here rather
  than creating inline. Future per-session settings (model, pinned
  LoRAs, etc.) will land on this screen.
- **Project landing** (`/projects/:p`) — the project's session list.
- **Library:** `/library/families`, `/library/models`, `/library/loras` —
  CRUD tables with search and filters. Edit forms with markdown editors
  for `description` / `prompt_guide`. An inline rename block under the
  name field for models and LoRAs. Assistant launch buttons with an
  embedded live indicator for the corresponding task.
- **Settings / LMStudio** (`/settings/lmstudio`) — URL/API key config,
  Refresh, Unload all, an `lm_models` table with `enabled`, `favorite`,
  `hidden` toggles and manual capability overrides. Also hosts the
  app-wide **default sampling per action** rows: one row per action
  (analyze, chat, summarize, generate) with a gear button that opens
  the same `ActionSettingsModal` used by the action triggers (see
  §4.4).
- **Settings / Privacy** (`/settings/privacy`) — the `show_hidden`
  toggle.
- **SessionSettingsDrawer** — picks `model`, multi-checkbox/tag selector
  for pinned LoRAs, picks `vl_model_name` and `prompt_model_name` (each
  filtered by the relevant capability), `use_negative`.

### 6.3. PromptPane details

- Positive / Negative — two textareas with a character counter in the
  caption.
- LoRA list: one row per LoRA with a `pinned / retrieved / picked` badge,
  a weight slider, and trigger words (when the `name` is known; otherwise
  ⚠ and a weight editor without trigger words).
- A **Copy LoRA string** button assembles `<lora:a:0.6> <lora:b:0.8> ...`.
- Copy positive / Copy negative buttons — independent.
- Debug pane (collapsed by default): intents → retrieved LoRAs → picked.
- The Generate / Regenerate button opens the **GenerateModal**: a Radix
  Dialog that, on open, runs `POST /summarize-chat`, then shows the
  resulting brief as a **read-only** markdown preview alongside a
  context preview (mode, model + family, pinned LoRAs, `use_negative`,
  source-image analyses, and model description when available). Family
  prompt guides are deliberately not shown — they belong to the model.
  Refinement happens in the chat itself: cancel and continue the
  discussion, then re-open the modal to re-summarize. Optional
  "Compact chat history after generation" checkbox triggers §3.2
  message compaction. Generate launches the orchestrator with the
  brief; the modal stays open with disabled controls during the call
  and closes on success. Failures stay inline for retry. Cancel makes
  no server-side changes.

### 6.4. Hidden indicators

Anywhere an entity with `hidden` is rendered (sidebar, library tables, the
LMStudio table), an eye / eye-off icon is shown as a control. Hidden
entries appear in lists only when `show_hidden` is on.

### 6.5. Task indicator

The subscription to `/api/tasks/stream` lives globally. A header-level
indicator shows the count of active tasks; specific parent forms (LoRA
assistant, family assistant, import) embed the live status of their own
task into their own UI.

---

## 7. External dependencies

**Backend (runtime):** `fastapi`, `uvicorn[standard]`, `pydantic` v2,
`httpx`, `sentence-transformers` (`BAAI/bge-m3`, multilingual, 1024-dim —
the `vec_loras` dimension is tied to this choice; the first run pulls
~2 GB of weights into `~/.cache/huggingface/`), `sqlite-vec` (PyPI,
precompiled binaries for Windows), `numpy`, `python-multipart`. Dev
extras: `pytest`, `ruff`.

**Backend (intentionally absent):** `langchain`, `llamaindex`, `watchdog`,
`python-frontmatter`, `chromadb`, the `openai` SDK. A tool-calling agent
(post-MVP) will be considered on top of `langgraph` only as needed.

**Frontend:** `react`, `react-dom`, `vite`, `typescript`,
`@radix-ui/react-dialog` (other primitives — added on demand),
`lucide-react`, `postcss` + `autoprefixer` + `postcss-nested`, `zustand`,
`@tanstack/react-query`, `react-router-dom`, `react-resizable-panels`,
`@uiw/react-md-editor`. Tests: `vitest`, `@testing-library/*`, `jsdom`.

**External services:** LMStudio locally (chat / completions; embeddings are
done locally via `sentence-transformers`, not by LMStudio), the Civitai
public API for importing LoRA metadata.

---

## 8. Repo layout

- `backend/` — Python backend.
  - `pyproject.toml`, `migrations/*.sql` — DB schema versions.
  - `app/main.py` — FastAPI entry.
  - `app/api/` — REST/SSE endpoints (projects, sessions, chat, prompt,
    library, settings, tasks).
  - `app/services/` — embedder, indexer, retriever, prompt_builder,
    prompt_orchestrator, chat_summarizer, lmstudio_client, llm_log,
    civitai, lora_reindex, task_runner, library_service.
  - `app/storage/` — db init/migrations, library_repo, session_repo,
    settings_repo, images.
  - `app/models/` — Pydantic schemas (including `GeneratedPrompt`,
    `IntentList`, and the comfy slot / payload shapes).
  - `app/cli/` — `init_db`, `dev`, `reindex_all`.
  - `tests/` — pytest, plus a fake-embedder fixture for hermetic tests.
- `frontend/` — Vite SPA.
  - `package.json`, `vite.config.ts`.
  - `src/api/` — TanStack Query hooks over REST/SSE.
  - `src/components/{atoms,molecules,organisms,templates}/`.
  - `src/features/{i2i,t2i,comfy}/` — per-session-type workspace
    shells and session-type-specific components.
  - `src/routes/` — workspace (thin dispatch by session_type),
    library/{families,models,loras}, settings/{lmstudio,privacy}.
  - `src/store/` — Zustand store for client state.
  - `src/styles/`, `assets/`, `lib/`.
- `scripts/` — `dev.sh` / `dev.ps1` / `dev.mjs` (raise backend + frontend
  with one command, merging stdout with `[be]` / `[fe]` prefixes);
  `debug_chat.py` (drive a session through chat / orchestrator without
  the UI, see §5.6).
- `docs/` — the specification (this file).
- `doc/concept.md` — the original prose concept (historical).
- `mvp-ui-mock/` — design-system prototype (CSS tokens, primitives —
  ported into `frontend/src/styles/`).
- `data/` — runtime state (git-ignored): `app.db` +
  `images/<session_id>/` + `llm_log/<YYYY-MM-DD>.jsonl` (see §5.6).

---

## 9. MVP scope / out of MVP

**Shipped (MVP, Slice 6):**

- Projects + sessions (CRUD).
- Source upload, VL analysis.
- Chat (SSE).
- Generate-prompt (two-stage: intent rewriting + RAG retrieval +
  composition).
- Library CRUD for families / models / loras (UI + REST).
- LoRA indexer (automatic on upsert, plus a startup sweep).
- PromptPane with copy buttons.
- Pinned LoRAs and `use_negative` as session settings.

**Shipped post-MVP, already in this tree:**

- ComfyUI integration — Phase 1 (node-readiness gate + on-demand
  catalog growth), Phase 2, Phase 2.5 (workflow-declared, typed,
  labelled slot list with per-slot bindings — replaces Phase 2's
  fixed three-key model), and Phase 3 prep (dynamic orchestrator
  schema: comfy sessions produce a per-workflow `GeneratedPayload`
  keyed by slot label; chat is slot-aware; persistence keeps both
  legacy `GeneratedPrompt` and comfy `GeneratedPayload` shapes side
  by side via `prompts.payload_json`). Phase 3 (generation
  execution: graph patching, queue, websocket, result persistence)
  is still pending. See §10.

- LMStudio settings + capability detection (`vision`, `tool_use`,
  `reasoning`) + the `lm_models` cache + Unload all.
- Mode-specific prompt guides (`prompt_i2i`, `prompt_t2i`) — appended
  to the family `prompt_guide` during composition.
- Session types (`i2i` / `t2i`) chosen at creation on a dedicated
  screen and displayed as an immutable header badge. Both modes are
  wired end-to-end: chat / summarizer / orchestrator each pick the
  right framing and the family's mode-specific guide
  (`prompt_i2i` / `prompt_t2i`). `t2i` sessions store every uploaded
  image with `is_main = 0` (reference only); the `PATCH .../main`
  endpoint 409s on `t2i`, the workspace hides the main affordances,
  and the orchestrator runs with any number of analysed references
  (including zero).
- Privacy/hidden flags on every list entity + a global `show_hidden`.
- Rename flow for models and LoRAs that preserves embeddings.
- Background task registry + SSE indicator.
- Civitai import for LoRAs (parser + metadata fetch + UI button).
- Library assistants (family prompt guide + LoRA metadata) on top of the
  task registry.
- Generate modal flow: explicit two-step generation triggered from
  the prompt panel — chat summarization into an editable brief, then
  orchestrator with optional history compaction. Replaces the earlier
  in-chat tool-calling agent, which proved too dependent on local-model
  tool behavior to be reliable.

**Out of scope (architectural placeholders):**

- VL critique of the result (step 6) — UI placeholder, endpoint stub.
- Importing LoRAs from a local `.md` folder (CLI).
- Auto-export of the DB to a markdown dump or git-friendly snapshots.
- Sharing descriptions (DB export/import) as a UI feature.
- Normalizing `tags` / `trigger_words` into junction tables — only when
  performance or features demand it.
- LoRA usage stats, ratings, "last used" tracking.

---

## 10. ComfyUI integration

A separate session type sits next to `i2i` and `t2i`: the **comfy
session** binds a sd-chisel session to a user-uploaded ComfyUI
workflow (API-format JSON, the format ComfyUI's "Save (API Format)"
produces — UI-format graphs are rejected at upload). The end goal
is a single click that takes the prompt orchestrator's output and
renders an image in the bound workflow. Two phases have shipped;
the third (queue + websocket cycle) is still pending.

### 10.1. Settings

ComfyUI configuration lives on the singleton `app_settings` row,
exposed through its own settings card on the page (sibling of the
LM Studio card):

- `comfyui_url` — HTTP base URL of the running ComfyUI (default
  `http://127.0.0.1:8188`).
- `comfyui_path` — filesystem path to the ComfyUI install. Required
  for the import wizard's pack-locator stage.
- `comfyui_api_key` — optional auth header for reverse-proxied or
  cloud ComfyUI. Read but not yet attached to outbound requests
  outside the connection check (Phase 3 will use it).

Endpoints: `GET /api/settings/comfyui`, `PUT /api/settings/comfyui`,
`POST /api/settings/comfyui/check`. The check runs `GET /system_stats`
against the URL and verifies the install path contains `custom_nodes/`,
in parallel.

### 10.2. Comfy session lifecycle

`session_type = "comfy"` on `sessions`, with a non-null
`comfy_workflow_id` referencing `comfy_workflows(id)` (`ON DELETE
RESTRICT`). The workspace surface is:

- **Readiness gate (one-time).** Until every distinct `class_type`
  in the bound workflow's graph is `ready` (catalogued + installed),
  the workspace renders the readiness panel — one card per class,
  bucketed into `ready` / `needs_config` / `not_installed`. The user
  walks any `needs_config` cards through the per-node import wizard
  (§10.5) and resolves `not_installed` ones by installing packs in
  ComfyUI then pressing Refresh. Once `ready=true`, the gate flips
  off automatically and the workspace mounts.
- **Workspace shell (post-readiness).** A three-column layout:
  - **Left** — `ChatPane` plus a payload preview of the slot-keyed
    `GeneratedPayload` produced by the latest assistant turn.
  - **Centre** — gallery of past `comfy_jobs` runs, newest first.
    Phase 3 pins a running-job progress card to the top while in
    flight; Mock PR shows an empty state.
  - **Right rail** — tabbed inspector with five tabs:
    1. **Slots** — read-only summary of the slot map, grouped by
       `group`. A pencil icon opens the **slot-map drawer**, which
       wraps the same editor body that used to live in the full-
       screen "Step 2" — `Save` / `Discard` close it.
    2. **Bindings** — per-slot picker for every `binding=user_image`
       slot. Mock PR is read-only; Live PR persists picks as
       session-scoped state and feeds them into Phase 3's
       `payload_overrides[<label>]`.
    3. **Frozen** — per-session override editor for `binding=frozen`
       slots. Mock PR is read-only; Live PR adds kind-appropriate
       widgets and a "use slot-map value" toggle. Edits never write
       back to the slot map.
    4. **Sources** — image upload + thumbnails (the shared
       `SourceImagesPane`, with no `is_main` UI for comfy).
    5. **Nodes** — compact readiness summary. If a workflow replace
       regresses readiness (a class drops out of the catalog), the
       inline gate surfaces here — the user is not bounced back to
       a step machine.
- **Header.** Project / session crumbs, pinned-LoRA chip, a
  prominent **Generate** button (disabled in Mock PR, wired in Live
  PR), and `Session settings`.

There is no `compose` step or full-screen `slot_map` / `nodes` step
— the slot-map editor is a drawer; readiness regressions surface in
the Nodes tab. Generation (Phase 3) will gate on "every slot the
session needs is filled" once it ships; the Brief drawer + SSE
progress described in the Phase 3 plan replaces the existing
GenerateModal for comfy sessions.

The session's mode (`i2i` / `t2i`) for the family-prompt-guide
append (§4.x) is **inferred** from the slot list at composition
time: any wired `binding=user_image` slot ⇒ `i2i`, otherwise
`t2i`. Computed on demand — no cached column on `sessions`.
Legacy `i2i` / `t2i` (non-comfy) sessions keep their explicit
`session_type` column.

### 10.3. Workflow uploads

`comfy_workflows` stores API-format graphs alongside `graph_hash`
(sha256 of the canonicalised graph) and `slot_map_json` (Phase 2,
see §10.6). Endpoints:

- `POST /api/comfy/workflows` — upload. `?on_conflict=error|replace
  |rename` controls duplicate-hash behaviour; the `error` default
  returns 409 with the existing summary so the client can prompt
  the user.
- `GET /api/comfy/workflows`, `GET /api/comfy/workflows/{id}` —
  list/detail.
- `DELETE /api/comfy/workflows/{id}` — 409 if any session still
  references the workflow.

Mode (`t2i` / `i2i`) is **not** stored on the workflow row; it is
inferred from the slot list at composition / chat time — any wired
`binding=user_image` slot ⇒ `i2i`, otherwise `t2i`. See §10.6 / §10.7.

### 10.4. Catalog (`comfy_packs`, `comfy_nodes`)

Catalog rows grow on demand through the import wizard, never via a
bulk sync. The schema:

- **`comfy_packs`** — one row per pack discovered under
  `<comfyui_path>/custom_nodes/`, plus a synthetic `ComfyUI` row
  for built-in nodes. Metadata sourced from `pyproject.toml`
  (`name`, `display_name`, `description`, `version`, `repo_url`,
  `publisher_id`) plus the cached `readme_md`.
- **`comfy_nodes`** — one row per imported `class_type`. Stores
  the raw `INPUT_TYPES` schema from `/api/object_info`
  (`inputs_raw_json`, `outputs_raw_json`) alongside the catalog's
  enriched view: `display_name`, `category`, `description_md`,
  and `inputs_semantic_json` (a `[{name, notes}]` list of optional
  per-input notes; older rows may carry a `role_hint` key from
  Phase 1 which the read path silently strips). The
  `requires_semantic_config` boolean is a forward-compat flag for a
  not-yet-implemented "auto-ready" detector — Phase 1/2 always
  write `1`.
- **`comfy_node_overrides`** — sparse table holding user edits to
  `description_md`, `inputs_semantic_json`, `category`. Overlaid
  on read; survives re-import.

The library gains a **Comfy Nodes** section that lists packs and
nodes side by side, with detail panes for each. The node-detail
editor lets the user edit description and per-input notes; edits
land in `comfy_node_overrides`. Endpoints: `GET /api/comfy/packs`,
`GET /api/comfy/packs/{name}`, `GET /api/comfy/nodes`,
`GET /api/comfy/nodes/{class_type}`, `PUT /api/comfy/nodes/{class_type}`.

### 10.5. Per-node import wizard

`POST /api/comfy/nodes/{class_type}/import` runs four stages and
streams them as Server-Sent Events
(`stage_started` / `stage_succeeded` / `stage_failed` / `done`):

1. **Locate pack.** Reads `python_module` from `/api/object_info`,
   resolves it to a directory under `custom_nodes/` (or to the
   built-in pack), parses the matching `pyproject.toml` and reads
   the `README.md`.
2. **Fetch raw schema.** Pulls `INPUT_TYPES` and outputs from
   `/api/object_info` for the class_type.
3. **LLM enrichment.** Sends `(pack README + raw schema + display
   name + class_type)` to LMStudio. Asks for a short markdown
   description (`description_md`) and an optional list of
   per-input `notes`. The system prompt is strict enough to use
   `response_format = "text"` with a brace-matching JSON
   extractor (LMStudio's `json_schema` mode silently produces
   empty content on reasoning-distilled models). Validates that
   every `name` exists in the raw schema.
4. **Persist.** Upserts `comfy_packs` and `comfy_nodes` atomically.

Failures abort the run; retry re-POSTs the endpoint and re-runs all
four stages from scratch — there's no per-stage resume bookkeeping
on the server.

The wizard uses a dedicated `comfy_import` action in the
per-action sampling-bundle system (§4 alongside `analyze`, `chat`,
`summarize`, `generate`). Defaults live on
`app_settings.default_comfy_import_settings`; a code-level
`BUILTIN_DEFAULTS` baseline (`temperature 0.1`, `max_tokens 6000`)
makes a fresh install runnable without manual tuning. The model
itself is the user's favourite LMStudio model — a dedicated
`comfy_import_model_name` setting is parked for Phase 1 polish.

### 10.6. Workflow slot mapping

The slot map is a **per-workflow list of labelled, typed slots**
that sd-chisel binds to concrete `(node_id, input_name)` pairs in
the workflow graph. Each slot carries a label, an optional group,
a typed `kind`, an `origin`, a `binding` (who supplies the value
at generation time), and per-kind metadata. The shape replaces
Phase 2's fixed three-key dict.

#### Slot kinds

A closed enum, set per slot:

- `text`, `multiline_text` — `STRING` inputs in the graph.
  Multiline is set from the `STRING` widget's `multiline` flag.
- `image`, `image_alpha` — combos flagged `image_upload=true` /
  `mask=true` in the catalog's raw schema (LoadImage-style
  pickers).
- `number_int`, `number_float`, `boolean` — primitive scalars
  (INT / FLOAT / BOOLEAN widgets). Range / step / default are
  carried over from the schema in the candidate's metadata.
- `enum` — a generic combo, exposed with the candidate options.
- `lora_name`, `checkpoint_name` — combos whose options are
  filename lists ending in `.safetensors` / `.ckpt` / etc., and
  whose input name implies the file role (`lora_name`,
  `ckpt_name`, `checkpoint_*`).

#### Slot bindings

Who fills the value at generation time:

- `llm` — the composition LLM call (Phase 3 prep). Default for
  text and number kinds.
- `frozen` — the value is fixed at slot-map config time and reused
  on every generation, stored on the slot's `metadata.value`.
  Default for non-text scalars and the file-name combo kinds.
- `user_image` — picked from the session's source images at
  generate time. Default for image / image_alpha kinds.
- `library_loras` — sd-chisel's LoRA retriever. Reserved in the
  enum for the L4 milestone; not selectable from the editor and
  rejected by the validator.

The per-kind allow-list is fixed: text / number / boolean / enum
slots accept `llm` or `frozen`; image / image_alpha accept
`user_image` or `frozen`; `lora_name` / `checkpoint_name` accept
only `frozen` until L4 ships.

#### Candidate discovery

The service walks `graph_json` and classifies every literal-valued
input by `kind`, returning one candidate bucket per kind. Catalog-
known classes use the cached `inputs_raw_json` schema to detect
combo subtypes (`image_upload`, `mask`, lora / checkpoint
filename lists). Uncatalogued classes fall back to a soft
heuristic on the literal value alone — primitive scalars and
plain strings are still classified, but combo subtypes can't be
detected without the catalog. Each candidate carries
`(node_id, input_name, node_class_type, node_display_name,
node_title, node_in_catalog, current_value, kind, metadata)`.

#### Persistence and lazy upgrade

`comfy_workflows.slot_map_json` holds the saved map as
`{"version": 2, "slots": [...]}`. Older Phase 2 rows (the
three-key dict, no version key) are upgraded **lazily on read**
by the service: each non-null legacy assignment becomes a slot
with the matching default label (`positive_prompt`,
`negative_prompt`, `main_image`), kind borrowed from the
candidate, and binding (`llm` for the prompts, `user_image` for
the image). Empty / unmatched legacy keys collapse to an empty
slot list. The upgraded shape is written back the first time the
slot map is saved through `PUT /slot_map`. The column is JSON,
no migration SQL was needed.

#### API surface

- `GET /api/comfy/sessions/{id}/slot_map` — recomputes candidates
  every call, runs the lazy upgrade against any saved row, and
  returns
  `{session_id, workflow_id, slot_map: {version, slots[]},
  candidates: {<kind>: [...]}, inferred_mode}`. Every kind bucket
  is always present (empty list when no eligible inputs).
  `inferred_mode` is `i2i` if the slot list contains any wired
  `binding=user_image` slot, else `t2i`.
- `PUT /api/comfy/sessions/{id}/slot_map` — full-replace write
  with body `{slots: [...]}`. Validation rejects (422) duplicate
  labels, origins that don't match a candidate of the slot's
  declared kind, bindings outside the per-kind allow-list, and
  frozen scalars whose value falls outside the candidate's
  declared range / options. The legacy `positive_prompt` /
  `negative_prompt` / `main_image` keys are **not** part of the
  request contract — clients always send and receive the slot
  list.

Slots are independent: saving partial lists is fine; generation
(Phase 3) will simply skip the unbound graph inputs and let the
workflow's baked literals stand.

### 10.7. Phase 3 prep — dynamic orchestrator schema

The orchestrator (§4.3) branches on `session_type`. Comfy sessions
produce a `GeneratedPayload` rather than the legacy
`GeneratedPrompt`; the rest of the pipeline (intents, retrieval,
LoRA candidates, brief / chat tail) is shared.

**Dynamic schema.** At composition time, the orchestrator loads the
bound workflow's slot map (upgraded to v2 by §10.6's lazy upgrade)
and derives:

- A schema-hint block enumerating each `binding=llm` slot's label and
  JSON shape (string / integer / number / boolean / enum-with-
  options) plus a reserved `__loras` field carrying the same
  `[{name, weight}]` list legacy `loras` had. The block is inlined
  into the composition system message. Slots with `binding=frozen`,
  `binding=user_image`, or `binding=library_loras` are NOT part of
  the LLM-facing schema.
- A workflow-slots context block listing every slot (including the
  non-llm ones) so the LLM sees the full graph shape: each row
  shows the binding tag (`[fill]` / `[frozen=<value>]` /
  `[user image]` / `[library loras]`), label (with optional
  `<group>/` prefix), kind chip, and description.

**Validation.** The composition response is parsed with the same
brace-matching JSON extractor `comfy_import` uses, then validated
per-slot: every `binding=llm` slot must be present and its value
must match the slot's kind (booleans rejected for int slots,
numbers checked against any `min` / `max`, enum values checked
against the candidate's options). Malformed payloads bubble up as
`LmError("shape", ...)` the same way malformed `GeneratedPrompt`
responses do today.

**LoRA strategy (L1).** The reserved `__loras` field is split off
the validated payload and persisted into the legacy `loras_json`
column so the prompt-pane LoRA widget stays shape-agnostic. No
graph mutation happens — LoRAs surface for inspection / copy-paste
only, exactly like legacy sessions. L4 (binding `library_loras`
into stack-capable nodes) is deferred per the comfy plan's LoRA
section; the binding stays in the enum but is not selectable from
the editor and rejected by the slot-map validator.

**Mode inference.** The orchestrator and chat both derive the comfy
session's mode (`i2i` / `t2i`) from the bound workflow's slot map:
any wired `binding=user_image` slot ⇒ `i2i`, otherwise `t2i`.
Computed on demand — no cached column on `sessions`. Generalises
the inference rule §10.3 already established for the fixed
`main_image` slot to any `binding=user_image` slot.

**Generate modal preview.** When the modal opens against a comfy
session, the read-only context preview renders the slot list
grouped by `group` instead of (or alongside) the legacy
positive / negative / loras column. Each row shows the slot's
label, kind, binding, and frozen value where applicable. The
brief, source-image analyses, and pinned-LoRA blocks render the
same as legacy sessions. Editing slot values from the modal is
out of scope for 3-prep — the modal stays read-only across all
bindings; refinement still goes through chat.

**Persistence.** A row in `prompts` for a comfy session carries
`payload_json` (the validated payload, sans `__loras`) and the
mirrored LoRA list in `loras_json` (the discriminator is
`payload_json IS NOT NULL`). The `intents_json`,
`retrieved_loras_json`, and `brief` debug fields keep their
meaning unchanged. One migration adds the column.

**What's still pending (Phase 3).** The catalogue, readiness gate,
slot-map editor, dynamic-schema composition, persistence, and the
redesigned three-column workspace shell (§10.2 — chat + gallery +
tabbed inspector, with the slot-map drawer in place of the old
full-screen step) are in place; what remains is the actual
generation cycle: a `comfy_client` service mirroring
`lmstudio_client.py`, image upload, workflow patching per
`slot_map_json`, queueing via `/api/prompt`, the websocket consumer
for progress events, result fetching + persistence, the running-job
progress card and gallery cards in the centre column, the live
session-scoped state for the Bindings / Frozen rail tabs, and the
Brief drawer + SSE wiring for the header `Generate` button (it
replaces the `GenerateModal` for comfy). None of this exists yet —
the comfy workspace ends at slot mapping plus payload composition
for now.
