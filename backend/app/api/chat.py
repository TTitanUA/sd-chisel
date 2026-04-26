from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from app.api.deps import get_conn
from app.models.chat import MessageOut
from app.storage import session_repo

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

router = APIRouter(tags=["chat"])


class MessagesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messages: list[MessageOut]


def _not_found(session_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"session not found: {session_id}",
    )


@router.get(
    "/api/sessions/{session_id}/messages",
    response_model=MessagesResponse,
)
def list_messages(session_id: str, conn: Conn) -> MessagesResponse:
    if session_repo.get_session(conn, session_id) is None:
        raise _not_found(session_id)
    rows = session_repo.list_messages(conn, session_id=session_id)
    return MessagesResponse(messages=[MessageOut(**r) for r in rows])
