from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_conn
from app.main import app
from app.services import prompt_orchestrator
from app.services.lmstudio_client import LmError
from app.storage import db as db_mod
from app.storage import library_repo, session_repo, settings_repo
from app.storage.migrations import apply_pending


@pytest.fixture
def conn(tmp_path, seed_default_families):
    c = db_mod.connect(tmp_path / "t.db")
    apply_pending(c, Path(__file__).parent.parent / "migrations")
    seed_default_families(c)
    yield c
    c.close()


@pytest.fixture
def client(conn):
    app.dependency_overrides[get_conn] = lambda: conn
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _bootstrap(client, conn) -> str:
    settings_repo.set_lmstudio(
        conn, url="http://lm", api_key=None,
    )
    settings_repo.upsert_lm_models(conn, models=[
        {"name": "pm-1", "vision": False, "tool_use": False, "reasoning": False},
    ])
    settings_repo.patch_lm_model(
        conn, name="pm-1", enabled=True,
    )
    library_repo.create_model(
        conn, name="m1", display_name="m1", family_id="sdxl", description=None,
    )
    library_repo.create_lora(
        conn, name="lo", display_name="lo", description="d",
        tags=[], trigger_words=[], family_id="sdxl",
    )
    proj = session_repo.create_project(conn, name="p")
    sess = session_repo.create_session(
        conn, project_id=proj["id"], name="s",
        model_name="m1",
    )
    session_repo.update_session(
        conn, sess["id"], name="s", model_name="m1",
        use_negative=True, prompt_model_name="pm-1",
    )
    session_repo.set_vl_summary(conn, sess["id"], "summary text")
    return sess["id"]


def test_generate_prompt_returns_persisted_payload(client, conn, monkeypatch):
    sid = _bootstrap(client, conn)
    monkeypatch.setattr(prompt_orchestrator, "generate", lambda *a, **kw: {
        "prompt_id": 99,
        "prompt": {"positive": "p", "negative": "n", "loras": []},
        "intents": [{"kind": "k", "query": "q"}],
        "retrieved": [{"intent_index": 0, "intent_query": "q", "results": []}],
        "created_at": 1700000000,
    })
    resp = client.post(f"/api/sessions/{sid}/generate-prompt")
    assert resp.status_code == 200
    body = resp.json()
    assert body["prompt_id"] == 99
    assert body["prompt"]["positive"] == "p"
    assert body["intents"][0]["kind"] == "k"


def test_generate_prompt_404_when_session_unknown(client):
    resp = client.post("/api/sessions/nope/generate-prompt")
    assert resp.status_code == 404


def test_generate_prompt_409_when_lmstudio_not_configured(client, conn):
    sid = _bootstrap(client, conn)
    settings_repo.set_lmstudio(conn, url=None, api_key=None)
    resp = client.post(f"/api/sessions/{sid}/generate-prompt")
    assert resp.status_code == 409
    assert "base_url" in resp.json()["detail"]


def test_generate_prompt_409_when_prompt_model_not_set(client, conn):
    sid = _bootstrap(client, conn)
    session_repo.update_session(
        conn, sid, name="s", model_name="m1",
        use_negative=True, prompt_model_name=None,
    )
    resp = client.post(f"/api/sessions/{sid}/generate-prompt")
    assert resp.status_code == 409
    assert "prompt_model_name" in resp.json()["detail"]


def test_generate_prompt_409_for_precondition(client, conn, monkeypatch):
    sid = _bootstrap(client, conn)
    def boom(*a, **kw):
        raise prompt_orchestrator.PreconditionError("session has no vl_summary")
    monkeypatch.setattr(prompt_orchestrator, "generate", boom)
    resp = client.post(f"/api/sessions/{sid}/generate-prompt")
    assert resp.status_code == 409
    assert "vl_summary" in resp.json()["detail"]


def test_generate_prompt_502_for_lm_error(client, conn, monkeypatch):
    sid = _bootstrap(client, conn)
    def boom(*a, **kw):
        raise LmError("upstream", "boom")
    monkeypatch.setattr(prompt_orchestrator, "generate", boom)
    resp = client.post(f"/api/sessions/{sid}/generate-prompt")
    assert resp.status_code == 502
    assert "boom" in resp.json()["detail"]


def test_list_prompts_returns_newest_first(client, conn):
    sid = _bootstrap(client, conn)
    session_repo.append_prompt(
        conn, session_id=sid, positive="old", negative=None,
        loras=[], intents=None, retrieved=None,
    )
    session_repo.append_prompt(
        conn, session_id=sid, positive="new", negative=None,
        loras=[{"name": "lo", "weight": 0.5}],
        intents=[{"kind": "k", "query": "q"}],
        retrieved=[{"intent_index": 0, "intent_query": "q", "results": []}],
    )
    resp = client.get(f"/api/sessions/{sid}/prompts")
    assert resp.status_code == 200
    rows = resp.json()["prompts"]
    assert [r["prompt"]["positive"] for r in rows] == ["new", "old"]
    assert rows[0]["intents"] == [{"kind": "k", "query": "q"}]
    assert rows[1]["intents"] is None


def test_list_prompts_404_for_unknown_session(client):
    resp = client.get("/api/sessions/nope/prompts")
    assert resp.status_code == 404
