"""Summarize a chat into a self-contained generation brief.

Replaces the old tool-calling agent path: the chat is now plain
streaming, and at "Generate" time the server collapses the
conversation into a brief that becomes the input to
``prompt_orchestrator``.

The summarizer is a single non-streaming LLM call that returns plain
markdown with two sections: ``## Direction`` (a paragraph) and an
optional ``## Constraints`` (bullet list). We deliberately do not use
JSON schemas or structured outputs — small local models handle
free-form markdown more reliably, and the same string flows straight
into the modal's markdown preview without parsing. The orchestrator
also accepts the markdown verbatim as the user brief.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from app.services import lmstudio_client
from app.storage import session_repo, source_image_repo

CHAT_HISTORY_LIMIT = 30

SUMMARIZER_SYSTEM = (
    "You read a chat between a user and an assistant about an "
    "image-generation prompt and produce a brief of what the user "
    "wants. Focus on USER INTENT — the change they want to apply "
    "(for image-to-image) or the image they want to create "
    "(for text-to-image). The downstream pipeline already has access "
    "to the source-image analyses and the model's family guide, so do "
    "not re-describe the source from scratch and do not invent visual "
    "details the user did not ask for. Capture only the user's ask.\n\n"
    "Stay model-agnostic — do not assume a specific diffusion model, "
    "family, or prompt syntax; the orchestrator handles that.\n\n"
    "Output format — plain markdown, exactly these sections in order:\n\n"
    "## Goal\n"
    "<one concise paragraph answering: what does the user want? For "
    "i2i, what change are they asking to apply to the source? For "
    "t2i, what image are they asking to create? Capture concrete "
    "edits, references between source images (e.g. \"take the cat "
    "from Image_1 onto the background of Image_2\") if the user made "
    "any, and the specific direction they converged on. Skip "
    "pleasantries, abandoned ideas, and assistant meta-commentary "
    "(\"I'm not sure what you want\", etc.). No lists, no nested "
    "headings.>\n\n"
    "## Constraints\n"
    "- <one bullet per user-stated prohibition or hard exclusion>\n\n"
    "Constraint rules:\n"
    "- Include every prohibition the user stated, even if mentioned "
    "only once.\n"
    "- Use the user's EXACT names for LoRAs, models, styles.\n"
    "- Phrasings like 'do not use X', 'не используй X', "
    "'запрещено использовать X', 'avoid X', 'без X', 'exclude X' are "
    "constraints. Translate the constraint into a clear English bullet "
    "while preserving the user's exact identifier.\n"
    "- If the user stated NO prohibitions, omit the entire ## "
    "Constraints section — do not output an empty heading or "
    "placeholder bullet. Never invent constraints.\n\n"
    "If the chat is empty or off-topic, output a Goal of 'No specific "
    "direction yet — keep the source image as-is' for i2i, or 'No "
    "specific direction yet' for t2i, and omit the Constraints "
    "section.\n\n"
    "No preamble, no code fences, no extra sections."
)


def summarize_session_chat(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    endpoint: dict[str, Any],
    prompt_model: str,
    sampling: dict[str, Any] | None = None,
) -> str:
    """Return a markdown brief for the next generation run.

    Uses the same ``prompt_model`` as the orchestrator. Pulls the
    session's mode (i2i / t2i), main source-image analysis (when any),
    and the last N chat messages, and asks the LLM to converge them
    into a markdown brief of the documented shape.
    """
    session = session_repo.get_session(conn, session_id) or {}
    mode = session.get("session_type") or "i2i"

    sources = source_image_repo.list_for_session(conn, session_id)
    history = session_repo.list_messages(conn, session_id=session_id)
    history = history[-CHAT_HISTORY_LIMIT:]

    parts: list[str] = [f"# Session mode\n{mode}"]
    if mode == "t2i":
        ref_lines = []
        for s in sources:
            if not (s.get("analysis") or "").strip():
                continue
            text = s["analysis"].strip().replace("\n", " ")
            ref_lines.append(f"- Image_{s['image_number']}: {text}")
        if ref_lines:
            parts.append("# Reference images\n" + "\n".join(ref_lines))
    else:
        main = next((s for s in sources if s["is_main"]), None)
        main_summary = (main or {}).get("analysis") or ""
        if main_summary.strip():
            parts.append(f"# Source image analysis\n{main_summary.strip()}")
    if history:
        lines = [f"{m['role']}: {m['content']}" for m in history]
        parts.append("# Conversation\n" + "\n".join(lines))
    else:
        parts.append("# Conversation\n(no chat yet)")
    user_content = "\n\n".join(parts) + (
        "\n\nReturn the markdown brief now."
    )

    messages = [
        {"role": "system", "content": SUMMARIZER_SYSTEM},
        {"role": "user", "content": user_content},
    ]
    raw = lmstudio_client.chat_complete(
        endpoint=endpoint, model=prompt_model, messages=messages,
        sampling=sampling,
    )
    return raw.strip()
