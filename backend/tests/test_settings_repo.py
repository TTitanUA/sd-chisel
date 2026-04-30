from pathlib import Path

import pytest

from app.storage import db as db_mod
from app.storage import settings_repo
from app.storage.migrations import apply_pending


@pytest.fixture
def conn(tmp_path):
    c = db_mod.connect(tmp_path / "s.db")
    apply_pending(c, Path(__file__).parent.parent / "migrations")
    yield c
    c.close()


def test_default_lmstudio_settings_are_blank(conn):
    cfg = settings_repo.get_lmstudio(conn)
    assert cfg["lmstudio_url"] is None
    assert cfg["lmstudio_api_key"] is None


def test_set_lmstudio_stores_server_root(conn):
    settings_repo.set_lmstudio(conn, url="http://localhost:1234", api_key="k")
    cfg = settings_repo.get_lmstudio(conn)
    assert cfg["lmstudio_url"] == "http://localhost:1234"
    assert cfg["lmstudio_api_key"] == "k"


def test_set_lmstudio_strips_trailing_slash(conn):
    settings_repo.set_lmstudio(conn, url="http://localhost:1234/", api_key=None)
    assert settings_repo.get_lmstudio(conn)["lmstudio_url"] == "http://localhost:1234"


def test_set_lmstudio_does_not_append_v1(conn):
    settings_repo.set_lmstudio(conn, url="http://localhost:1234", api_key=None)
    assert settings_repo.get_lmstudio(conn)["lmstudio_url"] == "http://localhost:1234"


def test_set_lmstudio_bumps_updated_at(conn):
    before = settings_repo.get_lmstudio(conn)["updated_at"]
    settings_repo.set_lmstudio(conn, url="http://h", api_key=None)
    assert settings_repo.get_lmstudio(conn)["updated_at"] >= before


def test_set_lmstudio_can_clear_to_null(conn):
    settings_repo.set_lmstudio(conn, url="http://h", api_key="k")
    settings_repo.set_lmstudio(conn, url=None, api_key=None)
    cfg = settings_repo.get_lmstudio(conn)
    assert cfg["lmstudio_url"] is None
    assert cfg["lmstudio_api_key"] is None


def _make_model(name: str, vision=False, tool_use=False, reasoning=False):
    return {"name": name, "vision": vision, "tool_use": tool_use, "reasoning": reasoning}


def test_upsert_stores_capabilities(conn):
    models = [
        _make_model("qwen-vl", vision=True),
        _make_model("mistral", tool_use=True, reasoning=True),
    ]
    settings_repo.upsert_lm_models(conn, models=models, seen_at=100)
    by_name = {m["name"]: m for m in settings_repo.list_lm_models(conn)}
    assert by_name["qwen-vl"]["vision"] is True
    assert by_name["qwen-vl"]["tool_use"] is False
    assert by_name["qwen-vl"]["enabled"] is True  # default
    assert by_name["mistral"]["tool_use"] is True
    assert by_name["mistral"]["reasoning"] is True


def test_upsert_updates_capabilities_preserves_enabled(conn):
    settings_repo.upsert_lm_models(
        conn, models=[_make_model("m", vision=False)], seen_at=100,
    )
    settings_repo.patch_lm_model(conn, name="m", enabled=False)

    settings_repo.upsert_lm_models(
        conn, models=[_make_model("m", vision=True, tool_use=True)], seen_at=200,
    )
    m = settings_repo.get_lm_model(conn, "m")
    assert m["vision"] is True     # updated from API
    assert m["tool_use"] is True   # updated from API
    assert m["enabled"] is False   # preserved


def test_upsert_keeps_stale_rows_when_model_disappears(conn):
    settings_repo.upsert_lm_models(
        conn,
        models=[_make_model("a"), _make_model("b")],
        seen_at=100,
    )
    settings_repo.upsert_lm_models(conn, models=[_make_model("a")], seen_at=200)
    by_name = {m["name"]: m for m in settings_repo.list_lm_models(conn)}
    assert set(by_name) == {"a", "b"}
    assert by_name["a"]["last_seen"] == 200
    assert by_name["b"]["last_seen"] == 100  # stale but preserved


def test_patch_updates_vision(conn):
    settings_repo.upsert_lm_models(conn, models=[_make_model("m")], seen_at=0)
    settings_repo.patch_lm_model(conn, name="m", vision=True)
    assert settings_repo.get_lm_model(conn, "m")["vision"] is True


def test_patch_updates_enabled(conn):
    settings_repo.upsert_lm_models(conn, models=[_make_model("m")], seen_at=0)
    settings_repo.patch_lm_model(conn, name="m", enabled=False)
    assert settings_repo.get_lm_model(conn, "m")["enabled"] is False


def test_patch_returns_none_for_unknown(conn):
    assert settings_repo.patch_lm_model(conn, name="ghost", enabled=False) is None
