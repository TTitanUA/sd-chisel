"""Pure SQL ops over `vec_loras` + `lora_vec_map`.

This module knows nothing about the embedder, the repo, or HTTP — its only
job is to keep the two vector tables consistent with a given (name, vector)
pair under the caller's transaction.
"""
from __future__ import annotations

import sqlite3

import sqlite_vec

from app.services.embedder import EMBEDDING_DIM


class IndexerError(Exception):
    """Raised on shape violations or unexpected SQL state."""


def upsert_lora_vector(
    conn: sqlite3.Connection, *, lora_name: str, vector: list[float],
) -> None:
    """Insert or in-place update the vector for `lora_name`.

    Caller owns the transaction (this function issues no BEGIN/COMMIT).
    """
    if len(vector) != EMBEDDING_DIM:
        raise IndexerError(
            f"vector dim mismatch: got {len(vector)}, want {EMBEDDING_DIM}",
        )
    payload = sqlite_vec.serialize_float32(vector)

    existing = conn.execute(
        "SELECT rowid FROM lora_vec_map WHERE lora_name = ?", (lora_name,),
    ).fetchone()

    if existing is not None:
        conn.execute(
            "UPDATE vec_loras SET embedding = ? WHERE rowid = ?",
            (payload, existing[0]),
        )
        return

    cur = conn.execute(
        "INSERT INTO vec_loras(embedding) VALUES (?)", (payload,),
    )
    new_rowid = cur.lastrowid
    if new_rowid is None:
        raise IndexerError("vec_loras INSERT did not return a rowid")
    conn.execute(
        "INSERT INTO lora_vec_map(lora_name, rowid) VALUES (?, ?)",
        (lora_name, new_rowid),
    )


def delete_lora_vector(conn: sqlite3.Connection, *, lora_name: str) -> None:
    """Remove the vector + mapping for `lora_name`. No-op if not indexed.

    Must run BEFORE the `loras` row is deleted, because the FK cascade would
    drop the `lora_vec_map` row first and we'd lose the rowid we need to
    target `vec_loras`.
    """
    row = conn.execute(
        "SELECT rowid FROM lora_vec_map WHERE lora_name = ?", (lora_name,),
    ).fetchone()
    if row is None:
        return
    conn.execute("DELETE FROM vec_loras WHERE rowid = ?", (row[0],))
    conn.execute("DELETE FROM lora_vec_map WHERE lora_name = ?", (lora_name,))


def is_indexed(conn: sqlite3.Connection, lora_name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM lora_vec_map WHERE lora_name = ?", (lora_name,),
    ).fetchone() is not None
