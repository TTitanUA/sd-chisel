import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.deps import get_conn
from app.main import app
from app.models.chat import ChatRequest, MessageOut
from app.services import lmstudio_client
from app.storage import db as db_mod
from app.storage import session_repo
from app.storage.migrations import apply_pending


def test_chat_request_strips_and_rejects_empty():
    assert ChatRequest(content="  hi  ").content == "hi"
    with pytest.raises(ValidationError):
        ChatRequest(content="   ")
    with pytest.raises(ValidationError):
        ChatRequest(content="")


def test_chat_request_rejects_oversize():
    with pytest.raises(ValidationError):
        ChatRequest(content="x" * 8001)


def test_message_out_round_trip():
    m = MessageOut(id=1, session_id="s", role="user", content="hi", created_at=10)
    assert m.model_dump() == {
        "id": 1, "session_id": "s", "role": "user", "content": "hi", "created_at": 10,
    }


@pytest.fixture
def conn(tmp_path):
    c = db_mod.connect(tmp_path / "chat.db")
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
        json={"name": "s", "model_name": None, "use_negative": True},
    ).json()["id"]


def test_messages_empty_for_fresh_session(client):
    sid = _make_session(client)
    resp = client.get(f"/api/sessions/{sid}/messages")
    assert resp.status_code == 200
    assert resp.json() == {"messages": []}


def test_messages_404_when_session_missing(client):
    assert client.get("/api/sessions/missing/messages").status_code == 404


def test_messages_returned_in_chronological_order(client, conn):
    sid = _make_session(client)
    session_repo.append_message(conn, session_id=sid, role="user", content="first")
    session_repo.append_message(conn, session_id=sid, role="assistant", content="second")

    body = client.get(f"/api/sessions/{sid}/messages").json()
    assert [m["content"] for m in body["messages"]] == ["first", "second"]
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][1]["role"] == "assistant"


def _bootstrap_chat_session(client, monkeypatch, *, prompt_model: str | None = "mistral") -> str:
    """Configure LMStudio + a prompt-role model + a session that points at it."""
    client.put("/api/settings/lmstudio", json={"base_url": "http://h", "api_key": None})
    monkeypatch.setattr(lmstudio_client, "list_models", lambda **_: [
        lmstudio_client.LmsModel(name="mistral", vision=False, tool_use=False, reasoning=False),
        lmstudio_client.LmsModel(name="qwen-vl", vision=True, tool_use=False, reasoning=False),
    ])
    client.post("/api/settings/lmstudio/refresh")
    client.patch(
        "/api/settings/lmstudio/models/mistral",
        json={"enabled": True},
    )

    sid = _make_session(client)
    if prompt_model is not None:
        client.patch(
            f"/api/sessions/{sid}",
            json={
                "name": "s", "model_name": None, "use_negative": True,
                "pinned_loras": [],
                "vl_model_name": None,
                "prompt_model_name": prompt_model,
            },
        )
    return sid


def _parse_sse(body: bytes) -> list[dict]:
    events: list[dict] = []
    for chunk in body.split(b"\n\n"):
        chunk = chunk.strip()
        if not chunk.startswith(b"data:"):
            continue
        events.append(json.loads(chunk[len(b"data:"):].strip()))
    return events


