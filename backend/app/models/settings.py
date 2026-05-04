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


class ActionDefaultsOut(StrictModel):
    """Per-action default sampling bundles (app-wide)."""
    analyze: dict
    chat: dict
    summarize: dict
    generate: dict


class ActionDefaultsPatch(StrictModel):
    """Partial update — only fields the client sends are persisted.

    Each value is a sampling bundle dict (e.g. {"temperature": 0.7,
    "top_p": 0.9}). Pass an empty object to clear all overrides for an
    action.
    """
    analyze: dict | None = None
    chat: dict | None = None
    summarize: dict | None = None
    generate: dict | None = None
