"""Tests for /api/comfy/sessions/{id}/single_run + the comfy_jobs
read endpoints. The pipeline itself runs in an asyncio task and hits
LMStudio + ComfyUI; these tests cover the synchronous validate-and-
snapshot path + the read-and-delete endpoints. The full integration
is exercised by the live smoke against localhost:8188.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_conn
from app.main import app
from app.services import comfy_orchestrator
from app.storage import comfy_jobs_repo, comfy_workflow_repo
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


GRAPH = {
    "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "a"}},
    "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "b"}},
    "3": {"class_type": "KSampler", "inputs": {"seed": 0}},
    "4": {"class_type": "LoadImage", "inputs": {"image": "ref.png"}},
}

SLOTS = [
    {
        "label": "positive", "group": None, "ordinal": 1, "description": None,
        "kind": "multiline_text",
        "origin": {"node_id": "1", "input_name": "text"},
        "binding": "llm", "metadata": {},
    },
    {
        "label": "negative", "group": None, "ordinal": 2, "description": None,
        "kind": "multiline_text",
        "origin": {"node_id": "2", "input_name": "text"},
        "binding": "llm", "metadata": {},
    },
    {
        "label": "seed", "group": None, "ordinal": 3, "description": None,
        "kind": "number_int",
        "origin": {"node_id": "3", "input_name": "seed"},
        "binding": "frozen", "metadata": {"value": 42},
    },
    {
        "label": "main_image", "group": None, "ordinal": 4, "description": None,
        "kind": "image",
        "origin": {"node_id": "4", "input_name": "image"},
        "binding": "user_image", "metadata": {},
    },
]


def _make_workflow(client, conn, *, slots=SLOTS) -> dict:
    wf = client.post(
        "/api/comfy/workflows", json={"name": "W", "graph": GRAPH},
    ).json()
    comfy_workflow_repo.set_slot_map(
        conn,
        workflow_id=wf["id"],
        slot_map={"version": 2, "slots": slots},
    )
    return wf


def _make_session(client, *, workflow_id: str) -> dict:
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    return client.post(
        f"/api/projects/{pid}/sessions",
        json={
            "session_type": "comfy", "name": "S",
            "model_name": None, "use_negative": True,
            "comfy_workflow_id": workflow_id,
        },
    ).json()


# --- validation / 409 paths -------------------------------------------


def test_single_run_409_when_session_missing(client):
    resp = client.post(
        "/api/comfy/sessions/nope/single_run",
        json={"image_bindings": {}},
    )
    assert resp.status_code == 409
    assert "session not found" in resp.json()["detail"]


def test_single_run_409_when_no_workflow_bound(client, conn):
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    s = client.post(
        f"/api/projects/{pid}/sessions",
        json={"session_type": "i2i", "name": "S", "model_name": None,
              "use_negative": True},
    ).json()
    resp = client.post(
        f"/api/comfy/sessions/{s['id']}/single_run",
        json={},
    )
    assert resp.status_code == 409
    assert "not a comfy session" in resp.json()["detail"]


def test_single_run_409_when_no_agent_for_llm_slot(client, conn):
    wf = _make_workflow(client, conn)
    s = _make_session(client, workflow_id=wf["id"])
    resp = client.post(
        f"/api/comfy/sessions/{s['id']}/single_run",
        json={"image_bindings": {"main_image": "img-1"}},
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert "missing agent output" in detail
    assert "positive" in detail and "negative" in detail


def test_single_run_409_when_no_image_for_user_image_slot(client, conn):
    wf = _make_workflow(client, conn)
    s = _make_session(client, workflow_id=wf["id"])
    # Seed an agent that covers both llm slots.
    client.post(
        f"/api/comfy/sessions/{s['id']}/agents/seed_default",
    )
    resp = client.post(
        f"/api/comfy/sessions/{s['id']}/single_run",
        json={"image_bindings": {}},
    )
    assert resp.status_code == 409
    assert "missing image binding" in resp.json()["detail"]
    assert "main_image" in resp.json()["detail"]


# --- jobs list / get --------------------------------------------------


def test_list_jobs_empty_for_session(client):
    resp = client.get("/api/comfy/jobs?session_id=any")
    assert resp.status_code == 200
    assert resp.json() == {"jobs": []}


def test_get_job_404_when_missing(client):
    resp = client.get("/api/comfy/jobs/nope")
    assert resp.status_code == 404


def test_get_job_returns_full_row_with_outputs(client, conn):
    wf = _make_workflow(client, conn)
    s = _make_session(client, workflow_id=wf["id"])
    job = comfy_jobs_repo.create_job(
        conn,
        session_id=s["id"], workflow_id=wf["id"],
        generation_id="20260508-000000-abcdef",
        slot_map_snapshot=SLOTS,
        agents_snapshot=[],
    )
    comfy_jobs_repo.add_output(
        conn, job_id=job["id"], slot_label="result",
        node_id="9", output_index=0, path="images/x/output/g/result.png",
        is_primary=True,
    )

    resp = client.get(f"/api/comfy/jobs/{job['id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == job["id"]
    assert body["status"] == "running"
    assert body["generation_id"] == "20260508-000000-abcdef"
    assert len(body["outputs"]) == 1
    assert body["outputs"][0]["url"] == "/media/images/x/output/g/result.png"
    assert body["outputs"][0]["is_primary"] is True


def test_list_jobs_orders_newest_first(client, conn):
    wf = _make_workflow(client, conn)
    s = _make_session(client, workflow_id=wf["id"])
    j1 = comfy_jobs_repo.create_job(
        conn, session_id=s["id"], workflow_id=wf["id"],
        generation_id="g1", slot_map_snapshot=SLOTS, agents_snapshot=[],
    )
    j2 = comfy_jobs_repo.create_job(
        conn, session_id=s["id"], workflow_id=wf["id"],
        generation_id="g2", slot_map_snapshot=SLOTS, agents_snapshot=[],
    )
    body = client.get(f"/api/comfy/jobs?session_id={s['id']}").json()
    ids = [j["id"] for j in body["jobs"]]
    assert ids[0] == j2["id"]  # newest first
    assert ids[1] == j1["id"]


# --- delete -----------------------------------------------------------


def test_delete_job_drops_row_and_cascade(client, conn, tmp_path, monkeypatch):
    # Redirect data root to tmp so the cleanup path is contained.
    monkeypatch.setattr(
        "app.config.resolve_data_root", lambda: tmp_path,
    )
    monkeypatch.setattr(
        "app.api.comfy_jobs.resolve_data_root", lambda: tmp_path,
    )
    wf = _make_workflow(client, conn)
    s = _make_session(client, workflow_id=wf["id"])
    job = comfy_jobs_repo.create_job(
        conn, session_id=s["id"], workflow_id=wf["id"],
        generation_id="g", slot_map_snapshot=SLOTS, agents_snapshot=[],
    )
    out_path = (
        tmp_path / "images" / s["id"] / "output" / "g" / "result.png"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(b"fake png")
    comfy_jobs_repo.add_output(
        conn, job_id=job["id"], slot_label="result",
        node_id="9", output_index=0,
        path=f"images/{s['id']}/output/g/result.png",
        is_primary=True,
    )

    resp = client.delete(f"/api/comfy/jobs/{job['id']}")
    assert resp.status_code == 204
    assert comfy_jobs_repo.get_job(conn, job["id"]) is None
    assert not out_path.exists()
    # Empty per-run dir cleaned up too.
    assert not out_path.parent.exists()


def test_stream_404_when_no_channel(client):
    # No run started — channel doesn't exist.
    resp = client.get("/api/comfy/jobs/nope/stream")
    assert resp.status_code == 404


def test_cancel_404_for_unknown_job(client):
    resp = client.post("/api/comfy/jobs/nope/cancel")
    assert resp.status_code == 404


def test_cancel_idempotent_for_finished_job(client, conn):
    # Build a finished row directly through the repo so we don't need
    # an actual orchestrator run.
    wf = _make_workflow(client, conn)
    s = _make_session(client, workflow_id=wf["id"])
    job = comfy_jobs_repo.create_job(
        conn, session_id=s["id"], workflow_id=wf["id"],
        generation_id="g", slot_map_snapshot=SLOTS, agents_snapshot=[],
    )
    comfy_jobs_repo.set_status(conn, job["id"], "success")
    resp = client.post(f"/api/comfy/jobs/{job['id']}/cancel")
    assert resp.status_code == 202
    # Status untouched on a no-op cancel.
    assert resp.json()["status"] == "success"


def test_cancel_running_job_without_channel_flips_status(client, conn):
    """When the run has no live channel (e.g. the orchestrator died
    or was reaped), the cancel endpoint still flips the row to
    `cancelled` so the gallery reflects reality."""
    wf = _make_workflow(client, conn)
    s = _make_session(client, workflow_id=wf["id"])
    job = comfy_jobs_repo.create_job(
        conn, session_id=s["id"], workflow_id=wf["id"],
        generation_id="g", slot_map_snapshot=SLOTS, agents_snapshot=[],
    )
    # Row is in `running` from create_job; no channel was ever opened.
    resp = client.post(f"/api/comfy/jobs/{job['id']}/cancel")
    assert resp.status_code == 202
    assert resp.json()["status"] == "cancelled"
    refreshed = comfy_jobs_repo.get_job(conn, job["id"])
    assert refreshed is not None
    assert refreshed["status"] == "cancelled"


# --- repo-level invariants -------------------------------------------


def _seed_session(conn) -> str:
    """Insert a minimal session row directly so the comfy_jobs FK
    holds without spinning up the full project/workflow tree."""
    conn.execute(
        "INSERT INTO projects(id, name, hidden, created_at, updated_at) "
        "VALUES ('p', 'P', 0, 0, 0)",
    )
    conn.execute(
        "INSERT INTO sessions(id, project_id, name, session_type, "
        "model_name, use_negative, hidden, created_at, updated_at, "
        "comfy_input_cleanup) VALUES "
        "('s', 'p', 'S', 'comfy', NULL, 1, 0, 0, 0, 'keep')",
    )
    conn.commit()
    return "s"


def test_set_status_stamps_finished_at_on_terminal(conn):
    _seed_session(conn)
    job = comfy_jobs_repo.create_job(
        conn, session_id="s", workflow_id="w", generation_id="g",
        slot_map_snapshot=[], agents_snapshot=[],
    )
    assert job["finished_at"] is None
    comfy_jobs_repo.set_status(conn, job["id"], "success")
    refreshed = comfy_jobs_repo.get_job(conn, job["id"])
    assert refreshed is not None
    assert refreshed["finished_at"] is not None
    assert refreshed["status"] == "success"


def test_find_running_job_returns_active(conn):
    _seed_session(conn)
    j1 = comfy_jobs_repo.create_job(
        conn, session_id="s", workflow_id="w", generation_id="g1",
        slot_map_snapshot=[], agents_snapshot=[],
    )
    comfy_jobs_repo.set_status(conn, j1["id"], "success")
    j2 = comfy_jobs_repo.create_job(
        conn, session_id="s", workflow_id="w", generation_id="g2",
        slot_map_snapshot=[], agents_snapshot=[],
    )
    found = comfy_jobs_repo.find_running_job(conn, "s")
    assert found is not None
    assert found["id"] == j2["id"]


def test_find_running_job_none_when_session_idle(conn):
    _seed_session(conn)
    j1 = comfy_jobs_repo.create_job(
        conn, session_id="s", workflow_id="w", generation_id="g1",
        slot_map_snapshot=[], agents_snapshot=[],
    )
    comfy_jobs_repo.set_status(conn, j1["id"], "success")
    assert comfy_jobs_repo.find_running_job(conn, "s") is None
