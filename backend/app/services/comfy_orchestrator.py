"""Single Run orchestrator — drives the full pipeline from "the user
clicked Single Run" to "result image is on disk + gallery card
appears".

Stages (each emits ``{"stage": <name>, "event": ..., ...}`` to the
job's ``RunChannel``):

1. ``validate``       — confirm every binding=llm slot has a bound
                        agent output, every required user_image slot
                        has an image picked. Raises before snapshot.
2. ``snapshot``       — create the comfy_jobs row, flip to running.
3. ``agents``         — for each agent: emit started, run via
                        comfy_agent_runner, emit finished.
4. ``unload_lm``      — best-effort LMStudio unload-all to free VRAM.
5. ``upload_inputs``  — upload session source images for every wired
                        user_image slot; the returned ComfyUI filename
                        becomes the slot's value.
6. ``patch``          — run comfy_graph_patcher with the merged
                        payload (agents' last_values + frozen +
                        user_image filenames + overrides).
7. ``queue``          — POST /api/prompt; capture prompt_id.
8. ``execute``        — drive the WS consumer; on each `executed`
                        event for a SaveImage in the output map,
                        capture the file into
                        data/images/<sid>/output/<gid>/<label>.<ext>.
9. ``save``           — flip status to success.
10. ``cleanup``       — apply the per-session input_cleanup policy.
11. ``done``          — terminator event with overall status.

Most stages are best-effort with "warning" events on soft failure;
a hard failure short-circuits to cleanup → done with status=error.

The orchestrator runs as an asyncio.Task spawned by the API layer.
It is responsible for closing the channel on exit (``finally``)
so the SSE endpoint terminates cleanly even on crash.
"""
from __future__ import annotations

import asyncio
import shutil
import sqlite3
import time
import traceback
from pathlib import Path
from typing import Any

from app.config import resolve_data_root
from app.services import (
    comfy_agent_runner,
    comfy_client,
    comfy_graph_patcher,
    comfy_paths,
    comfy_run_streams,
    lmstudio_client,
)
from app.storage import (
    comfy_jobs_repo,
    comfy_session_agent_repo as agent_repo,
    comfy_workflow_repo,
    images as images_storage,
    session_repo,
    settings_repo,
    source_image_repo,
)
from app.storage.db import connect
from app.utils.generation_id import new_generation_id


