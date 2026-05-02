from __future__ import annotations

from pathlib import Path

import pytest

from app.storage import db as db_mod
from app.storage import library_repo
from app.storage.migrations import apply_pending


@pytest.fixture
def conn(tmp_path, seed_default_families):
    c = db_mod.connect(tmp_path / "t.db")
    apply_pending(c, Path(__file__).parent.parent / "migrations")
    seed_default_families(c)
    yield c
    c.close()


def _seed(conn, *, name: str, family: str, tags: list[str]) -> None:
    library_repo.create_lora(
        conn,
        name=name,
        display_name=name,
        description=f"desc for {name}",
        tags=tags,
        trigger_words=[],
        family_id=family,
    )


def test_list_distinct_tags_returns_sorted_unique(conn):
    _seed(conn, name="a", family="sdxl", tags=["lighting", "style"])
    _seed(conn, name="b", family="sdxl", tags=["style", "character"])
    assert library_repo.list_distinct_tags(conn) == ["character", "lighting", "style"]


def test_list_distinct_tags_empty_when_no_loras(conn):
    assert library_repo.list_distinct_tags(conn) == []


def test_get_loras_by_names_preserves_input_order(conn):
    _seed(conn, name="a", family="sdxl", tags=[])
    _seed(conn, name="b", family="sdxl", tags=[])
    _seed(conn, name="c", family="sdxl", tags=[])
    rows = library_repo.get_loras_by_names(conn, ["c", "a", "missing", "b"])
    assert [r["name"] for r in rows] == ["c", "a", "b"]
    assert all("description" in r for r in rows)


def test_get_loras_by_names_empty_input_returns_empty(conn):
    assert library_repo.get_loras_by_names(conn, []) == []


def test_list_loras_excludes_hidden_when_include_hidden_false(conn):
    _seed(conn, name="a", family="sdxl", tags=[])
    _seed(conn, name="b", family="sdxl", tags=[])
    library_repo.set_lora_hidden(conn, "b", hidden=True)

    visible = library_repo.list_loras(conn, include_hidden=False)
    assert [r["name"] for r in visible] == ["a"]
    everything = library_repo.list_loras(conn, include_hidden=True)
    assert sorted(r["name"] for r in everything) == ["a", "b"]


def test_get_loras_by_names_excludes_hidden_when_include_hidden_false(conn):
    _seed(conn, name="a", family="sdxl", tags=[])
    _seed(conn, name="b", family="sdxl", tags=[])
    library_repo.set_lora_hidden(conn, "b", hidden=True)

    rows = library_repo.get_loras_by_names(conn, ["a", "b"], include_hidden=False)
    assert [r["name"] for r in rows] == ["a"]


def test_list_distinct_tags_excludes_hidden_when_include_hidden_false(conn):
    _seed(conn, name="a", family="sdxl", tags=["lighting"])
    _seed(conn, name="b", family="sdxl", tags=["nsfw"])
    library_repo.set_lora_hidden(conn, "b", hidden=True)

    assert library_repo.list_distinct_tags(conn, include_hidden=False) == ["lighting"]
    assert library_repo.list_distinct_tags(conn, include_hidden=True) == ["lighting", "nsfw"]
