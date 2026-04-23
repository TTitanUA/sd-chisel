from __future__ import annotations

from pathlib import Path

_REPO_MARKERS = {".git", "pyproject.toml"}


def _find_repo_root(start: Path) -> Path:
    """Walk up from `start` and return the outermost directory containing a repo marker."""
    current = start.resolve()
    if current.is_file():
        current = current.parent
    matches = [
        candidate
        for candidate in [current, *current.parents]
        if any((candidate / marker).exists() for marker in _REPO_MARKERS)
    ]
    if not matches:
        raise RuntimeError(f"Could not find repo root walking up from {start}")
    return matches[-1]


def resolve_data_root(anchor_file: Path | None = None) -> Path:
    """Return `<repo_root>/data`, creating it if missing.

    `anchor_file` defaults to this module; tests can override it.
    """
    anchor = anchor_file or Path(__file__)
    repo_root = _find_repo_root(anchor)
    data = repo_root / "data"
    data.mkdir(parents=True, exist_ok=True)
    return data