class ValidationError(Exception):
    """Raised by ``validate`` when the request can't proceed.

    The orchestrator API layer catches this and returns 409 with the
    detail message before the job row is created — keeping the
    history clean of "never-ran" rows.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


# Active orchestrator tasks, kept here so they aren't garbage-collected
# while running. The asyncio.create_task return value is the only
# strong reference and the API layer doesn't keep one.
_TASKS: set[asyncio.Task[Any]] = set()


def _publish(channel: comfy_run_streams.RunChannel, event: dict[str, Any]) -> None:
    """Stamp the event with a monotonic ts and push to the channel.

    Centralised so every event has a consistent shape.
    """
    event = {**event, "ts": int(time.time() * 1000)}
    channel.publish(event)


def _resolve_lm_endpoint(conn: sqlite3.Connection) -> dict[str, Any]:
    cfg = settings_repo.get_lmstudio(conn)
    return {
        "server_root": cfg["lmstudio_url"],
        "api_key": cfg["lmstudio_api_key"],
    }


def _resolve_comfy_endpoint(conn: sqlite3.Connection) -> dict[str, Any]:
    cfg = settings_repo.get_comfyui(conn)
    return {
        "server_root": cfg["comfyui_url"],
        "api_key": cfg["comfyui_api_key"],
    }


def _new_client_id(job_id: str) -> str:
    """ComfyUI's WS demux key. We use the job id directly so multiple
    runs from the same process get separate event streams."""
    return f"sd-chisel-{job_id}"


# --- public entrypoint --------------------------------------------------


async def start_single_run(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    payload_overrides: dict[str, Any] | None = None,
    image_bindings: dict[str, str | None] | None = None,
    rerun_agents: bool = True,
) -> dict[str, Any]:
    """Validate the request, create the job row, spawn the pipeline
    task, and return ``{job_id, generation_id}``.

    The validate + snapshot stage runs on the request connection so
    pre-flight failures don't leak job rows. Once snapshotted, the
    pipeline runs in the background and opens its own connections;
    subscribers attach to the run channel via the SSE endpoint.
    """
    payload_overrides = payload_overrides or {}
    image_bindings = image_bindings or {}

    snapshot = _validate_and_snapshot(
        conn,
        session_id=session_id,
        image_bindings=image_bindings,
    )

    channel = await comfy_run_streams.open_channel(snapshot["job_id"])
    _publish(channel, {"stage": "validate", "event": "succeeded"})
    _publish(channel, {
        "stage": "snapshot",
        "event": "succeeded",
        "job_id": snapshot["job_id"],
        "generation_id": snapshot["generation_id"],
    })

    # Drop any closed channels past the grace window — opportunistic GC.
    await comfy_run_streams.gc_closed_channels()

    task = asyncio.create_task(_run_pipeline(
        job_id=snapshot["job_id"],
        session_id=session_id,
        workflow_id=snapshot["workflow_id"],
        slot_map_snapshot=snapshot["slot_map"],
        agents_snapshot=snapshot["agents"],
        payload_overrides=payload_overrides,
        image_bindings=image_bindings,
        rerun_agents=rerun_agents,
        channel=channel,
    ))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return {
        "job_id": snapshot["job_id"],
        "generation_id": snapshot["generation_id"],
    }


# --- validate + snapshot ------------------------------------------------


def _validate_and_snapshot(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    image_bindings: dict[str, str | None],
) -> dict[str, Any]:
    """Do the structural checks + freeze the slot map / agent list,
    then write the comfy_jobs row. Raises ValidationError on
    structural failure — the API maps to 409."""
    session = session_repo.get_session(conn, session_id)
    if session is None:
        raise ValidationError("session not found")
    if session.get("session_type") not in ("comfy", "comfy_mock"):
        raise ValidationError("not a comfy session")
    workflow_id = session.get("comfy_workflow_id")
    if not workflow_id:
        raise ValidationError("session has no bound workflow")
    workflow = comfy_workflow_repo.get_workflow(conn, workflow_id)
    if workflow is None:
        raise ValidationError("bound workflow not found")
    slot_map_blob = workflow.get("slot_map") or {}
    slot_map = list(slot_map_blob.get("slots") or [])
    if not slot_map:
        raise ValidationError("workflow has no slot map saved")

    # Refuse to start when a run is already in flight for this session.
    in_flight = comfy_jobs_repo.find_running_job(conn, session_id)
    if in_flight is not None:
        raise ValidationError(
            f"run already in progress (job {in_flight['id']})",
        )

    agents = agent_repo.list_agents(conn, session_id)

    # Validate llm slot coverage.
    bound_labels: set[str] = set()
    for a in agents:
        for o in a.get("output_slots") or []:
            target = (o.get("bound_to") or {}).get("workflow_slot_label")
            if isinstance(target, str):
                bound_labels.add(target)

    missing_llm: list[str] = []
    missing_image: list[str] = []
    for s in slot_map:
        binding = s.get("binding")
        label = s.get("label")
        if not isinstance(label, str):
            continue
        if binding == "llm" and label not in bound_labels:
            missing_llm.append(label)
        elif binding == "user_image":
            picked = image_bindings.get(label)
            if not isinstance(picked, str) or not picked:
                # User image is required; the modal sends the resolved
                # session image id under the slot's label.
                missing_image.append(label)

    if missing_llm:
        raise ValidationError(
            f"missing agent output for llm slot(s): {', '.join(missing_llm)}",
        )
    if missing_image:
        raise ValidationError(
            f"missing image binding for user_image slot(s): {', '.join(missing_image)}",
        )

    # Snapshot — freeze slot map + agents into the job row.
    generation_id = new_generation_id()

    job = comfy_jobs_repo.create_job(
        conn,
        session_id=session_id,
        workflow_id=workflow_id,
        generation_id=generation_id,
        slot_map_snapshot=slot_map,
        agents_snapshot=agents,
    )
    return {
        "job_id": job["id"],
        "workflow_id": workflow_id,
        "generation_id": generation_id,
        "slot_map": slot_map,
        "agents": agents,
    }


# --- pipeline -----------------------------------------------------------


async def _run_pipeline(
    *,
    job_id: str,
    session_id: str,
    workflow_id: str,
    slot_map_snapshot: list[dict[str, Any]],
    agents_snapshot: list[dict[str, Any]],
    payload_overrides: dict[str, Any],
    image_bindings: dict[str, str | None],
    rerun_agents: bool,
    channel: comfy_run_streams.RunChannel,
) -> None:
    final_status: str = "success"
    error_message: str | None = None
    upload_subfolder: str | None = None
    try:
        # 3. agents
        if rerun_agents:
            await _stage_agents(
                channel=channel,
                session_id=session_id,
                agents=agents_snapshot,
            )
            # Refresh agents (last_value updated).
            with connect() as conn:
                agents_snapshot = agent_repo.list_agents(conn, session_id)
        else:
            _publish(channel, {"stage": "agents", "event": "skipped"})

        # 4. unload_lm — best-effort.
        await _stage_unload_lm(channel=channel)

        # 5. upload_inputs — for each binding=user_image slot.
        upload_subfolder = f"sd-chisel/{job_id}"
        uploaded = await _stage_upload_inputs(
            channel=channel,
            slot_map=slot_map_snapshot,
            image_bindings=image_bindings,
            session_id=session_id,
            upload_subfolder=upload_subfolder,
        )

        # 6. patch.
        payload = _build_payload(
            slot_map=slot_map_snapshot,
            agents=agents_snapshot,
            payload_overrides=payload_overrides,
            uploaded_filenames=uploaded,
        )
        with connect() as conn:
            comfy_jobs_repo.set_payload(conn, job_id, payload)
        graph = await asyncio.to_thread(_load_graph, workflow_id)
        patch_result = comfy_graph_patcher.patch_graph(
            graph=graph, slot_map=slot_map_snapshot, payload=payload,
        )
        _publish(channel, {
            "stage": "patch",
            "event": "succeeded",
            "patched": [
                {"slot_label": l, "node_id": n, "input_name": i}
                for (l, n, i) in patch_result.patched_inputs
            ],
            "warnings": list(patch_result.warnings),
        })

        # 7. queue.
        prompt_id = await _stage_queue(
            channel=channel,
            job_id=job_id,
            patched_graph=patch_result.graph,
        )

        # 8. execute.
        await _stage_execute(
            channel=channel,
            job_id=job_id,
            session_id=session_id,
            prompt_id=prompt_id,
            workflow_id=workflow_id,
        )

        # 9. save.
        with connect() as conn:
            comfy_jobs_repo.set_status(conn, job_id, "success")
        _publish(channel, {"stage": "save", "event": "succeeded"})
    except ValidationError as exc:
        # Shouldn't happen — validation runs before snapshot — but
        # keep a defensive arm in case a downstream stage finds
        # something the pre-flight missed.
        final_status = "error"
        error_message = exc.detail
        _publish(channel, {"stage": "validate", "event": "failed", "message": exc.detail})
    except Exception as exc:  # noqa: BLE001 — orchestrator-level failure mode
        final_status = "error"
        error_message = f"{type(exc).__name__}: {exc}"
        _publish(channel, {
            "stage": "execute",
            "event": "failed",
            "message": error_message,
            "trace": traceback.format_exc(limit=4),
        })
    finally:
        # 10. cleanup — always runs, even on error.
        try:
            await _stage_cleanup(
                channel=channel,
                session_id=session_id,
                upload_subfolder=upload_subfolder,
            )
        except Exception as exc:  # noqa: BLE001
            _publish(channel, {
                "stage": "cleanup",
                "event": "failed",
                "message": f"{type(exc).__name__}: {exc}",
            })

        if final_status != "success":
            with connect() as conn:
                comfy_jobs_repo.set_status(
                    conn, job_id, final_status,
                    error_message=error_message,
                )

        # 11. done — terminator. The SSE endpoint stops at this event.
        _publish(channel, {"stage": "done", "status": final_status})
        channel.close()


# --- stages -------------------------------------------------------------


async def _stage_agents(
    *,
    channel: comfy_run_streams.RunChannel,
    session_id: str,
    agents: list[dict[str, Any]],
) -> None:
    _publish(channel, {"stage": "agents", "event": "started", "count": len(agents)})
    for agent in agents:
        agent_id = agent["id"]
        _publish(channel, {
            "stage": "agents",
            "event": "agent_started",
            "agent_id": agent_id,
            "name": agent.get("name"),
            "model": agent.get("model_name"),
        })
        try:
            updated = await asyncio.to_thread(
                _run_agent_sync, session_id=session_id, agent_id=agent_id,
            )
            outputs = {
                o["label"]: o.get("last_value")
                for o in updated.get("output_slots", [])
                if o.get("label")
            }
            _publish(channel, {
                "stage": "agents",
                "event": "agent_finished",
                "agent_id": agent_id,
                "outputs": outputs,
            })
        except Exception as exc:  # noqa: BLE001
            _publish(channel, {
                "stage": "agents",
                "event": "agent_failed",
                "agent_id": agent_id,
                "message": f"{type(exc).__name__}: {exc}",
            })
            raise
    _publish(channel, {"stage": "agents", "event": "succeeded"})


def _run_agent_sync(*, session_id: str, agent_id: str) -> dict[str, Any]:
    """Sync wrapper around comfy_agent_runner.run_agent for the
    asyncio.to_thread offload. Uses its own connection — sqlite
    Connection objects can't move between threads, and we're already
    on a worker thread here."""
    with connect() as conn:
        return comfy_agent_runner.run_agent(
            conn,
            session_id=session_id,
            agent_id=agent_id,
        )


async def _stage_unload_lm(
    *, channel: comfy_run_streams.RunChannel,
) -> None:
    _publish(channel, {"stage": "unload_lm", "event": "started"})
    try:
        with connect() as conn:
            cfg = settings_repo.get_lmstudio(conn)
        if not cfg.get("lmstudio_url"):
            _publish(channel, {
                "stage": "unload_lm",
                "event": "warning",
                "message": "LMStudio URL not configured; skipping unload",
            })
            return
        endpoint = {
            "server_root": cfg["lmstudio_url"],
            "api_key": cfg["lmstudio_api_key"],
        }
        ids = await asyncio.to_thread(
            lmstudio_client.list_loaded_instance_ids, endpoint=endpoint,
        )
        for iid in ids:
            await asyncio.to_thread(
                lmstudio_client.unload_model,
                endpoint=endpoint, instance_id=iid,
            )
        _publish(channel, {
            "stage": "unload_lm",
            "event": "succeeded",
            "unloaded": len(ids),
        })
    except Exception as exc:  # noqa: BLE001 — soft-fail
        _publish(channel, {
            "stage": "unload_lm",
            "event": "warning",
            "message": f"{type(exc).__name__}: {exc}",
        })


async def _stage_upload_inputs(
    *,
    channel: comfy_run_streams.RunChannel,
    slot_map: list[dict[str, Any]],
    image_bindings: dict[str, str | None],
    session_id: str,
    upload_subfolder: str,
) -> dict[str, str]:
    """Upload one image per binding=user_image slot. Returns a map
    of slot_label → ComfyUI filename."""
    _publish(channel, {"stage": "upload_inputs", "event": "started"})
    uploaded: dict[str, str] = {}
    with connect() as conn:
        endpoint = _resolve_comfy_endpoint(conn)
        sources = source_image_repo.list_for_session(conn, session_id)
    by_id = {s["id"]: s for s in sources}
    data_root = resolve_data_root()

    for slot in slot_map:
        if slot.get("binding") != "user_image":
            continue
        label = slot.get("label")
        if not isinstance(label, str):
            continue
        image_id = image_bindings.get(label)
        if not image_id:
            continue
        source = by_id.get(image_id)
        if source is None:
            _publish(channel, {
                "stage": "upload_inputs",
                "event": "warning",
                "slot_label": label,
                "message": "bound image not found; skipping slot",
            })
            continue
        local_path = data_root / source["path"]
        if not local_path.exists():
            _publish(channel, {
                "stage": "upload_inputs",
                "event": "warning",
                "slot_label": label,
                "message": "source file missing on disk; skipping slot",
            })
            continue
        _publish(channel, {
            "stage": "upload_inputs",
            "event": "upload_started",
            "slot_label": label,
            "filename": local_path.name,
        })
        filename = await comfy_client.upload_image(
            endpoint=endpoint,
            file_path=local_path,
            subfolder=upload_subfolder,
        )
        # ComfyUI returns the bare filename; the patcher needs
        # `<subfolder>/<filename>` for LoadImage to find it.
        full = f"{upload_subfolder}/{filename}" if upload_subfolder else filename
        uploaded[label] = full
        _publish(channel, {
            "stage": "upload_inputs",
            "event": "upload_finished",
            "slot_label": label,
            "comfy_filename": full,
        })
    _publish(channel, {"stage": "upload_inputs", "event": "succeeded"})
    return uploaded


async def _stage_queue(
    *,
    channel: comfy_run_streams.RunChannel,
    job_id: str,
    patched_graph: dict[str, Any],
) -> str:
    _publish(channel, {"stage": "queue", "event": "started"})
    with connect() as conn:
        endpoint = _resolve_comfy_endpoint(conn)
    client_id = _new_client_id(job_id)
    prompt_id = await comfy_client.queue_prompt(
        endpoint=endpoint, prompt=patched_graph, client_id=client_id,
    )
    with connect() as conn:
        comfy_jobs_repo.set_prompt_id(conn, job_id, prompt_id)
    _publish(channel, {
        "stage": "queue",
        "event": "succeeded",
        "prompt_id": prompt_id,
        "client_id": client_id,
    })
    return prompt_id


async def _stage_execute(
    *,
    channel: comfy_run_streams.RunChannel,
    job_id: str,
    session_id: str,
    prompt_id: str,
    workflow_id: str,
) -> None:
    _publish(channel, {"stage": "execute", "event": "started"})
    with connect() as conn:
        endpoint = _resolve_comfy_endpoint(conn)
        workflow = comfy_workflow_repo.get_workflow(conn, workflow_id)
        job = comfy_jobs_repo.get_job(conn, job_id)
    output_map_blob = (workflow or {}).get("output_slot_map") or {}
    output_map_entries = list(output_map_blob.get("outputs") or [])
    output_map_by_node: dict[str, str] = {
        e["node_id"]: e.get("label", "")
        for e in output_map_entries
        if isinstance(e, dict) and isinstance(e.get("node_id"), str)
    }
    generation_id = (job or {}).get("generation_id", "")

    client_id = _new_client_id(job_id)
    has_primary = False
    async with comfy_client.event_stream(
        endpoint=endpoint, client_id=client_id,
    ) as events:
        async for event in events:
            etype = event.get("type")
            data = event.get("data") or {}
            ev_prompt_id = data.get("prompt_id")
            if ev_prompt_id and ev_prompt_id != prompt_id:
                # Another job's events on the same client_id — should
                # not happen with our per-job client_id, but
                # belt-and-braces.
                continue

            if etype == "executing":
                # When `node` is None the workflow is done; ComfyUI
                # closes its end of the stream shortly after.
                node_id = data.get("node")
                if node_id is None:
                    _publish(channel, {
                        "stage": "execute",
                        "event": "execution_completed",
                    })
                    break
                _publish(channel, {
                    "stage": "execute",
                    "event": "executing",
                    "node_id": node_id,
                })
            elif etype == "progress":
                _publish(channel, {
                    "stage": "execute",
                    "event": "progress",
                    "value": data.get("value"),
                    "max": data.get("max"),
                    "node_id": data.get("node"),
                })
            elif etype == "executed":
                node_id = str(data.get("node") or "")
                images = (data.get("output") or {}).get("images") or []
                slot_label = output_map_by_node.get(node_id)
                for idx, img in enumerate(images):
                    is_primary = not has_primary
                    has_primary = True
                    saved = await _save_output(
                        endpoint=endpoint,
                        session_id=session_id,
                        generation_id=generation_id,
                        slot_label=slot_label,
                        node_id=node_id,
                        output_index=idx,
                        comfy_filename=str(img.get("filename") or ""),
                        comfy_subfolder=str(img.get("subfolder") or ""),
                        comfy_type=str(img.get("type") or "output"),
                        is_primary=is_primary,
                        job_id=job_id,
                    )
                    _publish(channel, {
                        "stage": "execute",
                        "event": "image_ready",
                        "slot_label": slot_label,
                        "node_id": node_id,
                        "output_index": idx,
                        "url": saved["url"],
                        "is_primary": is_primary,
                    })
            elif etype == "execution_error":
                msg = data.get("exception_message") or "ComfyUI execution error"
                raise RuntimeError(str(msg))
            elif etype == "execution_success":
                # ComfyUI emits this when the queue entry finishes
                # cleanly. We've already broken on `executing` with
                # node=None, but keep the arm for completeness.
                break
    _publish(channel, {"stage": "execute", "event": "succeeded"})


async def _save_output(
    *,
    endpoint: dict[str, Any],
    session_id: str,
    generation_id: str,
    slot_label: str | None,
    node_id: str,
    output_index: int,
    comfy_filename: str,
    comfy_subfolder: str,
    comfy_type: str,
    is_primary: bool,
    job_id: str,
) -> dict[str, Any]:
    """Persist a SaveImage output to
    ``data/images/<sid>/output/<gid>/<label-or-fallback>.<ext>`` —
    direct fs copy when ComfyUI's output dir is reachable, else
    HTTP download via /view."""
    out_dir = images_storage.session_output_dir(session_id, generation_id)
    ext = Path(comfy_filename).suffix or ".png"
    base = slot_label if (slot_label and not Path(slot_label).suffix) else (
        Path(comfy_filename).stem or f"node_{node_id}_{output_index}"
    )
    if output_index > 0:
        base = f"{base}_{output_index}"
    target = out_dir / f"{base}{ext}"
    if target.exists():
        target = out_dir / f"{base}_{node_id}_{output_index}{ext}"

    bytes_written = _try_local_copy(
        comfy_filename=comfy_filename,
        comfy_subfolder=comfy_subfolder,
        comfy_type=comfy_type,
        target=target,
    )
    if bytes_written is None:
        data = await comfy_client.fetch_view_image(
            endpoint=endpoint,
            filename=comfy_filename,
            subfolder=comfy_subfolder,
            folder_type=comfy_type,
        )
        target.write_bytes(data)

    rel = target.relative_to(resolve_data_root())
    rel_posix = str(rel).replace("\\", "/")
    with connect() as conn:
        comfy_jobs_repo.add_output(
            conn,
            job_id=job_id,
            slot_label=slot_label,
            node_id=node_id,
            output_index=output_index,
            path=rel_posix,
            is_primary=is_primary,
        )
    return {
        "path": rel_posix,
        "url": f"/media/{rel_posix}",
    }


def _try_local_copy(
    *,
    comfy_filename: str,
    comfy_subfolder: str,
    comfy_type: str,
    target: Path,
) -> int | None:
    """Copy from ComfyUI's output dir directly when reachable.
    Returns the byte count on success, None when the dir resolver
    can't find a reachable path or the source file doesn't exist."""
    with connect() as conn:
        cfg = settings_repo.get_comfyui(conn)
    if comfy_type == "input":
        root = comfy_paths.resolve_input_dir(cfg)
    else:
        root = comfy_paths.resolve_output_dir(cfg)
    if root is None:
        return None
    src = root / comfy_subfolder / comfy_filename if comfy_subfolder else root / comfy_filename
    if not src.exists():
        return None
    shutil.copyfile(src, target)
    return target.stat().st_size


async def _stage_cleanup(
    *,
    channel: comfy_run_streams.RunChannel,
    session_id: str,
    upload_subfolder: str | None,
) -> None:
    _publish(channel, {"stage": "cleanup", "event": "started"})
    if upload_subfolder is None:
        _publish(channel, {"stage": "cleanup", "event": "skipped"})
        return
    with connect() as conn:
        session = session_repo.get_session(conn, session_id)
        cfg = settings_repo.get_comfyui(conn)
    if (session or {}).get("comfy_input_cleanup") != "delete":
        _publish(channel, {"stage": "cleanup", "event": "succeeded", "kept": True})
        return
    input_dir = comfy_paths.resolve_input_dir(cfg)
    if input_dir is None:
        _publish(channel, {
            "stage": "cleanup",
            "event": "warning",
            "message": "input dir not reachable; soft-degrading to keep",
        })
        return
    folder = input_dir / upload_subfolder
    if folder.exists():
        try:
            shutil.rmtree(folder)
        except OSError as exc:
            _publish(channel, {
                "stage": "cleanup",
                "event": "warning",
                "message": f"rmtree failed: {exc}",
            })
            return
    _publish(channel, {"stage": "cleanup", "event": "succeeded", "kept": False})


# --- helpers -----------------------------------------------------------


def _load_graph(workflow_id: str) -> dict[str, Any]:
    with connect() as conn:
        wf = comfy_workflow_repo.get_workflow(conn, workflow_id)
    if wf is None:
        raise RuntimeError("workflow disappeared mid-run")
    return wf["graph"]


def _build_payload(
    *,
    slot_map: list[dict[str, Any]],
    agents: list[dict[str, Any]],
    payload_overrides: dict[str, Any],
    uploaded_filenames: dict[str, str],
) -> dict[str, Any]:
    """Merge agent last_values + frozen + uploaded filenames into the
    flat slot label → value map the patcher consumes. Per-call overrides
    win at every layer."""
    bound: dict[str, Any] = {}

    # Index agent outputs by bound workflow slot label.
    for a in agents:
        for o in a.get("output_slots") or []:
            target = (o.get("bound_to") or {}).get("workflow_slot_label")
            if isinstance(target, str):
                bound[target] = o.get("last_value")

    out: dict[str, Any] = {}
    for slot in slot_map:
        label = slot.get("label")
        if not isinstance(label, str):
            continue
        binding = slot.get("binding")
        if binding == "llm":
            value = bound.get(label)
        elif binding == "frozen":
            value = (slot.get("metadata") or {}).get("value")
        elif binding == "user_image":
            value = uploaded_filenames.get(label)
        else:
            continue
        if label in payload_overrides:
            value = payload_overrides[label]
        if value is not None:
            out[label] = value
    return out
