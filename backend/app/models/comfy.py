"""Pydantic models for ComfyUI integration endpoints (Phase 1)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


ReadinessStatus = Literal["ready", "needs_config", "not_installed"]


class WorkflowUpload(StrictModel):
    """Body of POST /api/comfy/workflows.

    The graph must be ComfyUI's API-format dict (node-id keys with
    ``class_type`` + ``inputs``); the UI-format graphs that ComfyUI
    saves from the canvas are not accepted at this layer.
    """
    name: str = Field(min_length=1, max_length=200)
    graph: dict[str, Any]


class WorkflowSummary(StrictModel):
    id: str
    name: str
    graph_hash: str
    created_at: int


class WorkflowOut(StrictModel):
    id: str
    name: str
    graph: dict[str, Any]
    graph_hash: str
    created_at: int
    slot_map: dict[str, Any] | None = None
    """Phase 2.5 typed slot list. ``None`` means no map saved yet —
    the editor opens with an empty list. Stored shape is
    ``{"version": 2, "slots": [...]}`` (older rows may still carry
    ``version: 1`` and are upgraded on read by
    :func:`app.services.comfy_slot_map_service.upgrade_slot_map`).
    See :class:`SlotMapOut` for the response contract."""


class WorkflowList(StrictModel):
    workflows: list[WorkflowSummary]


class WorkflowConflict(StrictModel):
    """Returned with HTTP 409 when an upload's hash matches an existing
    workflow. The client retries with ?on_conflict=replace|rename."""
    conflict: str = "graph_hash"
    existing: WorkflowSummary


class ReadinessCardOut(StrictModel):
    """One row in the readiness panel — keyed by class_type, not by
    node id (multiple nodes of the same class share a card)."""
    class_type: str
    status: ReadinessStatus
    instance_count: int
    display_name: str | None
    description: str | None
    category: str | None
    python_module: str | None
    pack_name: str | None


class ReadinessOut(StrictModel):
    session_id: str
    workflow_id: str
    ready: bool
    """True once every card is in the 'ready' bucket — the gate the
    session lifecycle uses to transition out of the readiness panel."""
    cards: list[ReadinessCardOut]
    error: str | None = None
    """Set when the URL check failed entirely (e.g. ComfyUI down). When
    non-null, ``cards`` is empty and the UI shows a single error
    state."""


# --- catalog (Library → Comfy Nodes) ------------------------------------


class PackOut(StrictModel):
    name: str
    display_name: str
    description: str | None
    version: str | None
    repo_url: str | None
    publisher_id: str | None
    dir_path: str | None
    node_count: int
    imported_at: int


class PackDetailOut(StrictModel):
    name: str
    display_name: str
    description: str | None
    version: str | None
    repo_url: str | None
    publisher_id: str | None
    dir_path: str | None
    readme_md: str | None
    nodes: list[NodeListItemOut]
    imported_at: int


class NodeListItemOut(StrictModel):
    """Compact summary used by the library list and pack detail."""
    class_type: str
    pack_name: str
    display_name: str
    category: str | None
    description_md: str
    has_override: bool
    requires_semantic_config: bool
    imported_at: int


class NodeInputSemantic(StrictModel):
    """Per-input notes the catalog keeps alongside the raw schema.

    The Phase 1 design also stored a ``role_hint`` enum here used by an
    auto-proposed slot map. That auto-proposal was dropped in Phase 2
    (see Q7 in docs/comfy-workflow-plan.md): slot mapping is manual,
    workflow-level, and reads only the raw schema. Existing rows in
    ``comfy_nodes.inputs_semantic_json`` may still carry a role_hint
    key — we silently ignore it on read, which keeps the column sparse
    and harmless without forcing a data migration.
    """
    name: str
    notes: str | None = None


class NodeOut(StrictModel):
    class_type: str
    pack_name: str
    display_name: str
    category: str | None
    description_md: str
    inputs_raw: dict | list
    outputs_raw: list
    inputs_semantic: list[NodeInputSemantic]
    requires_semantic_config: bool
    has_override: bool
    override_updated_at: int | None
    imported_at: int
    last_seen_in_object_info_at: int


class NodeUpdate(StrictModel):
    """All fields are optional. Distinct from absent: passing ``null``
    explicitly clears that override; omitting the field keeps the
    existing value. The API layer uses ``model_fields_set`` to tell
    them apart."""
    description_md: str | None = None
    inputs_semantic: list[NodeInputSemantic] | None = None
    category: str | None = None


class PackList(StrictModel):
    packs: list[PackOut]


class NodeList(StrictModel):
    nodes: list[NodeListItemOut]


# --- Phase 2.5: workflow-declared, typed, labelled slots ------------------
#
# The Phase 2 model exposed three fixed logical slots (positive_prompt,
# negative_prompt, main_image). Phase 2.5 replaces that with a per-
# workflow list of labelled slots, each carrying a kind (text, image,
# number, …) and a binding (who fills the value at generation time).
#
# Background and the wider design — see docs/comfy-workflow-plan.md
# §"Phase 2.5". Stored payloads use ``version: 2``; older rows
# (``version: 1`` or no version key) are upgraded lazily on read.


SlotKind = Literal[
    "text",
    "multiline_text",
    "image",
    "image_alpha",
    "number_int",
    "number_float",
    "boolean",
    "enum",
    "lora_name",
    "checkpoint_name",
]


ALL_SLOT_KINDS: tuple[SlotKind, ...] = (
    "text",
    "multiline_text",
    "image",
    "image_alpha",
    "number_int",
    "number_float",
    "boolean",
    "enum",
    "lora_name",
    "checkpoint_name",
)


SlotBinding = Literal["llm", "frozen", "user_image", "library_loras"]
"""Who supplies the value at generation time.

