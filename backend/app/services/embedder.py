"""Lazy wrapper around sentence-transformers `BAAI/bge-m3`.

The module-level `embed(text)` function is the seam every test monkeypatches —
no test code should ever cause sentence-transformers to actually load the model.
"""
from __future__ import annotations

from typing import Any

EMBEDDING_DIM = 1024  # BAAI/bge-m3 — must match `vec_loras` FLOAT[1024]
MODEL_NAME = "BAAI/bge-m3"

_model: Any | None = None


class EmbedderError(Exception):
    """Raised when embedding fails or returns an unexpected shape."""


def build_embedding_text(lora: dict[str, Any]) -> str:
    """Build the canonical text fed to the embedder for a LoRA row.

    Format: ``"<description> | <tag1, tag2, ...> | <trigger1, trigger2, ...>"``.
    `display_name` is intentionally excluded — it duplicates `name` semantically.
    """
    desc = str(lora.get("description") or "")
    tags = ", ".join(str(t) for t in (lora.get("tags") or []))
    triggers = ", ".join(str(t) for t in (lora.get("trigger_words") or []))
    return f"{desc} | {tags} | {triggers}"


def _load_sentence_transformer() -> Any:  # pragma: no cover — heavy I/O
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(MODEL_NAME)


def _get_model() -> Any:
    global _model
    if _model is None:
        _model = _load_sentence_transformer()
    return _model


def _reset_for_tests() -> None:
    global _model
    _model = None


def embed(text: str) -> list[float]:
    """Embed `text` → 1024-dim list of floats. Tests monkeypatch this."""
    model = _get_model()
    raw = model.encode(text, normalize_embeddings=True)
    vec = [float(x) for x in raw]
    if len(vec) != EMBEDDING_DIM:
        raise EmbedderError(
            f"unexpected embedding dim: got {len(vec)}, want {EMBEDDING_DIM}",
        )
    return vec


# Preserved reference to the real implementation so unit tests can restore it
# after the autouse fake-embedder fixture in conftest.py replaces `embed`.
_real_embed = embed
