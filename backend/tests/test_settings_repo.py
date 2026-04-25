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
    assert cfg["lmstudio_base_url"] is None
    assert cfg["lmstudio_api_key"] is None


def test_set_lmstudio_round_trips_and_bumps_updated_at(conn):
    before = settings_repo.get_lmstudio(conn)
    settings_repo.set_lmstudio(
        conn,
        base_url="http://localhost:1234/v1",
        api_key="lm-studio",
    )
    after = settings_repo.get_lmstudio(conn)
    assert after["lmstudio_base_url"] == "http://localhost:1234/v1"
    assert after["lmstudio_api_key"] == "lm-studio"
    assert after["updated_at"] >= before["updated_at"]


def test_set_lmstudio_strips_trailing_slash_in_base_url(conn):
    settings_repo.set_lmstudio(conn, base_url="http://h/v1/", api_key=None)
    assert settings_repo.get_lmstudio(conn)["lmstudio_base_url"] == "http://h/v1"


def test_set_lmstudio_appends_v1_when_path_is_empty(conn):
    settings_repo.set_lmstudio(conn, base_url="http://localhost:1234", api_key=None)
    assert settings_repo.get_lmstudio(conn)["lmstudio_base_url"] == "http://localhost:1234/v1"


def test_set_lmstudio_appends_v1_when_path_is_root_slash(conn):
    settings_repo.set_lmstudio(conn, base_url="http://localhost:1234/", api_key=None)
    assert settings_repo.get_lmstudio(conn)["lmstudio_base_url"] == "http://localhost:1234/v1"


def test_set_lmstudio_keeps_custom_path_intact(conn):
    """Reverse-proxy prefixes like /proxy/openai/v1 must not be mangled."""
    settings_repo.set_lmstudio(
        conn, base_url="https://proxy.example.com/proxy/openai/v1", api_key=None,
    )
    assert (
        settings_repo.get_lmstudio(conn)["lmstudio_base_url"]
        == "https://proxy.example.com/proxy/openai/v1"
    )


def test_set_lmstudio_can_clear_to_null(conn):
    settings_repo.set_lmstudio(conn, base_url="http://h/v1", api_key="k")
    settings_repo.set_lmstudio(conn, base_url=None, api_key=None)
    cfg = settings_repo.get_lmstudio(conn)
    assert cfg["lmstudio_base_url"] is None
    assert cfg["lmstudio_api_key"] is None


def test_lm_models_upsert_merge_keeps_user_flags(conn):
    settings_repo.upsert_lm_models(
        conn,
        names=["qwen2-vl-7b", "mistral-nemo-12b"],
        seen_at=100,
    )
    settings_repo.update_lm_model(conn, name="qwen2-vl-7b", role="vl", enabled=True)
    settings_repo.update_lm_model(conn, name="mistral-nemo-12b", role="prompt", enabled=False)

    settings_repo.upsert_lm_models(
        conn,
        names=["qwen2-vl-7b", "mistral-nemo-12b", "new-model"],
        seen_at=200,
    )

    by_name = {m["name"]: m for m in settings_repo.list_lm_models(conn)}
    assert by_name["qwen2-vl-7b"]["role"] == "vl"
    assert by_name["qwen2-vl-7b"]["enabled"] is True
    assert by_name["qwen2-vl-7b"]["last_seen"] == 200
    assert by_name["mistral-nemo-12b"]["role"] == "prompt"
    assert by_name["mistral-nemo-12b"]["enabled"] is False
    assert by_name["mistral-nemo-12b"]["last_seen"] == 200
    assert by_name["new-model"]["role"] == "both"      # default
    assert by_name["new-model"]["enabled"] is True     # default


def test_lm_models_upsert_keeps_stale_rows_when_disappear(conn):
    # Spec §2.3: stale models are kept on refresh so users still see disabled/old picks.
    settings_repo.upsert_lm_models(conn, names=["a", "b"], seen_at=100)
    settings_repo.upsert_lm_models(conn, names=["a"], seen_at=200)  # `b` disappears

    by_name = {m["name"]: m for m in settings_repo.list_lm_models(conn)}
    assert set(by_name) == {"a", "b"}            # `b` survives
    assert by_name["a"]["last_seen"] == 200      # `a` was refreshed
    assert by_name["b"]["last_seen"] == 100      # `b` keeps original timestamp


def test_update_lm_model_returns_none_for_unknown(conn):
    assert settings_repo.update_lm_model(conn, name="ghost", enabled=False) is None


def test_update_lm_model_rejects_bad_role(conn):
    settings_repo.upsert_lm_models(conn, names=["m"], seen_at=0)
    with pytest.raises(ValueError):
        settings_repo.update_lm_model(conn, name="m", role="bogus")
