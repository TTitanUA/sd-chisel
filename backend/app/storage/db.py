from __future__ import annotations

import sqlite3
from pathlib import Path

import sqlite_vec

from app.config import resolve_data_root


def db_path(data_root: Path | None = None) -> Path:
    return (data_root or resolve_data_root()) / "app.db"


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open a connection with WAL, FK on, sqlite-vec loaded.

    Returns a connection with row_factory=sqlite3.Row for dict-like access.
    """
    target = path or db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, isolation_level=None)  # manual transactions
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn
