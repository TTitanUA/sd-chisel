"""Output slot map (PR-2) — Phase 3 prep, symmetric to ``slot_map``.

Where ``comfy_slot_map_service`` declares which workflow *inputs*
sd-chisel fills, this module declares which workflow *outputs*
sd-chisel captures. Phase 3's generation cycle walks the saved
``output_slot_map_json`` to know which SaveImage results to copy from
ComfyUI's output dir into ``data/images/<sid>/output/<gid>/<label>.<ext>``.
SaveImage results not in the map are reported as "untracked" warnings
and left alone.

The service offers:

- :func:`compute_output_candidates` — walk the graph and emit one
  :class:`OutputCandidate`-shape dict per node whose ``class_type`` is
  in :data:`app.models.comfy.IMAGE_SAVER_CLASSES`. Other classes that
  also produce IMAGE outputs (custom savers, S3 uploaders, video
  encoders) are skipped — see the IMAGE_SAVER_CLASSES docstring.
- :func:`validate_output_slots` — per-slot guard rails matching the
  shape produced by the editor. Mirrors :func:`comfy_slot_map_service.
  validate_slots`'s contract (raises a typed exception, returns a
  normalised list).
- :func:`upgrade_output_slot_map` — read-time upgrade. Drops entries
  whose ``node_id`` no longer points at a SaveImage candidate (graph
  changed under the saved map) so the editor can reproposition them.
- :func:`auto_default_outputs` — the seed list returned when no map
  has been saved yet. One entry per SaveImage candidate, label
  derived from the node's ``filename_prefix`` literal (or
  ``output_<node_id>`` when the prefix is empty / collides). The API
  layer falls back to this when ``output_slot_map_json`` is NULL on
  the workflow row.

Rejected scenarios for ``validate_output_slots``:

- Empty / non-string label, or a label that doesn't match
  ``_LABEL_PATTERN`` (same regex as the input slot map).
- Duplicate labels.
- ``node_id`` not a string, or not in the candidate set.
- ``kind`` outside :data:`app.models.comfy.ALL_OUTPUT_KINDS`.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from app.models.comfy import ALL_OUTPUT_KINDS, IMAGE_SAVER_CLASSES
from app.storage import comfy_catalog_repo


_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")


# --- candidate computation ------------------------------------------------


def compute_output_candidates(
    *, conn: sqlite3.Connection, graph: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return one candidate per SaveImage node in the workflow.

    Each item: ``{node_id, node_class_type, node_display_name,
    node_title, node_in_catalog, kind, filename_prefix}``. Iteration
    order is lexical by node id so the output is stable across calls.
    """
    out: list[dict[str, Any]] = []
    catalog_cache: dict[str, dict[str, Any] | None] = {}

    def _node_row(class_type: str) -> dict[str, Any] | None:
        if class_type not in catalog_cache:
            catalog_cache[class_type] = comfy_catalog_repo.get_node(
                conn, class_type,
            )
        return catalog_cache[class_type]

    for node_id in sorted(graph.keys(), key=lambda x: (len(x), x)):
        node = graph.get(node_id)
        if not isinstance(node, dict):
            continue
        class_type = node.get("class_type")
        if not isinstance(class_type, str) or class_type not in IMAGE_SAVER_CLASSES:
            continue

        catalog_row = _node_row(class_type)
        node_display_name = (
            catalog_row["display_name"] if catalog_row else None
        )
        meta = node.get("_meta") if isinstance(node.get("_meta"), dict) else None
        node_title = meta.get("title") if meta else None
        if not isinstance(node_title, str) or not node_title.strip():
            node_title = None

        inputs = node.get("inputs")
        prefix = None
        if isinstance(inputs, dict):
            raw_prefix = inputs.get("filename_prefix")
            if isinstance(raw_prefix, str) and raw_prefix.strip():
                prefix = raw_prefix.strip()

        out.append({
            "node_id": str(node_id),
            "node_class_type": class_type,
            "node_display_name": node_display_name,
            "node_title": node_title,
            "node_in_catalog": catalog_row is not None,
            "kind": "image",
            "filename_prefix": prefix,
        })

    return out


# --- defaults / seeding ---------------------------------------------------


