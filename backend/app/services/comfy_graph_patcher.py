"""Graph patcher — write resolved slot values into a workflow's
``graph_json`` for the Single Run pipeline.

Input:

* ``graph`` — the API-format graph from ``comfy_workflows.graph_json``.
  A dict keyed by string node id; each node has ``class_type`` and
  ``inputs``. Inputs are either literals (the patcher's targets) or
  ``[wire_node_id, output_index]`` lists (left untouched).
* ``slot_map`` — the v2 slot list snapshotted at run time
  (``comfy_jobs.slot_map_snapshot_json``). The orchestrator freezes
  it before patching so a workflow replace mid-flight can't shift
  the targets.
* ``payload`` — flat dict ``slot_label → value``. The orchestrator
  builds this by walking the slot map and resolving each binding:
  ``llm`` from the bound agent's ``last_value``, ``frozen`` from
  ``metadata.value`` (overrides applied), ``user_image`` from the
  uploaded ComfyUI filename. Slots not in ``payload`` are skipped
  (the graph keeps its baked literal).

The patcher does not mutate the input graph — it deep-copies and
returns the patched copy. Any slot whose ``origin`` doesn't match a
node/input in the graph is recorded as a warning and otherwise
ignored; the caller decides whether warnings escalate to failures.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PatchResult:
    """The patched graph plus a per-slot warning trail.

    ``patched_inputs`` lists every (slot_label, node_id, input_name)
    that was actually written, in slot-list order. ``warnings`` is a
    parallel list of human-readable strings — bound but unwritten
    slots (no value in payload, missing node, missing input, rejected
    binding). The orchestrator emits these as ``patch_warning`` events
    on the run's SSE channel.
    """
    graph: dict[str, Any]
    patched_inputs: list[tuple[str, str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def patch_graph(
    *,
    graph: dict[str, Any],
    slot_map: list[dict[str, Any]],
    payload: dict[str, Any],
) -> PatchResult:
    out = copy.deepcopy(graph)
    result = PatchResult(graph=out)

    for slot in slot_map:
        label = slot.get("label")
        if not isinstance(label, str):
            continue
        origin = slot.get("origin") or {}
        node_id = origin.get("node_id")
        input_name = origin.get("input_name")
        binding = slot.get("binding")

        # No origin = the user labelled the slot but never wired it to
        # a graph input. Nothing to patch; the caller already knows
        # this slot has no value path.
        if not isinstance(node_id, str) or not isinstance(input_name, str):
            continue

        if binding == "library_loras":
            # Reserved binding — should never reach the patcher (the
            # slot-map editor disallows it and the validator 422s on
            # save). Treat as a defensive warning and skip.
            result.warnings.append(
                f"slot '{label}' has binding 'library_loras' — "
                "deferred to L4, not patched",
            )
            continue

        if label not in payload:
            # The orchestrator left this slot out of the payload.
            # Either an llm slot whose agent had no last_value (the
            # validator should have blocked the run earlier — defensive
            # warning here), a user_image slot the user did not pick,
            # or a frozen slot with no value. Leave the graph's baked
            # literal alone.
            continue

        node = out.get(node_id)
        if not isinstance(node, dict):
            result.warnings.append(
                f"slot '{label}' targets node {node_id!r} which is not "
                "in the graph; leaving untouched",
            )
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            result.warnings.append(
                f"slot '{label}' targets node {node_id!r} which has no "
                "inputs map; leaving untouched",
            )
            continue
        if input_name not in inputs:
            result.warnings.append(
                f"slot '{label}' targets {node_id}.{input_name} which is "
                "not present on the node; leaving untouched",
            )
            continue
        existing = inputs[input_name]
        if isinstance(existing, list):
            # The slot's targeted input is wired (literal_or_wire is a
            # list). Patching a wire would silently disconnect the
            # upstream node — refuse and warn.
            result.warnings.append(
                f"slot '{label}' targets {node_id}.{input_name} which "
                "is wired from another node; leaving untouched",
            )
            continue

        inputs[input_name] = payload[label]
        result.patched_inputs.append((label, node_id, input_name))

    return result
