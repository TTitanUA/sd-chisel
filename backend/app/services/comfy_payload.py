"""Phase 3 prep — dynamic LLM payload schema for comfy sessions.

Given a comfy session's slot map (``SlotMapV2`` shape from
``comfy_slot_map_service.upgrade_slot_map``), this module builds the
artefacts the prompt orchestrator needs for the composition LLM call:

- :func:`validate_payload` — checks an LLM-produced JSON object against
  the slot list (one field per ``binding=llm`` slot, plus a reserved
  ``__loras`` field that mirrors the legacy ``loras: [{name, weight}]``
  list so comfy sessions surface LoRA picks the same way as i2i / t2i
  sessions).
- :func:`build_schema_hint` — the schema-instruction string the
  composition system message inlines so the LLM knows what JSON to
  return.
- :func:`build_slot_context_block` — a markdown block enumerating every
  slot (label, group, kind, binding, description, frozen value where
  applicable). The composition message uses it so the LLM understands
  the full workflow context, even on slots it does not fill itself.
- :func:`build_chat_slot_block` — one-line-per-slot block appended to
  the chat system prompt for slot-aware chat (resolves Q9).

A hand-rolled validator was preferred over a dynamic Pydantic class:
slot labels are user-controlled and can collide with whatever
internal field name we'd reserve for the LoRA list (Pydantic v2
forbids ``__``-prefixed field names).

Phase 3 prep stops at composition; the patcher / queue cycle that
actually injects values into ``graph_json`` is Phase 3 work.
"""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.models.prompts import LoraSpec

# Reserved key in the produced payload for the LoRA list. Starts with
# ``__`` — the slot label pattern (``^[A-Za-z0-9][...]``) forbids
# leading underscores, so this can never collide with a user-defined
# slot label.
LORAS_KEY = "__loras"


# --- per-kind type rendering ---------------------------------------------


def _json_type_label(kind: str) -> str:
    if kind in ("text", "multiline_text", "enum"):
        return "string"
    if kind == "number_int":
        return "integer"
    if kind == "number_float":
        return "number"
    if kind == "boolean":
        return "boolean"
    raise ValueError(f"slot kind {kind!r} is not LLM-fillable")


def _llm_slots(slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Subset of slots the LLM is responsible for filling."""
    return [s for s in slots if s.get("binding") == "llm"]


def _slot_sort_key(slot: dict[str, Any]) -> tuple[int, str, int, int, str]:
    """Stable ordering: groupless first (sentinel 0), then by group,
    then by ordinal (None floated to end), then by label."""
    group = slot.get("group")
    group_present = 1 if group else 0
    group_value = group or ""
    ordinal = slot.get("ordinal")
    ordinal_present = 0 if ordinal is not None else 1
    ordinal_value = int(ordinal) if ordinal is not None else 0
    return (group_present, group_value, ordinal_present, ordinal_value, slot.get("label") or "")


def sorted_slots(slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return ``slots`` sorted by ``(group, ordinal, label)``."""
    return sorted(slots, key=_slot_sort_key)


# --- validation -----------------------------------------------------------


class PayloadValidationError(ValueError):
    """Raised when an LLM-produced payload does not conform to the slot
    schema. Wraps the first failure with a self-describing message —
    the orchestrator surfaces it as ``LmError("shape", ...)`` the
    same way legacy ``GeneratedPrompt`` shape errors are surfaced."""


def _check_type(label: str, kind: str, value: Any) -> Any:
    """Return ``value`` coerced to the kind's Python type, or raise.

    Booleans are checked strictly (``bool`` first) because ``bool`` is
    a subclass of ``int`` in Python — without the strict order an int
    slot would accept ``True`` / ``False``.
    """
    if kind in ("text", "multiline_text"):
        if not isinstance(value, str):
            raise PayloadValidationError(
                f"slot '{label}' must be a string, got {type(value).__name__}",
            )
        return value
    if kind == "boolean":
        if not isinstance(value, bool):
            raise PayloadValidationError(
                f"slot '{label}' must be a boolean, got {type(value).__name__}",
            )
        return value
    if kind == "number_int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise PayloadValidationError(
                f"slot '{label}' must be an integer, got {type(value).__name__}",
            )
        return value
    if kind == "number_float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PayloadValidationError(
                f"slot '{label}' must be a number, got {type(value).__name__}",
            )
        return float(value)
    if kind == "enum":
        if not isinstance(value, str):
            raise PayloadValidationError(
                f"slot '{label}' must be a string, got {type(value).__name__}",
            )
        return value
    raise PayloadValidationError(
        f"slot '{label}' has kind '{kind}', which is not LLM-fillable",
    )


