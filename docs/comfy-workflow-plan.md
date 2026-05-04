# ComfyUI direct-generation flow — implementation plan

This is a planning document, not part of the technical specification. It
captures the staged approach for adding direct ComfyUI generation (t2i
and i2i) to sd-chisel. Once a phase ships, the relevant parts move into
`docs/spec/technical_specifications.md` and stop living here.

## Status (2026-05-04)

**Phase 1 — shipped end-to-end.** The bones work: a comfy session can
be created against an uploaded workflow, the readiness panel walks
every unknown node through the four-stage import wizard, and once all
cards turn green the catalog is populated. Verified live against
ComfyUI 0.15.1 + LMStudio. Each subsection below is annotated with
**✅ shipped**, **⏭ deferred** (with rationale), or no marker (still
planned).

Open Phase 1 polish noted by the user:
- Visual огрехи across the new screens — to be polished later.
- LM Studio model selection for `comfy_import` is implicit (favourite
  model). Reasoning-distilled models can still produce empty content
  even with the bumped `max_tokens=6000` baseline; consider a
  dedicated `comfy_import_model_name` setting later.

**Phase 2 (slot mapping)** and **Phase 3 (generation execution)** are
untouched — sketches at the bottom of this doc are still the design.

## Context and end goal

Today sd-chisel's `prompt_orchestrator` ends at a **text prompt**
(`{positive, negative, loras[]}`) stored in the `prompts` table. The
user has to copy that into a separate ComfyUI / A1111 UI to actually
render an image.

The end goal is to let the user point sd-chisel at a local ComfyUI
install, pick one of *their own* ComfyUI workflows (a node graph), and
press **Generate** — sd-chisel fills in the slots (positive, negative,
seed, width / height, main image for i2i, LoRAs) and returns the
rendered image inside the session.

The hard part of "works with arbitrary workflows" is that every workflow
is just a dict of opaque nodes. To map our prompt fields onto a graph we
need a **semantic layer** that knows what each node does and which
inputs play which role. Building that semantic layer drives the first
phase: instead of pre-syncing every node, we grow the catalog
on-demand, gated by the workflow the user actually wants to run.

## Three phases, in order

1. **ComfyUI Workflow session + readiness gate.** ✅ shipped. A new
   session type. User uploads or picks a workflow, sees a
   node-readiness panel, and walks every unknown node through a staged
   import wizard until all are *ready*. Phase 1 ends there — no slot
   mapping, no generation. The catalog (`comfy_packs`, `comfy_nodes`)
   grows as a side effect of import. The library gained a Comfy Nodes
   section as a secondary view of what has been imported.

2. **Workflow slot mapping.** Pending. Once a workflow's nodes are
   all ready, propose a mapping from logical slots (positive prompt,
   negative prompt, seed, width / height, main image, LoRA stack,
   sampler params) onto specific node ids using the catalog's role
   hints. User confirms or edits.

3. **Generation execution.** Pending. `comfy_client` service, the
   actual queue + websocket cycle, image fetching, persistence,
   progress streaming over SSE.

This document specifies Phase 1 in detail and sketches Phases 2 and 3
at a level sufficient to confirm Phase 1's data model carries them.

---

## Phase 1 — ComfyUI Workflow session + node readiness gate

### Session lifecycle ✅ shipped

New `session_type = "comfy"` alongside the existing `i2i` and `t2i`
(both unchanged; they keep producing text prompts).

Creating a comfy session opens a two-step flow:
1. Pick a saved workflow from the user's library, **or** upload a new
   workflow JSON (API format only — what ComfyUI's "Save (API Format)"
   produces).
2. The session is bound to that workflow and opens.

A bound comfy session has two lifecycle states:

- `unready` — at least one node in the workflow is `needs config` or
  `not installed`. The session screen shows the **readiness panel
  only**. No chat, no generate.
- `ready` — every distinct class_type in the workflow is `ready`.
  Phase 1 keeps the user on the **same readiness panel** in this
  state — every card is green. Future iterations will attach more UI
  here (slot mapping in Phase 2, generation in Phase 3, plus other
  workflow-bound widgets we plan to add). For Phase 1 the screen is
  visibly "done, more to come" — implementers should not start
  sketching the post-readiness workspace yet.

