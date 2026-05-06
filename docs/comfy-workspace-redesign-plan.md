# Comfy workspace redesign plan — Live PR

This doc supersedes the §"Workspace UX (Phase 3 layout)" notes in
[`comfy-workflow-plan.md`](comfy-workflow-plan.md). The first two
PRs of the redesign have landed; only the Live PR remains, and it
gates on the Phase 3 backend tracked in that other doc.

## Status (2026-05-06)

**Done — Restructure PR.** `frontend/src/features/{i2i,t2i,comfy}/`
landed; comfy organisms moved into `features/comfy/`;
`routes/workspace.tsx` is a thin three-way dispatch by
`session_type`; per-feature workspace shells (`I2iWorkspace`,
`T2iWorkspace`, `ComfyWorkspace`) extracted from the old
`WorkspaceRoute`. Pure code organization — no behaviour change.

**Done — Mock PR.** Comfy step machine dropped. `ComfyWorkspace`
runs the readiness gate one-time (until `ready=true`), then mounts
the 3-column shell:

- **Left** — `ChatColumn` (ChatPane + payload-preview PromptPane).
- **Centre** — `GalleryColumn` with empty state.
- **Right rail** — `InspectorRail` with five tabs:
  - **Slots** — read-only summary, grouped by `group`, kind +
    binding chips, ✏ icon opens the slot-map drawer.
  - **Bindings** — lists every `binding=user_image` slot with a
    "not picked" placeholder + Phase-3 copy.
  - **Frozen** — lists every `binding=frozen` slot with the same
    placeholder treatment.
  - **Sources** — embeds the shared `SourceImagesPane`.
  - **Nodes** — compact readiness summary; if readiness regresses,
    the inline gate surfaces here (no full-screen rewind).

Slot-map editing is a right-side drawer (`SlotMapDrawer` wraps the
existing editor body). The header has a prominent **Generate**
button — disabled in Mock PR with a tooltip pointing at the Live
PR. Spec §10.2 / §6.1 / §8 updated.

**Pending — Live PR.** Phase 3 generation cycle landing inside the
new shell. Depends on
[`comfy-workflow-plan.md`](comfy-workflow-plan.md) Phase 3 backend.

## Live PR scope

### Backend prerequisites

Tracked in `comfy-workflow-plan.md` Phase 3, not here:
`comfy_jobs` tables, queue, WS consumer, workflow patcher per
`slot_map_json`, image upload, `/api/prompt` queueing, result
fetching + persistence, cancel endpoint.

### Gallery cards (centre column)

Replace the empty state with per-job cards, **newest first**.

- Each card carries: thumbnail (click → fullscreen lightbox), the
  job's `bindings` + `frozen` snapshot collapsed under it, and
  per-card actions: `Regenerate with same overrides` (lifts the
  prior job's snapshot back into the rail), `Show payload`,
  `Delete`.
- The collapsed snapshot is what makes "what changed between two
  runs?" answerable at a glance — keep the diff inline.

### Running-job progress card

Pinned to the top of the gallery while a job is in flight. Streams
progress events from the backend WS / SSE bridge. Cancel button
posts to the Phase 3 cancel endpoint.

### Bindings tab — live state

Per-slot image-binding picker, one row per `binding=user_image`
slot.

- Session-scoped state (survives across generations, persisted on
  the session row or a sibling table — backend choice in Phase 3).
- Drag-or-pick from the Sources tab thumbnails.
- Phase 3's `payload_overrides[<label>]` reads from this state at
  generate time.
- A "clear" affordance per slot reverts to "not picked" (which
  blocks Generate when the slot is required).

### Frozen tab — live state

Per-slot frozen-override editor, one row per `binding=frozen`
slot.

- Kind-appropriate widgets: number / boolean / enum / lora / text
  reuse the same primitives the slot-map editor already has.
- "Use slot-map value" toggle per slot — when on, no override is
  sent and the saved slot-map value stands.
- Edits are **session-scoped** — they never write back to the
  slot map. The slot-map drawer stays the place for workflow-wide
  changes.

### Brief drawer (replaces `GenerateModal` for comfy)

Inline drawer (≤50% width) opened by the header **Generate**
button.

- On open: `POST /summarize-chat`, stream the brief into a
  read-only markdown preview.
- Bindings + Frozen state already lives in the rail, so the
  drawer body is just `Brief preview + Confirm` — no embedded
  per-slot editors. The non-comfy `GenerateModal` keeps its
  current shape.
- Confirm queues the job. Drawer closes. Progress moves to the
  centre running-job card and streams via SSE / WS.
- Failures keep the drawer open for retry.

### Spec updates that land with the Live PR

- §10.2 grows the gallery + brief-drawer + Bindings/Frozen
  live-state details (currently described as "Mock PR is
  read-only").
- §10.x picks up the Phase 3 endpoint vocabulary
  (`/api/comfy/jobs*`, SSE / WS event names) from
  `comfy-workflow-plan.md`.

## Out of scope

- Legacy i2i / t2i layouts — untouched.
- Session creation flow (`/sessions/new`) — unchanged.
- Multi-session split-view, drag-to-reorder slots, mobile layouts.
- Auto-suggest slot labels — parked in
  [`backlog.md`](backlog.md).
- URL-deep-link for the active inspector tab and drawer state.
  Local component state is fine for Live PR; query-param wiring
  can land later if it earns its keep.
