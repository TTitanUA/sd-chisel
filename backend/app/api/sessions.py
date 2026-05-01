from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status

from app import config as app_config
from app.api.deps import get_conn
from app.models.session import (
    AnalyzeSourceRequest,
    HiddenPatch,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    SessionCreate,
    SessionOut,
    SessionUpdate,
    SourceImageOut,
)
from app.services import lmstudio_client
from app.storage import images, session_repo, settings_repo, source_image_repo
from app.utils.ids import new_id

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

router = APIRouter(tags=["sessions"])


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _not_found(kind: str, key: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail=f"{kind} not found: {key}",
    )


def _media_url(path: str) -> str:
    return f"/media/{path}"


def _source_image_to_api_dict(row: dict) -> dict:
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "path": row["path"],
        "url": _media_url(row["path"]),
        "original_filename": row["original_filename"],
        "image_number": row["image_number"],
        "is_main": bool(row["is_main"]),
        "analysis": row.get("analysis"),
        "analysis_prompt": row.get("analysis_prompt"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _session_to_api_dict(conn: sqlite3.Connection, row: dict) -> dict:
    sources = source_image_repo.list_for_session(conn, row["id"])
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "name": row["name"],
        "session_type": row.get("session_type") or "i2i",
        "model_name": row["model_name"],
        "use_negative": row["use_negative"],
        "pinned_loras": row.get("pinned_loras", []),
        "source_images": [_source_image_to_api_dict(s) for s in sources],
        "vl_model_name": row.get("vl_model_name"),
        "prompt_model_name": row.get("prompt_model_name"),
        "hidden": bool(row.get("hidden", False)),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _session_payload(conn: sqlite3.Connection, session_id: str) -> dict:
    row = session_repo.get_session_with_pinned(conn, session_id)
    if row is None:
        raise _not_found("session", session_id)
    return _session_to_api_dict(conn, row)


# --- projects ---------------------------------------------------------------


@router.get("/api/projects", response_model=list[ProjectOut])
def list_projects(conn: Conn):
    return session_repo.list_projects(conn)


@router.post("/api/projects", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreate, conn: Conn):
    try:
        return session_repo.create_project(conn, name=body.name)
    except sqlite3.IntegrityError as exc:
        raise _conflict(exc) from exc


@router.patch("/api/projects/{project_id}", response_model=ProjectOut)
def update_project(project_id: str, body: ProjectUpdate, conn: Conn):
    row = session_repo.update_project(conn, project_id, name=body.name)
    if row is None:
        raise _not_found("project", project_id)
    return row


@router.patch("/api/projects/{project_id}/hidden", response_model=ProjectOut)
def patch_project_hidden(project_id: str, body: HiddenPatch, conn: Conn):
    row = session_repo.set_project_hidden(conn, project_id, hidden=body.hidden)
    if row is None:
        raise _not_found("project", project_id)
    return row


@router.delete("/api/projects/{project_id}", status_code=204)
def delete_project(project_id: str, conn: Conn):
    cascaded = session_repo.delete_project_and_collect_sessions(conn, project_id)
    if cascaded is None:
        raise _not_found("project", project_id)
    for sid in cascaded:
        images.remove_session_images(sid)
    return Response(status_code=204)


# --- sessions ---------------------------------------------------------------


@router.get(
    "/api/projects/{project_id}/sessions", response_model=list[SessionOut],
)
def list_sessions(project_id: str, conn: Conn):
    if session_repo.get_project(conn, project_id) is None:
        raise _not_found("project", project_id)
    sessions = session_repo.list_sessions(conn, project_id)
    out = []
    for s in sessions:
        s2 = {**s}
        s2["pinned_loras"] = session_repo.list_pinned_loras(conn, s2["id"])
        out.append(_session_to_api_dict(conn, s2))
    return out


@router.post(
    "/api/projects/{project_id}/sessions",
    response_model=SessionOut,
    status_code=201,
)
def create_session(project_id: str, body: SessionCreate, conn: Conn):
    if session_repo.get_project(conn, project_id) is None:
        raise HTTPException(status_code=409, detail=f"unknown project: {project_id}")
    try:
        row = session_repo.create_session(
            conn,
            project_id=project_id,
            session_type=body.session_type,
            name=body.name,
            model_name=body.model_name,
            use_negative=body.use_negative,
        )
    except sqlite3.IntegrityError as exc:
        raise _conflict(exc) from exc
    return _session_payload(conn, row["id"])


@router.get("/api/sessions/{session_id}", response_model=SessionOut)
def get_session(session_id: str, conn: Conn):
    return _session_payload(conn, session_id)


@router.patch("/api/sessions/{session_id}", response_model=SessionOut)
def update_session(session_id: str, body: SessionUpdate, conn: Conn):
    row = session_repo.update_session(
        conn,
        session_id,
        name=body.name,
        model_name=body.model_name,
        use_negative=body.use_negative,
        vl_model_name=body.vl_model_name,
        prompt_model_name=body.prompt_model_name,
    )
    if row is None:
        raise _not_found("session", session_id)
    try:
        session_repo.set_pinned_loras(
            conn,
            session_id,
            [p.model_dump() for p in body.pinned_loras],
        )
    except sqlite3.IntegrityError as exc:
        raise _conflict(exc) from exc
    return _session_payload(conn, session_id)


@router.patch("/api/sessions/{session_id}/hidden", response_model=SessionOut)
def patch_session_hidden(session_id: str, body: HiddenPatch, conn: Conn):
    row = session_repo.set_session_hidden(conn, session_id, hidden=body.hidden)
    if row is None:
        raise _not_found("session", session_id)
    return _session_payload(conn, session_id)


@router.delete("/api/sessions/{session_id}", status_code=204)
def delete_session(session_id: str, conn: Conn):
    if session_repo.get_session(conn, session_id) is None:
        raise _not_found("session", session_id)
    images.remove_session_images(session_id)
    session_repo.delete_session(conn, session_id)
    return Response(status_code=204)


_ALLOWED_EXT: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}

