# Comfy agents UI mock — ComfyMock session type

A new `comfy_mock` session type (peer of `i2i` / `t2i` / `comfy`) where
we iterate on layout / interaction variants for the agents redesign on
**real workflows** without depending on real LMStudio or real ComfyUI
generation. Backend contracts are defined in
[`comfy-agents-redesign.md`](comfy-agents-redesign.md); this doc covers
the throwaway UI layer plus the small backend hooks needed to make
ComfyMock a first-class session type.

## Status (2026-05-07)

Plan only — no code yet. Backend agent CRUD landed (PR1, see spec
§3.5 / §10.8). The next milestone is ComfyMock; per-agent `/run` and
real workflow Generate (PR2/PR6) wait until a UI variant wins.

## Why a session type instead of a `/playground` page

Switched from the original "browser-only playground page" plan once
the user pointed out that:

1. Workflow upload, readiness gate, slot-map editor, catalog,
   per-node import — all of that already works the way ComfyMock
   would need it. A separate page would re-mock all of it; a session
   type **reuses every bit of it for free**.
2. Multiple ComfyMock sessions with different real workflows can
   coexist, so we evaluate each variant against several real shapes
   (simple t2i, regional, controlnet i2i, …) instead of a fixture
   library we'd have to author.
3. The frontend is already split by feature (`features/i2i`,
   `features/t2i`, `features/comfy`); a `features/comfymock` slot
   drops in cleanly without touching the others.

What stays mocked / browser-local:

- The per-agent LLM call (emulated with a 10-second delay and
  kind-aware canned output).
- Workflow Generate execution (no patch, no queue, no ComfyUI
  call) — replaced with a snapshot-and-fake-render step.
- Job history (localStorage per session) — see "Gallery snapshots"
  below.
- Chat replies (echo what the user wrote).

What stays real:

- Workflow upload + slot map + catalog (existing endpoints).
- Source images (existing upload, real DB rows + files).
- Agents CRUD (the table that just landed in PR1).
- Agent `last_value`s — when an agent "runs", we PATCH the agent
  with the fake values, so they persist across reload exactly the
  way real runs will.

## Backend changes

Tiny — most of the work is frontend.

### Migration `017_comfy_mock_session_type.sql`

Adds `'comfy_mock'` to the `sessions.session_type` CHECK constraint,
following the same SQLite table-rebuild recipe as
`013_comfy_session_type.sql`. No new columns; the workflow FK and
existing comfy machinery already cover ComfyMock's needs.

### Session-type guards

`_ensure_comfy_session` (and the analogous checks in
`_resolve_comfy_session_workflow`, slot-map endpoints, agent endpoints)
currently rejects anything that isn't `session_type == 'comfy'`.
Update them to accept `('comfy', 'comfy_mock')` — a small helper
`COMFY_LIKE_TYPES` in `app/storage/session_repo.py` keeps it readable.
All existing comfy endpoints (workflow upload, readiness, slot map,
agent CRUD, seed_default) start working for `comfy_mock` sessions
without any other change.

### Future: per-agent `/run` (next backend PR)

When the real `/run` endpoint lands, it branches on `session_type`:
`comfy` calls real LMStudio; `comfy_mock` returns the kind-aware
canned output server-side instead. v0 of ComfyMock keeps the
emulation client-only — `/run` doesn't exist yet, the frontend
PATCHes the agent directly with fake `last_value`s.

### Spec impact

§3.2 (sessions) gains `comfy_mock` as an accepted `session_type`;
§9 lists ComfyMock under "post-MVP, design exploration"; §10.8 grows
a "ComfyMock" subsection that documents the session type, what's
real, and what's emulated.

## Frontend layout

