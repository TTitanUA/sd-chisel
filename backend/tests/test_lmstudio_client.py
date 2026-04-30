from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

from app.services import lmstudio_client

ENDPOINT = {"server_root": "http://localhost:1234", "api_key": None}
ENDPOINT_WITH_KEY = {"server_root": "http://localhost:1234", "api_key": "lm-key"}


def _make_transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _models_body(items: list[dict]) -> dict:
    return {"data": items}


def _llm_item(name: str, vision=False, tool_use=False, reasoning_opts=None) -> dict:
    caps: dict[str, Any] = {"vision": vision, "trained_for_tool_use": tool_use}
    if reasoning_opts is not None:
        caps["reasoning"] = {"allowed_options": reasoning_opts, "default": reasoning_opts[0]}
    return {"id": name, "type": "llm", "capabilities": caps}


def _chat_response(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}]
        },
    )


# --- list_models ---

def test_list_models_hits_api_v1_models_endpoint():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=_models_body([_llm_item("m")]))

    lmstudio_client.list_models(endpoint=ENDPOINT, transport=_make_transport(handler))
    assert captured["url"] == "http://localhost:1234/api/v1/models"


def test_list_models_returns_capabilities():
    items = [
        _llm_item("qwen-vl", vision=True),
        _llm_item("mistral", tool_use=True, reasoning_opts=["disabled", "enabled"]),
    ]

    def handler(r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_models_body(items))

    models = lmstudio_client.list_models(endpoint=ENDPOINT, transport=_make_transport(handler))
    by_name = {m.name: m for m in models}

    assert by_name["qwen-vl"].vision is True
    assert by_name["qwen-vl"].tool_use is False
    assert by_name["qwen-vl"].reasoning is False

    assert by_name["mistral"].vision is False
    assert by_name["mistral"].tool_use is True
    assert by_name["mistral"].reasoning is True


def test_list_models_filters_out_embeddings():
    items = [
        {"id": "bert-embed", "type": "embedding"},
        _llm_item("llama"),
    ]

    def handler(r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_models_body(items))

    models = lmstudio_client.list_models(endpoint=ENDPOINT, transport=_make_transport(handler))
    assert len(models) == 1
    assert models[0].name == "llama"


def test_list_models_handles_missing_capabilities():
    items = [{"id": "llama", "type": "llm"}]

    def handler(r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_models_body(items))

    models = lmstudio_client.list_models(endpoint=ENDPOINT, transport=_make_transport(handler))
    m = models[0]
    assert m.vision is False
    assert m.tool_use is False
    assert m.reasoning is False


def test_list_models_sends_auth_header():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=_models_body([]))

    lmstudio_client.list_models(endpoint=ENDPOINT_WITH_KEY, transport=_make_transport(handler))
    assert captured["auth"] == "Bearer lm-key"


def test_list_models_raises_on_non_2xx():
    transport = _make_transport(lambda r: httpx.Response(503, text="busy"))
    with pytest.raises(lmstudio_client.LmError) as exc:
        lmstudio_client.list_models(endpoint=ENDPOINT, transport=transport)
    assert exc.value.kind == "upstream"


def test_list_models_raises_on_timeout():
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("nope")

    with pytest.raises(lmstudio_client.LmError) as exc:
        lmstudio_client.list_models(endpoint=ENDPOINT, transport=_make_transport(handler))
    assert exc.value.kind == "timeout"


# --- unload_model ---

def test_unload_model_hits_correct_endpoint():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"instance_id": "inst-1"})

    lmstudio_client.unload_model(
        endpoint=ENDPOINT, instance_id="inst-1", transport=_make_transport(handler),
    )
    assert captured["url"] == "http://localhost:1234/api/v1/models/unload"
    assert captured["body"] == {"instance_id": "inst-1"}


# --- analyze_image ---

def test_analyze_image_sends_to_v1_chat_completions():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return _chat_response("a moody street")

    out = lmstudio_client.analyze_image(
        endpoint=ENDPOINT,
        model="qwen-vl",
        image_bytes=b"\x89PNG_fake",
        content_type="image/png",
        transport=_make_transport(handler),
    )
    assert out == "a moody street"
    assert captured["url"] == "http://localhost:1234/v1/chat/completions"
    assert captured["body"]["model"] == "qwen-vl"
    parts = captured["body"]["messages"][-1]["content"]
    assert any(p.get("type") == "image_url" for p in parts)


# --- chat_complete ---

def test_chat_complete_sends_to_v1_chat_completions():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return _chat_response("hello")

    out = lmstudio_client.chat_complete(
        endpoint=ENDPOINT,
        model="mistral",
        messages=[{"role": "user", "content": "hi"}],
        transport=_make_transport(handler),
    )
    assert out == "hello"
    assert captured["url"] == "http://localhost:1234/v1/chat/completions"


