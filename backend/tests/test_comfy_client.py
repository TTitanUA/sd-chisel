"""Smoke tests for ``comfy_client`` — the Phase 3 async surface used
by the Single Run pipeline.

Covers the URL/body/header shapes the orchestrator sends to ComfyUI;
WebSocket streaming hits a live socket and isn't unit-tested (the
pipeline integration covers it).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.services import comfy_client

ENDPOINT = {"server_root": "http://localhost:8188", "api_key": None}
ENDPOINT_WITH_KEY = {"server_root": "http://localhost:8188", "api_key": "secret"}


def _async_transport(handler):
    return httpx.MockTransport(handler)


def _run(coro):
    return asyncio.run(coro)


# --- queue_prompt ---------------------------------------------------------


def test_queue_prompt_posts_to_api_prompt():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.read()
        return httpx.Response(200, json={"prompt_id": "pid-1", "number": 1})

    pid = _run(comfy_client.queue_prompt(
        endpoint=ENDPOINT,
        prompt={"3": {"class_type": "X"}},
        client_id="cid-1",
        transport=_async_transport(handler),
    ))
    assert pid == "pid-1"
    assert captured["url"] == "http://localhost:8188/api/prompt"
    assert b"client_id" in captured["body"]
    assert b"cid-1" in captured["body"]


def test_queue_prompt_propagates_api_key():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization", "")
        return httpx.Response(200, json={"prompt_id": "pid-1"})

    _run(comfy_client.queue_prompt(
        endpoint=ENDPOINT_WITH_KEY,
        prompt={},
        client_id="cid",
        transport=_async_transport(handler),
    ))
    assert seen["auth"] == "Bearer secret"


def test_queue_prompt_raises_on_missing_prompt_id():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"number": 1})

    with pytest.raises(comfy_client.ComfyError) as exc:
        _run(comfy_client.queue_prompt(
            endpoint=ENDPOINT,
            prompt={},
            client_id="cid",
            transport=_async_transport(handler),
        ))
    assert exc.value.kind == "shape"


def test_queue_prompt_surfaces_4xx():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad workflow")

    with pytest.raises(comfy_client.ComfyError) as exc:
        _run(comfy_client.queue_prompt(
            endpoint=ENDPOINT,
            prompt={},
            client_id="cid",
            transport=_async_transport(handler),
        ))
    assert exc.value.kind == "upstream"


# --- upload_image ---------------------------------------------------------


def test_upload_image_sends_multipart_with_returned_name(tmp_path: Path):
    captured: dict[str, Any] = {}
    src = tmp_path / "input.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.read()
        return httpx.Response(200, json={"name": "input.png", "subfolder": "", "type": "input"})

    name = _run(comfy_client.upload_image(
        endpoint=ENDPOINT, file_path=src, transport=_async_transport(handler),
    ))
    assert name == "input.png"
    assert captured["url"] == "http://localhost:8188/api/upload/image"
    # Multipart frame contains the original filename and the field name.
    assert b"input.png" in captured["body"]
    assert b'name="image"' in captured["body"]


def test_upload_image_raises_when_file_missing(tmp_path: Path):
    with pytest.raises(comfy_client.ComfyError) as exc:
        _run(comfy_client.upload_image(
            endpoint=ENDPOINT,
            file_path=tmp_path / "missing.png",
            transport=_async_transport(lambda r: httpx.Response(200, json={"name": "x"})),
        ))
    assert exc.value.kind == "config"


# --- get_history ----------------------------------------------------------


def test_get_history_returns_inner_record_for_prompt_id():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://localhost:8188/history/pid-1"
        return httpx.Response(200, json={
            "pid-1": {"prompt": [], "outputs": {"9": {"images": [{"filename": "out.png"}]}}},
        })

    out = _run(comfy_client.get_history(
        endpoint=ENDPOINT, prompt_id="pid-1", transport=_async_transport(handler),
    ))
    assert out["outputs"]["9"]["images"][0]["filename"] == "out.png"


def test_get_history_returns_empty_when_prompt_id_absent():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})  # ComfyUI lag — pid not yet present.

    out = _run(comfy_client.get_history(
        endpoint=ENDPOINT, prompt_id="pid-1", transport=_async_transport(handler),
    ))
    assert out == {}


# --- interrupt ------------------------------------------------------------


def test_interrupt_swallows_404():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="nothing executing")

    # Should not raise.
    _run(comfy_client.interrupt(endpoint=ENDPOINT, transport=_async_transport(handler)))


def test_interrupt_raises_on_5xx():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(comfy_client.ComfyError):
        _run(comfy_client.interrupt(endpoint=ENDPOINT, transport=_async_transport(handler)))


# --- free_memory ---------------------------------------------------------


def test_free_memory_posts_to_api_free_with_payload():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.read()
        return httpx.Response(200, text="")

    _run(comfy_client.free_memory(
        endpoint=ENDPOINT, transport=_async_transport(handler),
    ))
    assert captured["url"] == "http://localhost:8188/api/free"
    assert b'"unload_models":true' in captured["body"]
    assert b'"free_memory":true' in captured["body"]


def test_free_memory_raises_on_4xx():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(comfy_client.ComfyError):
        _run(comfy_client.free_memory(
            endpoint=ENDPOINT, transport=_async_transport(handler),
        ))


# --- shape failure helpers ------------------------------------------------


def test_missing_server_root_raises_config():
    with pytest.raises(comfy_client.ComfyError) as exc:
        _run(comfy_client.queue_prompt(
            endpoint={"server_root": "", "api_key": None},
            prompt={},
            client_id="cid",
        ))
    assert exc.value.kind == "config"
