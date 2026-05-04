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
    """Phase 2 slot mapping. None means no map saved yet — the editor
    opens with everything unassigned. See ``SlotMapOut`` for shape."""


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
    nodes: list["NodeListItemOut"]
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


# --- Phase 2: workflow slot mapping ---------------------------------------


SlotName = Literal["positive_prompt", "negative_prompt", "main_image"]
"""Logical injection slots sd-chisel knows how to fill. Two text
slots and one image slot — Phase 2 scope. LoRA-related slots will
join here once Q3 is decided."""


SLOT_NAMES: tuple[SlotName, ...] = (
    "positive_prompt",
    "negative_prompt",
    "main_image",
)


SlotKind = Literal["text", "image"]


SLOT_KIND: dict[SlotName, SlotKind] = {
    "positive_prompt": "text",
    "negative_prompt": "text",
    "main_image": "image",
}


class SlotAssignment(StrictModel):
    node_id: str = Field(min_length=1)
    input_name: str = Field(min_length=1)


class CandidateInput(StrictModel):
    """One eligible (node_id, input_name) pair the user can pick to
    fill a logical slot. Eligibility is computed from the graph and
    the catalog's raw INPUT_TYPES schema — see
    ``comfy_slot_map_service.compute_candidates``."""
    node_id: str
    input_name: str
    node_class_type: str
    node_display_name: str | None
    """Human-readable name from the catalog (``NODE_DISPLAY_NAME_MAPPINGS``
    in ComfyUI), e.g. "CLIP Text Encode (Prompt)". Falls back to
    ``class_type`` when the node hasn't been imported yet."""
    node_title: str | None
    """Per-node free-form title the user set in the ComfyUI canvas
    (``graph[node_id]._meta.title``). When two nodes share a class
    this is the only thing that distinguishes them — the editor
    leads with it when present."""
    node_in_catalog: bool
    """False when the workflow references a node class that hasn't
    been imported yet. The candidate still works for image slots
    (LoadImage is detected by name), but the editor flags it so the
    user can finish import first if they want catalog-driven hints."""
    current_value: Any
    """The literal value currently sitting at this input — shown as
    a preview so the user can recognise which encoder is which."""
    multiline: bool = False


class CandidateBucket(StrictModel):
    text: list[CandidateInput]
    image: list[CandidateInput]


class SlotMapOut(StrictModel):
    session_id: str
    workflow_id: str
    slot_map: dict[SlotName, SlotAssignment | None]
    """Saved assignments. Every slot in ``SLOT_NAMES`` is present;
    unassigned slots hold ``null``."""
    candidates: CandidateBucket
    """All eligible inputs grouped by kind. The same candidate may
    appear in multiple slot dropdowns (e.g. a STRING input can fill
    either positive_prompt or negative_prompt)."""


class SlotMapUpdate(StrictModel):
    """Body of PUT /api/comfy/sessions/{id}/slot_map. Send the full
    desired state — omitted slots are treated as unassigned."""
    slot_map: dict[SlotName, SlotAssignment | None]
