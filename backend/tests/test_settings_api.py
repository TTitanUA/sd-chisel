from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_conn
from app.main import app
from app.services import lmstudio_client
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
