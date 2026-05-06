# ComfyUI direct-generation flow — implementation plan

This is a planning document, not part of the technical specification. It
captures the staged approach for adding direct ComfyUI generation to
sd-chisel. Once a phase ships, the relevant parts move into
`docs/spec/technical_specifications.md` and stop living here.

## Status (2026-05-06)

**Phase 1 — shipped (post-MVP).** Comfy session type, workflow upload,
readiness gate, per-node import wizard, on-demand catalog growth,
Comfy Nodes library section, dedicated ComfyUI settings card. Live
against ComfyUI 0.15.1 + LMStudio. Detail in spec §10.1–10.5.

**Phase 2 — shipped, design widening.** A fixed three-slot map
(`positive_prompt`, `negative_prompt`, `main_image`) with a manual
candidate-from-graph editor. Works for canonical single-sampler
SD/SDXL pipelines. **Cannot express** workflows with two or more
positive prompts — Base+Refiner SDXL, Flux 2 two-stage, HiRes-fix
with its own prompt, regional / Attention-Couple / multi-character
graphs, ConditioningCombine blends. Real graphs the user runs go
to ten or more text inputs each, and the current model collapses
all of them onto a single string.

**New direction.** This document below redesigns the slot system
around **workflow-declared, labelled, typed slots** with a
**dynamic orchestrator schema** derived per session. The decision
follows a survey of how the wider ComfyUI ecosystem handles the
same problem (ComfyDeploy, SwarmUI, Krita AI Diffusion, ViewComfy,
ComfyUI-Workflow-Component, native Subgraph) — every serious tool
treats workflow inputs as a per-workflow contract; none model
multi-prompt structure semantically. The reflection that produced
this redirect lives in chat history; the salient summary sits in
**Context** below.

**Coming up:**

- **Phase 2.5** — typed labelled slots: data model rewrite,
  candidate-discovery widening, slot-map editor evolution.
- **Phase 3 prep** — dynamic orchestrator schema, composition call
  restructure, legacy i2i/t2i path preserved.
- **Phase 3** — generation execution: `comfy_client`, image upload,
  graph patching with slot bindings, queue + websocket cycle,
  result persistence.

LLM auto-suggest labels (originally Phase 2.6) is parked in
[backlog.md](backlog.md) — manual labelling in the slot-map
editor turned out fast enough that the auto-suggest button is
not currently worth the extra surface area. Revisit when real
workflows push past ~10 slots.

Carried-forward polish from earlier phases that is independent of
this redirect:

- Visual polish on the Comfy Nodes library (align with `library/models`).
- Node import wizard modal: explicit Run button, per-import model
  override, sampling-bundle gear (parked under Q6).
- Drop the dead `comfy_nodes.role_hint` schema bit in a future
  migration (read path already strips it).

## Context: why workflow-declared slots

Three observations from the ecosystem survey that drive the design:

1. **Workflow inputs are a per-workflow contract.** Every tool that
   runs arbitrary ComfyUI workflows lets the workflow side declare
   what's exposed. Two patterns coexist:
   - **Marker-node** (ComfyDeploy: `External*` family;
     SwarmUI: `SwarmInput*`; Krita AI: `Parameter` + domain nodes
     `Krita Canvas` / `Krita Image Layer` / `Krita Style & Prompt`;
     ComfyUI-Workflow-Component: `ComponentInput`/`Output`; native
     Subgraph): the author drops nodes that play the role of
     exposed ports and the app reads them.
   - **Discovery** (ViewComfy: `<node_id>-inputs-<input>`): the app
     walks the graph and exposes every literal input by id, with
     no marker effort from the author.

2. **Multi-prompt is never modelled semantically.** No tool tries to
   encode "this is region 1 vs region 2" or "main vs refiner".
   Regional / Attention-Couple / ConditioningCombine workflows are
   just workflows that happen to have N text inputs; the user names
   them and the form has N fields. Trying to be smart about it is
   not what anyone does.

3. **Krita-AI's hybrid is closest to our shape.** Krita does not
   require pre-marked workflows — its `Parameter` node is generic
   ("convert any widget to input, attach a Parameter"), and the
   plugin auto-builds the form from whatever Parameter nodes are
   present. Plus it has a few domain nodes that bind to Krita
   concepts (canvas, layers, masks). The lesson: discovery of
   eligible candidates plus post-hoc labelling, with the option of
   auto-suggestion, gets the best UX without forcing workflow
   authors to know about sd-chisel.

The constraint sd-chisel imposes that none of the surveyed tools
have: we want the orchestrator's chat-driven, RAG-retrieved,
family-prompt-guide-aware composition logic to fill text slots.
Other tools either ask the user to type into form fields or run a
pre-baked prompt template. Our chat→intent→retrieve→compose pipeline
becomes "produce a structured payload conforming to a schema the
session's slot map declares". This is the only architectural twist
unique to us.

## Design overview

A **labelled slot** is the unit of integration:

```text
{
  label:       string         // human, unique within the workflow's slot list
  group:       string | null  // optional one-level grouping (e.g. "Refiner")
  ordinal:     int | null     // sort key within group; null = alphabetical
  description: string | null  // free text, shown as tooltip and fed to LLM
  kind:        SlotKind       // typed channel (see taxonomy below)
  origin:      { node_id, input_name }   // where it lives in the graph
  binding:     SlotBinding    // who supplies the value at generation time
  metadata:    object         // type-specific extras (multiline, min/max, options)
}
```

`SlotKind` is a closed enum we own (text, multiline_text, image, …).
`SlotBinding` is also a closed enum:

