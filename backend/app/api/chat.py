from __future__ import annotations

import json
import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from starlette.responses import StreamingResponse

from app.api.deps import get_conn
from app.models.chat import ChatRequest, MessageOut, MessagesResponse
from app.services import lmstudio_client, prompt_orchestrator, task_runner
from app.storage import session_repo, settings_repo, source_image_repo

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

router = APIRouter(tags=["chat"])

CHAT_HISTORY_LIMIT = 30
CHAT_SYSTEM_PROMPT_BASE = (
    "You are a chat assistant helping the user iterate on a Stable-Diffusion "
    "image-to-image idea. Discuss composition, lighting, style, mood, and "
    "concrete edits. Stay concise and concrete; do not write final prompt JSON."
)
CHAT_SYSTEM_PROMPT_TOOL = (
    CHAT_SYSTEM_PROMPT_BASE
    + "\n\nWhen — and ONLY when — the user gives an explicit go-ahead "
    "('go', 'generate', 'погнали', 'давай', 'ок генерируй' or any clear "
    "equivalent), call the regenerate_prompt tool. Pass a `brief`: a "
    "concise, self-contained summary of the agreed direction. Do not call "
    "the tool while the user is still asking questions or refining ideas."
)

REGENERATE_PROMPT_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "regenerate_prompt",
        "description": (
            "Trigger image-prompt regeneration once the user has explicitly "
            "agreed on the direction. Do not call this proactively — wait "
            "for a clear go-ahead from the user."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "brief": {
                    "type": "string",
                    "description": (
                        "Concise, self-contained summary of the agreed "
                        "direction the prompt should take. Becomes the "
                        "primary input to the prompt-generation pipeline."
                    ),
                },
            },
            "required": ["brief"],
        },
    },
}


def _not_found(session_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"session not found: {session_id}",
    )


def _validated_prompt_model(conn: sqlite3.Connection, name: str | None) -> dict[str, Any]:
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
    return row


def _build_payload_messages(
    conn: sqlite3.Connection,
    session_row: dict,
    user_content: str,
    *,
    system_prompt: str,
) -> list[dict]:
    msgs: list[dict] = [{"role": "system", "content": system_prompt}]
    sources = source_image_repo.list_for_session(conn, session_row["id"])
    main_image = next((s for s in sources if s["is_main"]), None)
    if main_image is not None and (main_image.get("analysis") or "").strip():
        block = f"# Source image analysis\n{main_image['analysis']}"
        ref_lines = []
        for s in sources:
            if s["is_main"] or not (s.get("analysis") or "").strip():
                continue
            text = s["analysis"].strip().replace("\n", " ")
            ref_lines.append(f"- {s['original_filename']}: {text}")
        if ref_lines:
            block += "\n\n# Reference images\n" + "\n".join(ref_lines)
        msgs.append({"role": "system", "content": block})
    history = session_repo.list_messages(conn, session_id=session_row["id"])
    history = history[-CHAT_HISTORY_LIMIT:]
    for h in history:
        msgs.append({"role": h["role"], "content": h["content"]})
    msgs.append({"role": "user", "content": user_content})
    return msgs


def _sse(payload: dict) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


def _is_reindexing() -> bool:
    try:
        reg = task_runner.get()
    except RuntimeError:
        return False
    return bool(reg.find_active(
        lambda t: t.kind in ("reindex_lora", "reindex_all"),
    ))


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
    model_row = _validated_prompt_model(conn, session_row.get("prompt_model_name"))
    model = model_row["name"]
    tool_capable = bool(model_row.get("tool_use"))

    system_prompt = CHAT_SYSTEM_PROMPT_TOOL if tool_capable else CHAT_SYSTEM_PROMPT_BASE
    payload_messages = _build_payload_messages(
        conn, session_row, body.content, system_prompt=system_prompt,
    )
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
        accumulated: list[str] = []

        def emit_delta(chunk: str) -> bytes:
            accumulated.append(chunk)
            return _sse({"type": "delta", "content": chunk})

        try:
            if tool_capable:
                yield from _gen_tool_capable(
                    conn=conn,
                    session_row=session_row,
                    endpoint=endpoint,
                    model=model,
                    payload_messages=payload_messages,
                    accumulated=accumulated,
                    emit_delta=emit_delta,
                )
            else:
                for chunk in lmstudio_client.chat_stream(
                    endpoint=endpoint, model=model, messages=payload_messages,
                ):
                    yield emit_delta(chunk)
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


