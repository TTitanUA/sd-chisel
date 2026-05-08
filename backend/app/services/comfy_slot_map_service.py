"""Phase 2.5 — workflow-declared, typed, labelled slots.

Computes the set of *eligible* (node_id, input_name) pairs in a
workflow that sd-chisel can fill at generate time, classifies each by
``SlotKind`` (text / multiline_text / image / number / enum / …),
validates a user-saved slot map against the graph + catalog, and
upgrades pre-2.5 ``slot_map_json`` payloads to the new shape on read.

What changes vs Phase 2:

- The candidate computer no longer returns ``{text, image}`` only — it
  returns one bucket per :data:`app.models.comfy.ALL_SLOT_KINDS`. Each
  candidate carries a ``kind`` field plus kind-specific ``metadata``
  (multiline, options, min/max/step, default).
- The slot model is no longer a fixed three-key dict. It's a per-
  workflow list of :class:`SlotDefinition` rows with labels, optional
  groups, and a binding (``llm`` / ``frozen`` / ``user_image`` /
  ``library_loras``).
- Mode (``i2i`` / ``t2i``) is inferred from the slot list at read time
  — any wired ``binding=user_image`` slot ⇒ ``i2i``.

Phase 2.5 stops at the data model + editor; the composition LLM call
and graph-patching paths land in Phase 3 prep / Phase 3.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from app.models.comfy import (
    ALL_SLOT_KINDS,
    ALLOWED_BINDINGS,
    IMAGE_LOADER_CLASSES,
    IMAGE_SAVER_CLASSES,
    USER_IMAGE_KINDS,
    SlotBinding,
    SlotKind,
)
from app.storage import comfy_catalog_repo

# --- graph helpers --------------------------------------------------------


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


# --- candidate kind detection --------------------------------------------


_MODEL_FILE_EXTENSIONS = (".safetensors", ".ckpt", ".pt", ".pth", ".bin")


def _looks_like_lora(input_name: str, options: list[Any]) -> bool:
    if "lora" not in input_name.lower():
        return False
    return all(
        isinstance(o, str) and o.lower().endswith(_MODEL_FILE_EXTENSIONS)
        for o in options if o
    ) and any(options)


def _looks_like_checkpoint(input_name: str, options: list[Any]) -> bool:
    name = input_name.lower()
    if not any(token in name for token in ("ckpt", "checkpoint")):
        return False
    return all(
        isinstance(o, str) and o.lower().endswith(_MODEL_FILE_EXTENSIONS)
        for o in options if o
    ) and any(options)


def _classify_with_catalog(
    input_name: str,
    type_spec: Any,
    options: dict[str, Any],
    *,
    class_type: str,
) -> tuple[SlotKind, dict[str, Any]] | None:
    """Catalog-aware classification. Returns ``(kind, metadata)`` or
    ``None`` for inputs sd-chisel can't fill.

    ``type_spec`` is the first element of the raw INPUT_TYPES tuple
    (a string for primitive types, a list for combos). ``options`` is
    the second element (an options dict, possibly empty).

    ``class_type`` is needed because the ``image`` / ``image_alpha``
    kinds are gated to :data:`IMAGE_LOADER_CLASSES` — Phase 3's image
    upload + patch step only knows how to drive a ``LoadImage`` node;
    custom loaders (``LoadImageFromUrl``, ``LoadImageBatch``, …) declare
    the same ``image_upload`` flag but expect different inputs and would
    silently produce wrong results.
    """
    if isinstance(type_spec, str):
        if type_spec == "STRING":
            multiline = bool(options.get("multiline", False))
            kind: SlotKind = "multiline_text" if multiline else "text"
            metadata: dict[str, Any] = {"multiline": multiline}
            if "default" in options:
                metadata["default"] = options.get("default")
            return kind, metadata
        if type_spec == "INT":
            return "number_int", _number_metadata(options)
        if type_spec == "FLOAT":
            return "number_float", _number_metadata(options)
        if type_spec == "BOOLEAN":
            md: dict[str, Any] = {}
            if "default" in options:
                md["default"] = options.get("default")
            return "boolean", md
        return None

    if isinstance(type_spec, list):
        # Combo input. Branch on options shape first (image / mask
        # flags), then on the values' shape (lora / checkpoint
        # heuristic), and fall through to a generic enum.
        if options.get("image_upload") is True:
            if class_type in IMAGE_LOADER_CLASSES:
                return "image", {}
            # Fall through — a custom node with the same flag still
            # exposes a list of filenames; surface it as a generic
            # enum so the user can frozen-bind it if they really want.
            return "enum", {"options": list(type_spec)}
        if options.get("mask") is True or options.get("mask_upload") is True:
            if class_type in IMAGE_LOADER_CLASSES:
                return "image_alpha", {}
            return "enum", {"options": list(type_spec)}
        if _looks_like_lora(input_name, type_spec):
            return "lora_name", {"options": list(type_spec)}
        if _looks_like_checkpoint(input_name, type_spec):
            return "checkpoint_name", {"options": list(type_spec)}
        return "enum", {"options": list(type_spec)}

    return None


def _number_metadata(options: dict[str, Any]) -> dict[str, Any]:
    md: dict[str, Any] = {}
    for key in ("min", "max", "step", "default"):
        if key in options:
            md[key] = options.get(key)
    return md


def _classify_without_catalog(
    value: Any,
) -> tuple[SlotKind, dict[str, Any]] | None:
    """Fallback when the catalog has no row for the node's class. We
    only have the literal value to go on, so combo subtypes (image,
    lora_name, …) can't be detected — those literal values just look
    like plain strings. Bool / int / float / multiline_text we can
    still tell apart from the literal alone."""
    if isinstance(value, bool):
        return "boolean", {}
    if isinstance(value, int):
        return "number_int", {}
    if isinstance(value, float):
        return "number_float", {}
    if isinstance(value, str):
        if "\n" in value:
            return "multiline_text", {"multiline": True}
        return "text", {"multiline": False}
    return None


# --- candidate computation ------------------------------------------------


def compute_candidates(
    *,
    conn: sqlite3.Connection,
    graph: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Walk the graph and return one bucket per :data:`ALL_SLOT_KINDS`.

    Each item describes one eligible input the editor can offer:
    ``{node_id, input_name, node_class_type, node_display_name,
    node_title, node_in_catalog, current_value, kind, metadata}``.

    Eligibility rules:
      - Only literals (not wires) are eligible.
      - Catalog-known nodes use the cached ``inputs_raw_json`` schema
        so combo subtypes (``image_upload``, mask, lora/checkpoint
        filename lists) are detected; uncatalogued nodes fall back to
        a soft heuristic on the literal value alone.
    """
    buckets: dict[str, list[dict[str, Any]]] = {
        kind: [] for kind in ALL_SLOT_KINDS
    }

    catalog_cache: dict[str, dict[str, Any] | None] = {}

    def _node_row(class_type: str) -> dict[str, Any] | None:
        if class_type not in catalog_cache:
            catalog_cache[class_type] = comfy_catalog_repo.get_node(
                conn, class_type,
            )
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
        # same class look identical in the dropdown without it.
        meta = node.get("_meta") if isinstance(node.get("_meta"), dict) else None
        node_title = (meta.get("title") if meta else None)
        if not isinstance(node_title, str) or not node_title.strip():
            node_title = None

        for input_name, value in inputs.items():
            if _is_wired(value):
                continue

            classified: tuple[SlotKind, dict[str, Any]] | None
            if inputs_raw is not None:
                spec = _input_type_spec(inputs_raw, input_name)
                if spec is None:
                    continue
                classified = _classify_with_catalog(
                    input_name, spec[0], spec[1], class_type=class_type,
                )
            else:
                classified = _classify_without_catalog(value)

            if classified is None:
                continue
            kind, metadata = classified

            entry = {
                "node_id": node_id,
                "input_name": input_name,
                "node_class_type": class_type,
                "node_display_name": node_display_name,
                "node_title": node_title,
                "node_in_catalog": catalog_row is not None,
                "current_value": value,
                "kind": kind,
                "metadata": metadata,
            }
            buckets[kind].append(entry)

    return buckets


