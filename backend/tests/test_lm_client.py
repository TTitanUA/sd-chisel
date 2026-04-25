from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.services import lm_client


def _models_response(names: list[str]) -> httpx.Response:
    return httpx.Response(
        200,
        json={"object": "list", "data": [{"id": n, "object": "model"} for n in names]},
    )


def _chat_response(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "x",
            "object": "chat.completion",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        },
    )


def test_list_models_hits_models_endpoint_and_returns_names():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        return _models_response(["qwen2-vl-7b-instruct", "mistral-nemo-12b"])

    out = lm_client.list_models(
        endpoint={"base_url": "http://localhost:1234/v1", "api_key": "lm-studio"},
        transport=httpx.MockTransport(handler),
    )
    assert out == ["mistral-nemo-12b", "qwen2-vl-7b-instruct"]  # sorted
    assert captured["url"] == "http://localhost:1234/v1/models"
    assert captured["headers"]["authorization"] == "Bearer lm-studio"


def test_list_models_omits_authorization_when_no_api_key():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        return _models_response([])

    lm_client.list_models(
        endpoint={"base_url": "http://h/v1", "api_key": None},
        transport=httpx.MockTransport(handler),
    )
    assert "authorization" not in captured["headers"]


def test_list_models_strips_trailing_slash():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return _models_response([])

    lm_client.list_models(
        endpoint={"base_url": "http://h/v1/", "api_key": None},
        transport=httpx.MockTransport(handler),
    )
    assert captured["url"] == "http://h/v1/models"


def test_list_models_raises_on_non_2xx():
    transport = httpx.MockTransport(lambda r: httpx.Response(503, text="busy"))
    with pytest.raises(lm_client.LmError) as exc:
        lm_client.list_models(
            endpoint={"base_url": "http://h/v1", "api_key": None},
            transport=transport,
        )
    assert exc.value.kind == "upstream"


def test_list_models_raises_on_timeout():
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("nope")

    with pytest.raises(lm_client.LmError) as exc:
        lm_client.list_models(
            endpoint={"base_url": "http://h/v1", "api_key": None},
            transport=httpx.MockTransport(handler),
        )
    assert exc.value.kind == "timeout"


def test_analyze_image_sends_chat_completions_with_data_url():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return _chat_response("a moody street at dusk")

    out = lm_client.analyze_image(
        endpoint={"base_url": "http://localhost:1234/v1", "api_key": "lm-studio"},
        model="qwen2-vl-7b-instruct",
        image_bytes=b"\x89PNG_fake",
        content_type="image/png",
        transport=httpx.MockTransport(handler),
    )
    assert out == "a moody street at dusk"
    assert captured["url"] == "http://localhost:1234/v1/chat/completions"
    assert captured["body"]["model"] == "qwen2-vl-7b-instruct"
    user = captured["body"]["messages"][-1]
    parts = user["content"]
    types = [p["type"] for p in parts]
    assert "text" in types and "image_url" in types
    assert parts[-1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_analyze_image_raises_on_shape_mismatch():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"choices": []}))
    with pytest.raises(lm_client.LmError) as exc:
        lm_client.analyze_image(
            endpoint={"base_url": "http://h/v1", "api_key": None},
            model="m",
            image_bytes=b"x",
            content_type="image/png",
            transport=transport,
        )
    assert exc.value.kind == "shape"


def test_analyze_image_propagates_timeout():
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with pytest.raises(lm_client.LmError) as exc:
        lm_client.analyze_image(
            endpoint={"base_url": "http://h/v1", "api_key": None},
            model="m", image_bytes=b"x", content_type="image/png",
            transport=httpx.MockTransport(handler),
        )
    assert exc.value.kind == "timeout"
