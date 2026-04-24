from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from app.storage.db import connect


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
