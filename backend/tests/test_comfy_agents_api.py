"""Tests for /api/comfy/sessions/{id}/agents (Comfy agents redesign).

Covers CRUD, output-slot validation (preset / custom / auto), the
single-bind rule across sibling agents, auto-slot resolution from the
workflow slot + catalog, and the opt-in ``seed_default`` action.
"""
from __future__ import annotations

import json as _json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_conn
from app.main import app
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


SAMPLE_GRAPH = {
    "3": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 0, "steps": 20, "cfg": 7.5,
            "model": ["4", 0], "positive": ["6", 0],
            "negative": ["7", 0], "latent_image": ["10", 0],
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


def _seed_node(
    conn,
    *,
    class_type: str,
    inputs_raw: dict,
    description_md: str = "",
    inputs_semantic: list[dict] | None = None,
    pack_name: str = "ComfyUI",
):
    conn.execute(
        "INSERT OR IGNORE INTO comfy_packs(name, display_name, imported_at) "
        "VALUES (?, ?, 0)",
        (pack_name, pack_name),
    )
    conn.execute(
        "INSERT INTO comfy_nodes(class_type, pack_name, display_name, "
        "  inputs_raw_json, outputs_raw_json, inputs_semantic_json, "
        "  description_md, imported_at, last_seen_in_object_info_at) "
        "VALUES (?, ?, ?, ?, '[]', ?, ?, 0, 0)",
        (
            class_type, pack_name, class_type,
            _json.dumps(inputs_raw),
            _json.dumps(inputs_semantic or []),
            description_md,
        ),
    )


def _seed_catalog(conn):
    _seed_node(
        conn,
        class_type="CLIPTextEncode",
        inputs_raw={"required": {"text": ["STRING", {"multiline": True}]}},
        description_md="Encodes text into conditioning.",
        inputs_semantic=[
            {"name": "text", "notes": "Free-form prompt text."},
        ],
    )
    _seed_node(
        conn,
        class_type="KSampler",
        inputs_raw={
            "required": {
                "seed": ["INT", {"default": 0, "min": 0, "max": 100_000}],
                "steps": ["INT", {"default": 20, "min": 1, "max": 200}],
                "cfg": ["FLOAT", {"default": 7.5, "min": 0, "max": 30}],
            },
        },
    )
    _seed_node(
        conn,
        class_type="CheckpointLoaderSimple",
        inputs_raw={"required": {"ckpt_name": [["sd_xl_base.safetensors"], {}]}},
    )
    _seed_node(
        conn,
        class_type="LoadImage",
        inputs_raw={"required": {"image": [["ref.png"], {"image_upload": True}]}},
    )


def _make_workflow_with_slots(client, conn, *, slots: list[dict]) -> dict:
    """Create a workflow and persist a slot map directly through the
    repo. Going through PUT /slot_map would also work but adds noise to
    the agent tests' setup."""
    wf = client.post(
        "/api/comfy/workflows", json={"name": "W", "graph": SAMPLE_GRAPH},
    ).json()
    comfy_workflow_repo.set_slot_map(
        conn,
        workflow_id=wf["id"],
        slot_map={"version": 2, "slots": slots},
    )
    return wf


def _make_comfy_session(client, *, workflow_id: str) -> dict:
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


# Default slot map most tests reuse: two llm text slots plus a frozen
# seed and a user-image slot. Mirrors a small workflow shape.
DEFAULT_SLOTS = [
    {
        "label": "positive_prompt",
        "group": None, "ordinal": 1,
        "description": "What we want to see in the image.",
        "kind": "multiline_text",
        "origin": {"node_id": "6", "input_name": "text"},
        "binding": "llm",
        "metadata": {"multiline": True},
    },
    {
        "label": "negative_prompt",
        "group": None, "ordinal": 2,
        "description": None,
        "kind": "multiline_text",
        "origin": {"node_id": "7", "input_name": "text"},
        "binding": "llm",
        "metadata": {"multiline": True},
    },
    {
        "label": "seed",
        "group": None, "ordinal": 3,
        "description": None,
        "kind": "number_int",
        "origin": {"node_id": "3", "input_name": "seed"},
        "binding": "frozen",
        "metadata": {"value": 12345, "min": 0, "max": 100_000},
    },
    {
        "label": "ref_image",
        "group": None, "ordinal": 4,
        "description": None,
        "kind": "image",
        "origin": {"node_id": "10", "input_name": "image"},
        "binding": "user_image",
        "metadata": {},
    },
]


# --- list / create ---------------------------------------------------------


def test_list_agents_empty_for_new_session(client, conn):
    _seed_catalog(conn)
    wf = _make_workflow_with_slots(client, conn, slots=DEFAULT_SLOTS)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    body = client.get(f"/api/comfy/sessions/{s['id']}/agents").json()
    assert body == {"agents": []}


def test_list_agents_404_when_session_missing(client):
    resp = client.get("/api/comfy/sessions/nope/agents")
    assert resp.status_code == 404


def test_list_agents_409_when_session_not_comfy(client, conn):
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    s = client.post(
        f"/api/projects/{pid}/sessions",
        json={"session_type": "i2i", "name": "x", "use_negative": True},
    ).json()
    resp = client.get(f"/api/comfy/sessions/{s['id']}/agents")
    assert resp.status_code == 409


def test_create_minimal_agent(client, conn):
    _seed_catalog(conn)
    wf = _make_workflow_with_slots(client, conn, slots=DEFAULT_SLOTS)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    resp = client.post(
        f"/api/comfy/sessions/{s['id']}/agents",
        json={"name": "Composer"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Composer"
    assert body["prompt"] == ""
    assert body["source_scope"] == "all"
    assert body["source_ids"] is None
    assert body["loras_enabled"] is False
    assert body["output_slots"] == []
    assert body["last_run_at"] is None
    assert body["session_id"] == s["id"]
    assert body["position"] == 0


def test_create_agent_with_preset_output_slot(client, conn):
    _seed_catalog(conn)
    wf = _make_workflow_with_slots(client, conn, slots=DEFAULT_SLOTS)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    resp = client.post(
        f"/api/comfy/sessions/{s['id']}/agents",
        json={
            "name": "Composer",
            "output_slots": [
                {
                    "id": "slot1",
                    "origin": "preset",
                    "preset": "positive",
                    "label": "positive",
                },
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    slots = resp.json()["output_slots"]
    assert len(slots) == 1
    assert slots[0]["preset"] == "positive"
    assert slots[0]["kind"] == "multiline_text"  # filled in from PRESET_KIND


def test_preset_with_wrong_kind_is_422(client, conn):
    _seed_catalog(conn)
    wf = _make_workflow_with_slots(client, conn, slots=DEFAULT_SLOTS)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    resp = client.post(
        f"/api/comfy/sessions/{s['id']}/agents",
        json={
            "name": "X",
            "output_slots": [
                {
                    "id": "s1",
                    "origin": "preset",
                    "preset": "positive",
                    "label": "positive",
                    "kind": "number_int",  # wrong for preset=positive
                },
            ],
        },
    )
    assert resp.status_code == 422
    assert "preset" in resp.json()["detail"].lower()


def test_custom_slot_requires_kind(client, conn):
    _seed_catalog(conn)
    wf = _make_workflow_with_slots(client, conn, slots=DEFAULT_SLOTS)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    resp = client.post(
        f"/api/comfy/sessions/{s['id']}/agents",
        json={
            "name": "X",
            "output_slots": [
                {
                    "id": "s1",
                    "origin": "custom",
                    "label": "custom1",
                    # kind missing
                },
            ],
        },
    )
    assert resp.status_code == 422


def test_position_increments_per_session(client, conn):
    _seed_catalog(conn)
    wf = _make_workflow_with_slots(client, conn, slots=DEFAULT_SLOTS)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    a = client.post(
        f"/api/comfy/sessions/{s['id']}/agents", json={"name": "A"},
    ).json()
    b = client.post(
        f"/api/comfy/sessions/{s['id']}/agents", json={"name": "B"},
    ).json()
    assert a["position"] == 0
    assert b["position"] == 1


# --- bind_to validation + single-bind rule ---------------------------------


def test_bind_to_unknown_label_is_422(client, conn):
    _seed_catalog(conn)
    wf = _make_workflow_with_slots(client, conn, slots=DEFAULT_SLOTS)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    resp = client.post(
        f"/api/comfy/sessions/{s['id']}/agents",
        json={
            "name": "X",
            "output_slots": [
                {
                    "id": "s1",
                    "origin": "custom",
                    "kind": "multiline_text",
                    "label": "out1",
                    "bound_to": {"workflow_slot_label": "does_not_exist"},
                },
            ],
        },
    )
    assert resp.status_code == 422
    assert "unknown" in resp.json()["detail"].lower()


def test_bind_to_non_llm_slot_is_422(client, conn):
    _seed_catalog(conn)
    wf = _make_workflow_with_slots(client, conn, slots=DEFAULT_SLOTS)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    resp = client.post(
        f"/api/comfy/sessions/{s['id']}/agents",
        json={
            "name": "X",
            "output_slots": [
                {
                    "id": "s1",
                    "origin": "custom",
                    "kind": "number_int",
                    "label": "out1",
                    "bound_to": {"workflow_slot_label": "seed"},  # frozen
                },
            ],
        },
    )
    assert resp.status_code == 422
    assert "binding" in resp.json()["detail"].lower()


def test_bind_to_kind_mismatch_is_422(client, conn):
    _seed_catalog(conn)
    wf = _make_workflow_with_slots(client, conn, slots=DEFAULT_SLOTS)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    resp = client.post(
        f"/api/comfy/sessions/{s['id']}/agents",
        json={
            "name": "X",
            "output_slots": [
                {
                    "id": "s1",
                    "origin": "custom",
                    "kind": "text",  # workflow slot is multiline_text
                    "label": "out1",
                    "bound_to": {"workflow_slot_label": "positive_prompt"},
                },
            ],
        },
    )
    assert resp.status_code == 422
    assert "kind" in resp.json()["detail"].lower()


def test_two_agents_cannot_bind_same_workflow_slot(client, conn):
    _seed_catalog(conn)
    wf = _make_workflow_with_slots(client, conn, slots=DEFAULT_SLOTS)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    client.post(
        f"/api/comfy/sessions/{s['id']}/agents",
        json={
            "name": "A",
            "output_slots": [
                {
                    "id": "a1",
                    "origin": "custom",
                    "kind": "multiline_text",
                    "label": "out",
                    "bound_to": {"workflow_slot_label": "positive_prompt"},
                },
            ],
        },
    )
    resp = client.post(
        f"/api/comfy/sessions/{s['id']}/agents",
        json={
            "name": "B",
            "output_slots": [
                {
                    "id": "b1",
                    "origin": "custom",
                    "kind": "multiline_text",
                    "label": "out",
                    "bound_to": {"workflow_slot_label": "positive_prompt"},
                },
            ],
        },
    )
    assert resp.status_code == 409
    assert "already bound" in resp.json()["detail"].lower()


def test_self_can_keep_its_own_binding_on_patch(client, conn):
    """The single-bind check must skip the agent being updated, otherwise
    a no-op PATCH would 409 against its own existing binding."""
    _seed_catalog(conn)
    wf = _make_workflow_with_slots(client, conn, slots=DEFAULT_SLOTS)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    a = client.post(
        f"/api/comfy/sessions/{s['id']}/agents",
        json={
            "name": "A",
            "output_slots": [
                {
                    "id": "a1",
                    "origin": "custom",
                    "kind": "multiline_text",
                    "label": "out",
                    "bound_to": {"workflow_slot_label": "positive_prompt"},
                },
            ],
        },
    ).json()
    resp = client.patch(
        f"/api/comfy/sessions/{s['id']}/agents/{a['id']}",
        json={"output_slots": a["output_slots"]},
    )
    assert resp.status_code == 200, resp.text


# --- auto-slot resolution --------------------------------------------------


def test_auto_slot_snapshots_kind_and_description(client, conn):
    _seed_catalog(conn)
    wf = _make_workflow_with_slots(client, conn, slots=DEFAULT_SLOTS)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    resp = client.post(
        f"/api/comfy/sessions/{s['id']}/agents",
        json={
            "name": "A",
            "output_slots": [
                {
                    "id": "a1",
                    "origin": "auto",
                    "label": "auto_pos",
                    # no kind, no description
                    "bound_to": {"workflow_slot_label": "positive_prompt"},
                },
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    slot = resp.json()["output_slots"][0]
    assert slot["kind"] == "multiline_text"
    # description merges workflow slot description + catalog input notes
    desc = slot["description"] or ""
    assert "What we want to see" in desc  # from the workflow slot
    assert "Free-form prompt text" in desc  # from the catalog input semantic


def test_auto_slot_unbound_is_allowed(client, conn):
    _seed_catalog(conn)
    wf = _make_workflow_with_slots(client, conn, slots=DEFAULT_SLOTS)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    resp = client.post(
        f"/api/comfy/sessions/{s['id']}/agents",
        json={
            "name": "A",
            "output_slots": [
                {
                    "id": "a1",
                    "origin": "auto",
                    "label": "scratch",
                },
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    slot = resp.json()["output_slots"][0]
    assert slot["kind"] is None
    assert slot["bound_to"] is None


# --- patch + delete --------------------------------------------------------


def test_patch_updates_prompt_only(client, conn):
    _seed_catalog(conn)
    wf = _make_workflow_with_slots(client, conn, slots=DEFAULT_SLOTS)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    a = client.post(
        f"/api/comfy/sessions/{s['id']}/agents",
        json={"name": "A", "loras_enabled": True},
    ).json()
    resp = client.patch(
        f"/api/comfy/sessions/{s['id']}/agents/{a['id']}",
        json={"prompt": "make it dramatic"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["prompt"] == "make it dramatic"
    assert body["loras_enabled"] is True  # unchanged
    assert body["name"] == "A"  # unchanged


def test_patch_source_scope_selected_requires_ids(client, conn):
    _seed_catalog(conn)
    wf = _make_workflow_with_slots(client, conn, slots=DEFAULT_SLOTS)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    a = client.post(
        f"/api/comfy/sessions/{s['id']}/agents", json={"name": "A"},
    ).json()
    resp = client.patch(
        f"/api/comfy/sessions/{s['id']}/agents/{a['id']}",
        json={"source_scope": "selected"},  # without source_ids
    )
    assert resp.status_code == 422


def test_patch_source_scope_selected_with_ids(client, conn):
    _seed_catalog(conn)
    wf = _make_workflow_with_slots(client, conn, slots=DEFAULT_SLOTS)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    a = client.post(
        f"/api/comfy/sessions/{s['id']}/agents", json={"name": "A"},
    ).json()
    resp = client.patch(
        f"/api/comfy/sessions/{s['id']}/agents/{a['id']}",
        json={"source_scope": "selected", "source_ids": ["src1", "src2"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["source_scope"] == "selected"
    assert body["source_ids"] == ["src1", "src2"]


def test_delete_agent_removes_row(client, conn):
    _seed_catalog(conn)
    wf = _make_workflow_with_slots(client, conn, slots=DEFAULT_SLOTS)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    a = client.post(
        f"/api/comfy/sessions/{s['id']}/agents", json={"name": "A"},
    ).json()
    resp = client.delete(f"/api/comfy/sessions/{s['id']}/agents/{a['id']}")
    assert resp.status_code == 204
    assert client.get(
        f"/api/comfy/sessions/{s['id']}/agents/{a['id']}",
    ).status_code == 404


def test_delete_session_cascades_to_agents(client, conn):
    _seed_catalog(conn)
    wf = _make_workflow_with_slots(client, conn, slots=DEFAULT_SLOTS)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    a = client.post(
        f"/api/comfy/sessions/{s['id']}/agents", json={"name": "A"},
    ).json()
    client.delete(f"/api/sessions/{s['id']}")
    # Direct DB read — the public endpoint 404s on unknown session.
    rows = conn.execute(
        "SELECT id FROM comfy_session_agents WHERE id = ?", (a["id"],),
    ).fetchall()
    assert rows == []


# --- seed_default ----------------------------------------------------------


def test_seed_default_creates_one_agent_with_bound_outputs(client, conn):
    _seed_catalog(conn)
    wf = _make_workflow_with_slots(client, conn, slots=DEFAULT_SLOTS)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    resp = client.post(
        f"/api/comfy/sessions/{s['id']}/agents/seed_default",
    )
    assert resp.status_code == 200, resp.text
    agent = resp.json()["agent"]
    assert agent["name"] == "Default composer"
    labels = sorted(s["bound_to"]["workflow_slot_label"] for s in agent["output_slots"])
    assert labels == ["negative_prompt", "positive_prompt"]
    # auto-resolved kind
    assert all(s["kind"] == "multiline_text" for s in agent["output_slots"])


def test_seed_default_409_when_already_seeded(client, conn):
    _seed_catalog(conn)
    wf = _make_workflow_with_slots(client, conn, slots=DEFAULT_SLOTS)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    client.post(f"/api/comfy/sessions/{s['id']}/agents", json={"name": "manual"})
    resp = client.post(f"/api/comfy/sessions/{s['id']}/agents/seed_default")
    assert resp.status_code == 409


def test_seed_default_409_when_no_llm_slots(client, conn):
    _seed_catalog(conn)
    # Slot map with only frozen + user_image — no llm slots to seed.
    only_non_llm = [
        s for s in DEFAULT_SLOTS if s["binding"] != "llm"
    ]
    wf = _make_workflow_with_slots(client, conn, slots=only_non_llm)
    s = _make_comfy_session(client, workflow_id=wf["id"])
    resp = client.post(f"/api/comfy/sessions/{s['id']}/agents/seed_default")
    assert resp.status_code == 409
    assert "no binding=llm" in resp.json()["detail"]
