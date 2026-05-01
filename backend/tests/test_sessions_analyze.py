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


def _bootstrap(client, monkeypatch, *, vl_model: str | None = "qwen2-vl-7b-instruct") -> tuple[str, str]:
    """Set lmstudio config, refresh-with-fake, mark a VL model, attach source.
    Returns (session_id, image_id)."""
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
        json={"session_type": "i2i", "name": "s", "model_name": None, "use_negative": True},
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
    img = client.post(
        f"/api/sessions/{sid}/sources",
        files={"file": ("source.png", _PNG_1x1, "image/png")},
    ).json()
    return sid, img["id"]


def _analyze(client, sid: str, image_id: str, refining_prompt: str | None = None):
    return client.post(
        f"/api/sessions/{sid}/sources/{image_id}/analyze",
        json={"refining_prompt": refining_prompt},
    )


def test_analyze_returns_summary_and_persists(client, monkeypatch):
    captured: dict[str, Any] = {}

    def fake_analyze(**kwargs):
        captured.update(kwargs)
        return "moody portrait, soft rim light"

    sid, image_id = _bootstrap(client, monkeypatch)
    monkeypatch.setattr(lmstudio_client, "analyze_image", fake_analyze)

    resp = _analyze(client, sid, image_id)
    assert resp.status_code == 200
    body = resp.json()
    assert body["analysis"] == "moody portrait, soft rim light"
    assert body["analysis_prompt"] is None
    assert body["is_main"] is True

    assert captured["model"] == "qwen2-vl-7b-instruct"
    assert captured["content_type"] == "image/png"
    assert captured["image_bytes"] == _PNG_1x1
    assert captured["endpoint"] == {"server_root": "http://h", "api_key": None}
    assert captured["refining_prompt"] is None

    again = client.get(f"/api/sessions/{sid}/sources").json()
    assert again[0]["analysis"] == "moody portrait, soft rim light"


def test_analyze_forwards_refining_prompt(client, monkeypatch):
    captured: dict[str, Any] = {}

    def fake_analyze(**kwargs):
        captured.update(kwargs)
        return "with detail"

    sid, image_id = _bootstrap(client, monkeypatch)
    monkeypatch.setattr(lmstudio_client, "analyze_image", fake_analyze)

    resp = _analyze(client, sid, image_id, refining_prompt="focus on the cat")
    assert resp.status_code == 200
    body = resp.json()
    assert body["analysis_prompt"] == "focus on the cat"
    assert captured["refining_prompt"] == "focus on the cat"


def test_reanalyze_overwrites_previous(client, monkeypatch):
    sid, image_id = _bootstrap(client, monkeypatch)
    monkeypatch.setattr(lmstudio_client, "analyze_image", lambda **_: "first")
    assert _analyze(client, sid, image_id).status_code == 200
    monkeypatch.setattr(lmstudio_client, "analyze_image", lambda **_: "second")
    body = _analyze(client, sid, image_id, refining_prompt="redo").json()
    assert body["analysis"] == "second"
    assert body["analysis_prompt"] == "redo"


def test_analyze_404_when_session_missing(client):
    assert client.post(
        "/api/sessions/missing/sources/abc/analyze", json={"refining_prompt": None},
    ).status_code == 404


def test_analyze_404_when_image_belongs_to_other_session(client, monkeypatch):
    sid, _ = _bootstrap(client, monkeypatch)
    other_pid = client.post("/api/projects", json={"name": "Q"}).json()["id"]
    other_sid = client.post(
        f"/api/projects/{other_pid}/sessions",
        json={"session_type": "i2i", "name": "x", "model_name": None, "use_negative": True},
    ).json()["id"]
    other_img = client.post(
        f"/api/sessions/{other_sid}/sources",
        files={"file": ("x.png", _PNG_1x1, "image/png")},
    ).json()
    resp = client.post(
        f"/api/sessions/{sid}/sources/{other_img['id']}/analyze",
        json={"refining_prompt": None},
    )
    assert resp.status_code == 404


def test_analyze_409_when_no_lmstudio_config(client, monkeypatch):
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    sid = client.post(
        f"/api/projects/{pid}/sessions",
        json={"session_type": "i2i", "name": "s", "model_name": None, "use_negative": True},
    ).json()["id"]
    img = client.post(
        f"/api/sessions/{sid}/sources",
        files={"file": ("source.png", _PNG_1x1, "image/png")},
    ).json()

    resp = _analyze(client, sid, img["id"])
    assert resp.status_code == 409
    assert "lmstudio" in resp.json()["detail"].lower() or "base_url" in resp.json()["detail"].lower()


def test_analyze_409_when_no_vl_model_on_session(client, monkeypatch):
    sid, image_id = _bootstrap(client, monkeypatch, vl_model=None)
    resp = _analyze(client, sid, image_id)
    assert resp.status_code == 409
    assert "vl_model" in resp.json()["detail"]


def test_analyze_409_when_vl_model_disabled(client, monkeypatch):
    sid, image_id = _bootstrap(client, monkeypatch)
    client.patch(
        "/api/settings/lmstudio/models/qwen2-vl-7b-instruct",
        json={"enabled": False},
    )
    resp = _analyze(client, sid, image_id)
    assert resp.status_code == 409


def test_analyze_409_when_vl_model_has_no_vision_capability(client, monkeypatch):
    sid, image_id = _bootstrap(client, monkeypatch)
    client.patch(
        "/api/settings/lmstudio/models/qwen2-vl-7b-instruct",
        json={"vision": False},
    )
    resp = _analyze(client, sid, image_id)
    assert resp.status_code == 409


def test_analyze_502_on_upstream_error(client, monkeypatch):
    sid, image_id = _bootstrap(client, monkeypatch)

    def fake(**_): raise lmstudio_client.LmError("upstream", "boom")
    monkeypatch.setattr(lmstudio_client, "analyze_image", fake)

    assert _analyze(client, sid, image_id).status_code == 502


def test_analyze_504_on_timeout(client, monkeypatch):
    sid, image_id = _bootstrap(client, monkeypatch)

    def fake(**_): raise lmstudio_client.LmError("timeout", "slow")
    monkeypatch.setattr(lmstudio_client, "analyze_image", fake)

    assert _analyze(client, sid, image_id).status_code == 504


def test_analyze_failure_does_not_overwrite_existing_summary(client, monkeypatch):
    sid, image_id = _bootstrap(client, monkeypatch)
    monkeypatch.setattr(lmstudio_client, "analyze_image", lambda **_: "first summary")
    assert _analyze(client, sid, image_id).status_code == 200

    def fake_fail(**_): raise lmstudio_client.LmError("upstream", "boom")
    monkeypatch.setattr(lmstudio_client, "analyze_image", fake_fail)

    assert _analyze(client, sid, image_id).status_code == 502
    after = client.get(f"/api/sessions/{sid}/sources").json()
    assert after[0]["analysis"] == "first summary"