_EXT_TO_CT: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def _resolve_ext(content_type: str | None) -> str:
    if content_type not in _ALLOWED_EXT:
        raise HTTPException(
            status_code=422,
            detail=f"unsupported content_type: {content_type!r}",
        )
    return _ALLOWED_EXT[content_type]


def _content_type_from_ext(ext: str) -> str:
    if ext not in _EXT_TO_CT:
        raise HTTPException(
            status_code=409,
            detail=f"stored image has unsupported extension: {ext!r}",
        )
    return _EXT_TO_CT[ext]


def _validated_vl_model(conn: sqlite3.Connection, name: str | None) -> str:
    if not name:
        raise HTTPException(
            status_code=409,
            detail="session has no vl_model_name selected",
        )
    row = settings_repo.get_lm_model(conn, name)
    if row is None or not row["enabled"] or not row["vision"]:
        raise HTTPException(
            status_code=409,
            detail=f"vl_model_name {name!r} is not enabled or does not support vision",
        )
    return name


def _require_session(conn: sqlite3.Connection, session_id: str) -> dict:
    row = session_repo.get_session(conn, session_id)
    if row is None:
        raise _not_found("session", session_id)
    return row


def _require_source_image(
    conn: sqlite3.Connection, session_id: str, image_id: str,
) -> dict:
    row = source_image_repo.get(conn, image_id)
    if row is None or row["session_id"] != session_id:
        raise _not_found("source image", image_id)
    return row


@router.get(
    "/api/sessions/{session_id}/sources",
    response_model=list[SourceImageOut],
)
def list_sources(session_id: str, conn: Conn):
    _require_session(conn, session_id)
    return [
        _source_image_to_api_dict(s)
        for s in source_image_repo.list_for_session(conn, session_id)
    ]


