"""ComfyUI pack discovery: locate the on-disk pack for a given class_type
and read its pyproject.toml metadata.

Phase 1 of the ComfyUI integration uses ComfyUI's own ``/api/object_info``
endpoint as the source of truth for which class_types exist. Each entry
has a ``python_module`` field that pinpoints where the node was loaded
from — e.g. ``custom_nodes.z-image-turbo`` for a custom pack or
``nodes`` / ``comfy_extras.nodes_*`` for built-ins. That makes the
locator a small string-prefix step rather than an AST walk over the
pack's ``__init__.py``.

The pyproject parser is similarly minimal: ComfyUI Registry's
``[tool.comfy]`` section plus the standard ``[project]`` table cover
everything Phase 1 stores on the pack row (display name, repo URL,
version, publisher, description). Missing/partial files are tolerated —
hand-written packs without a pyproject still get a row with synthesised
defaults.

See docs/comfy-workflow-plan.md (Phase 1).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Standard library tomllib lands in 3.11; fall back to tomli on 3.10.
if sys.version_info >= (3, 11):
    import tomllib as _toml
else:  # pragma: no cover
    import tomli as _toml  # type: ignore[no-redef]


# Synthetic pack name used for everything that ships in the main ComfyUI
# repo (built-in nodes, comfy_extras, comfy_api_nodes).
BUILTIN_PACK = "ComfyUI"

# Module prefixes that map to the built-in pack rather than custom_nodes.
_BUILTIN_PREFIXES = ("comfy_extras.", "comfy_api_nodes.", "comfy.")
_BUILTIN_TOPLEVEL = {"nodes", "comfy", "comfy_extras", "comfy_api_nodes"}


@dataclass
class PackLocation:
    """Result of resolving a class_type's python_module to a pack."""
    name: str
    """Pack identifier — directory name for custom packs, ``BUILTIN_PACK`` for built-ins."""

    is_builtin: bool

    dir_path: Path | None
    """Absolute path to the pack directory; None for built-in."""


def locate_pack(
    *,
    python_module: str,
    comfyui_path: Path,
) -> PackLocation:
    """Resolve ``object_info[class_type].python_module`` to a pack location.

    Examples:
        ``custom_nodes.z-image-turbo`` -> custom pack ``z-image-turbo`` at
        ``<comfyui_path>/custom_nodes/z-image-turbo``.
        ``nodes`` / ``comfy_extras.nodes_ace`` -> built-in.
    """
    pm = (python_module or "").strip()
    if not pm:
        # Treat unknown source as built-in. The import wizard's UI will
        # surface this so the user knows the metadata is sparse.
        return PackLocation(name=BUILTIN_PACK, is_builtin=True, dir_path=None)

    if pm.startswith("custom_nodes."):
        rest = pm[len("custom_nodes."):]
        # Custom pack names sometimes contain dashes; the python_module
        # truncates at the first dot inside the pack — but ComfyUI uses
        # the directory name verbatim so a single-segment rest is the
        # pack name. If the remainder has further dots (a sub-module),
        # take the first segment.
        pack_dir = rest.split(".", 1)[0]
        return PackLocation(
            name=pack_dir,
            is_builtin=False,
            dir_path=comfyui_path / "custom_nodes" / pack_dir,
        )

    if pm in _BUILTIN_TOPLEVEL or pm.startswith(_BUILTIN_PREFIXES):
        return PackLocation(name=BUILTIN_PACK, is_builtin=True, dir_path=None)

    # Anything else (rare — e.g. nodes loaded from a fully-qualified
    # third-party install) is treated as built-in for Phase 1; we surface
    # the raw module string in the import UI so the user can react.
    return PackLocation(name=BUILTIN_PACK, is_builtin=True, dir_path=None)


@dataclass
class PackMetadata:
    """Subset of pyproject.toml used by the catalog.

    All fields are nullable — pyproject.toml may be absent (hand-written
    pack) or partial. The caller fills missing fields with sensible
    defaults (display_name fallback to dir name, etc.).
    """
    name: str | None
    display_name: str | None
    description: str | None
    version: str | None
    repo_url: str | None
    publisher_id: str | None


def read_pack_metadata(pack_dir: Path) -> PackMetadata:
    """Parse <pack_dir>/pyproject.toml. Tolerant: missing file or partial
    fields produce a metadata record full of None values rather than an
    error.
    """
    pyproject = pack_dir / "pyproject.toml"
    if not pyproject.is_file():
        return PackMetadata(
            name=None, display_name=None, description=None,
            version=None, repo_url=None, publisher_id=None,
        )
    try:
        data = _toml.loads(pyproject.read_text(encoding="utf-8"))
    except Exception:
        # A broken pyproject.toml shouldn't prevent the user from
        # importing nodes from this pack; just behave as if it were
        # missing.
        return PackMetadata(
            name=None, display_name=None, description=None,
            version=None, repo_url=None, publisher_id=None,
        )

    project = _as_dict(data.get("project"))
    urls = _as_dict(project.get("urls"))
    comfy = _as_dict(_as_dict(data.get("tool")).get("comfy"))

    return PackMetadata(
        name=_as_str(project.get("name")),
        display_name=_as_str(comfy.get("DisplayName")),
        description=_as_str(project.get("description")),
        version=_as_str(project.get("version")),
        repo_url=_as_str(urls.get("Repository")),
        publisher_id=_as_str(comfy.get("PublisherId")),
    )


def read_pack_readme(pack_dir: Path) -> str | None:
    """Return the raw README markdown, or None if no README is present."""
    for candidate in ("README.md", "README.MD", "readme.md", "Readme.md"):
        f = pack_dir / candidate
        if f.is_file():
            try:
                return f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
    return None


def _as_dict(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _as_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None
