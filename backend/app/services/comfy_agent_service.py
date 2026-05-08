"""Validation and seeding for comfy session agents.

The repo (:mod:`app.storage.comfy_session_agent_repo`) handles raw row
storage; this module enforces the cross-cutting rules:

- Output-slot shape per ``origin`` (preset / custom / auto).
- ``bound_to`` references a real workflow slot with ``binding=llm`` and
  a matching ``kind``.
- Single-bind rule: no two agents in the same session may target the
  same workflow slot label.
- Auto-slot resolution at bind time: when an ``origin=auto`` slot first
  gets a ``bound_to``, its ``kind`` and ``description`` are snapshotted
  from the workflow slot's metadata + the catalog node's input
  description. Subsequent edits to the workflow / catalog do not
  re-snapshot.

The service also supplies :func:`seed_default_agent` — the opt-in
"create one agent covering every binding=llm workflow slot" entry
point. It is rejected when the session already has an agent.

See ``docs/comfy-agents-redesign.md``.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from app.models.comfy import (
    ALL_SLOT_KINDS,
    PRESET_KIND,
)
from app.models.session import COMFY_LIKE_TYPES
from app.storage import (
    comfy_catalog_repo,
    session_repo,
)
from app.storage import (
    comfy_session_agent_repo as agent_repo,
)
from app.storage import (
    comfy_workflow_repo as workflow_repo,
)
from app.utils.ids import new_id


class AgentValidationError(ValueError):
    """Raised when an agent payload (CRUD body or seed_default
    precondition) violates one of the rules in this module. The API
    layer renders this as HTTP 422 (validation) or 409 (state
    conflict, e.g. seeding when agents already exist)."""

    def __init__(self, message: str, *, code: str = "validation") -> None:
        super().__init__(message)
        self.code = code


# --- helpers --------------------------------------------------------------


def _workflow_slot_lookup(slot_map: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Map ``label → slot dict`` from a saved slot map. Returns an
    empty dict when the slot map is null or version != 2 (older shapes
    are upgraded on read elsewhere; this module sees post-upgrade data
    via the API layer)."""
    if not slot_map or not isinstance(slot_map, dict):
        return {}
    slots = slot_map.get("slots") or []
    return {
        s["label"]: s
        for s in slots
        if isinstance(s, dict) and isinstance(s.get("label"), str)
    }


def _catalog_input_description(
    conn: sqlite3.Connection,
    *,
    class_type: str,
    input_name: str,
) -> str | None:
    """Return the human-readable description the catalog stored for
    this input, if any. Falls back to the node-level description when
    the per-input row has no notes. ``None`` when the node isn't in
    the catalog (auto-slot resolution accepts that — kind is still
    derived from the workflow slot)."""
    node = comfy_catalog_repo.get_node(conn, class_type)
    if node is None:
        return None
    semantic = node.get("inputs_semantic") or []
    if isinstance(semantic, list):
        for item in semantic:
            if (
                isinstance(item, dict)
                and item.get("name") == input_name
                and isinstance(item.get("notes"), str)
                and item["notes"].strip()
            ):
                return item["notes"].strip()
    desc = node.get("description_md")
    if isinstance(desc, str) and desc.strip():
        return desc.strip()
    return None


# --- output-slot validation ----------------------------------------------


