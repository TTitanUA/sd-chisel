from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from starlette.responses import StreamingResponse

from app.api.deps import get_conn
from app.models.chat import ChatRequest, MessageOut, MessagesResponse
from app.services import (
    action_settings,
    comfy_payload,
    comfy_slot_map_service,
    llm_log,
    lmstudio_client,
)
from app.storage import comfy_workflow_repo, session_repo, settings_repo, source_image_repo
from app.storage import db as db_mod

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

router = APIRouter(tags=["chat"])

CHAT_HISTORY_LIMIT = 30
CHAT_SYSTEM_PROMPT_I2I = (
    "You are a chat assistant helping the user iterate on a Stable-Diffusion "
    "image-to-image idea. Discuss composition, lighting, style, mood, and "
    "concrete edits to the source image. Stay concise and concrete; do not "
    "write final prompt JSON. Generation is launched by the user from a "
    "separate Generate button — never claim to have generated anything "
    "yourself."
)
CHAT_SYSTEM_PROMPT_T2I = (
    "You are a chat assistant helping the user iterate on a Stable-Diffusion "
    "text-to-image idea. Discuss subject, composition, lighting, style, and "
    "mood of the image the user wants to create. Reference images, if any, "
    "are inspiration only — the result is generated from text. Stay concise "
    "and concrete; do not write final prompt JSON. Generation is launched by "
    "the user from a separate Generate button — never claim to have generated "
    "anything yourself."
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


def _resolve_chat_mode_and_slots(
    conn: sqlite3.Connection, session_row: dict,
) -> tuple[str, list[dict]]:
    """For comfy sessions, derive the chat-time mode (i2i / t2i) from
    the bound workflow's slot map and return the slot list for the
    Q9 slot-awareness block. For legacy sessions, returns the
    session's explicit ``session_type`` and an empty slot list.

    Errors during slot resolution are swallowed — chat must keep
    working even if the workflow row is missing or the slot map is
    corrupt; we just degrade to a slot-unaware system prompt.
    """
    if session_row.get("session_type") != "comfy":
        return session_row.get("session_type") or "i2i", []
    workflow_id = session_row.get("comfy_workflow_id")
    if not workflow_id:
        return "t2i", []
    try:
        workflow = comfy_workflow_repo.get_workflow(conn, workflow_id)
        if workflow is None:
            return "t2i", []
        candidates = comfy_slot_map_service.compute_candidates(
            conn=conn, graph=workflow["graph"],
        )
        slot_map_v2 = comfy_slot_map_service.upgrade_slot_map(
            raw=workflow.get("slot_map"), candidates=candidates,
        )
    except Exception:  # noqa: BLE001 — chat must not crash on a bad workflow row
        return "t2i", []
    return (
        comfy_slot_map_service.infer_mode(slot_map_v2),
        list(slot_map_v2.get("slots") or []),
    )


def _build_system_messages(
    conn: sqlite3.Connection, session_row: dict,
) -> list[dict]:
    mode, comfy_slots = _resolve_chat_mode_and_slots(conn, session_row)
    system_prompt = (
        CHAT_SYSTEM_PROMPT_T2I if mode == "t2i" else CHAT_SYSTEM_PROMPT_I2I
    )
    msgs: list[dict] = [{"role": "system", "content": system_prompt}]
    sources = source_image_repo.list_for_session(conn, session_row["id"])
    analysis_trailer = (
        "\n\nThe user may refer to images as `@Image_N` "
        "(e.g. `@Image_2`). Use the same `Image_N` form when you "
        "talk about images — do not invent filenames."
    )
    if mode == "t2i":
        ref_lines = []
        for s in sources:
            if not (s.get("analysis") or "").strip():
                continue
            text = s["analysis"].strip().replace("\n", " ")
            ref_lines.append(f"- Image_{s['image_number']}: {text}")
        if ref_lines:
            block = "# Reference images\n" + "\n".join(ref_lines) + analysis_trailer
            msgs.append({"role": "system", "content": block})
    else:
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
            block += analysis_trailer
            msgs.append({"role": "system", "content": block})

    # Q9: slot-aware chat for comfy sessions with a non-empty slot map.
    # Empty slot maps (fresh upload, not yet labelled) and legacy
    # i2i / t2i sessions skip the block entirely.
    if comfy_slots:
        slot_block = comfy_payload.build_chat_slot_block(comfy_slots)
        if slot_block:
            msgs.append({"role": "system", "content": slot_block})
    return msgs


def _append_history(msgs: list[dict], history: list[dict]) -> None:
    """Append chat history to ``msgs`` with the leading-assistant fix.

    After modal-driven compaction the history starts with a single
    assistant "Summary of previous discussion" row. Some local models use
    strict jinja templates that reject a conversation whose first
    non-system turn is the assistant — they raise "No user query found
    in messages." Promote any leading assistant rows to system context so
    the first remaining user/assistant pair starts with the user.
    """
    leading_assistant: list[dict] = []
    while history and history[0]["role"] == "assistant":
        leading_assistant.append(history[0])
        history = history[1:]
    for h in leading_assistant:
        msgs.append({"role": "system", "content": h["content"]})
    for h in history:
        msgs.append({"role": h["role"], "content": h["content"]})


def _build_payload_messages(
    conn: sqlite3.Connection,
    session_row: dict,
    user_content: str,
) -> list[dict]:
    msgs = _build_system_messages(conn, session_row)
    history = session_repo.list_messages(conn, session_id=session_row["id"])
    history = history[-CHAT_HISTORY_LIMIT:]
    _append_history(msgs, history)
    msgs.append({"role": "user", "content": user_content})
    return msgs


def _build_payload_messages_for_edit(
    conn: sqlite3.Connection, session_row: dict,
) -> list[dict]:
    """Like ``_build_payload_messages`` but for the edit branch, where the
    current chat history already ends with the edited user turn. We must
    NOT append another user row — that would re-introduce the
    two-user-in-a-row case the edit flow exists to avoid.
    """
    msgs = _build_system_messages(conn, session_row)
    history = session_repo.list_messages(conn, session_id=session_row["id"])
    history = history[-CHAT_HISTORY_LIMIT:]
    _append_history(msgs, history)
    return msgs


def _sse(payload: dict) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


def _conn_file(conn: sqlite3.Connection) -> Path:
    """Return the on-disk path of the ``main`` database for ``conn``.

    The streaming generator outlives the request-scoped ``Depends(get_conn)``
    teardown, so we cannot reuse ``conn`` inside ``gen()`` — it has already
    been closed by the time Starlette starts iterating the body. We open a
    fresh connection to the same file instead. ``PRAGMA database_list``
    returns ``(seq, name, file)`` rows; the ``main`` row carries the path.
    """
    for row in conn.execute("PRAGMA database_list").fetchall():
        if row["name"] == "main":
            return Path(row["file"])
    raise RuntimeError("connection has no 'main' database attached")


@router.get(
    "/api/sessions/{session_id}/messages",
    response_model=MessagesResponse,
)
def list_messages(session_id: str, conn: Conn) -> MessagesResponse:
    if session_repo.get_session(conn, session_id) is None:
        raise _not_found(session_id)
    rows = session_repo.list_messages(conn, session_id=session_id)
    return MessagesResponse(messages=[MessageOut(**r) for r in rows])


def _user_message_or_404(
    conn: sqlite3.Connection, session_id: str, message_id: int,
) -> dict:
    if session_repo.get_session(conn, session_id) is None:
        raise _not_found(session_id)
    row = session_repo.get_message(conn, message_id=message_id)
    if row is None or row["session_id"] != session_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"message not found: {message_id}",
        )
    if row["role"] != "user":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="only user messages can be deleted",
        )
    return row


