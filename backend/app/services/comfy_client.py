"""HTTP client for ComfyUI.

Phase 1 only needs the connection check — verify the configured URL is
reachable and that ComfyUI responds with system stats. Subsequent
phases will extend this module with workflow queueing, websocket
subscription, and image fetching (see docs/comfy-workflow-plan.md).

`endpoint` shape: {"server_root": str, "api_key": str | None}
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import httpx

DEFAULT_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


@dataclass
class ComfySystemStats:
    """A subset of /api/system_stats. We only surface what the settings
    section displays after a successful connection check."""
    comfyui_version: str | None
    python_version: str | None
    os: str | None


class ComfyError(Exception):
    def __init__(
        self,
        kind: Literal["upstream", "timeout", "shape", "config"],
        detail: str,
    ) -> None:
        super().__init__(f"ComfyError({kind}): {detail}")
        self.kind = kind
        self.detail = detail


def _resolve(endpoint: dict[str, Any]) -> tuple[str, dict[str, str]]:
    server_root = str(endpoint.get("server_root") or "").strip().rstrip("/")
    if not server_root:
        raise ComfyError("config", "ComfyUI URL is not configured")
    headers: dict[str, str] = {}
    api_key = endpoint.get("api_key") or None
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return server_root, headers


def system_stats(
    *,
    endpoint: dict[str, Any],
    transport: httpx.BaseTransport | None = None,
) -> ComfySystemStats:
    """GET /api/system_stats — used by the settings connection check."""
    body = _get_json(endpoint, "/api/system_stats", transport)
    system = body.get("system") if isinstance(body, dict) else None
    if not isinstance(system, dict):
        raise ComfyError("shape", "missing 'system' object in response")
    return ComfySystemStats(
        comfyui_version=_str_or_none(system.get("comfyui_version")),
        python_version=_str_or_none(system.get("python_version")),
        os=_str_or_none(system.get("os")),
    )


# Larger timeout — object_info on a heavily-loaded ComfyUI can take a
# few seconds (a couple of thousand class_types serialised).
OBJECT_INFO_TIMEOUT = httpx.Timeout(30.0, connect=5.0)


def object_info(
    *,
    endpoint: dict[str, Any],
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """GET /api/object_info — full per-class_type schema dictionary.

    The response is a dict keyed by class_type. Each value carries
    ``input``, ``output``, ``python_module``, ``display_name``,
    ``description``, ``category`` and other fields (see ComfyUI source
    for the full shape). Phase 1 uses ``python_module`` to map nodes to
    packs and the rest as the raw schema for the catalog.
    """
    body = _get_json(endpoint, "/api/object_info", transport, OBJECT_INFO_TIMEOUT)
    if not isinstance(body, dict):
        raise ComfyError("shape", "object_info response is not a JSON object")
    return body


def _get_json(
    endpoint: dict[str, Any],
    path: str,
    transport: httpx.BaseTransport | None,
    timeout: httpx.Timeout = DEFAULT_TIMEOUT,
) -> Any:
    server_root, headers = _resolve(endpoint)
    url = f"{server_root}{path}"
    try:
        with httpx.Client(transport=transport, timeout=timeout) as client:
            resp = client.get(url, headers=headers)
    except httpx.TimeoutException as exc:
        raise ComfyError("timeout", str(exc)) from exc
    except httpx.HTTPError as exc:
        raise ComfyError("upstream", str(exc)) from exc
    if resp.status_code >= 400:
        raise ComfyError("upstream", f"{resp.status_code}: {resp.text[:200]}")
    try:
        return resp.json()
    except ValueError as exc:
        raise ComfyError("shape", f"invalid JSON: {exc}") from exc


def _str_or_none(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None
