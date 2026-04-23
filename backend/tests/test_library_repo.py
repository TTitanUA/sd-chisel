from pathlib import Path

import pytest

from app.storage import db as db_mod
from app.storage import library_repo
from app.storage.migrations import apply_pending


@pytest.fixture
def conn(tmp_path):
    c = db_mod.connect(tmp_path / "t.db")
    apply_pending(c, Path(__file__).parent.parent / "migrations")
    yield c
    c.close()


def test_list_families_returns_seeded(conn):
    fams = library_repo.list_families(conn)
    ids = [f["id"] for f in fams]
    assert "sdxl" in ids and len(ids) == 10


def test_create_and_get_model(conn):
    library_repo.create_model(conn, name="juggernautXL_v10",
                              display_name="Juggernaut XL v10",
                              family_id="sdxl")
    m = library_repo.get_model(conn, "juggernautXL_v10")
    assert m is not None
    assert m["display_name"] == "Juggernaut XL v10"
    assert m["family_id"] == "sdxl"


def test_create_model_with_unknown_family_raises(conn):
    with pytest.raises(Exception):
        library_repo.create_model(conn, name="x", display_name="X", family_id="nope")


def test_create_and_get_lora_with_compat(conn):
    library_repo.create_lora(
        conn,
        name="cinematic_lighting_v2",
        display_name="Cinematic Lighting v2",
        description="Dramatic cinematic light.",
        tags=["light", "mood"],
        trigger_words=["cinematic", "rim light"],
        recommended_weight=0.85,
        family_compat=["sdxl", "illustrious"],
    )
    l = library_repo.get_lora(conn, "cinematic_lighting_v2")
    assert l is not None
    assert l["tags"] == ["light", "mood"]
    assert set(l["family_compat"]) == {"sdxl", "illustrious"}


def test_delete_lora_cascades_compat_and_vec_map(conn):
    library_repo.create_lora(
        conn, name="ltest", display_name="L", description="d",
        tags=[], trigger_words=[], family_compat=["sdxl"],
    )
    # Simulate vec_map row (indexer would populate this in Slice 5)
    conn.execute("INSERT INTO lora_vec_map(lora_name, rowid) VALUES (?, ?)", ("ltest", 1))
    library_repo.delete_lora(conn, "ltest")
    assert library_repo.get_lora(conn, "ltest") is None
    assert list(conn.execute("SELECT * FROM lora_family_compat WHERE lora_name='ltest'")) == []
    assert list(conn.execute("SELECT * FROM lora_vec_map WHERE lora_name='ltest'")) == []
