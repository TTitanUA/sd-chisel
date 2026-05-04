"""Compute per-class_type readiness for a workflow against a running
ComfyUI plus the local catalog.

This is the read side of the Phase 1 readiness gate. It enumerates the
distinct class_types referenced by the bound workflow's graph, asks
ComfyUI which of them are currently loaded (``/api/object_info``), and
cross-references with the local ``comfy_nodes`` table to bucket each
class_type into ``ready`` / ``needs_config`` / ``not_installed``.

In Phase 1 ``comfy_nodes`` is always empty until the per-node import
wizard ships, so every installed class_type comes back as
``needs_config``. The shape stays the same once the wizard lands — it
just starts producing rows.
"""
from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.services import comfy_packs

ReadinessStatus = Literal["ready", "needs_config", "not_installed"]


@dataclass
class ReadinessCard:
    class_type: str
    status: ReadinessStatus
    instance_count: int
    display_name: str | None
    description: str | None
    category: str | None
    python_module: str | None
    pack_name: str | None


def extract_class_types(graph: dict[str, Any]) -> Counter[str]:
    """Return a Counter of class_type → number of times it appears in
    the graph. Non-conformant entries (no class_type, wrong type) are
    silently skipped — graph validation belongs at upload time."""
    counter: Counter[str] = Counter()
    for node in graph.values():
        if not isinstance(node, dict):
            continue
        ct = node.get("class_type")
        if isinstance(ct, str) and ct:
            counter[ct] += 1
    return counter


def _configured_class_types(
    conn: sqlite3.Connection, class_types: list[str],
) -> set[str]:
    """Return the subset of ``class_types`` that have a fully-configured
    ``comfy_nodes`` row (description + semantic schema present, OR the
    node is marked as not requiring semantic config)."""
    if not class_types:
        return set()
    placeholders = ",".join(["?"] * len(class_types))
    rows = conn.execute(
        f"SELECT class_type FROM comfy_nodes "
        f"WHERE class_type IN ({placeholders}) "
        f"  AND ("
        f"    requires_semantic_config = 0"
        f"    OR (description_md != '' AND inputs_semantic_json != '[]')"
        f"  )",
        class_types,
    ).fetchall()
    return {r["class_type"] for r in rows}


def compute_readiness(
    *,
    conn: sqlite3.Connection,
    graph: dict[str, Any],
    object_info: dict[str, Any],
    comfyui_path: Path | None,
) -> tuple[bool, list[ReadinessCard]]:
    """Compute readiness for a workflow graph.

    Returns ``(all_ready, cards)``. ``cards`` is sorted alphabetically
    by class_type for stable ordering in the UI.
    """
    counts = extract_class_types(graph)
    class_types = sorted(counts.keys())
    configured = _configured_class_types(conn, class_types)

    cards: list[ReadinessCard] = []
    for ct in class_types:
        info = object_info.get(ct) if isinstance(object_info, dict) else None

        if info is None or not isinstance(info, dict):
            cards.append(ReadinessCard(
                class_type=ct,
                status="not_installed",
                instance_count=counts[ct],
                display_name=None,
                description=None,
                category=None,
                python_module=None,
                pack_name=None,
            ))
            continue

        python_module = _str_or_none(info.get("python_module"))
        pack_name: str | None = None
        if python_module and comfyui_path is not None:
            try:
                loc = comfy_packs.locate_pack(
                    python_module=python_module,
                    comfyui_path=comfyui_path,
                )
                pack_name = loc.name
            except Exception:
                # locate_pack is total; this branch is defensive only.
                pack_name = None

        status: ReadinessStatus = "ready" if ct in configured else "needs_config"
        cards.append(ReadinessCard(
            class_type=ct,
            status=status,
            instance_count=counts[ct],
            display_name=_str_or_none(info.get("display_name")) or ct,
            description=_str_or_none(info.get("description")),
            category=_str_or_none(info.get("category")),
            python_module=python_module,
            pack_name=pack_name,
        ))

    all_ready = bool(cards) and all(c.status == "ready" for c in cards)
    return all_ready, cards


def _str_or_none(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None
