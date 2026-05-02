"""Structured logging of LLM round-trips.

Every public ``lmstudio_client`` call writes one JSONL line to
``data/llm_log/<YYYY-MM-DD>.jsonl`` (UTC date) with the full request
payload, the assembled response, duration, and any error. A ``run_id``
context variable groups every call within a single user-facing turn (one
chat message, one generate-prompt run, one VL analysis), so the whole
multi-step flow is greppable as one logical unit.

Disable with ``SDCHISEL_LLM_LOG=0`` (tests do this via the conftest).
Image binaries inside chat messages are redacted to
``<base64:Nb>`` placeholders so the log stays readable.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import resolve_data_root

_run_id_var: ContextVar[str | None] = ContextVar("llm_run_id", default=None)
_lock = threading.Lock()


def _enabled() -> bool:
    return os.environ.get("SDCHISEL_LLM_LOG", "1") != "0"


def current_run_id() -> str | None:
    return _run_id_var.get()


@contextmanager
def run_context(run_id: str | None = None) -> Iterator[str]:
    """Set a ``run_id`` for the duration of the block.

    If a ``run_id`` is already set on the context (e.g. the orchestrator
    is invoked from inside a chat turn), the existing value is reused —
    no new id is generated and the contextvar is not reset on exit.

    Note on streaming: the chat endpoint enters this context manager
    inside a starlette ``StreamingResponse`` generator. anyio iterates
    that generator in a different Context than the one that created the
    token, so ``ContextVar.reset(token)`` raises ``ValueError`` on exit.
    We swallow that and clear the var instead — the leak is harmless
    because the next chat turn opens a fresh context anyway.
    """
    existing = _run_id_var.get()
    if existing is not None and run_id is None:
        yield existing
        return
    rid = run_id or _new_run_id()
    token = _run_id_var.set(rid)
    try:
        yield rid
    finally:
        try:
            _run_id_var.reset(token)
        except ValueError:
            _run_id_var.set(None)


def _new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def _log_path() -> Path:
    root = resolve_data_root() / "llm_log"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{datetime.now(UTC).strftime('%Y-%m-%d')}.jsonl"


def _redact_messages(messages: Any) -> Any:
    """Return a copy of ``messages`` with base64 image payloads replaced by
    ``data:<mime>,<base64:Nb>`` placeholders. Non-list inputs pass through."""
    if not isinstance(messages, list):
        return messages
    out: list[Any] = []
    for msg in messages:
        if not isinstance(msg, dict):
            out.append(msg)
            continue
        content = msg.get("content")
        if isinstance(content, list):
            new_parts: list[Any] = []
            for part in content:
                if (
                    isinstance(part, dict)
                    and part.get("type") == "image_url"
                    and isinstance(part.get("image_url"), dict)
                ):
                    url = part["image_url"].get("url") or ""
                    if isinstance(url, str) and url.startswith("data:"):
                        head, _, payload = url.partition(",")
                        new_parts.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"{head},<base64:{len(payload)}b>",
                            },
                        })
                    else:
                        new_parts.append(part)
                else:
                    new_parts.append(part)
            out.append({**msg, "content": new_parts})
        else:
            out.append(msg)
    return out


def _redact_request(request: dict[str, Any] | None) -> dict[str, Any] | None:
    if not request:
        return request
    payload = request.get("payload")
    if isinstance(payload, dict) and "messages" in payload:
        request = {
            **request,
            "payload": {**payload, "messages": _redact_messages(payload["messages"])},
        }
    return request


def write_event(
    *,
    kind: str,
    model: str | None,
    request: dict[str, Any] | None,
    response: dict[str, Any] | None = None,
    error: str | None = None,
    duration_ms: int | None = None,
) -> None:
    """Append one JSONL record. Best-effort — never raises."""
    if not _enabled():
        return
    rid = current_run_id() or f"oneshot-{_new_run_id()[:8]}"
    record = {
        "ts": datetime.now(UTC).isoformat(),
        "run_id": rid,
        "kind": kind,
        "model": model,
        "duration_ms": duration_ms,
        "request": _redact_request(request),
        "response": response,
        "error": error,
    }
    try:
        line = json.dumps(record, ensure_ascii=False, default=str)
        with _lock:
            with _log_path().open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    except OSError:
        # Logging must not break the LLM call.
        pass


def now_ms() -> float:
    """Monotonic timer base for ``int((now_ms() - t0) * 1000)`` patterns."""
    return time.perf_counter()
