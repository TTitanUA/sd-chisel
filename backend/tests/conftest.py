"""Project-wide pytest fixtures.

The `_fake_embedder` fixture is autouse so NO test ever loads the real
sentence-transformers model. Tests that need to exercise the real `embed`
body (e.g. unit-testing `_get_model` and dimension validation) opt out via
``@pytest.mark.real_embedder``.

The `seed_default_families` helper lets tests pre-populate the canonical
10 family ids that production fixtures (models, loras) reference. The app
itself starts with an empty `families` table; this helper exists purely
so legacy tests don't have to create each family inline.
"""
from __future__ import annotations

import hashlib
import sqlite3

import pytest

from app.services import embedder
from app.storage import library_repo


DEFAULT_FAMILY_IDS = (
    "sdxl",
    "illustrious",
    "pony",
    "flux",
    "sd15",
    "sd21",
    "cascade",
    "hunyuan",
    "kolors",
    "auraflow",
)


@pytest.fixture
def seed_default_families():
    """Returns a callable that inserts the 10 canonical family ids on a connection.

    Used by tests that create models/loras with `family_id="sdxl"` etc. The
    production app starts with an empty `families` table — only tests need this.
    """
    def _seed(conn: sqlite3.Connection) -> None:
        for fid in DEFAULT_FAMILY_IDS:
            if library_repo.get_family(conn, fid) is None:
                library_repo.create_family(
                    conn, id=fid, display_name=fid, prompt_guide="",
                )
    return _seed


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
