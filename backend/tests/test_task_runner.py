from __future__ import annotations

import asyncio
import time

import pytest

from app.services import task_runner
from app.services.task_runner import TaskRegistry


@pytest.fixture(autouse=True)
def _no_global_leak():
    """Tests use isolated registries; never touch the module-level slot."""
    yield
    task_runner._install_for_tests(None)


def _run(coro):
    return asyncio.run(coro)


def test_submit_runs_task_to_completion():
    async def go():
        reg = TaskRegistry()
        reg.start()
        try:
            seen: list[float | None] = []

            def runner(progress):
                progress(0.5, "halfway")
                seen.append(0.5)

            task = reg.submit(
                kind="reindex_lora",
                title="reindex foo",
                target={"lora_name": "foo"},
                runner=runner,
            )

            await reg.wait_idle()
            final = reg.get(task.id)
            assert final is not None
            assert final.status == "done"
            assert final.progress == 1.0
            assert final.finished_at is not None
            assert seen == [0.5]
        finally:
            await reg.stop()

    _run(go())


def test_failure_records_error():
    async def go():
        reg = TaskRegistry()
        reg.start()
        try:
            def runner(progress):
                raise RuntimeError("kaboom")

            task = reg.submit(
                kind="reindex_lora",
                title="reindex bad",
                target={"lora_name": "bad"},
                runner=runner,
            )

            await reg.wait_idle()
            final = reg.get(task.id)
            assert final is not None
            assert final.status == "failed"
            assert final.error == "kaboom"
            assert final.finished_at is not None
        finally:
            await reg.stop()

    _run(go())


def test_subscribers_receive_lifecycle_events():
    async def go():
        reg = TaskRegistry()
        reg.start()
        try:
            sub = reg.subscribe()

            def runner(progress):
                progress(0.25, "step1")

            reg.submit(
                kind="reindex_lora",
                title="t",
                target={"lora_name": "x"},
                runner=runner,
            )

            events = await task_runner.collect_events(sub, count=4)
            types = [e.type for e in events]
            statuses = [e.task.status for e in events]
            assert types == ["added", "updated", "updated", "updated"]
            assert statuses[0] == "queued"
            assert statuses[-1] == "done"
        finally:
            await reg.stop()

    _run(go())


def test_active_only_filter():
    async def go():
        reg = TaskRegistry()
        reg.start()
        try:
            started = asyncio.Event()
            release = asyncio.Event()
            loop = asyncio.get_running_loop()

            def slow(progress):
                loop.call_soon_threadsafe(started.set)
                while True:
                    if release.is_set():
                        return
                    time.sleep(0.01)

            reg.submit(
                kind="reindex_lora",
                title="slow",
                target={"lora_name": "slow"},
                runner=slow,
            )

            await asyncio.wait_for(started.wait(), timeout=1.0)

            active = reg.list(active_only=True)
            assert len(active) == 1
            assert active[0].status == "running"

            release.set()
            await reg.wait_idle()

            active_after = reg.list(active_only=True)
            assert active_after == []
            all_after = reg.list()
            assert len(all_after) == 1
            assert all_after[0].status == "done"
        finally:
            await reg.stop()

    _run(go())


def test_find_active_predicate():
    async def go():
        reg = TaskRegistry()
        reg.start()
        try:
            started = asyncio.Event()
            release = asyncio.Event()
            loop = asyncio.get_running_loop()

            def gated(progress):
                loop.call_soon_threadsafe(started.set)
                while not release.is_set():
                    time.sleep(0.01)

            def fast(progress):
                pass

            reg.submit(
                kind="reindex_lora", title="A",
                target={"lora_name": "alpha"}, runner=gated,
            )
            reg.submit(
                kind="reindex_lora", title="B",
                target={"lora_name": "beta"}, runner=fast,
            )

            await asyncio.wait_for(started.wait(), timeout=1.0)
            # A is running (matches predicate), B is queued (also matches).
            active_for_alpha = reg.find_active(
                lambda t: t.target.get("lora_name") == "alpha",
            )
            assert len(active_for_alpha) == 1
            active_total = reg.find_active(lambda t: True)
            assert len(active_total) == 2

            release.set()
            await reg.wait_idle()
            assert reg.find_active(lambda t: True) == []
        finally:
            await reg.stop()

    _run(go())


def test_module_install_get_roundtrip():
    reg = TaskRegistry()
    task_runner.install(reg)
    assert task_runner.get() is reg
    task_runner._install_for_tests(None)
    with pytest.raises(RuntimeError):
        task_runner.get()


def test_tasks_run_sequentially():
    """Single-worker invariant: second task does not start before first ends."""
    async def go():
        reg = TaskRegistry()
        reg.start()
        try:
            order: list[str] = []
            started_a = asyncio.Event()
            release_a = asyncio.Event()
            loop = asyncio.get_running_loop()

            def a(progress):
                order.append("a-start")
                loop.call_soon_threadsafe(started_a.set)
                while not release_a.is_set():
                    time.sleep(0.01)
                order.append("a-end")

            def b(progress):
                order.append("b-start")
                order.append("b-end")

            reg.submit(kind="reindex_lora", title="a", target={}, runner=a)
            reg.submit(kind="reindex_lora", title="b", target={}, runner=b)

            await asyncio.wait_for(started_a.wait(), timeout=1.0)
            assert "b-start" not in order
            release_a.set()
            await reg.wait_idle()
            assert order == ["a-start", "a-end", "b-start", "b-end"]
        finally:
            await reg.stop()

    _run(go())
