"""Resolve ComfyUI input/output directories from app settings.

Phase 3 needs to know where on the local filesystem ComfyUI reads
uploaded inputs from and writes its results to. The settings layer
exposes three relevant fields:

- ``comfyui_path`` — install root. ComfyUI's defaults read/write
  ``<comfyui_path>/input`` and ``<comfyui_path>/output``.
- ``comfyui_input_dir`` — explicit override for the input dir. Set
  this when the user runs ComfyUI with ``--input-directory <path>`` or
  has a non-standard layout.
- ``comfyui_output_dir`` — explicit override for the output dir.

This module is the single resolver: given a settings row (already
loaded by ``settings_repo.get_comfyui``), return the effective
absolute path for either side, or ``None`` when neither override nor
install path is set.

It is deliberately I/O-free — :func:`resolve_input_dir` /
:func:`resolve_output_dir` do not check that the path exists, is a
directory, or is writable. Callers (Phase 3 upload / cleanup paths)
do the check and decide what to do on failure (cleanup soft-degrades
to ``keep``; output capture surfaces an error).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _resolve(override: Any, install_path: Any, *, suffix: str) -> Path | None:
    if isinstance(override, str) and override.strip():
        return Path(override.strip())
    if isinstance(install_path, str) and install_path.strip():
        return Path(install_path.strip()) / suffix
    return None


def resolve_input_dir(comfy_settings: dict[str, Any]) -> Path | None:
    """Effective input dir, or ``None`` when neither
    ``comfyui_input_dir`` nor ``comfyui_path`` is set."""
    return _resolve(
        comfy_settings.get("comfyui_input_dir"),
        comfy_settings.get("comfyui_path"),
        suffix="input",
    )


def resolve_output_dir(comfy_settings: dict[str, Any]) -> Path | None:
    """Effective output dir, or ``None``."""
    return _resolve(
        comfy_settings.get("comfyui_output_dir"),
        comfy_settings.get("comfyui_path"),
        suffix="output",
    )
