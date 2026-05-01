from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_conn
from app.main import app
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


def _make_session(client) -> str:
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    return client.post(
        f"/api/projects/{pid}/sessions",
        json={"session_type": "i2i", "name": "s", "model_name": None, "use_negative": True},
    ).json()["id"]


def test_upload_source_writes_file_and_updates_session(client, data_root):
    sid = _make_session(client)

    resp = client.post(
        f"/api/sessions/{sid}/source",
        files={"file": ("source.png", _PNG_1x1, "image/png")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["source_image_path"] == f"images/{sid}/source.png"
    assert body["source_image_url"] == f"/media/images/{sid}/source.png"

    stored = data_root / "images" / sid / "source.png"
    assert stored.exists() and stored.read_bytes() == _PNG_1x1


def test_reupload_replaces_previous_extension(client, data_root):
    sid = _make_session(client)
    client.post(
        f"/api/sessions/{sid}/source",
        files={"file": ("source.png", _PNG_1x1, "image/png")},
    )
    resp = client.post(
        f"/api/sessions/{sid}/source",
        files={"file": ("source.jpg", _PNG_1x1, "image/jpeg")},
    )
    assert resp.status_code == 200
    assert resp.json()["source_image_path"].endswith("source.jpg")
    d = data_root / "images" / sid
    assert {p.name for p in d.iterdir()} == {"source.jpg"}


def test_upload_rejects_unknown_content_type(client):
    sid = _make_session(client)
    resp = client.post(
        f"/api/sessions/{sid}/source",
        files={"file": ("evil.exe", b"garbage", "application/octet-stream")},
    )
    assert resp.status_code == 422


def test_clear_source(client, data_root):
    sid = _make_session(client)
    client.post(
        f"/api/sessions/{sid}/source",
        files={"file": ("source.png", _PNG_1x1, "image/png")},
    )
    d = data_root / "images" / sid

    resp = client.delete(f"/api/sessions/{sid}/source")
    assert resp.status_code == 200
    assert resp.json()["source_image_path"] is None
    assert not any(d.glob("source.*"))


def test_delete_session_removes_image_dir(client, data_root):
    sid = _make_session(client)
    client.post(
        f"/api/sessions/{sid}/source",
        files={"file": ("source.png", _PNG_1x1, "image/png")},
    )
    d = data_root / "images" / sid
    assert d.exists()

    resp = client.delete(f"/api/sessions/{sid}")
    assert resp.status_code == 204
    assert not d.exists()


def test_delete_project_cleans_all_session_dirs(client, data_root):
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    s1 = client.post(
        f"/api/projects/{pid}/sessions",
        json={"session_type": "i2i", "name": "a", "model_name": None, "use_negative": True},
    ).json()["id"]
    s2 = client.post(
        f"/api/projects/{pid}/sessions",
        json={"session_type": "i2i", "name": "b", "model_name": None, "use_negative": True},
    ).json()["id"]
    client.post(
        f"/api/sessions/{s1}/source",
        files={"file": ("source.png", _PNG_1x1, "image/png")},
    )

    assert client.delete(f"/api/projects/{pid}").status_code == 204
    assert not (data_root / "images" / s1).exists()
    assert not (data_root / "images" / s2).exists()


def test_static_mount_serves_uploaded_file(client, data_root):
    sid = _make_session(client)
    client.post(
        f"/api/sessions/{sid}/source",
        files={"file": ("source.png", _PNG_1x1, "image/png")},
    )
    resp = client.get(f"/media/images/{sid}/source.png")
    assert resp.status_code == 200
    assert resp.content == _PNG_1x1
