"""Tests for /api/comfy/sessions/{id}/slot_map (Phase 2)."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_conn
from app.main import app
from app.services import comfy_slot_map_service
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
                "seed": ["INT", {"default": 0}],
                "steps": ["INT", {"default": 20}],
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


def test_slot_map_returns_empty_assignments_initially(client, conn):
    _seed_realistic_catalog(conn)
    wf = _create_workflow(client)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    resp = client.get(f"/api/comfy/sessions/{s['id']}/slot_map")
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == s["id"]
    assert body["workflow_id"] == wf["id"]
    assert body["slot_map"] == {
        "positive_prompt": None,
        "negative_prompt": None,
        "main_image": None,
    }


def test_slot_map_text_candidates_include_both_encoders(client, conn):
    _seed_realistic_catalog(conn)
    wf = _create_workflow(client)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    body = client.get(f"/api/comfy/sessions/{s['id']}/slot_map").json()
    text_pairs = {
        (c["node_id"], c["input_name"]) for c in body["candidates"]["text"]
    }
    assert text_pairs == {("6", "text"), ("7", "text")}
    # Each candidate carries the literal value as preview.
    by_id = {c["node_id"]: c for c in body["candidates"]["text"]}
    assert by_id["6"]["current_value"] == "a cat"
    assert by_id["7"]["current_value"] == "low quality"
    assert by_id["6"]["multiline"] is True


def test_slot_map_image_candidates_filter_by_image_upload(client, conn):
    _seed_realistic_catalog(conn)
    wf = _create_workflow(client)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    body = client.get(f"/api/comfy/sessions/{s['id']}/slot_map").json()
    image_pairs = {
        (c["node_id"], c["input_name"]) for c in body["candidates"]["image"]
    }
    assert image_pairs == {("10", "image")}


def test_slot_map_excludes_wired_inputs(client, conn):
    _seed_realistic_catalog(conn)
    wf = _create_workflow(client)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    body = client.get(f"/api/comfy/sessions/{s['id']}/slot_map").json()
    # KSampler.model is wired (["4", 0]); never eligible.
    text = {(c["node_id"], c["input_name"]) for c in body["candidates"]["text"]}
    assert ("3", "model") not in text


def test_put_slot_map_persists_assignments(client, conn):
    _seed_realistic_catalog(conn)
    wf = _create_workflow(client)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    resp = client.put(
        f"/api/comfy/sessions/{s['id']}/slot_map",
        json={
            "slot_map": {
                "positive_prompt": {"node_id": "6", "input_name": "text"},
                "negative_prompt": {"node_id": "7", "input_name": "text"},
                "main_image": {"node_id": "10", "input_name": "image"},
            },
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["slot_map"]["positive_prompt"] == {"node_id": "6", "input_name": "text"}

    # Persisted on the workflow row — fetch fresh and confirm.
    again = client.get(f"/api/comfy/sessions/{s['id']}/slot_map").json()
    assert again["slot_map"]["main_image"] == {"node_id": "10", "input_name": "image"}


def test_put_slot_map_rejects_assignment_to_non_eligible_input(client, conn):
    _seed_realistic_catalog(conn)
    wf = _create_workflow(client)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    # CheckpointLoaderSimple.ckpt_name is a combo without image_upload —
    # not eligible for any sd-chisel slot.
    resp = client.put(
        f"/api/comfy/sessions/{s['id']}/slot_map",
        json={
            "slot_map": {
                "positive_prompt": {"node_id": "4", "input_name": "ckpt_name"},
            },
        },
    )
    assert resp.status_code == 422
    assert "ckpt_name" in resp.json()["detail"]


def test_put_slot_map_rejects_kind_mismatch(client, conn):
    _seed_realistic_catalog(conn)
    wf = _create_workflow(client)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    # Putting an image candidate into a text slot should fail.
    resp = client.put(
        f"/api/comfy/sessions/{s['id']}/slot_map",
        json={
            "slot_map": {
                "positive_prompt": {"node_id": "10", "input_name": "image"},
            },
        },
    )
    assert resp.status_code == 422


def test_put_slot_map_clears_with_null(client, conn):
    _seed_realistic_catalog(conn)
    wf = _create_workflow(client)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    client.put(
        f"/api/comfy/sessions/{s['id']}/slot_map",
        json={
            "slot_map": {
                "positive_prompt": {"node_id": "6", "input_name": "text"},
            },
        },
    )
    # Now clear it.
    body = client.put(
        f"/api/comfy/sessions/{s['id']}/slot_map",
        json={"slot_map": {"positive_prompt": None}},
    ).json()
    assert body["slot_map"]["positive_prompt"] is None


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


def test_slot_map_propagates_meta_title(client, conn):
    """User-set ``_meta.title`` from the ComfyUI canvas is the only
    thing distinguishing two nodes of the same class. The candidate
    response must surface it so the dropdown can label them."""
    _seed_realistic_catalog(conn)
    graph = {
        **SAMPLE_GRAPH,
        "6": {
            **SAMPLE_GRAPH["6"],
            "_meta": {"title": "Positive prompt"},
        },
        "7": {
            **SAMPLE_GRAPH["7"],
            "_meta": {"title": "Negative prompt"},
        },
    }
    wf = _create_workflow(client, graph=graph)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    body = client.get(f"/api/comfy/sessions/{s['id']}/slot_map").json()
    by_id = {c["node_id"]: c for c in body["candidates"]["text"]}
    assert by_id["6"]["node_title"] == "Positive prompt"
    assert by_id["7"]["node_title"] == "Negative prompt"
    # LoadImage in the image bucket has no _meta.title — null.
    image_by_id = {c["node_id"]: c for c in body["candidates"]["image"]}
    assert image_by_id["10"]["node_title"] is None


def test_compute_candidates_falls_back_when_node_not_in_catalog(conn):
    """A workflow may reference a class_type the user hasn't imported
    yet. The candidate computer still returns string-typed literal
    inputs as text candidates, with ``node_in_catalog=False`` so the
    UI can flag them."""
    graph = {
        "1": {
            "class_type": "MysteryEncoder",
            "inputs": {"prompt": "hello", "weight": 0.5, "wired": ["2", 0]},
        },
    }
    candidates = comfy_slot_map_service.compute_candidates(conn=conn, graph=graph)
    text_names = {(c["node_id"], c["input_name"]) for c in candidates["text"]}
    # Strings show up as text; floats and wires don't.
    assert text_names == {("1", "prompt")}
    assert candidates["text"][0]["node_in_catalog"] is False
