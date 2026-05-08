"""Tests for the per-agent run path
(:mod:`app.services.comfy_agent_runner`).

Covers the slot inclusion rules ("auto + unbound is skipped",
non-LLM kinds are skipped), the precondition errors (no LMStudio
URL, no model, no composable slots), and the happy path end-to-end
through the HTTP endpoint with a stubbed ``chat_complete``.
"""
from __future__ import annotations

import json as _json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_conn
from app.main import app
from app.services import comfy_agent_runner, lmstudio_client
from app.storage import (
    comfy_session_agent_repo as agent_repo,
    comfy_workflow_repo,
    library_repo,
    session_repo,
    settings_repo,
    source_image_repo,
)
from app.storage import db as db_mod
from app.storage.migrations import apply_pending


# Smallest valid 1x1 PNG ("\x89PNG\r\n\x1a\n…"). Decoded from the
# canonical fixture used elsewhere in the test suite.
_PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
    b"\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9c"
    b"c\xfc\xff\xff?\x03\x00\x05\xfe\x02\xfe\xa3:\xeb\xa6\x00\x00\x00"
    b"\x00IEND\xaeB`\x82"
)


# --- fixtures (mirror test_comfy_agents_api.py) ---------------------------


@pytest.fixture
def conn(tmp_path):
    c = db_mod.connect(tmp_path / "s.db")
    apply_pending(c, Path(__file__).parent.parent / "migrations")
    settings_repo.set_lmstudio(c, url="http://lm:1234", api_key=None)
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
            "negative": ["7", 0],
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
}


SLOTS = [
    {
        "label": "positive_prompt",
        "group": None, "ordinal": 1,
        "description": "What we want to see.",
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
        "label": "steps",
        "group": None, "ordinal": 3,
        "description": None,
        "kind": "number_int",
        "origin": {"node_id": "3", "input_name": "steps"},
        "binding": "llm",
        "metadata": {"default": 20, "min": 1, "max": 200},
    },
]


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
        (class_type, class_type, _json.dumps(inputs_raw)),
    )


def _seed_catalog(conn):
    _seed_node(
        conn, class_type="CLIPTextEncode",
        inputs_raw={"required": {"text": ["STRING", {"multiline": True}]}},
    )
    _seed_node(
        conn, class_type="KSampler",
        inputs_raw={"required": {
            "steps": ["INT", {"default": 20, "min": 1, "max": 200}],
        }},
    )
    _seed_node(
        conn, class_type="CheckpointLoaderSimple",
        inputs_raw={"required": {"ckpt_name": [["sd_xl_base.safetensors"], {}]}},
    )


def _make_workflow(conn, *, slots):
    wf = comfy_workflow_repo.insert_workflow(
        conn, name="W", graph=SAMPLE_GRAPH,
    )
    comfy_workflow_repo.set_slot_map(
        conn, workflow_id=wf["id"],
        slot_map={"version": 2, "slots": slots},
    )
    return wf


def _make_session(conn, *, workflow_id, prompt_model="m1"):
    pid = session_repo.create_project(conn, name="P")["id"]
    s = session_repo.create_session(
        conn, project_id=pid, session_type="comfy",
        name="comfy", model_name=None,
        comfy_workflow_id=workflow_id,
    )
    if prompt_model is not None:
        session_repo.update_session(
            conn, s["id"], name=s["name"], model_name=None, use_negative=True,
            prompt_model_name=prompt_model,
        )
    return session_repo.get_session(conn, s["id"])


def _make_agent(conn, *, session_id, output_slots, model_params=None,
                model_name=None, prompt="describe a scene"):
    return agent_repo.insert_agent(
        conn, session_id=session_id,
        name="Composer", prompt=prompt,
        model_name=model_name, model_params=model_params,
        source_scope="all", source_ids=None,
        loras_enabled=False,
        output_slots=output_slots,
    )


def _patch_chat(monkeypatch, *, payload, capture=None):
    def fake(*, endpoint, model, messages, response_format=None,
             sampling=None, transport=None):
        if capture is not None:
            capture.append({
                "endpoint": endpoint, "model": model, "messages": messages,
                "response_format": response_format, "sampling": sampling,
            })
        return payload
    monkeypatch.setattr(
        "app.services.comfy_agent_runner.lmstudio_client.chat_complete",
        fake,
    )


# --- selection rules ------------------------------------------------------


