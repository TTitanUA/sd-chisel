"""Coordinates `library_repo` and `indexer` under one outer transaction.

Every LoRA write goes through this module, never the repo directly. If the
embedder fails for create or update, we ROLLBACK so the database never has a
LoRA row without a matching vector (and vice versa).
"""
from __future__ import annotations

import sqlite3
from typing import Any

from app.services import embedder, indexer
from app.storage import library_repo


def _hydrated_with_index_status(
    conn: sqlite3.Connection, lora: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if lora is None:
        return None
    lora["is_indexed"] = indexer.is_indexed(conn, lora["name"])
    return lora


def _rollback(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("ROLLBACK")
    except sqlite3.OperationalError:
        pass


def create_lora(conn: sqlite3.Connection, **kwargs: Any) -> dict[str, Any]:
    conn.execute("BEGIN")
    try:
        row = library_repo.create_lora(conn, **kwargs)
        vector = embedder.embed(embedder.build_embedding_text(row))
        indexer.upsert_lora_vector(conn, lora_name=row["name"], vector=vector)
        conn.execute("COMMIT")
    except Exception:
        _rollback(conn)
        raise
    return _hydrated_with_index_status(conn, library_repo.get_lora(conn, row["name"]))  # type: ignore[return-value]


def update_lora(
    conn: sqlite3.Connection, name: str, **kwargs: Any,
) -> dict[str, Any] | None:
    conn.execute("BEGIN")
    try:
        updated = library_repo.update_lora(conn, name, **kwargs)
        if updated is None:
            conn.execute("COMMIT")  # nothing to roll back; still a clean exit
            return None
        vector = embedder.embed(embedder.build_embedding_text(updated))
        indexer.upsert_lora_vector(conn, lora_name=name, vector=vector)
        conn.execute("COMMIT")
    except Exception:
        _rollback(conn)
        raise
    return _hydrated_with_index_status(conn, library_repo.get_lora(conn, name))


def delete_lora(conn: sqlite3.Connection, name: str) -> bool:
    conn.execute("BEGIN")
    try:
        # vec_loras must be cleared BEFORE loras row goes away — the FK cascade
        # on lora_vec_map fires on the loras delete and would orphan vec_loras.
        indexer.delete_lora_vector(conn, lora_name=name)
        deleted = library_repo.delete_lora(conn, name)
        conn.execute("COMMIT")
    except Exception:
        _rollback(conn)
        raise
    return deleted


def reindex_one(conn: sqlite3.Connection, name: str) -> bool:
    """Re-embed and replace the vector for an existing LoRA. Used by `reindex-all`.

    Returns True on success, False if the LoRA is missing.
    """
    lora = library_repo.get_lora(conn, name)
    if lora is None:
        return False
    conn.execute("BEGIN")
    try:
        vector = embedder.embed(embedder.build_embedding_text(lora))
        indexer.upsert_lora_vector(conn, lora_name=name, vector=vector)
        conn.execute("COMMIT")
    except Exception:
        _rollback(conn)
        raise
    return True


def get_lora(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    """Read-through for the API layer — adds `is_indexed` to the row."""
    return _hydrated_with_index_status(conn, library_repo.get_lora(conn, name))


def list_loras(
    conn: sqlite3.Connection, *,
    family_id: str | None = None,
    tag: str | None = None,
    q: str | None = None,
) -> list[dict[str, Any]]:
    rows = library_repo.list_loras(conn, family_id=family_id, tag=tag, q=q)
    if not rows:
        return rows
    indexed = {
        r[0] for r in conn.execute(
            "SELECT lora_name FROM lora_vec_map WHERE lora_name IN ("
            + ",".join(["?"] * len(rows)) + ")",
            [row["name"] for row in rows],
        )
    }
    for r in rows:
        r["is_indexed"] = r["name"] in indexed
    return rows
