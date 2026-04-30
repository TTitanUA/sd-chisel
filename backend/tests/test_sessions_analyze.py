from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_conn
from app.main import app
from app.services import lmstudio_client
from app.storage import db as db_mod
from app.storage.migrations import apply_pending

_PNG_1x1 = bytes.fromhex(
    "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C489"
    "0000000A49444154789C6300010000000500010D0A2DB40000000049454E44AE426082"
)


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "data"
    (root / "images").mkdir(parents=True)
    monkeypatch.setattr("app.config.resolve_data_root", lambda *a, **kw: root)
    monkeypatch.setattr("app.storage.images.resolve_data_root", lambda *a, **kw: root)
    monkeypatch.setattr("app.api.sessions.app_config.resolve_data_root", lambda *a, **kw: root)
    return root


@pytest.fixture
def conn(data_root):
    c = db_mod.connect(data_root / "app.db")
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


def _bootstrap(client, monkeypatch, *, vl_model: str | None = "qwen2-vl-7b-instruct") -> str:
    """Set lmstudio config, refresh-with-fake, mark a VL model, attach source."""
    client.put(
        "/api/settings/lmstudio",
        json={"base_url": "http://h", "api_key": None},
    )
    monkeypatch.setattr(
        lmstudio_client, "list_models",
        lambda **_: [
            lmstudio_client.LmsModel(name="qwen2-vl-7b-instruct", vision=True, tool_use=False, reasoning=False),
            lmstudio_client.LmsModel(name="mistral-nemo-12b", vision=False, tool_use=False, reasoning=False),
        ],
    )
    client.post("/api/settings/lmstudio/refresh")
    client.patch(
        "/api/settings/lmstudio/models/qwen2-vl-7b-instruct",
        json={"vision": True, "enabled": True},
    )

    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    sid = client.post(
        f"/api/projects/{pid}/sessions",
        json={"name": "s", "model_name": None, "use_negative": True},
    ).json()["id"]
    client.patch(
        f"/api/sessions/{sid}",
        json={
            "name": "s",
            "model_name": None,
            "use_negative": True,
            "pinned_loras": [],
            "vl_model_name": vl_model,
            "prompt_model_name": None,
        },
    )
    client.post(
        f"/api/sessions/{sid}/source",
        files={"file": ("source.png", _PNG_1x1, "image/png")},
    )
    return sid


def test_analyze_returns_summary_and_persists(client, monkeypatch):
    captured: dict[str, Any] = {}

    def fake_analyze(**kwargs):
        captured.update(kwargs)
        return "moody portrait, soft rim light"

    sid = _bootstrap(client, monkeypatch)
    monkeypatch.setattr(lmstudio_client, "analyze_image", fake_analyze)

    resp = client.post(f"/api/sessions/{sid}/analyze-source")
    assert resp.status_code == 200
    assert resp.json()["vl_summary"] == "moody portrait, soft rim light"

    assert captured["model"] == "qwen2-vl-7b-instruct"
    assert captured["content_type"] == "image/png"
    assert captured["image_bytes"] == _PNG_1x1
    assert captured["endpoint"] == {"server_root": "http://h", "api_key": None}

    again = client.get(f"/api/sessions/{sid}").json()
    assert again["vl_summary"] == "moody portrait, soft rim light"


def test_analyze_404_when_session_missing(client):
    assert client.post("/api/sessions/missing/analyze-source").status_code == 404


def test_analyze_409_when_no_lmstudio_config(client, monkeypatch):
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    sid = client.post(
        f"/api/projects/{pid}/sessions",
        json={"name": "s", "model_name": None, "use_negative": True},
    ).json()["id"]
    client.post(
        f"/api/sessions/{sid}/source",
        files={"file": ("source.png", _PNG_1x1, "image/png")},
    )

    resp = client.post(f"/api/sessions/{sid}/analyze-source")
    assert resp.status_code == 409
    assert "lmstudio" in resp.json()["detail"].lower() or "base_url" in resp.json()["detail"].lower()


def test_analyze_409_when_no_source_image(client, monkeypatch):
    client.put("/api/settings/lmstudio", json={"base_url": "http://h/v1", "api_key": None})
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    sid = client.post(
        f"/api/projects/{pid}/sessions",
        json={"name": "s", "model_name": None, "use_negative": True},
    ).json()["id"]
    resp = client.post(f"/api/sessions/{sid}/analyze-source")
    assert resp.status_code == 409
    assert "source" in resp.json()["detail"].lower()


def test_analyze_409_when_no_vl_model_on_session(client, monkeypatch):
    sid = _bootstrap(client, monkeypatch, vl_model=None)
    resp = client.post(f"/api/sessions/{sid}/analyze-source")
    assert resp.status_code == 409
    assert "vl_model" in resp.json()["detail"]


def test_analyze_409_when_vl_model_disabled(client, monkeypatch):
    sid = _bootstrap(client, monkeypatch)
    client.patch(
        "/api/settings/lmstudio/models/qwen2-vl-7b-instruct",
        json={"enabled": False},
    )
    resp = client.post(f"/api/sessions/{sid}/analyze-source")
    assert resp.status_code == 409


def test_analyze_409_when_vl_model_has_no_vision_capability(client, monkeypatch):
    sid = _bootstrap(client, monkeypatch)
    client.patch(
        "/api/settings/lmstudio/models/qwen2-vl-7b-instruct",
        json={"vision": False},
    )
    resp = client.post(f"/api/sessions/{sid}/analyze-source")
    assert resp.status_code == 409


def test_analyze_502_on_upstream_error(client, monkeypatch):
    sid = _bootstrap(client, monkeypatch)

    def fake(**_): raise lmstudio_client.LmError("upstream", "boom")
    monkeypatch.setattr(lmstudio_client, "analyze_image", fake)

    assert client.post(f"/api/sessions/{sid}/analyze-source").status_code == 502


def test_analyze_504_on_timeout(client, monkeypatch):
    sid = _bootstrap(client, monkeypatch)

    def fake(**_): raise lmstudio_client.LmError("timeout", "slow")
    monkeypatch.setattr(lmstudio_client, "analyze_image", fake)

    assert client.post(f"/api/sessions/{sid}/analyze-source").status_code == 504


def test_analyze_failure_does_not_overwrite_existing_summary(client, monkeypatch):
    sid = _bootstrap(client, monkeypatch)
    monkeypatch.setattr(lmstudio_client, "analyze_image", lambda **_: "first summary")
    assert client.post(f"/api/sessions/{sid}/analyze-source").status_code == 200

    def fake_fail(**_): raise lmstudio_client.LmError("upstream", "boom")
    monkeypatch.setattr(lmstudio_client, "analyze_image", fake_fail)

    assert client.post(f"/api/sessions/{sid}/analyze-source").status_code == 502
    assert client.get(f"/api/sessions/{sid}").json()["vl_summary"] == "first summary"
