"""In-memory pub/sub for Single Run SSE events.

Each running job gets a ``RunChannel`` keyed by ``job_id``. The
orchestrator publishes events; the SSE endpoint subscribes. Multiple
subscribers (e.g. user has the run open in two tabs) each get their
own view: every event already published is replayed first, then
new events stream live.

Channels stick around until the job is `done` *and* every subscriber
has drained — that way a tab that opens after the run ends still
gets the full transcript. After a grace period the channel is
garbage-collected.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

# Channels are keyed by job_id and live in a process-global dict.
# Single-process FastAPI app, so this is safe; if we ever need
# multi-worker, swap for Redis pub/sub or a DB-backed event log.
_CHANNELS: dict[str, "RunChannel"] = {}
_CHANNELS_LOCK = asyncio.Lock()

# How long after the terminating `done` event to keep a closed
# channel around for late subscribers (a tab the user opened
# seconds after the run finished). Five minutes is generous.
GRACE_SECONDS = 300


class RunChannel:
    """Per-job event log + fan-out broker.

    Events are appended to ``self.events`` and pushed to every live
    subscriber's queue. Subscribers receive a *snapshot* of the log
    when they subscribe, then live events; this is the
    replay-then-resume contract the SSE endpoint exposes.
    """

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self.events: list[dict[str, Any]] = []
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self.closed = False
        self.closed_at: float | None = None
        # Set by the cancel endpoint; checked by the orchestrator at
        # stage boundaries. Distinct from `closed` (which is the
        # post-`done` GC flag) — a cancelled channel still publishes
        # the cancellation events through to subscribers.
        self.cancel_event = asyncio.Event()

    def publish(self, event: dict[str, Any]) -> None:
        self.events.append(event)
        for q in list(self.subscribers):
            # `put_nowait` because the queue is unbounded; we never
            # want the orchestrator to block on a slow subscriber.
            q.put_nowait(event)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.closed_at = time.monotonic()
        # Wake every subscriber so their iterators terminate.
        sentinel = {"_sentinel": "channel_closed"}
        for q in list(self.subscribers):
            q.put_nowait(sentinel)

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        """Yield every event so far + every new event until close."""
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        # Snapshot the existing log into the queue under the same
        # lock that publish runs under to avoid the
        # subscribe/publish race that would drop one event.
        for e in self.events:
            q.put_nowait(e)
        if self.closed:
            # Already finished — replay then close on a sentinel.
            q.put_nowait({"_sentinel": "channel_closed"})
        self.subscribers.add(q)
        try:
            while True:
                event = await q.get()
                if event.get("_sentinel") == "channel_closed":
                    return
                yield event
        finally:
            self.subscribers.discard(q)


async def open_channel(job_id: str) -> RunChannel:
    """Create-or-get the channel for ``job_id``.

    Idempotent — if a channel already exists (rare, would mean the
    same job was started twice — guarded against at the API level),
    returns the existing one.
    """
    async with _CHANNELS_LOCK:
        ch = _CHANNELS.get(job_id)
        if ch is None:
            ch = RunChannel(job_id)
            _CHANNELS[job_id] = ch
        return ch


async def get_channel(job_id: str) -> RunChannel | None:
    async with _CHANNELS_LOCK:
        return _CHANNELS.get(job_id)


async def close_channel(job_id: str) -> None:
    async with _CHANNELS_LOCK:
        ch = _CHANNELS.get(job_id)
    if ch is not None:
        ch.close()


async def gc_closed_channels(*, now: float | None = None) -> int:
    """Drop channels whose grace window has elapsed. Returns the
    number reaped. Called opportunistically when new channels open;
    no background scheduler needed."""
    cutoff = (now if now is not None else time.monotonic()) - GRACE_SECONDS
    reaped = 0
    async with _CHANNELS_LOCK:
        stale = [
            jid
            for jid, ch in _CHANNELS.items()
            if ch.closed and ch.closed_at is not None and ch.closed_at < cutoff
            and not ch.subscribers
        ]
        for jid in stale:
            del _CHANNELS[jid]
            reaped += 1
    return reaped
