"""Tests for /api/comfy/sessions/{id}/source_slots — the
server-side replacement for the localStorage SourceSlot table.

Covers CRUD, the unique-key constraint, the explicit-id migration
path, the description / image-id null-clear semantics, and
session-scope isolation (slots from session A never leak into
session B's listing).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_conn
from app.main import app
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


def _make_session(client, *, name: str = "S", session_type: str = "comfy") -> dict:
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    payload: dict = {
        "session_type": session_type, "name": name,
        "model_name": None, "use_negative": True,
    }
    if session_type in ("comfy", "comfy_mock"):
        # Workflow name + graph have to be unique across the test
        # process; keep the inputs map distinct per session so the
        # graph hash differs.
        graph = {"1": {"class_type": "X", "inputs": {"name": name}}}
        wf = client.post(
            "/api/comfy/workflows", json={"name": name + "-wf", "graph": graph},
        ).json()
        payload["comfy_workflow_id"] = wf["id"]
    return client.post(f"/api/projects/{pid}/sessions", json=payload).json()


def _upload_image(client, session_id: str) -> dict:
    files = {"file": ("test.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 16, "image/png")}
    return client.post(
        f"/api/sessions/{session_id}/sources", files=files,
    ).json()


# --- list / create -----------------------------------------------------


def test_list_slots_empty_for_new_session(client):
    s = _make_session(client)
    body = client.get(f"/api/comfy/sessions/{s['id']}/source_slots").json()
    assert body == {"slots": []}


def test_list_404_when_session_missing(client):
    resp = client.get("/api/comfy/sessions/nope/source_slots")
    assert resp.status_code == 404


def test_list_409_on_non_comfy_session(client):
    s = _make_session(client, session_type="i2i")
    resp = client.get(f"/api/comfy/sessions/{s['id']}/source_slots")
    assert resp.status_code == 409


def test_create_slot_minimal(client):
    s = _make_session(client)
    resp = client.post(
        f"/api/comfy/sessions/{s['id']}/source_slots",
        json={"key": "Image 1"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["key"] == "Image 1"
    assert body["purpose"] == "main"
    assert body["description"] is None
    assert body["source_image_id"] is None
    assert body["position"] == 0


def test_create_slot_with_full_payload(client):
    s = _make_session(client)
    img = _upload_image(client, s["id"])
    resp = client.post(
        f"/api/comfy/sessions/{s['id']}/source_slots",
        json={
            "key": "Background",
            "purpose": "ref_in_scene",
            "description": "Distant mountains, soft mist.",
            "source_image_id": img["id"],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["purpose"] == "ref_in_scene"
    assert body["description"] == "Distant mountains, soft mist."
    assert body["source_image_id"] == img["id"]


def test_create_slot_409_on_duplicate_key(client):
    s = _make_session(client)
    client.post(
        f"/api/comfy/sessions/{s['id']}/source_slots",
        json={"key": "Image 1"},
    )
    resp = client.post(
        f"/api/comfy/sessions/{s['id']}/source_slots",
        json={"key": "Image 1"},
    )
    assert resp.status_code == 409
    assert "already used" in resp.json()["detail"]


def test_create_slot_409_when_image_belongs_to_other_session(client):
    s1 = _make_session(client)
    s2 = _make_session(client, name="S2")
    img = _upload_image(client, s1["id"])
    resp = client.post(
        f"/api/comfy/sessions/{s2['id']}/source_slots",
        json={"key": "Image 1", "source_image_id": img["id"]},
    )
    assert resp.status_code == 409


def test_create_slot_with_explicit_id_for_migration(client):
    """The migration shim posts existing localStorage ids so workflow
    / agent references that point at them keep resolving."""
    s = _make_session(client)
    resp = client.post(
        f"/api/comfy/sessions/{s['id']}/source_slots",
        json={"id": "abcdef0123456789", "key": "Migrated"},
    )
    assert resp.status_code == 201
    assert resp.json()["id"] == "abcdef0123456789"


def test_list_returns_slots_in_position_order(client):
    s = _make_session(client)
    for i in range(3):
        client.post(
            f"/api/comfy/sessions/{s['id']}/source_slots",
            json={"key": f"Image {i + 1}"},
        )
    body = client.get(f"/api/comfy/sessions/{s['id']}/source_slots").json()
    keys = [r["key"] for r in body["slots"]]
    assert keys == ["Image 1", "Image 2", "Image 3"]


# --- session-scope isolation ------------------------------------------


def test_slots_isolated_per_session(client):
    s1 = _make_session(client, name="A")
    s2 = _make_session(client, name="B")
    client.post(
        f"/api/comfy/sessions/{s1['id']}/source_slots",
        json={"key": "Only-In-A"},
    )
    body = client.get(f"/api/comfy/sessions/{s2['id']}/source_slots").json()
    assert body == {"slots": []}


# --- patch -------------------------------------------------------------


def test_patch_clears_description_with_explicit_null(client):
    s = _make_session(client)
    created = client.post(
        f"/api/comfy/sessions/{s['id']}/source_slots",
        json={"key": "Image 1", "description": "initial"},
    ).json()
    resp = client.patch(
        f"/api/comfy/sessions/{s['id']}/source_slots/{created['id']}",
        json={"description": None},
    )
    assert resp.status_code == 200
    assert resp.json()["description"] is None


def test_patch_leaves_omitted_field_alone(client):
    s = _make_session(client)
    created = client.post(
        f"/api/comfy/sessions/{s['id']}/source_slots",
        json={"key": "Image 1", "description": "keep me"},
    ).json()
    resp = client.patch(
        f"/api/comfy/sessions/{s['id']}/source_slots/{created['id']}",
        json={"key": "Renamed"},
    )
    assert resp.status_code == 200
    assert resp.json()["description"] == "keep me"
    assert resp.json()["key"] == "Renamed"


def test_patch_404_on_unknown_slot(client):
    s = _make_session(client)
    resp = client.patch(
        f"/api/comfy/sessions/{s['id']}/source_slots/missing",
        json={"key": "Renamed"},
    )
    assert resp.status_code == 404


def test_patch_409_on_key_collision(client):
    s = _make_session(client)
    client.post(
        f"/api/comfy/sessions/{s['id']}/source_slots",
        json={"key": "A"},
    )
    other = client.post(
        f"/api/comfy/sessions/{s['id']}/source_slots",
        json={"key": "B"},
    ).json()
    resp = client.patch(
        f"/api/comfy/sessions/{s['id']}/source_slots/{other['id']}",
        json={"key": "A"},
    )
    assert resp.status_code == 409


# --- delete ------------------------------------------------------------


def test_delete_removes_slot(client):
    s = _make_session(client)
    created = client.post(
        f"/api/comfy/sessions/{s['id']}/source_slots",
        json={"key": "Image 1"},
    ).json()
    resp = client.delete(
        f"/api/comfy/sessions/{s['id']}/source_slots/{created['id']}",
    )
    assert resp.status_code == 204
    body = client.get(f"/api/comfy/sessions/{s['id']}/source_slots").json()
    assert body == {"slots": []}


def test_delete_404_when_missing(client):
    s = _make_session(client)
    resp = client.delete(
        f"/api/comfy/sessions/{s['id']}/source_slots/missing",
    )
    assert resp.status_code == 404


# --- image FK behaviour ------------------------------------------------


def test_deleting_image_unbinds_slots(client):
    """ON DELETE SET NULL on source_image_id — dropping the image
    leaves the slot intact, just unbound."""
    s = _make_session(client)
    img = _upload_image(client, s["id"])
    created = client.post(
        f"/api/comfy/sessions/{s['id']}/source_slots",
        json={"key": "Image 1", "source_image_id": img["id"]},
    ).json()
    assert created["source_image_id"] == img["id"]

    client.delete(f"/api/sessions/{s['id']}/sources/{img['id']}")
    body = client.get(f"/api/comfy/sessions/{s['id']}/source_slots").json()
    assert len(body["slots"]) == 1
    assert body["slots"][0]["source_image_id"] is None
