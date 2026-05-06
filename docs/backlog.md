# Backlog

Ideas parked for later. Not on the active roadmap. Promoted to a
plan document if and when they become real work.

## LLM auto-suggest slot labels (was "Phase 2.6")

A button on the slot-map editor that proposes a label / group /
description / binding for every eligible candidate the workflow
exposes. The user reviews, edits, and saves. No autosave; the
response is just a draft.

Originally scheduled as Phase 2.6 of the comfy-workflow plan;
deferred indefinitely after Phase 2.5 shipped — manual labelling
in the slot-map editor turned out fast enough that the auto-
suggest button is not currently worth the additional LLM action,
prompt template, and review-mode UX. Revisit if real workflows
push past ~10 slots and labelling each one by hand becomes the
friction point.

### Sketch (rough — needs a fresh pass before implementing)

**Migration.** One migration on `app_settings` adding three
columns: `default_comfy_label_settings` (JSON, nullable —
sampling bundle, see Action below) and the
`comfy_import_model_name` / `comfy_label_model_name` pair (TEXT,
nullable — see Polish below).

**Action.** New per-action sampling bundle `comfy_label`,
sibling of `comfy_import` / `analyze` / `chat` / `summarize` /
`generate`. Defaults on `app_settings.default_comfy_label_settings`.
Code-level `BUILTIN_DEFAULTS`: `temperature=0.2`,
`max_tokens=8000` (the payload can be large for 20-node
workflows). Validation in `action_settings.py`.

**Prompt and response.** Input: full `graph_json` + per-class
`description_md` + user override notes from
`comfy_node_overrides` + the candidate list
`(node_id, input_name, kind, current_value, _meta.title)` + a
short style instruction (snake_case labels; group by obvious
semantic clusters — refiner, region, style, controlnet; default
`binding=llm` for text, `frozen` for numbers/scalars/enums,
`user_image` for images; never invent kinds). Response is a
`{suggestions: [{node_id, input_name, label, group, ordinal,
description, kind, binding}]}` JSON object validated against a
Pydantic schema (same `text` mode + brace-matching extractor as
`comfy_import`).

**Validation.** Every `(node_id, input_name)` must exist among
candidates of the matching `kind`; labels unique; bindings valid
for kind. On failure the wizard surfaces the error and the user
retries — no per-stage resume.

**UX.** Toolbar button "Auto-suggest labels" runs the call.
Streams events as SSE the same way `comfy_import` does
(`stage_started`, `stage_succeeded`, `stage_failed`, `done`), so
the editor can show a spinner. On success the editor enters
**review mode**: every suggested slot is rendered as a slot row
with a green `suggested` badge and Accept / Discard per row, plus
top-level Accept all / Discard all. Accepted suggestions become
real slots on Save. Pre-existing slots are preserved; an overlap
on `origin` shows side-by-side, the user picks. Re-running
auto-suggest replaces the unsaved draft; saved slots aren't
touched.

**API.** `POST /api/comfy/sessions/{id}/slot_map/suggest_labels`
— starts the LLM call, streams SSE, returns the validated
`suggestions` array on `done`. No state on the server; the client
owns review and the eventual `PUT`.

**Polish — dedicated import / label models (the deferred Q6).**
Both `comfy_import` and `comfy_label` currently fall back to the
favourite LMStudio model. Reasoning-distilled models can drop
their JSON answer into `reasoning_content` and ship empty
`message.content` even with the bumped baseline. The settings:

- `comfy_import_model_name` — pin a specific LMStudio model for
  the per-node import wizard.
- `comfy_label_model_name` — same for slot-map auto-suggest.

Both nullable. Resolution order at call time: per-action setting
→ favourite → 422 (no usable model). The LM Studio settings page
renders two model dropdowns next to the existing per-action
sampling rows. Reasoning models are **not** filtered out —
instead the dropdown row shows a warning chip ("reasoning models
often emit empty content with this action"). Pydantic validator
checks the named model exists in `lm_models` and is `enabled`.

**Out of scope.** Auto-applying suggestions (always requires user
confirmation). Suggesting `binding=library_loras` slots (gated on
the LoRA-injection L4 milestone). Suggesting frozen values for
non-text slots (the LLM proposes the slot, the user fills the
literal — auto-filling reasonable numeric defaults would be a
follow-up polish).

**Tests.** Unit tests for the validator (every suggestion ties to
a real candidate, label collision rejects, invalid kind rejects,
binding-for-kind rejects). Integration test with a faked
LMStudio (SSE event sequence, successful suggestion array,
malformed-JSON retry). Browser test (press the button, review,
Accept all, save, reload).

**Spec impact when shipped.** §10.6 grows a sub-section for the
auto-suggest endpoint and the new `comfy_label` action. §4 grows
the per-action sampling table.

### Independently-shippable subset

`comfy_import_model_name` alone is useful even without auto-
suggest — the per-node import wizard already exists and
sometimes hits the same reasoning-model surface bug. If the
wizard's reliability becomes painful before this whole feature is
revisited, the `comfy_import_model_name` setting + dropdown could
be lifted out as a self-contained polish without dragging the
rest of the auto-suggest scope along.
