"""Tests for the per-node import wizard SSE endpoint.

Covers the four stages and their happy/error paths. Both ComfyUI and
LMStudio are mocked — the test focuses on validation, persistence, and
event shapes.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_conn
from app.main import app
from app.services import comfy_client, comfy_import_service, lmstudio_client
from app.storage import db as db_mod
from app.storage.migrations import apply_pending


@pytest.fixture
def conn(tmp_path):
    c = db_mod.connect(tmp_path / "s.db")
    apply_pending(c, Path(__file__).parent.parent / "migrations")
    yield c
    c.close()


@pytest.fixture
def comfyui_install(tmp_path):
    """Filesystem fixture mimicking a real ComfyUI install."""
    install = tmp_path / "ComfyUI"
    custom = install / "custom_nodes"
    custom.mkdir(parents=True)
    pack_dir = custom / "z-image-turbo"
    pack_dir.mkdir()
    (pack_dir / "pyproject.toml").write_text(
        '[project]\n'
        'name = "z-image-turbo"\n'
        'description = "Z-Image."\n'
        'version = "1.0"\n\n'
        '[project.urls]\n'
        'Repository = "https://github.com/tpc2233/ComfyUI-Z-Image-Turbo"\n\n'
        '[tool.comfy]\n'
        'PublisherId = "tpc2233"\n'
        'DisplayName = "ComfyUI-Z-Image-Turbo"\n',
        encoding="utf-8",
    )
    (pack_dir / "README.md").write_text("# Z-Image-Turbo\n\nLoader and sampler.\n")
    return install


@pytest.fixture
def client(conn, comfyui_install):
    # Configure ComfyUI + LMStudio settings for the test connection.
    conn.execute(
        "UPDATE app_settings SET comfyui_url = 'http://h', "
        "comfyui_path = ?, lmstudio_url = 'http://lm' WHERE id = 1",
        (str(comfyui_install),),
    )
    # Seed a favourite LMStudio model so the wizard knows what to call.
    conn.execute(
        "INSERT INTO lm_models(name, enabled, last_seen, vision, tool_use, "
        "  reasoning, favorite, hidden) "
        "VALUES('qwen-coder', 1, 0, 0, 1, 0, 1, 0)",
    )
    app.dependency_overrides[get_conn] = lambda: conn
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


_FAKE_NODE_INFO = {
    "ZImageLoader": {
        "input": {
            "required": {
                "model_name": ["STRING", {"default": "z-turbo"}],
                "device": ["STRING", {"default": "cuda"}],
            },
        },
        "output": ["MODEL"],
        "display_name": "Z-Image Turbo Loader (ModelScope)",
        "description": "Loads the Z-Image Turbo model.",
        "category": "Z-Image-Turbo",
        "python_module": "custom_nodes.z-image-turbo",
    },
}


def _read_sse_events(response) -> list[dict]:
    events: list[dict] = []
    for line in response.iter_lines():
        if not line:
            continue
        line = line.strip()
        if line.startswith("data:"):
            events.append(json.loads(line[len("data:"):].strip()))
    return events


def test_import_runs_all_four_stages_and_persists(client, monkeypatch):
    monkeypatch.setattr(comfy_client, "object_info", lambda **_: _FAKE_NODE_INFO)

    def fake_chat_complete(**kwargs):
        return json.dumps({
            "description_md": "Loads the Z-Image Turbo weights via ModelScope.",
            "inputs": [
                {"name": "model_name", "notes": "Path on disk."},
                {"name": "device", "notes": "GPU device"},
            ],
        })

    monkeypatch.setattr(lmstudio_client, "chat_complete", fake_chat_complete)

    resp = client.post("/api/comfy/nodes/ZImageLoader/import")
    assert resp.status_code == 200, resp.text
    events = _read_sse_events(resp)

    types = [e["type"] for e in events]
    # Each stage emits started + succeeded.
    assert types == [
        "stage_started", "stage_succeeded",
        "stage_started", "stage_succeeded",
        "stage_started", "stage_succeeded",
        "stage_started", "stage_succeeded",
        "done",
    ]
    stages = [e["stage"] for e in events if "stage" in e]
    assert stages == [
        "locate_pack", "locate_pack",
        "fetch_schema", "fetch_schema",
        "enrich_llm", "enrich_llm",
        "persist", "persist",
    ]

    locate = next(e for e in events if e["type"] == "stage_succeeded" and e["stage"] == "locate_pack")
    assert locate["data"]["pack"]["name"] == "z-image-turbo"
    assert locate["data"]["pack"]["repo_url"].endswith("ComfyUI-Z-Image-Turbo")
    assert locate["data"]["readme_present"] is True

    fetch = next(e for e in events if e["type"] == "stage_succeeded" and e["stage"] == "fetch_schema")
    assert fetch["data"]["input_names"] == ["model_name", "device"]

    enrich = next(e for e in events if e["type"] == "stage_succeeded" and e["stage"] == "enrich_llm")
    assert enrich["data"]["description_md"].startswith("Loads")
    notes_by_name = {i["name"]: i["notes"] for i in enrich["data"]["inputs_semantic"]}
    assert notes_by_name == {"model_name": "Path on disk.", "device": "GPU device"}

    done = events[-1]
    assert done["type"] == "done"
    assert done["node"]["class_type"] == "ZImageLoader"

    # Persisted in the catalog.
    listed = client.get("/api/comfy/nodes").json()["nodes"]
    assert [n["class_type"] for n in listed] == ["ZImageLoader"]
    body = client.get("/api/comfy/nodes/ZImageLoader").json()
    assert body["description_md"].startswith("Loads")
    assert all(set(item) == {"name", "notes"} for item in body["inputs_semantic"])


def test_import_fails_when_class_type_unknown(client, monkeypatch):
    monkeypatch.setattr(comfy_client, "object_info", lambda **_: {})
    resp = client.post("/api/comfy/nodes/Ghost/import")
    events = _read_sse_events(resp)
    assert events[-1]["type"] == "stage_failed"
    assert events[-1]["stage"] == "locate_pack"
    assert "Ghost" in events[-1]["error"]


def test_import_fails_when_comfyui_unreachable(client, monkeypatch):
    def boom(**_):
        raise comfy_client.ComfyError("upstream", "boom")
    monkeypatch.setattr(comfy_client, "object_info", boom)
    events = _read_sse_events(client.post("/api/comfy/nodes/ZImageLoader/import"))
    assert events[-1]["type"] == "stage_failed"
    assert events[-1]["stage"] == "locate_pack"


def test_import_fails_on_invalid_llm_json(client, monkeypatch):
    monkeypatch.setattr(comfy_client, "object_info", lambda **_: _FAKE_NODE_INFO)
    monkeypatch.setattr(
        lmstudio_client, "chat_complete", lambda **_: "not-json",
    )
    events = _read_sse_events(client.post("/api/comfy/nodes/ZImageLoader/import"))
    assert events[-1]["type"] == "stage_failed"
    assert events[-1]["stage"] == "enrich_llm"
    assert "JSON" in events[-1]["error"]


def test_import_rejects_hallucinated_input_names(client, monkeypatch):
    monkeypatch.setattr(comfy_client, "object_info", lambda **_: _FAKE_NODE_INFO)
    monkeypatch.setattr(
        lmstudio_client, "chat_complete",
        lambda **_: json.dumps({
            "description_md": "x",
            "inputs": [
                {"name": "model_name", "notes": None},
                {"name": "made_up_input", "notes": None},
            ],
        }),
    )
    events = _read_sse_events(client.post("/api/comfy/nodes/ZImageLoader/import"))
    assert events[-1]["type"] == "stage_failed"
    assert events[-1]["stage"] == "enrich_llm"
    assert "made_up_input" in events[-1]["error"]


def test_import_ignores_legacy_role_hint_keys(client, monkeypatch):
    """Phase 1 imports asked the LLM for ``role_hint`` per input. Phase 2
    drops that field; the wizard now accepts (and silently ignores) any
    ``role_hint`` key the LLM emits, so older system prompts and
    reasoning-distilled models don't break the import path."""
    monkeypatch.setattr(comfy_client, "object_info", lambda **_: _FAKE_NODE_INFO)
    monkeypatch.setattr(
        lmstudio_client, "chat_complete",
        lambda **_: json.dumps({
            "description_md": "x",
            "inputs": [{"name": "model_name", "role_hint": "weird-role", "notes": "ok"}],
        }),
    )
    events = _read_sse_events(client.post("/api/comfy/nodes/ZImageLoader/import"))
    assert events[-1]["type"] == "done"
    body = client.get("/api/comfy/nodes/ZImageLoader").json()
    assert all("role_hint" not in item for item in body["inputs_semantic"])


