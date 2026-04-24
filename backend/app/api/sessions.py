from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status

from app.api.deps import get_conn
from app.models.session import (
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    SessionCreate,
    SessionOut,
    SessionUpdate,
)
from app.storage import images, session_repo

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

router = APIRouter(tags=["sessions"])


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _not_found(kind: str, key: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail=f"{kind} not found: {key}",
    )


def _session_url(path: str | None) -> str | None:
    return f"/media/{path}" if path else None


def _session_to_api_dict(row: dict) -> dict:
    """Narrow DB row to SessionOut (exclude vl_endpoint, prompt_endpoint, etc.)."""
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "name": row["name"],
        "model_name": row["model_name"],
        "use_negative": row["use_negative"],
        "pinned_loras": row.get("pinned_loras", []),
        "source_image_path": row.get("source_image_path"),
        "source_image_url": _session_url(row.get("source_image_path")),
        "vl_summary": row.get("vl_summary"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _session_payload(conn: sqlite3.Connection, session_id: str) -> dict:
    row = session_repo.get_session_with_pinned(conn, session_id)
    if row is None:
        raise _not_found("session", session_id)
    return _session_to_api_dict(row)


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
        out.append(_session_to_api_dict(s2))
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


def _resolve_ext(content_type: str | None) -> str:
    if content_type not in _ALLOWED_EXT:
        raise HTTPException(
            status_code=422,
            detail=f"unsupported content_type: {content_type!r}",
        )
    return _ALLOWED_EXT[content_type]


@router.post("/api/sessions/{session_id}/source", response_model=SessionOut)
async def upload_source(
    session_id: str,
    conn: Conn,
    file: Annotated[UploadFile, File()],
):
    if session_repo.get_session(conn, session_id) is None:
        raise _not_found("session", session_id)
    ext = _resolve_ext(file.content_type)

    target_dir = images.session_image_dir(session_id)
    for previous in target_dir.glob("source.*"):
        previous.unlink()
    target = target_dir / f"source{ext}"
    target.write_bytes(await file.read())

    rel_path = f"images/{session_id}/source{ext}"
    session_repo.set_source_image(conn, session_id, rel_path)
    return _session_payload(conn, session_id)


@router.delete("/api/sessions/{session_id}/source", response_model=SessionOut)
def clear_source(session_id: str, conn: Conn):
    if session_repo.get_session(conn, session_id) is None:
        raise _not_found("session", session_id)
    target_dir = images.session_image_dir(session_id)
    for previous in target_dir.glob("source.*"):
        previous.unlink()
    session_repo.clear_source_image(conn, session_id)
    return _session_payload(conn, session_id)
