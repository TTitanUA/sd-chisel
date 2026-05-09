"""REST + SSE endpoints for Single Run jobs.

The orchestrator (`comfy_orchestrator`) does the heavy lifting; this
module is the thin HTTP/SSE wrapper.

Endpoints:

- ``POST /api/comfy/sessions/{session_id}/single_run`` — kick off a
  Single Run. Validates synchronously, snapshots into a job row, then
  spawns the pipeline asyncio task and returns the job id + the URL
  the frontend opens for live progress.
- ``GET  /api/comfy/jobs/{job_id}`` — full row + outputs.
- ``GET  /api/comfy/jobs?session_id=…`` — list per session.
- ``GET  /api/comfy/jobs/{job_id}/stream`` — SSE: replay every event
  the channel has buffered, then stream live until ``stage=done``.
- ``DELETE /api/comfy/jobs/{job_id}`` — drop the row + on-disk files.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from app.api.deps import get_conn
from app.config import resolve_data_root
from app.services import comfy_orchestrator, comfy_run_streams
from app.storage import comfy_jobs_repo

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

router = APIRouter(tags=["comfy_jobs"])


# --- request / response models -----------------------------------------


class SingleRunBody(BaseModel):
    payload_overrides: dict[str, Any] | None = None
    image_bindings: dict[str, str | None] | None = Field(
        default=None,
        description=(
            "Per-slot image picks. Keys are workflow slot labels for "
            "binding=user_image slots; values are session_source_images.id "
            "or null. The frontend resolves its localStorage source-slot "
            "table client-side and sends the resolved map."
        ),
    )
    rerun_agents: bool = True


class SingleRunOut(BaseModel):
    job_id: str
    generation_id: str
    stream_url: str


class JobOutputOut(BaseModel):
    id: str
    slot_label: str | None
    node_id: str
    output_index: int
    path: str
    url: str
    is_primary: bool
    created_at: int


class JobOut(BaseModel):
    id: str
    session_id: str
    workflow_id: str
    prompt_id: str | None
    generation_id: str
    payload: dict[str, Any]
    slot_map_snapshot: list[dict[str, Any]]
    agents_snapshot: list[dict[str, Any]]
    status: str
    error_message: str | None
    started_at: int
    finished_at: int | None
    outputs: list[JobOutputOut]


class JobsListOut(BaseModel):
    jobs: list[JobOut]


# --- helpers ------------------------------------------------------------


def _output_to_out(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "slot_label": row["slot_label"],
        "node_id": row["node_id"],
        "output_index": row["output_index"],
        "path": row["path"],
        "url": f"/media/{row['path']}",
        "is_primary": bool(row["is_primary"]),
        "created_at": row["created_at"],
    }


def _job_to_out(conn: sqlite3.Connection, row: dict[str, Any]) -> dict[str, Any]:
    outputs = comfy_jobs_repo.list_outputs(conn, row["id"])
    return {
        **row,
        "outputs": [_output_to_out(o) for o in outputs],
    }


# --- endpoints ----------------------------------------------------------


@router.post(
    "/api/comfy/sessions/{session_id}/single_run",
    response_model=SingleRunOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_single_run(
    session_id: str,
    body: SingleRunBody,
    conn: Conn,
) -> dict[str, Any]:
    try:
        result = await comfy_orchestrator.start_single_run(
            conn,
            session_id=session_id,
            payload_overrides=body.payload_overrides or {},
            image_bindings=body.image_bindings or {},
            rerun_agents=body.rerun_agents,
        )
    except comfy_orchestrator.ValidationError as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    return {
        **result,
        "stream_url": f"/api/comfy/jobs/{result['job_id']}/stream",
    }


@router.get("/api/comfy/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, conn: Conn) -> dict[str, Any]:
    row = comfy_jobs_repo.get_job(conn, job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _job_to_out(conn, row)


@router.get("/api/comfy/jobs", response_model=JobsListOut)
def list_jobs(
    conn: Conn,
    session_id: Annotated[str, Query(min_length=1)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    rows = comfy_jobs_repo.list_jobs_for_session(
        conn, session_id, limit=limit, offset=offset,
    )
    return {"jobs": [_job_to_out(conn, r) for r in rows]}


@router.post(
    "/api/comfy/jobs/{job_id}/cancel",
    status_code=status.HTTP_202_ACCEPTED,
)
async def cancel_job(job_id: str, conn: Conn) -> dict[str, Any]:
    """Best-effort cancellation. Sets the run channel's cancel flag —
    the orchestrator picks it up at its next stage boundary and the
    interrupt watcher posts /api/interrupt to ComfyUI if the run is
    in the execute stage. Returns 202 immediately; the actual
    transition to `cancelled` lands as an SSE event and the row's
    `status` updates a moment later.
    """
    row = comfy_jobs_repo.get_job(conn, job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="job not found")
    if row["status"] not in ("queued", "running"):
        # Idempotent — cancelling a finished job is a no-op.
        return {"job_id": job_id, "status": row["status"]}
    channel = await comfy_run_streams.get_channel(job_id)
    if channel is None:
        # Channel was reaped (run finished long ago, status row not
        # yet updated). Just flip the row.
        comfy_jobs_repo.set_status(
            conn, job_id, "cancelled", error_message="cancelled by user",
        )
        return {"job_id": job_id, "status": "cancelled"}
    channel.cancel_event.set()
    return {"job_id": job_id, "status": "cancelling"}


@router.delete(
    "/api/comfy/jobs/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_job(job_id: str, conn: Conn) -> Response:
    row = comfy_jobs_repo.get_job(conn, job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="job not found")
    # Unlink files first; the FK CASCADE on comfy_job_outputs takes
    # care of the rows once the job row drops.
    outputs = comfy_jobs_repo.list_outputs(conn, job_id)
    data_root = resolve_data_root()
    for o in outputs:
        try:
            (data_root / o["path"]).unlink(missing_ok=True)
        except OSError:  # noqa: PERF203 — leftovers are tolerable
            pass
    # The whole `output/<generation_id>/` directory is created
    # per-run; if it's empty after unlinking, drop it too.
    gen_dir = data_root / "images" / row["session_id"] / "output" / row["generation_id"]
    if gen_dir.exists() and not any(gen_dir.iterdir()):
        try:
            shutil.rmtree(gen_dir)
        except OSError:
            pass
    comfy_jobs_repo.delete_job(conn, job_id)
    return Response(status_code=204)


@router.get("/api/comfy/jobs/{job_id}/stream")
async def stream_job(job_id: str) -> StreamingResponse:
    """SSE — replay every channel event so far, then stream live until
    ``stage=done`` arrives.

    No connection is held in the DB layer; the orchestrator publishes
    to an in-memory ``RunChannel`` keyed by ``job_id``. Late
    subscribers (refresh after the run finished) receive the full
    event log within the channel's grace window (5 minutes).
    """
    channel = await comfy_run_streams.get_channel(job_id)
    if channel is None:
        # No live channel — either the run finished long ago and the
        # channel was reaped, or the job_id is wrong. Either way the
        # frontend should fall back to GET /jobs/{id} to read final
        # state from the DB.
        raise HTTPException(status_code=404, detail="run channel not available")

    async def gen():
        try:
            async for event in channel.subscribe():
                yield f"data: {json.dumps(event)}\n\n"
        except asyncio.CancelledError:
            # Client disconnected mid-stream — exit cleanly.
            raise

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
