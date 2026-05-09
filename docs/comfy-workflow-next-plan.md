# ComfyUI workflow — next plan

Consolidates the four previous comfy plans (`comfy-workflow-plan.md`,
`comfy-agents-redesign.md`, `comfy-agents-ui-mock-plan.md`,
`comfy-workspace-redesign-plan.md`) into a single living doc covering
what's left. Once a track here ships, the relevant parts move into
`docs/spec/technical_specifications.md` and stop living here.

## Status (2026-05-08)

**Shipped end-to-end.**

- Phase 1 — readiness gate, catalog, per-node import wizard, ComfyUI
  settings card. Spec §10.1–§10.5.
- Phase 2.5 — workflow-declared, typed, labelled slot list with
  per-slot bindings (`llm` / `frozen` / `user_image` /
  `library_loras`-reserved). Spec §10.6.
- Phase 3 prep — `GeneratedPayload` keyed by slot label, dynamic
  schema, mode inference, persistence column on `prompts`. Spec
  §10.7. The implicit-composer call path is **superseded** by the
  agents redesign but kept in the tree until workflow Generate
  switches to reading agent `last_value`s.
- PR-2 prep — generation id, output slot map, on-disk layout,
  LoadImage/SaveImage gates, per-session `comfy_input_cleanup`. Spec
  §10.7's "PR-2 prep" subsection.
- **Agents PR1** — `comfy_session_agents` table (migration 016),
  full CRUD, `seed_default`, per-agent `/run` (LMStudio + VL on
  `source` input slots, slot-aware system prompt, validated /
  coerced JSON output, `last_value` persistence). Spec §10.8.
- **Comfy workspace IDE shell** — `features/comfy/`: readiness gate,
  agents list + editor, slot/output editors, `MappingTreeShell` with
  `InputContextPanel`, `NodeTreeViewer`, gallery, knobs strip, chat
  panel. Spec §10.9.
- Backend chat slot-awareness (Q9) — the real
  `/api/sessions/{id}/chat` endpoint inlines the slot list + plain-prose
  instruction for comfy sessions. Spec §4.2.

**Not shipped — what this doc covers.**

1. **Frontend chat for comfy is mocked.** `features/comfy/components/
   ChatPanel.tsx` uses `mocks/chat-emulator.ts` (echoes user back).
   The real backend endpoint exists, is slot-aware, and is unused
   by the comfy workspace.
2. **Workflow-level Generate is mocked, and the surface is wrong.**
   `runWorkflow` in `state/ComfyProvider.tsx` renders a procedural
   PNG after a 1.5 s delay and saves it to localStorage via
   `mocks/fake-result.ts` + `mocks/job-snapshots.ts`. There is no
   server endpoint, no `comfy_jobs` table, no graph patcher, no
   image upload, no ComfyUI WS consumer, no result fetch.
   `comfy_client.py` carries only the connection check. The
   current `Generate workflow` button on `ComfyHeader.tsx` is
   replaced by `Single Run` / `Batch Run` at the bottom of the
   agents column (see Track B); the run itself is visualised in
   a dedicated Run Viewer rather than a header-level toast.
3. **`SourceSlot` indirection lives in localStorage.**
   `state/source-slots.ts` is browser-only; the per-input-slot
   `source_image_overrides` payload sent to per-agent `/run` is
   resolved client-side. Workflow Generate will need the same
   mapping for `binding=user_image` workflow slots, persisted
   server-side.
