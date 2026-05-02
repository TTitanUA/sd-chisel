from __future__ import annotations

import json
import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from starlette.responses import StreamingResponse

from app.api.deps import get_conn
from app.models.library import (
    AssistFieldsSnapshot,
    AssistRequest,
    CivitaiImportResult,
    FamilyCreate,
    FamilyOut,
    FamilyUpdate,
    HiddenPatch,
    LoraAssistFieldsSnapshot,
    LoraAssistRequest,
    LoraCreate,
    LoraOut,
    LoraUpdate,
    ModelCreate,
    ModelOut,
    ModelUpdate,
    RenameRequest,
)
from app.services import civitai, library_service, lmstudio_client, lora_reindex
from app.storage import library_repo, settings_repo

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

router = APIRouter(prefix="/api/library", tags=["library"])


def _conflict(exc: sqlite3.IntegrityError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _not_found(kind: str, key: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{kind} not found: {key}")


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


def _format_snapshot(snap: AssistFieldsSnapshot) -> str:
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


def _validate_assist_model(conn, model_name: str):
    """Shared validation for assist endpoints."""
    cfg = settings_repo.get_lmstudio(conn)
    if not cfg["lmstudio_url"]:
        raise HTTPException(status_code=409, detail="LMStudio base_url is not configured")
    row = settings_repo.get_lm_model(conn, model_name)
    if row is None or not row["enabled"]:
        raise HTTPException(status_code=409, detail=f"model {model_name!r} is not enabled")
    if not row["tool_use"]:
        raise HTTPException(status_code=409, detail=f"model {model_name!r} does not support tool use")
    return {
        "server_root": cfg["lmstudio_url"],
        "api_key": cfg["lmstudio_api_key"],
    }


def _assist_stream_response(
    *,
    endpoint: dict,
    model: str,
    system_prompt: str,
    tools: list[dict],
    artifact_extractor,
    user_text: str,
    previous_response_id: str | None,
) -> StreamingResponse:
    """Build an SSE StreamingResponse for any assist endpoint.

    ``artifact_extractor(tool_name, arguments) -> (field, content) | None``
    maps a function-call event to an artifact SSE payload.
    """

    def _stream_pass(user_input, prev_id):
        for event in lmstudio_client.chat_responses_stream(
            endpoint=endpoint,
            model=model,
            instructions=system_prompt,
            user_input=user_input,
            tools=tools,
            previous_response_id=prev_id,
        ):
            etype = event["type"]
            if etype == "delta":
                yield ("sse", {"type": "delta", "content": event["content"]}, "")
            elif etype == "tool_status":
                yield ("sse", {
                    "type": "tool_status",
                    "tool": event.get("tool", ""),
                    "status": event.get("status", ""),
                }, "")
            elif etype == "function_call":
                tool_name = event.get("name") or ""
                args = event.get("arguments", {})
                pair = artifact_extractor(tool_name, args)
                if pair is not None:
                    yield ("sse", {"type": "artifact", "field": pair[0], "content": pair[1]}, "")
                yield ("call", {
                    "type": "function_call_output",
                    "call_id": event.get("call_id", ""),
                    "output": "ok",
                }, "")
            elif etype == "completed":
                yield ("done", {}, event.get("response_id", ""))

    def gen():
        user_input: Any = user_text
        prev_id = previous_response_id
        last_response_id = prev_id or ""
        try:
            for _ in range(8):
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


def _family_artifact(tool_name: str, args: dict):
    field = ASSIST_FIELD_BY_TOOL.get(tool_name)
    if field is None:
        return None
    return (field, args.get("content", ""))


@router.post("/families/assist")
def assist(body: AssistRequest, conn: Conn) -> StreamingResponse:
    endpoint = _validate_assist_model(conn, body.model)
    return _assist_stream_response(
        endpoint=endpoint,
        model=body.model,
        system_prompt=ASSIST_SYSTEM_PROMPT,
        tools=ASSIST_TOOLS,
        artifact_extractor=_family_artifact,
        user_text=f"{_format_snapshot(body.current_state)}\n\n---\n{body.message}",
        previous_response_id=body.previous_response_id,
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


@router.patch("/families/{family_id}/hidden", response_model=FamilyOut)
def patch_family_hidden(family_id: str, body: HiddenPatch, conn: Conn):
    row = library_repo.set_family_hidden(conn, family_id, hidden=body.hidden)
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


@router.post("/models/{name}/rename", response_model=ModelOut)
def rename_model(name: str, body: RenameRequest, conn: Conn):
    try:
        row = library_repo.rename_model(conn, name, body.new_name)
    except sqlite3.IntegrityError as exc:
        raise _conflict(exc) from exc
    if row is None:
        raise _not_found("model", name)
    return row


@router.patch("/models/{name}/hidden", response_model=ModelOut)
def patch_model_hidden(name: str, body: HiddenPatch, conn: Conn):
    row = library_repo.set_model_hidden(conn, name, hidden=body.hidden)
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


LORA_ASSIST_SYSTEM_PROMPT = (
    "You are filling in metadata for a LoRA (Low-Rank Adaptation) model used "
    "in image generation. The metadata is stored in a library and used by "
    "ANOTHER LLM that selects and configures LoRAs for image prompts.\n\n"
    "Fields you can update independently — one tool per field. Set as many "
    "as you can confidently extract from the user's message or fetched docs. "
    "Skip a field rather than guess.\n\n"
    "[name] — filename slug, [a-zA-Z0-9_.-], no spaces, no extension. "
    "Only valid in CREATE mode; in EDIT mode it is locked.\n"
    "  Tool: update_name(content).\n\n"
    "[display_name] — short human-readable name.\n"
    "  Tool: update_display_name(content).\n\n"
    "[description] — markdown describing what the LoRA does, when to use it, "
    "incompatibilities, prompting tips. The downstream prompt LLM reads this "
    "verbatim. Strict rules:\n"
    "  - No marketing prose, download stats, or licensing notes.\n"
    "  - No links, citations, or 'see docs at …' references.\n"
    "  - No emojis.\n"
    "  - No code examples or API snippets.\n"
    "  - No filler — write the rule directly.\n"
    "  Tool: update_description(content).\n\n"
    "[tags] — short lowercase categorical labels (style, character, concept, "
    "pose, clothing, background, lighting, etc.). Use hyphens not spaces.\n"
    "  Tool: update_tags(tags).\n\n"
    "[trigger_words] — exact tokens the LoRA was trained on. Required "
    "keywords. Do not invent. Leave empty if not documented.\n"
    "  Tool: update_trigger_words(trigger_words).\n\n"
    "[family_id] — which base model family this LoRA is for. MUST be one of "
    "the available family IDs listed in the editor state. Do not invent.\n"
    "  Tool: update_family_id(content).\n\n"
    "[recommended_weight] — typical weight, range -2.0 to 2.0. Most LoRAs "
    "are 0.5–0.9.\n"
    "  Tool: update_recommended_weight(weight).\n\n"
    "[author], [version], [source_url] — provenance fields.\n"
    "  Tools: update_author(content), update_version(content), "
    "update_source_url(content).\n\n"
    "When the user provides a documentation URL (Civitai, HuggingFace, etc.), "
    "use your browser tools to fetch the page and extract: display name, "
    "version, author, description, prompting tips, trigger words, "
    "recommended weight. Also set source_url to the URL itself.\n\n"
    "The user's message will be preceded by a block with the current editor "
    "state, the list of available families, and the mode (CREATE or EDIT). "
    "Call update_* tools with the FULL new value (not a diff)."
)

LORA_ASSIST_TOOLS_META: dict[str, dict[str, str]] = {
    "update_name": {"field": "name", "arg": "content"},
    "update_display_name": {"field": "display_name", "arg": "content"},
    "update_description": {"field": "description", "arg": "content"},
    "update_tags": {"field": "tags", "arg": "tags"},
    "update_trigger_words": {"field": "trigger_words", "arg": "trigger_words"},
    "update_family_id": {"field": "family_id", "arg": "content"},
    "update_recommended_weight": {"field": "recommended_weight", "arg": "weight"},
    "update_author": {"field": "author", "arg": "content"},
    "update_version": {"field": "version", "arg": "content"},
    "update_source_url": {"field": "source_url", "arg": "content"},
}


def _array_tool(name: str, description: str, param_name: str) -> dict:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": {
                param_name: {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": f"Complete list of {param_name}.",
                },
            },
            "required": [param_name],
            "additionalProperties": False,
        },
    }


