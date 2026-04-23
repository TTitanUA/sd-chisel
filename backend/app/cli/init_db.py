"""CLI: apply migrations against ./data/app.db.

Invoke:  python -m app.cli.init_db
         sd-init-db               (via project script entry point)
"""
from __future__ import annotations

from pathlib import Path

from app.storage import db as db_mod
from app.storage.migrations import apply_pending

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def main() -> None:
    conn = db_mod.connect()
    try:
        count = apply_pending(conn, MIGRATIONS_DIR)
        print(f"Applied {count} migration(s). DB at {db_mod.db_path()}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
