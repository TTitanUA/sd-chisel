"""Top-K LoRA retrieval over sqlite-vec, per intent.

The retriever knows nothing about LLMs or the prompt builder. Given a set of
intents (each a {kind, query} dict), it embeds each query, runs vec_loras
MATCH, joins back to `loras` with an optional family filter, and returns:

- ``per_intent``: a flat list of hits with ``intent_index`` so callers can
  reconstruct which intent produced what (used for the debug payload).
- ``candidates``: the deduplicated union (by ``name``), capped at
  ``global_cap``, sorted by best (smallest) per-name distance.
- ``by_name``: ``dict[str, dict]`` mapping name → full hydrated LoRA row,
  used by the prompt builder to pull descriptions without re-querying.

Family pre-filter is best-effort: sqlite-vec MATCH does not honour external
WHERE clauses, so we over-fetch (k * 4) and filter in the join.
"""
from __future__ import annotations

import sqlite3
from typing import Any

import sqlite_vec

from app.services import embedder
from app.storage import library_repo

OVERFETCH_FACTOR = 4
DEFAULT_GLOBAL_CAP = 20


def top_k(
    conn: sqlite3.Connection,
    *,
    query: str,
    k: int,
    family_id: str | None = None,
) -> list[dict[str, Any]]:
    """Embed `query`, return up to k {name, distance} hits, optionally
    filtered to `family_id`."""
    vec = embedder.embed(query)
    payload = sqlite_vec.serialize_float32(vec)
    fetch_k = max(k * OVERFETCH_FACTOR, k)

    sql = (
        "WITH knn AS ("
        "  SELECT rowid, distance FROM vec_loras "
        "  WHERE embedding MATCH ? AND k = ? "
        "  ORDER BY distance"
        ") "
        "SELECT l.name AS name, knn.distance AS distance "
        "FROM knn "
        "JOIN lora_vec_map m ON m.rowid = knn.rowid "
        "JOIN loras l ON l.name = m.lora_name "
    )
    params: list[Any] = [payload, fetch_k]
    if family_id:
        sql += "WHERE l.family_id = ? "
        params.append(family_id)
    sql += "ORDER BY knn.distance"

    rows = conn.execute(sql, params).fetchall()
    return [{"name": r["name"], "distance": float(r["distance"])} for r in rows[:k]]


def retrieve_for_intents(
    conn: sqlite3.Connection,
    *,
    intents: list[dict[str, Any]],
    k: int,
    family_id: str | None = None,
    global_cap: int = DEFAULT_GLOBAL_CAP,
) -> dict[str, Any]:
    """Run top_k for each intent, dedupe the union by name (keeping the
    smallest distance), cap at ``global_cap``, and return the bundle."""
    flat_hits: list[dict[str, Any]] = []
    best_by_name: dict[str, float] = {}
    for idx, intent in enumerate(intents):
        hits = top_k(conn, query=intent["query"], k=k, family_id=family_id)
        for h in hits:
            flat_hits.append({
                "intent_index": idx,
                "intent_query": intent["query"],
                "name": h["name"],
                "distance": h["distance"],
            })
            prev = best_by_name.get(h["name"])
            if prev is None or h["distance"] < prev:
                best_by_name[h["name"]] = h["distance"]

    ranked = sorted(best_by_name.items(), key=lambda kv: kv[1])[:global_cap]
    candidate_names = [name for name, _ in ranked]
    candidates = library_repo.get_loras_by_names(conn, candidate_names)
    by_name = {c["name"]: c for c in candidates}

    grouped: dict[int, dict[str, Any]] = {}
    for hit in flat_hits:
        bucket = grouped.setdefault(hit["intent_index"], {
            "intent_index": hit["intent_index"],
            "intent_query": hit["intent_query"],
            "results": [],
        })
        bucket["results"].append({"name": hit["name"], "distance": hit["distance"]})
    debug = [grouped[i] for i in sorted(grouped)]

    return {
        "per_intent": debug,
        "candidates": candidates,
        "by_name": by_name,
    }