4. **`comfy_mock` enum lingers.** Migration 017 added it; the
   workspace shell collapsed both types into one shell, so the
   enum value (and `features/comfymock/`'s empty dirs) is dead
   weight.

## What's left

Three tracks. Land in this order — chat is small and unblocks user
testing while track B lands; track C cleans up once track B is
proven.

### Track A — Wire the real chat into the comfy workspace

Goal: delete the emulator, render real assistant turns, get the
slot-aware system prompt the backend already produces.

- Replace `features/comfy/components/ChatPanel.tsx` with the shared
  `components/molecules/ChatPane`, the same one `I2iWorkspace` and
  `T2iWorkspace` mount. The shared pane already handles SSE
  streaming, history persistence, edit-and-resend, clear, mention
  popover, and per-action sampling settings.
- Delete `mocks/chat-emulator.ts` and the `chat` /
  `sendChat` / `clearChat` browser-only state in
  `state/ComfyProvider.tsx` — the shared pane owns history via
  `useMessages` + the chat-stream hooks.
- Keep the chat panel slot in the IDE-shell's left tab bar (same
  position it has now). The "reference-only" copy in the panel
  header stays — the agents redesign deliberately demoted chat
  away from being the source of creative direction.
- **Agents-awareness (extends Q9).** The chat system prompt for a
  comfy session today inlines the slot list. Add a one-line-per-
  agent block underneath: `<name>: bound to <labels…>` so the
  consultant can answer "what should I put in the
  Foreground/positive agent?". Same soft-fail rules as the slot
  block — empty agent list ⇒ no block.

Estimated PR shape: one frontend PR replacing the panel, one tiny
backend PR adding the agents block to `app.api.chat`'s system
prompt (extends `_resolve_chat_mode_and_slots`).

Spec edits when shipped: §4.2 grows the agents-block paragraph.

### Track B — Workflow generation pipeline (Phase 3 proper)

Goal: the **Single Run** button at the bottom of the Agents panel
drives the full pipeline — agents → LMStudio unload → image upload →
ComfyUI queue → result persistence → cleanup — and the workspace
visualises every stage in a focused run viewer. This is the big
chunk.

**Header changes.** The standalone `Generate workflow` button on
the workspace header (`ComfyHeader.tsx`) is removed. Generation is
not a header-level concern any more; it lives next to the agents
that produce its inputs.

**Agents-panel footer.** Two buttons pinned to the bottom of the
left agents column:

- `Single Run` — runs the full pipeline end-to-end against the
  current session state (B6 below). Always enabled when every
  `binding=llm` slot has a bound agent output and every required
  `binding=user_image` slot has an image picked; otherwise
  disabled with a tooltip listing the missing pieces.
- `Batch Run` — placeholder, disabled in this phase. Future-phase
  work, see "Future — Batch Run" below.

The per-agent `Generate` button stays inside the agent editor —
useful for iterating on one agent's output without firing the
whole pipeline.

#### B1. `comfy_client.py` — full client surface

Today it has the connection check only. Extend it to mirror
`lmstudio_client.py`:

- One process-wide `client_id`, one persistent WebSocket to
  `/ws?clientId=…`, per-job asyncio queues demuxed by `prompt_id`.
- `POST /api/prompt` — queue a workflow.
- `POST /api/upload/image` — upload a source image, capture the
  returned filename.
- `GET /history/{prompt_id}` — fetch outputs after a job finishes.
- `POST /api/interrupt` — best-effort cancel.
- `comfyui_api_key` honored on every request.
- Auto-reconnect with backoff. In-flight jobs surface a
  `connection_lost` SSE event and flip to `error` if reconnect
  doesn't recover the `prompt_id` within a grace window.

#### B2. Persistence — `comfy_jobs` + `comfy_job_outputs`

One migration (`019_comfy_jobs.sql`):

- `comfy_jobs` — `id` (random hex), `session_id` (FK
  `sessions(id) ON DELETE CASCADE`), `workflow_id`, `prompt_id`
  (string from ComfyUI), `generation_id` (the
  `YYYYMMDD-HHMMSS-rrrrrr` stamp from PR-2 prep, used as the
  on-disk folder name), `payload_json` (slot label → value at run
  time, merged from agent `last_value`s + frozen + image bindings),
  `slot_map_snapshot_json` (frozen slot list at run time),
  `agents_snapshot_json` (every agent's prompt + model + output
  values at the moment of the run, for reproducibility-of-record),
  `status` (`queued` | `running` | `success` | `error` |
  `cancelled`), `error_message` (nullable), `started_at`,
  `finished_at`.
