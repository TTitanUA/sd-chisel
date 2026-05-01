from pathlib import Path

import pytest

from app.storage import db as db_mod
from app.storage import session_repo, source_image_repo
from app.storage.migrations import apply_pending


@pytest.fixture
def conn(tmp_path, seed_default_families):
    c = db_mod.connect(tmp_path / "t.db")
    apply_pending(c, Path(__file__).parent.parent / "migrations")
    seed_default_families(c)
    yield c
    c.close()


def _new_session(conn) -> str:
    p = session_repo.create_project(conn, name="P")
    return session_repo.create_session(conn, project_id=p["id"])["id"]


def test_insert_lists_in_main_first_then_creation_order(conn):
    sid = _new_session(conn)
    a = source_image_repo.insert(
        conn, session_id=sid, path="images/x/sources/a.png",
        original_filename="a.png", is_main=False,
    )
    b = source_image_repo.insert(
        conn, session_id=sid, path="images/x/sources/b.png",
        original_filename="b.png", is_main=True,
    )
    c = source_image_repo.insert(
        conn, session_id=sid, path="images/x/sources/c.png",
        original_filename="c.png", is_main=False,
    )

    listing = source_image_repo.list_for_session(conn, sid)
    assert [r["id"] for r in listing] == [b["id"], a["id"], c["id"]]


def test_set_main_keeps_uniqueness(conn):
    sid = _new_session(conn)
    a = source_image_repo.insert(
        conn, session_id=sid, path="p/a", original_filename="a", is_main=True,
    )
    b = source_image_repo.insert(
        conn, session_id=sid, path="p/b", original_filename="b", is_main=False,
    )
    source_image_repo.set_main(conn, session_id=sid, image_id=b["id"])

    refreshed = {r["id"]: r for r in source_image_repo.list_for_session(conn, sid)}
    assert refreshed[a["id"]]["is_main"] is False
    assert refreshed[b["id"]]["is_main"] is True


def test_promote_first_remaining_picks_oldest(conn):
    sid = _new_session(conn)
    a = source_image_repo.insert(
        conn, session_id=sid, path="p/a", original_filename="a", is_main=True,
    )
    b = source_image_repo.insert(
        conn, session_id=sid, path="p/b", original_filename="b", is_main=False,
    )
    source_image_repo.insert(
        conn, session_id=sid, path="p/c", original_filename="c", is_main=False,
    )
    source_image_repo.delete(conn, a["id"])
    promoted = source_image_repo.promote_first_remaining(conn, sid)
    assert promoted is not None
    assert promoted["id"] == b["id"]
    assert promoted["is_main"] is True
    listing = source_image_repo.list_for_session(conn, sid)
    assert len(listing) == 2


def test_promote_no_op_when_main_present(conn):
    sid = _new_session(conn)
    source_image_repo.insert(
        conn, session_id=sid, path="p/a", original_filename="a", is_main=True,
    )
    assert source_image_repo.promote_first_remaining(conn, sid) is None


def test_set_analysis_stores_text_and_prompt(conn):
    sid = _new_session(conn)
    img = source_image_repo.insert(
        conn, session_id=sid, path="p/a", original_filename="a", is_main=True,
    )
    updated = source_image_repo.set_analysis(
        conn, img["id"], analysis="moody", refining_prompt="zoom in",
    )
    assert updated["analysis"] == "moody"
    assert updated["analysis_prompt"] == "zoom in"


def test_delete_session_cascades_source_images(conn):
    sid = _new_session(conn)
    source_image_repo.insert(
        conn, session_id=sid, path="p/a", original_filename="a", is_main=True,
    )
    session_repo.delete_session(conn, sid)
    assert source_image_repo.list_for_session(conn, sid) == []
