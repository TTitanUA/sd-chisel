from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_conn
from app.main import app
from app.storage import db as db_mod
from app.storage.migrations import apply_pending


@pytest.fixture
def conn(tmp_path):
    c = db_mod.connect(tmp_path / "api.db")
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


def test_family_crud_http(client):
    create = client.post(
        "/api/library/families",
        json={"id": "api_fam", "display_name": "API Family", "prompt_guide": "Guide"},
    )
    assert create.status_code == 201
    assert create.json()["id"] == "api_fam"

    duplicate = client.post(
        "/api/library/families",
        json={"id": "api_fam", "display_name": "API Family", "prompt_guide": "Guide"},
    )
    assert duplicate.status_code == 409

    listed = client.get("/api/library/families", params={"q": "api"})
    assert listed.status_code == 200
    assert [f["id"] for f in listed.json()] == ["api_fam"]

    update = client.put(
        "/api/library/families/api_fam",
        json={"display_name": "API Family 2", "prompt_guide": "Guide 2"},
    )
    assert update.status_code == 200
    assert update.json()["display_name"] == "API Family 2"

    delete = client.delete("/api/library/families/api_fam")
    assert delete.status_code == 204
    assert client.get("/api/library/families/api_fam").status_code == 404


def test_model_crud_http_and_fk_conflict(client):
    missing_family = client.post(
        "/api/library/models",
        json={"name": "bad", "display_name": "Bad", "family_id": "missing"},
    )
    assert missing_family.status_code == 409

    create = client.post(
        "/api/library/models",
        json={
            "name": "juggernaut",
            "display_name": "Juggernaut",
            "family_id": "sdxl",
            "description": "General SDXL model",
        },
    )
    assert create.status_code == 201
    assert create.json()["family_id"] == "sdxl"

    listed = client.get("/api/library/models", params={"family_id": "sdxl", "q": "general"})
    assert [m["name"] for m in listed.json()] == ["juggernaut"]

    update = client.put(
        "/api/library/models/juggernaut",
        json={
            "display_name": "Juggernaut XL",
            "family_id": "sdxl",
            "description": "Updated",
            "author": "RunDiffusion",
            "version": "v10",
            "source_url": "https://example.test/juggernaut",
        },
    )
    assert update.status_code == 200
    assert update.json()["version"] == "v10"

    assert client.delete("/api/library/models/juggernaut").status_code == 204
    assert client.delete("/api/library/models/juggernaut").status_code == 404


def test_lora_crud_http(client):
    create = client.post(
        "/api/library/loras",
        json={
            "name": "cinematic_light",
            "display_name": "Cinematic Light",
            "description": "Rim light and cinematic contrast.",
            "tags": ["light", "mood"],
            "trigger_words": ["cinematic light"],
            "family_id": "sdxl",
            "recommended_weight": 0.8,
            "author": "me",
        },
    )
    assert create.status_code == 201
    assert create.json()["tags"] == ["light", "mood"]

    listed = client.get("/api/library/loras", params={"family_id": "sdxl", "tag": "light"})
    assert [row["name"] for row in listed.json()] == ["cinematic_light"]

    update = client.put(
        "/api/library/loras/cinematic_light",
        json={
            "display_name": "Cinematic Light 2",
            "description": "Softer cinematic light.",
            "tags": ["light"],
            "trigger_words": ["soft cinematic light"],
            "family_id": "sdxl",
            "recommended_weight": 0.65,
            "author": "me",
            "version": "v2",
            "source_url": None,
        },
    )
    assert update.status_code == 200
    assert update.json()["recommended_weight"] == 0.65

    assert client.delete("/api/library/loras/cinematic_light").status_code == 204
    assert client.get("/api/library/loras/cinematic_light").status_code == 404