def _check_range(label: str, value: int | float, metadata: dict[str, Any]) -> None:
    lo = metadata.get("min")
    hi = metadata.get("max")
    if isinstance(lo, (int, float)) and value < lo:
        raise PayloadValidationError(
            f"slot '{label}' value {value} is below the minimum ({lo})",
        )
    if isinstance(hi, (int, float)) and value > hi:
        raise PayloadValidationError(
            f"slot '{label}' value {value} is above the maximum ({hi})",
        )


def _check_enum(label: str, value: str, metadata: dict[str, Any]) -> None:
    options = list(metadata.get("options") or [])
    if not options:
        return
    if value not in options:
        raise PayloadValidationError(
            f"slot '{label}' value {value!r} is not one of the allowed "
            f"options {options!r}",
        )


def validate_payload(
    raw: Any, slots: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate an LLM-produced payload against the slot list.

    Returns the normalised payload dict — keyed by slot label, plus
    :data:`LORAS_KEY` carrying the validated LoRA list. Raises
    :class:`PayloadValidationError` on the first per-slot failure
    (missing required field, wrong type, out-of-range number,
    enum mismatch) or on a malformed LoRA list.
    """
    if not isinstance(raw, dict):
        raise PayloadValidationError(
            f"payload must be a JSON object, got {type(raw).__name__}",
        )

    out: dict[str, Any] = {}
    for slot in _llm_slots(slots):
        label = slot["label"]
        kind = slot["kind"]
        if label not in raw:
            raise PayloadValidationError(
                f"slot '{label}' is missing from the payload",
            )
        value = _check_type(label, kind, raw[label])
        metadata = slot.get("metadata") or {}
        if kind in ("number_int", "number_float"):
            _check_range(label, value, metadata)
        elif kind == "enum":
            _check_enum(label, value, metadata)
        out[label] = value

    raw_loras = raw.get(LORAS_KEY, [])
    if not isinstance(raw_loras, list):
        raise PayloadValidationError(
            f"{LORAS_KEY!r} must be an array, got {type(raw_loras).__name__}",
        )
    loras: list[dict[str, Any]] = []
    for idx, item in enumerate(raw_loras):
        try:
            spec = LoraSpec.model_validate(item)
        except ValidationError as exc:
            raise PayloadValidationError(
                f"{LORAS_KEY}[{idx}] is invalid: {exc.errors()[:1]}",
            ) from exc
        loras.append(spec.model_dump())
    out[LORAS_KEY] = loras
    return out


def split_loras(payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Pop :data:`LORAS_KEY` from ``payload`` and return
    ``(payload_without_loras, loras_list)``. Used by the orchestrator
    to keep the slot-only payload in ``payload_json`` and the LoRA
    list in the legacy ``loras_json`` column."""
    out = dict(payload)
    loras = list(out.pop(LORAS_KEY, []))
    return out, loras


# --- schema-hint block (for the composition system message) ---------------


def build_schema_hint(slots: list[dict[str, Any]]) -> str:
    """Markdown-ish description of the JSON object the LLM must return.

    Lists every ``binding=llm`` slot's label + JSON shape inline, plus
    the reserved ``__loras`` field. The composition system message
    pastes this verbatim — we deliberately keep it terse so it
    survives reasoning-distilled models that sometimes truncate
    long instructions.
    """
    lines: list[str] = ["Return a JSON object with EXACTLY these fields:"]
    llm = sorted_slots(_llm_slots(slots))
    if not llm:
        lines.append("  (no slot fields — only the LoRA list)")
    for slot in llm:
        label = slot["label"]
        kind = slot["kind"]
        json_type = _json_type_label(kind)
        suffix = ""
        if kind == "enum":
            options = (slot.get("metadata") or {}).get("options") or []
            suffix = f", one of {options!r}"
        elif kind in ("number_int", "number_float"):
            md = slot.get("metadata") or {}
            bounds = []
            if "min" in md:
                bounds.append(f"min={md['min']}")
            if "max" in md:
                bounds.append(f"max={md['max']}")
            if bounds:
                suffix = f" ({', '.join(bounds)})"
        lines.append(f"  {label!r}: {json_type}{suffix}")
    lines.append(
        f"  {LORAS_KEY!r}: array of {{name: string, weight: number in "
        f"[-2.0, 2.0]}} (may be empty)",
    )
    lines.append("No prose, no markdown, no comments — JSON only.")
    return "\n".join(lines)


# --- slot context block (for the composition system message) --------------


def _kind_chip(kind: str) -> str:
    """Compact human label for a kind."""
    return {
        "text": "text",
        "multiline_text": "text (multiline)",
        "image": "image",
        "image_alpha": "mask",
        "number_int": "int",
        "number_float": "float",
        "boolean": "boolean",
        "enum": "enum",
        "lora_name": "lora filename",
        "checkpoint_name": "checkpoint filename",
    }.get(kind, kind)


def _slot_label(slot: dict[str, Any]) -> str:
    """`<group>/<label>` if grouped, else `<label>`."""
    group = slot.get("group")
    label = slot.get("label") or "?"
    return f"{group}/{label}" if group else label


def build_slot_context_block(slots: list[dict[str, Any]]) -> str:
    """Markdown block describing every slot in the workflow.

    Used in the composition system message so the LLM sees the full
    slot landscape (not just the ones it fills) — frozen / image /
    lora bindings show their value or marker so the model can reason
    about the overall workflow shape (e.g. "the workflow already
    has a frozen sampler set to euler_a").
    """
    if not slots:
        return ""
    parts: list[str] = ["# Workflow slots"]
    for slot in sorted_slots(slots):
        binding = slot.get("binding") or "?"
        kind = _kind_chip(slot.get("kind") or "?")
        label = _slot_label(slot)
        meta = slot.get("metadata") or {}
        descriptor: str
        if binding == "llm":
            descriptor = f"[fill] {label} ({kind})"
        elif binding == "frozen":
            value = meta.get("value")
            descriptor = f"[frozen={value!r}] {label} ({kind})"
        elif binding == "user_image":
            descriptor = f"[user image] {label} ({kind})"
        elif binding == "library_loras":
            descriptor = f"[library loras] {label} ({kind})"
        else:
            descriptor = f"[{binding}] {label} ({kind})"
        description = (slot.get("description") or "").strip()
        if description:
            descriptor = f"{descriptor} — {description}"
        parts.append(f"- {descriptor}")
    return "\n".join(parts)


# --- chat slot-awareness block (Q9) --------------------------------------


def build_chat_slot_block(slots: list[dict[str, Any]]) -> str:
    """One-line-per-slot block appended to the chat system prompt for
    comfy sessions with a non-empty slot map (resolves Q9 in the
    Phase 3 prep plan).

    Tells the LLM which slots exist so it can acknowledge user
    references in prose, but explicitly forbids JSON / structured
    replies — composition is a separate step. Empty slot maps yield
    an empty string and the caller skips appending anything.
    """
    if not slots:
        return ""
    lines: list[str] = ["The workflow exposes these labelled slots:"]
    for slot in sorted_slots(slots):
        label = _slot_label(slot)
        kind = _kind_chip(slot.get("kind") or "?")
        description = (slot.get("description") or "").strip()
        if description:
            lines.append(f"- {label} ({kind}): {description}")
        else:
            lines.append(f"- {label} ({kind})")
    lines.extend([
        "",
        "Reply in plain prose. Do not emit JSON, schemas, or "
        "\"slot: value\" structures — a separate composition step "
        "fills the slots. The user may reference slots by label; "
        "acknowledge them in prose.",
    ])
    return "\n".join(lines)
