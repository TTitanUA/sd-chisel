"""Per-agent run path: turns one comfy agent into one LMStudio call,
parses the model's JSON output, and persists each output slot's
``last_value``.

Source input slots — the frontend stores a session-scoped, browser-
only ``SourceSlot`` table (key + purpose + ``source_image_id``) and
each agent's ``source`` input slot points at one ``SourceSlot.id``,
not at the session image directly. The backend has no view of that
table, so the run endpoint accepts a ``source_image_overrides`` map
that the client fills before posting (input-slot id → resolved
``session_source_images.id``). The runner reads the image bytes off
disk, calls ``lmstudio_client.analyze_image`` with the slot's VL
model + prompt + sampling, and appends the description to the
agent's system message under a per-slot heading.

What this is:

- The replacement for the ComfyMock 10-second client-side emulator
  (``frontend/src/features/comfy/mocks/llm-emulator.ts``). Same
  contract — fill each composable output slot with a kind-typed
  value, leave the rest alone — but the values come from a real
  LMStudio chat completion now.

What this is *not*:

- The workflow-level Generate. That's a separate, later piece of
  work (Phase 3 backend); it composes every agent and patches a
  ComfyUI graph. ``run_agent`` only writes ``last_value``​s.

Slot inclusion rules (mirroring the ComfyMock emulator and the user's
"скип auto+unbound" instruction):

- Skip output slots whose ``origin == 'auto'`` and whose ``bound_to``
  is ``None`` — by definition they have no ``kind`` to compose
  against and no workflow slot to feed.
- Skip output slots whose ``kind`` is ``None`` — defensive belt-and-
  braces; the validator already enforces non-null kind for bound
  slots.
- Skip ``image`` / ``image_alpha`` / ``lora_name`` / ``checkpoint_name``
  kinds — those are not produced by the LLM in the real flow
  (they come from ``user_image`` / ``frozen`` / ``library_loras``
  bindings, or from a future LoRA-output side-channel).

Input slot resolution (stored under
``agent.model_params.__input_slots`` by the frontend):

- ``system`` — extra system-prompt text appended verbatim.
- ``prompt_guide`` — pull the picked Family's ``prompt_guide``
  (and ``prompt_i2i`` / ``prompt_t2i`` when ``generation_type``
  is set) and append.
- ``source`` — load the bound session image and run a VL pass with
  the slot's model + prompt; append the resulting description.
  Slots with no resolved image, no VL model, or a missing/disabled
  model are skipped with a one-line warning in the system prompt
  rather than aborting the whole run — partial context is more
  useful than a hard failure.
- ``loras`` — scoping list/filters, no effect on the run path
  itself; the workflow-level Generate consumes them.

The endpoint config + model resolution mirror the legacy prompt
orchestrator's pattern: LMStudio settings come from
``app_settings``; the model is the agent's own ``model_name`` if
set, otherwise the session's ``prompt_model_name``.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

from app import config as app_config
from app.models.comfy import ALL_SLOT_KINDS
from app.models.session import COMFY_LIKE_TYPES
from app.services import lmstudio_client, llm_log
from app.storage import (
    comfy_session_agent_repo as agent_repo,
    library_repo,
    session_repo,
    settings_repo,
    source_image_repo,
)


@dataclass
class _SourceVlResult:
    """One source-input slot's VL pass result, captured during system-
    prompt assembly so the runner can persist it back onto the slot
    after a successful run. ``summary`` carries the model output on
    success; ``warning`` carries a one-line soft-failure message
    (image missing, model disabled, upstream LM error, …) — the two
    are mutually exclusive but both feed the same UI panel so the
    user always sees *something* after a run."""
    summary: str | None
    warning: str | None
    image_filename: str | None
    when: int


_EXT_TO_CT: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


_INPUT_SLOTS_KEY = "__input_slots"

# Kinds the LLM is responsible for composing. Other kinds (image,
# image_alpha, lora_name, checkpoint_name) are filled by other
# bindings at workflow-Generate time.
_COMPOSABLE_KINDS: frozenset[str] = frozenset({
    "text",
    "multiline_text",
    "number_int",
    "number_float",
    "boolean",
    "enum",
})

# Sampling keys we forward from agent.model_params to the LMStudio
# client. Keys outside this set (notably ``__input_slots``) stay on
# the row but never reach the upstream call.
_SAMPLING_KEYS: frozenset[str] = frozenset({
    "temperature", "top_p", "top_k", "max_tokens",
    "presence_penalty", "frequency_penalty", "repeat_penalty", "seed",
})


class AgentRunError(Exception):
    """Raised when the agent run cannot proceed (missing model, bad
    LMStudio config, no composable slots, etc.). The API layer maps
    this to HTTP 409 — same contract as
    :class:`prompt_orchestrator.PreconditionError`."""


# --- public entry point ---------------------------------------------------


def run_agent(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    agent_id: str,
    source_image_overrides: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    """Run one agent and persist its output-slot ``last_value``​s.

    ``source_image_overrides`` is a per-call map from
    ``source``-kind input-slot id to the resolved
    ``session_source_images.id``. The frontend fills it from its
    browser-only ``SourceSlot`` table; the backend reads
    ``model_params.__input_slots`` to know which slots exist but
    relies on this map to resolve a slot to an image.

    Returns the refreshed agent row. Raises :class:`AgentRunError`
    when preconditions fail (no comfy session, no model, no
    LMStudio config, no composable slots) and
    :class:`lmstudio_client.LmError` when the upstream call itself
    fails (timeout / shape / config). The router maps both onto HTTP
    409 / 502 respectively.
    """
    with llm_log.run_context():
        return _run_inner(
            conn,
            session_id=session_id,
            agent_id=agent_id,
            source_image_overrides=source_image_overrides or {},
        )


def _run_inner(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    agent_id: str,
    source_image_overrides: dict[str, str | None],
) -> dict[str, Any]:
    session = session_repo.get_session(conn, session_id)
    if session is None:
        raise AgentRunError(f"session not found: {session_id!r}")
    if session.get("session_type") not in COMFY_LIKE_TYPES:
        raise AgentRunError("session is not a comfy session")

    agent = agent_repo.get_agent(conn, agent_id)
    if agent is None or agent.get("session_id") != session_id:
        raise AgentRunError(f"agent not found: {agent_id!r}")

    composable = _select_composable_slots(agent.get("output_slots") or [])
    if not composable:
        raise AgentRunError(
            "agent has no composable output slots — every slot is either "
            "auto-unbound, kind-less, or a non-LLM kind",
        )

    model = _resolve_model(agent=agent, session=session)
    endpoint = _resolve_endpoint(conn)
    sampling = _extract_sampling(agent.get("model_params"))
    source_results: dict[str, _SourceVlResult] = {}
    system_prompt = _build_system_prompt(
        conn=conn,
        endpoint=endpoint,
        agent=agent,
        composable=composable,
        session_id=session_id,
        source_image_overrides=source_image_overrides,
        source_results=source_results,
    )
    user_message = (agent.get("prompt") or "").strip() or "(no user prompt)"

    raw = lmstudio_client.chat_complete(
        endpoint=endpoint,
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        # LMStudio's strict json_schema mode silently drops content for
        # some reasoning models (see comfy_import_service note); the
        # text mode + post-hoc JSON extraction is the same pattern the
        # rest of the app uses.
        response_format={"type": "text"},
        sampling=sampling or None,
    )
    parsed = _parse_object(raw)

    # Apply per-label values back onto the agent's slot list.
    by_label = {s["label"]: s for s in composable}
    new_slots: list[dict[str, Any]] = []
    for slot in agent.get("output_slots") or []:
        if slot.get("label") in by_label:
            value = parsed.get(slot["label"])
            coerced = _coerce_to_kind(value, kind=slot["kind"])
            new_slots.append({**slot, "last_value": coerced})
        else:
            new_slots.append(slot)

    update_fields: dict[str, Any] = {"output_slots": new_slots}
    if source_results:
        merged = _merge_source_vl_results(
            agent.get("model_params"), source_results,
        )
        if merged is not None:
            update_fields["model_params"] = merged

    agent_repo.update_agent(conn, agent_id, fields=update_fields)
    agent_repo.touch_last_run_at(conn, agent_id, when=int(time.time()))
    refreshed = agent_repo.get_agent(conn, agent_id)
    assert refreshed is not None
    return refreshed


def _merge_source_vl_results(
    model_params: dict[str, Any] | None,
    results: dict[str, _SourceVlResult],
) -> dict[str, Any] | None:
    """Patch each ``source``-kind input slot's ``last_summary`` /
    ``last_warning`` / ``last_image_filename`` / ``last_at`` fields
    from ``results``. Returns a new ``model_params`` dict the caller
    passes to :func:`agent_repo.update_agent`. Returns ``None`` when
    ``model_params`` doesn't carry the input-slots blob — nothing to
    update."""
    if not isinstance(model_params, dict):
        return None
    raw = model_params.get(_INPUT_SLOTS_KEY)
    if not isinstance(raw, list):
        return None
    new_slots: list[dict[str, Any]] = []
    changed = False
    for slot in raw:
        if not isinstance(slot, dict):
            new_slots.append(slot)
            continue
        if slot.get("kind") != "source":
            new_slots.append(slot)
            continue
        slot_id = slot.get("id") if isinstance(slot.get("id"), str) else None
        result = results.get(slot_id or "")
        if result is None:
            new_slots.append(slot)
            continue
        cfg = dict(slot.get("source") or {})
        cfg["last_summary"] = result.summary
        cfg["last_warning"] = result.warning
        cfg["last_image_filename"] = result.image_filename
        cfg["last_at"] = result.when
        new_slots.append({**slot, "source": cfg})
        changed = True
    if not changed:
        return None
    return {**model_params, _INPUT_SLOTS_KEY: new_slots}


# --- selection ------------------------------------------------------------


def _select_composable_slots(
    slots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in slots:
        kind = s.get("kind")
        origin = s.get("origin")
        bound = s.get("bound_to")
        if origin == "auto" and not bound:
            continue
        if not isinstance(kind, str) or kind not in ALL_SLOT_KINDS:
            continue
        if kind not in _COMPOSABLE_KINDS:
            continue
        out.append(s)
    return out


# --- model + endpoint -----------------------------------------------------


def _resolve_model(
    *, agent: dict[str, Any], session: dict[str, Any],
) -> str:
    model = (agent.get("model_name") or "").strip()
    if not model:
        model = (session.get("prompt_model_name") or "").strip()
    if not model:
        raise AgentRunError(
            "no model selected — pick one on the agent or set the "
            "session's prompt model in Session settings",
        )
    return model


def _resolve_endpoint(conn: sqlite3.Connection) -> dict[str, Any]:
    cfg = settings_repo.get_lmstudio(conn)
    url = (cfg.get("lmstudio_url") or "").strip()
    if not url:
        raise AgentRunError(
            "LMStudio base URL is not configured — open Settings → LMStudio",
        )
    return {"server_root": url, "api_key": cfg.get("lmstudio_api_key")}


def _extract_sampling(
    model_params: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(model_params, dict):
        return {}
    return {
        k: v for k, v in model_params.items()
        if k in _SAMPLING_KEYS and v is not None
    }


# --- system prompt --------------------------------------------------------


def _build_system_prompt(
    *,
    conn: sqlite3.Connection,
    endpoint: dict[str, Any],
    agent: dict[str, Any],
    composable: list[dict[str, Any]],
    session_id: str,
    source_image_overrides: dict[str, str | None],
    source_results: dict[str, _SourceVlResult] | None = None,
) -> str:
    parts: list[str] = []
    parts.append(
        "You are a per-slot composer for a ComfyUI workflow. Read the "
        "user's brief and produce a JSON object whose keys are the "
        "slot labels listed below. Output ONE JSON object and nothing "
        "else — no prose, no markdown fences, no commentary."
    )
    parts.append(_describe_slots_block(composable))

    inputs = _read_input_slots(agent.get("model_params"))
    extras = _input_slot_additions(
        conn,
        endpoint=endpoint,
        slots=inputs,
        session_id=session_id,
        source_image_overrides=source_image_overrides,
        source_results=source_results,
    )
    if extras:
        parts.append("Additional context:")
        parts.extend(extras)

    parts.append(
        "JSON output rules:\n"
        "- Every key listed above MUST be present.\n"
        "- Numeric kinds (number_int / number_float) MUST be JSON "
        "numbers, not strings.\n"
        "- boolean kinds MUST be true / false, not strings.\n"
        "- Values for text / multiline_text MUST be non-empty strings."
    )
    return "\n\n".join(parts)


def _describe_slots_block(slots: list[dict[str, Any]]) -> str:
    lines = ["Slots to fill:"]
    for s in slots:
        line = f"- {s['label']} (kind: {s['kind']})"
        desc = (s.get("description") or "").strip()
        if desc:
            line += f": {desc}"
        lines.append(line)
    return "\n".join(lines)


def _read_input_slots(
    model_params: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(model_params, dict):
        return []
    raw = model_params.get(_INPUT_SLOTS_KEY)
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for s in raw:
        if isinstance(s, dict) and isinstance(s.get("kind"), str):
            out.append(s)
    return out


def _input_slot_additions(
    conn: sqlite3.Connection,
    *,
    endpoint: dict[str, Any],
    slots: list[dict[str, Any]],
    session_id: str,
    source_image_overrides: dict[str, str | None],
    source_results: dict[str, _SourceVlResult] | None = None,
) -> list[str]:
    """Render each input slot to a system-prompt fragment. Unknown
    kinds and unresolved references are silently skipped — the
    editor surfaces those as warnings; the runner does not fail
    the call over a missing family or a misconfigured source slot.

    ``source_results``, when provided, is mutated in place: every
    source-kind input slot's :class:`_SourceVlResult` is recorded
    keyed by the slot's ``id`` so the caller can persist them back
    onto the slot after a successful run. Slots with no ``id`` are
    skipped (defence — the frontend always assigns one)."""
    parts: list[str] = []
    for s in slots:
        if s["kind"] == "system":
            text = (s.get("system") or {}).get("text") or ""
            if text.strip():
                parts.append(text.strip())
        elif s["kind"] == "prompt_guide":
            cfg = s.get("prompt_guide") or {}
            family_id = cfg.get("guide_id")
            gen = cfg.get("generation_type")
            if isinstance(family_id, str):
                rendered = _render_prompt_guide(
                    conn, family_id=family_id, generation_type=gen,
                )
                if rendered:
                    parts.append(rendered)
        elif s["kind"] == "source":
            label = s.get("label") or "source"
            slot_id = s.get("id") if isinstance(s.get("id"), str) else None
            result = _render_source(
                conn,
                endpoint=endpoint,
                slot=s,
                session_id=session_id,
                resolved_image_id=source_image_overrides.get(slot_id or ""),
            )
            if source_results is not None and slot_id:
                source_results[slot_id] = result
            parts.append(_format_source_for_prompt(label, result))
        # loras: see module docstring.
    return parts


def _render_source(
    conn: sqlite3.Connection,
    *,
    endpoint: dict[str, Any],
    slot: dict[str, Any],
    session_id: str,
    resolved_image_id: str | None,
) -> _SourceVlResult:
    """Run a VL pass on the bound session image and return a structured
    result with the description (or a one-line soft-failure message).
    Soft failures (no image bound, model missing, image not on disk,
    upstream LM error) are reported as ``warning`` so the LLM still
    sees that the user intended to attach an image — better than
    silently dropping context. ``LmError`` from the upstream call is
    *not* re-raised: the agent's own composition pass should still
    proceed.

    The runner persists this result back onto the input slot after a
    successful run so the UI can show "what the VL model saw" without
    re-running the analysis. ``summary`` and ``warning`` are mutually
    exclusive — exactly one is non-null on return."""
    cfg = slot.get("source") or {}
    when = int(time.time())

    def fail(msg: str, *, filename: str | None = None) -> _SourceVlResult:
        return _SourceVlResult(
            summary=None, warning=msg, image_filename=filename, when=when,
        )

    if not resolved_image_id:
        return fail("no image bound (configure a source slot).")
    image_row = source_image_repo.get(conn, resolved_image_id)
    if image_row is None or image_row.get("session_id") != session_id:
        return fail("bound image not found on this session.")
    image_filename = image_row.get("original_filename")

    vl_model = (cfg.get("vl_model") or "").strip()
    if not vl_model:
        return fail(
            "no VL model selected — image was not analysed.",
            filename=image_filename,
        )
    model_row = settings_repo.get_lm_model(conn, vl_model)
    if model_row is None or not model_row["enabled"] or not model_row["vision"]:
        return fail(
            f"VL model {vl_model!r} is disabled or not vision-capable — "
            "image was not analysed.",
            filename=image_filename,
        )

    try:
        data_root = app_config.resolve_data_root().resolve()
        image_path = (data_root / image_row["path"]).resolve()
        if not str(image_path).startswith(str(data_root)) or not image_path.is_file():
            return fail(
                "bound image is missing on disk.", filename=image_filename,
            )
        ext = image_path.suffix.lower()
        content_type = _EXT_TO_CT.get(ext)
        if content_type is None:
            return fail(
                f"unsupported image format ({ext!r}).",
                filename=image_filename,
            )
        image_bytes = image_path.read_bytes()
    except OSError as exc:
        return fail(
            f"could not read image: {exc}.", filename=image_filename,
        )

    sampling: dict[str, Any] = {}
    if isinstance(cfg.get("vl_temperature"), (int, float)):
        sampling["temperature"] = float(cfg["vl_temperature"])
    if isinstance(cfg.get("vl_max_tokens"), int):
        sampling["max_tokens"] = int(cfg["vl_max_tokens"])

    try:
        summary = lmstudio_client.analyze_image(
            endpoint=endpoint,
            model=vl_model,
            image_bytes=image_bytes,
            content_type=content_type,
            refining_prompt=cfg.get("vl_prompt") or None,
            sampling=sampling or None,
        )
    except lmstudio_client.LmError as exc:
        return fail(
            f"VL call failed: {exc.detail}.", filename=image_filename,
        )
    return _SourceVlResult(
        summary=summary,
        warning=None,
        image_filename=image_filename,
        when=when,
    )


def _format_source_for_prompt(label: str, result: _SourceVlResult) -> str:
    """Render a :class:`_SourceVlResult` into the system-prompt
    fragment shape the LLM expects."""
    if result.summary is not None:
        filename = result.image_filename or "(unknown filename)"
        return f"[{label}] image description ({filename}):\n{result.summary}"
    return f"[{label}] {result.warning or 'unknown VL state'}"


def _render_prompt_guide(
    conn: sqlite3.Connection,
    *,
    family_id: str,
    generation_type: str | None,
) -> str | None:
    fam = library_repo.get_family(conn, family_id)
    if fam is None:
        return None
    base = (fam.get("prompt_guide") or "").strip()
    extra = ""
    if generation_type == "i2i":
        extra = (fam.get("prompt_i2i") or "").strip()
    elif generation_type == "t2i":
        extra = (fam.get("prompt_t2i") or "").strip()
    body = "\n\n".join(p for p in (base, extra) if p)
    if not body:
        return None
    return f"Prompt guide for family {fam['display_name']!r}:\n{body}"


# --- response parsing -----------------------------------------------------


def _parse_object(raw: str) -> dict[str, Any]:
    """Pull a JSON object out of the LLM's text and decode it. Same
    fence/leading-prose tolerance as
    :mod:`app.services.comfy_import_service`."""
    s = (raw or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()
    start = s.find("{")
    if start < 0:
        raise lmstudio_client.LmError("shape", "no JSON object in agent output")
    depth = 0
    in_string = False
    escape = False
    end = -1
    for i, ch in enumerate(s[start:], start=start):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end < 0:
        raise lmstudio_client.LmError("shape", "unbalanced JSON object in agent output")
    block = s[start:end]
    try:
        obj = json.loads(block)
    except json.JSONDecodeError as exc:
        raise lmstudio_client.LmError("shape", f"bad JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise lmstudio_client.LmError("shape", "agent output is not a JSON object")
    return obj


def _coerce_to_kind(value: Any, *, kind: str) -> Any:
    """Best-effort coercion to the slot's declared kind. Returns
    ``None`` when the value is missing or unusable — the frontend
    renders that as "(no value yet)" without breaking the run.
    Strict typing belongs upstream (response_format is "text" by
    design); this layer is the safety net for slightly off-shape
    outputs (number-as-string, bool-as-string, etc.)."""
    if value is None:
        return None
    if kind in ("text", "multiline_text"):
        if isinstance(value, str):
            return value
        return str(value)
    if kind == "number_int":
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                return None
        return None
    if kind == "number_float":
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                return None
        return None
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            v = value.strip().lower()
            if v in ("true", "1", "yes"):
                return True
            if v in ("false", "0", "no"):
                return False
        if isinstance(value, (int, float)):
            return bool(value)
        return None
    if kind == "enum":
        if isinstance(value, (str, int, float, bool)):
            return value
        return None
    return value