# --- chat_stream_with_tools ---

def _sse_lines(*events: str) -> str:
    return "".join(f"data: {e}\n\n" for e in events) + "data: [DONE]\n\n"


def _text_delta(content: str) -> str:
    return json.dumps({
        "choices": [{"delta": {"content": content}, "finish_reason": None}],
    })


def _tool_call_delta(*, name: str | None = None, arguments: str = "") -> str:
    tc: dict[str, Any] = {"index": 0, "function": {}}
    if name is not None:
        tc["id"] = "call_1"
        tc["type"] = "function"
        tc["function"]["name"] = name
    if arguments:
        tc["function"]["arguments"] = arguments
    return json.dumps({
        "choices": [{"delta": {"tool_calls": [tc]}, "finish_reason": None}],
    })


def test_chat_stream_with_tools_yields_text_deltas():
    body = _sse_lines(_text_delta("hello "), _text_delta("world"))

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert "tools" in payload
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    events = list(lmstudio_client.chat_stream_with_tools(
        endpoint=ENDPOINT,
        model="m",
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "noop", "parameters": {}}}],
        transport=_make_transport(handler),
    ))
    assert events == [
        {"type": "delta", "content": "hello "},
        {"type": "delta", "content": "world"},
    ]


def test_chat_stream_with_tools_yields_tool_call():
    body = _sse_lines(
        _text_delta("Here is the guide."),
        _tool_call_delta(name="update_prompt_guide", arguments='{"conte'),
        _tool_call_delta(arguments='nt": "the guide"}'),
    )

    def handler(r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    events = list(lmstudio_client.chat_stream_with_tools(
        endpoint=ENDPOINT,
        model="m",
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        transport=_make_transport(handler),
    ))
    assert events == [
        {"type": "delta", "content": "Here is the guide."},
        {"type": "tool_call", "name": "update_prompt_guide", "arguments": {"content": "the guide"}},
    ]


def test_chat_stream_with_tools_raises_on_upstream_error():
    transport = _make_transport(lambda r: httpx.Response(500, text="internal"))

    with pytest.raises(lmstudio_client.LmError) as exc:
        list(lmstudio_client.chat_stream_with_tools(
            endpoint=ENDPOINT,
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
            transport=transport,
        ))
    assert exc.value.kind == "upstream"


# --- chat_native_stream ---

def _native_sse(*events: tuple[str, dict]) -> str:
    lines = []
    for etype, data in events:
        lines.append(f"event: {etype}\ndata: {json.dumps(data)}\n")
    return "\n".join(lines)


def test_chat_native_stream_yields_deltas_and_tool_status():
    body = _native_sse(
        ("message.delta", {"content": "Reading docs..."}),
        ("tool_call.start", {"tool": "browser_navigate", "provider_info": {}}),
        ("tool_call.success", {"tool": "browser_navigate", "output": "ok"}),
        ("message.delta", {"content": " Done."}),
        ("chat.end", {"response_id": "resp_abc"}),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["input"] == "read this"
        assert payload["system_prompt"] == "be helpful"
        assert "mcp/playwright" in payload["integrations"]
        assert payload["stream"] is True
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    events = list(lmstudio_client.chat_native_stream(
        endpoint=ENDPOINT,
        model="m",
        system_prompt="be helpful",
        user_input="read this",
        integrations=["mcp/playwright"],
        transport=_make_transport(handler),
    ))
    assert events == [
        {"type": "delta", "content": "Reading docs..."},
        {"type": "tool_status", "tool": "browser_navigate", "status": "running"},
        {"type": "tool_status", "tool": "browser_navigate", "status": "done"},
        {"type": "delta", "content": " Done."},
        {"type": "chat_end", "response_id": "resp_abc"},
    ]


def test_chat_native_stream_passes_previous_response_id():
    body = _native_sse(
        ("message.delta", {"content": "ok"}),
        ("chat.end", {"response_id": "resp_2"}),
    )

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    list(lmstudio_client.chat_native_stream(
        endpoint=ENDPOINT,
        model="m",
        system_prompt="sys",
        user_input="follow up",
        previous_response_id="resp_1",
        transport=_make_transport(handler),
    ))
    assert captured["previous_response_id"] == "resp_1"


def test_chat_native_stream_raises_on_upstream_error():
    transport = _make_transport(lambda r: httpx.Response(500, text="server error"))

    with pytest.raises(lmstudio_client.LmError) as exc:
        list(lmstudio_client.chat_native_stream(
            endpoint=ENDPOINT,
            model="m",
            system_prompt="sys",
            user_input="hi",
            transport=transport,
        ))
    assert exc.value.kind == "upstream"
