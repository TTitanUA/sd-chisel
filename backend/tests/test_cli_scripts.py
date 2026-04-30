import tomllib
from pathlib import Path


def test_pyproject_exposes_short_uv_scripts():
    pyproject = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text())

    assert pyproject["project"]["scripts"] == {
        "db-init": "app.cli.init_db:main",
        "dev": "app.cli.dev:main",
        "reindex-all": "app.cli.reindex_all:main",
    }


def test_dev_script_runs_uvicorn_with_readme_defaults(monkeypatch):
    from app.cli import dev

    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(dev.uvicorn, "run", fake_run)

    dev.main()

    assert calls == [
        (
            ("app.main:app",),
            {"reload": True, "port": 8000},
        )
    ]
