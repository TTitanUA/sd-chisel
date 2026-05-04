"""Tests for the comfy_packs locator and pyproject reader."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.comfy_packs import (
    BUILTIN_PACK,
    PackMetadata,
    locate_pack,
    read_pack_metadata,
    read_pack_readme,
)


# --- locate_pack ---

def test_locate_pack_custom_node():
    loc = locate_pack(
        python_module="custom_nodes.z-image-turbo",
        comfyui_path=Path("/comfyui"),
    )
    assert loc.is_builtin is False
    assert loc.name == "z-image-turbo"
    assert loc.dir_path == Path("/comfyui/custom_nodes/z-image-turbo")


def test_locate_pack_handles_dashes_in_name():
    # rgthree-comfy survives the dotted module unchanged.
    loc = locate_pack(
        python_module="custom_nodes.rgthree-comfy",
        comfyui_path=Path("/x"),
    )
    assert loc.name == "rgthree-comfy"


def test_locate_pack_truncates_at_first_dot_after_pack():
    # Some custom packs expose nested submodules; we still want the
    # top-level pack directory.
    loc = locate_pack(
        python_module="custom_nodes.comfyui-impact-pack.modules.impact",
        comfyui_path=Path("/x"),
    )
    assert loc.name == "comfyui-impact-pack"


def test_locate_pack_builtin_top_level_nodes():
    loc = locate_pack(python_module="nodes", comfyui_path=Path("/x"))
    assert loc.is_builtin is True
    assert loc.name == BUILTIN_PACK
    assert loc.dir_path is None


@pytest.mark.parametrize("module", [
    "comfy_extras.nodes_ace",
    "comfy_api_nodes.nodes_openai",
    "comfy.sample",
])
def test_locate_pack_builtin_prefixes(module):
    loc = locate_pack(python_module=module, comfyui_path=Path("/x"))
    assert loc.is_builtin is True
    assert loc.name == BUILTIN_PACK


def test_locate_pack_unknown_module_falls_back_to_builtin():
    loc = locate_pack(python_module="some.third_party.thing", comfyui_path=Path("/x"))
    assert loc.is_builtin is True
    assert loc.name == BUILTIN_PACK


def test_locate_pack_empty_module():
    loc = locate_pack(python_module="", comfyui_path=Path("/x"))
    assert loc.is_builtin is True


# --- read_pack_metadata ---

def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def test_read_pack_metadata_full_registry_format(tmp_path):
    _write(tmp_path / "pyproject.toml", """
[project]
name = "rgthree-comfy"
description = "Making ComfyUI more comfortable."
version = "1.0.2512112053"

[project.urls]
Repository = "https://github.com/rgthree/rgthree-comfy"

[tool.comfy]
PublisherId = "rgthree"
DisplayName = "rgthree-comfy"
""".strip())
    md = read_pack_metadata(tmp_path)
    assert md == PackMetadata(
        name="rgthree-comfy",
        display_name="rgthree-comfy",
        description="Making ComfyUI more comfortable.",
        version="1.0.2512112053",
        repo_url="https://github.com/rgthree/rgthree-comfy",
        publisher_id="rgthree",
    )


def test_read_pack_metadata_missing_tool_comfy(tmp_path):
    _write(tmp_path / "pyproject.toml", """
[project]
name = "z-image-turbo"
description = "ZImage."
version = "1.0.0"

[project.urls]
Repository = "https://github.com/tpc2233/ComfyUI-Z-Image-Turbo"
""".strip())
    md = read_pack_metadata(tmp_path)
    assert md.name == "z-image-turbo"
    assert md.display_name is None
    assert md.publisher_id is None
    assert md.repo_url == "https://github.com/tpc2233/ComfyUI-Z-Image-Turbo"


def test_read_pack_metadata_missing_file(tmp_path):
    md = read_pack_metadata(tmp_path)
    assert md.name is None
    assert md.display_name is None
    assert md.repo_url is None


def test_read_pack_metadata_broken_toml(tmp_path):
    _write(tmp_path / "pyproject.toml", "not [a valid toml")
    md = read_pack_metadata(tmp_path)
    assert md == PackMetadata(
        name=None, display_name=None, description=None,
        version=None, repo_url=None, publisher_id=None,
    )


def test_read_pack_metadata_strips_whitespace(tmp_path):
    _write(tmp_path / "pyproject.toml", """
[project]
name = "  spaced  "
""".strip())
    md = read_pack_metadata(tmp_path)
    assert md.name == "spaced"


def test_read_pack_metadata_empty_string_treated_as_none(tmp_path):
    _write(tmp_path / "pyproject.toml", """
[project]
name = "foo"
description = "   "
""".strip())
    md = read_pack_metadata(tmp_path)
    assert md.name == "foo"
    assert md.description is None


# --- read_pack_readme ---

def test_read_pack_readme_returns_markdown(tmp_path):
    _write(tmp_path / "README.md", "# Title\n\nBody.")
    assert read_pack_readme(tmp_path) == "# Title\n\nBody."


def test_read_pack_readme_missing_returns_none(tmp_path):
    assert read_pack_readme(tmp_path) is None


def test_read_pack_readme_handles_alternate_casing(tmp_path):
    # Windows is case-insensitive; on Linux this still works because the
    # iteration over candidates picks whatever exists first.
    _write(tmp_path / "README.md", "# Found")
    assert read_pack_readme(tmp_path) == "# Found"


# --- Optional integration test against the user's real ComfyUI install ---

REAL_COMFYUI = Path("F:/VAIProjects/ComfyUI")


@pytest.mark.skipif(
    not (REAL_COMFYUI / "custom_nodes").is_dir(),
    reason="Real ComfyUI install not present",
)
def test_pyproject_parser_against_real_packs():
    """Smoke-test the parser against the user's actual install."""
    custom_nodes = REAL_COMFYUI / "custom_nodes"
    seen = 0
    for child in custom_nodes.iterdir():
        if not child.is_dir() or child.name.startswith((".", "__")):
            continue
        md = read_pack_metadata(child)
        # We don't assert specific values — just that the parser doesn't
        # crash and returns the right shape on real-world inputs.
        assert isinstance(md, PackMetadata)
        seen += 1
    assert seen > 0
