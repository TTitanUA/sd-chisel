from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SessionType = Literal["i2i", "t2i", "comfy", "comfy_mock"]


ComfyInputCleanup = Literal["keep", "delete"]
"""Per-session policy for files sd-chisel uploaded into ComfyUI's input
dir after a generation finishes (Phase 3). ``keep`` (default) leaves
them; ``delete`` removes them via direct filesystem access. Phase 3
soft-degrades to ``keep`` when the input dir isn't reachable."""
"""``comfy_mock`` is a UI-exploration session type that reuses comfy
workflow / slot-map / agent machinery but emulates LLM calls and
workflow generation on the frontend. See
``docs/comfy-agents-ui-mock-plan.md``."""


COMFY_LIKE_TYPES: frozenset[SessionType] = frozenset({"comfy", "comfy_mock"})
"""Session types that use the comfy workflow + slot map + agents
contracts. The agent + slot-map + readiness endpoints accept any
member; only the generation cycle differs (real LMStudio/ComfyUI for
``comfy``, emulated client-side for ``comfy_mock``)."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PinnedLoraIn(StrictModel):
    lora_name: str = Field(min_length=1)
    weight_override: float | None = Field(default=None, ge=-2.0, le=2.0)


class PinnedLoraOut(StrictModel):
    lora_name: str
    weight_override: float | None


class ProjectOut(StrictModel):
    id: str
    name: str
    session_count: int
    hidden: bool = False
    created_at: int
    updated_at: int


class ProjectCreate(StrictModel):
    name: str = Field(min_length=1, max_length=160)


class ProjectUpdate(StrictModel):
    name: str = Field(min_length=1, max_length=160)


class SourceImageOut(StrictModel):
    id: str
    session_id: str
    path: str
    url: str
    original_filename: str
    image_number: int
    is_main: bool
    analysis: str | None
    analysis_prompt: str | None
    created_at: int
    updated_at: int


class SessionOut(StrictModel):
    id: str
    project_id: str
    name: str | None
    session_type: SessionType
    model_name: str | None
    use_negative: bool
    pinned_loras: list[PinnedLoraOut]
    source_images: list[SourceImageOut]
    vl_model_name: str | None
    prompt_model_name: str | None
    analyze_settings: dict | None = None
    chat_settings: dict | None = None
    summarize_settings: dict | None = None
    generate_settings: dict | None = None
    comfy_workflow_id: str | None = None
    comfy_input_cleanup: ComfyInputCleanup = "keep"
    comfy_restart_after_run: bool = False
    hidden: bool = False
    created_at: int
    updated_at: int


class AnalyzeSourceRequest(StrictModel):
    refining_prompt: str | None = Field(default=None, max_length=2000)


class HiddenPatch(StrictModel):
    hidden: bool


class SessionCreate(StrictModel):
    session_type: SessionType
    name: str | None = Field(default=None, max_length=160)
    model_name: str | None = None
    use_negative: bool = True
    # Required when session_type == 'comfy'; must be omitted otherwise.
    # API enforces both directions.
    comfy_workflow_id: str | None = None


class SessionUpdate(StrictModel):
    name: str | None = Field(default=None, max_length=160)
    model_name: str | None = None
    use_negative: bool
    pinned_loras: list[PinnedLoraIn] = Field(default_factory=list)
    vl_model_name: str | None = None
    prompt_model_name: str | None = None
    # Action sampling bundles. Absent fields = "leave the column alone";
    # ``null`` = "clear all per-session overrides for this action and
    # inherit the full app default"; ``{}`` is treated the same as null.
    analyze_settings: dict | None = None
    chat_settings: dict | None = None
    summarize_settings: dict | None = None
    generate_settings: dict | None = None
    comfy_input_cleanup: ComfyInputCleanup | None = None
    """Per-session policy for ComfyUI input cleanup. ``None`` leaves the
    column alone; pass ``"keep"`` / ``"delete"`` to update."""
    comfy_restart_after_run: bool | None = None
    """Per-session opt-in: bounce the ComfyUI process after every Single
    Run via POST /manager/reboot (requires ComfyUI-Manager). ``None``
    leaves the column alone; ``True`` / ``False`` updates it."""
