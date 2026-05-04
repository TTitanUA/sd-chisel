"""Pydantic models for ComfyUI integration endpoints (Phase 1)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


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