def _number_tool(
    name: str, description: str, param_name: str, minimum: float, maximum: float,
) -> dict:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": {
                param_name: {
                    "type": "number",
                    "minimum": minimum,
                    "maximum": maximum,
                },
            },
            "required": [param_name],
            "additionalProperties": False,
        },
    }


LORA_ASSIST_TOOLS = [
    _function_tool(
        "update_name",
        "Set the LoRA filename slug (no extension). Only call in CREATE mode.",
    ),
    _function_tool("update_display_name", "Set the display name."),
    _function_tool(
        "update_description", "Update the LoRA description (markdown).",
    ),
    _array_tool("update_tags", "Replace the full tags list.", "tags"),
    _array_tool(
        "update_trigger_words",
        "Replace the full trigger-words list.",
        "trigger_words",
    ),
    _function_tool(
        "update_family_id",
        "Set the base family ID. Must match one of the available family IDs.",
    ),
    _number_tool(
        "update_recommended_weight",
        "Set the recommended weight (typical 0.5–0.9).",
        "weight",
        -2.0,
        2.0,
    ),
    _function_tool("update_author", "Set the LoRA author."),
    _function_tool("update_version", "Set the LoRA version string."),
    _function_tool(
        "update_source_url",
        "Set the source URL (Civitai, HuggingFace, etc.).",
    ),
    {"type": "mcp", "server_label": "playwright"},
]


