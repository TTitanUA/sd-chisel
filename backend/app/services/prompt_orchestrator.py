"""Two-step generate-prompt flow.

Owns the only place that calls both ``lm_client`` and ``retriever``. Lives
above ``services/`` peers because it composes them; nothing else imports it
except ``app.api.prompt``.

Comfy sessions follow the same intent + retrieval + composition shape but
emit a per-session ``GeneratedPayload`` (JSON object keyed by slot label)
instead of the legacy ``GeneratedPrompt = {positive, negative, loras}``.
The branch lives in :func:`_generate_inner`; legacy i2i / t2i sessions
keep the original code path verbatim.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.models.prompts import GeneratedPrompt, IntentList
from app.services import (
    comfy_payload,
    comfy_slot_map_service,
    llm_log,
    lmstudio_client,
    prompt_builder,
    retriever,
)
from app.storage import (
    comfy_workflow_repo,
    library_repo,
    session_repo,
    settings_repo,
    source_image_repo,
)

_M = TypeVar("_M", bound=BaseModel)

CHAT_HISTORY_LIMIT = 10
RETRIEVAL_TOP_K = 12
RETRIEVAL_GLOBAL_CAP = 20


class PreconditionError(Exception):
    """Raised when input state cannot be turned into a valid LLM call.
    The API layer maps this to HTTP 409.
    """


def _extract_json_object(text: str) -> str:
    """Walk for the first balanced {...} block. Used as a recovery for models
    that wrap JSON in chatty prose."""
    start = text.find("{")
    if start < 0:
        raise lmstudio_client.LmError("shape", "no JSON object in LLM output")
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise lmstudio_client.LmError("shape", "unbalanced JSON object in LLM output")


def _parse_json(text: str, model_cls: type[_M]) -> _M:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        raw = json.loads(_extract_json_object(text))
    try:
        return model_cls.model_validate(raw)
    except ValidationError as exc:
        raise lmstudio_client.LmError("shape", f"schema mismatch: {exc.errors()[:3]}") from exc


def _last_n_messages(conn: sqlite3.Connection, session_id: str, n: int) -> list[dict[str, Any]]:
    msgs = session_repo.list_messages(conn, session_id=session_id)
    return msgs[-n:]


def _coerce_negative(prompt: GeneratedPrompt, *, use_negative: bool) -> GeneratedPrompt:
    neg = prompt.negative
    if not use_negative:
        if neg is None or (isinstance(neg, str) and neg.strip() == ""):
            return prompt.model_copy(update={"negative": None})
        raise lmstudio_client.LmError(
            "shape", "use_negative=false but model returned a non-empty negative",
        )
    if neg is None or not str(neg).strip():
        raise lmstudio_client.LmError(
            "shape", "use_negative=true but model returned null/empty negative",
        )
    return prompt


def generate(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    endpoint: dict[str, Any],
    prompt_model: str,
    brief: str | None = None,
    sampling: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with llm_log.run_context():
        return _generate_inner(
            conn,
            session_id=session_id,
            endpoint=endpoint,
            prompt_model=prompt_model,
            brief=brief,
            sampling=sampling,
        )


def _generate_inner(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    endpoint: dict[str, Any],
    prompt_model: str,
    brief: str | None = None,
    sampling: dict[str, Any] | None = None,
) -> dict[str, Any]:
    session = session_repo.get_session_with_pinned(conn, session_id)
    if session is None:
        raise PreconditionError(f"session not found: {session_id}")

    if session.get("session_type") == "comfy":
        return _generate_comfy(
            conn,
            session=session,
            endpoint=endpoint,
            prompt_model=prompt_model,
            brief=brief,
            sampling=sampling,
        )
    return _generate_legacy(
        conn,
        session=session,
        endpoint=endpoint,
        prompt_model=prompt_model,
        brief=brief,
        sampling=sampling,
    )


def _resolve_family_guide(
    conn: sqlite3.Connection,
    *,
    model_name: str | None,
    mode: str,
) -> tuple[str | None, str, str | None]:
    """Resolve ``(family_id, family_prompt_guide, model_description)`` for a
    session given its model and inferred mode. The guide already has the
    mode-specific suffix appended when the family provides one. Falls
    back to a generic per-mode guide when the session has no model
    selected or the chosen model has no family with a guide.
    """
    family_id: str | None = None
    family_prompt_guide = ""
    model_description: str | None = None
    if model_name:
        model_row = library_repo.get_model(conn, model_name)
        if model_row is not None:
            family_id = model_row["family_id"]
            model_description = model_row.get("description")
            family_row = library_repo.get_family(conn, family_id)
            if family_row is not None:
                family_prompt_guide = family_row["prompt_guide"]
                # Append the mode-specific guide when the family provides one.
                # Spec §4.3: composition receives prompt_guide PLUS the
                # relevant prompt_i2i / prompt_t2i.
                mode_key = "prompt_i2i" if mode == "i2i" else "prompt_t2i"
                mode_guide = (family_row[mode_key] or "").strip()
                if mode_guide:
                    base = family_prompt_guide.strip()
                    family_prompt_guide = (
                        f"{base}\n\n{mode_guide}" if base else mode_guide
                    )
    if not family_prompt_guide:
        kind = "image-to-image" if mode == "i2i" else "text-to-image"
        family_prompt_guide = (
            f"You are writing a Stable Diffusion {kind} prompt. Be "
            "concrete and concise. Use comma-separated tags."
        )
    return family_id, family_prompt_guide, model_description


def _candidates_with_pinned(
    conn: sqlite3.Connection,
    *,
    bundle: dict[str, Any],
    session: dict[str, Any],
    show_hidden: bool,
) -> list[dict[str, Any]]:
    """Merge the session's pinned LoRAs into the retrieval candidates,
    de-duplicated by name. Hidden pinned LoRAs are dropped unless the
    global ``show_hidden`` is on — same rule as for retrieved candidates,
    so the LLM never sees a hidden LoRA when the toggle is off."""
    pinned = session.get("pinned_loras") or []
    pinned_names = [p["lora_name"] for p in pinned]
    pinned_rows = library_repo.get_loras_by_names(
        conn, pinned_names, include_hidden=show_hidden,
    )
    seen = {c["name"] for c in bundle["candidates"]}
    out = list(bundle["candidates"])
    for row in pinned_rows:
        if row["name"] not in seen:
            out.append(row)
            seen.add(row["name"])
    return out


def _generate_legacy(
    conn: sqlite3.Connection,
    *,
    session: dict[str, Any],
    endpoint: dict[str, Any],
    prompt_model: str,
    brief: str | None,
    sampling: dict[str, Any] | None,
) -> dict[str, Any]:
    session_id = session["id"]
    mode = session.get("session_type") or "i2i"

    sources = source_image_repo.list_for_session(conn, session_id)
    main_summary: str | None
    if mode == "t2i":
        # t2i has no main image — every source row is a reference.
        # Generation may also run with zero source images (pure
        # text-to-image). The composition system prompt picks up
        # # Mode: t2i and the family's prompt_t2i guide downstream.
        main_summary = None
        reference_summaries = [
            (f"Image_{s['image_number']}", s["analysis"])
            for s in sources
            if (s.get("analysis") or "").strip()
        ]
    else:
        main_image = next((s for s in sources if s["is_main"]), None)
        if main_image is None or not (main_image.get("analysis") or "").strip():
            raise PreconditionError(
                "session has no main source image with a completed analysis yet",
            )
        main_summary = main_image["analysis"]
        reference_summaries = [
            (f"Image_{s['image_number']}", s["analysis"])
            for s in sources
            if not s["is_main"] and (s.get("analysis") or "").strip()
        ]

    family_id, family_prompt_guide, model_description = _resolve_family_guide(
        conn, model_name=session.get("model_name"), mode=mode,
    )

    # When a brief is provided (chat tool path), the converged user intent
    # *is* the brief — chat history is intentionally skipped to avoid noise.
    chat_messages = (
        [] if (brief and brief.strip())
        else _last_n_messages(conn, session_id, CHAT_HISTORY_LIMIT)
    )
    show_hidden = settings_repo.get_privacy(conn)["show_hidden"]
    distinct_tags = library_repo.list_distinct_tags(conn, include_hidden=show_hidden)

    # ---- Step 1: intents -------------------------------------------------
    intent_messages = prompt_builder.build_intent_messages(
        mode=mode,
        vl_summary=main_summary,
        chat_messages=chat_messages,
        distinct_tags=distinct_tags,
        reference_summaries=reference_summaries,
        brief=brief,
    )
    intent_raw = lmstudio_client.chat_complete(
        endpoint=endpoint,
        model=prompt_model,
        messages=intent_messages,
        sampling=sampling,
    )
    intents_obj = _parse_json(intent_raw, IntentList)

    # ---- Step 2: retrieval ----------------------------------------------
    bundle = retriever.retrieve_for_intents(
        conn,
        intents=[i.model_dump() for i in intents_obj.intents],
        k=RETRIEVAL_TOP_K,
        family_id=family_id,
        global_cap=RETRIEVAL_GLOBAL_CAP,
        include_hidden=show_hidden,
    )
    candidates = _candidates_with_pinned(
        conn, bundle=bundle, session=session, show_hidden=show_hidden,
    )

    # ---- Step 3: composition --------------------------------------------
    comp_messages = prompt_builder.build_composition_messages(
        mode=mode,
        family_prompt_guide=family_prompt_guide,
        model_description=model_description,
        candidates=candidates,
        vl_summary=main_summary,
        chat_messages=chat_messages,
        use_negative=session["use_negative"],
        reference_summaries=reference_summaries,
        brief=brief,
    )
    comp_raw = lmstudio_client.chat_complete(
        endpoint=endpoint,
        model=prompt_model,
        messages=comp_messages,
        sampling=sampling,
    )
    prompt_obj = _parse_json(comp_raw, GeneratedPrompt)
    prompt_obj = _coerce_negative(prompt_obj, use_negative=session["use_negative"])

    # ---- Persist ---------------------------------------------------------
    intents_dump = [i.model_dump() for i in intents_obj.intents]
    retrieved_dump = bundle["per_intent"]
    row = session_repo.append_prompt(
        conn,
        session_id=session_id,
        positive=prompt_obj.positive,
        negative=prompt_obj.negative,
        loras=[lora.model_dump() for lora in prompt_obj.loras],
        intents=intents_dump,
        retrieved=retrieved_dump,
        brief=brief,
    )

    return {
        "prompt_id": row["id"],
        "prompt": prompt_obj.model_dump(),
        "payload": None,
        "intents": intents_dump,
        "retrieved": retrieved_dump,
        "brief": brief,
        "created_at": row["created_at"],
    }


def _resolve_comfy_slot_map(
    conn: sqlite3.Connection, session: dict[str, Any],
) -> dict[str, Any]:
    """Load the bound workflow's slot map for a comfy session, upgraded
    to v2 shape. Raises :class:`PreconditionError` when the session has
    no workflow bound or the workflow has been deleted out from under it.
    """
    workflow_id = session.get("comfy_workflow_id")
    if not workflow_id:
        raise PreconditionError("comfy session is not bound to a workflow")
    workflow = comfy_workflow_repo.get_workflow(conn, workflow_id)
    if workflow is None:
        raise PreconditionError(f"bound workflow not found: {workflow_id}")
    candidates = comfy_slot_map_service.compute_candidates(
        conn=conn, graph=workflow["graph"],
    )
    return comfy_slot_map_service.upgrade_slot_map(
        raw=workflow.get("slot_map"), candidates=candidates,
    )


def _generate_comfy(
    conn: sqlite3.Connection,
    *,
    session: dict[str, Any],
    endpoint: dict[str, Any],
    prompt_model: str,
    brief: str | None,
    sampling: dict[str, Any] | None,
) -> dict[str, Any]:
    """Comfy-session composition: produces a ``GeneratedPayload`` (JSON
    keyed by slot label, plus a ``__loras`` side-channel) instead of
    the legacy ``GeneratedPrompt``. No graph patching, no execution —
    that's Phase 3.
    """
    session_id = session["id"]
    slot_map_v2 = _resolve_comfy_slot_map(conn, session)
    slots: list[dict[str, Any]] = list(slot_map_v2.get("slots") or [])
    mode = comfy_slot_map_service.infer_mode(slot_map_v2)

    sources = source_image_repo.list_for_session(conn, session_id)
    # Comfy sessions don't gate on a main image — the user_image
    # binding is consumed by the patcher (Phase 3), not the LLM. The
    # source-image analyses still feed the composition message when
    # available so the LLM can write coherent slot text against the
    # actual subject.
    main_image = next((s for s in sources if s["is_main"]), None)
    main_summary = (
        main_image["analysis"]
        if main_image and (main_image.get("analysis") or "").strip()
        else None
    )
    reference_summaries = [
        (f"Image_{s['image_number']}", s["analysis"])
        for s in sources
        if (not s["is_main"] or main_summary is None)
        and (s.get("analysis") or "").strip()
    ]

    family_id, family_prompt_guide, model_description = _resolve_family_guide(
        conn, model_name=session.get("model_name"), mode=mode,
    )

    chat_messages = (
        [] if (brief and brief.strip())
        else _last_n_messages(conn, session_id, CHAT_HISTORY_LIMIT)
    )
    show_hidden = settings_repo.get_privacy(conn)["show_hidden"]
    distinct_tags = library_repo.list_distinct_tags(
        conn, include_hidden=show_hidden,
    )

    # ---- Step 1: intents (same as legacy — drives LoRA retrieval) -------
    intent_messages = prompt_builder.build_intent_messages(
        mode=mode,
        vl_summary=main_summary,
        chat_messages=chat_messages,
        distinct_tags=distinct_tags,
        reference_summaries=reference_summaries,
        brief=brief,
    )
    intent_raw = lmstudio_client.chat_complete(
        endpoint=endpoint,
        model=prompt_model,
        messages=intent_messages,
        sampling=sampling,
    )
    intents_obj = _parse_json(intent_raw, IntentList)

    # ---- Step 2: retrieval ----------------------------------------------
    bundle = retriever.retrieve_for_intents(
        conn,
        intents=[i.model_dump() for i in intents_obj.intents],
        k=RETRIEVAL_TOP_K,
        family_id=family_id,
        global_cap=RETRIEVAL_GLOBAL_CAP,
        include_hidden=show_hidden,
    )
    candidates = _candidates_with_pinned(
        conn, bundle=bundle, session=session, show_hidden=show_hidden,
    )

    # ---- Step 3: composition (dynamic schema) ---------------------------
    schema_hint = comfy_payload.build_schema_hint(slots)
    slot_context_block = comfy_payload.build_slot_context_block(slots)
    comp_messages = prompt_builder.build_comfy_composition_messages(
        mode=mode,
        family_prompt_guide=family_prompt_guide,
        model_description=model_description,
        candidates=candidates,
        vl_summary=main_summary,
        chat_messages=chat_messages,
        reference_summaries=reference_summaries,
        brief=brief,
        slot_context_block=slot_context_block,
        schema_hint=schema_hint,
    )
    comp_raw = lmstudio_client.chat_complete(
        endpoint=endpoint,
        model=prompt_model,
        messages=comp_messages,
        sampling=sampling,
    )
    try:
        raw_payload = json.loads(comp_raw)
    except json.JSONDecodeError:
        raw_payload = json.loads(_extract_json_object(comp_raw))
    try:
        validated = comfy_payload.validate_payload(raw_payload, slots)
    except comfy_payload.PayloadValidationError as exc:
        raise lmstudio_client.LmError("shape", str(exc)) from exc
    payload_only, loras_list = comfy_payload.split_loras(validated)

    # ---- Persist ---------------------------------------------------------
    intents_dump = [i.model_dump() for i in intents_obj.intents]
    retrieved_dump = bundle["per_intent"]
    row = session_repo.append_prompt(
        conn,
        session_id=session_id,
        loras=loras_list,
        intents=intents_dump,
        retrieved=retrieved_dump,
        brief=brief,
        payload=payload_only,
    )

    return {
        "prompt_id": row["id"],
        "prompt": None,
        "payload": payload_only,
        "intents": intents_dump,
        "retrieved": retrieved_dump,
        "brief": brief,
        "created_at": row["created_at"],
    }
