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
from app.storage import session_repo, source_image_repo
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
        json={"session_type": "i2i", "name": "s", "model_name": None, "use_negative": True},
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
    main_img = source_image_repo.insert(
        conn, session_id=sid, path=f"images/{sid}/sources/main.png",
        original_filename="main.png", is_main=True,
    )
    source_image_repo.set_analysis(
        conn, main_img["id"],
        analysis="moody portrait, soft rim light", refining_prompt=None,
    )
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


def test_chat_t2i_uses_t2i_system_prompt_and_renders_refs_only(
    client, conn, monkeypatch,
):
    """t2i chat picks the t2i framing and lists every analysed source as a
    reference — no `(main)` label, no `# Source image analysis` block."""
    from app.storage import session_repo
    # Set up a t2i session: bootstrap LMStudio, then create the session
    # explicitly with session_type=t2i and point it at a prompt model.
    client.put("/api/settings/lmstudio", json={"base_url": "http://h", "api_key": None})
    monkeypatch.setattr(lmstudio_client, "list_models", lambda **_: [
        lmstudio_client.LmsModel(name="mistral", vision=False, tool_use=False, reasoning=False),
    ])
    client.post("/api/settings/lmstudio/refresh")
    client.patch("/api/settings/lmstudio/models/mistral", json={"enabled": True})
    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    sid = client.post(
        f"/api/projects/{pid}/sessions",
        json={"session_type": "t2i", "name": "s", "model_name": None, "use_negative": True},
    ).json()["id"]
    client.patch(
        f"/api/sessions/{sid}",
        json={
            "name": "s", "model_name": None, "use_negative": True,
            "pinned_loras": [], "vl_model_name": None,
            "prompt_model_name": "mistral",
        },
    )

    img1 = source_image_repo.insert(
        conn, session_id=sid, path=f"images/{sid}/sources/a.png",
        original_filename="a.png", is_main=False,
    )
    source_image_repo.set_analysis(
        conn, img1["id"], analysis="autumn forest", refining_prompt=None,
    )
    img2 = source_image_repo.insert(
        conn, session_id=sid, path=f"images/{sid}/sources/b.png",
        original_filename="b.png", is_main=False,
    )
    source_image_repo.set_analysis(
        conn, img2["id"], analysis="bronze sculpture", refining_prompt=None,
    )

    captured: dict = {}

    def fake_stream(**kwargs):
        captured.update(kwargs)
        yield "ok"

    monkeypatch.setattr(lmstudio_client, "chat_stream", fake_stream)

    with client.stream("POST", f"/api/sessions/{sid}/chat", json={"content": "now"}) as r:
        b"".join(r.iter_bytes())

    msgs = captured["messages"]
    system_blob = "\n".join(m["content"] for m in msgs if m["role"] == "system")
    assert "text-to-image" in system_blob.lower()
    assert "(main)" not in system_blob
    assert "# Source image analysis" not in system_blob
    assert "# Reference images" in system_blob
    assert "autumn forest" in system_blob
    assert "bronze sculpture" in system_blob


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
            json={"session_type": "i2i", "name": "s", "model_name": None, "use_negative": True},
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


def test_chat_emits_error_event_and_rolls_back_user_message_on_upstream_failure(client, monkeypatch):
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

    # User message is rolled back so a retry doesn't pile up duplicate
    # user turns in the history.
    msgs = client.get(f"/api/sessions/{sid}/messages").json()["messages"]
    assert msgs == []


def test_chat_does_not_persist_anything_when_stream_yields_nothing(client, monkeypatch):
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
    assert msgs == []


# --- delete / edit / clear -------------------------------------------------


def test_delete_user_message_removes_only_that_row(client, conn):
    sid = _make_session(client)
    u1 = session_repo.append_message(conn, session_id=sid, role="user", content="u1")
    a1 = session_repo.append_message(conn, session_id=sid, role="assistant", content="a1")
    u2 = session_repo.append_message(conn, session_id=sid, role="user", content="u2")

    resp = client.delete(f"/api/sessions/{sid}/messages/{u1['id']}")
    assert resp.status_code == 204

    remaining = client.get(f"/api/sessions/{sid}/messages").json()["messages"]
    assert [m["id"] for m in remaining] == [a1["id"], u2["id"]]


def test_delete_message_404_when_message_in_other_session(client, conn):
    sid_a = _make_session(client)
    sid_b = _make_session(client)
    msg = session_repo.append_message(conn, session_id=sid_a, role="user", content="x")
    assert client.delete(f"/api/sessions/{sid_b}/messages/{msg['id']}").status_code == 404


def test_delete_message_404_when_missing(client):
    sid = _make_session(client)
    assert client.delete(f"/api/sessions/{sid}/messages/9999").status_code == 404


