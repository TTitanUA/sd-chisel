from __future__ import annotations

import pytest

from app.services import embedder


def test_build_embedding_text_joins_description_tags_triggers():
    text = embedder.build_embedding_text({
        "description": "moody portrait",
        "tags": ["portrait", "moody"],
        "trigger_words": ["dramatic light"],
    })
    assert text == "moody portrait | portrait, moody | dramatic light"


def test_build_embedding_text_handles_empty_lists():
    text = embedder.build_embedding_text({
        "description": "x",
        "tags": [],
        "trigger_words": [],
    })
    assert text == "x |  | "


def test_embed_calls_loaded_model_and_returns_list_of_floats(monkeypatch):
    captured: dict[str, object] = {}

    class FakeModel:
        def encode(self, text, normalize_embeddings=False):
            captured["text"] = text
            captured["normalize"] = normalize_embeddings
            return [0.1] * 1024

    # Restore the real embed so this test exercises the actual implementation.
    monkeypatch.setattr(embedder, "embed", embedder._real_embed)
    monkeypatch.setattr(embedder, "_get_model", lambda: FakeModel())
    out = embedder.embed("hello")
    assert isinstance(out, list)
    assert len(out) == 1024
    assert all(isinstance(x, float) for x in out)
    assert captured["text"] == "hello"
    assert captured["normalize"] is True


def test_embed_raises_on_wrong_dimension(monkeypatch):
    class FakeModel:
        def encode(self, text, normalize_embeddings=False):
            return [0.0] * 768

    # Restore the real embed so this test exercises dimension-validation logic.
    monkeypatch.setattr(embedder, "embed", embedder._real_embed)
    monkeypatch.setattr(embedder, "_get_model", lambda: FakeModel())
    with pytest.raises(embedder.EmbedderError):
        embedder.embed("hello")


def test_get_model_lazy_loads_once_and_caches(monkeypatch):
    embedder._reset_for_tests()
    calls = {"n": 0}

    def fake_loader():
        calls["n"] += 1
        return object()

    monkeypatch.setattr(embedder, "_load_sentence_transformer", fake_loader)
    a = embedder._get_model()
    b = embedder._get_model()
    assert a is b
    assert calls["n"] == 1
    embedder._reset_for_tests()