# --- legacy upgrade -------------------------------------------------------


_LEGACY_SLOT_DEFAULTS: dict[str, dict[str, Any]] = {
    "positive_prompt": {
        "label": "positive_prompt",
        "ordinal": 1,
        "binding": "llm",
        "kind_options": ("multiline_text", "text"),
    },
    "negative_prompt": {
        "label": "negative_prompt",
        "ordinal": 2,
        "binding": "llm",
        "kind_options": ("multiline_text", "text"),
    },
    "main_image": {
        "label": "main_image",
        "ordinal": 3,
        "binding": "user_image",
        "kind_options": ("image", "image_alpha"),
    },
}


def _candidate_lookup(
    candidates: dict[str, list[dict[str, Any]]],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Flat ``(node_id, input_name) → candidate`` index. Each pair
    appears at most once across all buckets (kind is unique per
    input)."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for items in candidates.values():
        for item in items:
            out[(item["node_id"], item["input_name"])] = item
    return out


def upgrade_slot_map(
    *,
    raw: Any,
    candidates: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Bring a stored ``slot_map_json`` payload up to v2 shape.

    A ``None`` / missing value, a ``version=1`` payload (the fixed
    three-slot dict), or an already-v2 payload all return a
    ``{"version": 2, "slots": [...]}`` dict. Slots whose graph origin
    no longer matches a candidate (graph changed under the saved
    map) are dropped — the editor lets the user re-pick.
    """
    if isinstance(raw, dict) and raw.get("version") == 2:
        slots = raw.get("slots") if isinstance(raw.get("slots"), list) else []
        # Drop slots whose origin no longer points at a candidate of
        # the saved kind. The saved metadata (frozen value, etc.)
        # rides along untouched.
        index = _candidate_lookup(candidates)
        kept: list[dict[str, Any]] = []
        for slot in slots:
            if not isinstance(slot, dict):
                continue
            origin = slot.get("origin") or {}
            key = (origin.get("node_id"), origin.get("input_name"))
            cand = index.get(key)  # type: ignore[arg-type]
            if cand is None:
                continue
            if cand["kind"] != slot.get("kind"):
                # Kind drift: skip — validate_slots would have caught
                # this anyway, but the read path is silent.
                continue
            kept.append(slot)
        return {"version": 2, "slots": kept}

    # Anything that isn't v2 is treated as v1: the legacy three-key
    # dict ({positive_prompt, negative_prompt, main_image}). Empty /
    # null / corrupt payloads collapse to an empty slot list.
    if not isinstance(raw, dict):
        return {"version": 2, "slots": []}

    index = _candidate_lookup(candidates)
    upgraded: list[dict[str, Any]] = []
    for legacy_key, defaults in _LEGACY_SLOT_DEFAULTS.items():
        assignment = raw.get(legacy_key)
        if not isinstance(assignment, dict):
            continue
        node_id = assignment.get("node_id")
        input_name = assignment.get("input_name")
        if not isinstance(node_id, str) or not isinstance(input_name, str):
            continue
        cand = index.get((node_id, input_name))
        if cand is None:
            continue
        if cand["kind"] not in defaults["kind_options"]:
            continue
        upgraded.append({
            "label": defaults["label"],
            "group": None,
            "ordinal": defaults["ordinal"],
            "description": None,
            "kind": cand["kind"],
            "origin": {"node_id": node_id, "input_name": input_name},
            "binding": defaults["binding"],
            "metadata": {},
        })
    return {"version": 2, "slots": upgraded}


# --- mode inference -------------------------------------------------------


def infer_mode(slot_map_v2: dict[str, Any]) -> str:
    """Inferred mode for a comfy session: ``i2i`` if the slot list
    contains any wired ``binding=user_image`` slot of an image-shaped
    kind, else ``t2i``."""
    slots = slot_map_v2.get("slots") if isinstance(slot_map_v2, dict) else None
    if not isinstance(slots, list):
        return "t2i"
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        if slot.get("binding") != "user_image":
            continue
        if slot.get("kind") not in USER_IMAGE_KINDS:
            continue
        origin = slot.get("origin")
        if isinstance(origin, dict) and origin.get("node_id") and origin.get("input_name"):
            return "i2i"
    return "t2i"


# --- validation -----------------------------------------------------------


class SlotMapValidationError(ValueError):
    """Raised when a slot list is internally inconsistent or doesn't
    match the workflow graph + catalog."""


def validate_slots(
    *,
    slots: list[dict[str, Any]],
    candidates: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Validate a list of slot definitions against the candidate
    buckets, returning a normalised list ready for persistence.

    Checks performed:
      - Labels are unique within the list.
      - Every slot's ``(origin.node_id, origin.input_name)`` matches a
        candidate of the slot's declared ``kind``.
      - ``binding`` is in the per-kind allow-list (and not the
        reserved ``library_loras`` — that's gated on Phase 3 / L4).
      - For ``binding=frozen`` slots, ``metadata.value`` is present and
        loosely shape-checks for the kind (string, int, float, bool,
        or one-of options). Numbers respect any ``min``/``max`` from
        the candidate's metadata when present.

    Raises :class:`SlotMapValidationError` on the first failure with a
    message naming the offending slot label so the API layer can
    surface a clear 422.
    """
    index = _candidate_lookup(candidates)
    seen_labels: set[str] = set()
    out: list[dict[str, Any]] = []

    for slot in slots:
        label = slot.get("label")
        if not isinstance(label, str) or not label:
            raise SlotMapValidationError("slot is missing a label")
        if label in seen_labels:
            raise SlotMapValidationError(
                f"duplicate slot label: '{label}'",
            )
        seen_labels.add(label)

        kind = slot.get("kind")
        if kind not in ALL_SLOT_KINDS:
            raise SlotMapValidationError(
                f"slot '{label}' has unknown kind '{kind}'",
            )

        origin = slot.get("origin") or {}
        node_id = origin.get("node_id")
        input_name = origin.get("input_name")
        if not isinstance(node_id, str) or not isinstance(input_name, str):
            raise SlotMapValidationError(
                f"slot '{label}' is missing origin.node_id / origin.input_name",
            )
        cand = index.get((node_id, input_name))
        if cand is None:
            raise SlotMapValidationError(
                f"slot '{label}' points at {node_id}.{input_name}, which is "
                f"not an eligible input in this workflow",
            )
        if cand["kind"] != kind:
            raise SlotMapValidationError(
                f"slot '{label}' declares kind '{kind}' but the input is "
                f"of kind '{cand['kind']}'",
            )
        # Reject any input of an image-saver node (SaveImage). Saver
        # nodes are owned by the output slot map — their literal inputs
        # (e.g. ``filename_prefix``) seed the output label and must not
        # be repurposed as an LLM-composed / frozen input slot. Catches
        # a hand-crafted PUT; the editor blocks this in the UI but the
        # server is the source of truth.
        cand_class = cand.get("node_class_type")
        if cand_class in IMAGE_SAVER_CLASSES:
            raise SlotMapValidationError(
                f"slot '{label}' targets an input of '{cand_class}' node "
                f"'{node_id}'; saver nodes are reserved for the output "
                f"slot map and their inputs are not slot-mappable",
            )
        # Defence-in-depth for the LoadImage-only constraint. The
        # classifier already downgrades non-LoadImage image_upload nodes
        # to ``enum``, so the kind-mismatch check above usually catches
        # this — but a stale slot map saved before the gate landed (or
        # a hand-crafted PUT) can still arrive with kind=image and a
        # candidate that *also* came in as kind=image somehow. Reject
        # explicitly with a self-describing error so the frontend can
        # render "rebind to a LoadImage node".
        if kind in ("image", "image_alpha"):
            cand_class = cand.get("node_class_type")
            if cand_class not in IMAGE_LOADER_CLASSES:
                raise SlotMapValidationError(
                    f"slot '{label}' is image-kind but its origin node "
                    f"'{node_id}' is class '{cand_class}'; sd-chisel only "
                    f"drives LoadImage nodes for image inputs",
                )

        binding: SlotBinding = slot.get("binding")  # type: ignore[assignment]
        allowed = ALLOWED_BINDINGS.get(kind, frozenset())  # type: ignore[arg-type]
        if binding not in allowed:
            raise SlotMapValidationError(
                f"slot '{label}' has binding '{binding}' which is not "
                f"allowed for kind '{kind}'",
            )
        if binding == "library_loras":
            # In the enum but not yet selectable — defence in depth.
            raise SlotMapValidationError(
                f"slot '{label}' uses binding 'library_loras', which is "
                f"reserved for a future phase",
            )

        metadata = slot.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise SlotMapValidationError(
                f"slot '{label}' metadata must be an object",
            )
        if binding == "frozen":
            _validate_frozen_value(label, kind, metadata, cand)  # type: ignore[arg-type]

        out.append({
            "label": label,
            "group": slot.get("group") if isinstance(slot.get("group"), str) else None,
            "ordinal": slot.get("ordinal") if isinstance(slot.get("ordinal"), int) else None,
            "description": (
                slot.get("description")
                if isinstance(slot.get("description"), str)
                else None
            ),
            "kind": kind,
            "origin": {"node_id": node_id, "input_name": input_name},
            "binding": binding,
            "metadata": metadata,
        })

    return out


def _validate_frozen_value(
    label: str,
    kind: SlotKind,
    metadata: dict[str, Any],
    candidate: dict[str, Any],
) -> None:
    if "value" not in metadata:
        raise SlotMapValidationError(
            f"slot '{label}' is binding=frozen but metadata.value is missing",
        )
    value = metadata["value"]
    cand_meta = candidate.get("metadata") or {}

    if kind in ("text", "multiline_text"):
        if not isinstance(value, str):
            raise SlotMapValidationError(
                f"slot '{label}' frozen value must be a string",
            )
    elif kind == "number_int":
        if not isinstance(value, int) or isinstance(value, bool):
            raise SlotMapValidationError(
                f"slot '{label}' frozen value must be an int",
            )
        _check_numeric_range(label, value, cand_meta)
    elif kind == "number_float":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise SlotMapValidationError(
                f"slot '{label}' frozen value must be a number",
            )
        _check_numeric_range(label, value, cand_meta)
    elif kind == "boolean":
        if not isinstance(value, bool):
            raise SlotMapValidationError(
                f"slot '{label}' frozen value must be a boolean",
            )
    elif kind in ("enum", "lora_name", "checkpoint_name"):
        options = cand_meta.get("options") or []
        if value not in options:
            raise SlotMapValidationError(
                f"slot '{label}' frozen value is not in the candidate's options",
            )
    # image / image_alpha frozen — value should be a filename string.
    elif kind in ("image", "image_alpha"):
        if not isinstance(value, str):
            raise SlotMapValidationError(
                f"slot '{label}' frozen value must be a filename string",
            )


def _check_numeric_range(
    label: str, value: int | float, cand_meta: dict[str, Any],
) -> None:
    lo = cand_meta.get("min")
    hi = cand_meta.get("max")
    if isinstance(lo, (int, float)) and value < lo:
        raise SlotMapValidationError(
            f"slot '{label}' frozen value {value} is below the candidate's "
            f"minimum ({lo})",
        )
    if isinstance(hi, (int, float)) and value > hi:
        raise SlotMapValidationError(
            f"slot '{label}' frozen value {value} is above the candidate's "
            f"maximum ({hi})",
        )
