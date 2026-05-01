from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class TaskOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    title: str
    target: dict[str, Any]
    status: str
    progress: float | None
    message: str | None
    error: str | None
    created_at: float
    started_at: float | None
    finished_at: float | None


class TaskListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tasks: list[TaskOut]
