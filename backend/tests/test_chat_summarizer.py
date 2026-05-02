from __future__ import annotations

from pathlib import Path

import pytest

from app.services import chat_summarizer, lmstudio_client
from app.storage import db as db_mod
from app.storage import session_repo, source_image_repo
from app.storage.migrations import apply_pending


@pytest.fixture
def conn(tmp_path):
    c = db_mod.connect(tmp_path / "s.db")
    apply_pending(c, Path(__file__).parent.parent / "migrations")
    yield c
    c.close()


def _make_session(conn, *, session_type: str = "i2i") -> str:
    proj = session_repo.create_project(conn, name="p")
    sess = session_repo.create_session(
        conn, project_id=proj["id"], session_type=session_type, name="s",
    )
    return sess["id"]


def test_summarize_passes_mode_main_image_and_chat_history(conn, monkeypatch):
    sid = _make_session(conn, session_type="i2i")
    img = source_image_repo.insert(
        conn, session_id=sid, path=f"images/{sid}/sources/m.png",
        original_filename="m.png", is_main=True,
    )
    source_image_repo.set_analysis(
        conn, img["id"], analysis="moody portrait", refining_prompt=None,
    )
    session_repo.append_message(conn, session_id=sid, role="user", content="more contrast")
    session_repo.append_message(
        conn, session_id=sid, role="assistant", content="ok, dramatic light",
    )

    captured: dict = {}

    def fake_complete(*, endpoint, model, messages, **_):
        captured["model"] = model
        captured["messages"] = messages
        return "## Goal\nMoody portrait with dramatic high-contrast lighting."

    monkeypatch.setattr(lmstudio_client, "chat_complete", fake_complete)

    out = chat_summarizer.summarize_session_chat(
        conn, session_id=sid, endpoint={"server_root": "http://h"},
        prompt_model="pm",
    )
    assert out == "## Goal\nMoody portrait with dramatic high-contrast lighting."
    assert captured["model"] == "pm"
    user_msg = captured["messages"][-1]["content"]
    assert "# Session mode\ni2i" in user_msg
    assert "moody portrait" in user_msg
    assert "more contrast" in user_msg
    assert "dramatic light" in user_msg


def test_summarize_system_prompt_is_model_agnostic(conn, monkeypatch):
    """The brief generation must not lean on a specific diffusion-model
    family or syntax — that belongs further down the pipeline
    (orchestrator + family prompt guides). 'image-to-image' /
    'text-to-image' are allowed because they describe the session
    mode, not a model family."""
    sid = _make_session(conn)
    captured: dict = {}

    def fake_complete(*, endpoint, model, messages, **_):
        captured["sys"] = messages[0]["content"]
        return "## Goal\nok"

    monkeypatch.setattr(lmstudio_client, "chat_complete", fake_complete)
    chat_summarizer.summarize_session_chat(
        conn, session_id=sid, endpoint={"server_root": "http://h"},
        prompt_model="pm",
    )
    sys_lower = captured["sys"].lower()
    for banned in ("stable diffusion", "sdxl", "flux", "pony", "automatic1111", "comfyui"):
        assert banned not in sys_lower, f"{banned!r} leaked into system prompt"
    assert "model-agnostic" in sys_lower


def test_summarize_does_not_use_response_format(conn, monkeypatch):
    """We deliberately ask for plain markdown, not a JSON schema —
    structured-output schemas are unreliable on small local models."""
    sid = _make_session(conn)
    captured: dict = {}

    def fake_complete(*, endpoint, model, messages, response_format=None, **_):
        captured["response_format"] = response_format
        return "## Goal\nok"

    monkeypatch.setattr(lmstudio_client, "chat_complete", fake_complete)
    chat_summarizer.summarize_session_chat(
        conn, session_id=sid, endpoint={"server_root": "http://h"},
        prompt_model="pm",
    )
    assert captured["response_format"] is None


def test_summarize_returns_markdown_with_constraints(conn, monkeypatch):
    sid = _make_session(conn)
    img = source_image_repo.insert(
        conn, session_id=sid, path=f"images/{sid}/sources/m.png",
        original_filename="m.png", is_main=True,
    )
    source_image_repo.set_analysis(
        conn, img["id"], analysis="cat photo", refining_prompt=None,
    )
    session_repo.append_message(
        conn, session_id=sid, role="user", content="don't use HighResolution9B",
    )

    monkeypatch.setattr(
        lmstudio_client, "chat_complete",
        lambda **_: (
            "## Goal\nCat photo reframe.\n\n"
            "## Constraints\n- do not use HighResolution9B"
        ),
    )

    out = chat_summarizer.summarize_session_chat(
        conn, session_id=sid, endpoint={"server_root": "http://h"},
        prompt_model="pm",
    )
    assert "## Goal" in out
    assert "Cat photo reframe." in out
    assert "## Constraints" in out
    assert "HighResolution9B" in out


def test_summarize_handles_empty_chat(conn, monkeypatch):
    sid = _make_session(conn)
    img = source_image_repo.insert(
        conn, session_id=sid, path=f"images/{sid}/sources/m.png",
        original_filename="m.png", is_main=True,
    )
    source_image_repo.set_analysis(
        conn, img["id"], analysis="cat photo", refining_prompt=None,
    )

    captured: dict = {}

    def fake_complete(*, endpoint, model, messages, **_):
        captured["messages"] = messages
        return "## Goal\nReframe of the cat photo."

    monkeypatch.setattr(lmstudio_client, "chat_complete", fake_complete)
    chat_summarizer.summarize_session_chat(
        conn, session_id=sid, endpoint={"server_root": "http://h"},
        prompt_model="pm",
    )
    user_msg = captured["messages"][-1]["content"]
    assert "(no chat yet)" in user_msg
    assert "cat photo" in user_msg


def test_summarize_passes_t2i_mode(conn, monkeypatch):
    sid = _make_session(conn, session_type="t2i")
    captured: dict = {}

    def fake_complete(*, endpoint, model, messages, **_):
        captured["sys"] = messages[0]["content"]
        captured["user"] = messages[-1]["content"]
        return "## Goal\nok"

    monkeypatch.setattr(lmstudio_client, "chat_complete", fake_complete)
    chat_summarizer.summarize_session_chat(
        conn, session_id=sid, endpoint={"server_root": "http://h"},
        prompt_model="pm",
    )
    # Mode flows to the model via the user message, not the system prompt.
    assert "# Session mode\nt2i" in captured["user"]


def test_compact_messages_with_summary_replaces_history(conn):
    sid = _make_session(conn)
    session_repo.append_message(conn, session_id=sid, role="user", content="a")
    session_repo.append_message(conn, session_id=sid, role="assistant", content="b")
    session_repo.append_message(conn, session_id=sid, role="user", content="c")

    row = session_repo.compact_messages_with_summary(
        conn, session_id=sid, brief="moody portrait, dramatic light",
    )
    assert row["role"] == "assistant"
    assert row["content"].startswith("Summary of previous discussion:")
    assert "moody portrait" in row["content"]

    msgs = session_repo.list_messages(conn, session_id=sid)
    assert len(msgs) == 1
    assert msgs[0]["id"] == row["id"]