def _format_lora_snapshot(snap: LoraAssistFieldsSnapshot) -> str:
    tags_str = ", ".join(snap.tags) if snap.tags else "(none)"
    tw_str = ", ".join(snap.trigger_words) if snap.trigger_words else "(none)"
    desc = snap.description.strip() or "(empty)"
    weight_str = (
        f"{snap.recommended_weight}" if snap.recommended_weight is not None else "(empty)"
    )

    fam_lines = "\n".join(
        f"- {f.id}: {f.display_name}" for f in snap.available_families
    ) or "(none)"

    mode = "EDIT (the [name] field is locked, do not call update_name)" if snap.is_edit_mode else "CREATE"

    return (
        f"Mode: {mode}\n\n"
        f"Available families:\n{fam_lines}\n\n"
        "Current editor state:\n"
        f"[name]\n{snap.name or '(empty)'}\n\n"
        f"[display_name]\n{snap.display_name or '(empty)'}\n\n"
        f"[description]\n{desc}\n\n"
        f"[tags]\n{tags_str}\n\n"
        f"[trigger_words]\n{tw_str}\n\n"
        f"[family_id]\n{snap.family_id or '(empty)'}\n\n"
        f"[recommended_weight]\n{weight_str}\n\n"
        f"[author]\n{snap.author or '(empty)'}\n\n"
        f"[version]\n{snap.version or '(empty)'}\n\n"
        f"[source_url]\n{snap.source_url or '(empty)'}"
    )


def _lora_artifact(tool_name: str, args: dict):
    meta = LORA_ASSIST_TOOLS_META.get(tool_name)
    if meta is None:
        return None
    value = args.get(meta["arg"])
    if value is None:
        content = ""
    elif isinstance(value, bool):
        content = "true" if value else "false"
    elif isinstance(value, (list, dict)):
        content = json.dumps(value, ensure_ascii=False)
    elif isinstance(value, (int, float)):
        content = json.dumps(value)
    else:
        content = str(value)
    return (meta["field"], content)


@router.get("/loras/civitai-import", response_model=CivitaiImportResult)
def civitai_import(ref: str):
    try:
        model_id, version_id = civitai.parse_civitai_ref(ref)
        return civitai.fetch_lora_metadata(model_id, version_id)
    except civitai.CivitaiError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/loras/assist")
def lora_assist(body: LoraAssistRequest, conn: Conn) -> StreamingResponse:
    endpoint = _validate_assist_model(conn, body.model)
    return _assist_stream_response(
        endpoint=endpoint,
        model=body.model,
        system_prompt=LORA_ASSIST_SYSTEM_PROMPT,
        tools=LORA_ASSIST_TOOLS,
        artifact_extractor=_lora_artifact,
        user_text=f"{_format_lora_snapshot(body.current_state)}\n\n---\n{body.message}",
        previous_response_id=body.previous_response_id,
    )


@router.get("/loras", response_model=list[LoraOut])
def list_loras(
    conn: Conn,
    family_id: str | None = None,
    tag: str | None = None,
    q: str | None = None,
):
    show_hidden = settings_repo.get_privacy(conn)["show_hidden"]
    return library_service.list_loras(
        conn, family_id=family_id, tag=tag, q=q, include_hidden=show_hidden,
    )


@router.get("/loras/{name}", response_model=LoraOut)
def get_lora(name: str, conn: Conn):
    row = library_service.get_lora(conn, name)
    if row is None:
        raise _not_found("lora", name)
    return row


@router.post("/loras", response_model=LoraOut, status_code=status.HTTP_201_CREATED)
def create_lora(body: LoraCreate, conn: Conn):
    try:
        row = library_service.create_lora(conn, **_dump(body))
    except sqlite3.IntegrityError as exc:
        raise _conflict(exc) from exc
    lora_reindex.submit_reindex_lora(row["name"])
    return row


@router.put("/loras/{name}", response_model=LoraOut)
def update_lora(name: str, body: LoraUpdate, conn: Conn):
    try:
        row = library_service.update_lora(conn, name, **_dump(body))
    except sqlite3.IntegrityError as exc:
        raise _conflict(exc) from exc
    if row is None:
        raise _not_found("lora", name)
    lora_reindex.submit_reindex_lora(name)
    return row


@router.post("/loras/{name}/rename", response_model=LoraOut)
def rename_lora(name: str, body: RenameRequest, conn: Conn):
    try:
        row = library_service.rename_lora(conn, name, body.new_name)
    except sqlite3.IntegrityError as exc:
        raise _conflict(exc) from exc
    if row is None:
        raise _not_found("lora", name)
    return row


@router.patch("/loras/{name}/hidden", response_model=LoraOut)
def patch_lora_hidden(name: str, body: HiddenPatch, conn: Conn):
    row = library_repo.set_lora_hidden(conn, name, hidden=body.hidden)
    if row is None:
        raise _not_found("lora", name)
    return library_service.get_lora(conn, name)


@router.delete("/loras/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lora(name: str, conn: Conn):
    deleted = library_service.delete_lora(conn, name)
    if not deleted:
        raise _not_found("lora", name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