- `comfy_job_outputs` — `id`, `job_id` (FK
  `comfy_jobs(id) ON DELETE CASCADE`), `slot_label` (string,
  matches the `output_slot_map_json` entry), `node_id`,
  `output_index`, `path` (relative to `data/`), `is_primary`
  (bool — first output of the first SaveImage-class node, used
  as the gallery thumbnail), `created_at`. SaveImage results not
  in the output map are recorded with `slot_label=NULL` and
  surfaced as "untracked" warnings on the run row.

Output files land at
`data/images/<session_id>/output/<generation_id>/<slot_label>.<ext>`,
matching the layout PR-2 prep already documented in §10.7.

#### B3. Graph patching

`comfy_graph_patcher.py` operates on a deep copy of `graph_json`
and never mutates the workflow row. For each slot in
`slot_map_snapshot_json`:

- `binding=llm` ⇒ inject the bound agent output's `last_value`
  resolved from `agents_snapshot_json`. If unbound or
  `last_value=None`, the calling endpoint already aborted — the
  patcher trusts the snapshot.
- `binding=frozen` ⇒ inject `metadata.value`, with per-slot
  override from the request body's `payload_overrides[<label>]`
  (the seed/sampler escape hatch).
- `binding=user_image` ⇒ inject the uploaded ComfyUI filename,
  resolved per slot from the new server-side source-image map
  (B5). `(unset)` slots are skipped (graph keeps its baked
  literal).
- `binding=library_loras` ⇒ remains rejected (deferred to L4).
- Slot with no `origin` wired ⇒ skip.

Per-slot validation matches `comfy_payload`'s existing rules —
booleans rejected for int slots, enums against `metadata.options`,
etc.

#### B4. Image upload flow

For every `binding=user_image` slot bound to a session source
image:

- `POST /api/upload/image` to ComfyUI with the file content.
- Capture the returned filename, use it as the literal in the
  patched `(node_id, input_name)`.
- Per-job upload — no hash-based reuse cache yet (Phase 3 cost
  is dominated by generation, not upload; revisit if it ever
  shows up in profiling).
- After the job lands, the per-session `comfy_input_cleanup`
  policy decides whether to delete the uploaded files via the
  resolved input dir. `delete` soft-degrades to `keep` with a
  warning when no path is reachable.

#### B5. `SourceSlot` graduation — server-side persistence

Today the source-slot table (`features/comfy/state/source-slots.ts`)
lives in localStorage. Workflow Generate needs to persist
per-slot-label → image bindings server-side so historical jobs
record exactly which images they ran against. Two options; pick
when sequencing the PR.

- **Option α (lean) — drop the slot indirection entirely.**
  `binding=user_image` workflow slots store `metadata.source_image_id`
  directly (FK semantics enforced in service code, since `metadata`
  is JSON). Agents' `source` input slots already accept a session
  image id directly via `source_image_overrides` on `/run` — fold
  source-slots out of the agent payload too. Migration drops nothing
  (slot-map JSON is rewritten in place via the existing v1→v2
  upgrade mechanism). Ships smaller, no new table.
- **Option β (indirection-keeping) — promote `SourceSlot` to a
  table.** New `comfy_session_source_slots` (FK
  `session_id → sessions(id)`), columns mirror the localStorage
  shape. Slot-map metadata + agent input slots reference rows by
  id. More change, keeps the "named slot you can re-bind without
  touching every consumer" property the localStorage table has.

Recommendation: ship α first. The indirection is currently exercised
only in the mock layer; nothing in the agents PR1 backend persists
it. If users start asking for "named source slots I can swap behind
the scenes", upgrade to β in a follow-up.

#### B6. Single Run endpoint — orchestrated pipeline

`POST /api/comfy/sessions/{id}/single_run`:

