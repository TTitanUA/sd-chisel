"""Tests for /api/comfy/workflows."""
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


# Minimal API-format graph good enough for hash/CRUD round-trips.
SAMPLE_GRAPH = {
    "3": {
        "class_type": "KSampler",
        "inputs": {"seed": 0, "steps": 20, "cfg": 7.5, "model": ["4", 0]},
    },
    "4": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"},
    },
}


def _upload(client, *, name, graph, on_conflict=None):
    url = "/api/comfy/workflows"
    if on_conflict:
        url += f"?on_conflict={on_conflict}"
    return client.post(url, json={"name": name, "graph": graph})


def test_post_workflow_persists(client):
    resp = _upload(client, name="My SDXL t2i", graph=SAMPLE_GRAPH)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "My SDXL t2i"
    assert body["graph"] == SAMPLE_GRAPH
    assert len(body["graph_hash"]) == 64  # sha256 hex
    assert body["created_at"] > 0
    assert len(body["id"]) == 10


def test_list_returns_summaries(client):
    _upload(client, name="A", graph=SAMPLE_GRAPH)
    _upload(client, name="B", graph={"1": {"class_type": "CLIPTextEncode", "inputs": {}}})
    body = client.get("/api/comfy/workflows").json()
    names = [w["name"] for w in body["workflows"]]
    assert sorted(names) == ["A", "B"]
    # Summaries don't carry the full graph.
    assert "graph" not in body["workflows"][0]


def test_get_returns_full_graph(client):
    created = _upload(client, name="X", graph=SAMPLE_GRAPH).json()
    body = client.get(f"/api/comfy/workflows/{created['id']}").json()
    assert body["graph"] == SAMPLE_GRAPH


def test_get_missing_returns_404(client):
    assert client.get("/api/comfy/workflows/nope").status_code == 404


def test_duplicate_hash_returns_409_with_existing_summary(client):
    first = _upload(client, name="original", graph=SAMPLE_GRAPH).json()
    resp = _upload(client, name="duplicate", graph=SAMPLE_GRAPH)
    assert resp.status_code == 409
    body = resp.json()
    assert body["conflict"] == "graph_hash"
    assert body["existing"]["id"] == first["id"]
    assert body["existing"]["name"] == "original"


def test_on_conflict_replace_overwrites_existing_row(client):
    first = _upload(client, name="orig", graph=SAMPLE_GRAPH).json()
    # Replace with a different graph + new name; the row id must stay.
    new_graph = {"99": {"class_type": "KSampler", "inputs": {"seed": 1}}}
    resp = client.post(
        "/api/comfy/workflows?on_conflict=replace",
        json={"name": "renamed", "graph": SAMPLE_GRAPH},  # same hash
    )
    # Replace path — only triggers when hash matches; same SAMPLE_GRAPH used.
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == first["id"]
    assert body["name"] == "renamed"

    # And replacing with a different graph keeps the original id but
    # should not be the replace-on-conflict path (no collision). Verify
    # by uploading a new graph with default conflict policy → fresh row.
    resp2 = client.post(
        "/api/comfy/workflows",
        json={"name": "new", "graph": new_graph},
    )
    assert resp2.status_code == 200
    assert resp2.json()["id"] != first["id"]


def test_on_conflict_rename_creates_new_row(client):
    first = _upload(client, name="orig", graph=SAMPLE_GRAPH).json()
    resp = _upload(client, name="copy", graph=SAMPLE_GRAPH, on_conflict="rename")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] != first["id"]
    assert body["name"] == "copy"
    # Both rows visible in the list.
    listed = client.get("/api/comfy/workflows").json()["workflows"]
    assert {w["id"] for w in listed} == {first["id"], body["id"]}


def test_canonicalisation_makes_reordered_keys_collide(client):
    """Two graphs with identical content but different key insertion
    order should hash the same, so the second upload triggers 409."""
    g1 = {"a": {"x": 1, "y": 2}}
    g2 = {"a": {"y": 2, "x": 1}}
    _upload(client, name="A", graph=g1)
    resp = _upload(client, name="B", graph=g2)
    assert resp.status_code == 409


def test_delete_returns_204_then_404(client):
    created = _upload(client, name="A", graph=SAMPLE_GRAPH).json()
    assert client.delete(f"/api/comfy/workflows/{created['id']}").status_code == 204
    assert client.get(f"/api/comfy/workflows/{created['id']}").status_code == 404
    assert client.delete(f"/api/comfy/workflows/{created['id']}").status_code == 404


def test_post_rejects_empty_name(client):
    resp = client.post("/api/comfy/workflows", json={"name": "", "graph": SAMPLE_GRAPH})
    assert resp.status_code == 422


def test_post_rejects_unknown_field(client):
    resp = client.post(
        "/api/comfy/workflows",
        json={"name": "x", "graph": SAMPLE_GRAPH, "stray": True},
    )
    assert resp.status_code == 422