def test_import_fills_defaults_for_unmentioned_inputs(client, monkeypatch):
    """When the LLM mentions only a subset of inputs, the rest get
    notes=null defaults so the catalog row covers every input."""
    monkeypatch.setattr(comfy_client, "object_info", lambda **_: _FAKE_NODE_INFO)
    monkeypatch.setattr(
        lmstudio_client, "chat_complete",
        lambda **_: json.dumps({
            "description_md": "x",
            "inputs": [
                {"name": "model_name", "notes": "Path on disk."},
            ],
        }),
    )
    events = _read_sse_events(client.post("/api/comfy/nodes/ZImageLoader/import"))
    assert events[-1]["type"] == "done"

    body = client.get("/api/comfy/nodes/ZImageLoader").json()
    names = {i["name"] for i in body["inputs_semantic"]}
    assert names == {"model_name", "device"}


def test_import_fails_when_lmstudio_unconfigured(client, monkeypatch, conn):
    monkeypatch.setattr(comfy_client, "object_info", lambda **_: _FAKE_NODE_INFO)
    conn.execute("UPDATE app_settings SET lmstudio_url = NULL WHERE id = 1")
    events = _read_sse_events(client.post("/api/comfy/nodes/ZImageLoader/import"))
    failed = [e for e in events if e["type"] == "stage_failed"]
    assert failed and failed[-1]["stage"] == "enrich_llm"


def test_import_fails_when_no_favourite_model(client, monkeypatch, conn):
    monkeypatch.setattr(comfy_client, "object_info", lambda **_: _FAKE_NODE_INFO)
    conn.execute("UPDATE lm_models SET favorite = 0 WHERE name = 'qwen-coder'")
    events = _read_sse_events(client.post("/api/comfy/nodes/ZImageLoader/import"))
    failed = [e for e in events if e["type"] == "stage_failed"]
    assert failed and failed[-1]["stage"] == "enrich_llm"
    assert "model" in failed[-1]["error"].lower()


def test_extract_input_names_from_real_shape():
    inputs = {
        "required": {"text": ["STRING", {}], "clip": ["CLIP", {}]},
        "optional": {"chord": ["FLOAT", {}]},
    }
    assert comfy_import_service._extract_input_names(inputs) == ["text", "clip", "chord"]


def test_extract_input_names_handles_garbage():
    assert comfy_import_service._extract_input_names("nope") == []
    assert comfy_import_service._extract_input_names({}) == []
    assert comfy_import_service._extract_input_names({"required": "wrong"}) == []
