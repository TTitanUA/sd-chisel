from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FamilyOut(StrictModel):
    id: str
    display_name: str
    prompt_guide: str
    prompt_i2i: str
    prompt_t2i: str
    created_at: int
    updated_at: int


class FamilyCreate(StrictModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=160)
    prompt_guide: str = Field(min_length=1)
    prompt_i2i: str = ""
    prompt_t2i: str = ""


class FamilyUpdate(StrictModel):
    display_name: str = Field(min_length=1, max_length=160)
    prompt_guide: str = Field(min_length=1)
    prompt_i2i: str = ""
    prompt_t2i: str = ""


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


class AssistFieldsSnapshot(StrictModel):
    prompt_guide: str = ""
    prompt_i2i: str = ""
    prompt_t2i: str = ""


class AssistRequest(StrictModel):
    model: str = Field(min_length=1)
    message: str = Field(min_length=1)
    previous_response_id: str | None = None
    current_state: AssistFieldsSnapshot = Field(default_factory=AssistFieldsSnapshot)


class FamilyOption(StrictModel):
    id: str
    display_name: str


class LoraAssistFieldsSnapshot(StrictModel):
    name: str = ""
    display_name: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    trigger_words: list[str] = Field(default_factory=list)
    family_id: str = ""
    recommended_weight: float | None = None
    author: str = ""
    version: str = ""
    source_url: str = ""
    available_families: list[FamilyOption] = Field(default_factory=list)
    is_edit_mode: bool = False


class CivitaiImportResult(StrictModel):
    name: str = ""
    display_name: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    trigger_words: list[str] = Field(default_factory=list)
    recommended_weight: float | None = None
    author: str = ""
    version: str = ""
    source_url: str = ""
    base_model: str = ""
    model_type: str = ""
    air: str = ""


class LoraAssistRequest(StrictModel):
    model: str = Field(min_length=1)
    message: str = Field(min_length=1)
    previous_response_id: str | None = None
    current_state: LoraAssistFieldsSnapshot = Field(
        default_factory=LoraAssistFieldsSnapshot,
    )


class RenameRequest(StrictModel):
    new_name: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[a-zA-Z0-9_.-]+$",
    )
