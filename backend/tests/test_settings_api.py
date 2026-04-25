from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_conn
from app.main import app
from app.services import lm_client
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
        json={"base_url": "http://localhost:1234/v1/", "api_key": "lm-studio"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["base_url"] == "http://localhost:1234/v1"  # trailing slash stripped
    assert body["configured"] is True

    again = client.get("/api/settings/lmstudio").json()
    assert again["base_url"] == "http://localhost:1234/v1"


def test_refresh_409_when_unconfigured(client):
    assert client.post("/api/settings/lmstudio/refresh").status_code == 409


def test_refresh_populates_models(client, monkeypatch):
    client.put("/api/settings/lmstudio", json={"base_url": "http://h/v1", "api_key": None})

    captured: dict[str, Any] = {}

    def fake_list(*, endpoint, transport=None):
        captured["endpoint"] = endpoint
        return ["mistral-nemo-12b", "qwen2-vl-7b-instruct"]

    monkeypatch.setattr(lm_client, "list_models", fake_list)

    body = client.post("/api/settings/lmstudio/refresh").json()
    assert {m["name"] for m in body["models"]} == {
        "mistral-nemo-12b", "qwen2-vl-7b-instruct",
    }
    for m in body["models"]:
        assert m["role"] == "both"
        assert m["enabled"] is True
    assert captured["endpoint"] == {"base_url": "http://h/v1", "api_key": None}


def test_refresh_502_when_lm_client_upstream(client, monkeypatch):
    client.put("/api/settings/lmstudio", json={"base_url": "http://h/v1", "api_key": None})

    def fake(*, endpoint, transport=None):
        raise lm_client.LmError("upstream", "503: busy")
    monkeypatch.setattr(lm_client, "list_models", fake)

    assert client.post("/api/settings/lmstudio/refresh").status_code == 502


def test_refresh_504_on_timeout(client, monkeypatch):
    client.put("/api/settings/lmstudio", json={"base_url": "http://h/v1", "api_key": None})

    def fake(*, endpoint, transport=None):
        raise lm_client.LmError("timeout", "ConnectTimeout")
    monkeypatch.setattr(lm_client, "list_models", fake)

    assert client.post("/api/settings/lmstudio/refresh").status_code == 504


def test_patch_lm_model_role_and_enabled(client, monkeypatch):
    client.put("/api/settings/lmstudio", json={"base_url": "http://h/v1", "api_key": None})
    monkeypatch.setattr(lm_client, "list_models", lambda **_: ["qwen2-vl-7b-instruct"])
    client.post("/api/settings/lmstudio/refresh")

    resp = client.patch(
        "/api/settings/lmstudio/models/qwen2-vl-7b-instruct",
        json={"role": "vl", "enabled": False},
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "name": "qwen2-vl-7b-instruct",
        "role": "vl",
        "enabled": False,
        "last_seen": resp.json()["last_seen"],
    }


def test_patch_lm_model_404_for_unknown(client):
    resp = client.patch(
        "/api/settings/lmstudio/models/ghost", json={"enabled": False},
    )
    assert resp.status_code == 404


def test_refresh_does_not_clobber_user_flags(client, monkeypatch):
    client.put("/api/settings/lmstudio", json={"base_url": "http://h/v1", "api_key": None})
    monkeypatch.setattr(lm_client, "list_models", lambda **_: ["m"])
    client.post("/api/settings/lmstudio/refresh")
    client.patch("/api/settings/lmstudio/models/m", json={"role": "prompt", "enabled": False})

    body = client.post("/api/settings/lmstudio/refresh").json()
    [m] = body["models"]
    assert m["role"] == "prompt"
    assert m["enabled"] is False
