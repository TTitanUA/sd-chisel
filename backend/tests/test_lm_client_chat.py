from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.services import lm_client


def _sse_bytes(events: list[dict[str, Any] | str]) -> bytes:
    """Serialize a list of OpenAI-style SSE chat-completion chunks to wire bytes."""
    out: list[str] = []
    for ev in events:
        payload = ev if isinstance(ev, str) else json.dumps(ev)
        out.append(f"data: {payload}\n\n")
    return "".join(out).encode()


def _stream_response(events: list[dict[str, Any] | str]) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=_sse_bytes(events),
    )


def test_chat_stream_yields_content_deltas_until_done():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return _stream_response([
            {"choices": [{"delta": {"content": "Hel"}}]},
            {"choices": [{"delta": {"content": "lo"}}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            "[DONE]",
        ])

    chunks = list(lm_client.chat_stream(
        endpoint={"base_url": "http://h/v1", "api_key": "k"},
        model="m",
        messages=[{"role": "user", "content": "hi"}],
        transport=httpx.MockTransport(handler),
    ))
    assert chunks == ["Hel", "lo"]
    assert captured["url"] == "http://h/v1/chat/completions"
    assert captured["body"]["model"] == "m"
    assert captured["body"]["stream"] is True
    assert captured["body"]["messages"] == [{"role": "user", "content": "hi"}]


def test_chat_stream_skips_non_content_deltas():
    def handler(_request: httpx.Request) -> httpx.Response:
        return _stream_response([
            {"choices": [{"delta": {"role": "assistant"}}]},   # role-only first chunk
            {"choices": [{"delta": {"content": "ok"}}]},
            "[DONE]",
        ])

    chunks = list(lm_client.chat_stream(
        endpoint={"base_url": "http://h/v1", "api_key": None},
        model="m", messages=[{"role": "user", "content": "x"}],
        transport=httpx.MockTransport(handler),
    ))
    assert chunks == ["ok"]


def test_chat_stream_raises_lm_error_on_non_2xx():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="busy")

    with pytest.raises(lm_client.LmError) as exc:
        list(lm_client.chat_stream(
            endpoint={"base_url": "http://h/v1", "api_key": None},
            model="m", messages=[{"role": "user", "content": "x"}],
            transport=httpx.MockTransport(handler),
        ))
    assert exc.value.kind == "upstream"
    assert "503" in exc.value.detail


def test_chat_stream_raises_lm_error_on_timeout():
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with pytest.raises(lm_client.LmError) as exc:
        list(lm_client.chat_stream(
            endpoint={"base_url": "http://h/v1", "api_key": None},
            model="m", messages=[{"role": "user", "content": "x"}],
            transport=httpx.MockTransport(handler),
        ))
    assert exc.value.kind == "timeout"


def test_chat_stream_ignores_garbage_lines():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=(
                b": ping comment\n\n"
                b"data: {not json\n\n"
                b'data: {"choices": [{"delta": {"content": "ok"}}]}\n\n'
                b"data: [DONE]\n\n"
            ),
        )

    chunks = list(lm_client.chat_stream(
        endpoint={"base_url": "http://h/v1", "api_key": None},
        model="m", messages=[{"role": "user", "content": "x"}],
        transport=httpx.MockTransport(handler),
    ))
    assert chunks == ["ok"]


def test_chat_stream_raises_config_error_on_blank_model():
    with pytest.raises(lm_client.LmError) as exc:
        list(lm_client.chat_stream(
            endpoint={"base_url": "http://h/v1", "api_key": None},
            model="   ",
            messages=[{"role": "user", "content": "x"}],
        ))
    assert exc.value.kind == "config"


def test_chat_stream_raises_config_error_on_empty_messages():
    with pytest.raises(lm_client.LmError) as exc:
        list(lm_client.chat_stream(
            endpoint={"base_url": "http://h/v1", "api_key": None},
            model="m",
            messages=[],
        ))
    assert exc.value.kind == "config"