def _gen_tool_capable(
    *,
    conn: sqlite3.Connection,
    session_row: dict,
    endpoint: dict[str, Any],
    model: str,
    payload_messages: list[dict[str, Any]],
    accumulated: list[str],
    emit_delta,
):
    """Drive a chat turn with tool-calling.

    Streams the assistant's text. If the assistant invokes the
    `regenerate_prompt` tool, runs the orchestrator in-process, surfaces
    `tool_call` and `tool_result` SSE events, then re-enters the LLM with
    the tool result so the assistant can produce a closing follow-up
    message — those tokens are streamed as ordinary `delta` events too.
    """
    tool_call_event: dict[str, Any] | None = None
    for ev in lmstudio_client.chat_stream_with_tools(
        endpoint=endpoint,
        model=model,
        messages=payload_messages,
        tools=[REGENERATE_PROMPT_TOOL],
    ):
        if ev["type"] == "delta":
            yield emit_delta(ev["content"])
        elif ev["type"] == "tool_call":
            tool_call_event = ev

    if tool_call_event is None:
        return

    name = tool_call_event["name"]
    args = tool_call_event.get("arguments") or {}
    if name != "regenerate_prompt":
        # Unknown tool — surface as a chat error and stop.
        raise lmstudio_client.LmError(
            "shape", f"unexpected tool call: {name!r}",
        )

    brief = (args.get("brief") or "").strip()
    if not brief:
        raise lmstudio_client.LmError(
            "shape", "regenerate_prompt called without a non-empty brief",
        )

    yield _sse({"type": "tool_call", "name": name, "brief": brief})

    if _is_reindexing():
        tool_payload: dict[str, Any] = {
            "ok": False,
            "error": "LoRA index is updating — try again in a moment.",
        }
        yield _sse({"type": "tool_result", "ok": False, "error": tool_payload["error"]})
    else:
        try:
            out = prompt_orchestrator.generate(
                conn,
                session_id=session_row["id"],
                endpoint=endpoint,
                prompt_model=model,
                brief=brief,
            )
        except prompt_orchestrator.PreconditionError as exc:
            tool_payload = {"ok": False, "error": str(exc)}
            yield _sse({
                "type": "tool_result", "ok": False, "error": str(exc),
            })
        except lmstudio_client.LmError as exc:
            tool_payload = {"ok": False, "error": str(exc)}
            yield _sse({
                "type": "tool_result", "ok": False, "error": str(exc),
            })
        else:
            tool_payload = {
                "ok": True,
                "prompt_id": out["prompt_id"],
                "positive": out["prompt"]["positive"],
                "negative": out["prompt"].get("negative"),
                "loras": out["prompt"].get("loras") or [],
            }
            yield _sse({
                "type": "tool_result",
                "ok": True,
                "prompt_id": out["prompt_id"],
            })

    follow_up_messages: list[dict[str, Any]] = list(payload_messages) + [
        {
            "role": "assistant",
            "content": "".join(accumulated),
            "tool_calls": [
                {
                    "id": tool_call_event["id"],
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": tool_call_event.get(
                            "raw_arguments",
                        ) or json.dumps(args, ensure_ascii=False),
                    },
                },
            ],
        },
        {
            "role": "tool",
            "tool_call_id": tool_call_event["id"],
            "content": json.dumps(tool_payload, ensure_ascii=False),
        },
    ]
    for chunk in lmstudio_client.chat_stream(
        endpoint=endpoint, model=model, messages=follow_up_messages,
    ):
        yield emit_delta(chunk)
