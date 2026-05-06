"""Phase 3 prep — orchestrator branch for comfy sessions.

Verifies that comfy-bound sessions produce a ``GeneratedPayload``
keyed by slot label (rather than the legacy ``GeneratedPrompt =
{positive, negative, loras}``). No graph patching, no execution —
those land in Phase 3.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import comfy_payload, prompt_orchestrator
from app.storage import (
    comfy_workflow_repo,
    library_repo,
    session_repo,
)
from app.storage import (
    db as db_mod,
)
from app.storage.migrations import apply_pending

# --- fixtures (mirror test_comfy_slot_map_api shapes) ---------------------


SAMPLE_GRAPH = {
    "3": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 0, "steps": 20, "cfg": 7.5,
            "model": ["4", 0],
            "positive": ["6", 0], "negative": ["7", 0],
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
    _seed_node(
        conn, class_type="KSampler",
        inputs_raw={"required": {
            "seed": ["INT", {"default": 0, "min": 0, "max": 1_000_000}],
            "steps": ["INT", {"default": 20, "min": 1, "max": 200}],
            "cfg": ["FLOAT", {"default": 7.5, "min": 0, "max": 30}],
        }},
    )
    _seed_node(
        conn, class_type="CheckpointLoaderSimple",
        inputs_raw={"required": {
            "ckpt_name": [["sd_xl_base.safetensors"], {}],
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


def _make_comfy_session(conn, *, slot_map):
    library_repo.create_model(
        conn, name="m1", display_name="m1", family_id="sdxl",
        description="model delta",
    )
    workflow = comfy_workflow_repo.insert_workflow(
        conn, name="W", graph=SAMPLE_GRAPH,
    )
    if slot_map is not None:
        comfy_workflow_repo.set_slot_map(
            conn, workflow_id=workflow["id"], slot_map=slot_map,
        )
    project = session_repo.create_project(conn, name="P")
    session = session_repo.create_session(
        conn, project_id=project["id"], session_type="comfy",
        name="comfy", model_name="m1",
        comfy_workflow_id=workflow["id"],
    )
    return session, workflow


def _slot_map_v2(slots):
    return {"version": 2, "slots": slots}


def _patch_lm(monkeypatch, *, intent_payload, composition_payload):
    """Return the captured-messages list and patch chat_complete."""
    captured: list[list[dict]] = []

    def fake_complete(*, endpoint, model, messages, response_format=None,
                      sampling=None, transport=None):
        captured.append(messages)
        if len(captured) == 1:
            return intent_payload
        return composition_payload

    monkeypatch.setattr(
        "app.services.prompt_orchestrator.lmstudio_client.chat_complete",
        fake_complete,
    )
    monkeypatch.setattr(
        "app.services.retriever.embedder.embed",
        lambda text: [0.001] * 1024,
    )
    return captured


# --- tests ----------------------------------------------------------------


def test_comfy_generate_produces_payload_keyed_by_label(conn, monkeypatch):
    slots = [
        {
            "label": "main_positive", "group": None, "ordinal": 1,
            "description": "positive prompt", "kind": "multiline_text",
            "origin": {"node_id": "6", "input_name": "text"},
            "binding": "llm", "metadata": {"multiline": True},
        },
        {
            "label": "main_negative", "group": None, "ordinal": 2,
            "description": None, "kind": "multiline_text",
            "origin": {"node_id": "7", "input_name": "text"},
            "binding": "llm", "metadata": {"multiline": True},
        },
        {
            "label": "seed", "group": None, "ordinal": 3,
            "description": None, "kind": "number_int",
            "origin": {"node_id": "3", "input_name": "seed"},
            "binding": "frozen", "metadata": {"value": 42, "min": 0, "max": 1000000},
        },
    ]
    session, _wf = _make_comfy_session(conn, slot_map=_slot_map_v2(slots))

    captured = _patch_lm(
        monkeypatch,
        intent_payload=json.dumps({"intents": [{"kind": "k", "query": "q"}]}),
        composition_payload=json.dumps({
            "main_positive": "a cat in a moody noir alley",
            "main_negative": "blurry, low quality",
            comfy_payload.LORAS_KEY: [{"name": "noir", "weight": 0.7}],
        }),
    )

    out = prompt_orchestrator.generate(
        conn, session_id=session["id"],
        endpoint={"base_url": "http://x/v1", "api_key": None},
        prompt_model="m1",
    )

    assert out["prompt"] is None
    assert out["payload"] == {
        "main_positive": "a cat in a moody noir alley",
        "main_negative": "blurry, low quality",
    }
    # The composition system message must enumerate both LLM-fillable
    # slots and describe the frozen seed for the LLM's awareness.
    composition_system = captured[1][0]["content"]
    assert "[fill] main_positive" in composition_system
    assert "[fill] main_negative" in composition_system
    assert "[frozen=42]" in composition_system
    assert "'main_positive'" in composition_system
    assert "'main_negative'" in composition_system

    # Persisted: payload_json non-NULL, loras_json carries the LoRA list.
    rows = session_repo.list_prompts(conn, session_id=session["id"])
    assert len(rows) == 1
    persisted = rows[0]
    assert persisted["positive"] == ""
    assert persisted["negative"] is None
    assert json.loads(persisted["payload_json"]) == out["payload"]
    assert json.loads(persisted["loras_json"]) == [
        {"name": "noir", "weight": 0.7},
    ]


def test_comfy_generate_infers_t2i_when_no_user_image_slot(conn, monkeypatch):
    """Slot map with only text slots ⇒ inferred mode is t2i, family
    guide gets ``prompt_t2i`` appended on top of ``prompt_guide``."""
    conn.execute(
        "UPDATE families SET prompt_guide = ?, prompt_t2i = ? WHERE id = 'sdxl'",
        ("BASE_GUIDE_X", "T2I_APPEND_MARKER"),
    )
    slots = [{
        "label": "positive", "group": None, "ordinal": 1,
        "description": None, "kind": "multiline_text",
        "origin": {"node_id": "6", "input_name": "text"},
        "binding": "llm", "metadata": {"multiline": True},
    }]
    session, _ = _make_comfy_session(conn, slot_map=_slot_map_v2(slots))

    captured = _patch_lm(
        monkeypatch,
        intent_payload=json.dumps({"intents": [{"kind": "k", "query": "q"}]}),
        composition_payload=json.dumps({
            "positive": "a cat",
            comfy_payload.LORAS_KEY: [],
        }),
    )

    prompt_orchestrator.generate(
        conn, session_id=session["id"],
        endpoint={"base_url": "http://x/v1", "api_key": None},
        prompt_model="m1",
    )
    composition_system = captured[1][0]["content"]
    assert "# Mode: t2i" in composition_system
    assert "T2I_APPEND_MARKER" in composition_system


def test_comfy_generate_infers_i2i_when_user_image_slot_present(conn, monkeypatch):
    """Slot map with a wired ``binding=user_image`` slot ⇒ inferred
    mode is i2i. The composition message picks up ``prompt_i2i``."""
    conn.execute(
        "UPDATE families SET prompt_i2i = ? WHERE id = 'sdxl'",
        ("I2I_APPEND_MARKER",),
    )
    slots = [
        {
            "label": "positive", "group": None, "ordinal": 1,
            "description": None, "kind": "multiline_text",
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
    session, _ = _make_comfy_session(conn, slot_map=_slot_map_v2(slots))

    captured = _patch_lm(
        monkeypatch,
        intent_payload=json.dumps({"intents": [{"kind": "k", "query": "q"}]}),
        composition_payload=json.dumps({
            "positive": "a cat",
            comfy_payload.LORAS_KEY: [],
        }),
    )
    prompt_orchestrator.generate(
        conn, session_id=session["id"],
        endpoint={"base_url": "http://x/v1", "api_key": None},
        prompt_model="m1",
    )
    composition_system = captured[1][0]["content"]
    assert "# Mode: i2i" in composition_system
    assert "I2I_APPEND_MARKER" in composition_system


def test_comfy_generate_does_not_require_main_image(conn, monkeypatch):
    """Comfy sessions with i2i-shaped slot map but no source images
    still run — image bindings are wired up by Phase 3 (the patcher),
    not gated by the orchestrator."""
    slots = [
        {
            "label": "positive", "group": None, "ordinal": 1,
            "description": None, "kind": "multiline_text",
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
    session, _ = _make_comfy_session(conn, slot_map=_slot_map_v2(slots))
    _patch_lm(
        monkeypatch,
        intent_payload=json.dumps({"intents": [{"kind": "k", "query": "q"}]}),
        composition_payload=json.dumps({
            "positive": "x", comfy_payload.LORAS_KEY: [],
        }),
    )
    out = prompt_orchestrator.generate(
        conn, session_id=session["id"],
        endpoint={"base_url": "http://x/v1", "api_key": None},
        prompt_model="m1",
    )
    assert out["payload"] == {"positive": "x"}


def test_comfy_generate_rejects_malformed_payload(conn, monkeypatch):
    slots = [{
        "label": "positive", "group": None, "ordinal": 1,
        "description": None, "kind": "multiline_text",
        "origin": {"node_id": "6", "input_name": "text"},
        "binding": "llm", "metadata": {"multiline": True},
    }]
    session, _ = _make_comfy_session(conn, slot_map=_slot_map_v2(slots))
    _patch_lm(
        monkeypatch,
        intent_payload=json.dumps({"intents": [{"kind": "k", "query": "q"}]}),
        composition_payload=json.dumps({
            # missing "positive"
            comfy_payload.LORAS_KEY: [],
        }),
    )
    from app.services.lmstudio_client import LmError
    with pytest.raises(LmError) as exc:
        prompt_orchestrator.generate(
            conn, session_id=session["id"],
            endpoint={"base_url": "http://x/v1", "api_key": None},
            prompt_model="m1",
        )
    assert exc.value.kind == "shape"


def test_comfy_generate_recovers_from_prose_around_json(conn, monkeypatch):
    slots = [{
        "label": "positive", "group": None, "ordinal": 1,
        "description": None, "kind": "multiline_text",
        "origin": {"node_id": "6", "input_name": "text"},
        "binding": "llm", "metadata": {"multiline": True},
    }]
    session, _ = _make_comfy_session(conn, slot_map=_slot_map_v2(slots))
    _patch_lm(
        monkeypatch,
        intent_payload=json.dumps({"intents": [{"kind": "k", "query": "q"}]}),
        composition_payload=(
            "Here is the payload:\n"
            '{"positive": "x", "__loras": []}\n'
            "Hope this helps."
        ),
    )
    out = prompt_orchestrator.generate(
        conn, session_id=session["id"],
        endpoint={"base_url": "http://x/v1", "api_key": None},
        prompt_model="m1",
    )
    assert out["payload"] == {"positive": "x"}


def test_comfy_generate_raises_when_no_workflow_bound(conn, monkeypatch):
    library_repo.create_model(
        conn, name="m1", display_name="m1", family_id="sdxl",
        description=None,
    )
    project = session_repo.create_project(conn, name="P")
    # Create a comfy session without binding a workflow by patching
    # session_type after creation (the API path requires comfy_workflow_id;
    # this fixture exercises the orchestrator's guard directly).
    session = session_repo.create_session(
        conn, project_id=project["id"], session_type="i2i",
        name="x", model_name="m1",
    )
    conn.execute(
        "UPDATE sessions SET session_type = 'comfy' WHERE id = ?",
        (session["id"],),
    )
    with pytest.raises(prompt_orchestrator.PreconditionError):
        prompt_orchestrator.generate(
            conn, session_id=session["id"],
            endpoint={"base_url": "http://x/v1", "api_key": None},
            prompt_model="m1",
        )
