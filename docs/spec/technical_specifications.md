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

**Out of MVP:** direct ComfyUI integration, VL critique of the result
(step 6 — only an architectural placeholder).

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
  exactly one row per session is main, enforced by a unique partial
  index), `analysis` (free VL text, NULL until analyzed; overwritten by
  every re-analysis), and `analysis_prompt` (the optional refining
  instruction the user typed for the last run, NULL when none was
  provided). Only `i2i` sessions hold rows here. The canonical user- and
  LLM-facing identifier for each image is `Image_<image_number>` (e.g.
  `Image_3`); `original_filename` is metadata.
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
- **`prompts`** — append-only history of final prompts: `positive`,
  `negative` (NULL when `use_negative=0`), `loras_json` (what the LLM
  actually returned, verbatim, with no filtering of unknowns), plus the
  debug fields `intents_json`, `retrieved_loras_json`, and `brief` (the
  chat summary that fed this run, when one was supplied — NULL for
  manual generate calls without a brief).

**Session deletion** is transactional on both sides: cascade in the DB
(messages, prompts, pins) plus an application-level hook removes
`data/images/<session_id>/`.

### 3.3. Global settings and LMStudio model cache

- **`app_settings`** — single-row table (`id=1`):
  - `lmstudio_url`, `lmstudio_api_key` — the global LMStudio endpoint.
  - `show_hidden` — UI flag: whether to show hidden items across all
    lists.
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
loras, lm_models) carries a `hidden` column (0/1). The UI filters records
with `hidden=1` unless `app_settings.show_hidden` is set to `1`. A single
toggle on the Privacy page flips visibility globally. The point is privacy
for demo sessions and NSFW content in the library without deleting data.

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
persisted in `analysis_prompt` so the next re-analysis dialog can pre-fill
it. Re-running overwrites both fields. Only applicable to `i2i` sessions
— `t2i` sessions have no source images.

Prompt and chat composition consume the analyses as: the **main** row's
text is the primary "Source image analysis" labelled with its
`Image_<image_number>` identifier; every reference row that has its own
completed analysis is appended under a "Reference images" block as
`- Image_<image_number>: <analysis>` lines. References with no analysis
yet are silently skipped. The chat system prompt also tells the model
that the user may refer to images as `@Image_N` and that the model must
use the same form when referring back to them, never an
`original_filename`.

### 4.2. `chat` (SSE)

Pure streaming chat for discussing the desired changes — no tools, no
agent. History is normally append-only in `messages` (see §3.2 for the
one exception: history compaction). The endpoint speaks
Server-Sent Events with three payload types: `delta` (assistant text
chunks), `done` (final message id), `error`. The `prompt_model_name`
selected on the session is the only model used — `tool_use` capability
is no longer a requirement for chat (the field still exists on
`lm_models` and is consulted by library assistants).

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

It returns `GeneratedPrompt`:

- `positive` — required non-empty string.
- `negative` — string or `null` (when `session.use_negative = 0`).
- `loras` — array of `{name, weight}` with weight in `[-2.0, 2.0]`; may be
  empty.

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

### 4.4. Library assistants

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
  `retrieved` + `brief` inline in a single response. For a `t2i`
  session the endpoint currently returns 409 ("t2i prompt generation
  is not yet implemented") — the t2i flow is scoped to creation +
  display in this slice; full wiring is deferred. Generation also
  returns 409 when the session has no main image with a completed
  analysis.
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

Atomic design: `atoms/` (Button, Badge, Icon), `molecules/` (form blocks,
SourceImageCard, AnalyzeImageModal, AnalysisDetailModal, ImageLightbox,
MentionPopover, SessionSettingsDrawer), `organisms/` (LibraryCrud,
SourceImagesPane, PromptPane, ChatPane, GenerateModal, ProjectSidebar,
CRUD forms, LmStudioSettings, TaskIndicator), `templates/`
(WorkspaceLayout, LibraryLayout, AppShell).
Pages (`routes/`) are assembled from templates + organisms; data flows in
through TanStack Query hooks in `src/api/`.

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
  next to the model and pinned-loras chips. For `t2i` sessions the
  body grid is replaced with a "T2I workflow not yet implemented"
  placeholder; the header and SessionSettingsDrawer still render
  normally. The ChatPane composer supports an `@`-mention picker:
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
  `hidden` toggles and manual capability overrides.
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
  - `app/models/` — Pydantic schemas (including `GeneratedPrompt` and
    `IntentList`).
  - `app/cli/` — `init_db`, `dev`, `reindex_all`.
  - `tests/` — pytest, plus a fake-embedder fixture for hermetic tests.
- `frontend/` — Vite SPA.
  - `package.json`, `vite.config.ts`.
  - `src/api/` — TanStack Query hooks over REST/SSE.
  - `src/components/{atoms,molecules,organisms,templates}/`.
  - `src/routes/` — workspace, library/{families,models,loras},
    settings/{lmstudio,privacy}.
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

- LMStudio settings + capability detection (`vision`, `tool_use`,
  `reasoning`) + the `lm_models` cache + Unload all.
- Mode-specific prompt guides (`prompt_i2i`, `prompt_t2i`) — appended
  to the family `prompt_guide` during composition.
- Session types (`i2i` / `t2i`) chosen at creation on a dedicated
  screen and displayed as an immutable header badge. `i2i` is fully
  wired and consumes the family's mode-specific guide; `t2i` is a
  creation + display stub (workspace placeholder, generate-prompt
  refuses with 409).
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