- Body: `{payload_overrides?: {<slot_label>: <value>},
  rerun_agents?: bool}`.
  - `payload_overrides` is a free-form map, validated per-slot
    against the slot's `kind` (422 on mismatch). `binding=llm`
    overrides are accepted (power-user escape hatch) even though
    the UI only surfaces frozen + image overrides.
  - `rerun_agents` (default `true`) — when true, every agent is
    re-run before the patch step (the v1 default behaviour the
    button gives you). `false` is the API-level escape hatch for
    "I just edited frozen overrides, don't re-spend on LLM
    calls" — the orchestrator skips agent runs and uses each
    agent's existing `last_value`s as-is.
- Behaviour — one orchestrated pipeline, every stage publishes a
  named event on the run's SSE channel so the viewer can render
  per-stage status and values as they arrive. The pipeline is
  serial; failure at any stage flips the run to `error`,
  short-circuits remaining stages, and still runs the
  `unload_comfy` + `cleanup` stages so we don't leak VRAM or
  uploaded files.

  1. **`validate`** — walk every `binding=llm` slot, confirm the
     bound agent output exists; walk every required
     `binding=user_image` slot, confirm an image is bound. 409
     with the missing labels on failure (no `comfy_jobs` row
     created).
  2. **`snapshot`** — snapshot the slot map, the agent list, and
     the merged payload-pre-rerun. Insert a `comfy_jobs` row in
     `running` (no `queued` state — the orchestrator drives
     synchronously up to the ComfyUI queue point). Stamp
     `started_at` and the `generation_id`.
  3. **`agents`** — for each agent (in `position` order) when
     `rerun_agents=true`: emit `agent_started` (with `agent_id`,
     `name`, `model_name`), call the same composer the per-agent
     `/run` endpoint already uses, persist new `last_value`s,
     emit `agent_finished` with the slot-keyed output preview.
     Failures emit `agent_failed` with the error message and
     short-circuit. With `rerun_agents=false`, this stage emits
     a single `agents_skipped` event and moves on.
  4. **`unload_lm`** — call LMStudio's `Unload all` (the same
     endpoint the settings card already exposes). The whole
     point is to free VRAM before ComfyUI starts. Soft-fails:
     if LMStudio is unreachable or the unload errors, emit
     `unload_lm_warning` and continue — generation may still
     succeed if the box has enough VRAM for both, and the user
     would rather see the result than a blocked run.
  5. **`upload_inputs`** — for each `binding=user_image` slot
     bound to a session image, emit `upload_started` with the
     slot label + filename, `POST /api/upload/image` to ComfyUI,
     emit `upload_finished` with the returned filename.
  6. **`patch`** — graph patcher (B3) emits `patch_started`,
     produces the patched graph, emits `patch_finished`. Includes
     the merged `payload_json` snapshot in the event so the
     viewer can show "what's about to be sent".
  7. **`queue`** — `POST /api/prompt`, capture `prompt_id`,
     persist on the row. Emit `queue_position` events as the WS
     reports them.
  8. **`execute`** — drive the WS consumer. Re-emit ComfyUI's
     own `progress`, `executing` (per-node), and `executed`
     events to the SSE channel keyed by `node_id` so the run
     viewer can light up the corresponding node in the
     bound-subset tree. On each `executed` for a node in the
     output map, fetch the output from `/history/{prompt_id}`,
     copy files into
     `data/images/<session_id>/output/<generation_id>/`, insert
     `comfy_job_outputs` rows, emit `image_ready` with the slot
     label + URL.
  9. **`save`** — flip `comfy_jobs.status='success'`, stamp
     `finished_at`. Emit `save_finished` with the gallery card
     payload (job id, primary image URL).
  10. **`unload_comfy`** — POST `/api/free` on ComfyUI with
      `unload_models=true` + `free_memory=true` so the checkpoint
      / VAE / LoRAs vacate VRAM. Mirrors `unload_lm` at the start;
      same soft-fail rules — a dead ComfyUI socket emits a
      warning and continues. Always runs (the run already
      finished — the only question is whether the unload landed).
  11. **`cleanup`** — run the per-session `comfy_input_cleanup`
      policy on the uploaded files. Emit `cleanup_finished`
      (with a per-slot kept/deleted summary) or
      `cleanup_warning` when `delete` had to soft-degrade to
      `keep`.
  12. **`done`** — final terminator event with the run's overall
      status (`success` / `error` / `cancelled`).

  On `execution_error` from ComfyUI: flip `status='error'`,
  persist `error_message`, emit `execute_failed`, then still run
  the `unload_comfy` + `cleanup` stages — both are
  always-run finally arms.

