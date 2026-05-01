from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SessionType = Literal["i2i", "t2i"]


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


class SessionUpdate(StrictModel):
    name: str | None = Field(default=None, max_length=160)
    model_name: str | None = None
    use_negative: bool
    pinned_loras: list[PinnedLoraIn] = Field(default_factory=list)
    vl_model_name: str | None = None
    prompt_model_name: str | None = None
