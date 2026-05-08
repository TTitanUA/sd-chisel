from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_conn
from app.models.settings import (
    ActionDefaultsOut,
    ActionDefaultsPatch,
    ComfyUiCheckFieldOut,
    ComfyUiCheckOut,
    ComfyUiConfig,
    ComfyUiConfigOut,
    LmModelOut,
    LmModelPatch,
    LmModelsOut,
    LmStudioConfig,
    LmStudioConfigOut,
    PrivacyOut,
    PrivacyPatch,
)
from app.services import action_settings, comfy_client, lmstudio_client
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


@router.patch("/api/settings/lmstudio/models/{name:path}", response_model=LmModelOut)
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


def _to_comfy_out(row: dict) -> dict:
    from app.services import comfy_paths

    eff_input = comfy_paths.resolve_input_dir(row)
    eff_output = comfy_paths.resolve_output_dir(row)
    return {
        "base_url": row["comfyui_url"],
        "install_path": row["comfyui_path"],
        "api_key": row["comfyui_api_key"],
        "input_dir": row.get("comfyui_input_dir"),
        "output_dir": row.get("comfyui_output_dir"),
        "effective_input_dir": str(eff_input) if eff_input else None,
        "effective_output_dir": str(eff_output) if eff_output else None,
        "configured": bool(row["comfyui_url"]) and bool(row["comfyui_path"]),
        "updated_at": row["updated_at"],
    }


def _comfy_endpoint_from_row(row: dict) -> dict:
    return {
        "server_root": row["comfyui_url"],
        "api_key": row["comfyui_api_key"],
    }


@router.get("/api/settings/comfyui", response_model=ComfyUiConfigOut)
def get_comfyui(conn: Conn) -> dict:
    return _to_comfy_out(settings_repo.get_comfyui(conn))


@router.put("/api/settings/comfyui", response_model=ComfyUiConfigOut)
def put_comfyui(body: ComfyUiConfig, conn: Conn) -> dict:
    return _to_comfy_out(
        settings_repo.set_comfyui(
            conn,
            url=body.base_url,
            install_path=body.install_path,
            api_key=body.api_key,
            input_dir=body.input_dir,
            output_dir=body.output_dir,
        ),
    )


def _check_comfy_url(row: dict) -> dict[str, Any]:
    if not row.get("comfyui_url"):
        return {"ok": False, "detail": "URL is not set", "info": None}
    try:
        stats = comfy_client.system_stats(endpoint=_comfy_endpoint_from_row(row))
    except comfy_client.ComfyError as exc:
        return {"ok": False, "detail": str(exc), "info": None}
    return {
        "ok": True,
        "detail": None,
        "info": {
            "comfyui_version": stats.comfyui_version,
            "python_version": stats.python_version,
            "os": stats.os,
        },
    }


def _check_comfy_path(row: dict) -> dict[str, Any]:
    raw = row.get("comfyui_path")
    if not raw:
        return {"ok": False, "detail": "Path is not set", "info": None}
    p = Path(raw)
    if not p.exists():
        return {"ok": False, "detail": "Path does not exist", "info": None}
    if not p.is_dir():
        return {"ok": False, "detail": "Path is not a directory", "info": None}
    custom_nodes = p / "custom_nodes"
    if not custom_nodes.is_dir():
        return {
            "ok": False,
            "detail": "No 'custom_nodes/' subdirectory — is this really the ComfyUI install root?",
            "info": None,
        }
    pack_count = sum(
        1 for child in custom_nodes.iterdir()
        if child.is_dir() and not child.name.startswith((".", "__"))
    )
    return {
        "ok": True,
        "detail": None,
        "info": {"pack_count": pack_count},
    }


@router.post("/api/settings/comfyui/check", response_model=ComfyUiCheckOut)
async def check_comfyui(conn: Conn) -> dict:
    row = settings_repo.get_comfyui(conn)
    # Run both checks concurrently — they're independent and the URL
    # one does network I/O while the path one hits the filesystem.
    url_task = asyncio.to_thread(_check_comfy_url, row)
    path_task = asyncio.to_thread(_check_comfy_path, row)
    url_result, path_result = await asyncio.gather(url_task, path_task)
    return {
        "url": ComfyUiCheckFieldOut(**url_result).model_dump(),
        "install_path": ComfyUiCheckFieldOut(**path_result).model_dump(),
    }


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