- ``llm`` — composition LLM call (Phase 3 prep). Default for text/number
  slots.
- ``frozen`` — value is fixed at slot-map config time and reused on every
  generation. Default for non-text scalars and the catalog-derived
  combo kinds (lora_name, checkpoint_name).
- ``user_image`` — image picker / session source image. Default for
  image / image_alpha kinds.
- ``library_loras`` — sd-chisel's LoRA retriever. Reserved in the enum
  for the L4 milestone (Q3); not selectable from the editor in 2.5.
"""


ALLOWED_BINDINGS: dict[SlotKind, frozenset[SlotBinding]] = {
    "text":            frozenset({"llm", "frozen"}),
    "multiline_text":  frozenset({"llm", "frozen"}),
    "image":           frozenset({"user_image", "frozen"}),
    "image_alpha":     frozenset({"user_image", "frozen"}),
    "number_int":      frozenset({"llm", "frozen"}),
    "number_float":    frozenset({"llm", "frozen"}),
    "boolean":         frozenset({"llm", "frozen"}),
    "enum":            frozenset({"llm", "frozen"}),
    "lora_name":       frozenset({"frozen"}),
    "checkpoint_name": frozenset({"frozen"}),
}


DEFAULT_BINDING: dict[SlotKind, SlotBinding] = {
    "text":            "llm",
    "multiline_text":  "llm",
    "image":           "user_image",
    "image_alpha":     "user_image",
    "number_int":      "frozen",
    "number_float":    "frozen",
    "boolean":         "frozen",
    "enum":            "frozen",
    "lora_name":       "frozen",
    "checkpoint_name": "frozen",
}


# Kinds that, when wired as ``user_image``, mean the session is i2i.
USER_IMAGE_KINDS: frozenset[SlotKind] = frozenset({"image", "image_alpha"})


# A label may not collide with another label and must be filesystem /
# JSON-key safe. We allow alphanumerics, underscore, hyphen and dot —
# enough to express ``Region 1/positive`` style group + label without
# the editor having to escape anything.
_LABEL_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$"


class SlotOrigin(StrictModel):
    """Where the slot lives in the workflow graph."""
    node_id: str = Field(min_length=1)
    input_name: str = Field(min_length=1)


class SlotDefinition(StrictModel):
    """One labelled slot in the per-workflow slot list."""
    label: str = Field(min_length=1, max_length=64, pattern=_LABEL_PATTERN)
    group: str | None = Field(default=None, max_length=64)
    ordinal: int | None = None
    description: str | None = Field(default=None, max_length=2000)
    kind: SlotKind
    origin: SlotOrigin
    binding: SlotBinding
    metadata: dict[str, Any] = Field(default_factory=dict)
    """Kind-specific extras. For frozen scalars, ``metadata.value`` is
    the literal injected at patch time. For numbers, ``min``/``max``/
    ``step``. For enums, ``options``. The shape is validated against
    the candidate's raw schema in
    ``comfy_slot_map_service.validate_slots``."""


class SlotMapV2(StrictModel):
    """The persisted slot map. ``version`` distinguishes 2.5+ payloads
    from earlier ones (which the service upgrades on read)."""
    version: Literal[2] = 2
    slots: list[SlotDefinition] = Field(default_factory=list)


class CandidateInput(StrictModel):
    """One eligible (node_id, input_name) pair the editor can offer for
    a slot. Eligibility, the candidate's ``kind``, and any per-kind
    extras in ``metadata`` come from
    ``comfy_slot_map_service.compute_candidates``."""
    node_id: str
    input_name: str
    node_class_type: str
    node_display_name: str | None
    """Human-readable name from the catalog (``NODE_DISPLAY_NAME_MAPPINGS``
    in ComfyUI). Falls back to ``class_type`` when the node hasn't been
    imported yet."""
    node_title: str | None
    """Per-node free-form title the user set in the ComfyUI canvas
    (``graph[node_id]._meta.title``)."""
    node_in_catalog: bool
    """False when the workflow references a node class that hasn't
    been imported yet — combo subtypes (image_upload, mask, …) are
    only detected with the catalog, so uncatalogued combos appear as
    plain ``enum`` candidates."""
    current_value: Any
    """The literal currently sitting at this input — shown as a
    preview so the user can recognise which encoder is which."""
    kind: SlotKind
    metadata: dict[str, Any] = Field(default_factory=dict)
    """Kind-specific extras inferred from the raw schema. Examples:
    ``multiline`` for text kinds, ``options`` for enums,
    ``min``/``max``/``step``/``default`` for numbers."""


class CandidateBuckets(StrictModel):
    """All eligible candidates grouped by kind. Empty buckets are
    serialised as empty lists, never omitted."""
    text: list[CandidateInput] = Field(default_factory=list)
    multiline_text: list[CandidateInput] = Field(default_factory=list)
    image: list[CandidateInput] = Field(default_factory=list)
    image_alpha: list[CandidateInput] = Field(default_factory=list)
    number_int: list[CandidateInput] = Field(default_factory=list)
    number_float: list[CandidateInput] = Field(default_factory=list)
    boolean: list[CandidateInput] = Field(default_factory=list)
    enum: list[CandidateInput] = Field(default_factory=list)
    lora_name: list[CandidateInput] = Field(default_factory=list)
    checkpoint_name: list[CandidateInput] = Field(default_factory=list)


InferredMode = Literal["i2i", "t2i"]


class SlotMapOut(StrictModel):
    session_id: str
    workflow_id: str
    slot_map: SlotMapV2
    candidates: CandidateBuckets
    inferred_mode: InferredMode
    """Inferred at GET time from the saved slot list. ``i2i`` if any
    wired ``binding=user_image`` slot is present, else ``t2i``. The
    family-guide append logic (``prompt_i2i`` / ``prompt_t2i``)
    consumes this in Phase 3 prep."""


class SlotMapUpdate(StrictModel):
    """Body of PUT /api/comfy/sessions/{id}/slot_map. Send the full
    desired list — the slot map is replaced atomically."""
    slots: list[SlotDefinition]


# --- Comfy agents (per-session, user-programmable) ---------------------------
#
# A comfy session owns a list of agents. Each agent has its own prompt,
# model, source scope, LoRA toggle, and a list of typed output slots that
# bind to the workflow's `binding=llm` slots. See
# docs/comfy-agents-redesign.md.


SourceScope = Literal["all", "selected", "none"]


SlotOrigin_ = Literal["preset", "custom", "auto"]
"""How the agent output slot was authored.

