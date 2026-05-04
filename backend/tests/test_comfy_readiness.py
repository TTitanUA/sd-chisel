"""Tests for the readiness endpoint and the underlying service."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_conn
from app.main import app
from app.services import comfy_client, comfy_readiness
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


# Sample workflow: two CLIPTextEncode (positive + negative), one
# KSampler, one LoadImage. Mixes a custom-pack class for the locator
# coverage.
SAMPLE_GRAPH = {
    "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "a cat"}},
    "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "low quality"}},
    "3": {"class_type": "KSampler", "inputs": {"seed": 0}},
    "4": {"class_type": "LoadImage", "inputs": {"image": "ref.png"}},
    "5": {"class_type": "ZImageLoader", "inputs": {}},
}


def test_extract_class_types_counts_instances():
    counts = comfy_readiness.extract_class_types(SAMPLE_GRAPH)
    assert counts == Counter({
        "CLIPTextEncode": 2,
        "KSampler": 1,
        "LoadImage": 1,
        "ZImageLoader": 1,
    })


def test_extract_class_types_skips_malformed_entries():
    graph = {
        "1": {"class_type": "Foo"},
        "2": "not-a-dict",
        "3": {"class_type": ""},
        "4": {"class_type": None},
        "5": {"class_type": "Bar"},
    }
    counts = comfy_readiness.extract_class_types(graph)
    assert counts == Counter({"Foo": 1, "Bar": 1})


# --- end-to-end via the API ---


def _make_workflow(client, name="W", graph=None):
    return client.post(
        "/api/comfy/workflows",
        json={"name": name, "graph": graph or SAMPLE_GRAPH},
    ).json()


def _make_comfy_session(client, workflow_id):
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


def _put_settings(client, *, url, path):
    client.put(
        "/api/settings/comfyui",
        json={"base_url": url, "install_path": path, "api_key": None},
    )


_FAKE_OBJECT_INFO = {
    "CLIPTextEncode": {
        "display_name": "CLIP Text Encode (Prompt)",
        "description": "Encodes a text prompt.",
        "category": "conditioning",
        "python_module": "nodes",
        "input": {}, "output": [],
    },
    "KSampler": {
        "display_name": "KSampler",
        "description": "Samples latents.",
        "category": "sampling",
        "python_module": "nodes",
        "input": {}, "output": [],
    },
    "LoadImage": {
        "display_name": "Load Image",
        "description": "",
        "category": "image",
        "python_module": "nodes",
        "input": {}, "output": [],
    },
    # ZImageLoader intentionally omitted from object_info to exercise
    # the not_installed branch.
}


def test_readiness_404_when_session_missing(client):
    assert client.get("/api/comfy/sessions/ghost/readiness").status_code == 404


def test_readiness_409_when_session_not_comfy(client):
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    sid = client.post(
        f"/api/projects/{pid}/sessions",
        json={"session_type": "i2i", "name": "x", "model_name": None, "use_negative": True},
    ).json()["id"]
    resp = client.get(f"/api/comfy/sessions/{sid}/readiness")
    assert resp.status_code == 409


def test_readiness_returns_error_when_url_unset(client):
    wf = _make_workflow(client)
    s = _make_comfy_session(client, wf["id"])
    body = client.get(f"/api/comfy/sessions/{s['id']}/readiness").json()
    assert body["ready"] is False
    assert body["cards"] == []
    assert "ComfyUI URL is not configured" in body["error"]


def test_readiness_returns_error_when_comfy_unreachable(client, monkeypatch):
    _put_settings(client, url="http://h", path=None)
    wf = _make_workflow(client)
    s = _make_comfy_session(client, wf["id"])

    def boom(**_):
        raise comfy_client.ComfyError("upstream", "boom")

    monkeypatch.setattr(comfy_client, "object_info", boom)
    body = client.get(f"/api/comfy/sessions/{s['id']}/readiness").json()
    assert body["ready"] is False
    assert body["cards"] == []
    assert "boom" in body["error"]


def test_readiness_buckets_each_class_type_correctly(client, monkeypatch, tmp_path):
    install = tmp_path / "ComfyUI"
    (install / "custom_nodes").mkdir(parents=True)
    _put_settings(client, url="http://h", path=str(install))

    wf = _make_workflow(client)
    s = _make_comfy_session(client, wf["id"])

    monkeypatch.setattr(
        comfy_client, "object_info", lambda **_: _FAKE_OBJECT_INFO,
    )

    body = client.get(f"/api/comfy/sessions/{s['id']}/readiness").json()
    by_class = {c["class_type"]: c for c in body["cards"]}

    assert by_class["CLIPTextEncode"]["status"] == "needs_config"
    assert by_class["CLIPTextEncode"]["instance_count"] == 2
    assert by_class["CLIPTextEncode"]["pack_name"] == "ComfyUI"  # built-in
    assert by_class["CLIPTextEncode"]["display_name"] == "CLIP Text Encode (Prompt)"

    assert by_class["KSampler"]["status"] == "needs_config"
    assert by_class["KSampler"]["instance_count"] == 1

    assert by_class["LoadImage"]["status"] == "needs_config"

    assert by_class["ZImageLoader"]["status"] == "not_installed"
    # Nothing came back from object_info for it.
    assert by_class["ZImageLoader"]["display_name"] is None
    assert by_class["ZImageLoader"]["pack_name"] is None

    # No catalog rows yet, so nothing is ready.
    assert body["ready"] is False


def test_readiness_marks_card_ready_when_node_is_imported(
    client, monkeypatch, tmp_path, conn,
):
    install = tmp_path / "ComfyUI"
    (install / "custom_nodes").mkdir(parents=True)
    _put_settings(client, url="http://h", path=str(install))

    wf = _make_workflow(client, graph={"1": {"class_type": "KSampler", "inputs": {}}})
    s = _make_comfy_session(client, wf["id"])

    # Manually insert a configured comfy_nodes row for KSampler. (The
    # import wizard will do this in a later chunk; here we hand-craft
    # the row to exercise the readiness branch.)
    conn.execute(
        "INSERT INTO comfy_packs(name, display_name, imported_at) VALUES (?, ?, ?)",
        ("ComfyUI", "ComfyUI", 0),
    )
    conn.execute(
        "INSERT INTO comfy_nodes(class_type, pack_name, display_name, "
        "  inputs_raw_json, outputs_raw_json, inputs_semantic_json, description_md, "
        "  imported_at, last_seen_in_object_info_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "KSampler", "ComfyUI", "KSampler",
            "{}", "[]",
            '[{"name":"seed","role_hint":"seed"}]',
            "Samples latents.",
            0, 0,
        ),
    )

    monkeypatch.setattr(
        comfy_client, "object_info",
        lambda **_: {"KSampler": _FAKE_OBJECT_INFO["KSampler"]},
    )

    body = client.get(f"/api/comfy/sessions/{s['id']}/readiness").json()
    [card] = body["cards"]
    assert card["status"] == "ready"
    assert body["ready"] is True


def test_readiness_marks_card_ready_when_does_not_require_semantic_config(
    client, monkeypatch, tmp_path, conn,
):
    install = tmp_path / "ComfyUI"
    (install / "custom_nodes").mkdir(parents=True)
    _put_settings(client, url="http://h", path=str(install))

    wf = _make_workflow(client, graph={"1": {"class_type": "Reroute", "inputs": {}}})
    s = _make_comfy_session(client, wf["id"])

    conn.execute(
        "INSERT INTO comfy_packs(name, display_name, imported_at) VALUES (?, ?, ?)",
        ("ComfyUI", "ComfyUI", 0),
    )
    # requires_semantic_config = 0 means we don't require description /
    # semantic schema to mark this card ready.
    conn.execute(
        "INSERT INTO comfy_nodes(class_type, pack_name, display_name, "
        "  inputs_raw_json, outputs_raw_json, inputs_semantic_json, description_md, "
        "  requires_semantic_config, imported_at, last_seen_in_object_info_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("Reroute", "ComfyUI", "Reroute", "{}", "[]", "[]", "", 0, 0, 0),
    )

    monkeypatch.setattr(
        comfy_client, "object_info",
        lambda **_: {"Reroute": {
            "display_name": "Reroute", "description": "", "category": "utils",
            "python_module": "nodes", "input": {}, "output": [],
        }},
    )

    body = client.get(f"/api/comfy/sessions/{s['id']}/readiness").json()
    [card] = body["cards"]
    assert card["status"] == "ready"
