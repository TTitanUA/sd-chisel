"""ComfyUI integration endpoints (Phase 1).

This router currently holds the workflow CRUD surface. Subsequent
phases extend it with the readiness gate, the per-node import wizard,
and the catalog browse endpoints.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from starlette.responses import StreamingResponse

from app.api.deps import get_conn
from app.models.comfy import (
    NodeList,
    NodeOut,
    NodeUpdate,
    PackDetailOut,
    PackList,
    ReadinessOut,
    WorkflowConflict,
    WorkflowList,
    WorkflowOut,
    WorkflowSummary,
    WorkflowUpload,
)
from app.services import action_settings, comfy_client, comfy_import_service, comfy_readiness
from app.storage import comfy_catalog_repo, comfy_workflow_repo as repo
from app.storage import db as db_mod, session_repo, settings_repo

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


@router.get(
    "/api/comfy/sessions/{session_id}/readiness",
    response_model=ReadinessOut,
)
def get_session_readiness(session_id: str, conn: Conn) -> dict:
    session = session_repo.get_session(conn, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    if session.get("session_type") != "comfy":
        raise HTTPException(
            status_code=409,
            detail="session is not a comfy session",
        )
    workflow_id = session.get("comfy_workflow_id")
    if not workflow_id:
        raise HTTPException(
            status_code=409,
            detail="comfy session is not bound to a workflow",
        )
    workflow = repo.get_workflow(conn, workflow_id)
    if workflow is None:
        raise HTTPException(
            status_code=409,
            detail=f"bound workflow not found: {workflow_id}",
        )

    settings = settings_repo.get_comfyui(conn)
    comfyui_url = settings.get("comfyui_url")
    comfyui_path = settings.get("comfyui_path")
    if not comfyui_url:
        return {
            "session_id": session_id,
            "workflow_id": workflow_id,
            "ready": False,
            "cards": [],
            "error": "ComfyUI URL is not configured (Settings → ComfyUI)",
        }

    endpoint = {
        "server_root": comfyui_url,
        "api_key": settings.get("comfyui_api_key"),
    }
    try:
        object_info = comfy_client.object_info(endpoint=endpoint)
    except comfy_client.ComfyError as exc:
        return {
            "session_id": session_id,
            "workflow_id": workflow_id,
            "ready": False,
            "cards": [],
            "error": str(exc),
        }

    path_obj = Path(comfyui_path) if comfyui_path else None
    all_ready, cards = comfy_readiness.compute_readiness(
        conn=conn,
        graph=workflow["graph"],
        object_info=object_info,
        comfyui_path=path_obj,
    )
    return {
        "session_id": session_id,
        "workflow_id": workflow_id,
        "ready": all_ready,
        "cards": [asdict(c) for c in cards],
        "error": None,
    }


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


# --- catalog (Library → Comfy Nodes) ----------------------------------


def _node_summary(row: dict) -> dict:
    return {
        "class_type": row["class_type"],
        "pack_name": row["pack_name"],
        "display_name": row["display_name"],
        "category": row["category"],
        "description_md": row["description_md"],
        "has_override": row["has_override"],
        "requires_semantic_config": row["requires_semantic_config"],
        "imported_at": row["imported_at"],
    }


def _pack_summary(row: dict) -> dict:
    return {
        "name": row["name"],
        "display_name": row["display_name"],
        "description": row["description"],
        "version": row["version"],
        "repo_url": row["repo_url"],
        "publisher_id": row["publisher_id"],
        "dir_path": row["dir_path"],
        "node_count": row["node_count"],
        "imported_at": row["imported_at"],
    }


@router.get("/api/comfy/packs", response_model=PackList)
def list_packs(conn: Conn) -> dict:
    return {"packs": [_pack_summary(p) for p in comfy_catalog_repo.list_packs(conn)]}


@router.get("/api/comfy/packs/{name}", response_model=PackDetailOut)
def get_pack(name: str, conn: Conn) -> dict:
    pack = comfy_catalog_repo.get_pack(conn, name)
    if pack is None:
        raise HTTPException(status_code=404, detail="pack not found")
    nodes = comfy_catalog_repo.list_nodes(conn, pack=name)
    return {**pack, "nodes": [_node_summary(n) for n in nodes]}


@router.get("/api/comfy/nodes", response_model=NodeList)
def list_nodes(
    conn: Conn,
    q: Annotated[str | None, Query(description="Substring match on class_type, display_name, description")] = None,
    pack: Annotated[str | None, Query(description="Filter by pack name")] = None,
    has_description: Annotated[
        bool | None,
        Query(description="Only nodes with (true) or without (false) a description"),
    ] = None,
) -> dict:
    rows = comfy_catalog_repo.list_nodes(
        conn, q=q, pack=pack, has_description=has_description,
    )
    return {"nodes": [_node_summary(r) for r in rows]}


@router.get("/api/comfy/nodes/{class_type}", response_model=NodeOut)
def get_node(class_type: str, conn: Conn) -> dict:
    row = comfy_catalog_repo.get_node(conn, class_type)
    if row is None:
        raise HTTPException(status_code=404, detail="node not found")
    return row


def _sse(payload: dict) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


def _conn_file(conn: sqlite3.Connection) -> Path:
    """Path of the ``main`` SQLite file backing ``conn``. The SSE
    generator opens its own short-lived connection because the Depends-
    scoped one has already been closed by the time Starlette starts
    iterating the body."""
    for row in conn.execute("PRAGMA database_list").fetchall():
        if row["name"] == "main":
            return Path(row["file"])
    raise RuntimeError("connection has no 'main' database attached")


@router.post("/api/comfy/nodes/{class_type}/import")
async def import_node(class_type: str, conn: Conn) -> StreamingResponse:
    """Run the per-node import wizard (locate / fetch / enrich / persist)
    and stream stage events as Server-Sent Events.

    Phase 1 simplification: a single run from scratch. The client retries
    a failed import by re-POSTing this endpoint — there's no per-stage
    resume state on the server.
    """
    # Resolve dependencies up front so the stream's first event reflects
    # config errors quickly. The generator that backs the SSE stream
    # outlives the Depends(get_conn) teardown, so we open a fresh
    # connection inside it (same pattern as chat.py).
    settings_row = settings_repo.get_comfyui(conn)
    comfyui_url = settings_row.get("comfyui_url") or ""
    comfyui_path_str = settings_row.get("comfyui_path") or ""
    comfyui_api_key = settings_row.get("comfyui_api_key")

    lm_row = settings_repo.get_lmstudio(conn)
    llm_endpoint = {
        "server_root": lm_row.get("lmstudio_url") or "",
        "api_key": lm_row.get("lmstudio_api_key"),
    }
    favourite = settings_repo.get_favorite_lm_model(conn)
    llm_model = favourite["name"] if favourite is not None else None
    llm_sampling = settings_repo.get_default_bundle(conn, "comfy_import")

    comfyui_path = Path(comfyui_path_str) if comfyui_path_str else None
    db_path = _conn_file(conn)

    async def gen():
        gen_conn = db_mod.connect(db_path)
        try:
            async for event in comfy_import_service.run_import(
                class_type=class_type,
                conn=gen_conn,
                comfyui_url=comfyui_url,
                comfyui_api_key=comfyui_api_key,
                comfyui_path=comfyui_path,
                llm_endpoint=llm_endpoint,
                llm_model=llm_model,
                llm_sampling=llm_sampling,
            ):
                yield _sse(event)
        except Exception as exc:  # noqa: BLE001 — defence in depth.
            yield _sse({
                "type": "stage_failed",
                "stage": "internal",
                "error": f"unexpected error: {exc}",
            })
        finally:
            gen_conn.close()

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.put("/api/comfy/nodes/{class_type}", response_model=NodeOut)
def update_node(class_type: str, body: NodeUpdate, conn: Conn) -> dict:
    sent = body.model_fields_set
    kwargs: dict[str, object] = {}
    if "description_md" in sent:
        kwargs["description_md"] = body.description_md
    if "inputs_semantic" in sent:
        kwargs["inputs_semantic"] = (
            None
            if body.inputs_semantic is None
            else [item.model_dump() for item in body.inputs_semantic]
        )
    if "category" in sent:
        kwargs["category"] = body.category

    if not kwargs:
        # Nothing to update — just return current state.
        row = comfy_catalog_repo.get_node(conn, class_type)
        if row is None:
            raise HTTPException(status_code=404, detail="node not found")
        return row

    row = comfy_catalog_repo.set_override(conn, class_type=class_type, **kwargs)
    if row is None:
        raise HTTPException(status_code=404, detail="node not found")
    return row
