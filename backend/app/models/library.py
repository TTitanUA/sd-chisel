from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FamilyOut(StrictModel):
    id: str
    display_name: str
    prompt_guide: str
    created_at: int
    updated_at: int


class FamilyCreate(StrictModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=160)
    prompt_guide: str = Field(min_length=1)


class FamilyUpdate(StrictModel):
    display_name: str = Field(min_length=1, max_length=160)
    prompt_guide: str = Field(min_length=1)


class ModelOut(StrictModel):
    name: str
    display_name: str
    family_id: str
    description: str | None
    author: str | None
    version: str | None
    source_url: str | None
    created_at: int
    updated_at: int


class ModelCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=160)
    family_id: str = Field(min_length=1)
    description: str | None = None
    author: str | None = None
    version: str | None = None
    source_url: HttpUrl | None = None


class ModelUpdate(StrictModel):
    display_name: str = Field(min_length=1, max_length=160)
    family_id: str = Field(min_length=1)
    description: str | None = None
    author: str | None = None
    version: str | None = None
    source_url: HttpUrl | None = None


class LoraOut(StrictModel):
    name: str
    display_name: str
    description: str
    tags: list[str]
    trigger_words: list[str]
    family_id: str
    recommended_weight: float | None
    author: str | None
    version: str | None
    source_url: str | None
    created_at: int
    updated_at: int
    is_indexed: bool = False


class LoraCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    trigger_words: list[str] = Field(default_factory=list)
    family_id: str = Field(min_length=1)
    recommended_weight: float | None = Field(default=None, ge=-2.0, le=2.0)
    author: str | None = None
    version: str | None = None
    source_url: HttpUrl | None = None


class LoraUpdate(StrictModel):
    display_name: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    trigger_words: list[str] = Field(default_factory=list)
    family_id: str = Field(min_length=1)
    recommended_weight: float | None = Field(default=None, ge=-2.0, le=2.0)
    author: str | None = None
    version: str | None = None
    source_url: HttpUrl | None = None


class AssistMessage(StrictModel):
    role: str = Field(pattern=r"^(user|assistant)$")
    content: str = Field(min_length=1)


class AssistRequest(StrictModel):
    model: str = Field(min_length=1)
    messages: list[AssistMessage] = Field(min_length=1)
