from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LmStudioConfig(StrictModel):
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=500)


class LmStudioConfigOut(StrictModel):
    base_url: str | None
    api_key: str | None
    configured: bool
    updated_at: int


class LmModelOut(StrictModel):
    name: str
    vision: bool
    tool_use: bool
    reasoning: bool
    enabled: bool
    favorite: bool
    hidden: bool = False
    last_seen: int


class LmModelsOut(StrictModel):
    models: list[LmModelOut]


class LmModelPatch(StrictModel):
    vision: bool | None = None
    tool_use: bool | None = None
    reasoning: bool | None = None
    enabled: bool | None = None
    favorite: bool | None = None
    hidden: bool | None = None


class PrivacyOut(StrictModel):
    show_hidden: bool
    updated_at: int


class PrivacyPatch(StrictModel):
    show_hidden: bool
