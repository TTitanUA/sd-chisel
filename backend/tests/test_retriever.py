from __future__ import annotations

from pathlib import Path

import pytest

from app.services import retriever
from app.services.embedder import EMBEDDING_DIM
from app.storage import db as db_mod
from app.storage import library_repo
from app.storage.migrations import apply_pending


@pytest.fixture
def conn(tmp_path):
    c = db_mod.connect(tmp_path / "t.db")
    apply_pending(c, Path(__file__).parent.parent / "migrations")
    yield c
    c.close()


def _make_vector(seed: int) -> list[float]:
    """Deterministic, varied non-zero vector."""
    return [((seed + i) % 7) * 0.01 for i in range(EMBEDDING_DIM)]


def _seed_lora(conn, *, name, family, tags=None, vector_seed=1):
    library_repo.create_lora(
        conn, name=name, display_name=name, description=f"desc {name}",
        tags=tags or [], trigger_words=[], family_id=family,
    )
    from app.services import indexer
    indexer.upsert_lora_vector(conn, lora_name=name, vector=_make_vector(vector_seed))


def test_top_k_returns_at_most_k_with_distance(conn, monkeypatch):
    _seed_lora(conn, name="a", family="sdxl", vector_seed=1)
    _seed_lora(conn, name="b", family="sdxl", vector_seed=2)
    _seed_lora(conn, name="c", family="sdxl", vector_seed=3)

    monkeypatch.setattr(
        "app.services.retriever.embedder.embed",
        lambda text: _make_vector(1),
    )

    hits = retriever.top_k(conn, query="anything", k=2)
    assert len(hits) == 2
    assert all("name" in h and "distance" in h for h in hits)
    assert hits[0]["distance"] <= hits[1]["distance"]


def test_top_k_family_filter_drops_other_families(conn, monkeypatch):
    _seed_lora(conn, name="a", family="sdxl", vector_seed=1)
    _seed_lora(conn, name="b", family="pony", vector_seed=2)

    monkeypatch.setattr(
        "app.services.retriever.embedder.embed",
        lambda text: _make_vector(1),
    )

    hits = retriever.top_k(conn, query="x", k=10, family_id="sdxl")
    assert [h["name"] for h in hits] == ["a"]


def test_top_k_no_loras_returns_empty(conn, monkeypatch):
    monkeypatch.setattr(
        "app.services.retriever.embedder.embed",
        lambda text: _make_vector(1),
    )
    assert retriever.top_k(conn, query="x", k=5) == []


def test_retrieve_for_intents_dedupes_across_intents(conn, monkeypatch):
    _seed_lora(conn, name="a", family="sdxl", vector_seed=1)
    _seed_lora(conn, name="b", family="sdxl", vector_seed=2)

    monkeypatch.setattr(
        "app.services.retriever.embedder.embed",
        lambda text: _make_vector(1),
    )

    intents = [
        {"kind": "style", "query": "x"},
        {"kind": "detail", "query": "y"},
    ]
    bundle = retriever.retrieve_for_intents(conn, intents=intents, k=10)

    # debug payload reports both intents
    assert {h["intent_index"] for h in bundle["per_intent"]} == {0, 1}
    # union deduped on name
    union_names = sorted(c["name"] for c in bundle["candidates"])
    assert union_names == ["a", "b"]


def test_retrieve_for_intents_caps_global_union(conn, monkeypatch):
    for i in range(8):
        _seed_lora(conn, name=f"l{i}", family="sdxl", vector_seed=i + 1)

    monkeypatch.setattr(
        "app.services.retriever.embedder.embed",
        lambda text: _make_vector(1),
    )

    intents = [{"kind": "k", "query": "q"}]
    bundle = retriever.retrieve_for_intents(
        conn, intents=intents, k=10, global_cap=3,
    )
    assert len(bundle["candidates"]) == 3