- `llm` — composition LLM call produces the value, given the
  per-session schema. Default for text slots.
- `library_loras` — sd-chisel's LoRA retriever materialises a
  list (deferred to Q3).
- `user_image` — image picker / session source image.
- `frozen` — value is fixed at slot-map config time and reused
  every generation (default for non-text scalars in Phase 2.5).

A **session's dynamic schema** is derived on demand from its slot
map: every `binding=llm` slot becomes a typed field in the JSON
schema sent to the composition LLM. The LLM returns one JSON
object whose keys are slot labels and whose values match the
slot's kind. `binding=user_image` slots come from the existing
session source images. `binding=frozen` slots have their value
inlined at patch time. `binding=library_loras` is plumbed through
the existing retriever pipeline (Phase 3 work, gated on Q3).

Mode (`i2i` / `t2i`) becomes an inferred property: a session has
i2i character if any `kind=image` slot has `binding=user_image`
and is wired. Otherwise it's t2i. The family-guide append logic
(`prompt_i2i` / `prompt_t2i`) on top of `prompt_guide` continues
to work the same way; the family guide stays in the
**composition system message**, not per-slot.

## Phase 2.5 — typed labelled slots

Replaces the fixed-three-slot model with a labelled, typed slot
list per workflow. No new external behaviour — the wizard, library,
catalog, settings stay as they are. Generation is still gated
(Phase 3 not done). The point is to land the data model and
editor that Phase 3 prep / 3 plug into.

### Slot kinds — taxonomy

Closed enum, shipped as one column on the slot row plus per-kind
validation in Pydantic:

| Kind             | Source eligibility (literal-valued input)                   | Default binding | Metadata                          |
| ---------------- | ----------------------------------------------------------- | --------------- | --------------------------------- |
| `text`           | `STRING` widget, `multiline=false`                          | `llm`           | `default_value`                   |
| `multiline_text` | `STRING` widget, `multiline=true`                           | `llm`           | `default_value`                   |
| `image`          | combo with `image_upload=true` (LoadImage-style)            | `user_image`    | —                                 |
| `image_alpha`    | LoadImage-mask-style combo                                  | `user_image`    | —                                 |
| `number_int`     | `INT` widget                                                | `frozen`        | `min`, `max`, `step`, `default`   |
| `number_float`   | `FLOAT` widget                                              | `frozen`        | `min`, `max`, `step`, `default`   |
| `boolean`        | `BOOLEAN` widget                                            | `frozen`        | `default`                         |
| `enum`           | combo with a known options array (sampler, scheduler, etc.) | `frozen`        | `options[]`, `default`            |
| `lora_name`      | combo whose options match `comfyui_path/loras/*`            | `frozen`        | `default`                         |
| `checkpoint_name`| combo whose options match `comfyui_path/checkpoints/*`      | `frozen`        | `default`                         |

