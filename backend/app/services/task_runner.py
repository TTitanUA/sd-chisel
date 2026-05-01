"""In-process background task registry + single-worker queue.

The registry is the single source of truth for "what's running in the
background right now". HTTP layer reads it for the `/api/tasks` endpoints
and the SSE stream; library writes submit reindex jobs through it.

Design:
- One `TaskRegistry` instance per FastAPI app (created in `lifespan`).
- One worker coroutine drains an `asyncio.Queue` and runs each task's
  blocking callable via `asyncio.to_thread` (sentence-transformers is
  CPU/GPU bound — no point parallelising).
- Subscribers (SSE) attach via `subscribe()` and receive every status
  transition as a `TaskEvent`.

Persistence is intentionally absent. Restart loses task history; the
backend's startup sweep re-queues anything still missing a vector.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any, Literal

logger = logging.getLogger(__name__)

TaskKind = Literal[
    "reindex_lora",
    "reindex_all",
    "civitai_import",
]
TaskStatus = Literal["queued", "running", "done", "failed", "cancelled"]


# Runner signature: receives a `progress` callback to report (fraction, message).
# Returns nothing meaningful; raise to fail. Synchronous (run via to_thread).
ProgressCb = Callable[[float | None, str | None], None]
TaskRunner = Callable[[ProgressCb], None]


@dataclass(frozen=True)
class Task:
    id: str
    kind: TaskKind
    title: str
    target: dict[str, Any]
    status: TaskStatus
    progress: float | None
    message: str | None
    error: str | None
    created_at: float
    started_at: float | None
    finished_at: float | None


@dataclass
class TaskEvent:
    type: Literal["added", "updated", "removed"]
    task: Task


# Cap retained finished tasks so the registry doesn't grow unbounded.
HISTORY_LIMIT = 100


class TaskRegistry:
    """Owns the task table, the work queue, and the pub/sub fanout."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._history: deque[str] = deque(maxlen=HISTORY_LIMIT)
        self._runners: dict[str, TaskRunner] = {}
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._subscribers: set[asyncio.Queue[TaskEvent]] = set()
        self._worker_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    # --- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        if self._worker_task is None:
            return
        self._worker_task.cancel()
        try:
            await self._worker_task
        except asyncio.CancelledError:
            pass
        self._worker_task = None

    # --- public API ---------------------------------------------------------

    def submit(
        self,
        *,
        kind: TaskKind,
        title: str,
        target: dict[str, Any],
        runner: TaskRunner,
    ) -> Task:
        task_id = uuid.uuid4().hex
        task = Task(
            id=task_id,
            kind=kind,
            title=title,
            target=dict(target),
            status="queued",
            progress=None,
            message=None,
            error=None,
            created_at=time.time(),
            started_at=None,
            finished_at=None,
        )
        self._tasks[task_id] = task
        self._runners[task_id] = runner
        self._queue.put_nowait(task_id)
        self._publish(TaskEvent(type="added", task=task))
        return task

    def list(self, *, active_only: bool = False) -> list[Task]:
        tasks = list(self._tasks.values())
        if active_only:
            tasks = [t for t in tasks if t.status in ("queued", "running")]
        return sorted(tasks, key=lambda t: t.created_at)

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def find_active(self, predicate: Callable[[Task], bool]) -> list[Task]:
        return [
            t for t in self._tasks.values()
            if t.status in ("queued", "running") and predicate(t)
        ]

    def subscribe(self) -> asyncio.Queue[TaskEvent]:
        q: asyncio.Queue[TaskEvent] = asyncio.Queue()
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[TaskEvent]) -> None:
        self._subscribers.discard(q)

    async def wait_idle(self, timeout: float = 5.0) -> None:
        """Wait until queue is empty and no task is running. Test helper."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._queue.empty() and not any(
                t.status == "running" for t in self._tasks.values()
            ):
                return
            await asyncio.sleep(0.01)
        raise TimeoutError("tasks did not finish within timeout")

    # --- internals ----------------------------------------------------------

    def _publish(self, event: TaskEvent) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:  # pragma: no cover — unbounded queue
                pass

    def _update(self, task_id: str, **changes: Any) -> Task:
        current = self._tasks[task_id]
        updated = replace(current, **changes)
        self._tasks[task_id] = updated
        self._publish(TaskEvent(type="updated", task=updated))
        return updated

    def _retire(self, task_id: str) -> None:
        self._history.append(task_id)
        # Drop tasks pushed out of the history window.
        if len(self._history) == self._history.maxlen:
            # deque popleft already happened; recompute set of surviving ids.
            surviving = set(self._history)
            for tid in list(self._tasks.keys()):
                if (
                    self._tasks[tid].status in ("done", "failed", "cancelled")
                    and tid not in surviving
                ):
                    self._tasks.pop(tid, None)
                    self._runners.pop(tid, None)

    async def _worker_loop(self) -> None:
        try:
            while True:
                task_id = await self._queue.get()
                runner = self._runners.get(task_id)
                if runner is None:
                    continue
                await self._run_one(task_id, runner)
        except asyncio.CancelledError:
            raise

    async def _run_one(self, task_id: str, runner: TaskRunner) -> None:
        self._update(
            task_id, status="running", started_at=time.time(),
            message="starting",
        )

        def progress(p: float | None, m: str | None) -> None:
            self._update(task_id, progress=p, message=m)

        try:
            await asyncio.to_thread(runner, progress)
        except Exception as exc:  # noqa: BLE001 — task layer must catch all
            logger.exception("task %s (%s) failed", task_id, self._tasks[task_id].kind)
            self._update(
                task_id,
                status="failed",
                error=str(exc),
                finished_at=time.time(),
            )
        else:
            self._update(
                task_id,
                status="done",
                progress=1.0,
                message=None,
                finished_at=time.time(),
            )
        finally:
            self._runners.pop(task_id, None)
            self._retire(task_id)


# --- module-level singleton accessors --------------------------------------
#
# The registry instance is owned by the FastAPI app (set in lifespan and
# stashed on app.state). For places that don't have access to `request`/`app`
# we expose a process-global slot. Tests set/clear it explicitly via
# `_install_for_tests` to keep state isolated.

_global: TaskRegistry | None = None


def install(registry: TaskRegistry) -> None:
    global _global
    _global = registry


def get() -> TaskRegistry:
    if _global is None:
        raise RuntimeError("task registry not installed")
    return _global


def _install_for_tests(registry: TaskRegistry | None) -> None:
    global _global
    _global = registry


# --- async runner helpers --------------------------------------------------


async def collect_events(
    queue: asyncio.Queue[TaskEvent], *, count: int, timeout: float = 2.0,
) -> list[TaskEvent]:
    """Test helper: drain `count` events with an overall timeout."""
    out: list[TaskEvent] = []
    async def _pull() -> None:
        for _ in range(count):
            out.append(await queue.get())
    await asyncio.wait_for(_pull(), timeout=timeout)
    return out


# Re-exported for callers that don't want to import dataclasses directly.
__all__ = [
    "Task",
    "TaskEvent",
    "TaskKind",
    "TaskRegistry",
    "TaskStatus",
    "TaskRunner",
    "ProgressCb",
    "install",
    "get",
    "collect_events",
]


def make_runner_awaitable(coro_factory: Callable[[ProgressCb], Awaitable[None]]) -> TaskRunner:
    """Adapt an async runner so it can be passed to `submit`. The wrapper
    runs the coroutine inside `asyncio.run` from the worker thread; the worker
    itself is async but uses `to_thread` for the runner, so a fresh event
    loop here is safe. Used when a runner needs `await`-style I/O (e.g. a
    civitai import) but we still want it scheduled through this single-slot
    queue.
    """
    def _run(progress: ProgressCb) -> None:
        asyncio.run(coro_factory(progress))
    return _run
