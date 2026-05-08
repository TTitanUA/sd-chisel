# Comfy agents redesign — design doc

This doc supersedes the **Live PR** scope of
[`comfy-workspace-redesign-plan.md`](comfy-workspace-redesign-plan.md).
The Restructure + Mock PRs that already shipped stay; the Live PR is
re-planned around user-programmable agents instead of the single
implicit orchestrator.

## Status (2026-05-06)

**Design only.** No code yet. This doc captures the agreed architecture
before any implementation; the user must sign off before we cut PRs.

## Goals

1. Replace the single hardcoded orchestrator with **N user-programmable
   agents** per session. Each agent has its own prompt, model, source
   scope, LoRA toggle, and a list of typed output slots.
2. Reduce the chat from creative-direction surface to a **read-only
   consultant**. Nothing it produces feeds generation.
3. Keep the workflow's slot map (§10.6) as the single declaration of
   which inputs are exposed and what kind they are.
4. Make wiring agent outputs → workflow inputs explorable from the
   workflow itself: a node-tree viewer in the centre, clickable inputs.
5. No auto-mapping at session creation. The user explicitly authors
   their pipeline.

## Layout (post-readiness)

Three columns, with a vertical split in the centre.

```
┌──────────────┬──────────────────────────┬────────────────┐
│ Agents       │ Node tree (viewer)       │ Slots          │
│ ─────────    │ ──────────────────────── │ Inputs         │
│ • Composer   │ click input → drawer     │ Sources        │
│ • Refiner    │ shows binding + agent    │ Nodes          │
│ + add agent  │                          │ Chat (ref)     │
│              │ ──────────────────────── │                │
│ ─────────    │ Results gallery          │                │
│ Selected     │ (newest first, per-job)  │                │
│ agent panel: │ state-switcher per card  │                │
│ - prompt     │                          │                │
│ - sources    │                          │                │
│ - model/lora │                          │                │
│ - output     │                          │                │
│   slots      │                          │                │
│ - Generate   │                          │                │
└──────────────┴──────────────────────────┴────────────────┘
```

**Left column — Agents.** Top: list of agents on the session, with
"+ add agent". Bottom: panel for the selected agent — its prompt
textarea (persisted), source scope, model + params, LoRA toggle, list
of output slots (each with a kind chip, last generated value
preview, and a "bind to workflow slot" affordance), and a per-agent
**Generate** button. "Generate" only runs *this* agent — not the whole
workflow.

**Centre top — Node tree (viewer).** Read-only structural view of the
bound workflow. One row per node (class type, title, node id), inputs
indented below. Click any input → opens an inspector drawer (right
side) showing: which workflow slot, if any, owns this input; if a
slot, its binding and the bound agent output (or frozen value, or
user-image binding); affordances to create / edit / unbind via the
slot-map editor. The node tree is **not** a graph editor — no
re-wiring of edges.

**Centre bottom — Results gallery.** Per-job cards, newest first,
matching the Live-PR plan from the previous redesign doc. Each card
carries thumbnail, the job's frozen + user-image bindings + the
agents' output slot values that fed the run, plus card actions
(`Regenerate with same overrides`, `Show payload`, `Delete`).
"State-switcher" on a card lets the user re-load that historical job's
agent outputs back into the live agents (read-only preview; explicit
"Use as starting point" copies values into the current agents'
prompt + outputs for further iteration). A running-job progress card
pins to the top while a job is in flight.

**Right rail — Inspector tabs.**

- **Slots** — the read-only summary that exists today, grouped by
  `group`, kind + binding chips, ✏ icon opens the slot-map drawer.
- **Inputs** — *merged Bindings + Frozen.* One row per slot with
  `binding=user_image` or `binding=frozen`. The source-of-value chip
  (image picker vs frozen value editor) varies, but they share the
  layout, header, and "session-scoped overrides" semantics.
- **Sources** — unchanged. The shared `SourceImagesPane`.
- **Nodes** — unchanged. Compact readiness summary; inline gate when
  readiness regresses.