def _validate_one_output_slot(
    *,
    slot: dict[str, Any],
    workflow_slots: dict[str, dict[str, Any]],
    sibling_targets: dict[str, str],
    self_agent_id: str | None,
    conn: sqlite3.Connection,
    workflow_graph: dict[str, Any] | None,
) -> dict[str, Any]:
    """Validate one slot, returning its normalised form. Caller owns
    the cross-slot uniqueness state (``sibling_targets``: workflow slot
    label → agent id that already targets it) and updates it after a
    successful return."""
    origin = slot.get("origin")
    if origin not in ("preset", "custom", "auto"):
        raise AgentValidationError(
            f"output slot has invalid origin: {origin!r}",
        )

    label = slot.get("label")
    if not isinstance(label, str) or not label.strip():
        raise AgentValidationError("output slot label is required")

    out: dict[str, Any] = {
        "id": slot.get("id") or new_id(),
        "origin": origin,
        "label": label.strip(),
        "preset": None,
        "kind": slot.get("kind"),
        "description": slot.get("description"),
        "last_value": slot.get("last_value"),
        "bound_to": None,
    }

    # --- origin-specific shape rules -------------------------------------
    if origin == "preset":
        preset = slot.get("preset")
        if preset not in PRESET_KIND:
            raise AgentValidationError(
                f"preset slot has invalid preset name: {preset!r}",
            )
        expected_kind = PRESET_KIND[preset]
        if out["kind"] is None:
            out["kind"] = expected_kind
        elif out["kind"] != expected_kind:
            raise AgentValidationError(
                f"preset {preset!r} requires kind {expected_kind!r}, "
                f"got {out['kind']!r}",
            )
        out["preset"] = preset

    elif origin == "custom":
        if slot.get("preset") is not None:
            raise AgentValidationError(
                "custom slot must not set preset",
            )
        if out["kind"] not in ALL_SLOT_KINDS:
            raise AgentValidationError(
                f"custom slot kind is required and must be one of "
                f"{sorted(ALL_SLOT_KINDS)}, got {out['kind']!r}",
            )

    elif origin == "auto":
        if slot.get("preset") is not None:
            raise AgentValidationError(
                "auto slot must not set preset",
            )
        # kind/description may be unset pre-bind; once bound, they get
        # filled from the workflow slot below.

    # --- bound_to handling ----------------------------------------------
    raw_bound = slot.get("bound_to")
    if raw_bound is not None:
        if not isinstance(raw_bound, dict):
            raise AgentValidationError("bound_to must be an object or null")
        target_label = raw_bound.get("workflow_slot_label")
        if not isinstance(target_label, str) or not target_label.strip():
            raise AgentValidationError(
                "bound_to.workflow_slot_label is required",
            )
        target_label = target_label.strip()

        ws = workflow_slots.get(target_label)
        if ws is None:
            raise AgentValidationError(
                f"bound_to references unknown workflow slot label: "
                f"{target_label!r}",
            )
        if ws.get("binding") != "llm":
            raise AgentValidationError(
                f"workflow slot {target_label!r} has binding "
                f"{ws.get('binding')!r}, expected 'llm'",
            )

        # Single-bind across siblings.
        owner = sibling_targets.get(target_label)
        if owner is not None and owner != self_agent_id:
            raise AgentValidationError(
                f"workflow slot {target_label!r} is already bound "
                f"by another agent in this session",
                code="conflict",
            )
        sibling_targets[target_label] = self_agent_id or "<self>"

        # Auto-slot resolution: snapshot kind + description from the
        # workflow slot + catalog. If kind/description are already set
        # on the agent slot, they win — the snapshot only fills gaps.
        ws_kind = ws.get("kind")
        if origin == "auto" and out["kind"] is None:
            out["kind"] = ws_kind
        if out["kind"] is None:
            raise AgentValidationError(
                f"bound auto slot {label!r} needs a workflow slot with "
                f"a defined kind (got {ws_kind!r})",
            )
        if out["kind"] != ws_kind:
            raise AgentValidationError(
                f"agent slot kind {out['kind']!r} does not match "
                f"workflow slot {target_label!r} kind {ws_kind!r}",
            )

        if origin == "auto" and not out.get("description"):
            ws_desc = ws.get("description")
            origin_pair = ws.get("origin") or {}
            class_type = None
            input_name = origin_pair.get("input_name")
            if isinstance(workflow_graph, dict) and isinstance(
                origin_pair.get("node_id"), str,
            ):
                node = workflow_graph.get(origin_pair["node_id"])
                if isinstance(node, dict):
                    raw_class = node.get("class_type")
                    if isinstance(raw_class, str):
                        class_type = raw_class
            catalog_desc = None
            if class_type and isinstance(input_name, str):
                catalog_desc = _catalog_input_description(
                    conn,
                    class_type=class_type,
                    input_name=input_name,
                )
            merged = "\n\n".join(
                part for part in (ws_desc, catalog_desc) if part
            )
            out["description"] = merged or None

        out["bound_to"] = {"workflow_slot_label": target_label}

    elif origin == "auto" and out["kind"] is None:
        # Unbound auto slot is allowed to leave kind unset.
        pass

    if out["kind"] is not None and out["kind"] not in ALL_SLOT_KINDS:
        raise AgentValidationError(
            f"unknown slot kind: {out['kind']!r}",
        )

    return out


