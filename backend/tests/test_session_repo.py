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


def test_create_and_list_projects(conn):
    session_repo.create_project(conn, id="scrapyard", name="Scrapyard")
    session_repo.create_project(conn, id="portraits", name="Portraits")
    ps = session_repo.list_projects(conn)
    assert {p["id"] for p in ps} == {"scrapyard", "portraits"}


def test_create_session_and_append_message(conn):
    session_repo.create_project(conn, id="p1", name="P1")
    session_repo.create_session(conn, id="s1", project_id="p1", name="first")

    session_repo.append_message(conn, session_id="s1", role="user", content="hi")
    session_repo.append_message(conn, session_id="s1", role="assistant", content="hello")
    msgs = session_repo.list_messages(conn, session_id="s1")
    assert [m["role"] for m in msgs] == ["user", "assistant"]


def test_delete_session_cascades_messages(conn):
    session_repo.create_project(conn, id="p1", name="P1")
    session_repo.create_session(conn, id="s1", project_id="p1")
    session_repo.append_message(conn, session_id="s1", role="user", content="x")

    session_repo.delete_session(conn, "s1")

    assert session_repo.get_session(conn, "s1") is None
    assert list(conn.execute("SELECT * FROM messages WHERE session_id='s1'")) == []
