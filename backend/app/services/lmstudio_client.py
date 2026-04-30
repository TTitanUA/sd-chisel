"""Unified LMStudio client.

Handles both OpenAI-compat endpoints ({server_root}/v1/...) and
LMStudio-native system endpoints ({server_root}/api/v1/...).

`endpoint` shape: {"server_root": str, "api_key": str | None}
"""
from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from dataclasses import dataclass
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


@dataclass
class LmsModel:
    name: str
    vision: bool
    tool_use: bool
    reasoning: bool


class LmError(Exception):
    def __init__(self, kind: Literal["upstream", "timeout", "shape", "config"], detail: str) -> None:
        super().__init__(f"LmError({kind}): {detail}")
        self.kind = kind
        self.detail = detail


def _resolve(endpoint: dict[str, Any]) -> tuple[str, dict[str, str]]:
    server_root = str(endpoint.get("server_root") or "").strip().rstrip("/")
    if not server_root:
        raise LmError("config", "lmstudio server URL is not configured")
    headers = {"Content-Type": "application/json"}
    api_key = endpoint.get("api_key") or None
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return server_root, headers


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


# ---------------------------------------------------------------------------
# System methods (LMStudio-native /api/v1/...)
# ---------------------------------------------------------------------------

def list_models(
    *,
    endpoint: dict[str, Any],
    transport: httpx.BaseTransport | None = None,
) -> list[LmsModel]:
    server_root, headers = _resolve(endpoint)
    resp = _request(
        "GET", f"{server_root}/api/v1/models",
        headers=headers, json=None, transport=transport, timeout=LIST_TIMEOUT,
    )
    if resp.status_code >= 400:
        raise LmError("upstream", f"{resp.status_code}: {resp.text[:200]}")
    try:
        body = resp.json()
        items = body.get("data") or body.get("models") or []
        if not isinstance(items, list):
            raise ValueError(f"expected list, got {type(items)}")
    except (ValueError, KeyError, TypeError) as exc:
        raise LmError("shape", f"unexpected /api/v1/models body: {exc}") from exc

    models: list[LmsModel] = []
    for item in items:
        if item.get("type") != "llm":
            continue
        caps = item.get("capabilities") or {}
        reasoning_obj = caps.get("reasoning") or {}
        models.append(LmsModel(
            name=item.get("id") or item.get("key") or item.get("name") or "",
            vision=bool(caps.get("vision", False)),
            tool_use=bool(caps.get("trained_for_tool_use", False)),
            reasoning=bool(reasoning_obj.get("allowed_options")),
        ))
    return sorted(models, key=lambda m: m.name)


def unload_model(
    *,
    endpoint: dict[str, Any],
    instance_id: str,
    transport: httpx.BaseTransport | None = None,
) -> None:
    server_root, headers = _resolve(endpoint)
    resp = _request(
        "POST", f"{server_root}/api/v1/models/unload",
        headers=headers, json={"instance_id": instance_id},
        transport=transport, timeout=DEFAULT_TIMEOUT,
    )
    if resp.status_code >= 400:
        raise LmError("upstream", f"{resp.status_code}: {resp.text[:200]}")


