from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


Role = Literal["vl", "prompt", "both"]


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
    role: Role
    enabled: bool
    last_seen: int


class LmModelsOut(StrictModel):
    models: list[LmModelOut]


class LmModelPatch(StrictModel):
    role: Role | None = None
    enabled: bool | None = None
