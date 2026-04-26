from __future__ import annotations

import json

import httpx
import pytest

from app.services import lm_client


def _mock_response(payload: dict, status: int = 200) -> httpx.MockTransport:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)
    return httpx.MockTransport(handler)


def test_chat_complete_returns_assistant_content():
    transport = _mock_response({
        "choices": [{"message": {"role": "assistant", "content": "  hello  "}}],
    })
    out = lm_client.chat_complete(
        endpoint={"base_url": "http://x/v1", "api_key": None},
        model="m",
        messages=[{"role": "user", "content": "hi"}],
        transport=transport,
    )
    assert out == "hello"


def test_chat_complete_passes_response_format_when_supplied():
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.content.decode())
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "{}"}}],
        })

    out = lm_client.chat_complete(
        endpoint={"base_url": "http://x/v1", "api_key": None},
        model="m",
        messages=[{"role": "user", "content": "hi"}],
        response_format={"type": "json_object"},
        transport=httpx.MockTransport(handler),
    )
    assert out == "{}"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["body"]["stream"] is False


def test_chat_complete_omits_response_format_when_none():
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.content.decode())
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}}],
        })

    lm_client.chat_complete(
        endpoint={"base_url": "http://x/v1", "api_key": None},
        model="m",
        messages=[{"role": "user", "content": "hi"}],
        transport=httpx.MockTransport(handler),
    )
    assert "response_format" not in captured["body"]


def test_chat_complete_raises_upstream_on_4xx():
    transport = _mock_response({"error": "bad"}, status=400)
    with pytest.raises(lm_client.LmError) as exc:
        lm_client.chat_complete(
            endpoint={"base_url": "http://x/v1", "api_key": None},
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            transport=transport,
        )
    assert exc.value.kind == "upstream"


def test_chat_complete_raises_shape_on_empty_content():
    transport = _mock_response({
        "choices": [{"message": {"content": "   "}}],
    })
    with pytest.raises(lm_client.LmError) as exc:
        lm_client.chat_complete(
            endpoint={"base_url": "http://x/v1", "api_key": None},
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            transport=transport,
        )
    assert exc.value.kind == "shape"


def test_chat_complete_requires_model_and_messages():
    with pytest.raises(lm_client.LmError) as exc1:
        lm_client.chat_complete(
            endpoint={"base_url": "http://x/v1", "api_key": None},
            model="  ",
            messages=[{"role": "user", "content": "hi"}],
        )
    assert exc1.value.kind == "config"

    with pytest.raises(lm_client.LmError) as exc2:
        lm_client.chat_complete(
            endpoint={"base_url": "http://x/v1", "api_key": None},
            model="m",
            messages=[],
        )
    assert exc2.value.kind == "config"


def test_chat_complete_raises_timeout():
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=req)
    with pytest.raises(lm_client.LmError) as exc:
        lm_client.chat_complete(
            endpoint={"base_url": "http://x/v1", "api_key": None},
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            transport=httpx.MockTransport(handler),
        )
    assert exc.value.kind == "timeout"


def test_chat_complete_raises_shape_on_non_json_body():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json", headers={"content-type": "text/html"})
    with pytest.raises(lm_client.LmError) as exc:
        lm_client.chat_complete(
            endpoint={"base_url": "http://x/v1", "api_key": None},
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            transport=httpx.MockTransport(handler),
        )
    assert exc.value.kind == "shape"


def test_chat_complete_raises_shape_on_null_content():
    transport = _mock_response({
        "choices": [{"message": {"content": None}}],
    })
    with pytest.raises(lm_client.LmError) as exc:
        lm_client.chat_complete(
            endpoint={"base_url": "http://x/v1", "api_key": None},
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            transport=transport,
        )
    assert exc.value.kind == "shape"
    assert "null" in exc.value.detail.lower() or "tool" in exc.value.detail.lower()
