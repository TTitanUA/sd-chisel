from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


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


class SessionOut(StrictModel):
    id: str
    project_id: str
    name: str | None
    model_name: str | None
    use_negative: bool
    pinned_loras: list[PinnedLoraOut]
    source_image_path: str | None
    source_image_url: str | None
    vl_summary: str | None
    vl_model_name: str | None
    prompt_model_name: str | None
    hidden: bool = False
    created_at: int
    updated_at: int


class HiddenPatch(StrictModel):
    hidden: bool


class SessionCreate(StrictModel):
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
