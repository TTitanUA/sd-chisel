"""Project-wide pytest fixtures.

The `_fake_embedder` fixture is autouse so NO test ever loads the real
sentence-transformers model. Tests that need to control the embedding value
can re-monkeypatch `app.services.embedder.embed` per-test.
"""
from __future__ import annotations

import hashlib

import pytest

from app.services import embedder


def _deterministic_fake_vector(text: str) -> list[float]:
    """Return a 1024-float vector seeded by `text`. Stable across runs."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    # Cycle the digest until we have 1024 bytes; map each byte to [-1, 1).
    repeats = (1024 // len(digest)) + 1
    stretched = (digest * repeats)[:1024]
    return [(b - 128) / 128.0 for b in stretched]


@pytest.fixture(autouse=True)
def _fake_embedder(monkeypatch):
    monkeypatch.setattr(embedder, "embed", _deterministic_fake_vector)
    yield
    embedder._reset_for_tests()