def test_select_skips_auto_unbound_and_non_llm_kinds(conn):
    _seed_catalog(conn)
    wf = _make_workflow(conn, slots=SLOTS)
    s = _make_session(conn, workflow_id=wf["id"])

    output_slots = [
        # composed: bound preset, multiline_text
        {
            "id": "p1", "origin": "preset", "preset": "positive",
            "kind": "multiline_text", "label": "positive_prompt",
            "description": None, "last_value": None,
            "bound_to": {"workflow_slot_label": "positive_prompt"},
        },
        # skipped: auto + unbound (no kind, nothing to bind to)
        {
            "id": "a1", "origin": "auto", "preset": None,
            "kind": None, "label": "auto_unbound",
            "description": None, "last_value": None,
            "bound_to": None,
        },
        # skipped: kind=lora_name is not LLM-composed
        {
            "id": "c1", "origin": "custom", "preset": None,
            "kind": "lora_name", "label": "picked_lora",
            "description": None, "last_value": None,
            "bound_to": None,
        },
    ]
    _make_agent(
        conn, session_id=s["id"], output_slots=output_slots,
    )

    selected = comfy_agent_runner._select_composable_slots(output_slots)
    assert [s["label"] for s in selected] == ["positive_prompt"]


# --- happy path through the endpoint --------------------------------------


