from pathlib import Path

import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from app.api.deps import get_conn
from app.main import app
from app.models.chat import ChatRequest, MessageOut
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


from app.services import lm_client


def _bootstrap_chat_session(client, monkeypatch, *, prompt_model: str | None = "mistral") -> str:
    """Configure LMStudio + a prompt-role model + a session that points at it."""
    client.put("/api/settings/lmstudio", json={"base_url": "http://h/v1", "api_key": None})
    monkeypatch.setattr(lm_client, "list_models", lambda **_: ["mistral", "qwen-vl"])
    client.post("/api/settings/lmstudio/refresh")
    client.patch(
        "/api/settings/lmstudio/models/mistral",
        json={"role": "prompt", "enabled": True},
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
    import json as _json
    events: list[dict] = []
    for chunk in body.split(b"\n\n"):
        chunk = chunk.strip()
        if not chunk.startswith(b"data:"):
            continue
        events.append(_json.loads(chunk[len(b"data:"):].strip()))
    return events


def test_chat_streams_deltas_and_persists_both_messages(client, monkeypatch):
    sid = _bootstrap_chat_session(client, monkeypatch)

    captured: dict = {}

    def fake_stream(**kwargs):
        captured.update(kwargs)
        yield "Hel"
        yield "lo"

    monkeypatch.setattr(lm_client, "chat_stream", fake_stream)

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
    assert captured["endpoint"] == {"base_url": "http://h/v1", "api_key": None}
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

    monkeypatch.setattr(lm_client, "chat_stream", fake_stream)

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

    monkeypatch.setattr(lm_client, "chat_stream", fake_stream)

    with client.stream("POST", f"/api/sessions/{sid}/chat", json={"content": "now"}) as r:
        b"".join(r.iter_bytes())

    history = [m for m in captured["messages"] if m["role"] in ("user", "assistant")]
    # 30 prior + 1 new
    assert len(history) == 31
    assert history[0]["content"] == "m10"
    assert history[-1]["content"] == "now"
