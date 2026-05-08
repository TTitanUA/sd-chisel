from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LmStudioConfig(StrictModel):
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=500)


class LmStudioConfigOut(StrictModel):
    base_url: str | None
    api_key: str | None
    configured: bool
    updated_at: int


class ComfyUiConfig(StrictModel):
    base_url: str | None = Field(default=None, max_length=500)
    install_path: str | None = Field(default=None, max_length=1000)
    api_key: str | None = Field(default=None, max_length=500)
    input_dir: str | None = Field(default=None, max_length=1000)
    """Optional override for ComfyUI's input directory. ``None`` falls
    back to ``<install_path>/input`` at resolve time. Used by Phase 3
    to upload session images and (when ``comfy_input_cleanup=delete``)
    remove them after a generation."""
    output_dir: str | None = Field(default=None, max_length=1000)
    """Optional override for ComfyUI's output directory. ``None`` falls
    back to ``<install_path>/output``. Used by Phase 3 to read SaveImage
    results and copy them into ``data/images/<sid>/output/<gid>/``."""


class ComfyUiConfigOut(StrictModel):
    base_url: str | None
    install_path: str | None
    api_key: str | None
    input_dir: str | None
    output_dir: str | None
    effective_input_dir: str | None
    """Resolved input dir — either the override or
    ``<install_path>/input``, whichever is non-empty. ``None`` when
    both are unset. Read-only, computed on every GET."""
    effective_output_dir: str | None
    """Resolved output dir — same fallback rule as above."""
    configured: bool
    updated_at: int


class ComfyUiCheckFieldOut(StrictModel):
    """Per-field result from the connection check."""
    ok: bool
    detail: str | None = None  # error message when ok is false
    info: dict | None = None   # success metadata (version, pack count)


class ComfyUiCheckOut(StrictModel):
    url: ComfyUiCheckFieldOut
    install_path: ComfyUiCheckFieldOut


class LmModelOut(StrictModel):
    name: str
    vision: bool
    tool_use: bool
    reasoning: bool
    enabled: bool
    favorite: bool
    hidden: bool = False
    last_seen: int


class LmModelsOut(StrictModel):
    models: list[LmModelOut]


class LmModelPatch(StrictModel):
    vision: bool | None = None
    tool_use: bool | None = None
    reasoning: bool | None = None
    enabled: bool | None = None
    favorite: bool | None = None
    hidden: bool | None = None


class PrivacyOut(StrictModel):
    show_hidden: bool
    updated_at: int


class PrivacyPatch(StrictModel):
    show_hidden: bool


class ActionDefaultsOut(StrictModel):
    """Per-action default sampling bundles (app-wide)."""
    analyze: dict
    chat: dict
    summarize: dict
    generate: dict
    comfy_import: dict


class ActionDefaultsPatch(StrictModel):
    """Partial update — only fields the client sends are persisted.

    Each value is a sampling bundle dict (e.g. {"temperature": 0.7,
    "top_p": 0.9}). Pass an empty object to clear all overrides for an
    action.
    """
    analyze: dict | None = None
    chat: dict | None = None
    summarize: dict | None = None
    generate: dict | None = None
    comfy_import: dict | None = None
