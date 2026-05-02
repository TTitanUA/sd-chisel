from __future__ import annotations

import json
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from starlette.responses import StreamingResponse

from app.api.deps import get_conn
from app.models.chat import ChatRequest, MessageOut, MessagesResponse
from app.services import llm_log, lmstudio_client
from app.storage import session_repo, settings_repo, source_image_repo

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

router = APIRouter(tags=["chat"])

CHAT_HISTORY_LIMIT = 30
CHAT_SYSTEM_PROMPT = (
    "You are a chat assistant helping the user iterate on a Stable-Diffusion "
    "image-to-image idea. Discuss composition, lighting, style, mood, and "
    "concrete edits. Stay concise and concrete; do not write final prompt "
    "JSON. Generation is launched by the user from a separate Generate "
    "button — never claim to have generated anything yourself."
)


def _not_found(session_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"session not found: {session_id}",
    )


def _validated_prompt_model_name(
    conn: sqlite3.Connection, name: str | None,
) -> str:
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


def _build_payload_messages(
    conn: sqlite3.Connection,
    session_row: dict,
    user_content: str,
) -> list[dict]:
    msgs: list[dict] = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}]
    sources = source_image_repo.list_for_session(conn, session_row["id"])
    main_image = next((s for s in sources if s["is_main"]), None)
    if main_image is not None and (main_image.get("analysis") or "").strip():
        main_label = f"Image_{main_image['image_number']}"
        block = (
            f"# Source image analysis ({main_label}, main)\n"
            f"{main_image['analysis']}"
        )
        ref_lines = []
        for s in sources:
            if s["is_main"] or not (s.get("analysis") or "").strip():
                continue
            text = s["analysis"].strip().replace("\n", " ")
            ref_lines.append(f"- Image_{s['image_number']}: {text}")
        if ref_lines:
            block += "\n\n# Reference images\n" + "\n".join(ref_lines)
        block += (
            "\n\nThe user may refer to images as `@Image_N` "
            "(e.g. `@Image_2`). Use the same `Image_N` form when you "
            "talk about images — do not invent filenames."
        )
        msgs.append({"role": "system", "content": block})
    history = session_repo.list_messages(conn, session_id=session_row["id"])
    history = history[-CHAT_HISTORY_LIMIT:]
    for h in history:
        msgs.append({"role": h["role"], "content": h["content"]})
    msgs.append({"role": "user", "content": user_content})
    return msgs


def _sse(payload: dict) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


@router.get(
    "/api/sessions/{session_id}/messages",
    response_model=MessagesResponse,
)
def list_messages(session_id: str, conn: Conn) -> MessagesResponse:
    if session_repo.get_session(conn, session_id) is None:
        raise _not_found(session_id)
    rows = session_repo.list_messages(conn, session_id=session_id)
    return MessagesResponse(messages=[MessageOut(**r) for r in rows])


@router.post("/api/sessions/{session_id}/chat")
def chat(session_id: str, body: ChatRequest, conn: Conn) -> Response:
    session_row = session_repo.get_session(conn, session_id)
    if session_row is None:
        raise _not_found(session_id)

    cfg = settings_repo.get_lmstudio(conn)
    if not cfg["lmstudio_url"]:
        raise HTTPException(status_code=409, detail="LMStudio base_url is not configured")
    model = _validated_prompt_model_name(conn, session_row.get("prompt_model_name"))

    payload_messages = _build_payload_messages(conn, session_row, body.content)
    endpoint = {
        "server_root": cfg["lmstudio_url"],
        "api_key": cfg["lmstudio_api_key"],
    }

    # Persist the user message AFTER building the payload but BEFORE streaming,
    # so it survives any upstream failure.
    session_repo.append_message(
        conn, session_id=session_id, role="user", content=body.content,
    )

    def gen():
        with llm_log.run_context():
            accumulated: list[str] = []
            try:
                for chunk in lmstudio_client.chat_stream(
                    endpoint=endpoint, model=model, messages=payload_messages,
                ):
                    accumulated.append(chunk)
                    yield _sse({"type": "delta", "content": chunk})
            except lmstudio_client.LmError as exc:
                yield _sse({"type": "error", "detail": str(exc)})
                return

            full = "".join(accumulated).strip()
            if not full:
                yield _sse({"type": "error", "detail": "empty assistant response"})
                return

            row = session_repo.append_message(
                conn, session_id=session_id, role="assistant", content=full,
            )
            yield _sse({"type": "done", "message_id": row["id"]})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
