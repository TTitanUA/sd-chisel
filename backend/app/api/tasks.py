"""HTTP layer for the background task registry.

`GET /api/tasks` lists tasks (active by default — pass `?active_only=false`
for history). `GET /api/tasks/stream` is an SSE endpoint that pushes every
status transition. The frontend uses the stream to keep its task store
fresh; the list endpoint is for the initial paint.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict

from fastapi import APIRouter
from starlette.responses import StreamingResponse

from app.models.tasks import TaskListResponse, TaskOut
from app.services import task_runner

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _to_out(task: task_runner.Task) -> TaskOut:
    return TaskOut(**asdict(task))


@router.get("", response_model=TaskListResponse)
def list_tasks(active_only: bool = True) -> TaskListResponse:
    reg = task_runner.get()
    return TaskListResponse(
        tasks=[_to_out(t) for t in reg.list(active_only=active_only)],
    )


@router.get("/stream")
async def stream_tasks() -> StreamingResponse:
    reg = task_runner.get()
    sub = reg.subscribe()

    async def gen():
        # Initial snapshot so a fresh subscriber doesn't miss in-flight tasks.
        snapshot = [_to_out(t).model_dump() for t in reg.list(active_only=False)]
        yield _sse({"type": "snapshot", "tasks": snapshot})
        try:
            while True:
                try:
                    event = await asyncio.wait_for(sub.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # Heartbeat keeps proxies from closing the connection.
                    yield b": ping\n\n"
                    continue
                yield _sse({
                    "type": event.type,
                    "task": _to_out(event.task).model_dump(),
                })
        finally:
            reg.unsubscribe(sub)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _sse(payload: dict) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()