- **Chat** — *new.* The chat moves here as a tab. Read-only relative
  to generation: chat history persists per session, the user can talk
  to the model about the workflow / sources / prompting, but nothing
  the chat produces feeds the patcher. The chat system prompt sees the
  session's slot list + agent list + sources so it can answer
  questions like "what should I put in the Foreground/positive
  agent?"

## Data model

### Agents (session-scoped, new)

A new table `comfy_session_agents`, FK `session_id → sessions(id) ON
DELETE CASCADE`. One row per agent, ordered by an integer `position`
column.

Conceptual shape (stored as a couple of columns + a JSON blob; exact
SQL design picks land at implementation time):

- `id` — random hex, PK.
- `session_id`, `position`.
- `name` — user-editable display name.
- `prompt` — free text, the agent's input. Persisted; the user edits
  this and re-presses Generate to iterate.
- `model_name`, `model_params_json` — per-agent LLM. Defaults to the
  session's prompt-writer model on creation.
- `source_scope` — `all` | `selected` | `none`. When `selected`,
  `source_ids_json` holds the picked `session_source_images.id` list.
- `loras_enabled` — boolean. When true, the LoRA retriever runs the
  same way it does today and the candidates are inlined into the
  agent's system message; when false, the agent gets no LoRA context.
- `output_slots_json` — list of agent output slots (see below).
- `last_run_at` — timestamp of the agent's last successful Generate.

**Agent output slot** (an item in `output_slots_json`):

- `id` — random hex, stable across regenerates.
- `origin` — `preset` | `custom` | `auto`.
  - `preset`: one of a small built-in set —`positive`, `negative`,
    `loras`. Kind, description, and label are pre-filled.
  - `custom`: user picks `kind` + writes `description`. Label is the
    description's first line by default.
  - `auto`: kind + description are **snapshotted at bind time** from
    two sources, merged: (a) the **workflow slot** the agent slot is
    being bound to — its `kind`, `description`, frozen value if any;
    (b) the **catalog node** that owns the slot's origin — class
    description, input description, and any `description_for_llm`
    recommendation we already store from Phase 1's import wizard.
    The merged blob lands in the agent slot's `description` so the
    agent's system message gets the same instruction the catalog
    captured for that input. The snapshot is frozen — if the
    workflow is replaced and the bound input disappears, the agent
    slot stays as-is and unbinds, but doesn't re-snapshot off a new
    node.
- `kind` — one of the §10.6 kinds.
- `label`, `description` — user-visible.
- `last_value` — the last generated value, kind-typed. Persisted.
  Read by the workflow-run patcher.
- `bound_to` — `null` or `{ workflow_slot_label: string }`. The
  binding into the workflow's slot map. The target slot must have
  `binding=llm` and a matching kind.

**Agent ↔ workflow slot wiring rules.**

- Each workflow slot with `binding=llm` is filled by **at most one**
  agent output slot. Multi-bind is rejected at save time.
- An agent output slot with `bound_to=null` is "dangling" — the
  agent still produces a value at Generate time and persists it in
  `last_value`, but the value isn't sent to the workflow. Useful for
  scratch / iteration.
- A workflow slot with `binding=llm` and no agent bound to it is
  "unfilled" — workflow Generate refuses to run until either an
  agent output is bound or the workflow slot's binding is changed
  to `frozen`.

### Workflow slot map — unchanged

`comfy_workflows.slot_map_json` keeps its current §10.6 shape. Slot
binding enum stays `{llm, frozen, user_image, library_loras}`. The
slot-map editor stays the place to declare workflow slots; the new
node-tree viewer is a discovery surface that opens the same editor.

### Removed: implicit composer payload

Today the orchestrator produces a single `GeneratedPayload` for all
`binding=llm` slots. With agents, that single payload doesn't exist
— each agent owns a subset of slot values via its `last_value`s.
`prompts.payload_json` (§10.7) on a comfy-session row keeps its
meaning for **historical reproducibility**: when a workflow Generate
runs, the patcher snapshots every bound agent's `last_value`s into a
single dict keyed by workflow slot label and stores that under
`payload_json`, exactly the way today's row does. The composition
LLM call as a single-shot stage is replaced by per-agent LLM calls.

