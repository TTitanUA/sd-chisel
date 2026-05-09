"""REST endpoints for ``comfy_session_source_slots`` — per-session
named source slots (key + purpose + description + bound image).

Until 020 these lived in localStorage. Workflow slot maps and agent
input slots store slot ids; clients may pass an explicit ``id`` on
POST so the one-time migration shim keeps existing references valid.
"""
from __future__ import annotations

import sqlite3
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.api.deps import get_conn
from app.models.session import COMFY_LIKE_TYPES
from app.storage import (
    comfy_source_slot_repo,
    session_repo,
    source_image_repo,
)

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
Purpose = Literal["main", "ref_in_scene", "ref_text_only"]

router = APIRouter(tags=["comfy_source_slots"])


# --- request / response models -----------------------------------------


class SourceSlotOut(BaseModel):
    id: str
    session_id: str
    position: int
    key: str
    purpose: Purpose
    description: str | None
    source_image_id: str | None
    created_at: int
    updated_at: int


class SourceSlotsListOut(BaseModel):
    slots: list[SourceSlotOut]


class SourceSlotCreateBody(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    purpose: Purpose = "main"
    description: str | None = None
    source_image_id: str | None = None
    position: int | None = None
    """Optional explicit id for the localStorage migration shim. The
    frontend posts existing ids so workflow / agent references that
    already point at a SourceSlot id keep resolving. Random new id
    is assigned when omitted."""
    id: str | None = None


class SourceSlotPatchBody(BaseModel):
    """All fields optional. Description and source_image_id can be
    cleared with an explicit `null`; omitting the field leaves the
    current value alone (sentinel handled by the repo)."""
    key: str | None = None
    purpose: Purpose | None = None
    # `description` / `source_image_id` use Pydantic's "field present
    # but value-typed" trick: we read from `model_fields_set` to tell
    # null-clear from absence.
    description: str | None = None
    source_image_id: str | None = None
    position: int | None = None


# --- helpers ------------------------------------------------------------


def _ensure_comfy_session(conn: sqlite3.Connection, session_id: str) -> dict:
    session = session_repo.get_session(conn, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    if session.get("session_type") not in COMFY_LIKE_TYPES:
        raise HTTPException(
            status_code=409, detail="session is not a comfy session",
        )
    return session


def _validate_image(
    conn: sqlite3.Connection,
    session_id: str,
    image_id: str | None,
) -> None:
    if image_id is None:
        return
    image = source_image_repo.get(conn, image_id)
    if image is None or image["session_id"] != session_id:
        raise HTTPException(
            status_code=409,
            detail=f"image {image_id!r} not found in session",
        )


# --- endpoints ----------------------------------------------------------


@router.get(
    "/api/comfy/sessions/{session_id}/source_slots",
    response_model=SourceSlotsListOut,
)
def list_source_slots(session_id: str, conn: Conn) -> dict[str, Any]:
    _ensure_comfy_session(conn, session_id)
    return {"slots": comfy_source_slot_repo.list_for_session(conn, session_id)}


@router.post(
    "/api/comfy/sessions/{session_id}/source_slots",
    response_model=SourceSlotOut,
    status_code=status.HTTP_201_CREATED,
)
def create_source_slot(
    session_id: str,
    body: SourceSlotCreateBody,
    conn: Conn,
) -> dict[str, Any]:
    _ensure_comfy_session(conn, session_id)
    _validate_image(conn, session_id, body.source_image_id)
    try:
        slot = comfy_source_slot_repo.create(
            conn,
            session_id=session_id,
            key=body.key,
            purpose=body.purpose,
            description=body.description,
            source_image_id=body.source_image_id,
            position=body.position,
            slot_id=body.id,
        )
    except ValueError as exc:
        # Either invalid purpose (caught upstream by Pydantic) or
        # duplicate key — translate to 409.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return slot


@router.patch(
    "/api/comfy/sessions/{session_id}/source_slots/{slot_id}",
    response_model=SourceSlotOut,
)
def update_source_slot(
    session_id: str,
    slot_id: str,
    body: SourceSlotPatchBody,
    conn: Conn,
) -> dict[str, Any]:
    _ensure_comfy_session(conn, session_id)
    fields = body.model_fields_set
    description: Any = comfy_source_slot_repo._UNSET
    if "description" in fields:
        description = body.description
    image_id: Any = comfy_source_slot_repo._UNSET
    if "source_image_id" in fields:
        image_id = body.source_image_id
        _validate_image(conn, session_id, image_id)
    try:
        slot = comfy_source_slot_repo.update(
            conn,
            session_id=session_id, slot_id=slot_id,
            key=body.key,
            purpose=body.purpose,
            description=description,
            source_image_id=image_id,
            position=body.position,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if slot is None:
        raise HTTPException(status_code=404, detail="slot not found")
    return slot


@router.delete(
    "/api/comfy/sessions/{session_id}/source_slots/{slot_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_source_slot(
    session_id: str, slot_id: str, conn: Conn,
) -> Response:
    _ensure_comfy_session(conn, session_id)
    if not comfy_source_slot_repo.delete(conn, session_id, slot_id):
        raise HTTPException(status_code=404, detail="slot not found")
    return Response(status_code=204)
