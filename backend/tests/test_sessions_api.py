from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_conn
from app.main import app
from app.storage import db as db_mod
from app.storage import library_repo
from app.storage.migrations import apply_pending


@pytest.fixture
def conn(tmp_path, seed_default_families):
    c = db_mod.connect(tmp_path / "api.db")
    apply_pending(c, Path(__file__).parent.parent / "migrations")
    seed_default_families(c)
    library_repo.create_lora(
        c, name="cinematic_light", display_name="Cinematic Light",
        description="x", tags=["light"], trigger_words=["cinematic light"],
        family_id="sdxl", recommended_weight=0.8,
    )
    yield c
    c.close()


@pytest.fixture
def client(conn):
    app.dependency_overrides[get_conn] = lambda: conn
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_project_crud(client):
    create = client.post("/api/projects", json={"name": "Scrapyard"})
    assert create.status_code == 201
    pid = create.json()["id"]
    assert len(pid) == 10

    listed = client.get("/api/projects").json()
    assert [p["id"] for p in listed] == [pid]
    assert listed[0]["session_count"] == 0

    renamed = client.patch(f"/api/projects/{pid}", json={"name": "Renamed"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Renamed"

    assert client.delete(f"/api/projects/{pid}").status_code == 204
    assert client.delete(f"/api/projects/{pid}").status_code == 404


def test_session_crud_nested_under_project(client):
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]

    create = client.post(
        f"/api/projects/{pid}/sessions",
        json={"session_type": "i2i", "name": "first", "model_name": None, "use_negative": True},
    )
    assert create.status_code == 201
    sid = create.json()["id"]
    assert create.json()["project_id"] == pid
    assert create.json()["use_negative"] is True
    assert create.json()["pinned_loras"] == []
    assert create.json()["session_type"] == "i2i"

    listed = client.get(f"/api/projects/{pid}/sessions").json()
    assert [s["id"] for s in listed] == [sid]

    updated = client.patch(
        f"/api/sessions/{sid}",
        json={
            "name": "renamed",
            "model_name": None,
            "use_negative": False,
            "pinned_loras": [
                {"lora_name": "cinematic_light", "weight_override": 0.65},
            ],
        },
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["name"] == "renamed"
    assert body["use_negative"] is False
    assert body["pinned_loras"] == [
        {"lora_name": "cinematic_light", "weight_override": 0.65},
    ]

    fetched = client.get(f"/api/sessions/{sid}").json()
    assert fetched["pinned_loras"] == body["pinned_loras"]


def test_session_not_found(client):
    assert client.get("/api/sessions/missing").status_code == 404
    assert client.patch(
        "/api/sessions/missing",
        json={"name": None, "model_name": None, "use_negative": True, "pinned_loras": []},
    ).status_code == 404
    assert client.delete("/api/sessions/missing").status_code == 404


def test_create_session_under_missing_project_is_409(client):
    resp = client.post(
        "/api/projects/nope/sessions",
        json={"session_type": "i2i", "name": "x", "model_name": None, "use_negative": True},
    )
    assert resp.status_code == 409


def test_pinned_fk_missing_lora_is_409(client):
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    sid = client.post(
        f"/api/projects/{pid}/sessions",
        json={"session_type": "i2i", "name": "s", "model_name": None, "use_negative": True},
    ).json()["id"]

    resp = client.patch(
        f"/api/sessions/{sid}",
        json={
            "name": "s",
            "model_name": None,
            "use_negative": True,
            "pinned_loras": [{"lora_name": "unknown", "weight_override": None}],
        },
    )
    assert resp.status_code == 409


def test_patch_session_round_trips_vl_and_prompt_model_names(client):
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    sid = client.post(
        f"/api/projects/{pid}/sessions",
        json={"session_type": "i2i", "name": "s", "model_name": None, "use_negative": True},
    ).json()["id"]

    payload = {
        "name": "s",
        "model_name": None,
        "use_negative": True,
        "pinned_loras": [],
        "vl_model_name": "qwen2-vl-7b-instruct",
        "prompt_model_name": "mistral-nemo-12b",
    }
    resp = client.patch(f"/api/sessions/{sid}", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["vl_model_name"] == "qwen2-vl-7b-instruct"
    assert body["prompt_model_name"] == "mistral-nemo-12b"

    # null clears
    cleared = client.patch(
        f"/api/sessions/{sid}",
        json={**payload, "vl_model_name": None, "prompt_model_name": None},
    ).json()
    assert cleared["vl_model_name"] is None
    assert cleared["prompt_model_name"] is None


def test_create_session_t2i_round_trips_type(client):
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    create = client.post(
        f"/api/projects/{pid}/sessions",
        json={"session_type": "t2i", "name": "T", "model_name": None, "use_negative": True},
    )
    assert create.status_code == 201
    body = create.json()
    assert body["session_type"] == "t2i"
    fetched = client.get(f"/api/sessions/{body['id']}").json()
    assert fetched["session_type"] == "t2i"


def test_create_session_rejects_missing_session_type(client):
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    resp = client.post(
        f"/api/projects/{pid}/sessions",
        json={"name": "no-type", "model_name": None, "use_negative": True},
    )
    assert resp.status_code == 422


def test_create_session_rejects_unknown_session_type(client):
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    resp = client.post(
        f"/api/projects/{pid}/sessions",
        json={"session_type": "v2v", "name": "x", "model_name": None, "use_negative": True},
    )
    assert resp.status_code == 422


def test_session_type_is_immutable_via_patch(client):
    """SessionUpdate has no `session_type` field — passing one is rejected
    by extra='forbid'."""
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    sid = client.post(
        f"/api/projects/{pid}/sessions",
        json={"session_type": "i2i", "name": "s", "model_name": None, "use_negative": True},
    ).json()["id"]
    resp = client.patch(
        f"/api/sessions/{sid}",
        json={
            "session_type": "t2i",
            "name": "s",
            "model_name": None,
            "use_negative": True,
            "pinned_loras": [],
        },
    )
    assert resp.status_code == 422


# --- comfy session creation ---

_SAMPLE_GRAPH = {
    "3": {"class_type": "KSampler", "inputs": {"seed": 0}},
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "x"}},
}


def _make_workflow(client, name="W"):
    return client.post(
        "/api/comfy/workflows",
        json={"name": name, "graph": _SAMPLE_GRAPH},
    ).json()


def test_create_comfy_session_binds_workflow(client):
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    wf = _make_workflow(client)
    resp = client.post(
        f"/api/projects/{pid}/sessions",
        json={
            "session_type": "comfy",
            "name": "render",
            "model_name": None,
            "use_negative": True,
            "comfy_workflow_id": wf["id"],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["session_type"] == "comfy"
    assert body["comfy_workflow_id"] == wf["id"]


def test_comfy_session_requires_workflow_id(client):
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    resp = client.post(
        f"/api/projects/{pid}/sessions",
        json={
            "session_type": "comfy",
            "name": "x",
            "model_name": None,
            "use_negative": True,
        },
    )
    assert resp.status_code == 422
    assert "comfy_workflow_id" in resp.json()["detail"]


def test_comfy_session_rejects_unknown_workflow_id(client):
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    resp = client.post(
        f"/api/projects/{pid}/sessions",
        json={
            "session_type": "comfy",
            "name": "x",
            "model_name": None,
            "use_negative": True,
            "comfy_workflow_id": "deadbeef00",
        },
    )
    assert resp.status_code == 422
    assert "not found" in resp.json()["detail"]


def test_non_comfy_session_rejects_workflow_id(client):
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    wf = _make_workflow(client)
    resp = client.post(
        f"/api/projects/{pid}/sessions",
        json={
            "session_type": "i2i",
            "name": "x",
            "model_name": None,
            "use_negative": True,
            "comfy_workflow_id": wf["id"],
        },
    )
    assert resp.status_code == 422


def test_delete_workflow_in_use_returns_409(client):
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    wf = _make_workflow(client)
    client.post(
        f"/api/projects/{pid}/sessions",
        json={
            "session_type": "comfy",
            "name": "x",
            "model_name": None,
            "use_negative": True,
            "comfy_workflow_id": wf["id"],
        },
    )
    resp = client.delete(f"/api/comfy/workflows/{wf['id']}")
    assert resp.status_code == 409
    assert "in use" in resp.json()["detail"]


def test_delete_workflow_after_session_gone_succeeds(client):
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    wf = _make_workflow(client)
    sid = client.post(
        f"/api/projects/{pid}/sessions",
        json={
            "session_type": "comfy",
            "name": "x",
            "model_name": None,
            "use_negative": True,
            "comfy_workflow_id": wf["id"],
        },
    ).json()["id"]
    assert client.delete(f"/api/sessions/{sid}").status_code == 204
    assert client.delete(f"/api/comfy/workflows/{wf['id']}").status_code == 204


def test_session_type_constraint_no_longer_rejects_comfy_at_db_level(client):
    """Migration 013 relaxed the CHECK to include 'comfy'; smoke-test
    that the schema actually allows it (the API validation wraps the
    other direction)."""
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    wf = _make_workflow(client)
    resp = client.post(
        f"/api/projects/{pid}/sessions",
        json={
            "session_type": "comfy",
            "comfy_workflow_id": wf["id"],
            "model_name": None,
            "use_negative": True,
        },
    )
    assert resp.status_code == 201
