from __future__ import annotations

import json
import sqlite3
from typing import Annotated

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
    "You are a prompt-guide writing assistant for generative image model families. "
    "Help the user write a prompt guide — a set of rules that the LLM will follow "
    "when generating prompts for this family in both text-to-image (t2i) and "
    "image-to-image (i2i) workflows.\n\n"
    "When the user provides documentation links, use your browser tools to navigate "
    "to the URL and read the content.\n\n"
    "When you have a draft or update of the prompt guide, output it inside "
    "<artifact> and </artifact> tags. The content between these tags will appear "
    "in the editor automatically. Do not just describe what you plan to write — "
    "produce the draft immediately.\n\n"
    "Keep the prompt guide concise and actionable. Focus on:\n"
    "- Tag syntax and formatting rules\n"
    "- Quality/style tokens specific to this family\n"
    "- Token limits or recommendations\n"
    "- LoRA interaction patterns\n"
    "- Negative prompt conventions\n"
    "- Any differences between t2i and i2i prompting for this family"
)

ARTIFACT_OPEN = "<artifact>"
ARTIFACT_CLOSE = "</artifact>"


def _assist_sse(payload: dict) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


class _ArtifactParser:
    """Detects <artifact>...</artifact> in a token stream.

    Text outside tags → delta events.
    Text inside tags → single artifact event on close.
    """

    def __init__(self) -> None:
        self._buf = ""
        self._inside = False
        self._art_buf = ""

    def feed(self, text: str) -> list[dict]:
        events: list[dict] = []
        self._buf += text
        while self._buf:
            if not self._inside:
                idx = self._buf.find(ARTIFACT_OPEN)
                if idx >= 0:
                    if idx > 0:
                        events.append({"type": "delta", "content": self._buf[:idx]})
                    self._buf = self._buf[idx + len(ARTIFACT_OPEN):]
                    self._inside = True
                    continue
                # keep potential partial tag at end
                for i in range(min(len(ARTIFACT_OPEN) - 1, len(self._buf)), 0, -1):
                    if self._buf.endswith(ARTIFACT_OPEN[:i]):
                        safe = self._buf[:-i]
                        if safe:
                            events.append({"type": "delta", "content": safe})
                        self._buf = self._buf[-i:]
                        return events
                events.append({"type": "delta", "content": self._buf})
                self._buf = ""
            else:
                idx = self._buf.find(ARTIFACT_CLOSE)
                if idx >= 0:
                    self._art_buf += self._buf[:idx]
                    events.append({"type": "artifact", "content": self._art_buf.strip()})
                    self._buf = self._buf[idx + len(ARTIFACT_CLOSE):]
                    self._inside = False
                    self._art_buf = ""
                    continue
                self._art_buf += self._buf
                self._buf = ""
        return events

    def flush(self) -> list[dict]:
        events: list[dict] = []
        if self._buf:
            events.append({"type": "delta", "content": self._buf})
        if self._art_buf:
            events.append({"type": "delta", "content": self._art_buf})
        self._buf = ""
        self._art_buf = ""
        return events


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

    def gen():
        parser = _ArtifactParser()
        try:
            for event in lmstudio_client.chat_native_stream(
                endpoint=endpoint,
                model=body.model,
                system_prompt=ASSIST_SYSTEM_PROMPT,
                user_input=body.message,
                integrations=["mcp/playwright"],
                previous_response_id=body.previous_response_id,
            ):
                etype = event["type"]
                if etype == "delta":
                    for ev in parser.feed(event["content"]):
                        yield _assist_sse(ev)
                elif etype == "tool_status":
                    yield _assist_sse(event)
                elif etype == "chat_end":
                    for ev in parser.flush():
                        yield _assist_sse(ev)
                    yield _assist_sse({
                        "type": "done",
                        "response_id": event.get("response_id", ""),
                    })
                    return
        except lmstudio_client.LmError as exc:
            for ev in parser.flush():
                yield _assist_sse(ev)
            yield _assist_sse({"type": "error", "detail": str(exc)})
            return
        for ev in parser.flush():
            yield _assist_sse(ev)
        yield _assist_sse({"type": "done", "response_id": ""})

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