### Workflow storage ✅ shipped

`comfy_workflows` table:
- `id`, `name`, `graph_json` (API-format, raw), `graph_hash` (sha256 of
  the canonicalized graph), `created_at`.
- Mode (`t2i` / `i2i`) is **not** stored on the workflow row —
  workflows are mode-agnostic; mode is interpreted at slot-mapping time
  in Phase 2.

On upload, compute `graph_hash`. If a workflow with the same hash
already exists, prompt the user: **replace** the existing row,
**rename** the new upload, or **cancel**. Replace overwrites in place.
(For Phase 1 no execution depends on workflow content yet, so overwrite
is safe; Phase 2 / 3 may need to revisit if sessions become coupled to
workflow content.)

### Node readiness model ✅ shipped

Each workflow references a set of distinct class_types. For each:

- **`ready`** — class_type is reported by `/api/object_info` AND
  `comfy_nodes` has a row with `description_md` and
  `inputs_semantic_json` populated, **OR** the row's
  `requires_semantic_config` flag is `false`.
- **`needs config`** — class_type is reported by `/api/object_info` but
  the catalog has no row, or has a partial row (semantic fields empty)
  AND `requires_semantic_config = true`. Both sub-cases collapse into
  the same UI bucket — the user just clicks **Import**.
- **`not installed`** — class_type is **not** in `/api/object_info`.
  We don't help the user install it; we explain they should install
  the pack in ComfyUI manually, then click **Refresh** on the card.
  Refresh re-queries `/api/object_info` only (no filesystem scan — if
  ComfyUI doesn't see the node, sd-chisel can't use it either).

The readiness panel renders one card per **distinct class_type** in the
workflow (not per node id — multiple `CLIPTextEncode` instances share
one card). Each card has a status badge and a primary action:

| Status         | Action                                                           |
| -------------- | ---------------------------------------------------------------- |
| ready          | Open detail view (read-only / edit semantics).                   |
| needs config   | Open the per-node **Import wizard** modal (described below).     |
| not installed  | Show install instructions + **Refresh** button.                  |

Session readiness is the AND over all cards. Phase 1 stops the moment
this AND becomes true.

### Per-node import wizard — staged ✅ shipped (per-stage resume ⏭ deferred)

The modal walks the user through four stages, visibly. Each stage shows
inputs and outputs. **Nothing is persisted until all four stages
succeed.** A failed stage shows an error and a Retry button.

Per-stage resume (the originally-planned "retry only the failed stage")
turned out unnecessary in practice — Locate pack and Fetch schema take
~50 ms total, the only slow stage is the LLM call. Phase 1's Retry
re-runs the whole wizard from scratch (~5 seconds end-to-end). Revisit
if/when LLM calls start costing real money or take >30 s routinely.

The static `__init__.py` parser the original plan called for in
Stage 1 was **dropped**: ComfyUI's own `/api/object_info` exposes a
`python_module` field per class_type that resolves directly to the
custom_nodes directory (or to a built-in module name). The wizard
locates packs through that field instead of an AST walk.

**Stage 1 — Locate pack.** Read `python_module` from `/api/object_info`
to resolve the class_type to a pack directory under
`<comfyui_path>/custom_nodes/` (or to the synthetic built-in pack).
Read the matching pack's `pyproject.toml` and `README.md`. Outputs:
pack name, repo URL, publisher, display name, version, raw README
markdown.

**Stage 2 — Fetch raw schema.** GET `/api/object_info` for this
class_type. Outputs: `inputs_raw_json`, `outputs_raw_json`, node
display name (from `NODE_DISPLAY_NAME_MAPPINGS` if present, else fall
back to class_type).

