from __future__ import annotations

from pathlib import Path

import pytest

from app.services import indexer
from app.storage import db as db_mod
from app.storage import library_repo
from app.storage.migrations import apply_pending


@pytest.fixture
def conn(tmp_path):
    c = db_mod.connect(tmp_path / "indexer.db")
    apply_pending(c, Path(__file__).parent.parent / "migrations")
    yield c
    c.close()


def _make_lora(conn, name="l1") -> None:
    library_repo.create_lora(
        conn, name=name, display_name=name, description="d",
        tags=[], trigger_words=[], family_id="sdxl",
    )


def _vec(seed: int) -> list[float]:
    return [float(seed)] * 1024


def test_upsert_inserts_vector_and_mapping(conn):
    _make_lora(conn, "l1")
    indexer.upsert_lora_vector(conn, lora_name="l1", vector=_vec(1))

    mapping = conn.execute(
        "SELECT rowid FROM lora_vec_map WHERE lora_name = ?", ("l1",),
    ).fetchone()
    assert mapping is not None
    rowid = mapping[0]
    count = conn.execute(
        "SELECT COUNT(*) FROM vec_loras WHERE rowid = ?", (rowid,),
    ).fetchone()[0]
    assert count == 1


def test_upsert_replaces_existing_vector_in_place(conn):
    _make_lora(conn, "l1")
    indexer.upsert_lora_vector(conn, lora_name="l1", vector=_vec(1))
    rowid_before = conn.execute(
        "SELECT rowid FROM lora_vec_map WHERE lora_name = ?", ("l1",),
    ).fetchone()[0]

    indexer.upsert_lora_vector(conn, lora_name="l1", vector=_vec(2))
    mappings = conn.execute(
        "SELECT rowid FROM lora_vec_map WHERE lora_name = ?", ("l1",),
    ).fetchall()
    assert len(mappings) == 1
    assert mappings[0][0] == rowid_before  # same rowid, in-place update


def test_upsert_rejects_wrong_dimension(conn):
    _make_lora(conn, "l1")
    with pytest.raises(indexer.IndexerError):
        indexer.upsert_lora_vector(conn, lora_name="l1", vector=[0.0] * 768)


def test_delete_removes_vector_and_mapping(conn):
    _make_lora(conn, "l1")
    indexer.upsert_lora_vector(conn, lora_name="l1", vector=_vec(1))
    rowid = conn.execute(
        "SELECT rowid FROM lora_vec_map WHERE lora_name = ?", ("l1",),
    ).fetchone()[0]

    indexer.delete_lora_vector(conn, lora_name="l1")
    assert conn.execute(
        "SELECT COUNT(*) FROM lora_vec_map WHERE lora_name = ?", ("l1",),
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM vec_loras WHERE rowid = ?", (rowid,),
    ).fetchone()[0] == 0


def test_delete_is_noop_when_no_vector(conn):
    _make_lora(conn, "l1")
    # never indexed — delete should not raise
    indexer.delete_lora_vector(conn, lora_name="l1")


def test_is_indexed_helper(conn):
    _make_lora(conn, "l1")
    _make_lora(conn, "l2")
    indexer.upsert_lora_vector(conn, lora_name="l1", vector=_vec(1))
    assert indexer.is_indexed(conn, "l1") is True
    assert indexer.is_indexed(conn, "l2") is False