## Agent execution

Two distinct verbs, each with its own button.

### Per-agent Generate

Triggered from the selected-agent panel. Composes a fresh value for
every output slot the agent owns.

1. **Build context.** System message describes: the bound workflow's
   slot list (label / kind / binding / description, all of it — same
   block today's composer sees), the agent's role ("you produce
   values for the following output slots"), the agent's output slot
   schema (label / kind / description for each), and a JSON shape
   instruction. User message = `agent.prompt` verbatim.
2. **Add sources.** Per `agent.source_scope`: include the analyses
   for `all` source images, `selected` ones, or skip when `none`.
3. **Add LoRAs (if `loras_enabled`).** Run the existing LoRA
   retriever the same way today's orchestrator does; inline the
   candidates into the system message. The agent's response may
   include a `__loras` field; the value lands in `last_value` of the
   `preset=loras` output slot if one exists.
4. **Call `agent.model`.** Validate per output slot kind (same
   validator §10.7 already implements). Persist each output's
   `last_value`. Update `last_run_at`.

The chat is **not** consulted. Each agent is independent.

### Workflow-level Generate

Triggered from the header **Generate** button (the same one that's
disabled in Mock PR today). Patches the workflow and queues a job.

1. Walk the workflow's slot map. For each slot:
   - `binding=llm` → look up the bound agent output's `last_value`.
     If unbound or no last_value, **block the run** with an error
     pointing at the missing slot.
   - `binding=frozen` → the value lives on `metadata.value`, with
     session-scoped overrides from the Inputs tab (Frozen half).
   - `binding=user_image` → the bound source image from the Inputs
     tab (Bindings half).
   - `binding=library_loras` → reserved (L4 deferred).
2. Snapshot the merged payload into `prompts.payload_json` and
   `comfy_jobs.payload_json` (§10.7 + Phase 3). Snapshot also a
   per-agent state blob (`agents_snapshot_json`) on the job for
   reproducibility — every agent's prompt + model + output slot
   values at the moment of the run.
3. The rest mirrors Phase 3: image upload, graph patching, queue,
   WS, persistence.

The header Generate button is enabled iff every `binding=llm` slot
has a bound agent output with a non-null `last_value`. Tooltip when
disabled: "Run the agents that fill `<labels…>`."

## Chat as reference

The chat tab keeps the existing `chat_messages` table and SSE
streaming. What changes:

- The chat's system prompt loses the "this is the source of creative
  direction" framing. Instead it gets: "you help the user understand
  their workflow, slot list, sources, and family prompting guide. You
  do not produce JSON. You do not produce slot values. The user runs
  agents to fill slots; your job is consultation."
- The slot list, the configured agents (names + roles), and the
  family `prompt_guide` are inlined into the chat system prompt so
  the consultant is grounded.
- `summarize-chat` is removed from generation. The endpoint may stay
  as an internal tool for the chat itself if useful, but no agent
  reads it.
- Chat history is no longer cleared / massaged on Generate. Sessions
  accumulate chat indefinitely (existing chat-history retention rules
  apply unchanged).

## Migration / compatibility

- **Existing workflow slot maps.** No change. `binding=llm` slots
  stay declared; they just now require an agent binding to be filled.
- **Existing comfy sessions.** `comfy_session_agents` empty on first
  load. Header Generate is disabled until the user adds at least one
  agent and wires it. We do **not** auto-create a default agent.
- **"Create default composer" button.** A discoverable affordance
  (probably in the empty-state of the agents column and in the
  slot-map drawer's empty-binding warning) that creates **one
  agent** with one output slot per `binding=llm` workflow slot,
  each pre-bound and pre-described from the workflow slot's label +
  kind. The user can then refine the agent's prompt and run.
  Pressing this is opt-in; nothing creates it automatically.
- **`prompts.payload_json` historical rows.** Keep their meaning;
  any existing comfy-session prompts row stays valid as the last
  successful workflow run. New rows are written by the
  workflow-level Generate path described above.
- **Removed**: the `summarize-chat → compose` pipeline as the
  generation entry point. The composer service is repurposed into
  the per-agent LLM call (one agent ≈ one composer call with a
  smaller schema).

## Backend impact

- New table `comfy_session_agents` with the columns described above.
- New endpoints:
  - `GET /api/comfy/sessions/{id}/agents` — list.
  - `POST /api/comfy/sessions/{id}/agents` — create.
  - `PATCH /api/comfy/sessions/{id}/agents/{agent_id}` — partial
    update (prompt, model, sources, slots, etc.).
  - `DELETE /api/comfy/sessions/{id}/agents/{agent_id}`.
  - `POST /api/comfy/sessions/{id}/agents/{agent_id}/run` — fires
    the per-agent Generate; SSE-streams progress and persists the
    `last_value`s.
  - `POST /api/comfy/sessions/{id}/agents/seed_default` — the
    "Create default composer" action; idempotent only when no
    agents exist.
- `POST /api/comfy/sessions/{id}/generate` (Phase 3 endpoint) reads
  bound agent `last_value`s instead of running an orchestrator
  composition. Validation: every `binding=llm` slot needs a bound,
  fresh `last_value`.
- The composition orchestrator code shrinks to the "one agent's call"
  surface — most of `prompt_orchestrator.py` stays, but the
  schema-derivation step takes an agent's output-slot list instead of
  the whole workflow's `binding=llm` set.

## Open questions

1. **Per-agent run vs auto-run-on-workflow-Generate.** Do we keep
   strict two-stage (agent run → workflow run, two clicks) or add a
   "run all stale agents on workflow Generate" convenience path?
   Recommendation: strict two-stage in v1, ship the convenience
   button later if users ask. Predictability beats magic.
2. **Auto-slot kind resolution when bound input has no catalog
   entry.** Catalog coverage is best-effort; uncatalogued classes
   currently fall back to a soft heuristic (§10.6 candidate
   discovery). Do we forbid auto-slots on uncatalogued nodes, or let
   them snapshot the heuristic? Recommendation: forbid; force the
   user to choose kind explicitly when the catalog can't tell.
3. **Chat retention.** Sessions can now collect long chat histories
   that never feed generation. Do we still persist them indefinitely
   or add a cap? Recommendation: indefinite for v1, revisit if it
   bloats `chat_messages`.
4. **LoRA dedup across agents.** If two agents have `loras_enabled`,
   the prompt-pane LoRA list could mash them together. Probably
   fine — but worth one acceptance test.
5. **Agent ordering semantics.** Position is for display only; agents
   are otherwise independent. Confirmed?

## Out of scope

- Multi-agent dependency chains ("agent B's prompt sees agent A's
  output"). Each agent is independent in v1.
- Agent templates / sharing across sessions. Future polish.
- Reordering output slots inside an agent via drag. Position is
  insertion order; rebuild by deleting and re-adding if it matters.
- Mobile / split-view layouts.
- URL-deep-link for active inspector tab + selected agent.
- The Live PR's brief drawer — replaced entirely by per-agent
  Generate. The header Generate button skips straight to workflow
  patching.

## Spec impact (when implementation lands)

- §3.x — new `comfy_session_agents` table.
- §4.x — composition section rewritten: one composer call per agent
  rather than one per generation.
- §5.1 — new endpoints listed under "Comfy session APIs".
- §10.2 — workspace layout description rewritten around the new
  three-column / split-centre shell.
- §10.7 — restructured: per-agent dynamic schema instead of
  whole-workflow dynamic schema. `prompts.payload_json` semantics
  shift from "composer output" to "merged agent outputs at run
  time"; semantically the column is the same map of slot label →
  value, but the producer changes.
- §10.8 (new) — agent model: shape, run flow, persistence, default
  seeding.
