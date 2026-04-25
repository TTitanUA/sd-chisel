from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_conn
from app.models.settings import (
    LmModelOut,
    LmModelPatch,
    LmModelsOut,
    LmStudioConfig,
    LmStudioConfigOut,
)
from app.services import lm_client
from app.storage import settings_repo

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

router = APIRouter(tags=["settings"])


def _to_config_out(row: dict) -> dict:
    return {
        "base_url": row["lmstudio_base_url"],
        "api_key": row["lmstudio_api_key"],
        "configured": bool(row["lmstudio_base_url"]),
        "updated_at": row["updated_at"],
    }


def _endpoint_from_row(row: dict) -> dict:
    return {
        "base_url": row["lmstudio_base_url"],
        "api_key": row["lmstudio_api_key"],
    }


def _vl_translate(exc: lm_client.LmError) -> HTTPException:
    if exc.kind == "timeout":
        return HTTPException(status_code=504, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


@router.get("/api/settings/lmstudio", response_model=LmStudioConfigOut)
def get_lmstudio(conn: Conn) -> dict:
    return _to_config_out(settings_repo.get_lmstudio(conn))


@router.put("/api/settings/lmstudio", response_model=LmStudioConfigOut)
def put_lmstudio(body: LmStudioConfig, conn: Conn) -> dict:
    return _to_config_out(
        settings_repo.set_lmstudio(conn, base_url=body.base_url, api_key=body.api_key),
    )


@router.post("/api/settings/lmstudio/refresh", response_model=LmModelsOut)
def refresh_lmstudio_models(conn: Conn) -> dict:
    cfg = settings_repo.get_lmstudio(conn)
    if not cfg["lmstudio_base_url"]:
        raise HTTPException(status_code=409, detail="LMStudio base_url is not configured")
    try:
        names = lm_client.list_models(endpoint=_endpoint_from_row(cfg))
    except lm_client.LmError as exc:
        raise _vl_translate(exc) from exc
    settings_repo.upsert_lm_models(conn, names=names)
    return {"models": settings_repo.list_lm_models(conn)}


@router.get("/api/settings/lmstudio/models", response_model=LmModelsOut)
def list_lm_models(conn: Conn) -> dict:
    return {"models": settings_repo.list_lm_models(conn)}


@router.patch("/api/settings/lmstudio/models/{name}", response_model=LmModelOut)
def patch_lm_model(name: str, body: LmModelPatch, conn: Conn) -> dict:
    if body.role is None and body.enabled is None:
        raise HTTPException(status_code=422, detail="provide role or enabled")
    row = settings_repo.update_lm_model(
        conn, name=name, role=body.role, enabled=body.enabled,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown model: {name}",
        )
    return row