```
frontend/src/features/comfymock/
├── workspace/
│   ├── ComfyMockWorkspace.tsx       // shell + variant switcher
│   ├── ComfyMockHeader.tsx          // header with workflow name +
│                                    // KnobsStrip toggle + variant switch
│   └── ComfyMockWorkspace.module.css
├── mocks/
│   ├── llm-emulator.ts              // 10s delay, kind-aware output
│   ├── chat-emulator.ts             // echoes user message back
│   ├── job-snapshots.ts             // localStorage-backed history
│   └── fake-result.ts               // procedural placeholder image
├── variants/
│   ├── VariantALayout.tsx           // 3-col classic
│   ├── VariantBLayout.tsx           // top agent strip
│   ├── VariantCLayout.tsx           // canvas-first drawers
│   ├── VariantDLayout.tsx           // IDE-like
│   └── VariantELayout.tsx           // inline canvas (agent bubbles
│                                    // attached to bound inputs)
├── components/
│   ├── AgentCard.tsx                // list item
│   ├── AgentEditor.tsx              // full editor
│   ├── OutputSlotRow.tsx
│   ├── NodeTreeViewer.tsx           // read-only graph + click
│   ├── InputDrawer.tsx              // input → binding info
│   ├── GalleryCard.tsx              // job thumbnail + actions
│   ├── SnapshotViewer.tsx           // full job state inspector
│   ├── RunningJobCard.tsx           // pinned-progress card
│   ├── SourcesPanel.tsx             // reuses real upload endpoint
│   ├── ChatPanel.tsx                // echo emulator
│   └── KnobsStrip.tsx               // CSS-var sliders + manual input
└── index.ts
```

Plus: register the `comfy_mock` arm in `routes/workspace.tsx`'s
session-type dispatch and add ComfyMock as a creation option in the
session-creation modal.

## Variant switching

URL param `?variant=a|b|c|d|e`, persisted to localStorage. Switcher
lives in `ComfyMockHeader` as a dropdown next to the workflow name.
Switching variants does **not** lose state — agents, sources, chat,
and job history are session-scoped, so swapping the layout file
keeps everything in place.

A "Reset variant state" button next to the switcher clears
localStorage entries scoped to the current `(session_id, variant)`
pair — useful when a layout's position / scroll state gets weird.

## The five v0 variants

All five compose the same shared components (`AgentEditor`,
`NodeTreeViewer`, etc.). Layouts are pure JSX/CSS.

### A — 3-col classic

```
┌──────────┬──────────────┬──────────┐
│ Agents   │ Node tree    │ Slots    │
│ list +   │ ───────────  │ Inputs   │
│ selected │ Gallery      │ Sources  │
│ panel    │              │ Nodes    │
│          │              │ Chat     │
└──────────┴──────────────┴──────────┘
```

Matches the redesign doc. Left: agents list + selected-agent panel.
Centre: vertical split (node tree top, gallery bottom, draggable).
Right: inspector tabs.

### B — top agent strip

```
┌─── Agent pills (horizontal) + add ───────────┐
│ [Selected agent editor strip, collapsible]   │
├──────────────────┬───────────────────────────┤
│ Node tree        │ Slots                     │
│ ──────────────   │ Inputs                    │
│ Gallery          │ Sources / Nodes / Chat    │
└──────────────────┴───────────────────────────┘
```

Agents become a tab-strip in the header. Selecting opens the
editor strip below the header (collapsible). Centre full-height,
right inspector mirrors A. Trades agent visibility for centre
real estate.

### C — canvas-first drawers

```
┌───┬─────────────────────────────────────────┐
│ag │                                         │
│rai│       Node tree (full)                  │
│l  │                                         │
│   ├─────────────────────────────────────────┤
│   │ Gallery drawer (slides up)              │
└───┴─────────────────────────────────────────┘
                    ↑ Inspector (right drawer)
```

Big centre node tree. Agents in a thin left rail (collapsed cards;
click expands into a popover-style editor). Gallery + inspector are
slide-in drawers. Most node-tree real estate, most clicks for
ancillary tools.

### D — IDE-like

```
┌─────┬────────────────────────────────────┐
│ Tabs│  Centre work area                  │
│ ─── │  ────────────────────────────────  │
│ Ag. │  Selected: agent editor or node    │
│ Src │  tree (mode-toggle in centre top)  │
│ Insp│                                    │
├─────┴────────────────────────────────────┤
│ Gallery footer panel (collapsible)       │
└──────────────────────────────────────────┘
```

Left rail = vertical tab bar (Agents / Sources / Inspector). Centre
= one big work area that toggles between "edit agent" and "view node
tree" modes (mode-toggle pills at the top of the centre). Footer =
gallery as a collapsible panel, like a terminal in VSCode. Trades
parallel viewing for focus.

