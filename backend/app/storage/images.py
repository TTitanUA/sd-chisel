from __future__ import annotations

import re
import shutil
from pathlib import Path

from app.config import resolve_data_root

_SAFE_ID = re.compile(r"^[A-Za-z0-9_\-]+$")


def _validate_session_id(session_id: str) -> None:
    if not _SAFE_ID.match(session_id):
        raise ValueError(f"unsafe session id: {session_id!r}")


def session_image_dir(session_id: str, *, data_root: Path | None = None) -> Path:
    _validate_session_id(session_id)
    root = data_root or resolve_data_root()
    d = root / "images" / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def session_sources_dir(session_id: str, *, data_root: Path | None = None) -> Path:
    """Per-session subdirectory that holds source images (main + references)."""
    d = session_image_dir(session_id, data_root=data_root) / "sources"
    d.mkdir(parents=True, exist_ok=True)
    return d


def session_output_dir(
    session_id: str,
    generation_id: str,
    *,
    data_root: Path | None = None,
) -> Path:
    """Per-run output subdirectory matching the §10.7 layout
    `data/images/<session_id>/output/<generation_id>/`. Single Run
    captures every SaveImage file under here; the gallery serves
    them via the existing static-images mount."""
    if not _SAFE_ID.match(generation_id):
        raise ValueError(f"unsafe generation id: {generation_id!r}")
    d = session_image_dir(session_id, data_root=data_root) / "output" / generation_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def remove_session_images(session_id: str, *, data_root: Path | None = None) -> None:
    _validate_session_id(session_id)
    root = data_root or resolve_data_root()
    d = root / "images" / session_id
    if d.exists():
        shutil.rmtree(d)
