"""HTTP / WebSocket client for ComfyUI.

The Phase 1 surface is the sync `system_stats` + `object_info` pair —
used by the settings connection check and the catalog import. Phase 3
adds the async surface used by the Single Run orchestrator: image
upload, prompt queue, history fetch, interrupt, and a websocket
event stream.

`endpoint` shape: {"server_root": str, "api_key": str | None}.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import urllib.parse
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx
import websockets

DEFAULT_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
UPLOAD_TIMEOUT = httpx.Timeout(60.0, connect=5.0)
QUEUE_TIMEOUT = httpx.Timeout(30.0, connect=5.0)


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


# --------------------------------------------------------------------- #
# Phase 3 — async surface for the Single Run orchestrator.
# --------------------------------------------------------------------- #


async def upload_image(
    *,
    endpoint: dict[str, Any],
    file_path: Path,
    overwrite: bool = True,
    subfolder: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """POST /api/upload/image — upload a file into ComfyUI's input dir.

    Returns the filename ComfyUI assigned (which usually matches the
    upload but may have a suffix when ``overwrite`` is False and a
    same-named file already exists). The Single Run patcher uses the
    returned name as the literal value for the slot's input.
    """
    server_root, headers = _resolve(endpoint)
    url = f"{server_root}/api/upload/image"
    data: dict[str, str] = {"overwrite": "true" if overwrite else "false"}
    if subfolder:
        data["subfolder"] = subfolder
    try:
        with file_path.open("rb") as fh:
            files = {"image": (file_path.name, fh, "application/octet-stream")}
            async with httpx.AsyncClient(transport=transport, timeout=UPLOAD_TIMEOUT) as client:
                resp = await client.post(url, headers=headers, data=data, files=files)
    except FileNotFoundError as exc:
        raise ComfyError("config", f"upload source missing: {exc}") from exc
    except httpx.TimeoutException as exc:
        raise ComfyError("timeout", str(exc)) from exc
    except httpx.HTTPError as exc:
        raise ComfyError("upstream", str(exc)) from exc
    if resp.status_code >= 400:
        raise ComfyError("upstream", f"{resp.status_code}: {resp.text[:200]}")
    try:
        body = resp.json()
    except ValueError as exc:
        raise ComfyError("shape", f"invalid JSON: {exc}") from exc
    name = body.get("name") if isinstance(body, dict) else None
    if not isinstance(name, str) or not name:
        raise ComfyError("shape", "upload response missing 'name'")
    return name


async def queue_prompt(
    *,
    endpoint: dict[str, Any],
    prompt: dict[str, Any],
    client_id: str,
    extra_data: dict[str, Any] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """POST /api/prompt — enqueue a workflow. Returns the ``prompt_id``
    ComfyUI assigned. The orchestrator stores it on `comfy_jobs.prompt_id`
    so it can demux WS events and reconcile history fetches.
    """
    server_root, headers = _resolve(endpoint)
    url = f"{server_root}/api/prompt"
    payload: dict[str, Any] = {"prompt": prompt, "client_id": client_id}
    if extra_data is not None:
        payload["extra_data"] = extra_data
    try:
        async with httpx.AsyncClient(transport=transport, timeout=QUEUE_TIMEOUT) as client:
            resp = await client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        raise ComfyError("timeout", str(exc)) from exc
    except httpx.HTTPError as exc:
        raise ComfyError("upstream", str(exc)) from exc
    if resp.status_code >= 400:
        raise ComfyError("upstream", f"{resp.status_code}: {resp.text[:200]}")
    try:
        body = resp.json()
    except ValueError as exc:
        raise ComfyError("shape", f"invalid JSON: {exc}") from exc
    prompt_id = body.get("prompt_id") if isinstance(body, dict) else None
    if not isinstance(prompt_id, str) or not prompt_id:
        raise ComfyError("shape", "queue response missing 'prompt_id'")
    return prompt_id


async def get_history(
    *,
    endpoint: dict[str, Any],
    prompt_id: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """GET /history/{prompt_id} — fetch outputs after a job finishes.

    The response shape is ``{<prompt_id>: {"prompt": [...], "outputs":
    {<node_id>: {"images": [...]}}, "status": {...}}}``. Returns the
    inner dict for the requested prompt_id, or {} if not present yet
    (ComfyUI's history sometimes lags by a few hundred ms).
    """
    server_root, headers = _resolve(endpoint)
    url = f"{server_root}/history/{prompt_id}"
    try:
        async with httpx.AsyncClient(transport=transport, timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.get(url, headers=headers)
    except httpx.TimeoutException as exc:
        raise ComfyError("timeout", str(exc)) from exc
    except httpx.HTTPError as exc:
        raise ComfyError("upstream", str(exc)) from exc
    if resp.status_code >= 400:
        raise ComfyError("upstream", f"{resp.status_code}: {resp.text[:200]}")
    try:
        body = resp.json()
    except ValueError as exc:
        raise ComfyError("shape", f"invalid JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise ComfyError("shape", "history response is not a JSON object")
    inner = body.get(prompt_id)
    return inner if isinstance(inner, dict) else {}


async def fetch_view_image(
    *,
    endpoint: dict[str, Any],
    filename: str,
    subfolder: str = "",
    folder_type: str = "output",
    transport: httpx.AsyncBaseTransport | None = None,
) -> bytes:
    """GET /view?filename=…&subfolder=…&type=… — download a SaveImage
    output by filename. Used when ComfyUI's output dir isn't directly
    reachable from sd-chisel's process and we have to fall back to the
    HTTP download path."""
    server_root, headers = _resolve(endpoint)
    qs = urllib.parse.urlencode(
        {"filename": filename, "subfolder": subfolder, "type": folder_type}
    )
    url = f"{server_root}/view?{qs}"
    try:
        async with httpx.AsyncClient(transport=transport, timeout=UPLOAD_TIMEOUT) as client:
            resp = await client.get(url, headers=headers)
    except httpx.TimeoutException as exc:
        raise ComfyError("timeout", str(exc)) from exc
    except httpx.HTTPError as exc:
        raise ComfyError("upstream", str(exc)) from exc
    if resp.status_code >= 400:
        raise ComfyError("upstream", f"{resp.status_code}: {resp.text[:200]}")
    return resp.content


async def interrupt(
    *,
    endpoint: dict[str, Any],
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """POST /api/interrupt — best-effort cancel of the currently-executing
    workflow. ComfyUI doesn't take a prompt_id; it interrupts the active
    one and drops everything still queued for the same client_id."""
    server_root, headers = _resolve(endpoint)
    url = f"{server_root}/api/interrupt"
    try:
        async with httpx.AsyncClient(transport=transport, timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.post(url, headers=headers)
    except httpx.TimeoutException as exc:
        raise ComfyError("timeout", str(exc)) from exc
    except httpx.HTTPError as exc:
        raise ComfyError("upstream", str(exc)) from exc
    if resp.status_code >= 400 and resp.status_code != 404:
        # 404 happens when nothing is executing — treat as success.
        raise ComfyError("upstream", f"{resp.status_code}: {resp.text[:200]}")


async def memory_snapshot(
    *,
    endpoint: dict[str, Any],
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, int]:
    """GET /api/system_stats — return a small dict of RAM + VRAM totals
    (system RAM from the top-level ``system`` block, VRAM from the
    first reported CUDA device). Used by the orchestrator to report a
    freed-bytes delta around the unload_comfy stage so the user can
    see the unload had effect (otherwise ComfyUI's /api/free returns
    200 with no body and the operation is invisible).

    Note on RAM: ComfyUI processes ``free_memory`` by calling
    ``e.reset()`` + scheduling ``gc.collect()`` on the worker thread.
    Python's allocator (pymalloc) holds onto arenas after collection,
    so the process's resident set in Task Manager will not always
    drop — but ``ram_free`` from /api/system_stats reflects what the
    OS reports, which is the closest signal we have.
    """
    server_root, headers = _resolve(endpoint)
    url = f"{server_root}/api/system_stats"
    try:
        async with httpx.AsyncClient(transport=transport, timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.get(url, headers=headers)
    except httpx.TimeoutException as exc:
        raise ComfyError("timeout", str(exc)) from exc
    except httpx.HTTPError as exc:
        raise ComfyError("upstream", str(exc)) from exc
    if resp.status_code >= 400:
        raise ComfyError("upstream", f"{resp.status_code}: {resp.text[:200]}")
    body = resp.json() if isinstance(resp.json(), dict) else {}
    if not isinstance(body, dict):
        return {}
    out: dict[str, int] = {}
    system = body.get("system") if isinstance(body, dict) else None
    if isinstance(system, dict):
        out["ram_total"] = int(system.get("ram_total") or 0)
        out["ram_free"] = int(system.get("ram_free") or 0)
    devices = body.get("devices") if isinstance(body, dict) else None
    if isinstance(devices, list) and devices and isinstance(devices[0], dict):
        d = devices[0]
        out["vram_total"] = int(d.get("vram_total") or 0)
        out["vram_free"] = int(d.get("vram_free") or 0)
        out["torch_vram_total"] = int(d.get("torch_vram_total") or 0)
        out["torch_vram_free"] = int(d.get("torch_vram_free") or 0)
    return out


async def manager_reboot(
    *,
    endpoint: dict[str, Any],
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """POST /manager/reboot — bounce the ComfyUI Python process via the
    ComfyUI-Manager extension. The endpoint returns 200 (or simply
    closes the connection) and the ComfyUI process exits and is
    restarted by the launcher (Manager spawns a watchdog).

    Requires the ComfyUI-Manager custom node to be installed on the
    target ComfyUI server. If not installed, the endpoint 404s — the
    caller turns that into a soft warning (the run already succeeded).

    Connection-reset / read-timeout errors are EXPECTED here because
    the server kills its own listener mid-response; we treat any of
    those as success.
    """
    server_root, headers = _resolve(endpoint)
    url = f"{server_root}/manager/reboot"
    try:
        async with httpx.AsyncClient(
            transport=transport, timeout=httpx.Timeout(5.0, connect=5.0),
        ) as client:
            resp = await client.post(url, headers=headers)
    except (httpx.RemoteProtocolError, httpx.ReadError, httpx.ReadTimeout):
        # Server tore the socket down while answering — this is the
        # normal happy path for a process-restart endpoint.
        return
    except httpx.HTTPError as exc:
        raise ComfyError("upstream", str(exc)) from exc
    if resp.status_code == 404:
        raise ComfyError(
            "upstream",
            "ComfyUI-Manager not installed (POST /manager/reboot returned 404)",
        )
    if resp.status_code >= 400:
        raise ComfyError("upstream", f"{resp.status_code}: {resp.text[:200]}")


async def free_memory(
    *,
    endpoint: dict[str, Any],
    unload_models: bool = True,
    free_memory: bool = True,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """POST /api/free — drop loaded models / VRAM.

    Fire-and-forget — ComfyUI returns 200 with no body once the unload
    completes. The orchestrator calls this after a Single Run finishes
    so the next session (or LMStudio for the next run's agents) can
    reclaim the VRAM. Soft-fails on connection errors via the caller's
    try/except — the run already succeeded, so an unload failure is a
    warning, not an error.
    """
    server_root, headers = _resolve(endpoint)
    url = f"{server_root}/api/free"
    payload = {"unload_models": unload_models, "free_memory": free_memory}
    try:
        async with httpx.AsyncClient(transport=transport, timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        raise ComfyError("timeout", str(exc)) from exc
    except httpx.HTTPError as exc:
        raise ComfyError("upstream", str(exc)) from exc
    if resp.status_code >= 400:
        raise ComfyError("upstream", f"{resp.status_code}: {resp.text[:200]}")


async def stream_events(
    *,
    endpoint: dict[str, Any],
    client_id: str,
    stop: asyncio.Event | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Yield JSON events from ComfyUI's `/ws?clientId=…` socket.

    ComfyUI emits text frames (the JSON event types — `executing`,
    `progress`, `executed`, `execution_start`, `execution_success`,
    `execution_error`, `status`, …) and binary frames for the live
    preview image stream. We yield only the text events as parsed
    dicts; binary frames are dropped on the floor (the orchestrator
    doesn't show previews).

    The caller drives the lifetime — pass an `asyncio.Event` and set
    it to stop streaming, or break out of the iterator. Reconnect on
    transient drops is the orchestrator's job (the per-job pipeline
    can re-subscribe and resume from the history endpoint).
    """
    server_root, headers = _resolve(endpoint)
    if server_root.startswith("https://"):
        ws_root = "wss://" + server_root[len("https://"):]
    elif server_root.startswith("http://"):
        ws_root = "ws://" + server_root[len("http://"):]
    else:
        ws_root = server_root
    url = f"{ws_root}/ws?clientId={urllib.parse.quote(client_id)}"
    try:
        async with websockets.connect(
            url, additional_headers=headers, max_size=None
        ) as ws:
            while True:
                if stop is not None and stop.is_set():
                    return
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                except websockets.ConnectionClosed as exc:
                    raise ComfyError("upstream", f"ws closed: {exc}") from exc
                if isinstance(raw, (bytes, bytearray)):
                    # Binary frame = preview image; orchestrator skips.
                    continue
                try:
                    event = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(event, dict):
                    yield event
    except OSError as exc:
        raise ComfyError("upstream", f"ws connect failed: {exc}") from exc


@contextlib.asynccontextmanager
async def event_stream(
    *,
    endpoint: dict[str, Any],
    client_id: str,
) -> AsyncIterator[AsyncIterator[dict[str, Any]]]:
    """Context manager wrapping ``stream_events`` so the caller can
    ``async with`` and break out cleanly. Yields the same async
    iterator; on exit, sets the stop flag so the underlying socket
    closes deterministically."""
    stop = asyncio.Event()
    try:
        yield stream_events(endpoint=endpoint, client_id=client_id, stop=stop)
    finally:
        stop.set()
