from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_conn
from app.main import app
from app.services import chat_summarizer, prompt_orchestrator
from app.services.lmstudio_client import LmError
from app.storage import db as db_mod
from app.storage import library_repo, session_repo, settings_repo, source_image_repo
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
    img = source_image_repo.insert(
        conn, session_id=sess["id"],
        path=f"images/{sess['id']}/sources/main.png",
        original_filename="main.png", is_main=True,
    )
    source_image_repo.set_analysis(
        conn, img["id"], analysis="summary text", refining_prompt=None,
    )
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


def test_generate_prompt_409_when_reindex_active(client, conn):
    """A queued reindex task in the registry should block generate-prompt."""
    import asyncio

    from app.services import task_runner
    sid = _bootstrap(client, conn)

    async def setup_registry():
        reg = task_runner.TaskRegistry()
        # Worker is intentionally NOT started — the task stays queued,
        # which still counts as active and is enough to trip the gate.
        reg.submit(
            kind="reindex_lora", title="t",
            target={"lora_name": "lo"},
            runner=lambda progress: None,
        )
        return reg

    reg = asyncio.run(setup_registry())
    task_runner.install(reg)
    try:
        resp = client.post(f"/api/sessions/{sid}/generate-prompt")
        assert resp.status_code == 409
        body = resp.json()
        assert body["detail"]["code"] == "indexing_in_progress"
        assert body["detail"]["task_ids"]
    finally:
        task_runner._install_for_tests(None)


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
        raise prompt_orchestrator.PreconditionError(
            "session has no main source image with a completed analysis yet",
        )
    monkeypatch.setattr(prompt_orchestrator, "generate", boom)
    resp = client.post(f"/api/sessions/{sid}/generate-prompt")
    assert resp.status_code == 409
    assert "main source image" in resp.json()["detail"]


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


# --- summarize-chat + generate-prompt body fields --------------------------


def test_summarize_chat_returns_brief_and_context(client, conn, monkeypatch):
    sid = _bootstrap(client, conn)
    session_repo.append_message(conn, session_id=sid, role="user", content="moodier")
    session_repo.append_message(
        conn, session_id=sid, role="assistant", content="ok, low light",
    )
    monkeypatch.setattr(
        chat_summarizer, "summarize_session_chat",
        lambda *a, **kw: "Make it moodier with low key lighting.",
    )
    resp = client.post(f"/api/sessions/{sid}/summarize-chat")
    assert resp.status_code == 200
    body = resp.json()
    assert body["brief"] == "Make it moodier with low key lighting."
    ctx = body["context"]
    assert ctx["mode"] == "i2i"
    assert ctx["model_name"] == "m1"
    assert ctx["family_id"] == "sdxl"
    assert ctx["use_negative"] is True
    assert ctx["main_image"]["label"] == "Image_1"
    assert ctx["main_image"]["analysis"] == "summary text"
    assert ctx["reference_images"] == []


def test_summarize_chat_502_on_lm_error(client, conn, monkeypatch):
    sid = _bootstrap(client, conn)
    monkeypatch.setattr(
        chat_summarizer, "summarize_session_chat",
        lambda *a, **kw: (_ for _ in ()).throw(LmError("upstream", "boom")),
    )
    resp = client.post(f"/api/sessions/{sid}/summarize-chat")
    assert resp.status_code == 502


def test_generate_prompt_passes_brief_to_orchestrator(client, conn, monkeypatch):
    sid = _bootstrap(client, conn)
    captured: dict = {}

    def fake_generate(_conn, **kwargs):
        captured.update(kwargs)
        return {
            "prompt_id": 7,
            "prompt": {"positive": "p", "negative": None, "loras": []},
            "intents": [],
            "retrieved": [],
            "brief": kwargs.get("brief"),
            "created_at": 0,
        }

    monkeypatch.setattr(prompt_orchestrator, "generate", fake_generate)
    resp = client.post(
        f"/api/sessions/{sid}/generate-prompt",
        json={"brief": "moody nighttime", "compact_history": False},
    )
    assert resp.status_code == 200
    assert captured["brief"] == "moody nighttime"
    assert resp.json()["brief"] == "moody nighttime"


def test_generate_prompt_compacts_history_when_flag_set(client, conn, monkeypatch):
    sid = _bootstrap(client, conn)
    session_repo.append_message(conn, session_id=sid, role="user", content="old-1")
    session_repo.append_message(conn, session_id=sid, role="assistant", content="old-2")

    monkeypatch.setattr(prompt_orchestrator, "generate", lambda *a, **kw: {
        "prompt_id": 1,
        "prompt": {"positive": "p", "negative": None, "loras": []},
        "intents": [],
        "retrieved": [],
        "brief": kw.get("brief"),
        "created_at": 0,
    })
    resp = client.post(
        f"/api/sessions/{sid}/generate-prompt",
        json={"brief": "moody", "compact_history": True},
    )
    assert resp.status_code == 200

    msgs = session_repo.list_messages(conn, session_id=sid)
    assert len(msgs) == 1
    assert msgs[0]["role"] == "assistant"
    assert msgs[0]["content"].startswith("Summary of previous discussion:")
    assert "moody" in msgs[0]["content"]


def test_generate_prompt_does_not_compact_when_brief_missing(client, conn, monkeypatch):
    """compact_history=true is a no-op when brief is empty — there is
    nothing to summarize down to."""
    sid = _bootstrap(client, conn)
    session_repo.append_message(conn, session_id=sid, role="user", content="keep me")

    monkeypatch.setattr(prompt_orchestrator, "generate", lambda *a, **kw: {
        "prompt_id": 1,
        "prompt": {"positive": "p", "negative": None, "loras": []},
        "intents": [], "retrieved": [], "brief": None, "created_at": 0,
    })
    resp = client.post(
        f"/api/sessions/{sid}/generate-prompt",
        json={"compact_history": True},
    )
    assert resp.status_code == 200

    msgs = session_repo.list_messages(conn, session_id=sid)
    assert len(msgs) == 1
    assert msgs[0]["content"] == "keep me"
