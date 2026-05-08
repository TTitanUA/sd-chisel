"""Unit tests for ``comfy_graph_patcher`` — write resolved slot values
into a deep-copy of the workflow's ``graph_json`` for the Single Run
pipeline.

Covers: every binding kind, the "no origin" / "no value" / "missing
node" / "missing input" / "wired-input" warning paths, and the
input-graph-not-mutated invariant.
"""
from __future__ import annotations

from app.services import comfy_graph_patcher


def _slot(label: str, binding: str, *, node_id: str, input_name: str, **md):
    return {
        "label": label,
        "group": None,
        "ordinal": None,
        "description": None,
        "kind": md.pop("kind", "multiline_text"),
        "origin": {"node_id": node_id, "input_name": input_name},
        "binding": binding,
        "metadata": md,
    }


def test_patches_llm_frozen_and_user_image_slots():
    graph = {
        "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}},
        "2": {"class_type": "KSampler", "inputs": {"seed": 0}},
        "3": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
    }
    slot_map = [
        _slot("positive", "llm", node_id="1", input_name="text"),
        _slot("seed", "frozen", node_id="2", input_name="seed", kind="number_int"),
        _slot("main_image", "user_image", node_id="3", input_name="image", kind="image"),
    ]
    payload = {
        "positive": "a hyper-realistic portrait",
        "seed": 12345,
        "main_image": "uploaded_abc.png",
    }

    result = comfy_graph_patcher.patch_graph(
        graph=graph, slot_map=slot_map, payload=payload,
    )

    assert result.graph["1"]["inputs"]["text"] == "a hyper-realistic portrait"
    assert result.graph["2"]["inputs"]["seed"] == 12345
    assert result.graph["3"]["inputs"]["image"] == "uploaded_abc.png"
    assert result.warnings == []
    assert ("positive", "1", "text") in result.patched_inputs
    assert ("seed", "2", "seed") in result.patched_inputs
    assert ("main_image", "3", "image") in result.patched_inputs


def test_does_not_mutate_input_graph():
    graph = {"1": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}}}
    slot_map = [_slot("positive", "llm", node_id="1", input_name="text")]

    comfy_graph_patcher.patch_graph(
        graph=graph, slot_map=slot_map, payload={"positive": "new"},
    )

    assert graph["1"]["inputs"]["text"] == "old"


def test_skips_slot_without_origin():
    graph = {"1": {"class_type": "X", "inputs": {}}}
    slot = {
        "label": "no_origin",
        "group": None,
        "ordinal": None,
        "description": None,
        "kind": "multiline_text",
        "origin": None,
        "binding": "llm",
        "metadata": {},
    }
    result = comfy_graph_patcher.patch_graph(
        graph=graph, slot_map=[slot], payload={"no_origin": "v"},
    )
    assert result.patched_inputs == []
    assert result.warnings == []


def test_skips_slot_missing_in_payload():
    graph = {"1": {"class_type": "CLIPTextEncode", "inputs": {"text": "baked"}}}
    slot_map = [_slot("positive", "llm", node_id="1", input_name="text")]

    result = comfy_graph_patcher.patch_graph(
        graph=graph, slot_map=slot_map, payload={},
    )

    # Graph kept its baked literal; nothing patched, no warning.
    assert result.graph["1"]["inputs"]["text"] == "baked"
    assert result.patched_inputs == []
    assert result.warnings == []


def test_warns_when_node_missing():
    graph = {"1": {"class_type": "X", "inputs": {"a": 1}}}
    slot_map = [_slot("orphan", "llm", node_id="999", input_name="text")]

    result = comfy_graph_patcher.patch_graph(
        graph=graph, slot_map=slot_map, payload={"orphan": "v"},
    )
    assert result.patched_inputs == []
    assert result.warnings == [
        "slot 'orphan' targets node '999' which is not in the graph; "
        "leaving untouched",
    ]


def test_warns_when_input_missing_on_node():
    graph = {"1": {"class_type": "X", "inputs": {"a": 1}}}
    slot_map = [_slot("typo", "llm", node_id="1", input_name="text")]

    result = comfy_graph_patcher.patch_graph(
        graph=graph, slot_map=slot_map, payload={"typo": "v"},
    )
    assert result.patched_inputs == []
    assert any("not present on the node" in w for w in result.warnings)


def test_refuses_to_patch_wired_input():
    # When a CLIPTextEncode's `clip` input is wired from node 4, the
    # value is a [node_id, output_index] list. Patching it would
    # silently disconnect the wire — refuse + warn.
    graph = {
        "1": {"class_type": "CLIPTextEncode",
              "inputs": {"text": "ok", "clip": ["4", 0]}},
    }
    slot_map = [_slot("clip", "llm", node_id="1", input_name="clip")]

    result = comfy_graph_patcher.patch_graph(
        graph=graph, slot_map=slot_map, payload={"clip": "should-not-write"},
    )
    assert result.graph["1"]["inputs"]["clip"] == ["4", 0]
    assert result.patched_inputs == []
    assert any("wired from another node" in w for w in result.warnings)


def test_rejects_library_loras_binding_defensively():
    graph = {"1": {"class_type": "X", "inputs": {"loras": "old"}}}
    slot_map = [_slot("loras", "library_loras", node_id="1", input_name="loras")]

    result = comfy_graph_patcher.patch_graph(
        graph=graph, slot_map=slot_map, payload={"loras": "new"},
    )
    assert result.graph["1"]["inputs"]["loras"] == "old"
    assert result.patched_inputs == []
    assert any("library_loras" in w for w in result.warnings)
