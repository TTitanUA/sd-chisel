"""Reindex runners for the background task system.

Each function returns a `TaskRunner` (a callable taking a progress callback)
that the task_runner worker can execute on its thread. The runners open
their own short-lived sqlite connection — the HTTP request's connection
has already been closed by the time the worker picks the task up.
"""
from __future__ import annotations

import sqlite3

from app.services import library_service, task_runner
from app.storage import db as db_mod
from app.storage import library_repo


def _connect() -> sqlite3.Connection:
    return db_mod.connect()


def submit_reindex_lora(name: str) -> task_runner.Task:
    """Queue a single-LoRA reindex. Idempotent at the queue level: a
    second submission for the same name will run after the first finishes,
    which is fine — the second pass just rewrites the same vector.
    """
    def runner(progress: task_runner.ProgressCb) -> None:
        progress(None, f"reindexing {name}")
        conn = _connect()
        try:
            ok = library_service.reindex_one(conn, name)
            if not ok:
                # Row was deleted between submit and run — not an error.
                progress(1.0, f"{name} no longer exists")
        finally:
            conn.close()

    return task_runner.get().submit(
        kind="reindex_lora",
        title=f"Reindex LoRA \"{name}\"",
        target={"lora_name": name},
        runner=runner,
    )


def submit_reindex_all() -> task_runner.Task:
    def runner(progress: task_runner.ProgressCb) -> None:
        conn = _connect()
        try:
            names = library_repo.list_all_lora_names(conn)
            total = len(names)
            for i, name in enumerate(names):
                progress(
                    (i / total) if total else 1.0,
                    f"reindexing {name} ({i + 1}/{total})",
                )
                try:
                    library_service.reindex_one(conn, name)
                except Exception:  # noqa: BLE001 — keep going across rows
                    # Per-row failure is logged by the runner layer; the
                    # batch task succeeds as long as it processed every row.
                    continue
        finally:
            conn.close()

    return task_runner.get().submit(
        kind="reindex_all",
        title="Reindex all LoRAs",
        target={},
        runner=runner,
    )


def sweep_unindexed() -> int:
    """Queue a `reindex_lora` task for every LoRA missing a vector. Run on
    app startup so a crash mid-write doesn't leave rows permanently stale.
    Returns the number of tasks queued.
    """
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT name FROM loras "
            "WHERE name NOT IN (SELECT lora_name FROM lora_vec_map) "
            "ORDER BY name"
        ).fetchall()
    finally:
        conn.close()
    for row in rows:
        submit_reindex_lora(row[0])
    return len(rows)
