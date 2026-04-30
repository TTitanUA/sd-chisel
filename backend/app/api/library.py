from __future__ import annotations

import json
import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from starlette.responses import StreamingResponse

from app.api.deps import get_conn
from app.models.library import (
    AssistRequest,
    FamilyCreate,
    FamilyOut,
    FamilyUpdate,
    LoraCreate,
    LoraOut,
    LoraUpdate,
    ModelCreate,
    ModelOut,
    ModelUpdate,
)
from app.services import embedder, library_service, lmstudio_client
from app.storage import library_repo, settings_repo

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

router = APIRouter(prefix="/api/library", tags=["library"])


def _conflict(exc: sqlite3.IntegrityError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _not_found(kind: str, key: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{kind} not found: {key}")


def _embedder_failure(exc: embedder.EmbedderError) -> HTTPException:
    return HTTPException(status_code=500, detail=f"embedder failed: {exc}")


def _dump(data: ModelCreate | ModelUpdate | LoraCreate | LoraUpdate) -> dict:
    return data.model_dump(mode="json")


@router.get("/families", response_model=list[FamilyOut])
def list_families(conn: Conn, q: str | None = None):
    return library_repo.list_families(conn, q=q)


@router.get("/families/{family_id}", response_model=FamilyOut)
def get_family(family_id: str, conn: Conn):
    row = library_repo.get_family(conn, family_id)
    if row is None:
        raise _not_found("family", family_id)
    return row


@router.post("/families", response_model=FamilyOut, status_code=status.HTTP_201_CREATED)
def create_family(body: FamilyCreate, conn: Conn):
    try:
        return library_repo.create_family(conn, **body.model_dump())
    except sqlite3.IntegrityError as exc:
        raise _conflict(exc) from exc


ASSIST_SYSTEM_PROMPT = (
    "You are writing prompt guides for a generative image model family. "
    "The guides you produce will be fed to ANOTHER LLM whose only job is to "
    "write image prompts (text-to-image and image-to-image) for this family.\n\n"
    "There are THREE separate guides you can update independently:\n\n"
    "[prompt_guide] — BASE rules shared across all modes:\n"
    "- REQUIRED: language the output prompt must be written in (e.g. "
    "English-only, Booru tags in English with descriptive prose in English, "
    "etc.). This is about the OUTPUT prompt language, not the user's chat "
    "language.\n"
    "- Tag/keyword syntax and formatting.\n"
    "- Quality and style tokens.\n"
    "- Token limits and recommended length.\n"
    "- LoRA interaction patterns and weight conventions.\n"
    "- Negative prompt conventions.\n\n"
    "[prompt_i2i] — IMAGE-TO-IMAGE-specific additions only:\n"
    "- What to preserve from the source image.\n"
    "- Transformation language (subtle vs aggressive edits).\n"
    "- Denoising / strength guidance, if family-specific.\n\n"
    "[prompt_t2i] — TEXT-TO-IMAGE-specific additions only:\n"
    "- Full scene composition rules.\n"
    "- Subject and background description conventions.\n"
    "- How to describe pose, framing, camera, etc.\n\n"
    "Use the corresponding tool to update each guide:\n"
    "- update_prompt_guide for the base guide.\n"
    "- update_prompt_i2i for the i2i additions.\n"
    "- update_prompt_t2i for the t2i additions.\n\n"
    "The base [prompt_guide] MUST include a section specifying the language "
    "the output prompt should be written in. If the user does not provide it, "
    "ask.\n\n"
    "Do not duplicate base rules into i2i/t2i guides. Mode-specific guides "
    "should contain ONLY what is specific to that mode.\n\n"
    "When the user provides documentation links, use your browser tools to "
    "navigate to the URL and read the content. Extract only the prompt-relevant "
    "facts.\n\n"
    "Strict rules for guide content:\n"
    "- No marketing prose, model history, benchmark numbers, or licensing notes.\n"
    "- No links, citations, or 'see docs at …' references.\n"
    "- No emojis.\n"
    "- No code examples, no API/SDK snippets, no curl/python/json blocks.\n"
    "- No filler like 'this section explains' — write the rule directly.\n"
    "- Prefer compact tables and bullet lists over paragraphs.\n\n"
    "The user's message will be preceded by a 'Current editor state:' block "
    "with the latest values of all three guides. Use it to know what is already "
    "written and what to change. Call the appropriate update_* tool with the "
    "FULL new content of that field (not a diff)."
)


def _function_tool(name: str, description: str) -> dict:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Full markdown content for this guide.",
                },
            },
            "required": ["content"],
            "additionalProperties": False,
        },
    }


