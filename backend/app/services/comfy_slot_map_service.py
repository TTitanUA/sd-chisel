"""Phase 2 — workflow slot mapping.

Computes the set of *eligible* (node_id, input_name) pairs in a
workflow that sd-chisel can fill at generate time. The slot map
itself is purely user-driven: this service narrows the candidate
list, the editor in the UI assigns slots, and Phase 3 reads the
saved map to patch the graph before queueing.

What sd-chisel can inject:
  - text  → a STRING input that holds a literal in the graph
  - image → a LoadImage-style input that takes an uploaded filename

Everything else (seed, steps, cfg, sampler, dimensions, checkpoint,
VAE, …) lives in the workflow as the user exported it; Phase 2
deliberately doesn't touch those.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from app.storage import comfy_catalog_repo


def _is_wired(value: Any) -> bool:
    """ComfyUI's API format encodes wired inputs as ``[node_id, slot_idx]``
    where node_id is a string and slot_idx an int. Anything else is a
    literal (which sd-chisel can override) or an unsupported type we
    skip."""
    return (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], str)
        and isinstance(value[1], int)
    )


def _input_type_spec(
    inputs_raw: Any, input_name: str,
) -> tuple[Any, dict[str, Any]] | None:
    """Look up the (type, options) tuple for ``input_name`` in a node's
    raw INPUT_TYPES dict. Returns None if the input isn't declared in
    the schema (which can happen for permissive nodes that accept
    arbitrary kwargs)."""
    if not isinstance(inputs_raw, dict):
        return None
    for kind in ("required", "optional"):
        section = inputs_raw.get(kind)
        if not isinstance(section, dict):
            continue
        spec = section.get(input_name)
        if not isinstance(spec, list) or not spec:
            continue
        options = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
        return spec[0], options
    return None


def _classify_input(
    type_spec: Any, options: dict[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    """Bucket an input as ``"text"`` / ``"image"`` based on its raw
    schema, or return ``None`` for inputs sd-chisel can't fill (INT,
    FLOAT, MODEL wires, sampler-name combos, etc.)."""
    if isinstance(type_spec, str):
        if type_spec == "STRING":
            return "text", {"multiline": bool(options.get("multiline", False))}
        return None
    if isinstance(type_spec, list):
        # Combo input. We treat it as image-eligible only when ComfyUI
        # marks it with image_upload — that's the LoadImage / LoadMask
        # convention. Plain combos (sampler_name, scheduler, ckpt list)
        # are left alone; they're "the user already chose this".
        if options.get("image_upload") is True:
            return "image", {}
        return None
    return None


def compute_candidates(
    *,
    conn: sqlite3.Connection,
    graph: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Walk the graph and return ``{"text": [...], "image": [...]}``
    where each item describes one eligible input.

    Eligibility rules:
      - The input must hold a literal in the graph (not a wire).
      - The input's raw type must be ``STRING`` (text bucket) or a
        combo with ``image_upload=True`` (image bucket).
      - When the node's ``class_type`` is in the catalog we use its
        cached ``inputs_raw_json`` to read the schema. When it isn't,
        we fall back to a softer heuristic (``image_upload`` can't be
        detected without the catalog — those inputs are silently
        skipped, since the user can't very well pick them anyway).
    """
    text_bucket: list[dict[str, Any]] = []
    image_bucket: list[dict[str, Any]] = []

    catalog_cache: dict[str, dict[str, Any] | None] = {}

    def _node_row(class_type: str) -> dict[str, Any] | None:
        if class_type not in catalog_cache:
            catalog_cache[class_type] = comfy_catalog_repo.get_node(conn, class_type)
        return catalog_cache[class_type]

    # Iterate node ids in lexical order so the output is deterministic
    # regardless of how the JSON was originally serialised.
    for node_id in sorted(graph.keys(), key=lambda x: (len(x), x)):
        node = graph.get(node_id)
        if not isinstance(node, dict):
            continue
        class_type = node.get("class_type")
        if not isinstance(class_type, str) or not class_type:
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue

        catalog_row = _node_row(class_type)
        inputs_raw = catalog_row["inputs_raw"] if catalog_row else None
        node_display_name = (
            catalog_row["display_name"] if catalog_row else None
        )
        # ComfyUI lets the user set a free-form per-node title in the
        # canvas; it lands in graph as `_meta.title`. Two nodes of the
        # same class look identical in the dropdown without it (positive
        # vs negative CLIPTextEncode is the canonical case).
        meta = node.get("_meta") if isinstance(node.get("_meta"), dict) else None
        node_title = (meta.get("title") if meta else None)
        if not isinstance(node_title, str) or not node_title.strip():
            node_title = None

        for input_name, value in inputs.items():
            if _is_wired(value):
                continue
            kind: str | None = None
            multiline = False

            if inputs_raw is not None:
                spec = _input_type_spec(inputs_raw, input_name)
                if spec is None:
                    continue
                classified = _classify_input(spec[0], spec[1])
                if classified is None:
                    continue
                kind, extras = classified
                multiline = bool(extras.get("multiline", False))
            else:
                # No catalog entry yet: best-effort fallback. Strings are
                # almost always safe to expose as text candidates;
                # images require the image_upload flag we can't see, so
                # we leave them off.
                if isinstance(value, str):
                    kind = "text"
                    multiline = "\n" in value
                else:
                    continue

            entry = {
                "node_id": node_id,
                "input_name": input_name,
                "node_class_type": class_type,
                "node_display_name": node_display_name,
                "node_title": node_title,
                "node_in_catalog": catalog_row is not None,
                "current_value": value,
                "multiline": multiline,
            }
            if kind == "text":
                text_bucket.append(entry)
            elif kind == "image":
                image_bucket.append(entry)

    return {"text": text_bucket, "image": image_bucket}


