"""Phase 3 prep — chat slot-awareness (Q9) + prompt API payload field.

Verifies:
- Comfy sessions with a non-empty slot map get the slot list +
  no-JSON instruction appended to the chat system prompt.
- Comfy session chat uses the inferred mode (i2i / t2i) for
  framing, not the literal ``session_type = comfy``.
- Empty slot maps and legacy sessions skip the block.
- ``GET /api/sessions/{id}/prompts`` surfaces ``payload`` for comfy
  rows and ``prompt`` for legacy rows.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_conn
from app.main import app
from app.services import comfy_payload, lmstudio_client
from app.storage import (
    comfy_workflow_repo,
    library_repo,
    session_repo,
)
from app.storage import (
    db as db_mod,
)
from app.storage.migrations import apply_pending

SAMPLE_GRAPH = {
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
        "inputs": {"image": "ref.png"},
    },
}


def _seed_node(conn, *, class_type, inputs_raw):
    conn.execute(
        "INSERT OR IGNORE INTO comfy_packs(name, display_name, imported_at) "
        "VALUES (?, ?, 0)",
        ("ComfyUI", "ComfyUI"),
    )
    conn.execute(
        "INSERT INTO comfy_nodes(class_type, pack_name, display_name, "
        "  inputs_raw_json, outputs_raw_json, inputs_semantic_json, "
        "  description_md, imported_at, last_seen_in_object_info_at) "
        "VALUES (?, 'ComfyUI', ?, ?, '[]', '[]', '', 0, 0)",
        (class_type, class_type, json.dumps(inputs_raw)),
    )


def _seed_catalog(conn):
    _seed_node(
        conn, class_type="CLIPTextEncode",
        inputs_raw={"required": {
            "text": ["STRING", {"multiline": True}],
            "clip": ["CLIP", {}],
        }},
    )
    _seed_node(
        conn, class_type="LoadImage",
        inputs_raw={"required": {
            "image": [["ref.png"], {"image_upload": True}],
        }},
    )


@pytest.fixture
def conn(tmp_path, seed_default_families):
    c = db_mod.connect(tmp_path / "t.db")
    apply_pending(c, Path(__file__).parent.parent / "migrations")
    seed_default_families(c)
    _seed_catalog(c)
    yield c
    c.close()


@pytest.fixture
def client(conn):
    app.dependency_overrides[get_conn] = lambda: conn
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _bootstrap_lmstudio(client, monkeypatch):
    client.put(
        "/api/settings/lmstudio",
        json={"base_url": "http://h", "api_key": None},
    )
    monkeypatch.setattr(lmstudio_client, "list_models", lambda **_: [
        lmstudio_client.LmsModel(
            name="mistral", vision=False, tool_use=False, reasoning=False,
        ),
    ])
    client.post("/api/settings/lmstudio/refresh")
    client.patch(
        "/api/settings/lmstudio/models/mistral", json={"enabled": True},
    )


def _make_comfy_session(conn, client, *, slot_map):
    library_repo.create_model(
        conn, name="m1", display_name="m1", family_id="sdxl",
        description=None,
    )
    workflow = comfy_workflow_repo.insert_workflow(
        conn, name="W", graph=SAMPLE_GRAPH,
    )
    if slot_map is not None:
        comfy_workflow_repo.set_slot_map(
            conn, workflow_id=workflow["id"], slot_map=slot_map,
        )
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    sid = client.post(
        f"/api/projects/{pid}/sessions",
        json={
            "session_type": "comfy", "name": "comfy",
            "model_name": "m1", "use_negative": True,
            "comfy_workflow_id": workflow["id"],
        },
    ).json()["id"]
    client.patch(
        f"/api/sessions/{sid}",
        json={
            "name": "comfy", "model_name": "m1", "use_negative": True,
            "pinned_loras": [], "vl_model_name": None,
            "prompt_model_name": "mistral",
        },
    )
    return sid, workflow


def _capture_chat(client, monkeypatch, sid):
    captured: dict = {}

    def fake_stream(**kwargs):
        captured.update(kwargs)
        yield "ok"

    monkeypatch.setattr(lmstudio_client, "chat_stream", fake_stream)
    with client.stream(
        "POST", f"/api/sessions/{sid}/chat", json={"content": "hey"},
    ) as r:
        b"".join(r.iter_bytes())
    return captured


# --- chat slot-awareness (Q9) -------------------------------------------


def test_comfy_chat_appends_slot_block_for_non_empty_slot_map(
    conn, client, monkeypatch,
):
    _bootstrap_lmstudio(client, monkeypatch)
    slots = [
        {
            "label": "main_positive", "group": None, "ordinal": 1,
            "description": "main positive prompt", "kind": "multiline_text",
            "origin": {"node_id": "6", "input_name": "text"},
            "binding": "llm", "metadata": {"multiline": True},
        },
        {
            "label": "main_image", "group": None, "ordinal": 2,
            "description": None, "kind": "image",
            "origin": {"node_id": "10", "input_name": "image"},
            "binding": "user_image", "metadata": {},
        },
    ]
    sid, _ = _make_comfy_session(
        conn, client, slot_map={"version": 2, "slots": slots},
    )
    captured = _capture_chat(client, monkeypatch, sid)
    msgs = captured["messages"]
    system_text = "\n".join(m["content"] for m in msgs if m["role"] == "system")
    assert "main_positive (text (multiline)): main positive prompt" in system_text
    assert "main_image (image)" in system_text
    assert "Do not emit JSON" in system_text
    # Inferred mode is i2i (user_image slot wired) → i2i framing.
    assert "image-to-image" in system_text.lower()


def test_comfy_chat_uses_t2i_framing_when_no_user_image_slot(
    conn, client, monkeypatch,
):
    _bootstrap_lmstudio(client, monkeypatch)
    slots = [{
        "label": "positive", "group": None, "ordinal": 1,
        "description": None, "kind": "multiline_text",
        "origin": {"node_id": "6", "input_name": "text"},
        "binding": "llm", "metadata": {"multiline": True},
    }]
    sid, _ = _make_comfy_session(
        conn, client, slot_map={"version": 2, "slots": slots},
    )
    captured = _capture_chat(client, monkeypatch, sid)
    system_text = "\n".join(
        m["content"] for m in captured["messages"] if m["role"] == "system"
    )
    assert "text-to-image" in system_text.lower()


def test_comfy_chat_skips_slot_block_for_empty_slot_map(
    conn, client, monkeypatch,
):
    _bootstrap_lmstudio(client, monkeypatch)
    sid, _ = _make_comfy_session(conn, client, slot_map=None)
    captured = _capture_chat(client, monkeypatch, sid)
    system_text = "\n".join(
        m["content"] for m in captured["messages"] if m["role"] == "system"
    )
    assert "Do not emit JSON" not in system_text
    assert "labelled slots" not in system_text


def test_legacy_i2i_chat_does_not_get_slot_block(client, monkeypatch):
    _bootstrap_lmstudio(client, monkeypatch)
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    sid = client.post(
        f"/api/projects/{pid}/sessions",
        json={
            "session_type": "i2i", "name": "i2i",
            "model_name": None, "use_negative": True,
        },
    ).json()["id"]
    client.patch(
        f"/api/sessions/{sid}",
        json={
            "name": "i2i", "model_name": None, "use_negative": True,
            "pinned_loras": [], "vl_model_name": None,
            "prompt_model_name": "mistral",
        },
    )
    captured = _capture_chat(client, monkeypatch, sid)
    system_text = "\n".join(
        m["content"] for m in captured["messages"] if m["role"] == "system"
    )
    assert "Do not emit JSON" not in system_text
    assert "labelled slots" not in system_text


# --- prompt API: payload round-trip --------------------------------------


def test_prompts_endpoint_returns_payload_for_comfy_row(conn, client):
    """Comfy sessions persist via ``payload_json``; the read endpoint
    must surface ``payload`` and leave ``prompt`` null. The legacy
    ``loras_json`` column is mirrored back into ``payload.__loras``
    for shape-agnostic LoRA widgets."""
    library_repo.create_model(
        conn, name="m1", display_name="m1", family_id="sdxl",
        description=None,
    )
    workflow = comfy_workflow_repo.insert_workflow(
        conn, name="W", graph=SAMPLE_GRAPH,
    )
    project = session_repo.create_project(conn, name="P")
    session = session_repo.create_session(
        conn, project_id=project["id"], session_type="comfy",
        name="x", model_name="m1",
        comfy_workflow_id=workflow["id"],
    )
    session_repo.append_prompt(
        conn,
        session_id=session["id"],
        loras=[{"name": "noir", "weight": 0.7}],
        intents=[{"kind": "k", "query": "q"}],
        retrieved=None,
        brief="some brief",
        payload={"main_positive": "x"},
    )
    body = client.get(f"/api/sessions/{session['id']}/prompts").json()
    assert len(body["prompts"]) == 1
    row = body["prompts"][0]
    assert row["prompt"] is None
    assert row["payload"]["main_positive"] == "x"
    assert row["payload"][comfy_payload.LORAS_KEY] == [
        {"name": "noir", "weight": 0.7},
    ]


def test_prompts_endpoint_returns_legacy_prompt_for_i2i_row(conn, client):
    project = session_repo.create_project(conn, name="P")
    session = session_repo.create_session(
        conn, project_id=project["id"], session_type="i2i", name="x",
    )
    session_repo.append_prompt(
        conn,
        session_id=session["id"],
        positive="moody",
        negative="blurry",
        loras=[{"name": "lora-a", "weight": 0.5}],
        intents=None,
        retrieved=None,
    )
    body = client.get(f"/api/sessions/{session['id']}/prompts").json()
    row = body["prompts"][0]
    assert row["payload"] is None
    assert row["prompt"] == {
        "positive": "moody",
        "negative": "blurry",
        "loras": [{"name": "lora-a", "weight": 0.5}],
    }
