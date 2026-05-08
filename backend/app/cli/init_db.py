"""CLI: apply migrations against ./data/app.db.

Invoke:  uv run db-init

The same migration sweep also runs at FastAPI startup (see
``app.main.lifespan``), so this CLI is mostly useful for first-time
setup where the user wants to verify the DB before launching uvicorn.
"""
from __future__ import annotations

from app.storage import db as db_mod
from app.storage.migrations import DEFAULT_MIGRATIONS_DIR, apply_pending


def main() -> None:
    conn = db_mod.connect()
    try:
        count = apply_pending(conn, DEFAULT_MIGRATIONS_DIR)
        print(f"Applied {count} migration(s). DB at {db_mod.db_path()}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
