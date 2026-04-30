"""HTTP layer for the two-step generate-prompt flow."""
from __future__ import annotations

import json
import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_conn
from app.models.prompts import (
    GeneratedPrompt,
    GeneratePromptResponse,
    Intent,
    PromptOut,
    PromptsResponse,
    RetrievedIntent,
)
from app.services import lmstudio_client, prompt_orchestrator
from app.storage import session_repo, settings_repo

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

router = APIRouter(tags=["prompt"])


def _not_found(session_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"session not found: {session_id}",
    )


def _validated_prompt_model(conn: sqlite3.Connection, name: str | None) -> str:
    if not name:
        raise HTTPException(
            status_code=409, detail="session has no prompt_model_name selected",
        )
    row = settings_repo.get_lm_model(conn, name)
    if row is None or not row["enabled"]:
        raise HTTPException(
            status_code=409,
            detail=f"prompt_model_name {name!r} is not enabled",
        )
    return name


@router.post(
    "/api/sessions/{session_id}/generate-prompt",
    response_model=GeneratePromptResponse,
)
def generate_prompt(session_id: str, conn: Conn) -> GeneratePromptResponse:
    session = session_repo.get_session(conn, session_id)
    if session is None:
        raise _not_found(session_id)

    cfg = settings_repo.get_lmstudio(conn)
    if not cfg["lmstudio_url"]:
        raise HTTPException(
            status_code=409, detail="LMStudio base_url is not configured",
        )
    model = _validated_prompt_model(conn, session.get("prompt_model_name"))
    endpoint = {
        "server_root": cfg["lmstudio_url"],
        "api_key": cfg["lmstudio_api_key"],
    }

    try:
        out = prompt_orchestrator.generate(
            conn,
            session_id=session_id,
            endpoint=endpoint,
            prompt_model=model,
        )
    except prompt_orchestrator.PreconditionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except lmstudio_client.LmError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return GeneratePromptResponse(
        prompt_id=out["prompt_id"],
        prompt=GeneratedPrompt.model_validate(out["prompt"]),
        intents=[Intent.model_validate(i) for i in out["intents"]],
        retrieved=[RetrievedIntent.model_validate(r) for r in out["retrieved"]],
        created_at=out["created_at"],
    )


def _row_to_prompt_out(row: dict[str, Any]) -> PromptOut:
    return PromptOut(
        id=row["id"],
        session_id=row["session_id"],
        prompt=GeneratedPrompt.model_validate({
            "positive": row["positive"],
            "negative": row["negative"],
            "loras": json.loads(row["loras_json"]),
        }),
        intents=(
            [Intent.model_validate(i) for i in json.loads(row["intents_json"])]
            if row["intents_json"] else None
        ),
        retrieved=(
            [
                RetrievedIntent.model_validate(r)
                for r in json.loads(row["retrieved_loras_json"])
            ]
            if row["retrieved_loras_json"] else None
        ),
        created_at=row["created_at"],
    )


@router.get(
    "/api/sessions/{session_id}/prompts",
    response_model=PromptsResponse,
)
def list_prompts(session_id: str, conn: Conn) -> PromptsResponse:
    if session_repo.get_session(conn, session_id) is None:
        raise _not_found(session_id)
    rows = session_repo.list_prompts(conn, session_id=session_id)
    return PromptsResponse(prompts=[_row_to_prompt_out(r) for r in rows])
