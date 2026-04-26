from pathlib import Path

import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from app.models.chat import ChatRequest, MessageOut


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


from app.api.deps import get_conn
from app.main import app
from app.storage import db as db_mod
from app.storage.migrations import apply_pending


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
    from app.storage import session_repo
    sid = _make_session(client)
    session_repo.append_message(conn, session_id=sid, role="user", content="first")
    session_repo.append_message(conn, session_id=sid, role="assistant", content="second")

    body = client.get(f"/api/sessions/{sid}/messages").json()
    assert [m["content"] for m in body["messages"]] == ["first", "second"]
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][1]["role"] == "assistant"
