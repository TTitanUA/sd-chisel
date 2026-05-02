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


def _make_session(client) -> str:
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    return client.post(
        f"/api/projects/{pid}/sessions",
        json={"session_type": "i2i", "name": "s", "model_name": None, "use_negative": True},
    ).json()["id"]


def test_first_upload_becomes_main_and_creates_file(client, data_root):
    sid = _make_session(client)

    resp = client.post(
        f"/api/sessions/{sid}/sources",
        files={"file": ("kitten.png", _PNG_1x1, "image/png")},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["is_main"] is True
    assert body["original_filename"] == "kitten.png"
    assert body["analysis"] is None
    assert body["path"].startswith(f"images/{sid}/sources/")
    assert body["path"].endswith(".png")
    assert body["url"] == f"/media/{body['path']}"

    stored = data_root / body["path"]
    assert stored.exists() and stored.read_bytes() == _PNG_1x1


def test_second_upload_is_reference(client):
    sid = _make_session(client)
    client.post(
        f"/api/sessions/{sid}/sources",
        files={"file": ("first.png", _PNG_1x1, "image/png")},
    )
    second = client.post(
        f"/api/sessions/{sid}/sources",
        files={"file": ("second.jpg", _PNG_1x1, "image/jpeg")},
    ).json()
    assert second["is_main"] is False
    assert second["original_filename"] == "second.jpg"

    listing = client.get(f"/api/sessions/{sid}/sources").json()
    assert len(listing) == 2
    assert listing[0]["is_main"] is True
    assert listing[1]["is_main"] is False


def test_set_main_flips_flags(client):
    sid = _make_session(client)
    a = client.post(
        f"/api/sessions/{sid}/sources",
        files={"file": ("a.png", _PNG_1x1, "image/png")},
    ).json()
    b = client.post(
        f"/api/sessions/{sid}/sources",
        files={"file": ("b.png", _PNG_1x1, "image/png")},
    ).json()

    resp = client.patch(f"/api/sessions/{sid}/sources/{b['id']}/main")
    assert resp.status_code == 200
    assert resp.json()["is_main"] is True

    listing = client.get(f"/api/sessions/{sid}/sources").json()
    by_id = {r["id"]: r for r in listing}
    assert by_id[a["id"]]["is_main"] is False
    assert by_id[b["id"]]["is_main"] is True


def test_delete_main_promotes_oldest_remaining(client, data_root):
    sid = _make_session(client)
    a = client.post(
        f"/api/sessions/{sid}/sources",
        files={"file": ("a.png", _PNG_1x1, "image/png")},
    ).json()
    b = client.post(
        f"/api/sessions/{sid}/sources",
        files={"file": ("b.png", _PNG_1x1, "image/png")},
    ).json()
    c = client.post(
        f"/api/sessions/{sid}/sources",
        files={"file": ("c.png", _PNG_1x1, "image/png")},
    ).json()

    file_a = data_root / a["path"]
    assert file_a.exists()

    resp = client.delete(f"/api/sessions/{sid}/sources/{a['id']}")
    assert resp.status_code == 204
    assert not file_a.exists()

    listing = client.get(f"/api/sessions/{sid}/sources").json()
    by_id = {r["id"]: r for r in listing}
    assert by_id[b["id"]]["is_main"] is True
    assert by_id[c["id"]]["is_main"] is False


def test_delete_reference_keeps_main(client):
    sid = _make_session(client)
    a = client.post(
        f"/api/sessions/{sid}/sources",
        files={"file": ("a.png", _PNG_1x1, "image/png")},
    ).json()
    b = client.post(
        f"/api/sessions/{sid}/sources",
        files={"file": ("b.png", _PNG_1x1, "image/png")},
    ).json()
    client.delete(f"/api/sessions/{sid}/sources/{b['id']}")
    listing = client.get(f"/api/sessions/{sid}/sources").json()
    assert len(listing) == 1
    assert listing[0]["id"] == a["id"]
    assert listing[0]["is_main"] is True


def _make_t2i_session(client) -> str:
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    return client.post(
        f"/api/projects/{pid}/sessions",
        json={"session_type": "t2i", "name": "s", "model_name": None, "use_negative": True},
    ).json()["id"]


def test_t2i_uploads_never_become_main(client):
    sid = _make_t2i_session(client)
    a = client.post(
        f"/api/sessions/{sid}/sources",
        files={"file": ("a.png", _PNG_1x1, "image/png")},
    ).json()
    b = client.post(
        f"/api/sessions/{sid}/sources",
        files={"file": ("b.png", _PNG_1x1, "image/png")},
    ).json()
    assert a["is_main"] is False
    assert b["is_main"] is False
    listing = client.get(f"/api/sessions/{sid}/sources").json()
    assert all(row["is_main"] is False for row in listing)


def test_t2i_set_main_returns_409(client):
    sid = _make_t2i_session(client)
    a = client.post(
        f"/api/sessions/{sid}/sources",
        files={"file": ("a.png", _PNG_1x1, "image/png")},
    ).json()
    resp = client.patch(f"/api/sessions/{sid}/sources/{a['id']}/main")
    assert resp.status_code == 409
    assert "t2i" in resp.json()["detail"].lower()
    listing = client.get(f"/api/sessions/{sid}/sources").json()
    assert listing[0]["is_main"] is False


def test_t2i_delete_does_not_promote(client):
    sid = _make_t2i_session(client)
    a = client.post(
        f"/api/sessions/{sid}/sources",
        files={"file": ("a.png", _PNG_1x1, "image/png")},
    ).json()
    b = client.post(
        f"/api/sessions/{sid}/sources",
        files={"file": ("b.png", _PNG_1x1, "image/png")},
    ).json()
    client.delete(f"/api/sessions/{sid}/sources/{a['id']}")
    listing = client.get(f"/api/sessions/{sid}/sources").json()
    assert len(listing) == 1
    assert listing[0]["id"] == b["id"]
    assert listing[0]["is_main"] is False


def test_upload_rejects_unknown_content_type(client):
    sid = _make_session(client)
    resp = client.post(
        f"/api/sessions/{sid}/sources",
        files={"file": ("evil.exe", b"garbage", "application/octet-stream")},
    )
    assert resp.status_code == 422


def test_session_payload_embeds_source_images(client):
    sid = _make_session(client)
    client.post(
        f"/api/sessions/{sid}/sources",
        files={"file": ("a.png", _PNG_1x1, "image/png")},
    )
    body = client.get(f"/api/sessions/{sid}").json()
    assert "source_image_path" not in body
    assert "vl_summary" not in body
    assert len(body["source_images"]) == 1
    assert body["source_images"][0]["is_main"] is True


def test_delete_session_removes_image_dir(client, data_root):
    sid = _make_session(client)
    client.post(
        f"/api/sessions/{sid}/sources",
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
        f"/api/sessions/{s1}/sources",
        files={"file": ("source.png", _PNG_1x1, "image/png")},
    )

    assert client.delete(f"/api/projects/{pid}").status_code == 204
    assert not (data_root / "images" / s1).exists()
    assert not (data_root / "images" / s2).exists()


def test_static_mount_serves_uploaded_file(client, data_root):
    sid = _make_session(client)
    body = client.post(
        f"/api/sessions/{sid}/sources",
        files={"file": ("source.png", _PNG_1x1, "image/png")},
    ).json()
    resp = client.get(f"/media/{body['path']}")
    assert resp.status_code == 200
    assert resp.content == _PNG_1x1
