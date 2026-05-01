"""Integration tests for the actual async reindex path.

`test_library_api.py` patches `submit_reindex_lora` to a synchronous
fixture so existing assertions on `is_indexed` are stable. These tests
exercise the real path: a real `TaskRegistry`, a real worker thread, and
a runner that opens its own connection.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.services import library_service, lora_reindex, task_runner
from app.storage import db as db_mod
from app.storage.migrations import apply_pending


@pytest.fixture(autouse=True)
def _no_global_leak():
    yield
    task_runner._install_for_tests(None)


@pytest.fixture
def patched_db(tmp_path, seed_default_families, monkeypatch):
    db_path = tmp_path / "reindex.db"
    monkeypatch.setattr(db_mod, "db_path", lambda *a, **kw: db_path)
    c = db_mod.connect(db_path)
    apply_pending(c, Path(__file__).parent.parent / "migrations")
    seed_default_families(c)
    yield c
    c.close()


def _run(coro):
    return asyncio.run(coro)


def test_submit_reindex_lora_runs_async(patched_db):
    async def go():
        reg = task_runner.TaskRegistry()
        reg.start()
        task_runner.install(reg)
        try:
            # Row exists, no vector yet — mimics post-create state.
            library_service.create_lora(
                patched_db,
                name="cine",
                display_name="Cinematic",
                description="dramatic light",
                tags=["light"],
                trigger_words=["cine"],
                family_id="sdxl",
                recommended_weight=0.7,
            )
            assert library_service.get_lora(patched_db, "cine")["is_indexed"] is False

            task = lora_reindex.submit_reindex_lora("cine")
            assert task.kind == "reindex_lora"
            assert task.target == {"lora_name": "cine"}

            await reg.wait_idle()
            final = reg.get(task.id)
            assert final is not None
            assert final.status == "done"
            assert library_service.get_lora(patched_db, "cine")["is_indexed"] is True
        finally:
            await reg.stop()

    _run(go())


def test_sweep_unindexed_queues_missing_rows(patched_db):
    async def go():
        reg = task_runner.TaskRegistry()
        reg.start()
        task_runner.install(reg)
        try:
            for n in ("a", "b", "c"):
                library_service.create_lora(
                    patched_db, name=n,
                    display_name=n, description=f"desc {n}",
                    tags=[], trigger_words=[],
                    family_id="sdxl", recommended_weight=None,
                )
            count = lora_reindex.sweep_unindexed()
            assert count == 3
            await reg.wait_idle()
            for n in ("a", "b", "c"):
                assert library_service.get_lora(patched_db, n)["is_indexed"] is True
        finally:
            await reg.stop()

    _run(go())
