"""ComfyUI integration endpoints (Phase 1).

This router currently holds the workflow CRUD surface. Subsequent
phases extend it with the readiness gate, the per-node import wizard,
and the catalog browse endpoints.
"""
from __future__ import annotations

import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse

from app.api.deps import get_conn
from app.models.comfy import (
    WorkflowConflict,
    WorkflowList,
    WorkflowOut,
    WorkflowSummary,
    WorkflowUpload,
)
from app.storage import comfy_workflow_repo as repo

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

router = APIRouter(tags=["comfy"])


def _to_summary(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "graph_hash": row["graph_hash"],
        "created_at": row["created_at"],
    }


def _to_out(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "graph": row["graph"],
        "graph_hash": row["graph_hash"],
        "created_at": row["created_at"],
    }


@router.post(
    "/api/comfy/workflows",
    response_model=WorkflowOut,
    responses={409: {"model": WorkflowConflict}},
)
def create_workflow(
    body: WorkflowUpload,
    conn: Conn,
    on_conflict: Annotated[
        Literal["error", "replace", "rename"],
        Query(description="error → 409 on duplicate (default), replace → overwrite, rename → save as new with given name"),
    ] = "error",
) -> JSONResponse | dict:
    digest = repo.hash_graph(body.graph)
    existing = repo.find_by_hash(conn, digest)

    if existing is not None and on_conflict == "error":
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=WorkflowConflict(
                existing=WorkflowSummary(**_to_summary(existing)),
            ).model_dump(),
        )

    if existing is not None and on_conflict == "replace":
        replaced = repo.replace_workflow(
            conn, workflow_id=existing["id"], name=body.name, graph=body.graph,
        )
        assert replaced is not None
        return _to_out(replaced)

    # on_conflict == "rename" or no collision → fresh insert.
    inserted = repo.insert_workflow(conn, name=body.name, graph=body.graph)
    return _to_out(inserted)


@router.get("/api/comfy/workflows", response_model=WorkflowList)
def list_workflows(conn: Conn) -> dict:
    return {"workflows": [_to_summary(r) for r in repo.list_workflows(conn)]}


@router.get("/api/comfy/workflows/{workflow_id}", response_model=WorkflowOut)
def get_workflow(workflow_id: str, conn: Conn) -> dict:
    row = repo.get_workflow(conn, workflow_id)
    if row is None:
        raise HTTPException(status_code=404, detail="workflow not found")
    return _to_out(row)


@router.delete("/api/comfy/workflows/{workflow_id}")
def delete_workflow(workflow_id: str, conn: Conn) -> Response:
    if repo.get_workflow(conn, workflow_id) is None:
        raise HTTPException(status_code=404, detail="workflow not found")
    try:
        repo.delete_workflow(conn, workflow_id)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="workflow is in use by one or more sessions",
        ) from exc
    return Response(status_code=204)
