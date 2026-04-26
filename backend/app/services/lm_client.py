"""Thin OpenAI-compatible client for an LMStudio-style server.

We deliberately stay on raw httpx instead of pulling the openai SDK — slice 3
needs only two methods, and slice 4 (chat) will make its own decision on SSE.

`endpoint` shape used everywhere here: ``{"base_url": str, "api_key": str|None}``.
"""
from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from typing import Any, Literal

import httpx

DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=5.0)
LIST_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
CHAT_TIMEOUT = httpx.Timeout(120.0, connect=5.0, read=120.0)

VL_SYSTEM_PROMPT = (
    "You describe images in terms useful for image-to-image generation. "
    "Be concise and concrete. Cover composition, subjects/objects, style, "
    "lighting, palette, and mood. Avoid speculation; do not invent text. "
    "Output a single paragraph of plain prose, no lists, no preamble."
)


class LmError(Exception):
    """Failure raised by lm_client. `slots=True` is intentionally NOT used —
    combining it with `Exception` triggers a layout conflict on CPython."""

    def __init__(self, kind: Literal["upstream", "timeout", "shape", "config"], detail: str) -> None:
        super().__init__(f"LmError({kind}): {detail}")
        self.kind = kind
        self.detail = detail


def _resolve(endpoint: dict[str, Any]) -> tuple[str, dict[str, str]]:
    base_url = str(endpoint.get("base_url") or "").strip().rstrip("/")
    if not base_url:
        raise LmError("config", "lmstudio base_url is not configured")
    headers = {"Content-Type": "application/json"}
    api_key = endpoint.get("api_key") or None
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return base_url, headers


def _request(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    json: dict[str, Any] | None,
    transport: httpx.BaseTransport | None,
    timeout: httpx.Timeout,
) -> httpx.Response:
    try:
        with httpx.Client(transport=transport, timeout=timeout) as client:
            return client.request(method, url, headers=headers, json=json)
    except httpx.TimeoutException as exc:
        raise LmError("timeout", str(exc)) from exc
    except httpx.HTTPError as exc:
        raise LmError("upstream", str(exc)) from exc


def list_models(
    *,
    endpoint: dict[str, Any],
    transport: httpx.BaseTransport | None = None,
) -> list[str]:
    base_url, headers = _resolve(endpoint)
    resp = _request(
        "GET", f"{base_url}/models",
        headers=headers, json=None, transport=transport, timeout=LIST_TIMEOUT,
    )
    if resp.status_code >= 400:
        raise LmError("upstream", f"{resp.status_code}: {resp.text[:200]}")
    try:
        body = resp.json()
        names = sorted(item["id"] for item in body["data"])
    except (ValueError, KeyError, TypeError) as exc:
        raise LmError("shape", f"unexpected /models body: {exc}") from exc
    return names


def analyze_image(
    *,
    endpoint: dict[str, Any],
    model: str,
    image_bytes: bytes,
    content_type: str,
    transport: httpx.BaseTransport | None = None,
) -> str:
    if not model.strip():
        raise LmError("config", "model is required")

    base_url, headers = _resolve(endpoint)
    b64 = base64.b64encode(image_bytes).decode("ascii")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": VL_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this image for i2i prompt building."},
                    {"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{b64}"}},
                ],
            },
        ],
        "stream": False,
    }
    resp = _request(
        "POST", f"{base_url}/chat/completions",
        headers=headers, json=payload, transport=transport, timeout=DEFAULT_TIMEOUT,
    )
    if resp.status_code >= 400:
        raise LmError("upstream", f"{resp.status_code}: {resp.text[:200]}")
    try:
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LmError("shape", f"unexpected response body: {exc}") from exc
    if not isinstance(content, str) or not content.strip():
        raise LmError("shape", "empty content from VL endpoint")
    return content.strip()


def chat_stream(
    *,
    endpoint: dict[str, Any],
    model: str,
    messages: list[dict[str, Any]],
    transport: httpx.BaseTransport | None = None,
) -> Iterator[str]:
    """Yield assistant content chunks from an OpenAI-compatible streaming chat.

    Connects to ``{base_url}/chat/completions`` with ``stream=true``, parses
    Server-Sent Events line by line, and yields the ``choices[0].delta.content``
    string of each chunk that has one. The terminal ``data: [DONE]`` line ends
    iteration. Lines that aren't JSON or that have no content delta are
    skipped silently — LMStudio occasionally emits role-only or
    finish_reason-only chunks at the boundaries.
    """
    if not model.strip():
        raise LmError("config", "model is required")
    if not messages:
        raise LmError("config", "messages must not be empty")
    base_url, headers = _resolve(endpoint)
    payload = {"model": model, "messages": messages, "stream": True}
    try:
        with httpx.Client(transport=transport, timeout=CHAT_TIMEOUT) as client:
            with client.stream(
                "POST", f"{base_url}/chat/completions",
                headers=headers, json=payload,
            ) as resp:
                if resp.status_code >= 400:
                    body = resp.read().decode("utf-8", errors="replace")
                    raise LmError("upstream", f"{resp.status_code}: {body[:200]}")
                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if data == "[DONE]":
                        return
                    try:
                        chunk = json.loads(data)
                    except ValueError:
                        continue
                    try:
                        delta = chunk["choices"][0].get("delta") or {}
                    except (KeyError, IndexError, TypeError):
                        continue
                    content = delta.get("content")
                    if isinstance(content, str) and content:
                        yield content
    except httpx.TimeoutException as exc:
        raise LmError("timeout", str(exc)) from exc
    except httpx.HTTPError as exc:
        raise LmError("upstream", str(exc)) from exc


def chat_complete(
    *,
    endpoint: dict[str, Any],
    model: str,
    messages: list[dict[str, Any]],
    response_format: dict[str, Any] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> str:
    """Non-streaming OpenAI-compat chat. Returns the assistant content as a string.

    `response_format` is forwarded as-is when provided (e.g. ``{"type":
    "json_object"}``). LMStudio supports json_object on most prompt-tuned
    models; json_schema support is patchy, so callers should validate the
    parsed JSON themselves.
    """
    if not model.strip():
        raise LmError("config", "model is required")
    if not messages:
        raise LmError("config", "messages must not be empty")
    base_url, headers = _resolve(endpoint)
    payload: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
    if response_format is not None:
        payload["response_format"] = response_format
    resp = _request(
        "POST", f"{base_url}/chat/completions",
        headers=headers, json=payload, transport=transport, timeout=CHAT_TIMEOUT,
    )
    if resp.status_code >= 400:
        raise LmError("upstream", f"{resp.status_code}: {resp.text[:200]}")
    try:
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LmError("shape", f"unexpected response body: {exc}") from exc
    if not isinstance(content, str) or not content.strip():
        raise LmError("shape", "empty content from chat endpoint")
    return content.strip()
