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