ASSIST_FIELD_BY_TOOL = {
    "update_prompt_guide": "prompt_guide",
    "update_prompt_i2i": "prompt_i2i",
    "update_prompt_t2i": "prompt_t2i",
}

ASSIST_TOOLS = [
    _function_tool(
        "update_prompt_guide",
        "Update the BASE prompt guide (shared rules across all modes).",
    ),
    _function_tool(
        "update_prompt_i2i",
        "Update the IMAGE-TO-IMAGE-specific additions to the prompt guide.",
    ),
    _function_tool(
        "update_prompt_t2i",
        "Update the TEXT-TO-IMAGE-specific additions to the prompt guide.",
    ),
    # Reference Playwright MCP from LMStudio's mcp.json. The "Allow calling
    # servers from mcp.json" setting must be enabled in LMStudio Server Settings.
    {"type": "mcp", "server_label": "playwright"},
]


def _assist_sse(payload: dict) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


def _format_snapshot(snap) -> str:
    """Render the editor state block prepended to the user message.

    `snap` is an `AssistFieldsSnapshot` instance. Empty fields show as
    "(empty)" so the model knows there's nothing yet rather than guessing.
    """
    def section(label: str, value: str) -> str:
        return f"[{label}]\n{value if value.strip() else '(empty)'}"

    return (
        "Current editor state:\n"
        + section("prompt_guide", snap.prompt_guide)
        + "\n\n"
        + section("prompt_i2i", snap.prompt_i2i)
        + "\n\n"
        + section("prompt_t2i", snap.prompt_t2i)
    )


@router.post("/families/assist")
def assist(body: AssistRequest, conn: Conn) -> StreamingResponse:
    cfg = settings_repo.get_lmstudio(conn)
    if not cfg["lmstudio_url"]:
        raise HTTPException(status_code=409, detail="LMStudio base_url is not configured")

    row = settings_repo.get_lm_model(conn, body.model)
    if row is None or not row["enabled"]:
        raise HTTPException(status_code=409, detail=f"model {body.model!r} is not enabled")
    if not row["tool_use"]:
        raise HTTPException(status_code=409, detail=f"model {body.model!r} does not support tool use")

    endpoint = {
        "server_root": cfg["lmstudio_url"],
        "api_key": cfg["lmstudio_api_key"],
    }

    def _stream_pass(user_input, prev_id):
        """Run one /v1/responses pass and yield (sse_event, function_call_outputs, response_id)."""
        for event in lmstudio_client.chat_responses_stream(
            endpoint=endpoint,
            model=body.model,
            instructions=ASSIST_SYSTEM_PROMPT,
            user_input=user_input,
            tools=ASSIST_TOOLS,
            previous_response_id=prev_id,
        ):
            etype = event["type"]
            if etype == "delta":
                yield ("sse", {"type": "delta", "content": event["content"]}, "")
            elif etype == "mcp_status":
                yield ("sse", {
                    "type": "tool_status",
                    "tool": event.get("tool", ""),
                    "status": event.get("status", ""),
                }, "")
            elif etype == "function_call":
                tool_name = event.get("name") or ""
                field = ASSIST_FIELD_BY_TOOL.get(tool_name)
                if field is not None:
                    content = event.get("arguments", {}).get("content", "")
                    yield ("sse", {"type": "artifact", "field": field, "content": content}, "")
                yield ("call", {
                    "type": "function_call_output",
                    "call_id": event.get("call_id", ""),
                    "output": "ok",
                }, "")
            elif etype == "completed":
                yield ("done", {}, event.get("response_id", ""))

    def gen():
        user_input: Any = f"{_format_snapshot(body.current_state)}\n\n---\n{body.message}"
        prev_id = body.previous_response_id
        last_response_id = prev_id or ""
        try:
            for _ in range(8):  # cap follow-up loops
                pending_outputs: list[dict] = []
                had_call = False
                completed = False
                for kind, payload, rid in _stream_pass(user_input, prev_id):
                    if kind == "sse":
                        yield _assist_sse(payload)
                    elif kind == "call":
                        pending_outputs.append(payload)
                        had_call = True
                    elif kind == "done":
                        if rid:
                            last_response_id = rid
                        completed = True
                if not completed:
                    break
                if not had_call:
                    break
                user_input = pending_outputs
                prev_id = last_response_id
        except lmstudio_client.LmError as exc:
            yield _assist_sse({"type": "error", "detail": str(exc)})
            return
        yield _assist_sse({"type": "done", "response_id": last_response_id})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.put("/families/{family_id}", response_model=FamilyOut)
