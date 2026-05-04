"""Per-node import wizard — runs the four stages in sequence and emits
events suitable for an SSE stream.

Stages:
  1. locate_pack   — walk <comfyui_path>/custom_nodes/, read pyproject
                     and README for the resolved pack.
  2. fetch_schema  — pull the class_type's INPUT_TYPES from /api/object_info.
  3. enrich_llm    — feed (README + raw schema + display_name) to LMStudio,
                     get a short markdown description for the node, validate
                     the response shape.
  4. persist       — upsert comfy_packs + comfy_nodes with all four stages'
                     outputs.

Phase 1 simplification: this is a single-shot run. If a stage fails the
client gets an error event; to retry, the user re-POSTs and stages run
from scratch. Per-stage retry that preserves earlier outputs is parked
for a later iteration — every stage is fast except the LLM call, and
that's the one most likely to need a redo anyway.

Phase 2 cleanup: the wizard previously asked the LLM for a per-input
``role_hint`` from a closed enum. That field is unused — slot mapping
is workflow-level and manual (see Q7 in docs/comfy-workflow-plan.md),
so the LLM is now asked only for ``description_md``. ``inputs_semantic``
is still written to the catalog but only carries optional notes.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, AsyncIterator

from app.services import comfy_client, comfy_packs, lmstudio_client
from app.storage import comfy_catalog_repo


_LLM_SYSTEM = (
    "You analyse a ComfyUI custom node and produce a short structured "
    "summary as a single JSON object. Output VALID JSON ONLY — no prose, "
    "no <think> block, no markdown fences. Example:\n"
    '{\n'
    '  "description_md": "Samples a latent image from a model.",\n'
    '  "inputs": [\n'
    '    {"name": "seed", "notes": "Random seed."},\n'
    '    {"name": "model", "notes": null}\n'
    '  ]\n'
    '}\n'
    "Rules: ``description_md`` is one or two sentences in markdown. "
    "Every input 'name' MUST match an input name from the schema "
    "verbatim — do not rename, translate, or invent inputs. ``notes`` "
    "is a short string or null. You may omit inputs entirely; the "
    "schema is canonical. Do not output any other fields."
)


# LMStudio only accepts "json_schema" or "text"; json_object isn't a
# supported value there. Plain "text" mode plus a strict system prompt
# plus the post-hoc JSON-extractor below produces good results across
# all model families and dodges the silent-empty-content failure that
# strict json_schema hits with some reasoning-distilled models.
_LLM_RESPONSE_FORMAT: dict[str, str] = {"type": "text"}


def _extract_json_object(raw: str) -> str:
    """Pull the first top-level JSON object out of ``raw``. Tolerates
    leading prose, code-fence wrappers, and a trailing newline."""
    s = raw.strip()
    if s.startswith("```"):
        # Drop the opening fence (with or without a language tag).
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()
    start = s.find("{")
    if start < 0:
        return s
    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(s[start:], start=start):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return s[start:]


def _extract_input_names(inputs_raw: Any) -> list[str]:
    """Flat list of input names from the raw INPUT_TYPES dict."""
    if not isinstance(inputs_raw, dict):
        return []
    names: list[str] = []
    seen: set[str] = set()
    for kind in ("required", "optional"):
        section = inputs_raw.get(kind)
        if isinstance(section, dict):
            for key in section.keys():
                if isinstance(key, str) and key not in seen:
                    seen.add(key)
                    names.append(key)
    return names


class ImportError_(Exception):
    """Stage failure — message is surfaced to the client as the SSE event."""


def _build_user_prompt(
    *,
    class_type: str,
    display_name: str,
    pack_name: str,
    inputs_raw: Any,
    outputs_raw: Any,
    readme_md: str | None,
    description_seed: str | None,
) -> str:
    parts: list[str] = []
    parts.append(f"class_type: {class_type}")
    parts.append(f"display_name: {display_name}")
    parts.append(f"pack: {pack_name}")
    if description_seed:
        parts.append(f"\nComfyUI's own description: {description_seed}")
    parts.append("\nInputs schema (from /api/object_info):")
    parts.append(json.dumps(inputs_raw, ensure_ascii=False, indent=2))
    if outputs_raw:
        parts.append("\nOutputs:")
        parts.append(json.dumps(outputs_raw, ensure_ascii=False))
    if readme_md:
        # Truncate long READMEs to keep the prompt within reasonable
        # context. 5 KB is plenty for an LLM to grasp the pack idea.
        truncated = readme_md if len(readme_md) <= 5000 else readme_md[:5000] + "\n…(truncated)"
        parts.append(f"\nPack README:\n{truncated}")
    return "\n".join(parts)


def _validate_llm_response(
    body: dict[str, Any], known_input_names: set[str],
) -> tuple[str, list[dict[str, Any]]]:
    """Returns (description_md, inputs_semantic). Raises ImportError_ on
    bad shape or hallucinated input names.

    ``inputs_semantic`` is now a sparse ``[{name, notes}]`` list — the
    role_hint enum is gone (Phase 2 cleanup). Inputs the LLM didn't
    mention are still emitted with ``notes=None`` so the catalog row
    enumerates the full schema for the library node-detail editor.
    """
    description = body.get("description_md")
    if not isinstance(description, str):
        raise ImportError_("LLM response is missing a string description_md")
    raw_inputs = body.get("inputs")
    if raw_inputs is None:
        raw_inputs = []
    if not isinstance(raw_inputs, list):
        raise ImportError_("LLM response 'inputs' must be a list or omitted")

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in raw_inputs:
        if not isinstance(item, dict):
            raise ImportError_("inputs entry is not an object")
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise ImportError_("input name must be a non-empty string")
        if name not in known_input_names:
            raise ImportError_(
                f"LLM hallucinated an input named '{name}' that's not in the schema",
            )
        if name in seen:
            raise ImportError_(f"duplicate input '{name}' in LLM response")
        seen.add(name)
        notes = item.get("notes")
        if notes is not None and not isinstance(notes, str):
            raise ImportError_(f"notes for '{name}' must be a string or null")
        out.append({"name": name, "notes": (notes or None)})
    for name in known_input_names:
        if name not in seen:
            out.append({"name": name, "notes": None})
    return description.strip(), out


async def run_import(
    *,
    class_type: str,
    conn: sqlite3.Connection,
    comfyui_url: str,
    comfyui_api_key: str | None,
    comfyui_path: Path | None,
    llm_endpoint: dict[str, Any],
    llm_model: str | None,
    llm_sampling: dict[str, Any] | None,
) -> AsyncIterator[dict[str, Any]]:
    """Run the four stages and yield event dicts.

    Event shapes:
        {"type": "stage_started", "stage": "<name>"}
        {"type": "stage_succeeded", "stage": "<name>", "data": {...}}
        {"type": "stage_failed", "stage": "<name>", "error": "..."}
        {"type": "done", "class_type": "...", "node": {...}}
    """
    if not class_type:
        yield _failure("locate_pack", "class_type is required")
        return

    # --- Stage 1: locate_pack -------------------------------------------
    yield _started("locate_pack")

    # First, ask the running ComfyUI which pack this class_type came from
    # — the python_module field is authoritative.
    try:
        info = comfy_client.object_info(
            endpoint={"server_root": comfyui_url, "api_key": comfyui_api_key},
        )
    except comfy_client.ComfyError as exc:
        yield _failure("locate_pack", f"Couldn't reach ComfyUI: {exc.detail}")
        return

    if class_type not in info or not isinstance(info[class_type], dict):
        yield _failure(
            "locate_pack",
            f"ComfyUI doesn't currently expose a class_type named '{class_type}'.",
        )
        return

    node_info = info[class_type]
    python_module = (node_info.get("python_module") or "").strip()
    display_name = (node_info.get("display_name") or class_type).strip()
    category = (node_info.get("category") or None)
    description_seed = (node_info.get("description") or "").strip() or None

    if comfyui_path is None:
        yield _failure(
            "locate_pack",
            "ComfyUI install path is not configured (Settings → ComfyUI).",
        )
        return

    pack_loc = comfy_packs.locate_pack(
        python_module=python_module, comfyui_path=comfyui_path,
    )
    pack_metadata = (
        comfy_packs.read_pack_metadata(pack_loc.dir_path)
        if pack_loc.dir_path is not None
        else comfy_packs.PackMetadata(
            name=pack_loc.name, display_name=pack_loc.name,
            description="Built-in ComfyUI nodes.",
            version=None, repo_url=None, publisher_id=None,
        )
    )
    pack_readme = (
        comfy_packs.read_pack_readme(pack_loc.dir_path)
        if pack_loc.dir_path is not None else None
    )

    pack_payload = {
        "name": pack_loc.name,
        "display_name": pack_metadata.display_name or pack_loc.name,
        "description": pack_metadata.description,
        "version": pack_metadata.version,
        "repo_url": pack_metadata.repo_url,
        "publisher_id": pack_metadata.publisher_id,
        "dir_path": (
            str(pack_loc.dir_path.relative_to(comfyui_path))
            if pack_loc.dir_path is not None
            else None
        ),
        "is_builtin": pack_loc.is_builtin,
    }
    yield _succeeded("locate_pack", {
        "pack": pack_payload,
        "readme_present": pack_readme is not None,
    })

    # --- Stage 2: fetch_schema -----------------------------------------
    yield _started("fetch_schema")
    inputs_raw = node_info.get("input")
    outputs_raw = node_info.get("output") or []
    if not isinstance(inputs_raw, dict):
        yield _failure(
            "fetch_schema",
            "object_info entry is missing the 'input' object",
        )
        return
    input_names = _extract_input_names(inputs_raw)
    yield _succeeded("fetch_schema", {
        "input_names": input_names,
        "category": category,
        "display_name": display_name,
        "has_description_seed": description_seed is not None,
    })

    # --- Stage 3: enrich_llm -------------------------------------------
    yield _started("enrich_llm")
    if not llm_endpoint.get("server_root"):
        yield _failure(
            "enrich_llm",
            "LMStudio URL is not configured (Settings → LMStudio).",
        )
        return
    if not llm_model:
        yield _failure(
            "enrich_llm",
            "No LMStudio model is selected. Set a favourite model first.",
        )
        return

    user_prompt = _build_user_prompt(
        class_type=class_type,
        display_name=display_name,
        pack_name=pack_loc.name,
        inputs_raw=inputs_raw,
        outputs_raw=outputs_raw,
        readme_md=pack_readme,
        description_seed=description_seed,
    )
    messages = [
        {"role": "system", "content": _LLM_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]
    try:
        # chat_complete is sync — run it in a thread so the SSE generator
        # stays responsive. Use a small wrapper.
        import anyio
        raw = await anyio.to_thread.run_sync(
            lambda: lmstudio_client.chat_complete(
                endpoint=llm_endpoint,
                model=llm_model,
                messages=messages,
                response_format=_LLM_RESPONSE_FORMAT,
                sampling=llm_sampling,
            ),
        )
    except lmstudio_client.LmError as exc:
        yield _failure(
            "enrich_llm", f"LMStudio call failed: {exc.detail}",
        )
        return
    extracted = _extract_json_object(raw)
    try:
        body = json.loads(extracted)
    except ValueError as exc:
        yield _failure("enrich_llm", f"LLM returned invalid JSON: {exc}")
        return
    try:
        description_md, inputs_semantic = _validate_llm_response(
            body, set(input_names),
        )
    except ImportError_ as exc:
        yield _failure("enrich_llm", str(exc))
        return
    yield _succeeded("enrich_llm", {
        "description_md": description_md,
        "inputs_semantic": inputs_semantic,
    })

    # --- Stage 4: persist ----------------------------------------------
    yield _started("persist")
    try:
        comfy_catalog_repo.upsert_pack(
            conn,
            name=pack_payload["name"],
            display_name=pack_payload["display_name"],
            description=pack_payload["description"],
            version=pack_payload["version"],
            repo_url=pack_payload["repo_url"],
            publisher_id=pack_payload["publisher_id"],
            dir_path=pack_payload["dir_path"],
            readme_md=pack_readme,
        )
        node_row = comfy_catalog_repo.upsert_node(
            conn,
            class_type=class_type,
            pack_name=pack_payload["name"],
            display_name=display_name,
            category=category,
            inputs_raw=inputs_raw,
            outputs_raw=outputs_raw,
            inputs_semantic=inputs_semantic,
            description_md=description_md,
            requires_semantic_config=True,
        )
    except Exception as exc:  # noqa: BLE001 — surface any DB error.
        yield _failure("persist", f"Database write failed: {exc}")
        return

    yield _succeeded("persist", {"class_type": class_type})
    yield {"type": "done", "class_type": class_type, "node": node_row}


def _started(stage: str) -> dict[str, Any]:
    return {"type": "stage_started", "stage": stage}


def _succeeded(stage: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"type": "stage_succeeded", "stage": stage, "data": data}


def _failure(stage: str, error: str) -> dict[str, Any]:
    return {"type": "stage_failed", "stage": stage, "error": error}
