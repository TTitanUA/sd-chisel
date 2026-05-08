"""Tests for /api/comfy/sessions/{id}/slot_map (Phase 2.5).

Phase 2.5 replaces Phase 2's fixed three-slot dict with a per-workflow
list of labelled, typed slots. The API contract carries
``{slot_map: {version, slots[]}, candidates: {<kind>: [...]}, inferred_mode}``;
older v1 payloads in storage are upgraded on read.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_conn
from app.main import app
from app.services import comfy_slot_map_service
from app.storage import comfy_workflow_repo
from app.storage import db as db_mod
from app.storage.migrations import apply_pending


@pytest.fixture
def conn(tmp_path):
    c = db_mod.connect(tmp_path / "s.db")
    apply_pending(c, Path(__file__).parent.parent / "migrations")
    yield c
    c.close()


@pytest.fixture
def client(conn):
    app.dependency_overrides[get_conn] = lambda: conn
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


# Realistic API-format SDXL t2i + i2i hybrid workflow with two text
# encoders (positive + negative), one LoadImage, plus a KSampler.
SAMPLE_GRAPH = {
    "3": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 0,
            "steps": 20,
            "cfg": 7.5,
            "model": ["4", 0],
            "positive": ["6", 0],
            "negative": ["7", 0],
            "latent_image": ["10", 0],
        },
    },
    "4": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "sd_xl_base.safetensors"},
    },
    "6": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "a cat", "clip": ["4", 1]},
    },
    "7": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "low quality", "clip": ["4", 1]},
    },
    "10": {
        "class_type": "LoadImage",
        "inputs": {"image": "ref.png", "upload": "image"},
    },
}


def _make_comfy_session(client, *, workflow_id) -> dict:
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    return client.post(
        f"/api/projects/{pid}/sessions",
        json={
            "session_type": "comfy",
            "name": "comfy",
            "model_name": None,
            "use_negative": True,
            "comfy_workflow_id": workflow_id,
        },
    ).json()


def _seed_node(
    conn,
    *,
    class_type: str,
    pack_name: str = "ComfyUI",
    inputs_raw: dict | None = None,
):
    """Insert a minimal catalog row so compute_candidates classifies
    the node's inputs correctly. Test fixture only — bypasses the
    import wizard."""
    conn.execute(
        "INSERT OR IGNORE INTO comfy_packs(name, display_name, imported_at) "
        "VALUES (?, ?, 0)",
        (pack_name, pack_name),
    )
    import json as _json
    conn.execute(
        "INSERT INTO comfy_nodes(class_type, pack_name, display_name, "
        "  inputs_raw_json, outputs_raw_json, inputs_semantic_json, "
        "  description_md, imported_at, last_seen_in_object_info_at) "
        "VALUES (?, ?, ?, ?, '[]', '[]', '', 0, 0)",
        (class_type, pack_name, class_type, _json.dumps(inputs_raw or {})),
    )


def _seed_realistic_catalog(conn):
    _seed_node(
        conn,
        class_type="CLIPTextEncode",
        inputs_raw={
            "required": {
                "text": ["STRING", {"multiline": True}],
                "clip": ["CLIP", {}],
            },
        },
    )
    _seed_node(
        conn,
        class_type="LoadImage",
        inputs_raw={
            "required": {
                "image": [["ref.png", "other.png"], {"image_upload": True}],
            },
        },
    )
    _seed_node(
        conn,
        class_type="KSampler",
        inputs_raw={
            "required": {
                "seed": ["INT", {"default": 0, "min": 0, "max": 1_000_000}],
                "steps": ["INT", {"default": 20, "min": 1, "max": 200}],
                "cfg": ["FLOAT", {"default": 7.5, "min": 0, "max": 30}],
                "model": ["MODEL", {}],
            },
        },
    )
    _seed_node(
        conn,
        class_type="CheckpointLoaderSimple",
        inputs_raw={
            "required": {"ckpt_name": [["sd_xl_base.safetensors"], {}]},
        },
    )


def _create_workflow(client, *, graph=None) -> dict:
    return client.post(
        "/api/comfy/workflows",
        json={"name": "W", "graph": graph or SAMPLE_GRAPH},
    ).json()


# --- GET shape -----------------------------------------------------------


def test_slot_map_returns_v2_envelope_with_empty_slots(client, conn):
    _seed_realistic_catalog(conn)
    wf = _create_workflow(client)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    resp = client.get(f"/api/comfy/sessions/{s['id']}/slot_map")
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == s["id"]
    assert body["workflow_id"] == wf["id"]
    assert body["slot_map"] == {"version": 2, "slots": []}
    assert body["inferred_mode"] == "t2i"
    # Every kind bucket is always present.
    for kind in (
        "text", "multiline_text", "image", "image_alpha",
        "number_int", "number_float", "boolean",
        "enum", "lora_name", "checkpoint_name",
    ):
        assert kind in body["candidates"]


def test_slot_map_text_candidates_classify_multiline(client, conn):
    _seed_realistic_catalog(conn)
    wf = _create_workflow(client)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    body = client.get(f"/api/comfy/sessions/{s['id']}/slot_map").json()
    # CLIPTextEncode.text is multiline=True in the seeded schema, so
    # candidates land in the multiline_text bucket.
    multi = {(c["node_id"], c["input_name"]) for c in body["candidates"]["multiline_text"]}
    assert multi == {("6", "text"), ("7", "text")}
    by_id = {c["node_id"]: c for c in body["candidates"]["multiline_text"]}
    assert by_id["6"]["current_value"] == "a cat"
    assert by_id["6"]["kind"] == "multiline_text"


def test_slot_map_image_candidates_filter_by_image_upload(client, conn):
    _seed_realistic_catalog(conn)
    wf = _create_workflow(client)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    body = client.get(f"/api/comfy/sessions/{s['id']}/slot_map").json()
    image_pairs = {
        (c["node_id"], c["input_name"]) for c in body["candidates"]["image"]
    }
    assert image_pairs == {("10", "image")}


def test_slot_map_image_kind_only_for_loadimage_class(client, conn):
    """A custom node that declares ``image_upload=True`` should not
    appear in the ``image`` bucket — Phase 3's upload + patch path
    only supports the core LoadImage class. Such a custom node falls
    through to ``enum`` so the user can still frozen-bind it."""
    _seed_realistic_catalog(conn)
    _seed_node(
        conn,
        class_type="LoadImageFromUrl",
        pack_name="custom-pack",
        inputs_raw={
            "required": {
                "image": [["a.png", "b.png"], {"image_upload": True}],
            },
        },
    )
    graph = {
        **SAMPLE_GRAPH,
        "11": {
            "class_type": "LoadImageFromUrl",
            "inputs": {"image": "a.png"},
        },
    }
    wf = _create_workflow(client, graph=graph)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    body = client.get(f"/api/comfy/sessions/{s['id']}/slot_map").json()

    image_pairs = {
        (c["node_id"], c["input_name"]) for c in body["candidates"]["image"]
    }
    # Only the core LoadImage shows up — the custom URL loader is gated.
    assert image_pairs == {("10", "image")}

    # The custom node's input is downgraded to enum so the user can
    # still freeze it manually (e.g. "always pin to a.png").
    enum_pairs = {
        (c["node_id"], c["input_name"]) for c in body["candidates"]["enum"]
    }
    assert ("11", "image") in enum_pairs


def test_put_slot_map_rejects_save_image_input(client, conn):
    """Saver nodes are owned by the output slot map — their inputs
    (e.g. ``filename_prefix``) cannot also be mapped here."""
    _seed_realistic_catalog(conn)
    _seed_node(
        conn,
        class_type="SaveImage",
        inputs_raw={
            "required": {
                "filename_prefix": ["STRING", {"default": "ComfyUI"}],
                "images": ["IMAGE", {}],
            },
        },
    )
    graph = {
        **SAMPLE_GRAPH,
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "ComfyUI", "images": ["3", 0]},
        },
    }
    wf = _create_workflow(client, graph=graph)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    resp = client.put(
        f"/api/comfy/sessions/{s['id']}/slot_map",
        json={
            "slots": [{
                "label": "prefix",
                "group": None,
                "ordinal": 1,
                "description": None,
                "kind": "text",
                "origin": {"node_id": "9", "input_name": "filename_prefix"},
                "binding": "llm",
                "metadata": {},
            }],
        },
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "saver" in detail.lower() or "SaveImage" in detail


def test_put_slot_map_rejects_non_loadimage_image_origin(client, conn):
    """Defence-in-depth: a hand-crafted PUT can't sneak an image-kind
    slot through with a non-LoadImage origin."""
    _seed_realistic_catalog(conn)
    _seed_node(
        conn,
        class_type="LoadImageFromUrl",
        pack_name="custom-pack",
        inputs_raw={
            "required": {
                "image": [["a.png"], {"image_upload": True}],
            },
        },
    )
    graph = {
        **SAMPLE_GRAPH,
        "11": {
            "class_type": "LoadImageFromUrl",
            "inputs": {"image": "a.png"},
        },
    }
    wf = _create_workflow(client, graph=graph)
    s = _make_comfy_session(client, workflow_id=wf["id"])

    # The candidate at ("11", "image") is an enum after the gate, so
    # the kind-mismatch check fires — message names the right node.
    resp = client.put(
        f"/api/comfy/sessions/{s['id']}/slot_map",
        json={
            "slots": [{
                "label": "img",
                "group": None,
                "ordinal": 1,
                "description": None,
                "kind": "image",
                "origin": {"node_id": "11", "input_name": "image"},
                "binding": "user_image",
                "metadata": {},
            }],
        },
    )
    assert resp.status_code == 422
    assert "image" in resp.json()["detail"].lower()


def test_slot_map_classifies_numbers_and_checkpoint(client, conn):
    _seed_realistic_catalog(conn)
    wf = _create_workflow(client)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    body = client.get(f"/api/comfy/sessions/{s['id']}/slot_map").json()

    int_pairs = {(c["node_id"], c["input_name"]) for c in body["candidates"]["number_int"]}
    assert ("3", "seed") in int_pairs
    assert ("3", "steps") in int_pairs

    float_pairs = {(c["node_id"], c["input_name"]) for c in body["candidates"]["number_float"]}
    assert ("3", "cfg") in float_pairs

    ckpt_pairs = {(c["node_id"], c["input_name"]) for c in body["candidates"]["checkpoint_name"]}
    assert ("4", "ckpt_name") in ckpt_pairs


def test_slot_map_excludes_wired_inputs(client, conn):
    _seed_realistic_catalog(conn)
    wf = _create_workflow(client)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    body = client.get(f"/api/comfy/sessions/{s['id']}/slot_map").json()
    # KSampler.model is wired (["4", 0]); never eligible.
    flat = [
        (c["node_id"], c["input_name"])
        for items in body["candidates"].values() for c in items
    ]
    assert ("3", "model") not in flat


# --- PUT round-trip ------------------------------------------------------


def test_put_slots_persists_and_round_trips(client, conn):
    _seed_realistic_catalog(conn)
    wf = _create_workflow(client)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    payload = {
        "slots": [
            {
                "label": "main_positive",
                "group": None,
                "ordinal": 1,
                "description": None,
                "kind": "multiline_text",
                "origin": {"node_id": "6", "input_name": "text"},
                "binding": "llm",
                "metadata": {},
            },
            {
                "label": "main_negative",
                "group": None,
                "ordinal": 2,
                "description": None,
                "kind": "multiline_text",
                "origin": {"node_id": "7", "input_name": "text"},
                "binding": "llm",
                "metadata": {},
            },
            {
                "label": "main_image",
                "group": None,
                "ordinal": 3,
                "description": None,
                "kind": "image",
                "origin": {"node_id": "10", "input_name": "image"},
                "binding": "user_image",
                "metadata": {},
            },
        ],
    }
    resp = client.put(
        f"/api/comfy/sessions/{s['id']}/slot_map", json=payload,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["slot_map"]["version"] == 2
    saved = body["slot_map"]["slots"]
    assert [slot["label"] for slot in saved] == [
        "main_positive", "main_negative", "main_image",
    ]
    assert body["inferred_mode"] == "i2i"

    again = client.get(f"/api/comfy/sessions/{s['id']}/slot_map").json()
    assert again["slot_map"] == body["slot_map"]


def test_put_rejects_kind_mismatch(client, conn):
    _seed_realistic_catalog(conn)
    wf = _create_workflow(client)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    resp = client.put(
        f"/api/comfy/sessions/{s['id']}/slot_map",
        json={
            "slots": [
                {
                    "label": "wrong",
                    "kind": "image",
                    "origin": {"node_id": "6", "input_name": "text"},
                    "binding": "user_image",
                    "metadata": {},
                },
            ],
        },
    )
    assert resp.status_code == 422
    assert "wrong" in resp.json()["detail"]


def test_put_rejects_bad_origin(client, conn):
    _seed_realistic_catalog(conn)
    wf = _create_workflow(client)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    resp = client.put(
        f"/api/comfy/sessions/{s['id']}/slot_map",
        json={
            "slots": [
                {
                    "label": "ghost",
                    "kind": "multiline_text",
                    "origin": {"node_id": "9999", "input_name": "text"},
                    "binding": "llm",
                    "metadata": {},
                },
            ],
        },
    )
    assert resp.status_code == 422


def test_put_rejects_duplicate_labels(client, conn):
    _seed_realistic_catalog(conn)
    wf = _create_workflow(client)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    resp = client.put(
        f"/api/comfy/sessions/{s['id']}/slot_map",
        json={
            "slots": [
                {
                    "label": "p", "kind": "multiline_text",
                    "origin": {"node_id": "6", "input_name": "text"},
                    "binding": "llm", "metadata": {},
                },
                {
                    "label": "p", "kind": "multiline_text",
                    "origin": {"node_id": "7", "input_name": "text"},
                    "binding": "llm", "metadata": {},
                },
            ],
        },
    )
    assert resp.status_code == 422


def test_put_rejects_disallowed_binding(client, conn):
    _seed_realistic_catalog(conn)
    wf = _create_workflow(client)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    # llm is not allowed for image kinds.
    resp = client.put(
        f"/api/comfy/sessions/{s['id']}/slot_map",
        json={
            "slots": [
                {
                    "label": "img", "kind": "image",
                    "origin": {"node_id": "10", "input_name": "image"},
                    "binding": "llm", "metadata": {},
                },
            ],
        },
    )
    assert resp.status_code == 422


def test_put_rejects_library_loras_binding(client, conn):
    _seed_realistic_catalog(conn)
    wf = _create_workflow(client)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    resp = client.put(
        f"/api/comfy/sessions/{s['id']}/slot_map",
        json={
            "slots": [
                {
                    "label": "loras", "kind": "lora_name",
                    "origin": {"node_id": "4", "input_name": "ckpt_name"},
                    "binding": "library_loras", "metadata": {},
                },
            ],
        },
    )
    # Pydantic rejects the binding before service validation when it
    # isn't a Literal value, so 422 either way.
    assert resp.status_code == 422


def test_put_clears_with_empty_slots(client, conn):
    _seed_realistic_catalog(conn)
    wf = _create_workflow(client)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    client.put(
        f"/api/comfy/sessions/{s['id']}/slot_map",
        json={
            "slots": [
                {
                    "label": "pp", "kind": "multiline_text",
                    "origin": {"node_id": "6", "input_name": "text"},
                    "binding": "llm", "metadata": {},
                },
            ],
        },
    )
    body = client.put(
        f"/api/comfy/sessions/{s['id']}/slot_map", json={"slots": []},
    ).json()
    assert body["slot_map"]["slots"] == []


def test_frozen_seed_value_validates_range(client, conn):
    _seed_realistic_catalog(conn)
    wf = _create_workflow(client)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    # In-range seed → ok.
    ok = client.put(
        f"/api/comfy/sessions/{s['id']}/slot_map",
        json={
            "slots": [
                {
                    "label": "seed", "kind": "number_int",
                    "origin": {"node_id": "3", "input_name": "seed"},
                    "binding": "frozen", "metadata": {"value": 12345},
                },
            ],
        },
    )
    assert ok.status_code == 200
    # Out-of-range → 422.
    bad = client.put(
        f"/api/comfy/sessions/{s['id']}/slot_map",
        json={
            "slots": [
                {
                    "label": "seed", "kind": "number_int",
                    "origin": {"node_id": "3", "input_name": "seed"},
                    "binding": "frozen", "metadata": {"value": 9_999_999_999},
                },
            ],
        },
    )
    assert bad.status_code == 422


# --- legacy upgrade ------------------------------------------------------


def test_legacy_v1_payload_upgrades_lazily(client, conn):
    """A row written by Phase 2 (no version key, three-slot dict)
    should appear as a v2 envelope on the next GET."""
    _seed_realistic_catalog(conn)
    wf = _create_workflow(client)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    # Bypass the API and write a legacy payload directly.
    comfy_workflow_repo.set_slot_map(
        conn,
        workflow_id=wf["id"],
        slot_map={
            "positive_prompt": {"node_id": "6", "input_name": "text"},
            "negative_prompt": {"node_id": "7", "input_name": "text"},
            "main_image": {"node_id": "10", "input_name": "image"},
        },
    )
    conn.commit()

    body = client.get(f"/api/comfy/sessions/{s['id']}/slot_map").json()
    assert body["slot_map"]["version"] == 2
    labels = [s["label"] for s in body["slot_map"]["slots"]]
    assert labels == ["positive_prompt", "negative_prompt", "main_image"]
    bindings = [s["binding"] for s in body["slot_map"]["slots"]]
    assert bindings == ["llm", "llm", "user_image"]
    kinds = [s["kind"] for s in body["slot_map"]["slots"]]
    assert kinds == ["multiline_text", "multiline_text", "image"]
    assert body["inferred_mode"] == "i2i"


def test_legacy_payload_with_only_positive_drops_others(client, conn):
    _seed_realistic_catalog(conn)
    wf = _create_workflow(client)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    comfy_workflow_repo.set_slot_map(
        conn,
        workflow_id=wf["id"],
        slot_map={
            "positive_prompt": {"node_id": "6", "input_name": "text"},
            "negative_prompt": None,
            "main_image": None,
        },
    )
    conn.commit()
    body = client.get(f"/api/comfy/sessions/{s['id']}/slot_map").json()
    assert [s["label"] for s in body["slot_map"]["slots"]] == ["positive_prompt"]
    assert body["inferred_mode"] == "t2i"


# --- meta and uncatalogued nodes -----------------------------------------


def test_slot_map_propagates_meta_title(client, conn):
    """User-set ``_meta.title`` from the ComfyUI canvas is the only
    thing distinguishing two nodes of the same class."""
    _seed_realistic_catalog(conn)
    graph = {
        **SAMPLE_GRAPH,
        "6": {**SAMPLE_GRAPH["6"], "_meta": {"title": "Positive prompt"}},
        "7": {**SAMPLE_GRAPH["7"], "_meta": {"title": "Negative prompt"}},
    }
    wf = _create_workflow(client, graph=graph)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    body = client.get(f"/api/comfy/sessions/{s['id']}/slot_map").json()
    by_id = {c["node_id"]: c for c in body["candidates"]["multiline_text"]}
    assert by_id["6"]["node_title"] == "Positive prompt"
    assert by_id["7"]["node_title"] == "Negative prompt"


def test_compute_candidates_falls_back_when_node_not_in_catalog(conn):
    """A workflow may reference a class_type the user hasn't imported
    yet. The candidate computer still classifies literal scalars from
    the value alone, with ``node_in_catalog=False`` so the UI flags
    them. Combo subtypes can't be detected without the catalog."""
    graph = {
        "1": {
            "class_type": "MysteryEncoder",
            "inputs": {
                "prompt": "hello",
                "weight": 0.5,
                "steps": 7,
                "use_clip": True,
                "wired": ["2", 0],
            },
        },
    }
    candidates = comfy_slot_map_service.compute_candidates(conn=conn, graph=graph)
    text_pairs = {(c["node_id"], c["input_name"]) for c in candidates["text"]}
    int_pairs = {(c["node_id"], c["input_name"]) for c in candidates["number_int"]}
    float_pairs = {(c["node_id"], c["input_name"]) for c in candidates["number_float"]}
    bool_pairs = {(c["node_id"], c["input_name"]) for c in candidates["boolean"]}
    assert text_pairs == {("1", "prompt")}
    assert int_pairs == {("1", "steps")}
    assert float_pairs == {("1", "weight")}
    assert bool_pairs == {("1", "use_clip")}
    assert candidates["text"][0]["node_in_catalog"] is False


# --- session-shape errors ------------------------------------------------


def test_slot_map_404_when_session_unknown(client):
    resp = client.get("/api/comfy/sessions/ghost/slot_map")
    assert resp.status_code == 404


def test_slot_map_409_when_session_not_comfy(client):
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    s = client.post(
        f"/api/projects/{pid}/sessions",
        json={
            "session_type": "t2i", "name": "t2i",
            "model_name": None, "use_negative": False,
        },
    ).json()
    assert "id" in s, s
    resp = client.get(f"/api/comfy/sessions/{s['id']}/slot_map")
    assert resp.status_code == 409
