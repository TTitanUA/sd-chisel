from __future__ import annotations

from pathlib import Path

import pytest

from app.services import indexer, library_service
from app.storage import db as db_mod
from app.storage import library_repo
from app.storage.migrations import apply_pending


@pytest.fixture
def conn(tmp_path, seed_default_families):
    c = db_mod.connect(tmp_path / "service.db")
    apply_pending(c, Path(__file__).parent.parent / "migrations")
    seed_default_families(c)
    yield c
    c.close()


CREATE_KW = dict(
    display_name="Cinematic Light",
    description="dramatic rim light",
    tags=["light", "mood"],
    trigger_words=["cinematic"],
    family_id="sdxl",
    recommended_weight=0.8,
)


def test_create_writes_row_without_indexing(conn):
    out = library_service.create_lora(conn, name="cine", **CREATE_KW)
    assert out["name"] == "cine"
    # New contract: create commits the row only — embedding is the
    # background task layer's job. Until reindex runs, is_indexed=False.
    assert out["is_indexed"] is False
    assert indexer.is_indexed(conn, "cine") is False


def test_reindex_one_populates_vector(conn):
    library_service.create_lora(conn, name="cine", **CREATE_KW)
    assert library_service.reindex_one(conn, "cine") is True
    assert indexer.is_indexed(conn, "cine") is True


def test_update_drops_existing_vector(conn):
    library_service.create_lora(conn, name="cine", **CREATE_KW)
    library_service.reindex_one(conn, "cine")
    assert indexer.is_indexed(conn, "cine") is True

    out = library_service.update_lora(
        conn, "cine",
        display_name="Cinematic Light v2",
        description="even more dramatic",
        tags=["light"],
        trigger_words=["cinematic", "drama"],
        family_id="sdxl",
        recommended_weight=0.85,
    )
    assert out is not None
    # Edited row no longer has a fresh vector — retriever must not return
    # stale embeddings. Background task will re-populate.
    assert out["is_indexed"] is False
    assert indexer.is_indexed(conn, "cine") is False


def test_update_returns_none_when_lora_missing(conn):
    out = library_service.update_lora(
        conn, "missing",
        display_name="x", description="x",
        tags=[], trigger_words=[], family_id="sdxl",
        recommended_weight=None,
    )
    assert out is None


def test_delete_removes_row_and_vector_atomically(conn):
    library_service.create_lora(conn, name="cine", **CREATE_KW)
    library_service.reindex_one(conn, "cine")
    assert library_service.delete_lora(conn, "cine") is True
    assert library_repo.get_lora(conn, "cine") is None
    assert indexer.is_indexed(conn, "cine") is False
    assert conn.execute(
        "SELECT COUNT(*) FROM vec_loras "
        "WHERE rowid IN (SELECT rowid FROM lora_vec_map WHERE lora_name = 'cine')",
    ).fetchone()[0] == 0


def test_delete_returns_false_when_missing(conn):
    assert library_service.delete_lora(conn, "missing") is False


def test_rename_lora_preserves_vector(conn):
    library_service.create_lora(conn, name="old_slug", **CREATE_KW)
    library_service.reindex_one(conn, "old_slug")

    out = library_service.rename_lora(conn, "old_slug", "new_slug")
    assert out is not None
    assert out["name"] == "new_slug"
    # Rename doesn't change embedding text — vector survives the rename.
    assert out["is_indexed"] is True

    rows = conn.execute(
        "SELECT rowid FROM lora_vec_map WHERE lora_name = ?", ("new_slug",),
    ).fetchall()
    assert len(rows) == 1


def test_rename_lora_returns_none_when_missing(conn):
    assert library_service.rename_lora(conn, "ghost", "still_ghost") is None
