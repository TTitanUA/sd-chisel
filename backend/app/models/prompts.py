"""Schemas for the two-step generate-prompt flow.

Naming notes:
- ``Intent`` / ``IntentList`` are what the *intent rewriting* LLM emits.
- ``LoraSpec`` is the per-LoRA item the *composition* LLM emits inside
  ``GeneratedPrompt.loras``. We deliberately keep this generous (`extra="ignore"`)
  to absorb harmless extra fields some models add — the persisted column is the
  raw model output, so we don't lose information either way.
- ``RetrievedLora`` / ``RetrievedIntent`` are pure server-side debug payloads.
- ``PromptOut`` / ``GeneratePromptResponse`` / ``PromptsResponse`` are the API
  envelopes.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Intent(BaseModel):
    model_config = ConfigDict(extra="ignore")
    kind: str = Field(min_length=1, max_length=64)
    query: str = Field(min_length=1, max_length=400)


class IntentList(BaseModel):
    model_config = ConfigDict(extra="ignore")
    intents: list[Intent] = Field(min_length=1, max_length=8)


class LoraSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = Field(min_length=1)
    weight: float = Field(ge=-2.0, le=2.0)


class GeneratedPrompt(BaseModel):
    model_config = ConfigDict(extra="ignore")
    positive: str = Field(min_length=1)
    negative: str | None = None
    loras: list[LoraSpec] = Field(default_factory=list)


class RetrievedLora(BaseModel):
    name: str
    distance: float


class RetrievedIntent(BaseModel):
    intent_index: int
    intent_query: str
    results: list[RetrievedLora]


class PromptOut(BaseModel):
    id: int
    session_id: str
    prompt: GeneratedPrompt
    intents: list[Intent] | None
    retrieved: list[RetrievedIntent] | None
    created_at: int


class GeneratePromptResponse(BaseModel):
    prompt_id: int
    prompt: GeneratedPrompt
    intents: list[Intent]
    retrieved: list[RetrievedIntent]
    created_at: int


class PromptsResponse(BaseModel):
    prompts: list[PromptOut]
