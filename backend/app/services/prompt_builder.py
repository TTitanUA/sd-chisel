"""Pure string assembly for the two LLM calls.

Source: spec §4.1 (intent rewriting) and §4.5 (composition system prompt).
This module knows nothing about the LLM client or the DB — every input is a
plain Python value the orchestrator already has on hand.
"""
from __future__ import annotations

from typing import Any

INTENT_SYSTEM = (
    "You are a planner that turns an image-to-image editing brief into a "
    "small list of search intents. For each intent emit a `kind` (a short "
    "tag like 'style', 'detail', 'character', or anything that matches a "
    "tag we tell you about) and a `query` — a poetic phrase describing the "
    "*effect* you want to find a LoRA for, NOT a literal description of the "
    "source image. Output must be a JSON object matching this schema:\n"
    '{"intents": [{"kind": "string", "query": "string"}, ...]}\n'
    "1 to 6 intents. No prose, no markdown — JSON only."
)

GENERATED_PROMPT_SCHEMA_HINT = (
    'Return a JSON object matching exactly:\n'
    '{"positive": "string, non-empty",\n'
    ' "negative": "string | null",\n'
    ' "loras": [{"name": "string", "weight": number in [-2.0, 2.0]}, ...]}\n'
    "No prose, no markdown, no comments — JSON only."
)


def _format_history(chat_messages: list[dict[str, Any]]) -> str:
    if not chat_messages:
        return "(no prior conversation)"
    lines = []
    for m in chat_messages:
        lines.append(f"{m['role']}: {m['content']}")
    return "\n".join(lines)


def build_intent_messages(
    *,
    vl_summary: str,
    chat_messages: list[dict[str, Any]],
    distinct_tags: list[str],
) -> list[dict[str, str]]:
    if distinct_tags:
        tag_block = (
            "Known tags (prefer one of these for `kind`, but invent a new one "
            "if none fit):\n" + ", ".join(distinct_tags)
        )
    else:
        tag_block = (
            "We have no tags yet (cold start) — choose any short `kind` you like."
        )
    user_content = (
        f"# Source image analysis\n{vl_summary}\n\n"
        f"# Recent conversation\n{_format_history(chat_messages)}\n\n"
        f"# {tag_block}"
    )
    return [
        {"role": "system", "content": INTENT_SYSTEM},
        {"role": "user", "content": user_content},
    ]


def _format_lora_block(lora: dict[str, Any]) -> str:
    triggers = ", ".join(lora.get("trigger_words") or []) or "(none)"
    weight = lora.get("recommended_weight")
    head = (
        f"# {lora['name']}\n"
        f"family: {lora['family_id']} | "
        f"recommended_weight: {weight if weight is not None else 'n/a'} | "
        f"triggers: {triggers}\n"
    )
    return head + (lora.get("description") or "")


def build_composition_messages(
    *,
    family_prompt_guide: str,
    model_description: str | None,
    candidates: list[dict[str, Any]],
    vl_summary: str,
    chat_messages: list[dict[str, Any]],
    use_negative: bool,
) -> list[dict[str, str]]:
    parts = [family_prompt_guide.strip()]
    if model_description and model_description.strip():
        parts.append(model_description.strip())
    if candidates:
        loras_section = "\n\n---\n\n".join(_format_lora_block(c) for c in candidates)
    else:
        loras_section = "(no candidate LoRAs)"
    parts.append("# Available LoRAs\n" + loras_section)
    parts.append(f"# Source image analysis\n{vl_summary}")
    parts.append(f"# Conversation\n{_format_history(chat_messages)}")
    parts.append("# Output\n" + GENERATED_PROMPT_SCHEMA_HINT)
    system = "\n\n".join(parts)

    if use_negative:
        user = (
            "Generate the prompt now. `negative` must be a non-empty string "
            "describing what to avoid (artifacts, anatomy issues, unwanted "
            "styles, etc.)."
        )
    else:
        user = (
            "Generate the prompt now. The user disabled negative prompting — "
            "set `negative` to null."
        )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