- Returns `{job_id, generation_id, stream_url}`. The SSE channel
  at `stream_url` is opened by the frontend immediately after the
  POST resolves.

Plus the read endpoints:

- `GET /api/comfy/jobs/{job_id}` — full row + outputs.
- `GET /api/comfy/jobs/{job_id}/stream` — SSE progress, vocabulary
  is the per-stage names listed above plus `connection_lost` for
  WS drops. Re-subscribers (e.g. tab refresh mid-run) receive a
  `replay` snapshot of every event so far before the live
  stream resumes.
- `GET /api/comfy/jobs?session_id=…` — list per session, paged,
  ordered by `started_at desc`.
- `POST /api/comfy/jobs/{job_id}/cancel` — best-effort. If the
  run is in `agents`, kills the in-flight LMStudio call. If in
  `queue` or `execute`, posts `/api/interrupt` on ComfyUI. Always
  flips status to `cancelled` and runs the `cleanup` stage.

#### B7. Frontend hookup — Run Viewer + lock state

Replace the localStorage mock with real API calls and surface the
pipeline as a focused viewer.

- `runSingle()` in `ComfyProvider` POSTs to `.../single_run`, opens
  the returned SSE stream, mirrors every per-stage event into a
  `runState` slice (current stage, per-stage status, per-node
  status, per-slot live values, accumulated warnings / errors).
- `mocks/fake-result.ts` and `mocks/job-snapshots.ts` deleted. The
  gallery reads from `useJobs(sessionId)` (new TanStack hook on
  top of `GET /api/comfy/jobs`).