def update_family(family_id: str, body: FamilyUpdate, conn: Conn):
    try:
        row = library_repo.update_family(conn, family_id, **body.model_dump())
    except sqlite3.IntegrityError as exc:
        raise _conflict(exc) from exc
    if row is None:
        raise _not_found("family", family_id)
    return row


@router.delete("/families/{family_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_family(family_id: str, conn: Conn):
    try:
        deleted = library_repo.delete_family(conn, family_id)
    except sqlite3.IntegrityError as exc:
        raise _conflict(exc) from exc
    if not deleted:
        raise _not_found("family", family_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/models", response_model=list[ModelOut])
def list_models(conn: Conn, family_id: str | None = None, q: str | None = None):
    return library_repo.list_models(conn, family_id=family_id, q=q)


@router.get("/models/{name}", response_model=ModelOut)
def get_model(name: str, conn: Conn):
    row = library_repo.get_model(conn, name)
    if row is None:
        raise _not_found("model", name)
    return row


@router.post("/models", response_model=ModelOut, status_code=status.HTTP_201_CREATED)
def create_model(body: ModelCreate, conn: Conn):
    try:
        return library_repo.create_model(conn, **_dump(body))
    except sqlite3.IntegrityError as exc:
        raise _conflict(exc) from exc


@router.put("/models/{name}", response_model=ModelOut)
def update_model(name: str, body: ModelUpdate, conn: Conn):
    try:
        row = library_repo.update_model(conn, name, **_dump(body))
    except sqlite3.IntegrityError as exc:
        raise _conflict(exc) from exc
    if row is None:
        raise _not_found("model", name)
    return row


@router.delete("/models/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_model(name: str, conn: Conn):
    try:
        deleted = library_repo.delete_model(conn, name)
    except sqlite3.IntegrityError as exc:
        raise _conflict(exc) from exc
    if not deleted:
        raise _not_found("model", name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/loras", response_model=list[LoraOut])
def list_loras(
    conn: Conn,
    family_id: str | None = None,
    tag: str | None = None,
    q: str | None = None,
):
    return library_service.list_loras(conn, family_id=family_id, tag=tag, q=q)


@router.get("/loras/{name}", response_model=LoraOut)
def get_lora(name: str, conn: Conn):
    row = library_service.get_lora(conn, name)
    if row is None:
        raise _not_found("lora", name)
    return row


@router.post("/loras", response_model=LoraOut, status_code=status.HTTP_201_CREATED)
def create_lora(body: LoraCreate, conn: Conn):
    try:
        return library_service.create_lora(conn, **_dump(body))
    except sqlite3.IntegrityError as exc:
        raise _conflict(exc) from exc
    except embedder.EmbedderError as exc:
        raise _embedder_failure(exc) from exc


@router.put("/loras/{name}", response_model=LoraOut)
def update_lora(name: str, body: LoraUpdate, conn: Conn):
    try:
        row = library_service.update_lora(conn, name, **_dump(body))
    except sqlite3.IntegrityError as exc:
        raise _conflict(exc) from exc
    except embedder.EmbedderError as exc:
        raise _embedder_failure(exc) from exc
    if row is None:
        raise _not_found("lora", name)
    return row


@router.delete("/loras/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lora(name: str, conn: Conn):
    deleted = library_service.delete_lora(conn, name)
    if not deleted:
        raise _not_found("lora", name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