### E — inline canvas

```
┌──────────────────────────────────────────┐
│ Node tree as the workspace               │
│   ┌──KSampler──┐                         │
│   │ seed: 12345 [frozen]                 │
│   │ positive  ⟵ [Composer · positive]    │
│   │ negative  ⟵ [Composer · negative]    │
│   └────────────┘                         │
│ Gallery strip across the bottom          │
└──────────────────────────────────────────┘
                 ↑ Inspector floating right drawer
```

Agents rendered as **bubbles attached to the inputs they bind** on
the node tree itself. Click a bubble → edit the agent inline (popover
above the bubble). No separate agents column at all — they live where
their output lands. Gallery is a horizontal strip across the bottom;
inspector is a floating right drawer. Highest information density,
biggest design risk.

## Mocks

### `llm-emulator.ts` (10-second delay)

```
emulateAgentRun(agent, workflow): Promise<{[slotId]: value}>
```

10 s `setTimeout`. Returns a kind-aware fake value per output slot:

- `multiline_text` / `text`: `"[<slot.label>] Re: \"<agent.prompt>\"
  — <kind-appropriate filler>"` (e.g. "soft lighting, high detail,
  warm colours" for positive prompts).
- `number_int` / `number_float`: `metadata.default` ± a small
  random nudge.
- `boolean`: alternates true/false per call (deterministic-by-id).
- `enum`: random pick from `metadata.options`.
- LoRAs (when `agent.loras_enabled`): a fixed 2–3 entries from a
  fixture LoRA list; merged into the session-level fake LoRA list
  shown in the inspector.

The 10 s delay is intentional — long enough that the user feels the
loading states in each variant and we get a real read on whether the
layout handles "agent is busy" gracefully (spinner placement,
disabled state on Generate, can-other-agents-run-in-parallel, …).

### `chat-emulator.ts`

```
emulateChatReply(messages): Promise<string>
```

Echoes the last user message back as `"You said: <text>"`. No
further intelligence — chat in ComfyMock is for testing the chat
panel's layout, not its content.

### `fake-result.ts`

When workflow Generate fires, render a procedural placeholder
result: a 512×512 canvas with a gradient backdrop + the workflow
name + a small block of bound slot labels and their values. Save
the canvas as a `data:image/png` for the gallery card thumbnail.
No real disk write; the result lives inside the snapshot.

### `job-snapshots.ts`

A small localStorage-backed store keyed by `session_id`. Each entry:

```
{
  id: string,                  // uuid
  createdAt: number,
  workflowId: string,
  workflowName: string,
  slotMap: <verbatim copy>,
  agents: <full agent rows including last_values>,
  sources: [{id, name, blobUrl, mainFlag}],
  boundValues: { [workflow_slot_label]: any },  // patched-in payload
  resultDataUrl: string,                         // from fake-result
  status: 'success' | 'error',
}
```

Up to 50 entries per session, LRU eviction. Shown in the gallery
newest-first.

`SnapshotViewer` opens a card → modal with three panels:

- **State** — every agent's prompt + model + output_slots at run
  time, as if you were viewing the live editor but read-only.
- **Bindings** — the `boundValues` map, one row per workflow slot,
  showing which agent / output produced the value.
- **Result** — the placeholder image full-size.

A `Use as starting point` button copies the snapshot's agents (sans
last_values) back to the live state. Live agents must be empty (or
the user confirms an overwrite).

## Workflow Generate emulation

```
runWorkflow(): Promise<JobSnapshot>
```

1. Validate every `binding=llm` workflow slot has a bound agent
   output with non-null `last_value`. On failure, surface the
   missing slot labels and abort (matches the real PR6 behaviour).
2. Resolve `boundValues`: for each workflow slot, fetch the bound
   agent output's `last_value` (or `metadata.value` for `frozen`,
   or the active session source for `user_image`).
3. Wait 1.5 s (mimicking queue time — short, distinct from the
   per-agent 10 s).
4. Render the `fake-result` placeholder.
5. Build the `JobSnapshot`, push to localStorage, surface in the
   gallery.

