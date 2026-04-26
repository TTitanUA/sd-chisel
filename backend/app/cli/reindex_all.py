"""CLI: reindex every LoRA into vec_loras + lora_vec_map.

Invoke:  uv run reindex-all
"""
from __future__ import annotations

import sqlite3
import sys

from app.services import embedder, indexer, library_service
from app.storage import db as db_mod
from app.storage import library_repo


def _open_conn() -> sqlite3.Connection:
    return db_mod.connect()


def run(conn: sqlite3.Connection) -> dict:
    names = library_repo.list_all_lora_names(conn)
    indexed = 0
    failed = 0
    errors: list[str] = []
    for name in names:
        try:
            ok = library_service.reindex_one(conn, name)
        except (embedder.EmbedderError, indexer.IndexerError, sqlite3.Error) as exc:
            failed += 1
            errors.append(f"{name}: {exc}")
            print(f"failed: {name} - {exc}", file=sys.stderr)
            continue
        if ok:
            indexed += 1
            print(f"indexed: {name}")
        else:
            failed += 1
            errors.append(f"{name}: row vanished mid-reindex")
    return {
        "indexed": indexed, "failed": failed,
        "total": len(names), "errors": errors,
    }


def main() -> int:
    conn = _open_conn()
    try:
        summary = run(conn)
    finally:
        conn.close()
    print(
        f"indexed={summary['indexed']} "
        f"failed={summary['failed']} "
        f"total={summary['total']}"
    )
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
