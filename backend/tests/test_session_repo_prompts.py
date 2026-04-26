from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.storage import db as db_mod
from app.storage import session_repo
from app.storage.migrations import apply_pending


@pytest.fixture
def conn(tmp_path):
    c = db_mod.connect(tmp_path / "t.db")
    apply_pending(c, Path(__file__).parent.parent / "migrations")
    yield c
    c.close()


def _bootstrap_session(conn) -> str:
    proj = session_repo.create_project(conn, name="p")
    sess = session_repo.create_session(conn, project_id=proj["id"], name="s")
    return sess["id"]


def test_append_prompt_round_trips_full_payload(conn):
    sid = _bootstrap_session(conn)
    row = session_repo.append_prompt(
        conn,
        session_id=sid,
        positive="a moody girl, dramatic",
        negative="blurry, lowres",
        loras=[{"name": "noir-v2", "weight": 0.6}],
        intents=[{"kind": "style", "query": "moody anime"}],
        retrieved=[{
            "intent_index": 0, "intent_query": "moody anime",
            "results": [{"name": "noir-v2", "distance": 0.1}],
        }],
    )
    assert row["id"] > 0
    assert row["positive"] == "a moody girl, dramatic"
    assert row["negative"] == "blurry, lowres"
    assert json.loads(row["loras_json"]) == [{"name": "noir-v2", "weight": 0.6}]
    assert json.loads(row["intents_json"]) == [{"kind": "style", "query": "moody anime"}]
    assert json.loads(row["retrieved_loras_json"])[0]["intent_index"] == 0
    assert isinstance(row["created_at"], int)


def test_append_prompt_accepts_negative_none(conn):
    sid = _bootstrap_session(conn)
    row = session_repo.append_prompt(
        conn,
        session_id=sid,
        positive="x",
        negative=None,
        loras=[],
        intents=None,
        retrieved=None,
    )
    assert row["negative"] is None
    assert row["intents_json"] is None
    assert row["retrieved_loras_json"] is None
    assert json.loads(row["loras_json"]) == []


def test_list_prompts_returns_newest_first(conn):
    sid = _bootstrap_session(conn)
    a = session_repo.append_prompt(
        conn, session_id=sid, positive="a", negative=None,
        loras=[], intents=None, retrieved=None,
    )
    b = session_repo.append_prompt(
        conn, session_id=sid, positive="b", negative=None,
        loras=[], intents=None, retrieved=None,
    )
    rows = session_repo.list_prompts(conn, session_id=sid)
    assert [r["id"] for r in rows] == [b["id"], a["id"]]


def test_list_prompts_empty_for_unknown_session(conn):
    # Need a conn with at least one project so DB is initialized — empty result is the assertion
    assert session_repo.list_prompts(conn, session_id="nope") == []
