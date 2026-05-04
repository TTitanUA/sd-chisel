from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_conn
from app.models.settings import (
    ActionDefaultsOut,
    ActionDefaultsPatch,
    LmModelOut,
    LmModelPatch,
    LmModelsOut,
    LmStudioConfig,
    LmStudioConfigOut,
    PrivacyOut,
    PrivacyPatch,
)
from app.services import action_settings, lmstudio_client
from app.storage import settings_repo

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

router = APIRouter(tags=["settings"])


def _to_config_out(row: dict) -> dict:
    return {
        "base_url": row["lmstudio_url"],
        "api_key": row["lmstudio_api_key"],
        "configured": bool(row["lmstudio_url"]),
        "updated_at": row["updated_at"],
    }


def _endpoint_from_row(row: dict) -> dict:
    return {
        "server_root": row["lmstudio_url"],
        "api_key": row["lmstudio_api_key"],
    }


def _lm_error_to_http(exc: lmstudio_client.LmError) -> HTTPException:
    if exc.kind == "timeout":
        return HTTPException(status_code=504, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


@router.get("/api/settings/lmstudio", response_model=LmStudioConfigOut)
def get_lmstudio(conn: Conn) -> dict:
    return _to_config_out(settings_repo.get_lmstudio(conn))


@router.put("/api/settings/lmstudio", response_model=LmStudioConfigOut)
def put_lmstudio(body: LmStudioConfig, conn: Conn) -> dict:
    return _to_config_out(
        settings_repo.set_lmstudio(conn, url=body.base_url, api_key=body.api_key),
    )


@router.post("/api/settings/lmstudio/unload-all")
def unload_all_lmstudio_models(conn: Conn) -> dict:
    cfg = settings_repo.get_lmstudio(conn)
    if not cfg["lmstudio_url"]:
        raise HTTPException(status_code=409, detail="LMStudio URL is not configured")
    endpoint = _endpoint_from_row(cfg)
    try:
        ids = lmstudio_client.list_loaded_instance_ids(endpoint=endpoint)
        for iid in ids:
            lmstudio_client.unload_model(endpoint=endpoint, instance_id=iid)
    except lmstudio_client.LmError as exc:
        raise _lm_error_to_http(exc) from exc
    return {"unloaded": len(ids)}


@router.post("/api/settings/lmstudio/refresh", response_model=LmModelsOut)
def refresh_lmstudio_models(conn: Conn) -> dict:
    cfg = settings_repo.get_lmstudio(conn)
    if not cfg["lmstudio_url"]:
        raise HTTPException(status_code=409, detail="LMStudio URL is not configured")
    try:
        lms_models = lmstudio_client.list_models(endpoint=_endpoint_from_row(cfg))
    except lmstudio_client.LmError as exc:
        raise _lm_error_to_http(exc) from exc
    settings_repo.upsert_lm_models(
        conn,
        models=[
            {"name": m.name, "vision": m.vision, "tool_use": m.tool_use, "reasoning": m.reasoning}
            for m in lms_models
        ],
    )
    return {"models": settings_repo.list_lm_models(conn)}


@router.get("/api/settings/lmstudio/models", response_model=LmModelsOut)
def list_lm_models(conn: Conn) -> dict:
    return {"models": settings_repo.list_lm_models(conn)}


@router.patch("/api/settings/lmstudio/models/{name}", response_model=LmModelOut)
def patch_lm_model(name: str, body: LmModelPatch, conn: Conn) -> dict:
    fields = [body.vision, body.tool_use, body.reasoning, body.enabled, body.favorite, body.hidden]
    if all(v is None for v in fields):
        raise HTTPException(status_code=422, detail="provide at least one field")
    row = settings_repo.patch_lm_model(
        conn, name=name,
        vision=body.vision, tool_use=body.tool_use,
        reasoning=body.reasoning, enabled=body.enabled,
        favorite=body.favorite, hidden=body.hidden,
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown model: {name}")
    return row


@router.get("/api/settings/privacy", response_model=PrivacyOut)
def get_privacy(conn: Conn) -> dict:
    return settings_repo.get_privacy(conn)


@router.put("/api/settings/privacy", response_model=PrivacyOut)
def put_privacy(body: PrivacyPatch, conn: Conn) -> dict:
    return settings_repo.set_privacy(conn, show_hidden=body.show_hidden)


@router.get("/api/settings/action-defaults", response_model=ActionDefaultsOut)
def get_action_defaults(conn: Conn) -> dict:
    return settings_repo.get_default_bundles(conn)


@router.put("/api/settings/action-defaults", response_model=ActionDefaultsOut)
def put_action_defaults(body: ActionDefaultsPatch, conn: Conn) -> dict:
    bundles: dict[str, dict] = {}
    sent = body.model_fields_set
    for action in action_settings.ACTIONS:
        if action not in sent:
            continue
        raw = getattr(body, action)
        if raw is None:
            bundles[action] = {}
        else:
            try:
                bundles[action] = action_settings.parse_bundle(raw)
            except action_settings.ActionSettingsError as exc:
                raise HTTPException(
                    status_code=400, detail=f"{action}: {exc}",
                ) from exc
    return settings_repo.set_default_bundles(conn, bundles=bundles)