# ---------------------------------------------------------------------------
# OpenAI-compat methods ({server_root}/v1/...)
# ---------------------------------------------------------------------------

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
    server_root, headers = _resolve(endpoint)
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
        "POST", f"{server_root}/v1/chat/completions",
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
    if not model.strip():
        raise LmError("config", "model is required")
    if not messages:
        raise LmError("config", "messages must not be empty")
    server_root, headers = _resolve(endpoint)
    payload = {"model": model, "messages": messages, "stream": True}
    try:
        with httpx.Client(transport=transport, timeout=CHAT_TIMEOUT) as client:
            with client.stream(
                "POST", f"{server_root}/v1/chat/completions",
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


def chat_stream_with_tools(
    *,
    endpoint: dict[str, Any],
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    transport: httpx.BaseTransport | None = None,
) -> Iterator[dict[str, Any]]:
    if not model.strip():
        raise LmError("config", "model is required")
    if not messages:
        raise LmError("config", "messages must not be empty")
    server_root, headers = _resolve(endpoint)
    payload = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "stream": True,
    }
    tool_name = ""
    tool_args_buf: list[str] = []
    try:
        with httpx.Client(transport=transport, timeout=CHAT_TIMEOUT) as client:
            with client.stream(
                "POST", f"{server_root}/v1/chat/completions",
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
                        break
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
                        yield {"type": "delta", "content": content}
                    tool_calls = delta.get("tool_calls")
                    if tool_calls:
                        tc = tool_calls[0]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            tool_name = fn["name"]
                        if fn.get("arguments"):
                            tool_args_buf.append(fn["arguments"])
        if tool_name and tool_args_buf:
            raw_args = "".join(tool_args_buf)
            try:
                parsed = json.loads(raw_args)
            except ValueError:
                raise LmError("shape", f"invalid tool call JSON: {raw_args[:200]}")
            yield {"type": "tool_call", "name": tool_name, "arguments": parsed}
    except httpx.TimeoutException as exc:
        raise LmError("timeout", str(exc)) from exc
    except httpx.HTTPError as exc:
        raise LmError("upstream", str(exc)) from exc


RESPONSES_TIMEOUT = httpx.Timeout(180.0, connect=5.0, read=180.0)


def chat_responses_stream(
    *,
    endpoint: dict[str, Any],
    model: str,
    instructions: str,
    user_input: Any,
    tools: list[dict[str, Any]] | None = None,
    integrations: list[Any] | None = None,
    previous_response_id: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> Iterator[dict[str, Any]]:
    """Stream events from LMStudio's /v1/responses endpoint.

    Supports custom function tools AND MCP integrations simultaneously.

    Yields:
        {"type": "delta", "content": "..."}              -- assistant text
        {"type": "function_call", "call_id", "name", "arguments"}  -- custom tool call
        {"type": "mcp_status", "tool", "status"}         -- MCP tool progress
        {"type": "completed", "response_id": "..."}      -- response complete
    """
    if not model.strip():
        raise LmError("config", "model is required")
    server_root, headers = _resolve(endpoint)
    payload: dict[str, Any] = {
        "model": model,
        "input": user_input,
        "instructions": instructions,
        "stream": True,
    }
    if tools:
        payload["tools"] = tools
    if integrations:
        payload["integrations"] = integrations
    if previous_response_id:
        payload["previous_response_id"] = previous_response_id

    fn_calls: dict[str, dict[str, Any]] = {}

    try:
        with httpx.Client(transport=transport, timeout=RESPONSES_TIMEOUT) as client:
            with client.stream(
                "POST", f"{server_root}/v1/responses",
                headers=headers, json=payload,
            ) as resp:
                if resp.status_code >= 400:
                    body = resp.read().decode("utf-8", errors="replace")
                    raise LmError("upstream", f"{resp.status_code}: {body[:200]}")
                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    raw = line[len("data:"):].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    try:
                        data = json.loads(raw)
                    except ValueError:
                        continue
                    etype = data.get("type", "")
                    if etype == "response.output_text.delta":
                        delta = data.get("delta", "")
                        if delta:
                            yield {"type": "delta", "content": delta}
                    elif etype == "response.output_item.added":
                        item = data.get("item") or {}
                        if item.get("type") == "function_call":
                            iid = item.get("id", "")
                            fn_calls[iid] = {
                                "call_id": item.get("call_id", iid),
                                "name": item.get("name", ""),
                                "args": item.get("arguments", "") or "",
                            }
                    elif etype == "response.function_call_arguments.delta":
                        iid = data.get("item_id", "")
                        if iid in fn_calls:
                            fn_calls[iid]["args"] += data.get("delta", "")
                    elif etype == "response.output_item.done":
                        item = data.get("item") or {}
                        itype = item.get("type", "")
                        if itype == "function_call":
                            iid = item.get("id", "")
                            slot = fn_calls.pop(iid, None)
                            args_raw = (slot or {}).get("args") or item.get("arguments", "") or ""
                            try:
                                parsed = json.loads(args_raw) if args_raw else {}
                            except ValueError:
                                parsed = {}
                            yield {
                                "type": "function_call",
                                "call_id": item.get("call_id", iid),
                                "name": item.get("name", "") or (slot or {}).get("name", ""),
                                "arguments": parsed,
                            }
                        elif itype in ("mcp_call", "tool_call"):
                            tool = item.get("name") or item.get("tool", "")
                            ok = item.get("error") in (None, "")
                            yield {
                                "type": "mcp_status",
                                "tool": tool,
                                "status": "done" if ok else "failed",
                            }
                    elif etype == "response.mcp_call.in_progress" or etype == "response.mcp_call.arguments.delta":
                        if etype.endswith("in_progress"):
                            item = data.get("item") or {}
                            yield {
                                "type": "mcp_status",
                                "tool": item.get("name") or item.get("tool", ""),
                                "status": "running",
                            }
                    elif etype == "response.completed":
                        response = data.get("response") or {}
                        yield {
                            "type": "completed",
                            "response_id": response.get("id", ""),
                        }
                    elif etype == "error":
                        err = data.get("error") or {}
                        msg = err.get("message") if isinstance(err, dict) else str(err)
                        raise LmError("upstream", str(msg or "responses stream error"))
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
    if not model.strip():
        raise LmError("config", "model is required")
    if not messages:
        raise LmError("config", "messages must not be empty")
    server_root, headers = _resolve(endpoint)
    payload: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
    if response_format is not None:
        payload["response_format"] = response_format
    resp = _request(
        "POST", f"{server_root}/v1/chat/completions",
        headers=headers, json=payload, transport=transport, timeout=CHAT_TIMEOUT,
    )
    if resp.status_code >= 400:
        raise LmError("upstream", f"{resp.status_code}: {resp.text[:200]}")
    try:
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LmError("shape", f"unexpected response body: {exc}") from exc
    if content is None:
        raise LmError("shape", "content is null — model may have returned a tool call")
    if not isinstance(content, str) or not content.strip():
        raise LmError("shape", "empty content from chat endpoint")
    return content.strip()