- ``preset``: built-in pre-baked slot (currently ``positive`` /
  ``negative``). Kind, label, and description are pre-filled.
- ``custom``: user picks ``kind`` + writes ``description``.
- ``auto``: kind + description are snapshotted from the workflow slot
  and its catalog node info at bind time. Pre-bind, ``kind`` and
  ``description`` may be unset (the slot is a placeholder waiting to
  be wired)."""


PresetOutputName = Literal["positive", "negative"]


# Kind for each preset. Presets only cover the two pre-baked text slots
# in v1 — LoRA output stays a session-level side-channel via
# ``loras_enabled``, not a slot.
PRESET_KIND: dict[PresetOutputName, SlotKind] = {
    "positive": "multiline_text",
    "negative": "multiline_text",
}


class AgentSlotBinding(StrictModel):
    """A wiring from an agent's output slot into a workflow slot
    (matched by label)."""
    workflow_slot_label: str = Field(min_length=1, max_length=64)


class AgentOutputSlot(StrictModel):
    """One output slot owned by an agent.

    Validation rules (enforced in the service layer, not by Pydantic):

    - ``preset`` slots must use the kind defined by :data:`PRESET_KIND`
      and may not set ``preset`` to anything outside that map.
    - ``custom`` slots must set ``kind``; ``preset`` must be ``None``.
    - ``auto`` slots may have ``kind`` / ``description`` unset pre-bind;
      once ``bound_to`` is set, kind + description are snapshotted from
      the workflow slot + catalog node info.
    - ``bound_to`` must reference an existing workflow slot whose
      ``binding`` is ``llm`` and whose ``kind`` matches this slot's
      kind. No two agents in the same session may target the same
      workflow slot label.
    - ``last_value`` is the agent's most recent successful output for
      this slot, kind-typed. Persisted across session reads."""

    id: str = Field(min_length=1, max_length=32)
    origin: SlotOrigin_
    preset: PresetOutputName | None = None
    kind: SlotKind | None = None
    label: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=2000)
    last_value: Any | None = None
    bound_to: AgentSlotBinding | None = None


class AgentOut(StrictModel):
    """One agent on a comfy session."""
    id: str
    session_id: str
    position: int
    name: str
    prompt: str
    model_name: str | None
    model_params: dict[str, Any] | None
    source_scope: SourceScope
    source_ids: list[str] | None
    """Set when ``source_scope == 'selected'``. ``null`` for ``all`` /
    ``none``."""
    loras_enabled: bool
    output_slots: list[AgentOutputSlot]
    last_run_at: int | None
    created_at: int
    updated_at: int


class AgentList(StrictModel):
    agents: list[AgentOut]


class AgentCreate(StrictModel):
    """Body of POST /api/comfy/sessions/{id}/agents.

    Only ``name`` is required. Everything else has a sensible default —
    output slots start empty, prompt is empty, source scope is ``all``,
    LoRAs off. The user fills the rest via PATCH."""
    name: str = Field(min_length=1, max_length=120)
    prompt: str = Field(default="", max_length=20000)
    model_name: str | None = None
    model_params: dict[str, Any] | None = None
    source_scope: SourceScope = "all"
    source_ids: list[str] | None = None
    loras_enabled: bool = False
    output_slots: list[AgentOutputSlot] = Field(default_factory=list)


class AgentUpdate(StrictModel):
    """Partial update. Fields not present in ``model_fields_set`` keep
    their existing value; explicit ``None`` clears the value (where
    nullable). Position updates are accepted as-is — the service does
    not renumber siblings, the client is expected to send a coherent
    new position."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    prompt: str | None = Field(default=None, max_length=20000)
    model_name: str | None = None
    model_params: dict[str, Any] | None = None
    source_scope: SourceScope | None = None
    source_ids: list[str] | None = None
    loras_enabled: bool | None = None
    output_slots: list[AgentOutputSlot] | None = None
    position: int | None = None


class AgentSeedDefaultOut(StrictModel):
    """Returned by POST /api/comfy/sessions/{id}/agents/seed_default.

    The seed action is opt-in: it creates exactly one agent with one
    output slot per ``binding=llm`` workflow slot, all pre-bound. It is
    rejected (409) when the session already has at least one agent."""
    agent: AgentOut


class AgentRunRequest(StrictModel):
    """Optional body for ``POST .../agents/{id}/run``.

    ``source_image_overrides`` resolves each ``source``-kind input
    slot's frontend-only ``source_slot_id`` to an actual
    ``session_source_images.id`` so the runner can read the file off
    disk. Maps input-slot id (the id stored in
    ``model_params.__input_slots[].id``) to the session image id.
    Missing keys, ``null`` values, and unknown image ids are tolerated
    — the runner reports those as soft warnings inside the system
    prompt rather than aborting the run."""

    source_image_overrides: dict[str, str | None] | None = None