def _safe_label(raw: str | None, *, fallback: str) -> str:
    """Coerce a free-form string into a valid slot label. Strips
    characters outside ``A-Za-z0-9_.-`` and forces the first character
    to alphanumeric. Returns ``fallback`` if the result is empty."""
    if not isinstance(raw, str) or not raw.strip():
        return fallback
    cleaned = re.sub(r"[^A-Za-z0-9_.\-]+", "_", raw.strip())
    cleaned = cleaned.strip("_.-")
    if not cleaned:
        return fallback
    if not cleaned[0].isalnum():
        cleaned = f"o{cleaned}"
    return cleaned[:64]


def auto_default_outputs(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build the seed output list returned when no map is saved yet.

    One entry per candidate, labelled from the SaveImage's
    ``filename_prefix`` if present (sanitised through :func:`_safe_label`)
    and made unique with ``_2``/``_3`` suffixes on collision."""
    used: set[str] = set()
    out: list[dict[str, Any]] = []
    for cand in candidates:
        base = _safe_label(
            cand.get("filename_prefix"),
            fallback=f"output_{cand['node_id']}",
        )
        label = base
        n = 2
        while label in used:
            label = f"{base}_{n}"
            n += 1
        used.add(label)
        out.append({
            "label": label,
            "node_id": cand["node_id"],
            "kind": "image",
        })
    return out


# --- read-time upgrade ----------------------------------------------------


def upgrade_output_slot_map(
    *, raw: Any, candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Bring a stored ``output_slot_map_json`` payload up to v1 shape.

    A ``None`` / missing value seeds from :func:`auto_default_outputs`.
    A ``version=1`` payload is filtered against the candidate set —
    entries pointing at a node that's no longer SaveImage-eligible are
    dropped silently (the editor lets the user re-pick).
    """
    if isinstance(raw, dict) and raw.get("version") == 1:
        outputs = raw.get("outputs") if isinstance(raw.get("outputs"), list) else []
        eligible_ids = {c["node_id"] for c in candidates}
        kept: list[dict[str, Any]] = []
        seen_labels: set[str] = set()
        for slot in outputs:
            if not isinstance(slot, dict):
                continue
            label = slot.get("label")
            node_id = slot.get("node_id")
            kind = slot.get("kind", "image")
            if not isinstance(label, str) or not isinstance(node_id, str):
                continue
            if node_id not in eligible_ids:
                continue
            if kind not in ALL_OUTPUT_KINDS:
                continue
            if label in seen_labels:
                continue
            seen_labels.add(label)
            kept.append({"label": label, "node_id": node_id, "kind": kind})
        return {"version": 1, "outputs": kept}

    return {"version": 1, "outputs": auto_default_outputs(candidates)}


# --- validation -----------------------------------------------------------


class OutputSlotMapValidationError(ValueError):
    """Raised when an output slot list is internally inconsistent or
    doesn't match the workflow graph + catalog."""


def validate_output_slots(
    *,
    outputs: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Validate and normalise an output slot list.

    Returns a fresh list ready for persistence. Raises
    :class:`OutputSlotMapValidationError` on the first failure with a
    self-describing message naming the offending label.
    """
    by_id = {c["node_id"]: c for c in candidates}
    seen_labels: set[str] = set()
    out: list[dict[str, Any]] = []

    for slot in outputs:
        label = slot.get("label")
        if not isinstance(label, str) or not label:
            raise OutputSlotMapValidationError("output slot is missing a label")
        if not _LABEL_PATTERN.match(label):
            raise OutputSlotMapValidationError(
                f"output slot label '{label}' is not a safe identifier "
                f"(allowed: A-Z, a-z, 0-9, '_', '.', '-')",
            )
        if label in seen_labels:
            raise OutputSlotMapValidationError(
                f"duplicate output slot label: '{label}'",
            )
        seen_labels.add(label)

        node_id = slot.get("node_id")
        if not isinstance(node_id, str) or not node_id:
            raise OutputSlotMapValidationError(
                f"output slot '{label}' is missing node_id",
            )
        cand = by_id.get(node_id)
        if cand is None:
            raise OutputSlotMapValidationError(
                f"output slot '{label}' points at node '{node_id}', which is "
                f"not a SaveImage node in this workflow (sd-chisel only "
                f"captures from {sorted(IMAGE_SAVER_CLASSES)})",
            )

        kind = slot.get("kind", "image")
        if kind not in ALL_OUTPUT_KINDS:
            raise OutputSlotMapValidationError(
                f"output slot '{label}' has unknown kind '{kind}'",
            )

        out.append({"label": label, "node_id": node_id, "kind": kind})

    return out
