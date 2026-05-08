from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_conn
from app.main import app
from app.services import comfy_client, lmstudio_client
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


def test_get_lmstudio_returns_blank_by_default(client):
    body = client.get("/api/settings/lmstudio").json()
    assert body == {
        "base_url": None,
        "api_key": None,
        "configured": False,
        "updated_at": body["updated_at"],
    }


def test_put_lmstudio_persists(client):
    resp = client.put(
        "/api/settings/lmstudio",
        json={"base_url": "http://localhost:1234/", "api_key": "k"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["base_url"] == "http://localhost:1234"  # trailing slash stripped
    assert body["configured"] is True

    again = client.get("/api/settings/lmstudio").json()
    assert again["base_url"] == "http://localhost:1234"


def test_refresh_409_when_unconfigured(client):
    assert client.post("/api/settings/lmstudio/refresh").status_code == 409


def _fake_model(name: str, vision=False, tool_use=False, reasoning=False):
    return lmstudio_client.LmsModel(
        name=name, vision=vision, tool_use=tool_use, reasoning=reasoning,
    )


def test_refresh_populates_models(client, monkeypatch):
    client.put("/api/settings/lmstudio", json={"base_url": "http://h", "api_key": None})

    captured: dict[str, Any] = {}

    def fake_list(*, endpoint, transport=None):
        captured["endpoint"] = endpoint
        return [
            _fake_model("qwen-vl", vision=True),
            _fake_model("mistral", tool_use=True, reasoning=True),
        ]

    monkeypatch.setattr(lmstudio_client, "list_models", fake_list)

    body = client.post("/api/settings/lmstudio/refresh").json()
    by_name = {m["name"]: m for m in body["models"]}
    assert by_name["qwen-vl"]["vision"] is True
    assert by_name["qwen-vl"]["tool_use"] is False
    assert by_name["qwen-vl"]["enabled"] is True
    assert by_name["mistral"]["tool_use"] is True
    assert by_name["mistral"]["reasoning"] is True
    assert captured["endpoint"] == {"server_root": "http://h", "api_key": None}


def test_refresh_502_on_upstream_error(client, monkeypatch):
    client.put("/api/settings/lmstudio", json={"base_url": "http://h", "api_key": None})

    def fake(*, endpoint, transport=None):
        raise lmstudio_client.LmError("upstream", "503: busy")

    monkeypatch.setattr(lmstudio_client, "list_models", fake)
    assert client.post("/api/settings/lmstudio/refresh").status_code == 502


def test_refresh_504_on_timeout(client, monkeypatch):
    client.put("/api/settings/lmstudio", json={"base_url": "http://h", "api_key": None})

    def fake(*, endpoint, transport=None):
        raise lmstudio_client.LmError("timeout", "ConnectTimeout")

    monkeypatch.setattr(lmstudio_client, "list_models", fake)
    assert client.post("/api/settings/lmstudio/refresh").status_code == 504


def test_patch_lm_model_capabilities(client, monkeypatch):
    client.put("/api/settings/lmstudio", json={"base_url": "http://h", "api_key": None})
    monkeypatch.setattr(lmstudio_client, "list_models", lambda **_: [_fake_model("m", vision=True)])
    client.post("/api/settings/lmstudio/refresh")

    resp = client.patch(
        "/api/settings/lmstudio/models/m",
        json={"vision": False, "enabled": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["vision"] is False
    assert body["enabled"] is False
    assert body["tool_use"] is False


def test_patch_lm_model_accepts_encoded_slash_in_name(client, monkeypatch):
    name = "google/gemma-4-26b-a4b"
    client.put("/api/settings/lmstudio", json={"base_url": "http://h", "api_key": None})
    monkeypatch.setattr(lmstudio_client, "list_models", lambda **_: [_fake_model(name)])
    client.post("/api/settings/lmstudio/refresh")

    resp = client.patch(
        "/api/settings/lmstudio/models/google%2Fgemma-4-26b-a4b",
        json={"favorite": True},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == name
    assert body["favorite"] is True


def test_patch_lm_model_404_for_unknown(client):
    resp = client.patch("/api/settings/lmstudio/models/ghost", json={"enabled": False})
    assert resp.status_code == 404


def test_unload_all_409_when_unconfigured(client):
    assert client.post("/api/settings/lmstudio/unload-all").status_code == 409


def test_unload_all_unloads_each_loaded_instance(client, monkeypatch):
    client.put("/api/settings/lmstudio", json={"base_url": "http://h", "api_key": None})

    monkeypatch.setattr(
        lmstudio_client, "list_loaded_instance_ids", lambda **_: ["inst-a", "inst-b"],
    )

    unloaded: list[str] = []

    def fake_unload(*, endpoint, instance_id, transport=None):
        unloaded.append(instance_id)

    monkeypatch.setattr(lmstudio_client, "unload_model", fake_unload)

    body = client.post("/api/settings/lmstudio/unload-all").json()
    assert body == {"unloaded": 2}
    assert unloaded == ["inst-a", "inst-b"]


def test_unload_all_502_on_upstream_error(client, monkeypatch):
    client.put("/api/settings/lmstudio", json={"base_url": "http://h", "api_key": None})

    def fake(**_):
        raise lmstudio_client.LmError("upstream", "503: busy")

    monkeypatch.setattr(lmstudio_client, "list_loaded_instance_ids", fake)
    assert client.post("/api/settings/lmstudio/unload-all").status_code == 502


def test_refresh_updates_capabilities_preserves_enabled(client, monkeypatch):
    client.put("/api/settings/lmstudio", json={"base_url": "http://h", "api_key": None})
    monkeypatch.setattr(lmstudio_client, "list_models", lambda **_: [_fake_model("m")])
    client.post("/api/settings/lmstudio/refresh")
    client.patch("/api/settings/lmstudio/models/m", json={"enabled": False})

    monkeypatch.setattr(
        lmstudio_client, "list_models", lambda **_: [_fake_model("m", vision=True)],
    )
    body = client.post("/api/settings/lmstudio/refresh").json()
    [m] = body["models"]
    assert m["vision"] is True   # updated from API
    assert m["enabled"] is False  # preserved


# --- action defaults ---

def test_get_action_defaults_returns_empty_bundles_initially(client):
    """Session-scoped actions ship without baked defaults; comfy_import
    carries a builtin baseline so the import wizard runs end-to-end on
    a fresh install."""
    body = client.get("/api/settings/action-defaults").json()
    assert body["analyze"] == {}
    assert body["chat"] == {}
    assert body["summarize"] == {}
    assert body["generate"] == {}
    # comfy_import — sane baseline that survives reasoning models that
    # otherwise eat the entire token budget on <think> blocks.
    assert body["comfy_import"]["temperature"] == 0.1
    assert body["comfy_import"]["max_tokens"] == 6000


def test_user_override_replaces_builtin_for_comfy_import(client):
    res = client.put(
        "/api/settings/action-defaults",
        json={"comfy_import": {"temperature": 0.5, "max_tokens": 4000}},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["comfy_import"] == {"temperature": 0.5, "max_tokens": 4000}


def test_clearing_comfy_import_falls_back_to_builtin(client):
    client.put(
        "/api/settings/action-defaults",
        json={"comfy_import": {"temperature": 0.5}},
    )
    cleared = client.put(
        "/api/settings/action-defaults",
        json={"comfy_import": {}},
    ).json()
    # Cleared overrides resolve to the builtin baseline rather than
    # leaving the action with nothing.
    assert cleared["comfy_import"]["temperature"] == 0.1
    assert cleared["comfy_import"]["max_tokens"] == 6000


def test_put_action_defaults_persists_partial_update(client):
    res = client.put(
        "/api/settings/action-defaults",
        json={"chat": {"temperature": 0.9, "top_p": 0.85}},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["chat"] == {"temperature": 0.9, "top_p": 0.85}
    # Untouched session-scoped actions stay empty; the global
    # comfy_import action retains its builtin baseline.
    assert body["analyze"] == {}
    assert body["summarize"] == {}
    assert body["generate"] == {}
    assert body["comfy_import"]["max_tokens"] == 6000

    # GET reflects the same state.
    again = client.get("/api/settings/action-defaults").json()
    assert again == body


def test_put_action_defaults_clears_with_empty_object(client):
    client.put("/api/settings/action-defaults", json={"chat": {"temperature": 0.5}})
    res = client.put("/api/settings/action-defaults", json={"chat": {}})
    assert res.status_code == 200
    assert res.json()["chat"] == {}


def test_put_action_defaults_rejects_unknown_key(client):
    res = client.put(
        "/api/settings/action-defaults",
        json={"chat": {"foobar": 1}},
    )
    assert res.status_code == 400
    assert "foobar" in res.json()["detail"]


def test_put_action_defaults_rejects_out_of_range(client):
    res = client.put(
        "/api/settings/action-defaults",
        json={"chat": {"temperature": 5.0}},
    )
    assert res.status_code == 400
    assert "temperature" in res.json()["detail"]


# --- ComfyUI settings ---

def test_get_comfyui_returns_blank_by_default(client):
    body = client.get("/api/settings/comfyui").json()
    assert body == {
        "base_url": None,
        "install_path": None,
        "api_key": None,
        "input_dir": None,
        "output_dir": None,
        "effective_input_dir": None,
        "effective_output_dir": None,
        "configured": False,
        "updated_at": body["updated_at"],
    }


def test_put_comfyui_persists_and_normalises_url(client, tmp_path):
    install = tmp_path / "ComfyUI"
    (install / "custom_nodes").mkdir(parents=True)
    resp = client.put(
        "/api/settings/comfyui",
        json={
            "base_url": "http://127.0.0.1:8188/",
            "install_path": str(install),
            "api_key": "secret",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["base_url"] == "http://127.0.0.1:8188"  # trailing slash stripped
    assert body["install_path"] == str(install)
    assert body["api_key"] == "secret"
    assert body["configured"] is True

    again = client.get("/api/settings/comfyui").json()
    assert again["base_url"] == "http://127.0.0.1:8188"
    assert again["install_path"] == str(install)


def test_put_comfyui_configured_requires_both_fields(client):
    body = client.put(
        "/api/settings/comfyui",
        json={"base_url": "http://h", "install_path": None, "api_key": None},
    ).json()
    assert body["configured"] is False  # path missing


def test_comfyui_input_output_dir_default_to_install_path(client, tmp_path):
    install = tmp_path / "ComfyUI"
    (install / "custom_nodes").mkdir(parents=True)
    resp = client.put(
        "/api/settings/comfyui",
        json={
            "base_url": "http://h",
            "install_path": str(install),
            "api_key": None,
        },
    ).json()
    # Effective dirs derive from install path when no override is set.
    assert resp["input_dir"] is None
    assert resp["output_dir"] is None
    assert resp["effective_input_dir"] == str(install / "input")
    assert resp["effective_output_dir"] == str(install / "output")


def test_comfyui_input_output_dir_override(client, tmp_path):
    install = tmp_path / "ComfyUI"
    (install / "custom_nodes").mkdir(parents=True)
    custom_in = tmp_path / "custom-in"
    custom_out = tmp_path / "custom-out"
    resp = client.put(
        "/api/settings/comfyui",
        json={
            "base_url": "http://h",
            "install_path": str(install),
            "api_key": None,
            "input_dir": str(custom_in),
            "output_dir": str(custom_out),
        },
    ).json()
    assert resp["input_dir"] == str(custom_in)
    assert resp["output_dir"] == str(custom_out)
    assert resp["effective_input_dir"] == str(custom_in)
    assert resp["effective_output_dir"] == str(custom_out)

    # Round-trip on GET.
    again = client.get("/api/settings/comfyui").json()
    assert again["effective_input_dir"] == str(custom_in)
    assert again["effective_output_dir"] == str(custom_out)


def test_comfyui_no_install_path_no_effective_dirs(client):
    body = client.get("/api/settings/comfyui").json()
    assert body["effective_input_dir"] is None
    assert body["effective_output_dir"] is None


def test_check_comfyui_reports_per_field_results(client, tmp_path, monkeypatch):
    install = tmp_path / "ComfyUI"
    (install / "custom_nodes").mkdir(parents=True)
    (install / "custom_nodes" / "rgthree-comfy").mkdir()
    (install / "custom_nodes" / ".disabled").mkdir()  # ignored prefix
    (install / "custom_nodes" / "__pycache__").mkdir()  # ignored prefix
    (install / "custom_nodes" / "stub.py").write_text("# loose file")  # not a dir

    client.put(
        "/api/settings/comfyui",
        json={
            "base_url": "http://h",
            "install_path": str(install),
            "api_key": None,
        },
    )

    captured: dict[str, Any] = {}

    def fake_stats(*, endpoint, transport=None):
        captured["endpoint"] = endpoint
        return comfy_client.ComfySystemStats(
            comfyui_version="1.4.2", python_version="3.11.7", os="nt",
        )

    monkeypatch.setattr(comfy_client, "system_stats", fake_stats)

    body = client.post("/api/settings/comfyui/check").json()
    assert body["url"]["ok"] is True
    assert body["url"]["info"]["comfyui_version"] == "1.4.2"
    assert body["install_path"]["ok"] is True
    assert body["install_path"]["info"]["pack_count"] == 1
    assert captured["endpoint"] == {"server_root": "http://h", "api_key": None}


def test_check_comfyui_reports_url_failure(client, tmp_path, monkeypatch):
    install = tmp_path / "ComfyUI"
    (install / "custom_nodes").mkdir(parents=True)
    client.put(
        "/api/settings/comfyui",
        json={"base_url": "http://h", "install_path": str(install), "api_key": None},
    )

    def fake(*, endpoint, transport=None):
        raise comfy_client.ComfyError("upstream", "503: busy")

    monkeypatch.setattr(comfy_client, "system_stats", fake)
    body = client.post("/api/settings/comfyui/check").json()
    assert body["url"]["ok"] is False
    assert "503" in body["url"]["detail"]
    assert body["install_path"]["ok"] is True


def test_check_comfyui_reports_path_failure(client, tmp_path, monkeypatch):
    # Path exists but lacks a custom_nodes/ subdir.
    install = tmp_path / "wrongdir"
    install.mkdir()
    client.put(
        "/api/settings/comfyui",
        json={"base_url": "http://h", "install_path": str(install), "api_key": None},
    )
    monkeypatch.setattr(
        comfy_client, "system_stats",
        lambda **_: comfy_client.ComfySystemStats(
            comfyui_version="x", python_version="y", os="z",
        ),
    )
    body = client.post("/api/settings/comfyui/check").json()
    assert body["install_path"]["ok"] is False
    assert "custom_nodes" in body["install_path"]["detail"]


def test_check_comfyui_reports_unset_fields(client):
    # No PUT first — both fields blank.
    body = client.post("/api/settings/comfyui/check").json()
    assert body["url"]["ok"] is False
    assert body["url"]["detail"] == "URL is not set"
    assert body["install_path"]["ok"] is False
    assert body["install_path"]["detail"] == "Path is not set"
