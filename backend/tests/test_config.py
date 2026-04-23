from pathlib import Path

import pytest

from app.config import resolve_data_root


def test_resolve_data_root_returns_repo_data_dir(tmp_path, monkeypatch):
    # Simulate: project at tmp_path/repo with backend/app/main.py
    repo = tmp_path / "repo"
    (repo / "backend" / "app").mkdir(parents=True)
    (repo / ".git").mkdir()
    fake_main = repo / "backend" / "app" / "main.py"
    fake_main.write_text("# fake main")

    assert resolve_data_root(anchor_file=fake_main) == repo / "data"


def test_resolve_data_root_raises_when_no_repo_root(tmp_path):
    # No .git, no pyproject in the walk up
    orphan = tmp_path / "orphan" / "main.py"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("")
    with pytest.raises(RuntimeError, match="repo root"):
        resolve_data_root(anchor_file=orphan)


def test_resolve_data_root_creates_dir(tmp_path):
    repo = tmp_path / "repo"
    (repo / "backend" / "app").mkdir(parents=True)
    (repo / ".git").mkdir()
    fake_main = repo / "backend" / "app" / "main.py"
    fake_main.write_text("")

    root = resolve_data_root(anchor_file=fake_main)
    assert root.exists()
    assert root.is_dir()


def test_resolve_data_root_handles_backend_named_repo_root(tmp_path):
    # Repo is cloned into a directory literally named "backend".
    repo = tmp_path / "backend"
    (repo / "backend" / "app").mkdir(parents=True)
    (repo / ".git").mkdir()
    (repo / "backend" / "pyproject.toml").write_text("")
    fake_main = repo / "backend" / "app" / "main.py"
    fake_main.write_text("")

    # Outer (repo/.git) wins over inner (repo/backend/pyproject.toml).
    assert resolve_data_root(anchor_file=fake_main) == repo / "data"