- `GalleryCard` renders `comfy_jobs` rows: thumbnail from the
  `is_primary` output, payload + bindings collapsed under it, per-
  card actions (`Regenerate with same overrides` lifts the
  snapshot's `payload_overrides` into the next request, `Show
  payload` opens the stored `payload_json`, `Delete` drops the row
  + files).
- `Lightbox` opens against the file URL the new endpoint serves.
- **Frozen overrides — live tab.** The Inputs panel's frozen
  half today is a read-only mock. Wire it to a session-scoped
  state slice that flows into `payload_overrides` at Single Run
  time. Edits never write back to the slot map. Per-slot "use
  slot-map value" toggle clears the override.
- **Image bindings — live tab.** Same shape, per-slot picker over
  the session's source images (collapsed when only one source
  image + one slot exists; the auto-bind rule from the original
  Phase 3 plan still applies). Picks land in
  `payload_overrides[<label>]` and persist on the new server-side
  source map (B5).

##### Run Viewer

A new modal-shell component (`RunViewer`, full-viewport overlay
with a backdrop) opens the moment Single Run is pressed and stays
mounted until the run ends or the user dismisses a finished run.
Two regions:

- **Top — pipeline strip.** Compact horizontal stage list
  (`validate → snapshot → agents → unload_lm → upload_inputs →
  patch → queue → execute → save → unload_comfy → cleanup`). Each stage shows
  pending / running / success / failed / skipped state and the
  per-stage elapsed time once finished. Clicking a finished
  stage scrolls its events into focus in the bottom region.
- **Bottom — execution canvas.** A read-only graph view of the
  workflow's **bound subset** — every node owning a workflow
  slot (or referenced as the origin of one), laid out in
  topological execution order matching ComfyUI's resolution.
  Same node-card shape as `NodeTreeViewer` but the inputs of
  bound slots show their live value (or "pending…" / spinner /
  filled-with-checkmark) as `agent_finished`, `upload_finished`,
  `patch_finished`, `executing`, `executed`, and `image_ready`
  events arrive. Output slots in the map render their saved
  filename + a thumbnail once `image_ready` fires. Anything
  outside the bound subset is hidden — the user sees the
  pipeline-as-it-flows, not the full graph.

  The `agents` stage adds a virtual "Agents" node at the head of
  the canvas (one card per agent, each showing model + prompt
  preview + per-output-slot value as it lands). It collapses
  into a single row once the stage finishes, leaving the real
  graph nodes as the focus.

  Final stage emits a "Result" card pinned to the bottom of the
  canvas with the primary output thumbnail, a `Open in gallery`
  link, and a `Close` button that dismisses the viewer.

##### Workspace lock during a run

While `runState.status === 'running'`:

- The whole comfy workspace renders read-only — agents list,
  agent editor, mapping tree, input panels, slot-map drawer,
  source picker, knobs, gallery cards. Each interactive control
  flips to `disabled` (no half-states, no "looks editable but
  isn't"). The Run Viewer is the only live surface.
- Navigation is blocked. A TanStack-router `useBlocker`
  (or equivalent) intercepts every `navigate()` call and the
  browser back/forward buttons, popping a confirm: "A run is in
  progress. Cancel it before leaving?" Confirm cancels the
  run via `/cancel` then navigates; dismiss stays put.
- `Cancel` button on the Run Viewer's pipeline strip is the only
  un-locked control — it posts `/cancel` and waits for the
  cleanup stage to finish before closing.
- On `done`: lock releases. Workspace becomes interactive
  again. The viewer stays open until dismissed so the user can
  inspect the pipeline trace.

##### Resume on reload

Tab refresh during a run: `useJobs` returns the in-flight row
(status `running`), the workspace lock re-engages, and the Run
Viewer re-opens via the `/stream` endpoint's `replay` snapshot.
No manual recovery flow needed — the SSE re-subscribe gives back
every event the user missed.

Keep the brief drawer **out of scope** for this track. The agents
redesign moved generation off chat; the Single Run button skips
straight to validation + pipeline. The `summarize-chat` endpoint
stays as an internal tool but is not rendered.

### Future phase — Batch Run

Reserved next-phase work, captured here so the `Batch Run`
placeholder button has a clear target. Detail lands when we pick
this up; v1 just exposes a disabled button with a tooltip ("Batch
Run — coming soon").

Rough shape we're holding the slot for:

- A separate POST endpoint that takes a sweep description (varied
  values for one or more frozen slots, or a list of source-image
  bindings, or a count + per-agent prompt template) and produces N
  serial Single Runs.
- A batch viewer reusing the Run Viewer's pipeline strip per
  child run, plus a top-level batch progress bar.
- Same workspace lock + nav block as Single Run, scoped to the
  whole batch.
- Persistence: a `comfy_batches` row plus FK on each `comfy_jobs`
  row (`batch_id`).
- Cancel propagates: batch-level cancel stops the current child
  run and skips the rest.

Open until that phase: how the user authors the sweep (form vs
JSON vs preset templates), whether agents re-run per child or
once per batch, whether the batch viewer collapses finished
children or stacks them.

### Track C — Cleanup once track B lands

- Drop `mocks/chat-emulator.ts`, `mocks/fake-result.ts`,
  `mocks/job-snapshots.ts`. Drop the `chat`, `jobs`,
  `runningAgentIds`'s mock progress, and `workflowGenerateError`
  mock paths from `ComfyProvider`.
- Drop the empty `frontend/src/features/comfymock/` directory tree.
- Migration `020_drop_comfy_mock_session_type.sql` — re-tighten
  the `sessions.session_type` CHECK constraint to drop
  `comfy_mock`. Any leftover `comfy_mock` rows convert to `comfy`
  (one-time `UPDATE`); spec §3.2 records the drop.
- Update `routes/workspace.tsx` — remove the `case "comfy_mock"`
  fall-through.
- Strip the "(reference-only)" copy from the chat panel header
  once the agents-aware chat lands. The chat is still
  consultative, but the panel is no longer second-class.

## Open questions

1. **Source-slot indirection — α vs β (B5).** Pick when sequencing
   Track B. Recommendation in B5.
2. **Chat retention.** Comfy sessions can now collect long chat
   histories that never feed generation. Indefinite for v1, revisit
   if it bloats `messages`.
3. **Per-job parallelism.** ComfyUI's queue serialises by default;
   we just relay queue-position events. No explicit concurrency
   handling on our side. Confirm.
4. **Replay against post-replace workflow.** Phase 3 originally
   captured `slot_map_snapshot_json` for reproducibility-of-record,
   not replay. Holds with the agents redesign too — the
   `agents_snapshot_json` is a frozen record, not an
   instantiable copy. No replay UI.
5. **L4 LoRA injection.** Stays parked. The
   `binding=library_loras` enum value remains reserved-but-rejected
   in the slot-map editor and patcher. Pick a node-detection
   strategy (heuristic on `lora_<n>` / `strength_<n>` literals vs
   import-wizard `is_lora_stack` flag) when it's time.
6. **VL critique of the result.** Stays an architectural
   placeholder per spec §9. Worth one sweep once Track B is
   shipped to decide whether to wire it for comfy too or leave it
   as the legacy-session stub.

## Spec impact

**Track A:**

- §4.2 grows the agents-block paragraph in the comfy chat system
  prompt.

**Track B:**

- §3.x grows the `comfy_jobs` and `comfy_job_outputs` tables.
- §5.1 grows the `/api/comfy/jobs*` and
  `/api/comfy/sessions/{id}/single_run` endpoints; the per-stage
  SSE event vocabulary lands as a sub-list.
- §10.7 graduates from "PR-2 prep + composition pending" to a
  full generation-execution section, written around the Single
  Run pipeline. The "implicit composer is superseded by §10.8"
  paragraph drops once Single Run reads agent `last_value`s.
- §10.9 grows a Single Run + Run Viewer subsection (pipeline
  strip + execution canvas + workspace lock + resume-on-reload).
  The header Generate button is removed from the documented
  layout; the agents-panel footer with `Single Run` /
  `Batch Run` (latter disabled) is documented in its place. The
  "what's still emulated" subsection collapses; only the
  source-slot localStorage entry remains until the option α/β
  decision lands.

**Track C:**

- §3.2 records the `comfy_mock` enum drop.
- §10.9 drops the "remaining cleanup" subsection.

## Out of scope

- Multi-agent dependency chains ("agent B sees agent A's output").
  Each agent stays independent in v1.
- Agent templates / sharing across sessions.
- Reordering output slots inside an agent via drag.
- Batch Run (sweep-driven multi-image runs). Deferred — see
  "Future phase — Batch Run" above. The button ships disabled in
  this phase.
- Inline batching ("generate N images per click" through ComfyUI's
  own `batch_size`). Out of v1 UX; bake it into the workflow if
  you want it. Batch Run will own the multi-image story.
- Mobile / responsive layouts.
- URL-deep-link for active inspector tab + selected agent + drawer
  state.
- Re-executing historical jobs against a post-replace workflow.
- Brief drawer / `summarize-chat → compose` UX. Replaced by Single
  Run; the endpoint stays as an internal tool but is not rendered.
- LoRA injection L3 (splice `LoraLoader` nodes by rewiring
  model/clip edges). Permanently out — silent failure modes
  don't justify the surface area.