@router.post(
    "/api/sessions/{session_id}/sources",
    response_model=SourceImageOut,
    status_code=201,
)
async def upload_source_image(
    session_id: str,
    conn: Conn,
    file: Annotated[UploadFile, File()],
):
    _require_session(conn, session_id)
    ext = _resolve_ext(file.content_type)

    is_first = source_image_repo.count_for_session(conn, session_id) == 0
    sources_dir = images.session_sources_dir(session_id)

    image_id = new_id()
    rel_path = f"images/{session_id}/sources/{image_id}{ext}"
    target = sources_dir / f"{image_id}{ext}"
    target.write_bytes(await file.read())
    original_filename = (file.filename or f"image{ext}").strip() or f"image{ext}"
    inserted = source_image_repo.insert(
        conn,
        session_id=session_id,
        image_id=image_id,
        path=rel_path,
        original_filename=original_filename,
        is_main=is_first,
    )
    return _source_image_to_api_dict(inserted)


@router.delete(
    "/api/sessions/{session_id}/sources/{image_id}",
    status_code=204,
)
def delete_source_image(session_id: str, image_id: str, conn: Conn):
    _require_session(conn, session_id)
    existing = _require_source_image(conn, session_id, image_id)
    deleted = source_image_repo.delete(conn, image_id)
    if deleted is not None:
        data_root = app_config.resolve_data_root()
        target = (data_root / existing["path"]).resolve()
        base = data_root.resolve()
        if str(target).startswith(str(base)) and target.is_file():
            try:
                target.unlink()
            except OSError:
                pass
    if existing["is_main"]:
        source_image_repo.promote_first_remaining(conn, session_id)
    return Response(status_code=204)


@router.patch(
    "/api/sessions/{session_id}/sources/{image_id}/main",
    response_model=SourceImageOut,
)
def set_source_main(session_id: str, image_id: str, conn: Conn):
    _require_session(conn, session_id)
    _require_source_image(conn, session_id, image_id)
    updated = source_image_repo.set_main(
        conn, session_id=session_id, image_id=image_id,
    )
    if updated is None:
        raise _not_found("source image", image_id)
    return _source_image_to_api_dict(updated)


@router.post(
    "/api/sessions/{session_id}/sources/{image_id}/analyze",
    response_model=SourceImageOut,
)
def analyze_source_image(
    session_id: str,
    image_id: str,
    body: AnalyzeSourceRequest,
    conn: Conn,
) -> dict:
    session_row = _require_session(conn, session_id)
    image_row = _require_source_image(conn, session_id, image_id)

    cfg = settings_repo.get_lmstudio(conn)
    if not cfg["lmstudio_url"]:
        raise HTTPException(
            status_code=409, detail="LMStudio base_url is not configured",
        )
    model = _validated_vl_model(conn, session_row.get("vl_model_name"))

    data_root = app_config.resolve_data_root()
    image_path = (data_root / image_row["path"]).resolve()
    base = data_root.resolve()
    if not str(image_path).startswith(str(base)) or not image_path.is_file():
        raise HTTPException(status_code=409, detail="source image is missing on disk")

    content_type = _content_type_from_ext(image_path.suffix.lower())
    image_bytes = image_path.read_bytes()

    try:
        summary = lmstudio_client.analyze_image(
            endpoint={
                "server_root": cfg["lmstudio_url"],
                "api_key": cfg["lmstudio_api_key"],
            },
            model=model,
            image_bytes=image_bytes,
            content_type=content_type,
            refining_prompt=body.refining_prompt,
        )
    except lmstudio_client.LmError as exc:
        if exc.kind == "timeout":
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    refining = body.refining_prompt.strip() if body.refining_prompt else None
    updated = source_image_repo.set_analysis(
        conn, image_id, analysis=summary, refining_prompt=refining or None,
    )
    return _source_image_to_api_dict(updated)  # type: ignore[arg-type]