# --- assignment validation -------------------------------------------------


SLOT_KIND: dict[str, str] = {
    "positive_prompt": "text",
    "negative_prompt": "text",
    "main_image": "image",
}
"""Mirrors ``app.models.comfy.SLOT_KIND``. Kept here too so the
validator below has no inbound dependency on the API layer."""


class SlotMapValidationError(ValueError):
    """Raised when a slot map references a non-existent (node, input)
    pair, or assigns an input of the wrong kind to a slot."""


def validate_slot_map(
    *,
    slot_map: dict[str, Any],
    candidates: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Check that every assignment in ``slot_map`` points at a real
    eligible input of the matching kind.

    Returns a normalised slot_map (extra keys stripped, missing keys
    inserted as None). Raises ``SlotMapValidationError`` on the first
    bad assignment so the API layer can surface a clear 422.
    """
    out: dict[str, Any] = {slot: None for slot in SLOT_KIND}
    if not isinstance(slot_map, dict):
        raise SlotMapValidationError("slot_map must be an object")

    by_pair: dict[str, set[tuple[str, str]]] = {
        kind: {(c["node_id"], c["input_name"]) for c in items}
        for kind, items in candidates.items()
    }

    for slot, value in slot_map.items():
        if slot not in SLOT_KIND:
            # Silently drop unknown slots so older clients don't
            # accidentally clear new fields they don't know about yet.
            continue
        if value is None:
            out[slot] = None
            continue
        if not isinstance(value, dict):
            raise SlotMapValidationError(
                f"slot '{slot}' must be null or an object with node_id/input_name",
            )
        node_id = value.get("node_id")
        input_name = value.get("input_name")
        if not isinstance(node_id, str) or not isinstance(input_name, str):
            raise SlotMapValidationError(
                f"slot '{slot}' is missing node_id or input_name",
            )
        kind = SLOT_KIND[slot]
        if (node_id, input_name) not in by_pair.get(kind, set()):
            raise SlotMapValidationError(
                f"slot '{slot}' points at {node_id}.{input_name}, which is "
                f"not an eligible {kind} input in this workflow",
            )
        out[slot] = {"node_id": node_id, "input_name": input_name}

    return out
