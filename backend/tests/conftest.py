"""Project-wide pytest fixtures.

The `_fake_embedder` fixture is autouse so NO test ever loads the real
sentence-transformers model. Tests that need to exercise the real `embed`
body (e.g. unit-testing `_get_model` and dimension validation) opt out via
``@pytest.mark.real_embedder``.
"""
from __future__ import annotations

import hashlib

import pytest

from app.services import embedder


def _deterministic_fake_vector(text: str) -> list[float]:
    """Return a 1024-float vector seeded by `text`. Stable across runs."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    repeats = (1024 // len(digest)) + 1
    stretched = (digest * repeats)[:1024]
    return [(b - 128) / 128.0 for b in stretched]


@pytest.fixture(autouse=True)
def _fake_embedder(monkeypatch, request):
    if "real_embedder" in request.keywords:
        yield
        embedder._reset_for_tests()
        return
    monkeypatch.setattr(embedder, "embed", _deterministic_fake_vector)
    yield
    embedder._reset_for_tests()
