from pathlib import Path

import pytest

from app.storage import db as db_mod
from app.storage import library_repo, session_repo
from app.storage.migrations import apply_pending


@pytest.fixture
def conn(tmp_path, seed_default_families):
    c = db_mod.connect(tmp_path / "t.db")
    apply_pending(c, Path(__file__).parent.parent / "migrations")
    seed_default_families(c)
    yield c
    c.close()


def test_project_ids_are_generated(conn):
    p1 = session_repo.create_project(conn, name="Scrapyard")
    p2 = session_repo.create_project(conn, name="Portraits")
    assert p1["id"] != p2["id"]
    assert len(p1["id"]) == 10


def test_list_projects_carries_session_count(conn):
    p = session_repo.create_project(conn, name="P")
    session_repo.create_session(conn, project_id=p["id"], name="s1")
    session_repo.create_session(conn, project_id=p["id"], name="s2")
    rows = session_repo.list_projects(conn)
    assert rows[0]["id"] == p["id"]
    assert rows[0]["session_count"] == 2


def test_update_and_delete_project(conn):
    p = session_repo.create_project(conn, name="Old")
    updated = session_repo.update_project(conn, p["id"], name="New")
    assert updated["name"] == "New"
    assert session_repo.delete_project(conn, p["id"]) is True
    assert session_repo.get_project(conn, p["id"]) is None
    assert session_repo.delete_project(conn, p["id"]) is False


def test_delete_project_cascades_sessions_and_returns_ids(conn):
    p = session_repo.create_project(conn, name="P")
    s1 = session_repo.create_session(conn, project_id=p["id"])
    s2 = session_repo.create_session(conn, project_id=p["id"])
    cascaded = session_repo.delete_project_and_collect_sessions(conn, p["id"])
    assert set(cascaded) == {s1["id"], s2["id"]}
    assert session_repo.get_session(conn, s1["id"]) is None


def test_session_create_defaults_and_update(conn):
    p = session_repo.create_project(conn, name="P")
    s = session_repo.create_session(conn, project_id=p["id"])
    assert s["use_negative"] is True
    assert s["name"] is None

    updated = session_repo.update_session(
        conn,
        s["id"],
        name="renamed",
        model_name=None,
        use_negative=False,
    )
    assert updated["name"] == "renamed"
    assert updated["model_name"] is None
    assert updated["use_negative"] is False
    assert updated["updated_at"] >= s["updated_at"]


def test_update_session_missing_returns_none(conn):
    assert session_repo.update_session(
        conn, "nope", name=None, model_name=None, use_negative=True,
    ) is None


def test_pinned_loras_replace_semantics(conn):
    library_repo.create_lora(
        conn, name="a", display_name="A", description="x",
        tags=[], trigger_words=[], family_id="sdxl",
    )
    library_repo.create_lora(
        conn, name="b", display_name="B", description="x",
        tags=[], trigger_words=[], family_id="sdxl",
    )
    p = session_repo.create_project(conn, name="P")
    s = session_repo.create_session(conn, project_id=p["id"])

    session_repo.set_pinned_loras(
        conn, s["id"], [{"lora_name": "a", "weight_override": None},
                         {"lora_name": "b", "weight_override": 0.5}],
    )
    rows = session_repo.list_pinned_loras(conn, s["id"])
    assert {r["lora_name"] for r in rows} == {"a", "b"}
    assert next(r for r in rows if r["lora_name"] == "b")["weight_override"] == 0.5

    session_repo.set_pinned_loras(
        conn, s["id"], [{"lora_name": "a", "weight_override": 0.9}],
    )
    rows = session_repo.list_pinned_loras(conn, s["id"])
    assert [r["lora_name"] for r in rows] == ["a"]
    assert rows[0]["weight_override"] == 0.9


def test_source_image_set_and_clear(conn):
    p = session_repo.create_project(conn, name="P")
    s = session_repo.create_session(conn, project_id=p["id"])
    session_repo.set_source_image(conn, s["id"], "images/xyz/source.png")
    assert session_repo.get_session(conn, s["id"])["source_image_path"] == "images/xyz/source.png"
    session_repo.clear_source_image(conn, s["id"])
    assert session_repo.get_session(conn, s["id"])["source_image_path"] is None


def test_get_session_with_pinned_hydrates_list(conn):
    library_repo.create_lora(
        conn, name="a", display_name="A", description="x",
        tags=[], trigger_words=[], family_id="sdxl",
    )
    p = session_repo.create_project(conn, name="P")
    s = session_repo.create_session(conn, project_id=p["id"])
    session_repo.set_pinned_loras(
        conn, s["id"], [{"lora_name": "a", "weight_override": 0.8}],
    )

    full = session_repo.get_session_with_pinned(conn, s["id"])
    assert full["pinned_loras"] == [{"lora_name": "a", "weight_override": 0.8}]


def test_create_session_and_append_message(conn):
    p = session_repo.create_project(conn, name="P1")
    s = session_repo.create_session(conn, project_id=p["id"], name="first")

    session_repo.append_message(conn, session_id=s["id"], role="user", content="hi")
    session_repo.append_message(conn, session_id=s["id"], role="assistant", content="hello")
    msgs = session_repo.list_messages(conn, session_id=s["id"])
    assert [m["role"] for m in msgs] == ["user", "assistant"]


def test_delete_session_cascades_messages(conn):
    p = session_repo.create_project(conn, name="P1")
    s = session_repo.create_session(conn, project_id=p["id"])
    session_repo.append_message(conn, session_id=s["id"], role="user", content="x")

    session_repo.delete_session(conn, s["id"])

    assert session_repo.get_session(conn, s["id"]) is None
    assert list(conn.execute("SELECT * FROM messages WHERE session_id=?", (s["id"],))) == []


def test_update_session_persists_model_picks(conn):
    pid = session_repo.create_project(conn, name="P")["id"]
    sid = session_repo.create_session(conn, project_id=pid)["id"]

    session_repo.update_session(
        conn,
        sid,
        name=None,
        model_name=None,
        use_negative=True,
        vl_model_name="qwen2-vl-7b-instruct",
        prompt_model_name="mistral-nemo-12b",
    )

    fetched = session_repo.get_session_with_pinned(conn, sid)
    assert fetched["vl_model_name"] == "qwen2-vl-7b-instruct"
    assert fetched["prompt_model_name"] == "mistral-nemo-12b"


def test_update_session_can_clear_model_picks(conn):
    pid = session_repo.create_project(conn, name="P")["id"]
    sid = session_repo.create_session(conn, project_id=pid)["id"]
    session_repo.update_session(
        conn, sid, name=None, model_name=None, use_negative=True,
        vl_model_name="m", prompt_model_name="m",
    )
    session_repo.update_session(
        conn, sid, name=None, model_name=None, use_negative=True,
        vl_model_name=None, prompt_model_name=None,
    )
    after = session_repo.get_session_with_pinned(conn, sid)
    assert after["vl_model_name"] is None
    assert after["prompt_model_name"] is None


def test_set_vl_summary_persists_and_bumps_updated_at(conn):
    pid = session_repo.create_project(conn, name="P")["id"]
    created = session_repo.create_session(conn, project_id=pid)
    sid = created["id"]

    session_repo.set_vl_summary(conn, sid, "moody portrait")
    after = session_repo.get_session_with_pinned(conn, sid)
    assert after["vl_summary"] == "moody portrait"
    assert after["updated_at"] >= created["updated_at"]
