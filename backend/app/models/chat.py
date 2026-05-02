from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatRequest(StrictModel):
    content: str = Field(min_length=1, max_length=8000)
    # When set, this turn is an *edit* of an existing user message rather
    # than a new turn. The handler replaces that message's content,
    # truncates every later message, and streams a fresh assistant reply
    # — all inside the same request. No new user row is appended, so the
    # history never ends up with two user turns in a row.
    replace_message_id: int | None = None

    @field_validator("content")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("content must not be blank")
        return stripped


class MessageOut(StrictModel):
    id: int
    session_id: str
    role: Literal["user", "assistant", "system"]
    content: str
    created_at: int


class MessagesResponse(StrictModel):
    messages: list[MessageOut]
