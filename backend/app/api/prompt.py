"""HTTP layer for the chat-summary -> generate-prompt flow."""
from __future__ import annotations

import json
import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_conn
from app.models.prompts import (
    GeneratedPrompt,
    GeneratePromptRequest,
    GeneratePromptResponse,
    Intent,
    PromptOut,
    PromptsResponse,
    RetrievedIntent,
    SummarizeChatResponse,
    SummarizeContext,
    SummarizeImageView,
    SummarizePinnedLoraView,
)
from app.services import (
    action_settings,
    chat_summarizer,
    lmstudio_client,
    prompt_orchestrator,
    task_runner,
)
from app.storage import (
    library_repo,
    session_repo,
    settings_repo,
    source_image_repo,
)

Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

router = APIRouter(tags=["prompt"])


def _not_found(session_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"session not found: {session_id}",
    )


def _reject_if_indexing() -> None:
    """409 while any reindex task is still running. The retriever depends on
    `vec_loras` being current; serving a prompt during a partial reindex
    would either miss recently-edited LoRAs or pick up rows that are about
    to be re-embedded."""
    try:
        reg = task_runner.get()
    except RuntimeError:
        return
    active = reg.find_active(
        lambda t: t.kind in ("reindex_lora", "reindex_all"),
    )
    if active:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "indexing_in_progress",
                "message": "LoRA index is updating — try again in a moment.",
                "task_ids": [t.id for t in active],
            },
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


def _resolve_endpoint_and_model(
    conn: sqlite3.Connection, session: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    cfg = settings_repo.get_lmstudio(conn)
    if not cfg["lmstudio_url"]:
        raise HTTPException(
            status_code=409, detail="LMStudio base_url is not configured",
        )
    model = _validated_prompt_model(conn, session.get("prompt_model_name"))
    return {
        "server_root": cfg["lmstudio_url"],
        "api_key": cfg["lmstudio_api_key"],
    }, model


def _build_summarize_context(
    conn: sqlite3.Connection, session: dict[str, Any],
) -> SummarizeContext:
    family_id: str | None = None
    family_display_name: str | None = None
    model_description: str | None = None
    if session.get("model_name"):
        model_row = library_repo.get_model(conn, session["model_name"])
        if model_row is not None:
            family_id = model_row["family_id"]
            model_description = model_row.get("description")
            fam = library_repo.get_family(conn, family_id) if family_id else None
            if fam is not None:
                family_display_name = fam["display_name"]

    pinned_rows = session_repo.list_pinned_loras(conn, session["id"])
    pinned_names = [p["lora_name"] for p in pinned_rows]
    lora_rows = {
        lr["name"]: lr
        for lr in library_repo.get_loras_by_names(conn, pinned_names)
    }
    pinned_views: list[SummarizePinnedLoraView] = []
    for p in pinned_rows:
        weight = p.get("weight_override")
        if weight is None:
            row = lora_rows.get(p["lora_name"])
            weight = row.get("recommended_weight") if row else None
        pinned_views.append(SummarizePinnedLoraView(
            name=p["lora_name"], weight=weight,
        ))

    sources = source_image_repo.list_for_session(conn, session["id"])
    main = next((s for s in sources if s["is_main"]), None)
    main_view: SummarizeImageView | None = None
    if main is not None and (main.get("analysis") or "").strip():
        main_view = SummarizeImageView(
            label=f"Image_{main['image_number']}",
            analysis=main["analysis"],
        )
    refs = [
        SummarizeImageView(
            label=f"Image_{s['image_number']}",
            analysis=s["analysis"],
        )
        for s in sources
        if not s["is_main"] and (s.get("analysis") or "").strip()
    ]

    return SummarizeContext(
        mode=session.get("session_type") or "i2i",
        model_name=session.get("model_name"),
        model_description=model_description,
        family_id=family_id,
        family_display_name=family_display_name,
        pinned_loras=pinned_views,
        use_negative=bool(session.get("use_negative", True)),
        main_image=main_view,
        reference_images=refs,
    )


@router.post(
    "/api/sessions/{session_id}/summarize-chat",
    response_model=SummarizeChatResponse,
)
def summarize_chat(session_id: str, conn: Conn) -> SummarizeChatResponse:
    session = session_repo.get_session(conn, session_id)
    if session is None:
        raise _not_found(session_id)
    endpoint, model = _resolve_endpoint_and_model(conn, session)
    sampling = action_settings.resolve_for_session(conn, session, "summarize")
    try:
        brief = chat_summarizer.summarize_session_chat(
            conn,
            session_id=session_id,
            endpoint=endpoint,
            prompt_model=model,
            sampling=sampling,
        )
    except lmstudio_client.LmError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    context = _build_summarize_context(conn, session)
    return SummarizeChatResponse(brief=brief, context=context)


@router.post(
    "/api/sessions/{session_id}/generate-prompt",
    response_model=GeneratePromptResponse,
)
def generate_prompt(
    session_id: str,
    conn: Conn,
    body: GeneratePromptRequest | None = None,
) -> GeneratePromptResponse:
    if body is None:
        body = GeneratePromptRequest()
    session = session_repo.get_session(conn, session_id)
    if session is None:
        raise _not_found(session_id)

    _reject_if_indexing()
    endpoint, model = _resolve_endpoint_and_model(conn, session)
    sampling = action_settings.resolve_for_session(conn, session, "generate")

    brief = (body.brief or "").strip() or None
    try:
        out = prompt_orchestrator.generate(
            conn,
            session_id=session_id,
            endpoint=endpoint,
            prompt_model=model,
            brief=brief,
            sampling=sampling,
        )
    except prompt_orchestrator.PreconditionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except lmstudio_client.LmError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if body.compact_history and brief:
        # Best-effort: if compaction fails we still return the prompt —
        # the user got their generation, the chat just isn't compacted.
        try:
            session_repo.compact_messages_with_summary(
                conn, session_id=session_id, brief=brief,
            )
        except sqlite3.DatabaseError:
            pass

    return GeneratePromptResponse(
        prompt_id=out["prompt_id"],
        prompt=GeneratedPrompt.model_validate(out["prompt"]),
        intents=[Intent.model_validate(i) for i in out["intents"]],
        retrieved=[RetrievedIntent.model_validate(r) for r in out["retrieved"]],
        brief=out.get("brief"),
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
        brief=row.get("brief"),
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
