from __future__ import annotations

from pathlib import Path

import pytest

from app.services import embedder, indexer, library_service
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


def test_create_writes_row_and_indexes_in_one_transaction(conn):
    out = library_service.create_lora(conn, name="cine", **CREATE_KW)
    assert out["name"] == "cine"
    assert out["is_indexed"] is True
    assert indexer.is_indexed(conn, "cine") is True


def test_create_rolls_back_when_embedder_fails(conn, monkeypatch):
    def boom(_text):
        raise embedder.EmbedderError("boom")

    monkeypatch.setattr(embedder, "embed", boom)
    with pytest.raises(embedder.EmbedderError):
        library_service.create_lora(conn, name="failrow", **CREATE_KW)
    # Neither the loras row nor any vector survived the failure
    assert library_repo.get_lora(conn, "failrow") is None
    assert indexer.is_indexed(conn, "failrow") is False


def test_update_re_embeds_in_place(conn):
    library_service.create_lora(conn, name="cine", **CREATE_KW)
    rowid_before = conn.execute(
        "SELECT rowid FROM lora_vec_map WHERE lora_name = ?", ("cine",),
    ).fetchone()[0]

    library_service.update_lora(
        conn, "cine",
        display_name="Cinematic Light v2",
        description="even more dramatic",
        tags=["light"],
        trigger_words=["cinematic", "drama"],
        family_id="sdxl",
        recommended_weight=0.85,
    )

    rowid_after = conn.execute(
        "SELECT rowid FROM lora_vec_map WHERE lora_name = ?", ("cine",),
    ).fetchone()[0]
    assert rowid_after == rowid_before


def test_update_rolls_back_when_embedder_fails(conn, monkeypatch):
    library_service.create_lora(conn, name="cine", **CREATE_KW)
    original = library_repo.get_lora(conn, "cine")

    def boom(_text):
        raise embedder.EmbedderError("boom")

    monkeypatch.setattr(embedder, "embed", boom)
    with pytest.raises(embedder.EmbedderError):
        library_service.update_lora(
            conn, "cine",
            display_name="changed",
            description="changed",
            tags=[], trigger_words=[],
            family_id="sdxl", recommended_weight=None,
        )

    after = library_repo.get_lora(conn, "cine")
    assert after["display_name"] == original["display_name"]
    assert after["description"] == original["description"]


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
    assert library_service.delete_lora(conn, "cine") is True
    assert library_repo.get_lora(conn, "cine") is None
    assert indexer.is_indexed(conn, "cine") is False
    assert conn.execute(
        "SELECT COUNT(*) FROM vec_loras "
        "WHERE rowid IN (SELECT rowid FROM lora_vec_map WHERE lora_name = 'cine')",
    ).fetchone()[0] == 0


def test_delete_returns_false_when_missing(conn):
    assert library_service.delete_lora(conn, "missing") is False