A `RunningJobCard` pins to the gallery top while the 1.5 s wait is
in flight, showing a fake progress bar.

## KnobsStrip (from v0)

A devtools strip at the bottom of `ComfyMockWorkspace`, toggled
with a button in the header (or `?knobs=1`). Shows:

- Sliders **and** numeric inputs for every CSS variable a variant
  declares. The active variant publishes its tunables through a
  small `useKnobs(['--agents-col', '--gallery-split', …])` hook;
  KnobsStrip discovers them at render time.
- A select for "snap to preset" — variants ship 2-3 named presets
  (`'compact'`, `'spacious'`, …) so we can quickly compare extremes.
- A "Copy CSS" button — emits a snippet of the current variable
  values for pasting into the variant's stylesheet when we lock
  them in.

Knob values persist to localStorage keyed by `(variant, knob_name)`.

## Sequencing

Rough estimate. Ship in this order; review after each step.

1. **Backend hookup** — migration, session-type guards, session
   creation accepts `comfy_mock`. ~1 h.
2. **`features/comfymock` skeleton** — workspace shell, variant
   switcher, KnobsStrip wiring (no real layouts yet — variant A
   renders a placeholder). Mock provider + emulators land here too.
   ~3 h.
3. **Shared components** — `AgentEditor`, `NodeTreeViewer`,
   `OutputSlotRow`, `GalleryCard`, `SnapshotViewer`, `ChatPanel`,
   `SourcesPanel`. Each renders against the mock provider in
   isolation. ~6 h.
4. **Variant A layout** — first complete pass; full agent CRUD →
   per-agent run (10 s) → workflow Generate → snapshot in gallery
   round-trip works. ~2 h.
5. **Workflow + sources reuse path** — verify uploading a real
   workflow into a ComfyMock session works (it should — the
   readiness gate, slot-map editor, source upload should all work
   with no changes). ~1 h dogfood + bug fixes.
6. **Variants B–E** — each is composition of the same shared
   components into different layouts. ~1.5 h each ≈ 6 h.

Total ≈ 2 days. After step 4 we already have something to look at.

## Out of scope

- Replacing the real `comfy` session type — ComfyMock is purely
  additive, both coexist.
- Persisting job history server-side — localStorage is plenty.
- Image generation realism — placeholder is fine; the design we
  care about is around the *gallery card and snapshot viewer*, not
  the image itself.
- Mobile / responsive — desktop only.
- Animation polish — concept first.
- Auth, network errors, retry — variant exploration only.

## When we converge

1. User picks a winning variant.
2. Copy that variant's layout file to
   `frontend/src/features/comfy/workspace/`.
3. Replace mock emulators with real API hooks (per-agent `/run`
   from PR2 of the backend track; workflow Generate from PR6).
4. Snapshot history moves from localStorage to a real
   `comfy_jobs` table (Phase 3 backend work, already planned).
5. Delete `frontend/src/features/comfymock/`.
6. Drop `comfy_mock` from the session-type CHECK constraint
   (migration with one-time data move: archive any leftover
   ComfyMock sessions or convert them to `comfy`).

## Open questions

1. **ComfyMock session creation entry point.** Where does the
   "create ComfyMock session" affordance live in the UI? In the
   session-creation modal as a third option next to "i2i / t2i /
   comfy"? Or hidden behind a dev flag? Recommendation: visible in
   the modal, labelled "ComfyMock (UI exploration)" with a small
   warning that runs are emulated.
2. **localStorage budget.** 50 snapshots × ~30 KB JSON each ≈
   1.5 MB per session. Sound? If we want more headroom, drop the
   placeholder image data URL out of the snapshot and regenerate
   on view.
3. **Per-agent run streaming.** v0 ships a single 10 s delay then
   resolved promise. Want streaming (token-by-token) for realism?
   Costs ~1 h emulator complexity, may be worth it for the layouts
   that show progress per agent (e.g. variant E's bubbles).
4. **Side-by-side variant comparison.** A "split-screen" mode that
   renders two variants in two halves with the same state — worth
   building, or trust the dropdown switch + quick toggle?
   Recommendation: skip in v0, add if we find ourselves
   re-toggling constantly during review.