def test_run_endpoint_persists_last_values_and_bumps_last_run_at(
    client, conn, monkeypatch,
):
    _seed_catalog(conn)
    wf = _make_workflow(conn, slots=SLOTS)
    s = _make_session(conn, workflow_id=wf["id"])
    output_slots = [
        {
            "id": "p1", "origin": "preset", "preset": "positive",
            "kind": "multiline_text", "label": "positive_prompt",
            "description": "the positive", "last_value": None,
            "bound_to": {"workflow_slot_label": "positive_prompt"},
        },
        {
            "id": "p2", "origin": "preset", "preset": "negative",
            "kind": "multiline_text", "label": "negative_prompt",
            "description": None, "last_value": None,
            "bound_to": {"workflow_slot_label": "negative_prompt"},
        },
        {
            "id": "n1", "origin": "auto", "preset": None,
            "kind": None, "label": "auto_unbound",
            "description": None, "last_value": "previous",
            "bound_to": None,
        },
    ]
    a = _make_agent(
        conn, session_id=s["id"], output_slots=output_slots,
        model_name="m1",
    )

    captured: list[dict] = []
    _patch_chat(
        monkeypatch,
        payload=_json.dumps({
            "positive_prompt": "a moody cat in noir alley",
            "negative_prompt": "blurry, watermark",
        }),
        capture=captured,
    )

    resp = client.post(
        f"/api/comfy/sessions/{s['id']}/agents/{a['id']}/run",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    by_label = {row["label"]: row for row in body["output_slots"]}
    assert by_label["positive_prompt"]["last_value"] == "a moody cat in noir alley"
    assert by_label["negative_prompt"]["last_value"] == "blurry, watermark"
    # auto+unbound must keep its previous value untouched.
    assert by_label["auto_unbound"]["last_value"] == "previous"
    assert body["last_run_at"] is not None

    # The system prompt must enumerate each composable slot by label
    # and tell the model which JSON shape to emit.
    [call] = captured
    sys = call["messages"][0]["content"]
    assert "positive_prompt" in sys
    assert "negative_prompt" in sys
    assert "auto_unbound" not in sys
    assert "JSON" in sys


def test_run_coerces_number_int_returned_as_string(
    client, conn, monkeypatch,
):
    _seed_catalog(conn)
    wf = _make_workflow(conn, slots=SLOTS)
    s = _make_session(conn, workflow_id=wf["id"])
    a = _make_agent(
        conn, session_id=s["id"],
        model_name="m1",
        output_slots=[
            {
                "id": "i1", "origin": "custom", "preset": None,
                "kind": "number_int", "label": "steps",
                "description": None, "last_value": None,
                "bound_to": {"workflow_slot_label": "steps"},
            },
        ],
    )
    _patch_chat(
        monkeypatch, payload=_json.dumps({"steps": "24"}),
    )
    resp = client.post(
        f"/api/comfy/sessions/{s['id']}/agents/{a['id']}/run",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["output_slots"][0]["last_value"] == 24


# --- precondition errors --------------------------------------------------


def test_run_409_when_no_lmstudio_url_configured(client, conn, monkeypatch):
    _seed_catalog(conn)
    wf = _make_workflow(conn, slots=SLOTS)
    s = _make_session(conn, workflow_id=wf["id"])
    a = _make_agent(
        conn, session_id=s["id"], model_name="m1",
        output_slots=[
            {
                "id": "p1", "origin": "preset", "preset": "positive",
                "kind": "multiline_text", "label": "positive_prompt",
                "description": None, "last_value": None,
                "bound_to": {"workflow_slot_label": "positive_prompt"},
            },
        ],
    )
    settings_repo.set_lmstudio(conn, url=None, api_key=None)
    resp = client.post(
        f"/api/comfy/sessions/{s['id']}/agents/{a['id']}/run",
    )
    assert resp.status_code == 409
    assert "LMStudio" in resp.json()["detail"]


def test_run_409_when_agent_has_no_composable_slots(
    client, conn, monkeypatch,
):
    _seed_catalog(conn)
    wf = _make_workflow(conn, slots=SLOTS)
    s = _make_session(conn, workflow_id=wf["id"])
    a = _make_agent(
        conn, session_id=s["id"], model_name="m1",
        output_slots=[
            # Auto + unbound — would be skipped.
            {
                "id": "n1", "origin": "auto", "preset": None,
                "kind": None, "label": "auto_unbound",
                "description": None, "last_value": None,
                "bound_to": None,
            },
        ],
    )
    resp = client.post(
        f"/api/comfy/sessions/{s['id']}/agents/{a['id']}/run",
    )
    assert resp.status_code == 409
    assert "composable" in resp.json()["detail"]


def test_run_409_when_no_model_set(client, conn, monkeypatch):
    _seed_catalog(conn)
    wf = _make_workflow(conn, slots=SLOTS)
    # Session has no prompt_model_name and the agent has no model_name —
    # the runner has nothing to call with.
    s = _make_session(conn, workflow_id=wf["id"], prompt_model=None)
    a = _make_agent(
        conn, session_id=s["id"], model_name=None,
        output_slots=[
            {
                "id": "p1", "origin": "preset", "preset": "positive",
                "kind": "multiline_text", "label": "positive_prompt",
                "description": None, "last_value": None,
                "bound_to": {"workflow_slot_label": "positive_prompt"},
            },
        ],
    )
    resp = client.post(
        f"/api/comfy/sessions/{s['id']}/agents/{a['id']}/run",
    )
    assert resp.status_code == 409
    assert "model" in resp.json()["detail"].lower()


def test_run_502_on_upstream_lm_error(client, conn, monkeypatch):
    _seed_catalog(conn)
    wf = _make_workflow(conn, slots=SLOTS)
    s = _make_session(conn, workflow_id=wf["id"])
    a = _make_agent(
        conn, session_id=s["id"], model_name="m1",
        output_slots=[
            {
                "id": "p1", "origin": "preset", "preset": "positive",
                "kind": "multiline_text", "label": "positive_prompt",
                "description": None, "last_value": None,
                "bound_to": {"workflow_slot_label": "positive_prompt"},
            },
        ],
    )

    def fail(**_kwargs):
        raise lmstudio_client.LmError("upstream", "boom")

    monkeypatch.setattr(
        "app.services.comfy_agent_runner.lmstudio_client.chat_complete",
        fail,
    )
    resp = client.post(
        f"/api/comfy/sessions/{s['id']}/agents/{a['id']}/run",
    )
    assert resp.status_code == 502


# --- input slot rendering -------------------------------------------------


def test_input_slots_extend_system_prompt(client, conn, monkeypatch):
    _seed_catalog(conn)
    wf = _make_workflow(conn, slots=SLOTS)
    s = _make_session(conn, workflow_id=wf["id"])
    library_repo.create_family(
        conn, id="sdxl", display_name="SDXL",
        prompt_guide="Tag-based prompting works best.",
        prompt_i2i="Keep edits minimal.",
        prompt_t2i="Lead with subject + style.",
    )
    a = _make_agent(
        conn, session_id=s["id"], model_name="m1",
        model_params={
            "temperature": 0.5,
            "__input_slots": [
                {
                    "id": "g1", "kind": "system",
                    "label": "system",
                    "description": None,
                    "system": {"text": "Always write in lowercase."},
                },
                {
                    "id": "g2", "kind": "prompt_guide",
                    "label": "guide",
                    "description": None,
                    "prompt_guide": {
                        "guide_id": "sdxl",
                        "generation_type": "t2i",
                    },
                },
            ],
        },
        output_slots=[
            {
                "id": "p1", "origin": "preset", "preset": "positive",
                "kind": "multiline_text", "label": "positive_prompt",
                "description": None, "last_value": None,
                "bound_to": {"workflow_slot_label": "positive_prompt"},
            },
        ],
    )
    captured: list[dict] = []
    _patch_chat(
        monkeypatch,
        payload=_json.dumps({"positive_prompt": "ok"}),
        capture=captured,
    )
    resp = client.post(
        f"/api/comfy/sessions/{s['id']}/agents/{a['id']}/run",
    )
    assert resp.status_code == 200
    [call] = captured
    sys = call["messages"][0]["content"]
    assert "Always write in lowercase." in sys
    assert "Tag-based prompting works best." in sys
    assert "Lead with subject + style." in sys
    # i2i guide must NOT leak when generation_type=t2i.
    assert "Keep edits minimal." not in sys
    # Sampling forwarded; __input_slots stripped.
    assert call["sampling"] == {"temperature": 0.5}


# --- source input slot (VL pass) ------------------------------------------


def _seed_vl_model(conn, name: str = "vlm"):
    settings_repo.upsert_lm_models(
        conn,
        models=[
            {"name": name, "vision": True, "tool_use": False, "reasoning": False},
        ],
    )


def _attach_source_image(conn, *, session_id, tmp_path, monkeypatch,
                          filename="ref.png") -> dict:
    """Stage a real image file under a tmp data root and register the
    row. Returns the inserted source-image record."""
    data_root = tmp_path / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    img_dir = data_root / "sources" / session_id
    img_dir.mkdir(parents=True, exist_ok=True)
    img_path = img_dir / filename
    img_path.write_bytes(_PNG_1X1)
    monkeypatch.setattr(
        "app.services.comfy_agent_runner.app_config.resolve_data_root",
        lambda anchor_file=None: data_root,
    )
    return source_image_repo.insert(
        conn, session_id=session_id,
        path=str(img_path.relative_to(data_root)),
        original_filename=filename, is_main=True,
    )


def _agent_with_source_input(*, slot_id="src1", source_slot_id="ui-1",
                              vl_model="vlm", vl_prompt="describe"):
    return {
        "id": slot_id, "kind": "source", "label": "main",
        "description": None,
        "source": {
            "source_slot_id": source_slot_id,
            "vl_model": vl_model,
            "vl_prompt": vl_prompt,
            "vl_temperature": 0.2,
            "vl_max_tokens": 200,
        },
    }


def test_source_input_runs_vl_pass_and_appends_summary(
    client, conn, monkeypatch, tmp_path,
):
    _seed_catalog(conn)
    _seed_vl_model(conn)
    wf = _make_workflow(conn, slots=SLOTS)
    s = _make_session(conn, workflow_id=wf["id"])
    img = _attach_source_image(
        conn, session_id=s["id"], tmp_path=tmp_path, monkeypatch=monkeypatch,
    )
    a = _make_agent(
        conn, session_id=s["id"], model_name="m1",
        model_params={"__input_slots": [_agent_with_source_input()]},
        output_slots=[
            {
                "id": "p1", "origin": "preset", "preset": "positive",
                "kind": "multiline_text", "label": "positive_prompt",
                "description": None, "last_value": None,
                "bound_to": {"workflow_slot_label": "positive_prompt"},
            },
        ],
    )

    vl_calls: list[dict] = []

    def fake_analyze(*, endpoint, model, image_bytes, content_type,
                     refining_prompt, sampling=None, transport=None):
        vl_calls.append({
            "model": model, "content_type": content_type,
            "refining_prompt": refining_prompt, "sampling": sampling,
            "image_len": len(image_bytes),
        })
        return "a tiny test pixel"

    monkeypatch.setattr(
        "app.services.comfy_agent_runner.lmstudio_client.analyze_image",
        fake_analyze,
    )
    captured: list[dict] = []
    _patch_chat(
        monkeypatch,
        payload=_json.dumps({"positive_prompt": "ok"}),
        capture=captured,
    )

    resp = client.post(
        f"/api/comfy/sessions/{s['id']}/agents/{a['id']}/run",
        json={"source_image_overrides": {"src1": img["id"]}},
    )
    assert resp.status_code == 200, resp.text

    assert len(vl_calls) == 1
    assert vl_calls[0]["model"] == "vlm"
    assert vl_calls[0]["content_type"] == "image/png"
    assert vl_calls[0]["refining_prompt"] == "describe"
    assert vl_calls[0]["sampling"] == {"temperature": 0.2, "max_tokens": 200}

    sys = captured[0]["messages"][0]["content"]
    assert "a tiny test pixel" in sys
    assert "main" in sys


def test_source_input_skips_softly_when_image_not_resolved(
    client, conn, monkeypatch,
):
    _seed_catalog(conn)
    _seed_vl_model(conn)
    wf = _make_workflow(conn, slots=SLOTS)
    s = _make_session(conn, workflow_id=wf["id"])
    a = _make_agent(
        conn, session_id=s["id"], model_name="m1",
        model_params={"__input_slots": [_agent_with_source_input()]},
        output_slots=[
            {
                "id": "p1", "origin": "preset", "preset": "positive",
                "kind": "multiline_text", "label": "positive_prompt",
                "description": None, "last_value": None,
                "bound_to": {"workflow_slot_label": "positive_prompt"},
            },
        ],
    )

    def fail_analyze(**_kwargs):
        raise AssertionError("VL should not be called when no image is resolved")

    monkeypatch.setattr(
        "app.services.comfy_agent_runner.lmstudio_client.analyze_image",
        fail_analyze,
    )
    captured: list[dict] = []
    _patch_chat(
        monkeypatch,
        payload=_json.dumps({"positive_prompt": "ok"}),
        capture=captured,
    )

    # No override entry for slot id "src1" — runner reports a soft
    # warning and proceeds with the chat call.
    resp = client.post(
        f"/api/comfy/sessions/{s['id']}/agents/{a['id']}/run",
        json={"source_image_overrides": {}},
    )
    assert resp.status_code == 200
    sys = captured[0]["messages"][0]["content"]
    assert "no image bound" in sys


def test_source_input_skips_softly_when_vl_model_disabled(
    client, conn, monkeypatch, tmp_path,
):
    _seed_catalog(conn)
    # vlm exists but is disabled.
    _seed_vl_model(conn)
    settings_repo.patch_lm_model(conn, name="vlm", enabled=False)
    wf = _make_workflow(conn, slots=SLOTS)
    s = _make_session(conn, workflow_id=wf["id"])
    img = _attach_source_image(
        conn, session_id=s["id"], tmp_path=tmp_path, monkeypatch=monkeypatch,
    )
    a = _make_agent(
        conn, session_id=s["id"], model_name="m1",
        model_params={"__input_slots": [_agent_with_source_input()]},
        output_slots=[
            {
                "id": "p1", "origin": "preset", "preset": "positive",
                "kind": "multiline_text", "label": "positive_prompt",
                "description": None, "last_value": None,
                "bound_to": {"workflow_slot_label": "positive_prompt"},
            },
        ],
    )

    def fail_analyze(**_kwargs):
        raise AssertionError("VL should not be called when model is disabled")

    monkeypatch.setattr(
        "app.services.comfy_agent_runner.lmstudio_client.analyze_image",
        fail_analyze,
    )
    captured: list[dict] = []
    _patch_chat(
        monkeypatch,
        payload=_json.dumps({"positive_prompt": "ok"}),
        capture=captured,
    )

    resp = client.post(
        f"/api/comfy/sessions/{s['id']}/agents/{a['id']}/run",
        json={"source_image_overrides": {"src1": img["id"]}},
    )
    assert resp.status_code == 200
    sys = captured[0]["messages"][0]["content"]
    assert "disabled" in sys or "vision-capable" in sys


def test_source_input_swallows_upstream_vl_error(
    client, conn, monkeypatch, tmp_path,
):
    _seed_catalog(conn)
    _seed_vl_model(conn)
    wf = _make_workflow(conn, slots=SLOTS)
    s = _make_session(conn, workflow_id=wf["id"])
    img = _attach_source_image(
        conn, session_id=s["id"], tmp_path=tmp_path, monkeypatch=monkeypatch,
    )
    a = _make_agent(
        conn, session_id=s["id"], model_name="m1",
        model_params={"__input_slots": [_agent_with_source_input()]},
        output_slots=[
            {
                "id": "p1", "origin": "preset", "preset": "positive",
                "kind": "multiline_text", "label": "positive_prompt",
                "description": None, "last_value": None,
                "bound_to": {"workflow_slot_label": "positive_prompt"},
            },
        ],
    )

    def boom_analyze(**_kwargs):
        raise lmstudio_client.LmError("upstream", "vl boom")

    monkeypatch.setattr(
        "app.services.comfy_agent_runner.lmstudio_client.analyze_image",
        boom_analyze,
    )
    captured: list[dict] = []
    _patch_chat(
        monkeypatch,
        payload=_json.dumps({"positive_prompt": "ok"}),
        capture=captured,
    )

    # The VL error must NOT abort the run; the agent's own /run keeps
    # going and surfaces the failure as a system-prompt warning.
    resp = client.post(
        f"/api/comfy/sessions/{s['id']}/agents/{a['id']}/run",
        json={"source_image_overrides": {"src1": img["id"]}},
    )
    assert resp.status_code == 200
    sys = captured[0]["messages"][0]["content"]
    assert "VL call failed" in sys