def validate_output_slots(
    *,
    conn: sqlite3.Connection,
    session_id: str,
    self_agent_id: str | None,
    slots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Validate every output slot of one agent against the session's
    workflow slot map and the agent's siblings. Returns the slots in
    canonical form (ids assigned where missing, preset kinds filled
    in, auto slots resolved). Raises :class:`AgentValidationError` on
    the first failure."""

    # Workflow slot map context (None → empty lookup; binding to anything
    # is rejected with "unknown workflow slot label").
    workflow_slots: dict[str, dict[str, Any]] = {}
    workflow_graph: dict[str, Any] | None = None
    session = session_repo.get_session(conn, session_id)
    if session is None:
        raise AgentValidationError(
            f"session not found: {session_id!r}",
            code="not_found",
        )
    workflow_id = session.get("comfy_workflow_id")
    if workflow_id:
        workflow = workflow_repo.get_workflow(conn, workflow_id)
        if workflow is not None:
            workflow_graph = workflow.get("graph")
            workflow_slots = _workflow_slot_lookup(workflow.get("slot_map"))

    # Sibling state — start from every other agent's bindings.
    sibling_targets: dict[str, str] = {}
    for sibling in agent_repo.list_agents(conn, session_id):
        if sibling["id"] == self_agent_id:
            continue
        for s in sibling.get("output_slots") or []:
            bt = s.get("bound_to")
            if isinstance(bt, dict):
                target = bt.get("workflow_slot_label")
                if isinstance(target, str):
                    sibling_targets[target] = sibling["id"]

    # Per-slot uniqueness within this agent.
    seen_ids: set[str] = set()
    seen_labels: set[str] = set()
    out: list[dict[str, Any]] = []
    for slot in slots:
        normalised = _validate_one_output_slot(
            slot=slot,
            workflow_slots=workflow_slots,
            sibling_targets=sibling_targets,
            self_agent_id=self_agent_id,
            conn=conn,
            workflow_graph=workflow_graph,
        )
        if normalised["id"] in seen_ids:
            raise AgentValidationError(
                f"duplicate output-slot id within agent: {normalised['id']!r}",
            )
        if normalised["label"] in seen_labels:
            raise AgentValidationError(
                f"duplicate output-slot label within agent: "
                f"{normalised['label']!r}",
            )
        seen_ids.add(normalised["id"])
        seen_labels.add(normalised["label"])
        out.append(normalised)
    return out


def validate_source_scope(
    *,
    source_scope: str,
    source_ids: list[str] | None,
) -> list[str] | None:
    """Reconcile ``source_scope`` and ``source_ids``. Returns the
    canonical ``source_ids`` value (``None`` for ``all`` / ``none``;
    a non-empty list for ``selected``)."""
    if source_scope not in ("all", "selected", "none"):
        raise AgentValidationError(
            f"invalid source_scope: {source_scope!r}",
        )
    if source_scope == "selected":
        if not source_ids:
            raise AgentValidationError(
                "source_scope='selected' requires at least one source id",
            )
        # We don't verify the ids exist on the session here — sources
        # come and go on i2i sessions, and an agent referring to a
        # since-deleted source should fall back to skipping it at run
        # time rather than blocking edits. The run path handles that.
        return list(source_ids)
    if source_ids:
        raise AgentValidationError(
            f"source_ids must be empty when source_scope={source_scope!r}",
        )
    return None


# --- seeding --------------------------------------------------------------


def seed_default_agent(
    *,
    conn: sqlite3.Connection,
    session_id: str,
) -> dict[str, Any]:
    """Create one agent covering every ``binding=llm`` workflow slot.

    Preconditions (all enforced; AgentValidationError on failure):

    - The session exists, is a comfy session, and is bound to a workflow.
    - The session has no agents yet.
    - The bound workflow has at least one ``binding=llm`` slot.

    The seeded agent is named ``"Default composer"``, has an empty
    prompt, ``source_scope='all'``, ``loras_enabled=False``, and one
    output slot per matching workflow slot. Each output slot is created
    with ``origin='auto'``: kind + description are snapshotted from the
    workflow slot + catalog at this moment, exactly like the bind-time
    auto-resolution path.
    """
    session = session_repo.get_session(conn, session_id)
    if session is None:
        raise AgentValidationError(
            f"session not found: {session_id!r}", code="not_found",
        )
    if session.get("session_type") not in COMFY_LIKE_TYPES:
        raise AgentValidationError(
            "session is not a comfy session", code="conflict",
        )
    workflow_id = session.get("comfy_workflow_id")
    if not workflow_id:
        raise AgentValidationError(
            "comfy session is not bound to a workflow", code="conflict",
        )
    workflow = workflow_repo.get_workflow(conn, workflow_id)
    if workflow is None:
        raise AgentValidationError(
            f"bound workflow not found: {workflow_id!r}", code="conflict",
        )

    if agent_repo.count_agents(conn, session_id) > 0:
        raise AgentValidationError(
            "session already has at least one agent — seed is opt-in "
            "for empty sessions only",
            code="conflict",
        )

    workflow_slots = _workflow_slot_lookup(workflow.get("slot_map"))
    llm_slots = [
        s for s in workflow_slots.values() if s.get("binding") == "llm"
    ]
    if not llm_slots:
        raise AgentValidationError(
            "bound workflow has no binding=llm slots to seed",
            code="conflict",
        )

    # Sort the seeded outputs by (group, ordinal, label) the same way
    # the slot-map renders them, so the agent's output list mirrors
    # what the user sees in the slot panel.
    def _sort_key(s: dict[str, Any]) -> tuple[str, int, str]:
        return (
            s.get("group") or "",
            s.get("ordinal") if isinstance(s.get("ordinal"), int) else 1_000_000,
            s.get("label") or "",
        )

    seed_slots: list[dict[str, Any]] = []
    for ws in sorted(llm_slots, key=_sort_key):
        seed_slots.append({
            "id": new_id(),
            "origin": "auto",
            "label": ws["label"],
            "kind": None,  # filled in by validate_output_slots via bind_to
            "description": None,
            "last_value": None,
            "bound_to": {"workflow_slot_label": ws["label"]},
        })

    normalised = validate_output_slots(
        conn=conn,
        session_id=session_id,
        self_agent_id=None,
        slots=seed_slots,
    )

    return agent_repo.insert_agent(
        conn,
        session_id=session_id,
        name="Default composer",
        prompt="",
        model_name=None,
        model_params=None,
        source_scope="all",
        source_ids=None,
        loras_enabled=False,
        output_slots=normalised,
    )