@router.delete(
    "/api/sessions/{session_id}/messages/{message_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_message(session_id: str, message_id: int, conn: Conn) -> Response:
    _user_message_or_404(conn, session_id, message_id)
    session_repo.delete_message(conn, message_id=message_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/api/sessions/{session_id}/messages",
    status_code=status.HTTP_204_NO_CONTENT,
)
def clear_messages(session_id: str, conn: Conn) -> Response:
    if session_repo.get_session(conn, session_id) is None:
        raise _not_found(session_id)
    session_repo.clear_messages(conn, session_id=session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/api/sessions/{session_id}/chat")
def chat(session_id: str, body: ChatRequest, conn: Conn) -> Response:
    session_row = session_repo.get_session(conn, session_id)
    if session_row is None:
        raise _not_found(session_id)

    cfg = settings_repo.get_lmstudio(conn)
    if not cfg["lmstudio_url"]:
        raise HTTPException(status_code=409, detail="LMStudio base_url is not configured")
    model = _validated_prompt_model_name(conn, session_row.get("prompt_model_name"))
    sampling = action_settings.resolve_for_session(conn, session_row, "chat")

    # Edit branch: replace an existing user turn and drop everything after
    # it before assembling the payload. The edited row IS the user turn —
    # we don't append a new user message, so there is no risk of two user
    # rows in a row. On upstream failure the edit stays committed (the
    # user explicitly asked for it); they can re-send from the composer.
    rollback_user_id: int | None = None
    if body.replace_message_id is not None:
        target = session_repo.get_message(conn, message_id=body.replace_message_id)
        if target is None or target["session_id"] != session_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"message not found: {body.replace_message_id}",
            )
        if target["role"] != "user":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="only user messages can be edited",
            )
        session_repo.delete_messages_after(
            conn, session_id=session_id, message_id=body.replace_message_id,
        )
        session_repo.update_message_content(
            conn, message_id=body.replace_message_id, content=body.content,
        )
        # _build_payload_messages reads history then appends body.content as
        # the trailing user turn. After the edit, history already ends with
        # the target user row carrying body.content — we want exactly one
        # user turn at the tail, so use the edit-aware builder that does
        # not re-append.
        payload_messages = _build_payload_messages_for_edit(conn, session_row)
    else:
        payload_messages = _build_payload_messages(conn, session_row, body.content)
        # Persist the new user message before streaming so the assistant
        # turn can commit it together with its reply on success. On any
        # upstream failure we roll the user row back so a retry doesn't
        # pile up duplicate user turns in the history.
        user_row = session_repo.append_message(
            conn, session_id=session_id, role="user", content=body.content,
        )
        rollback_user_id = user_row["id"]

    endpoint = {
        "server_root": cfg["lmstudio_url"],
        "api_key": cfg["lmstudio_api_key"],
    }

    # Capture the db file now — Starlette tears down ``Depends(get_conn)``
    # BEFORE iterating the StreamingResponse body, so ``conn`` is closed by
    # the time ``gen()`` runs. ``gen()`` opens its own short-lived
    # connection to persist the assistant turn (or roll the user row back
    # on error).
    db_file = _conn_file(conn)

    def gen():
        with llm_log.run_context():
            accumulated: list[str] = []
            stream_failed: lmstudio_client.LmError | None = None
            try:
                for chunk in lmstudio_client.chat_stream(
                    endpoint=endpoint, model=model, messages=payload_messages,
                    sampling=sampling,
                ):
                    accumulated.append(chunk)
                    yield _sse({"type": "delta", "content": chunk})
            except lmstudio_client.LmError as exc:
                stream_failed = exc

            stream_conn = db_mod.connect(db_file)
            try:
                if stream_failed is not None:
                    if rollback_user_id is not None:
                        session_repo.delete_message(stream_conn, message_id=rollback_user_id)
                    yield _sse({"type": "error", "detail": str(stream_failed)})
                    return

                full = "".join(accumulated).strip()
                if not full:
                    if rollback_user_id is not None:
                        session_repo.delete_message(stream_conn, message_id=rollback_user_id)
                    yield _sse({"type": "error", "detail": "empty assistant response"})
                    return

                row = session_repo.append_message(
                    stream_conn, session_id=session_id, role="assistant", content=full,
                )
                yield _sse({"type": "done", "message_id": row["id"]})
            finally:
                stream_conn.close()

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
