from __future__ import annotations

from pathlib import Path

import pytest

from app.cli import reindex_all
from app.services import embedder, indexer
from app.storage import db as db_mod
from app.storage import library_repo
from app.storage.migrations import apply_pending


@pytest.fixture
def conn(tmp_path):
    c = db_mod.connect(tmp_path / "rx.db")
    apply_pending(c, Path(__file__).parent.parent / "migrations")
    yield c
    c.close()


def _seed(conn, name: str) -> None:
    library_repo.create_lora(
        conn, name=name, display_name=name, description=f"d-{name}",
        tags=[], trigger_words=[], family_id="sdxl",
    )


def test_run_reindex_indexes_every_lora(conn):
    _seed(conn, "a")
    _seed(conn, "b")
    summary = reindex_all.run(conn)
    assert summary == {"indexed": 2, "failed": 0, "total": 2, "errors": []}
    assert indexer.is_indexed(conn, "a")
    assert indexer.is_indexed(conn, "b")


def test_run_reindex_replaces_existing_vectors_in_place(conn):
    _seed(conn, "a")
    # Initial index, then re-run — rowid stays the same
    reindex_all.run(conn)
    rowid_before = conn.execute(
        "SELECT rowid FROM lora_vec_map WHERE lora_name = 'a'",
    ).fetchone()[0]

    reindex_all.run(conn)
    rowid_after = conn.execute(
        "SELECT rowid FROM lora_vec_map WHERE lora_name = 'a'",
    ).fetchone()[0]
    assert rowid_after == rowid_before


def test_run_reindex_records_failures_and_continues(conn, monkeypatch):
    _seed(conn, "ok")
    _seed(conn, "bad")

    def selective(text):
        if "bad" in text:
            raise embedder.EmbedderError("nope")
        return [0.0] * 1024

    monkeypatch.setattr(embedder, "embed", selective)

    summary = reindex_all.run(conn)
    assert summary["indexed"] == 1
    assert summary["failed"] == 1
    assert summary["total"] == 2
    assert any("bad" in e for e in summary["errors"])
    assert indexer.is_indexed(conn, "ok") is True
    assert indexer.is_indexed(conn, "bad") is False


def test_main_exits_zero_on_full_success(conn, monkeypatch, capsys):
    _seed(conn, "a")
    monkeypatch.setattr(reindex_all, "_open_conn", lambda: conn)
    rc = reindex_all.main()
    assert rc == 0
    captured = capsys.readouterr()
    assert "indexed=1" in captured.out
    assert "failed=0" in captured.out


def test_main_exits_one_when_any_failed(conn, monkeypatch, capsys):
    _seed(conn, "bad")
    monkeypatch.setattr(reindex_all, "_open_conn", lambda: conn)

    def boom(_text):
        raise embedder.EmbedderError("nope")

    monkeypatch.setattr(embedder, "embed", boom)
    rc = reindex_all.main()
    assert rc == 1
    captured = capsys.readouterr()
    assert "failed=1" in captured.out