def test_chat_streams_deltas_and_persists_both_messages(client, monkeypatch):
    sid = _bootstrap_chat_session(client, monkeypatch)

    captured: dict = {}

    def fake_stream(**kwargs):
        captured.update(kwargs)
        yield "Hel"
        yield "lo"

    monkeypatch.setattr(lmstudio_client, "chat_stream", fake_stream)

    with client.stream(
        "POST", f"/api/sessions/{sid}/chat",
        json={"content": "hey"},
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = b"".join(resp.iter_bytes())

    events = _parse_sse(body)
    deltas = [e for e in events if e["type"] == "delta"]
    done = [e for e in events if e["type"] == "done"]
    errors = [e for e in events if e["type"] == "error"]
    assert [d["content"] for d in deltas] == ["Hel", "lo"]
    assert len(done) == 1 and isinstance(done[0]["message_id"], int)
    assert errors == []

    # Both messages persisted in order
    msgs = client.get(f"/api/sessions/{sid}/messages").json()["messages"]
    assert [(m["role"], m["content"]) for m in msgs] == [
        ("user", "hey"),
        ("assistant", "Hello"),
    ]
    # Done event references the assistant message id
    assert done[0]["message_id"] == msgs[-1]["id"]

    # Endpoint config + model name flowed into lm_client
    assert captured["model"] == "mistral"
    assert captured["endpoint"] == {"server_root": "http://h", "api_key": None}
    # The most recent message in the upstream payload is the new user message
    assert captured["messages"][-1] == {"role": "user", "content": "hey"}
    # System prompt is prepended
    assert captured["messages"][0]["role"] == "system"


def test_chat_includes_vl_summary_and_recent_history(client, conn, monkeypatch):
    from app.storage import session_repo
    sid = _bootstrap_chat_session(client, monkeypatch)
    session_repo.set_vl_summary(conn, sid, "moody portrait, soft rim light")
    session_repo.append_message(conn, session_id=sid, role="user", content="prior-1")
    session_repo.append_message(conn, session_id=sid, role="assistant", content="prior-2")

    captured: dict = {}

    def fake_stream(**kwargs):
        captured.update(kwargs)
        yield "ok"

    monkeypatch.setattr(lmstudio_client, "chat_stream", fake_stream)

    with client.stream("POST", f"/api/sessions/{sid}/chat", json={"content": "now"}) as r:
        b"".join(r.iter_bytes())

    msgs = captured["messages"]
    # system prompt + vl-summary system + 2 history + new user
    assert msgs[0]["role"] == "system"
    assert any("moody portrait" in m["content"] for m in msgs if m["role"] == "system")
    assert [(m["role"], m["content"]) for m in msgs[-3:]] == [
        ("user", "prior-1"),
        ("assistant", "prior-2"),
        ("user", "now"),
    ]


def test_chat_truncates_history_to_30(client, conn, monkeypatch):
    from app.storage import session_repo
    sid = _bootstrap_chat_session(client, monkeypatch)
    for i in range(40):
        session_repo.append_message(
            conn, session_id=sid, role="user" if i % 2 == 0 else "assistant",
            content=f"m{i}",
        )

    captured: dict = {}

    def fake_stream(**kwargs):
        captured.update(kwargs)
        yield "ok"

    monkeypatch.setattr(lmstudio_client, "chat_stream", fake_stream)

    with client.stream("POST", f"/api/sessions/{sid}/chat", json={"content": "now"}) as r:
        b"".join(r.iter_bytes())

    history = [m for m in captured["messages"] if m["role"] in ("user", "assistant")]
    # 30 prior + 1 new
    assert len(history) == 31
    assert history[0]["content"] == "m10"
    assert history[-1]["content"] == "now"


def test_chat_persists_assistant_with_yield_dep_lifecycle(tmp_path, monkeypatch):
    """Reproduce production get_conn lifecycle: yield conn / finally close.
    Catches a regression where the streaming generator runs after the dep
    teardown closed conn."""
    from app.api.deps import get_conn as real_get_conn  # noqa: F401  (sanity import)

    db_file = tmp_path / "lifecycle.db"

    def yield_conn():
        c = db_mod.connect(db_file)
        apply_pending(c, Path(__file__).parent.parent / "migrations")
        try:
            yield c
        finally:
            c.close()

    app.dependency_overrides[real_get_conn] = yield_conn
    try:
        local_client = TestClient(app)

        # Bootstrap: lmstudio config, model, session with prompt_model
        local_client.put("/api/settings/lmstudio", json={"base_url": "http://h", "api_key": None})
        monkeypatch.setattr(lmstudio_client, "list_models", lambda **_: [
            lmstudio_client.LmsModel(name="mistral", vision=False, tool_use=False, reasoning=False),
        ])
        local_client.post("/api/settings/lmstudio/refresh")
        local_client.patch(
            "/api/settings/lmstudio/models/mistral",
            json={"enabled": True},
        )
        pid = local_client.post("/api/projects", json={"name": "P"}).json()["id"]
        sid = local_client.post(
            f"/api/projects/{pid}/sessions",
            json={"name": "s", "model_name": None, "use_negative": True},
        ).json()["id"]
        local_client.patch(
            f"/api/sessions/{sid}",
            json={
                "name": "s", "model_name": None, "use_negative": True,
                "pinned_loras": [],
                "vl_model_name": None,
                "prompt_model_name": "mistral",
            },
        )

        def fake_stream(**_):
            yield "Hello"

        monkeypatch.setattr(lmstudio_client, "chat_stream", fake_stream)

        with local_client.stream(
            "POST", f"/api/sessions/{sid}/chat",
            json={"content": "hi"},
        ) as resp:
            assert resp.status_code == 200
            body = b"".join(resp.iter_bytes())

        events = _parse_sse(body)
        done = [e for e in events if e["type"] == "done"]
        errors = [e for e in events if e["type"] == "error"]
        assert errors == [], f"unexpected error events: {errors}"
        assert len(done) == 1, f"expected one done event, got {len(done)} (events={events})"

        # Confirm assistant row was persisted (this is what would fail if conn is closed)
        msgs = local_client.get(f"/api/sessions/{sid}/messages").json()["messages"]
        assert [(m["role"], m["content"]) for m in msgs] == [
            ("user", "hi"),
            ("assistant", "Hello"),
        ]
    finally:
        app.dependency_overrides.clear()


def test_chat_404_when_session_missing(client):
    assert client.post("/api/sessions/missing/chat", json={"content": "x"}).status_code == 404


def test_chat_409_when_no_lmstudio_config(client):
    sid = _make_session(client)
    resp = client.post(f"/api/sessions/{sid}/chat", json={"content": "x"})
    assert resp.status_code == 409
    assert "lmstudio" in resp.json()["detail"].lower() or "base_url" in resp.json()["detail"].lower()


def test_chat_409_when_no_prompt_model_on_session(client, monkeypatch):
    sid = _bootstrap_chat_session(client, monkeypatch, prompt_model=None)
    resp = client.post(f"/api/sessions/{sid}/chat", json={"content": "x"})
    assert resp.status_code == 409
    assert "prompt_model" in resp.json()["detail"]


def test_chat_409_when_prompt_model_disabled(client, monkeypatch):
    sid = _bootstrap_chat_session(client, monkeypatch)
    client.patch(
        "/api/settings/lmstudio/models/mistral", json={"enabled": False},
    )
    resp = client.post(f"/api/sessions/{sid}/chat", json={"content": "x"})
    assert resp.status_code == 409


def test_chat_ok_when_prompt_model_is_vision_capable(client, monkeypatch):
    # Vision-capable models are valid prompt models — no role restriction exists.
    sid = _bootstrap_chat_session(client, monkeypatch)
    client.patch("/api/settings/lmstudio/models/mistral", json={"vision": True})

    def fake_stream(**_):
        yield "ok"

    monkeypatch.setattr(lmstudio_client, "chat_stream", fake_stream)

    with client.stream("POST", f"/api/sessions/{sid}/chat", json={"content": "hi"}) as resp:
        assert resp.status_code == 200


def test_chat_422_on_blank_content(client, monkeypatch):
    sid = _bootstrap_chat_session(client, monkeypatch)
    assert client.post(f"/api/sessions/{sid}/chat", json={"content": "   "}).status_code == 422


def test_chat_emits_error_event_and_keeps_user_message_on_upstream_failure(client, monkeypatch):
    sid = _bootstrap_chat_session(client, monkeypatch)

    def fail(**_):
        raise lmstudio_client.LmError("upstream", "boom")
        yield  # pragma: no cover  (make this a generator)

    monkeypatch.setattr(lmstudio_client, "chat_stream", fail)

    with client.stream("POST", f"/api/sessions/{sid}/chat", json={"content": "hey"}) as resp:
        assert resp.status_code == 200  # SSE always opens 200
        body = b"".join(resp.iter_bytes())

    events = _parse_sse(body)
    assert any(e["type"] == "error" for e in events)
    assert all(e["type"] != "done" for e in events)

    # User message remains; assistant was NOT saved
    msgs = client.get(f"/api/sessions/{sid}/messages").json()["messages"]
    assert [m["role"] for m in msgs] == ["user"]
    assert msgs[0]["content"] == "hey"


def test_chat_does_not_persist_assistant_when_stream_yields_nothing(client, monkeypatch):
    sid = _bootstrap_chat_session(client, monkeypatch)

    def empty(**_):
        if False:
            yield ""  # pragma: no cover

    monkeypatch.setattr(lmstudio_client, "chat_stream", empty)

    with client.stream("POST", f"/api/sessions/{sid}/chat", json={"content": "hey"}) as resp:
        body = b"".join(resp.iter_bytes())

    events = _parse_sse(body)
    assert any(e["type"] == "error" for e in events)
    msgs = client.get(f"/api/sessions/{sid}/messages").json()["messages"]
    assert [m["role"] for m in msgs] == ["user"]
