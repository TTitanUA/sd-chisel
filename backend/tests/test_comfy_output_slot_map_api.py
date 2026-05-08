"""Tests for /api/comfy/sessions/{id}/output_slot_map (PR-2).

Output slot map is symmetric to ``slot_map``: it declares which
SaveImage results Phase 3's generation cycle will copy into
``data/images/<sid>/output/<gid>/<label>.<ext>``. The contract is
``{output_slot_map: {version, outputs[]}, candidates: [...]}``. Read-time
upgrade seeds the map from the SaveImage nodes in the workflow when
nothing has been saved yet.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_conn
from app.main import app
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


# Two SaveImage nodes (with different prefixes) plus one custom saver
# the gate must reject.
SAMPLE_GRAPH = {
    "3": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 0, "steps": 20, "cfg": 7.5,
            "model": ["4", 0], "latent_image": ["5", 0],
            "positive": ["6", 0], "negative": ["7", 0],
        },
    },
    "4": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "sd_xl_base.safetensors"},
    },
    "5": {
        "class_type": "EmptyLatentImage",
        "inputs": {"width": 1024, "height": 1024, "batch_size": 1},
    },
    "6": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "a cat", "clip": ["4", 1]},
    },
    "7": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "low quality", "clip": ["4", 1]},
    },
    "9": {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "ComfyUI", "images": ["3", 0]},
    },
    "12": {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "ComfyUI/preview", "images": ["3", 0]},
    },
    "20": {
        # Custom saver — must NOT appear in the candidate list.
        "class_type": "SaveImageS3",
        "inputs": {"filename_prefix": "S3", "images": ["3", 0]},
    },
}


def _make_session(client, *, workflow_id: str) -> dict:
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


def _create_workflow(client) -> dict:
    return client.post(
        "/api/comfy/workflows",
        json={"name": "W", "graph": SAMPLE_GRAPH},
    ).json()


# --- GET shape -----------------------------------------------------------


def test_get_returns_candidates_only_for_save_image(client):
    wf = _create_workflow(client)
    s = _make_session(client, workflow_id=wf["id"])
    resp = client.get(f"/api/comfy/sessions/{s['id']}/output_slot_map")
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == s["id"]
    assert body["workflow_id"] == wf["id"]
    candidate_ids = {c["node_id"] for c in body["candidates"]}
    assert candidate_ids == {"9", "12"}
    # The custom S3 saver is silently skipped.
    assert "20" not in candidate_ids


def test_get_seeds_default_outputs_from_filename_prefix(client):
    wf = _create_workflow(client)
    s = _make_session(client, workflow_id=wf["id"])
    body = client.get(f"/api/comfy/sessions/{s['id']}/output_slot_map").json()
    # No map saved yet → default seed has one entry per SaveImage node,
    # labelled from the prefix (sanitised; "/" → "_").
    outputs = body["output_slot_map"]["outputs"]
    by_node = {o["node_id"]: o["label"] for o in outputs}
    assert set(by_node) == {"9", "12"}
    assert by_node["9"] == "ComfyUI"
    assert by_node["12"] == "ComfyUI_preview"
    # Every entry is image-kind in PR-2.
    assert all(o["kind"] == "image" for o in outputs)


# --- PUT round-trip ------------------------------------------------------


def test_put_persists_and_filters_unknown_node_ids(client):
    wf = _create_workflow(client)
    s = _make_session(client, workflow_id=wf["id"])
    resp = client.put(
        f"/api/comfy/sessions/{s['id']}/output_slot_map",
        json={
            "outputs": [
                {"label": "final",   "node_id": "9",  "kind": "image"},
                {"label": "preview", "node_id": "12", "kind": "image"},
            ],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["output_slot_map"]["version"] == 1
    labels = [o["label"] for o in body["output_slot_map"]["outputs"]]
    assert labels == ["final", "preview"]

    # Round-trip on GET.
    again = client.get(f"/api/comfy/sessions/{s['id']}/output_slot_map").json()
    assert again["output_slot_map"] == body["output_slot_map"]


def test_put_rejects_non_save_image_node(client):
    wf = _create_workflow(client)
    s = _make_session(client, workflow_id=wf["id"])
    resp = client.put(
        f"/api/comfy/sessions/{s['id']}/output_slot_map",
        json={
            "outputs": [
                {"label": "s3", "node_id": "20", "kind": "image"},
            ],
        },
    )
    assert resp.status_code == 422
    assert "SaveImage" in resp.json()["detail"]


def test_put_rejects_duplicate_labels(client):
    wf = _create_workflow(client)
    s = _make_session(client, workflow_id=wf["id"])
    resp = client.put(
        f"/api/comfy/sessions/{s['id']}/output_slot_map",
        json={
            "outputs": [
                {"label": "out", "node_id": "9",  "kind": "image"},
                {"label": "out", "node_id": "12", "kind": "image"},
            ],
        },
    )
    assert resp.status_code == 422
    assert "duplicate" in resp.json()["detail"].lower()


def test_put_rejects_unsafe_label(client):
    wf = _create_workflow(client)
    s = _make_session(client, workflow_id=wf["id"])
    resp = client.put(
        f"/api/comfy/sessions/{s['id']}/output_slot_map",
        json={
            "outputs": [
                {"label": "bad/slash", "node_id": "9", "kind": "image"},
            ],
        },
    )
    # Pydantic rejects bad/slash via the pattern field — 422 from the
    # framework, not our service.
    assert resp.status_code == 422


def test_get_drops_outputs_pointing_at_no_longer_eligible_node(
    client, conn,
):
    """Saved map references node_id=9; if the workflow then drops that
    SaveImage, GET should silently filter it out."""
    wf = _create_workflow(client)
    s = _make_session(client, workflow_id=wf["id"])
    client.put(
        f"/api/comfy/sessions/{s['id']}/output_slot_map",
        json={
            "outputs": [
                {"label": "final",   "node_id": "9",  "kind": "image"},
                {"label": "preview", "node_id": "12", "kind": "image"},
            ],
        },
    )

    # Replace the workflow graph so node 9 disappears (re-uses the same
    # workflow id via repo replace; mirrors what the upload-with-replace
    # flow does).
    new_graph = {k: v for k, v in SAMPLE_GRAPH.items() if k != "9"}
    comfy_workflow_repo = __import__(
        "app.storage.comfy_workflow_repo", fromlist=["replace_workflow"],
    )
    comfy_workflow_repo.replace_workflow(
        conn, workflow_id=wf["id"], name=wf["name"], graph=new_graph,
    )

    body = client.get(f"/api/comfy/sessions/{s['id']}/output_slot_map").json()
    labels = [o["label"] for o in body["output_slot_map"]["outputs"]]
    assert labels == ["preview"]
