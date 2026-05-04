"""Tests for /api/comfy/packs and /api/comfy/nodes (the library
read/edit surface).

The per-node import wizard isn't shipped yet, so these tests seed the
catalog directly via the repo to verify the read and edit surface.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_conn
from app.main import app
from app.storage import comfy_catalog_repo
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


def _seed_pack(conn, name="rgthree-comfy", **kwargs):
    return comfy_catalog_repo.upsert_pack(
        conn,
        name=name,
        display_name=kwargs.get("display_name", name),
        description=kwargs.get("description", "x"),
        version=kwargs.get("version", "1.0"),
        repo_url=kwargs.get("repo_url"),
        publisher_id=kwargs.get("publisher_id"),
        dir_path=kwargs.get("dir_path"),
        readme_md=kwargs.get("readme_md"),
    )


def _seed_node(
    conn, *, class_type, pack_name, display_name=None, description="",
    inputs_semantic=None, requires_semantic_config=True, category=None,
):
    return comfy_catalog_repo.upsert_node(
        conn,
        class_type=class_type,
        pack_name=pack_name,
        display_name=display_name or class_type,
        category=category,
        inputs_raw={"required": {}},
        outputs_raw=[],
        inputs_semantic=inputs_semantic if inputs_semantic is not None else [],
        description_md=description,
        requires_semantic_config=requires_semantic_config,
    )


def test_list_packs_empty_initially(client):
    body = client.get("/api/comfy/packs").json()
    assert body == {"packs": []}


def test_list_packs_returns_metadata_and_node_count(client, conn):
    _seed_pack(conn, name="ComfyUI", display_name="ComfyUI", repo_url="https://x")
    _seed_pack(conn, name="rgthree-comfy", display_name="rgthree", publisher_id="rgthree")
    _seed_node(conn, class_type="KSampler", pack_name="ComfyUI")
    _seed_node(conn, class_type="CLIPTextEncode", pack_name="ComfyUI")
    _seed_node(conn, class_type="RgthreePowerLoraLoader", pack_name="rgthree-comfy")

    body = client.get("/api/comfy/packs").json()
    by_name = {p["name"]: p for p in body["packs"]}
    assert by_name["ComfyUI"]["node_count"] == 2
    assert by_name["rgthree-comfy"]["node_count"] == 1
    assert by_name["rgthree-comfy"]["publisher_id"] == "rgthree"


def test_get_pack_returns_readme_and_nodes(client, conn):
    _seed_pack(conn, name="ComfyUI", display_name="ComfyUI", readme_md="# ComfyUI")
    _seed_node(conn, class_type="KSampler", pack_name="ComfyUI", description="Samples.")
    body = client.get("/api/comfy/packs/ComfyUI").json()
    assert body["readme_md"] == "# ComfyUI"
    assert [n["class_type"] for n in body["nodes"]] == ["KSampler"]


def test_get_pack_404_for_missing(client):
    assert client.get("/api/comfy/packs/ghost").status_code == 404


def test_list_nodes_empty_initially(client):
    body = client.get("/api/comfy/nodes").json()
    assert body == {"nodes": []}


def test_list_nodes_filters_by_search_query(client, conn):
    _seed_pack(conn, name="ComfyUI")
    _seed_node(conn, class_type="KSampler", pack_name="ComfyUI", description="Sampler.")
    _seed_node(conn, class_type="CLIPTextEncode", pack_name="ComfyUI", description="Encodes prompts.")
    _seed_node(conn, class_type="LoadImage", pack_name="ComfyUI", description="Loads an image.")

    body = client.get("/api/comfy/nodes?q=image").json()
    assert [n["class_type"] for n in body["nodes"]] == ["LoadImage"]

    # Substring of display_name + class_type also matches.
    body = client.get("/api/comfy/nodes?q=encode").json()
    assert [n["class_type"] for n in body["nodes"]] == ["CLIPTextEncode"]


def test_list_nodes_filters_by_pack(client, conn):
    _seed_pack(conn, name="ComfyUI")
    _seed_pack(conn, name="rgthree-comfy")
    _seed_node(conn, class_type="A", pack_name="ComfyUI")
    _seed_node(conn, class_type="B", pack_name="rgthree-comfy")
    body = client.get("/api/comfy/nodes?pack=ComfyUI").json()
    assert [n["class_type"] for n in body["nodes"]] == ["A"]


def test_list_nodes_filters_by_has_description(client, conn):
    _seed_pack(conn, name="ComfyUI")
    _seed_node(conn, class_type="WithDoc", pack_name="ComfyUI", description="hi")
    _seed_node(conn, class_type="NoDoc", pack_name="ComfyUI", description="")
    body = client.get("/api/comfy/nodes?has_description=true").json()
    assert [n["class_type"] for n in body["nodes"]] == ["WithDoc"]
    body = client.get("/api/comfy/nodes?has_description=false").json()
    assert [n["class_type"] for n in body["nodes"]] == ["NoDoc"]


def test_get_node_returns_full_schema(client, conn):
    _seed_pack(conn, name="ComfyUI")
    _seed_node(
        conn, class_type="KSampler", pack_name="ComfyUI",
        inputs_semantic=[{"name": "seed", "role_hint": "seed"}],
        description="Samples.",
    )
    body = client.get("/api/comfy/nodes/KSampler").json()
    assert body["class_type"] == "KSampler"
    assert body["inputs_semantic"] == [{"name": "seed", "role_hint": "seed", "notes": None}]
    assert body["has_override"] is False
    assert body["inputs_raw"] == {"required": {}}


def test_get_node_404_for_unknown(client):
    assert client.get("/api/comfy/nodes/ghost").status_code == 404


def test_put_node_writes_override_and_merges_on_read(client, conn):
    _seed_pack(conn, name="ComfyUI")
    _seed_node(
        conn, class_type="KSampler", pack_name="ComfyUI",
        description="Original.", inputs_semantic=[{"name": "seed"}],
    )
    resp = client.put(
        "/api/comfy/nodes/KSampler",
        json={"description_md": "User edit."},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["description_md"] == "User edit."
    assert body["has_override"] is True

    # Re-fetch returns the merged form.
    again = client.get("/api/comfy/nodes/KSampler").json()
    assert again["description_md"] == "User edit."

    # Non-overridden fields stay on the canonical row.
    assert again["inputs_semantic"] == [{"name": "seed", "role_hint": None, "notes": None}]


def test_put_node_clears_override_when_set_to_null(client, conn):
    _seed_pack(conn, name="ComfyUI")
    _seed_node(conn, class_type="KSampler", pack_name="ComfyUI", description="Canonical.")
    client.put("/api/comfy/nodes/KSampler", json={"description_md": "User."})
    # Now clear it.
    body = client.put(
        "/api/comfy/nodes/KSampler", json={"description_md": None},
    ).json()
    assert body["description_md"] == "Canonical."
    # Override row was dropped because all override fields are now null.
    assert body["has_override"] is False


def test_put_node_preserves_unmentioned_overrides(client, conn):
    _seed_pack(conn, name="ComfyUI")
    _seed_node(conn, class_type="KSampler", pack_name="ComfyUI")
    client.put(
        "/api/comfy/nodes/KSampler",
        json={"description_md": "D1", "category": "sampling-custom"},
    )
    # Update only one field — the other override stays.
    body = client.put(
        "/api/comfy/nodes/KSampler", json={"description_md": "D2"},
    ).json()
    assert body["description_md"] == "D2"
    assert body["category"] == "sampling-custom"


def test_put_node_404_for_unknown(client):
    resp = client.put("/api/comfy/nodes/ghost", json={"description_md": "x"})
    assert resp.status_code == 404


def test_put_node_can_replace_inputs_semantic(client, conn):
    _seed_pack(conn, name="ComfyUI")
    _seed_node(
        conn, class_type="KSampler", pack_name="ComfyUI",
        inputs_semantic=[{"name": "seed", "role_hint": "seed"}],
    )
    body = client.put(
        "/api/comfy/nodes/KSampler",
        json={"inputs_semantic": [
            {"name": "seed", "role_hint": "seed", "notes": "primary seed"},
            {"name": "steps", "role_hint": "steps", "notes": None},
        ]},
    ).json()
    assert len(body["inputs_semantic"]) == 2
    assert body["inputs_semantic"][1]["role_hint"] == "steps"
    assert body["has_override"] is True


def test_list_nodes_search_picks_up_override_description(client, conn):
    """Search should consider the user-edited description in the
    override layer, not just the canonical text."""
    _seed_pack(conn, name="ComfyUI")
    _seed_node(conn, class_type="K", pack_name="ComfyUI", description="boring")
    client.put("/api/comfy/nodes/K", json={"description_md": "magic word here"})
    body = client.get("/api/comfy/nodes?q=magic").json()
    assert [n["class_type"] for n in body["nodes"]] == ["K"]