`text_any` (ComfyDeploy's polymorphic input) is **not** added in
2.5 — every slot is strictly typed. We can revisit if real
workflows force the issue.

LoRA-stack / lora-chain bindings (Q3) are **out of scope for
2.5** — the data model leaves room (`binding=library_loras` is in
the enum) but no editor path or generation patching exists for it.

### Candidate discovery — widened

The current Phase 2 "eligible inputs" computation already does the
right thing for `STRING` and `image_upload` combos. Extend it:

- For every node in `graph_json` look at every input that is a
  literal (not a `[node_id, output_idx]` wire) and intersect
  with the catalog's `inputs_raw_json` for the class_type.
- For each literal input, derive a candidate kind from the raw
  type:
  - `STRING` → `text` if `multiline=false`, else `multiline_text`.
  - `INT` → `number_int`.
  - `FLOAT` → `number_float`.
  - `BOOLEAN` → `boolean`.
  - Combo: branch on the options shape — `image_upload=true`
    means `image`; `mask=true` means `image_alpha`; options
    matching `*.safetensors` filenames in
    `<comfyui_path>/loras/` means `lora_name`; same for
    `checkpoints/` → `checkpoint_name`; otherwise generic
    `enum`.
- Class types not yet imported still produce candidates from
  literal types alone (best-effort), flagged
  `node_in_catalog=false` like today. Combo subtypes are only
  detected with the catalog (no `image_upload` / `mask` flag
  without raw schema).
- Each candidate carries `display_name`, `node_meta_title`
  (`graph[node]._meta.title`), `current_value` preview, and
  `node_in_catalog`.

The output bucket on the API becomes
`candidates: { <kind>: [...] }` rather than the current
`{ text, image }`.

### Storage migration

`comfy_workflows.slot_map_json` swaps shape from a
`{slot_label: pair | null}` map to:

```json
{
  "version": 2,
  "slots": [
    {
      "label": "main_positive",
      "group": null,
      "ordinal": 1,
      "description": null,
      "kind": "multiline_text",
      "origin": {"node_id": "6", "input_name": "text"},
      "binding": "llm",
      "metadata": {}
    },
    {
      "label": "main_negative",
      "group": null,
      "ordinal": 2,
      "description": null,
      "kind": "multiline_text",
      "origin": {"node_id": "7", "input_name": "text"},
      "binding": "llm",
      "metadata": {}
    },
    {
      "label": "main_image",
      "group": null,
      "ordinal": 3,
      "description": null,
      "kind": "image",
      "origin": {"node_id": "12", "input_name": "image"},
      "binding": "user_image",
      "metadata": {}
    }
  ]
}
```

A `version: 1` payload (or a payload missing the `version` key
entirely — older rows) is upgraded **lazily on read** by the
session repo: every non-null assignment of the legacy
`positive_prompt` / `negative_prompt` / `main_image` keys becomes
a slot with the matching default label, kind, and binding. The
upgraded shape is written back the first time the slot map is
saved through `PUT /slot_map`. No migration SQL needed; the
column is JSON.

For sessions whose graph has no obvious match (e.g. a multi-prompt
workflow imported before 2.5), the upgrade just produces an empty
slot list — the user re-labels from the editor.

### Frontend slot-map editor — rewrite

Replaces the fixed three-row table. New layout:

- **Top toolbar.** "Add slot" (opens candidate picker filtered
  by kind), a mode badge (live i2i / t2i from the slot list),
  and a slot-count badge.
- **Slot list**, grouped by `group`, sorted by
  `(group, ordinal, label)`. Each row shows:
  - `label` — inline editable, validated (unique, no whitespace
    edge cases, max 64 chars).
  - `group` — small text input or null.
  - `kind` — read-only badge (kind is set when the candidate is
    chosen; changing kind means picking a different candidate).
  - `description` — collapsible textarea, used both as tooltip
    in the workspace and as LLM hint at composition time.
  - `binding` — dropdown of valid bindings for the slot's kind.
    Default per the kind table above; `frozen` slots show their
    frozen value editor (per-kind widget).
  - `origin` — dropdown of catalog candidates of the chosen kind,
    showing
    `<title|display_name|class_type>.<input> (#<node_id>) — "<value preview>"`.
    Picking a candidate sets `kind` from the candidate.
  - Per-row Delete button.
- **"Add slot" picker.** Modal with a kind selector at top, then
  a filtered candidate list. Picking inserts a new slot with a
  default label (`<class_type>_<input>` lowercased) for the user
  to rename.
- **Mode badge.** Recomputed live from the slot list — shows
  `i2i` if any wired `image` slot has `binding=user_image`,
  else `t2i`.

The "Continue to slot mapping" button on the readiness panel
keeps its meaning. The "Back to nodes" button on the slot-map
screen stays.

### API surface (Phase 2.5)

- `GET /api/comfy/sessions/{id}/slot_map` — same path. Response
  shape changes:
  ```json
  {
    "session_id": "…",
    "workflow_id": "…",
    "slot_map": { "version": 2, "slots": [...] },
    "candidates": {
      "text": [...], "multiline_text": [...],
      "image": [...], "image_alpha": [...],
      "number_int": [...], "number_float": [...],
      "boolean": [...], "enum": [...],
      "lora_name": [...], "checkpoint_name": [...]
    },
    "inferred_mode": "i2i" | "t2i"
  }
  ```
- `PUT /api/comfy/sessions/{id}/slot_map` — accepts `{slots: [...]}`.
  Validation:
  - Every slot's `(origin.node_id, origin.input_name)` must be a
    candidate of the slot's `kind`.
  - Labels unique within `slots`.
  - `binding` ∈ valid set for the kind.
  - For `frozen` slots, `metadata.value` must validate against
    the candidate's raw type/options.
  - 422 on any failure with a per-slot error array.

The legacy `positive_prompt` / `negative_prompt` / `main_image`
keys are removed from the API contract — clients always send and
receive the slot list. The upgrade path is server-side only.

### Out of scope for 2.5

- Auto-suggest labels — parked in [backlog.md](backlog.md).
- LLM composition consuming the schema (lands in 3-prep).
- Generation execution (Phase 3).
- LoRA-stack binding (Q3).
- Slot-level overrides per generation call (Phase 3 may add
  per-call patches like "use this seed this time only" — out of
  scope for the slot-map editor itself).

## Phase 3 prep — dynamic orchestrator schema

Lands the orchestrator-side changes that turn a labelled slot
list into actual LLM payloads, **without** queueing anything to
ComfyUI yet. Verified end-to-end by inspecting the produced
payload (no execution, no image).

### Goal

Comfy sessions stop producing the legacy
`GeneratedPrompt = {positive, negative, loras}`. They produce a
`GeneratedPayload`: a JSON object keyed by the session's slot
labels, validated against the session's dynamic schema. Existing
i2i / t2i sessions (the non-comfy session types) keep producing
`GeneratedPrompt` — no change to that path.

### Schema generation per session

Resolved at request time from `slot_map_json` and the catalog:

- For every slot with `binding=llm`:
  - Field name = `label`.
  - Field type derived from `kind` (`text` / `multiline_text`
    → string; `number_int` → integer; `number_float` → number;
    `boolean` → boolean; `enum` → string-enum with `options`
    inlined; `image*` / `lora_name` / `checkpoint_name` are not
    `llm`-bindable, so they're skipped here).
  - Field description = the slot's `description` (the LLM uses
    it as the per-field hint).
  - Optional / required: required for required-by-kind
    text/numbers; optional for everything else.
- Slots with `binding=frozen` / `binding=user_image` /
  `binding=library_loras` are not part of the LLM-facing
  schema. They're rendered into a separate `non_llm_slots`
  context block that the composition system message describes
  for awareness ("the workflow also has a frozen sampler set to
  euler_a — keep this in mind") but the LLM doesn't fill them.

### Composition call restructure

Today the composition system message hard-codes "return
GeneratedPrompt JSON". After 3-prep:

- The system message has the same anatomy (family `prompt_guide`
  + mode-specific append + model description + LoRA candidates +
  brief / chat tail) but the schema instruction is replaced by a
  per-session schema rendered inline. The composition message
  also lists every slot's `(label, group, description, kind)` so
  the LLM understands context for each.
- LMStudio call uses `response_format = "text"` plus the
  brace-matching JSON extractor (same approach `comfy_import`
  uses — `json_schema` mode is unreliable on reasoning-distilled
  models). Validation against the dynamic schema after extraction.
- LoRA list output: kept on the side. The orchestrator
  continues to produce a LoRA list alongside the new
  `GeneratedPayload`, stored in `prompts.loras_json` exactly
  like legacy sessions — for inspection, copy-paste, and the
  prompt pane's `<lora:name:weight>` widget. No graph
  patching happens here (Phase 3-prep does not touch the
  graph). The L4 milestone (Q3) will eventually consume this
  list into `binding=library_loras` slots; until then no
  slot of that binding can be created.

### Persistence

`prompts` table grows compatibly: keep the existing `positive`,
`negative`, `loras_json` columns for legacy sessions; add a
nullable `payload_json` column for comfy-session generations
(stores the raw `GeneratedPayload`). The `intents_json`,
`retrieved_loras_json`, `brief` debug fields keep their meaning
unchanged. Read-side keeps both shapes; UI inspects `payload_json`
when present, else falls back to the legacy triple. One small
migration adds the column.

### Mode inference

The session's mode (`i2i` / `t2i`) for the purposes of
`prompt_i2i` / `prompt_t2i` family-guide selection becomes:

- For comfy sessions: derived from the slot list at composition
  time. Any wired `binding=user_image` slot ⇒ `i2i`. Otherwise
  `t2i`. Computed on demand — the slot map is the source of
  truth, no cached column on `sessions`. (This generalises
  spec §10.3's existing "mode is inferred at slot-mapping
  time" rule from the fixed `main_image` slot to any
  `binding=user_image` slot.)
- For legacy i2i / t2i sessions: unchanged — the
  `session_type` column already drives this.

### Generate-modal UX

The Generate modal flow (summarize → brief → compose) stays the
same shape. Differences:

- The context preview the modal shows now lists slots by
  group with their `kind` / `binding`, instead of a single
  positive/negative/loras column.
- The "result" view inside the modal switches: legacy sessions
  keep showing the `{positive, negative, loras}` block; comfy
  sessions show every produced label with its value, grouped
  the same way as the editor.

### Chat system prompt — slot awareness (resolves Q9)

For comfy sessions with a saved non-empty slot map, the chat
system prompt builder appends a one-line slot list right
after the existing i2i / t2i framing block and before the
context block. Shape:

```text
The workflow exposes these labelled slots:
- <group>/<label> (<kind>): <description>
- <label> (<kind>): <description>
...

Reply in plain prose. Do not emit JSON, schemas, or
"slot: value" structures — a separate composition step
fills the slots. The user may reference slots by label;
acknowledge them in prose.
```

Groupless slots render without the `<group>/` prefix.
Slots without a `description` render with the kind-only tail
(`(<kind>)`, no trailing description text).

For comfy sessions whose slot map is empty (fresh upload, not
yet labelled) and for legacy `i2i` / `t2i` sessions, the slot
block is omitted — chat behaves exactly like today.

The chat *user* prompt and the existing `@Image_N` reference
mechanism stay unchanged. The composer (still `generate-prompt`)
is the only component that consumes the structured schema; the
chat just gets context awareness.

Smoke-test caveat called out by Q9: if local models drift to
structured replies even with the explicit "no JSON"
instruction, the fallback is to drop the slot block entirely
(go full unaware) and rely on the composer alone. Verify on
Phase 3 prep with two or three local models on a worked
example before locking the prompt in.

### Out of scope for 3-prep

- Patching the actual workflow graph (Phase 3).
- Queue / WS / image fetch (Phase 3).
- Editable frozen overrides and per-slot image binding inside
  the modal — design resolved (Q4 / Q7), but the editing UI
  ships in Phase 3 alongside actual execution. The 3-prep
  modal stays read-only across all bindings; refinement still
  goes through chat.

## Phase 3 — generation execution

Closes the loop: a comfy session takes the dynamic-orchestrator
payload from 3-prep, patches the bound workflow, queues it on
ComfyUI, and persists the result. This phase resolves Q4
(modal overrides), Q5 (workflow versioning), and Q7
(multi-image binding) inline; Q3 (LoRA injection) is partially
resolved — L1 ships now, L4 is plumbed but gated.

### `comfy_client.py` service

Mirrors `lmstudio_client.py`:

- One shared `client_id` per process, one persistent WebSocket
  to `/ws?clientId=…`, per-job asyncio queues demuxed by
  `prompt_id`.
- Honors `comfyui_api_key` (currently set but unused outside
  the connection check) on every outbound request.
- Auto-reconnect with backoff on WS disconnect. In-flight jobs
  surface a `connection_lost` event on their SSE stream and
  flip to `error` if the reconnect doesn't recover the
  `prompt_id` within a grace window.

### Image upload flow

For every `binding=user_image` slot the modal bound to a
session source row:

- `POST /api/upload/image` to ComfyUI with the file content.
- Capture the returned name (ComfyUI's input filename).
- Use it as the literal value when patching the slot's
  `(node_id, input_name)`.

Uploads are per-job; ComfyUI's input dir is treated as cache,
not state. The "upload once, reuse by hash" optimisation
(`fal-Connector`-style) is deferred — re-uploading a 1 MB PNG
per generation is cheap enough to start.

### Graph patching

Take the bound workflow's `graph_json`, walk the slot list as
captured in `slot_map_snapshot_json` (frozen at job time, not
the live workflow row), and for each slot:

- `binding=llm` ⇒ inject from `GeneratedPayload`. If the
  caller supplied `payload_overrides[<label>]`, the override
  wins.
- `binding=user_image` ⇒ inject the uploaded filename
  resolved per slot from the modal's image-binding section
  (see below). `(unset)` slots are skipped.
- `binding=frozen` ⇒ inject `metadata.value` from the slot,
  unless `payload_overrides[<label>]` supplied a per-call
  override (the seed/sampler escape hatch).
- `binding=library_loras` ⇒ deferred. See "LoRA strategy"
  below — Phase 3 ships with this binding **non-fillable**:
  the slot-map editor in 2.5 already disallows selecting it,
  and the patcher 422s if it sees one (defensive — should
  never fire).
- Slot with no `origin` wired ⇒ skip; the graph keeps its
  baked literal.

The patcher operates on a deep copy of `graph_json`. The
original `comfy_workflows.graph_json` row is never mutated by
the generator; replacement only happens through the upload
flow.

### LoRA strategy — L1 ships, L4 follows (resolves Q3)

Phase 3 ships **L1**: orchestrator-produced LoRAs are not
injected into the workflow. They surface in the comfy session's
prompt panel exactly as legacy sessions surface them — copy
buttons for the `<lora:name:weight>` string, weight sliders,
debug pane. The user pastes them into the workflow themselves
or runs the workflow's baked-in LoRAs.

This is intentionally conservative. It preserves chat/RAG
benefits (the user still sees what the orchestrator picked) and
ships generation against arbitrary workflows without committing
to a graph-mutation strategy.

**L4** (fill a stack-node's `lora_<n>` / `strength_<n>` slots)
is the next milestone. Gating is non-trivial: the catalog needs
to know which class_types are stack-capable without a hand-
coded allowlist. Two candidate paths, neither shipped:

- **Heuristic on `inputs_raw_json`.** Detect a series of
  matching `lora_<n>` + `strength_<n>` literal inputs (any
  naming convention). Stamp `stack_capacity=<n>` on the
  catalog row. Cheap, deterministic, but coupling-prone if a
  pack picks a weird name.
- **LLM-side flag in the import wizard.** Phase 1's Stage 3
  prompt grows a `is_lora_stack: bool` + `stack_capacity: int`
  output, validated against the schema. More expressive but
  one more thing the model can get wrong.

Once a node is flagged stack-capable, the slot-map editor
exposes a `kind=lora_chain` candidate; binding it to
`library_loras` lights up; the patcher fills its
`lora_<n>` / `strength_<n>` from the orchestrator's LoRA list,
capped at `stack_capacity`.

**L3** (splice `LoraLoader` nodes by rewiring model/clip edges)
stays out. Failure modes are silent — pick the wrong
model/clip wire and the LoRA appears applied while the cond
pipeline silently diverges. Not worth the surface area when
stack nodes already cover the use case.

### Per-slot image binding (resolves Q7)

When the bound workflow has more than one `binding=user_image`
slot, the Generate modal grows a collapsible **"Image
bindings"** section. It lists every such slot with a dropdown
of the session's `session_source_images` rows.

Defaults:

- One image slot total, one source image ⇒ auto-bind, no UI.
- Multiple slots ⇒ the first slot in
  `(group, ordinal, label)` order binds to the source row
  with `is_main=1` if any, else the lowest `image_number`.
  Other slots default to **(unset)**.
- `(unset)` means "skip this slot" — the graph keeps its
  baked filename. Useful when one slot is optional
  (controlnet reference, ip-adapter, mask).

Picks land in `payload_overrides` under the slot label
(`{<label>: {kind: "image", source_id: "<session_source_image.id>"}}`)
and persist on `comfy_jobs.payload_json` so a historical job
records exactly which images it ran against.

The `session_source_images` sidebar in the workspace stays
mode-agnostic for comfy sessions: every uploaded image is a
candidate for any slot, and `is_main` becomes a soft default
rather than a hard discriminator. For non-comfy `i2i` sessions,
`is_main` keeps its existing semantics (one main, references
underneath).

### Generate-modal UX (resolves Q4)

The modal grows but stays opinionated:

- **Brief preview** — same as today, read-only markdown,
  produced by `summarize-chat`.
- **Slot context** — read-only summary of the session's slot
  list grouped by `group`, with each slot's `kind` and
  `binding` rendered as compact chips. Frozen values shown
  inline.
- **Image bindings** (only when ≥ 2 `binding=user_image`
  slots exist) — see the previous section.
- **Frozen overrides** (collapsible, shown when ≥ 1
  `binding=frozen` slot exists) — every frozen slot rendered
  with an inline editor matching its `kind` (number input,
  enum dropdown, boolean toggle, text). Edits flow into
  `payload_overrides` for **this run only**; the saved slot
  values stay untouched. This is the seed/sampler tweak
  escape hatch — the chat is the wrong tool for "regenerate
  with a different seed".
- **`binding=llm` slots stay read-only.** Refining prompt
  content goes through chat, not the modal — keeps chat the
  single source of truth for creative direction. Power users
  can still POST to `/generate` with full
  `payload_overrides` via the API; the constraint is
  UI-only.

Generate launches the orchestrator + patcher + queue
sequence. The modal streams progress through the same SSE
session-scoped channel chat uses, then closes on success
with a result toast. Failures keep the modal inline for
retry.

### Workflow replace handling (resolves Q5)

Phase 1's overwrite-in-place behaviour stays — workflow `id`
doesn't change, `graph_json` and `graph_hash` get updated.
Phase 3 adds:

- **Slot-map re-validation on replace.** Iterate every slot
  in the saved `slot_map_json`. Drop any slot whose
  `(origin.node_id, origin.input_name)` no longer exists in
  the new graph or whose candidate kind no longer matches.
  Set `comfy_workflows.slot_map_needs_review` (new boolean
  column, migration adds it) when any slot was dropped.
- **Workspace banner.** When `slot_map_needs_review=true`,
  every comfy session bound to this workflow shows a banner
  above the Generate button: "Workflow was replaced; review
  slot map before generating." The banner links into the
  slot-map editor. Generation is **not blocked** — if the
  remaining bound slots are enough, the user can run as-is.
  Saving from the editor (even without changes) clears the
  flag.
- **Job history is unaffected.** Each `comfy_jobs` row
  carries `slot_map_snapshot_json` frozen at run time, so
  historical runs stay reproducible against the (now
  superseded) graph version that ran them. We do **not**
  retain old graph versions — replaying an old job against
  the post-replace workflow is out of scope. This is
  reproducibility-of-record, not re-execution.

### Persistence

New tables (one migration, alongside the
`slot_map_needs_review` column above):

- **`comfy_jobs`**: `id` (random hex), `session_id`,
  `workflow_id`, `prompt_id` (string from ComfyUI),
  `payload_json` (the merged `GeneratedPayload` ⊕
  `payload_overrides`), `slot_map_snapshot_json` (frozen
  slot list at run time), `status` (`queued` | `running` |
  `success` | `error` | `cancelled`), `error_message`
  (nullable text), `started_at`, `finished_at`. FK
  `session_id → sessions(id) ON DELETE CASCADE` — deleting a
  comfy session drops its job history.
- **`comfy_job_outputs`**: `id`, `job_id`, `node_id` (string,
  matches the graph node that produced this output),
  `output_index` (int), `path` (relative to `data/`),
  `is_primary` (bool — first output of the first
  SaveImage-style node, used as the gallery thumbnail),
  `created_at`. FK `job_id → comfy_jobs(id) ON DELETE CASCADE`.

Output files land under
`data/images/<session_id>/generated/<job_id>/<output_index>.<ext>`,
mirroring the existing per-session image directory structure.

### API

- `POST /api/comfy/sessions/{id}/generate` — accepts
  `{brief?: string, compact_history?: bool, payload_overrides?: object}`.
  `payload_overrides` is a free-form map keyed by slot label;
  values must structurally match the slot's `kind` (validated
  per-slot, 422 on mismatch). Runs the orchestrator
  (composition only — image bindings come from the
  `payload_overrides`, not the orchestrator), patches the
  graph, queues, returns `{job_id, prompt_id}`.
- `GET /api/comfy/jobs/{job_id}` — full row plus
  `comfy_job_outputs`.
- `GET /api/comfy/jobs/{job_id}/stream` — SSE progress.
  Event vocabulary mirrors `comfy_import`
  (`stage_started` / `stage_succeeded` / `stage_failed` /
  `done`) plus `progress` (per-step), `image_ready`
  (per-output), and `connection_lost`.
- `GET /api/comfy/jobs?session_id=…` — list per session,
  paged, ordered by `started_at desc`.
- `POST /api/comfy/jobs/{job_id}/cancel` — best-effort:
  `POST /api/interrupt` if executing, drop from queue if
  still queued. Sets row status to `cancelled`.

### Workspace UX (Phase 3 layout)

The post-readiness comfy session screen lights up:

- **Left** — chat + prompt pane + pinned-LoRAs stack. The
  prompt pane evolves for comfy sessions per Q8 (Variant A,
  tree of grouped slots). Legacy `i2i` / `t2i` sessions keep
  the current `positive / negative / loras` layout
  unchanged. Prompt-pane structure for comfy sessions:
  - Renders as one section per `group`. Groupless slots
    appear in an unlabeled section at the top; within each
    group, slots sort by `(ordinal, label)`.
  - Per-slot row for `binding=llm`: a textarea seeded with
    the latest job's value for that slot (empty placeholder
    pre-Generate), description shown as muted subtitle.
    Inline-editable; edits live in local component state
    only — they feed the per-slot Copy button but are NOT
    sent to Generate. Generate always re-runs the
    orchestrator and overwrites the textarea with its fresh
    output. The "edit then re-run with overrides" path
    lives on the Generate modal (read-only on llm, editable
    on frozen) and the API (`payload_overrides`); the
    prompt pane is intentionally a display + clipboard
    surface, keeping chat as the single source of creative
    direction.
  - Per-slot row for `binding=frozen`: read-only display
    rendered with a kind-appropriate widget — a number
    badge, an enum chip, a boolean pill, an inline text
    line — plus an "edit in slot map" link that jumps the
    editor.
  - Per-slot Copy button (copies the slot's current value).
    Per-group "Copy as JSON" button (copies just that
    group's slots as a JSON object). Top-level "Copy
    payload" button copies the whole payload as JSON.
  - When the slot map is empty (e.g. workflow uploaded but
    not labelled yet), the pane shows a placeholder banner:
    "Slot map not configured — go to slot mapping to set
    up generation." with a link to the editor.
  - LoRA list stays outside the slot tree for now (Phase 3
    ships L1; LoRAs aren't a bindable slot yet). Same
    widget legacy sessions use, with the
    `<lora:name:weight>` copy action.
- **Centre** — running-job progress card on top (when one is
  in flight), then a results gallery below grouped by job,
  newest first. Each gallery card opens a full-size lightbox;
  per-job actions: "Regenerate with same seed" (lifts the
  frozen overrides into the next run), "Show payload" (opens
  the stored `payload_json`), "Delete" (drops the job + files).
- **Right** — slot-map summary grouped by `group`, with an
  Edit-slots link that jumps to the editor; banner from
  Workflow replace handling renders here when active.

### Out of scope for Phase 3

- Multi-job parallelism beyond ComfyUI's own queue. We let
  ComfyUI queue serialise; the SSE stream just relays
  queue-position events.
- Re-executing historical jobs against a post-replace
  workflow — the snapshot is for record-keeping, not replay.
- Inline batching ("generate N images per click") — ComfyUI
  supports it natively via the workflow's `batch_size`;
  users can bake it into the workflow if they want it.
- LoRA injection L4 (deferred per the LoRA strategy section).
- VL critique of the result (legacy MVP step 6 placeholder
  remains a placeholder).

## Worked example: 8-slot regional t2i workflow

Anchors the design against a real shape the user runs.

The workflow has two regions plus a global negative and an
upscale stage. The user's slot list ends up as:

```text
Region 1/positive          (multiline_text, llm)      → CLIPTextEncode #15.text
Region 1/negative          (multiline_text, llm)      → CLIPTextEncode #16.text
Region 2/positive          (multiline_text, llm)      → CLIPTextEncode #17.text
Region 2/negative          (multiline_text, llm)      → CLIPTextEncode #18.text
Global/positive            (multiline_text, llm)      → CLIPTextEncode #6.text
Global/negative            (multiline_text, llm)      → CLIPTextEncode #7.text
Upscale/refiner_positive   (multiline_text, llm)      → CLIPTextEncode #42.text
Upscale/seed               (number_int,    frozen)    → KSampler #50.seed = 12345
```

User flow:

1. Upload workflow, walk readiness gate (Phase 1 — done).
2. Open slot-map editor. Press "Add slot" eight times, picking
   each text encoder + the seed input from the candidate picker.
   Label them `Foreground/positive`, `Foreground/negative`,
   `Background/positive`, `Background/negative`,
   `Global/positive`, `Global/negative`,
   `Upscale/refiner_positive`, `Upscale/seed`. Save.
3. Continue to chat. User describes the scene.
4. Open Generate modal. Summarize fires. Brief looks right.
   Press Generate.
5. Composition LLM call gets a system message describing the
   eight slots and produces a JSON object with seven text
   fields filled (the eighth is `frozen` and not in the
   schema). Family `prompt_guide` + `prompt_t2i` give the
   model the conventions for the chosen family. The LLM
   knows from the descriptions that "Foreground/positive"
   and "Background/positive" should differ.
6. Patcher injects all seven texts into the right node inputs;
   the frozen seed is already in the graph. Queue. WS. Result.

What this design **does not** try to do: it does not say
anything about *what makes a good Foreground vs Background
prompt* — that's the family `prompt_guide` and the LLM's job.
It does not infer the regional structure from the graph; it
just gives the user a labelled-slots editor that scales to as
many text inputs as the workflow has.

## Design decisions

All previously-parked design questions are resolved as of this
revision. Future open questions land here as they arise.

- **Variant 1 vs 2 for the slot model.** Going with Variant 2
  (workflow-declared, dynamic schema). Rationale in **Context**.
- **Slot binding enum.** Fixed as
  `{llm, frozen, user_image, library_loras}`. The first three
  ship in Phase 2.5. `library_loras` stays in the enum but is
  not selectable in the editor until L4 detection ships.
- **Slot kind taxonomy.** Fixed as the ten-kind table in
  Phase 2.5. `text_any`, `video`, `face_model`, `image_batch`
  are deferred polish, not part of the initial cut. `lora_chain`
  is reserved for L4 (Q3 follow-up).
- **`slot_map_json` migration.** Lazy upgrade on read
  (v1 → v2). No SQL migration — the column is JSON, the
  upgrade is in Python and writes back on the first save.
- **Mode (`i2i` / `t2i`) for comfy sessions.** Derived from
  the slot list (any wired `binding=user_image` slot ⇒ i2i,
  else t2i). Computed on demand — no cached column on
  `sessions`. Generalises the existing inference rule (spec
  §10.3) from the fixed `main_image` slot to any
  `binding=user_image` slot. Legacy `i2i` / `t2i` sessions
  keep their explicit `session_type` column.
- **`payload_overrides` API surface.** Free-form per-slot
  map on `POST .../generate`, structurally validated against
  each slot's `kind`. Power-user escape hatch even when the
  modal UI hides it.
- **Q3 — LoRA injection strategy.** Phase 3 ships **L1** only
  (reference-only LoRA list, no graph mutation; same
  copy-paste affordance legacy sessions have). **L4**
  (stack-node fill via `binding=library_loras`) is the next
  milestone, gated on a non-allowlist node-detection path —
  either a heuristic on `lora_<n>` / `strength_<n>` input
  series, or an LLM-side `is_lora_stack` flag in Stage 3 of
  the import wizard. Pick when it's time. **L3** (splice
  `LoraLoader` nodes by rewiring model/clip edges) stays
  permanently out — silent failure modes don't justify the
  surface area.
- **Q4 — per-call slot overrides in the Generate modal.**
  Hybrid: `binding=llm` slots are read-only in the UI (chat
  remains the single source of creative direction);
  `binding=frozen` slots are inline-editable (seed / sampler
  tweak escape hatch); image bindings live in their own modal
  section. The API itself accepts free-form
  `payload_overrides` for any slot — the read-only rule is
  UI-only.
- **Q5 — workflow versioning.** Replace re-validates the
  saved slot map against the new graph, drops misaligned
  slots, sets a `slot_map_needs_review` flag (new boolean
  column on `comfy_workflows`) that triggers a workspace
  banner. Saving the slot map from the editor — even
  unchanged — clears the flag. Job history is unaffected:
  each `comfy_jobs` row freezes `slot_map_snapshot_json` for
  reproducibility-of-record (not for replay).
- **Q6 — dedicated model selection.** Parked. Both
  `comfy_import` and any future `comfy_label` action would
  benefit from per-action model pins
  (`comfy_import_model_name` / `comfy_label_model_name`) rather
  than the favourite-LMStudio fallback, but the work was
  packaged with the auto-suggest feature in
  [backlog.md](backlog.md). The `comfy_import_model_name`
  half is independently shippable if the import wizard's
  reasoning-model surface bug becomes painful in isolation.
- **Q7 — multi-image i2i with named slots.** Per-slot dropdown
  in the Generate modal under "Image bindings". Picks land in
  `payload_overrides`, persist on `comfy_jobs.payload_json`.
  `session_source_images.is_main` becomes a soft default for
  comfy sessions, hard discriminator for legacy `i2i`.
- **Q8 — prompt pane in comfy sessions.** Variant A — a tree
  of groups, each containing per-slot rows. Groupless slots
  render above any group; within a group, slots sort by
  `(ordinal, label)`. `binding=llm` slots get editable
  textareas (edits are local component state, used as the
  source for per-slot Copy and not persisted server-side;
  Generate always re-runs the orchestrator, overwriting any
  unsaved manual edits — copy first if you need to keep
  them). `binding=frozen` slots render read-only with a
  kind-appropriate widget (number badge, enum chip, boolean
  pill) and an "edit in slot map" link. Per-slot, per-group,
  and per-payload (JSON) copy buttons. Legacy `i2i` / `t2i`
  sessions keep the existing
  `positive / negative / loras` layout — the slot tree only
  renders when the session has a non-empty slot map.
- **Q9 — chat awareness of slot schema.** Soft middle. For
  comfy sessions with a saved non-empty slot map, the chat
  system prompt appends a one-line slot list (label, kind,
  description) plus an instruction to keep replies in plain
  prose and never emit JSON. The user may reference slots
  by label; the LLM acknowledges in prose. Smoke-test
  caveat: if local models drift to structured replies anyway
  during Phase 3 prep validation, fall back to **unaware**
  (no slot list in the chat prompt) and rely on the
  composer alone.
- **Catalog `role_hint` enum.** Already dropped in Phase 2.
  Phase 2.5 confirms the dynamic schema does not need it.

## Verification plan

Phase 2.5:

- Unit tests for the slot model: validation of each kind's
  metadata, binding eligibility per kind, label uniqueness,
  origin-must-match-candidate-kind.
- Unit tests for the candidate discoverer: every kind detected
  correctly from the raw schema, including the catalog-gated
  kinds (`image`, `image_alpha`, `lora_name`, etc.).
- Unit test for the legacy `slot_map_json` upgrade path:
  `version=1` (or absent) becomes a `version=2` payload with
  three default slots; empty / null cells produce empty slot
  list.
- Integration test on a fixture workflow: GET returns the new
  shape, PUT round-trips, validation errors render per-slot.
- Browser test (chrome-devtools MCP): create a comfy session,
  upload a multi-prompt fixture workflow, walk the readiness
  gate (mocked), open the slot-map editor, add slots, save,
  reload, slots persist.

Phase 3 prep:

- Unit tests for the dynamic-schema generator: every kind maps
  to the right Pydantic / JSON-schema type, descriptions
  carried through, optional-vs-required rules.
- Unit tests for the composition-call restructure: legacy
  sessions still produce `GeneratedPrompt`; comfy sessions
  produce `GeneratedPayload`; mode inference works for graphs
  with / without wired image slots.
- Integration test with a faked LMStudio: end-to-end produce a
  payload for the eight-slot worked example, validate
  conformance.

Phase 3:

- Patcher tests: for each binding, the right input is set on
  the right node, frozen values are inlined, unwired slots are
  left alone, image bindings inject the uploaded filename.
- Live test against a real ComfyUI on `localhost:8188` with a
  fixture workflow: queue, WS, result fetch, persistence.
- Browser test: full happy-path generation against a
  three-slot toy workflow, then again against the eight-slot
  regional fixture.

## Spec impact

Phase 2.5: spec §10.6 is rewritten end-to-end. Slot kinds /
binding taxonomy, candidate-bucket shape, storage shape,
endpoint contracts. Mode-inference paragraph in §3.2 / §10.2
is updated to reflect the new derivation.

Phase 3 prep: spec §4.3 (Generate flow) grows a paragraph
distinguishing legacy `GeneratedPrompt` from comfy
`GeneratedPayload`. New sub-section in §10 covers the dynamic
schema. §3.2 grows the new `prompts.payload_json` column.

Phase 3: spec §10.7 graduates from "pending" to a full
generation-execution section. §3.x grows tables `comfy_jobs` and
`comfy_job_outputs`. §5.1 grows the new `/api/comfy/jobs*` and
`/api/comfy/sessions/{id}/generate` endpoints. §9 ("MVP scope")
moves Phase 3 from "remaining piece" to "shipped post-MVP".