def test_delete_assistant_message_rejected_with_409(client, conn):
    sid = _make_session(client)
    a = session_repo.append_message(conn, session_id=sid, role="assistant", content="a")
    assert client.delete(f"/api/sessions/{sid}/messages/{a['id']}").status_code == 409


def test_clear_messages_drops_everything_for_session(client, conn):
    sid_a = _make_session(client)
    sid_b = _make_session(client)
    session_repo.append_message(conn, session_id=sid_a, role="user", content="a-u")
    session_repo.append_message(conn, session_id=sid_a, role="assistant", content="a-a")
    keep = session_repo.append_message(conn, session_id=sid_b, role="user", content="b-u")

    resp = client.delete(f"/api/sessions/{sid_a}/messages")
    assert resp.status_code == 204

    assert client.get(f"/api/sessions/{sid_a}/messages").json()["messages"] == []
    other = client.get(f"/api/sessions/{sid_b}/messages").json()["messages"]
    assert [m["id"] for m in other] == [keep["id"]]


def test_clear_messages_404_when_session_missing(client):
    assert client.delete("/api/sessions/missing/messages").status_code == 404


# --- chat with replace_message_id ------------------------------------------


def test_chat_with_replace_id_truncates_after_and_does_not_append_user(client, monkeypatch, conn):
    sid = _bootstrap_chat_session(client, monkeypatch)
    u1 = session_repo.append_message(conn, session_id=sid, role="user", content="u1")
    session_repo.append_message(conn, session_id=sid, role="assistant", content="a1")
    session_repo.append_message(conn, session_id=sid, role="user", content="u2")
    session_repo.append_message(conn, session_id=sid, role="assistant", content="a2")

    captured: dict = {}

    def fake_stream(*, endpoint, model, messages, transport=None):
        captured["messages"] = messages
        yield "edited reply"

    monkeypatch.setattr(lmstudio_client, "chat_stream", fake_stream)

    with client.stream(
        "POST",
        f"/api/sessions/{sid}/chat",
        json={"content": "u1 rewritten", "replace_message_id": u1["id"]},
    ) as resp:
        body = b"".join(resp.iter_bytes())
    assert resp.status_code == 200
    events = _parse_sse(body)
    assert any(e["type"] == "done" for e in events)

    # Payload must contain exactly ONE user turn at the tail with the new
    # content — no leftover dup, no duplicate appended user.
    user_turns = [m for m in captured["messages"] if m["role"] == "user"]
    assert [m["content"] for m in user_turns] == ["u1 rewritten"]

    # DB now has just the edited row plus the new assistant.
    msgs = client.get(f"/api/sessions/{sid}/messages").json()["messages"]
    assert [(m["role"], m["content"]) for m in msgs] == [
        ("user", "u1 rewritten"),
        ("assistant", "edited reply"),
    ]


def test_chat_replace_id_404_on_missing_message(client, monkeypatch):
    sid = _bootstrap_chat_session(client, monkeypatch)
    resp = client.post(
        f"/api/sessions/{sid}/chat",
        json={"content": "hi", "replace_message_id": 9999},
    )
    assert resp.status_code == 404


def test_chat_replace_id_409_when_targeting_assistant(client, monkeypatch, conn):
    sid = _bootstrap_chat_session(client, monkeypatch)
    a = session_repo.append_message(conn, session_id=sid, role="assistant", content="a")
    resp = client.post(
        f"/api/sessions/{sid}/chat",
        json={"content": "x", "replace_message_id": a["id"]},
    )
    assert resp.status_code == 409


def test_chat_replace_id_keeps_edit_committed_on_upstream_failure(client, monkeypatch, conn):
    sid = _bootstrap_chat_session(client, monkeypatch)
    u = session_repo.append_message(conn, session_id=sid, role="user", content="orig")
    session_repo.append_message(conn, session_id=sid, role="assistant", content="reply")

    def fail(**_):
        raise lmstudio_client.LmError("upstream", "boom")
        yield  # pragma: no cover

    monkeypatch.setattr(lmstudio_client, "chat_stream", fail)

    with client.stream(
        "POST",
        f"/api/sessions/{sid}/chat",
        json={"content": "edited", "replace_message_id": u["id"]},
    ) as resp:
        body = b"".join(resp.iter_bytes())
    events = _parse_sse(body)
    assert any(e["type"] == "error" for e in events)

    # The edit IS committed (content replaced, follow-up dropped) even
    # though the assistant call failed — user explicitly asked for the
    # edit; rolling it back would lose their work.
    msgs = client.get(f"/api/sessions/{sid}/messages").json()["messages"]
    assert [(m["role"], m["content"]) for m in msgs] == [("user", "edited")]