**Stage 3 — LLM enrichment.** Send `(pack README + raw schema + display
name + class_type)` to LMStudio. Ask for: a short markdown description
and a per-input `role_hint` annotation. Validate the response —
returned input names must exist in `inputs_raw_json`; `role_hint`
values must come from a closed enum (`positive_prompt | negative_prompt
| seed | steps | cfg | sampler | scheduler | denoise | width | height
| main_image | mask_image | lora_name | lora_weight |
lora_chain_anchor | checkpoint_name | vae_name | clip_skip | …`, with
`null` for inputs that don't carry a logical role). On validation
failure, surface the diff and let the user retry. Outputs:
`description_md`, `inputs_semantic_json`.

This call uses a new action `comfy_import` in the existing per-action
settings system (joining `analyze`, `chat`, `summarize`, `generate`).
Reasoning: the call has its own profile — low temperature so the model
doesn't invent input names, no need for the verbosity tuning of
`generate`. Defaults live in `app_settings` under
`default_comfy_import_settings`; per-session override is not needed
because import is global (per-`class_type`), not per-session.
Validation lives alongside the existing action bundles in
`action_settings.py`. A code-level baseline is in `BUILTIN_DEFAULTS`
(`temperature 0.1`, `max_tokens 6000`) so a fresh install runs the
wizard without manual tuning. The "Default sampling per action" row
on the LM Studio settings page exposes it for editing.

Implementation note from the smoke test: LMStudio's `json_schema`
response_format produces empty content silently with reasoning-distilled
models (the answer ends up in `reasoning_content` while
`message.content` is empty). The wizard uses
`response_format = "text"` plus a strict system prompt and a
brace-matching JSON extractor in front of `json.loads`, which handles
all model families consistently.

**Stage 4 — Persist.** Upsert `comfy_packs`. Insert `comfy_nodes` with
all four artefacts. Set `requires_semantic_config = true` by default
(see "deferred" below). Mark the card ready and recompute the
readiness gate.

### Storage model ✅ shipped (migrations 011-013)

**`comfy_packs`**:
- `name` (PK), `display_name`, `description`, `version`, `repo_url`,
  `publisher_id`, `dir_path` (relative to `comfyui_path`; NULL for
  built-in), `readme_md` (raw), `imported_at`.

**`comfy_nodes`**:
- `class_type` (PK), `pack_name` (FK), `display_name`, `category`
  (best-effort, optional)
- `inputs_raw_json` — exactly what `/api/object_info` returned.
  Source-of-truth for types, defaults, options, range. Stored
  alongside the semantic form, never replaced by it.
- `outputs_raw_json` — same idea for outputs.
- `inputs_semantic_json` — normalized per-input
  `[{name, role_hint, notes}]`. Editable. Validated against
  `inputs_raw_json` on every write.
- `description_md` — short markdown description.
- `requires_semantic_config` (bool, default `true`). Forward-compat
  flag for the deferred "auto-ready" detection (see open questions).
  Phase 1 never sets it `false`; the column exists so a future detector
  can flip it without a migration.
- `imported_at`, `last_seen_in_object_info_at`.

**`comfy_node_overrides`** — sparse table keyed by `class_type` holding
user edits to `description_md`, `inputs_semantic_json`, `category`.
Overlaid on read; survives any future re-import.

### Library — Comfy Nodes section (secondary surface) ✅ shipped

The library gains a **Comfy Nodes** section alongside `vec_loras`. It
is read-mostly: imports happen through the workflow session, not here.

- **Single search/list mixing packs and nodes**, ranked by relevance
  (matches ComfyUI's own in-canvas search behaviour).
- Filters: type (pack | node), pack, builtin/custom, has-description.
- **Pack detail**: pyproject metadata, rendered README, list of nodes
  imported from this pack, repo link.
- **Node detail**: display name, class_type, breadcrumb (`pack ›
  category › node`), `description_md` (with edit), `inputs_semantic_json`
  in an editor (each input has a `role_hint` dropdown), raw
  `INPUT_TYPES` schema collapsed at the bottom.
- Edits go to `comfy_node_overrides` and survive re-import.

### Settings — dedicated ComfyUI section ✅ shipped

ComfyUI settings get their own section in the settings UI alongside (not
mixed into) the existing LM Studio section. This mirrors the existing
`LmStudioSettings.tsx` organism pattern: same layout language, a
distinct card for ComfyUI on the settings page.

**Frontend:** new organism `ComfyUiSettings.tsx`, sibling of
`LmStudioSettings.tsx`. The settings page renders both organisms as
separate cards, each self-contained (own form state, own save button,
own connection check).

**Fields:**
- `comfyui_url` — HTTP base URL of the running ComfyUI. Default
  `http://127.0.0.1:8188`.
- `comfyui_path` — filesystem path to the ComfyUI install (e.g.
  `F:/VAIProjects/ComfyUI`). Required for Stage 1 of the import
  wizard, since that walks `custom_nodes/`.
- `comfyui_api_key` — optional auth header for ComfyUI, mirroring
  `lmstudio_api_key`. Most local ComfyUI deployments have no auth;
  the field exists so the same settings flow works against
  reverse-proxied or cloud ComfyUI without a follow-up migration.
  Phase 1 reads it but does not yet attach it to outbound requests
  (that lights up in Phase 3 when `comfy_client` ships); the
  connection check below honors it.

**Connection check** (button in the section, like LM Studio's):
- Verify `comfyui_url` is reachable via `GET /api/system_stats`. Show
  ComfyUI version on success.
- Verify `comfyui_path` exists, is a directory, and contains a
  `custom_nodes/` subdirectory. Show pack count on success.
- Both checks run in parallel; surface errors per field so the user
  can fix them independently.

**Storage:** fields live on `app_settings` (same singleton row that
already holds `lmstudio_url` etc.) — no separate table for two
fields. The "section" is a UI and API concern, not a schema split.

**API:** dedicated endpoints `GET /api/settings/comfyui` and
`PUT /api/settings/comfyui` so the frontend organism is self-contained
and saves don't go through the same payload as LM Studio. Connection
check exposed as `POST /api/settings/comfyui/check`.

### API surface (Phase 1) ✅ shipped

New endpoint groups, all under `/api/`. Annotations show what landed
vs what was simplified.

**Settings** (covered above):
- ✅ `GET /api/settings/comfyui` — read.
- ✅ `PUT /api/settings/comfyui` — write.
- ✅ `POST /api/settings/comfyui/check` — connection check (url + path,
  in parallel; honors `comfyui_api_key`).

**Workflows:**
- ✅ `POST /api/comfy/workflows` — upload. Returns the saved row, or a
  409 with `{conflict: "graph_hash", existing: {…}}` on duplicate;
  client re-submits with `?on_conflict=replace|rename`.
- ✅ `GET /api/comfy/workflows` — list summaries.
- ✅ `GET /api/comfy/workflows/{id}` — full graph.
- ✅ `DELETE /api/comfy/workflows/{id}` — 409 if a session still
  references it (FK is ON DELETE RESTRICT).

**Readiness (per session):**
- ✅ `GET /api/comfy/sessions/{id}/readiness` — recomputed every call.
- ⏭ `POST /api/comfy/sessions/{id}/readiness/refresh` — deferred.
  GET already re-polls `/api/object_info` on every request, so a
  separate refresh endpoint had no extra behaviour to attach. Add it
  back if/when caching shows up.

**Per-node import wizard:**
- ✅ `POST /api/comfy/nodes/{class_type}/import` — runs the four
  stages and streams events directly as SSE
  (`stage_started` / `stage_succeeded` / `stage_failed` / `done`).
  Single endpoint, no separate job_id state — the originally
  planned `/{job_id}/stream`, `/retry`, `/cancel` triplet
  collapsed because retry-from-scratch turned out fast enough not
  to need server-side resume bookkeeping. Worth revisiting if the
  LLM step ever costs real money or routinely takes >30 s.

**Catalog (library and node detail):**
- ✅ `GET /api/comfy/nodes` — list with `?q=` / `?pack=` /
  `?has_description=`.
- ✅ `GET /api/comfy/nodes/{class_type}` — full row, raw + semantic +
  description, with override merge applied.
- ✅ `PUT /api/comfy/nodes/{class_type}` — updates land in
  `comfy_node_overrides`. Pydantic `model_fields_set` distinguishes
  "leave alone" (field omitted) from "explicit clear" (field=null).
- ✅ `GET /api/comfy/packs` — list.
- ✅ `GET /api/comfy/packs/{name}` — full pack row including README.

### Out of scope for Phase 1

- Slot mapping for the workflow as a whole (Phase 2).
- Generation execution (Phase 3).
- Bulk catalog sync — there is no "Sync all nodes" button. Catalog
  growth is workflow-driven only.
- Detection of which class_types do not need semantic config. The
  `requires_semantic_config` flag is laid into the schema but never
  flipped to `false` in Phase 1; every node goes through the full
  import wizard regardless of how trivial it looks (Reroute,
  PrimitiveNode, VAEDecode etc.). See open questions.
- Vector search over the catalog.
- LoRA-list injection logic.

---

## Phase 2 — Workflow slot mapping (sketch, pending)

The catalog supplies `role_hint` annotations for every input of every
node in any imported workflow. Phase 2:

- Walk the workflow's `graph_json`; for each node, look up
  `comfy_nodes.inputs_semantic_json` to learn the role hints. Propose
  a `slot_map` linking logical slots to concrete `(node_id, input_name)`
  pairs. Heuristics (e.g. "positive_prompt = the longest text
  CLIPTextEncode") supplement role hints when several candidates exist.
- Slot map editor: per logical slot, dropdown of candidates with
  rationale. User confirms / edits / saves.
- Mode (`t2i` / `i2i`) is inferred from whether a `main_image` slot is
  required and resolves to a `LoadImage` node.
- Stored on `comfy_workflows.slot_map_json`. Illustrative shape:
  `{"positive_prompt": {"node": "6", "input": "text"},
    "seed": {"node": "3", "input": "seed"},
    "main_image": {"node": "10", "input": "image"}, …}`.

## Phase 3 — Generation execution (sketch, pending)

- `comfy_client.py` service mirroring `lmstudio_client.py`: one shared
  `client_id` per process, one persistent WS to `/ws?clientId=…`,
  per-job asyncio queues demuxed by `prompt_id`.
- Cycle: optional `/api/upload/image` for i2i main image → patch
  `graph_json` per `slot_map_json` and per-job overrides → POST
  `/api/prompt` → consume WS (`progress`, `executed`,
  `execution_success` / `execution_error`) → GET `/api/view` → persist
  under `data/images/<session_id>/generated/`.
- Stream progress to the client over SSE (same mechanism chat already
  uses).
- New endpoint that accepts an existing `prompt_id` from
  `prompt_orchestrator` (or runs the orchestrator first) and queues
  the bound workflow.

---

## Open questions (parked for later discussion)

Resolved since previous revisions:
- **When to do LLM enrichment** — at import time, synchronously, per
  node, with retry-from-scratch on failure.
- **LLM response_format** — `"text"` plus a strict system prompt and a
  brace-matching JSON extractor. `json_schema` was unreliable on
  reasoning-distilled models; LMStudio rejects `json_object`.
- **Per-stage retry vs whole-wizard retry** — whole wizard. The
  non-LLM stages cost ~50 ms each; building a job-state machine just
  for them was over-engineering. Section above flags this as worth
  revisiting if the LLM step ever costs real money.

Still parked:

### Q1. How to auto-detect nodes that don't need semantic config

Phase 1 treats every unknown node identically. Many nodes (`Reroute`,
`PrimitiveNode`, `VAEDecode`, `CheckpointLoaderSimple`, plain
`KSampler`, `EmptyLatentImage` …) don't carry slots we'd want to map
onto our prompt fields, and walking the user through a four-stage LLM
import for each is friction.

We agreed not to hardcode an allowlist. Possible later approaches:
- Heuristic over `inputs_raw_json`: nodes whose inputs are all wired
  upstream (no literal slots) likely don't need semantic config.
- LLM-side decision in Stage 3: "does this node carry any user-facing
  semantic role?" returning a boolean used to set
  `requires_semantic_config`.
- Class-type prefix matching against a curated set of "wiring" types
  the community agrees are pure plumbing.

When chosen, the Stage 4 persist step sets `requires_semantic_config`
accordingly and the readiness rule auto-greens those nodes.

### Q2. Vector search over `comfy_nodes`

`vec_comfy_nodes` parallel to `vec_loras` would let the user ask "find
a node that does inpainting" or "find a sampler with rectified flow".
Useful, especially as the catalog grows. Probably overkill for Phase 1.

### Q3. LoRA injection in Phase 3

Three options:
- **L1**: don't inject; show LoRAs as a reference list, user wires
  them themselves.
- **L3**: dynamically splice `LoraLoader` nodes into the graph at a
  designated `lora_chain_anchor`, rewiring model/clip edges.
- **L4**: require a stack node (`Power Lora Loader (rgthree)` or
  `LoraLoaderStack`) and fill its `lora_N` / `strength_N` slots.

### Q4. Phase 3 generate-screen UX

The earlier A / B / C variants partially collapse: comfy sessions are
already workflow-bound (the C-style binding is just *how* this session
type works), so what remains is the layout of the post-readiness
screen (parameter form, results gallery, parallel jobs, queue depth,
chat sidebar yes/no). To be designed when Phase 3 is on deck.

### Q5. Phase 3 minor decisions

- Generated-image table with rich metadata vs files-only on disk.
- Parallel jobs: per-session limit vs ComfyUI queue passthrough with
  queue-position display.
- Workflow versioning and what "replace" means once sessions actually
  execute against workflow content.

### Q6. Dedicated model selection for the import wizard

`comfy_import` currently uses whatever LM Studio model is marked as
favourite. That's good enough for a session-scoped chat model but
fragile for the wizard: reasoning-distilled models silently emit
empty `message.content` (the answer ends up in `reasoning_content`
that the OpenAI-compat surface ignores). A dedicated
`comfy_import_model_name` setting next to the bumped builtin
sampling defaults would let the user pin a known-good non-reasoning
model for this action. Surfaced during Phase 1 smoke-testing.

---

## Verification plan (Phase 1) ✅ done

Replaced the planned `__init__.py` parser tests with pack-locator
tests against `python_module` once that path was chosen.

- Unit tests for the `pyproject.toml` parser: missing
  `[tool.comfy]`, partial fields, unicode publishers, missing repo
  URL.
- Unit tests for the import wizard with a faked LMStudio. Each stage's
  failure paths: pack not found, class_type missing from
  `/api/object_info`, LLM returns invalid JSON, LLM hallucinates input
  names, LLM emits role hints outside the closed enum. Confirm
  partial state never reaches `comfy_nodes`.
- Unit tests for the readiness gate: combinations of `ready`,
  `needs config`, `not installed` cards; refresh transitions.
- Unit tests for workflow upload: hash collision prompt; rename path;
  replace path.
- Integration test against a real ComfyUI on `localhost:8188` with a
  fixture workflow JSON: walk the readiness gate end-to-end with
  real `/api/object_info`.
- Browser test via chrome-devtools MCP: create a comfy session,
  upload a workflow, walk the import modal for two or three nodes
  (mock LLM responses), assert the all-ready transition unlocks the
  session.

## Spec impact ⏳ pending

Phase 1 shipped but `docs/spec/technical_specifications.md` has not
been updated yet. Backlog for the next session:

- Add `comfy` to the session_type enum, with its `unready` /
  `ready` lifecycle.
- Add `comfy_packs`, `comfy_nodes`, `comfy_node_overrides`,
  `comfy_workflows` to the data model.
- Add `comfyui_url`, `comfyui_path`, and `comfyui_api_key` to settings.
- Add the new `comfy_import` action (alongside `analyze`, `chat`,
  `summarize`, `generate`), its `default_comfy_import_settings`
  app-level column, and the code-level `BUILTIN_DEFAULTS` baseline.
- Document the workflow-bound session creation flow and the per-node
  import wizard (4 stages, SSE event types, retry-from-scratch
  semantics).
- Add the Comfy Nodes library section.
- Note Phases 2 and 3 are still planned but not in scope.

This document remains for ongoing planning of Phases 2 and 3, the
parked open questions, and the polish items called out in the
**Status** section at the top.
