"""Two-step generate-prompt flow.

Owns the only place that calls both ``lm_client`` and ``retriever``. Lives
above ``services/`` peers because it composes them; nothing else imports it
except ``app.api.prompt``.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.models.prompts import GeneratedPrompt, IntentList
from app.services import llm_log, lmstudio_client, prompt_builder, retriever
from app.storage import library_repo, session_repo, settings_repo, source_image_repo

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
) -> dict[str, Any]:
    with llm_log.run_context():
        return _generate_inner(
            conn,
            session_id=session_id,
            endpoint=endpoint,
            prompt_model=prompt_model,
            brief=brief,
        )


def _generate_inner(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    endpoint: dict[str, Any],
    prompt_model: str,
    brief: str | None = None,
) -> dict[str, Any]:
    session = session_repo.get_session_with_pinned(conn, session_id)
    if session is None:
        raise PreconditionError(f"session not found: {session_id}")

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

    family_id: str | None = None
    family_prompt_guide = ""
    model_description: str | None = None
    if session.get("model_name"):
        model_row = library_repo.get_model(conn, session["model_name"])
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
                    family_prompt_guide = f"{base}\n\n{mode_guide}" if base else mode_guide
    if not family_prompt_guide:
        kind = "image-to-image" if mode == "i2i" else "text-to-image"
        family_prompt_guide = (
            f"You are writing a Stable Diffusion {kind} prompt. Be "
            "concrete and concise. Use comma-separated tags."
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

    # Merge pinned LoRAs into candidates (no double-include). Hidden pinned
    # LoRAs are dropped unless the global "show hidden" setting is on, so
    # the prompt LLM never sees them as available.
    pinned = session.get("pinned_loras") or []
    pinned_names = [p["lora_name"] for p in pinned]
    pinned_rows = library_repo.get_loras_by_names(
        conn, pinned_names, include_hidden=show_hidden,
    )
    seen = {c["name"] for c in bundle["candidates"]}
    for row in pinned_rows:
        if row["name"] not in seen:
            bundle["candidates"].append(row)
            seen.add(row["name"])

    # ---- Step 3: composition --------------------------------------------
    comp_messages = prompt_builder.build_composition_messages(
        mode=mode,
        family_prompt_guide=family_prompt_guide,
        model_description=model_description,
        candidates=bundle["candidates"],
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
        "intents": intents_dump,
        "retrieved": retrieved_dump,
        "brief": brief,
        "created_at": row["created_at"],
    }
