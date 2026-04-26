import sqlite3
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
    with pytest.raises(sqlite3.IntegrityError):
        library_repo.create_model(conn, name="x", display_name="X", family_id="nope")


def test_create_and_get_lora_with_family(conn):
    library_repo.create_lora(
        conn,
        name="cinematic_lighting_v2",
        display_name="Cinematic Lighting v2",
        description="Dramatic cinematic light.",
        tags=["light", "mood"],
        trigger_words=["cinematic", "rim light"],
        recommended_weight=0.85,
        family_id="illustrious",
    )
    lora = library_repo.get_lora(conn, "cinematic_lighting_v2")
    assert lora is not None
    assert lora["tags"] == ["light", "mood"]
    assert lora["family_id"] == "illustrious"


def test_delete_lora_cascades_vec_map(conn):
    library_repo.create_lora(
        conn, name="ltest", display_name="L", description="d",
        tags=[], trigger_words=[], family_id="sdxl",
    )
    # Simulate vec_map row (indexer would populate this in Slice 5)
    conn.execute("INSERT INTO lora_vec_map(lora_name, rowid) VALUES (?, ?)", ("ltest", 1))
    library_repo.delete_lora(conn, "ltest")
    assert library_repo.get_lora(conn, "ltest") is None
    assert list(conn.execute("SELECT * FROM lora_vec_map WHERE lora_name='ltest'")) == []


def test_family_create_update_delete(conn):
    created = library_repo.create_family(
        conn,
        id="testfam",
        display_name="Test Family",
        prompt_guide="Use test syntax.",
    )
    assert created["id"] == "testfam"

    updated = library_repo.update_family(
        conn,
        "testfam",
        display_name="Test Family 2",
        prompt_guide="Updated guide.",
    )
    assert updated is not None
    assert updated["display_name"] == "Test Family 2"
    assert updated["updated_at"] >= created["updated_at"]

    assert library_repo.delete_family(conn, "testfam") is True
    assert library_repo.get_family(conn, "testfam") is None
    assert library_repo.delete_family(conn, "testfam") is False


def test_list_families_filters_by_query(conn):
    library_repo.create_family(conn, id="abcxyz", display_name="Needle Family", prompt_guide="x")
    rows = library_repo.list_families(conn, q="needle")
    assert [r["id"] for r in rows] == ["abcxyz"]


def test_model_update_delete_and_filters(conn):
    library_repo.create_model(
        conn,
        name="model_a",
        display_name="Model A",
        family_id="sdxl",
        description="alpha",
    )
    library_repo.create_model(conn, name="model_b", display_name="Model B", family_id="pony")

    filtered = library_repo.list_models(conn, family_id="sdxl", q="alpha")
    assert [m["name"] for m in filtered] == ["model_a"]

    updated = library_repo.update_model(
        conn,
        "model_a",
        display_name="Model A2",
        family_id="sdxl",
        description="beta",
        author="me",
        version="v1",
        source_url="https://example.test/model",
    )
    assert updated is not None
    assert updated["display_name"] == "Model A2"
    assert updated["description"] == "beta"

    assert library_repo.delete_model(conn, "model_a") is True
    assert library_repo.get_model(conn, "model_a") is None
    assert library_repo.delete_model(conn, "model_a") is False


def test_lora_update_delete_and_filters(conn):
    library_repo.create_lora(
        conn,
        name="detail_boost",
        display_name="Detail Boost",
        description="Adds crisp detail.",
        tags=["detail", "portrait"],
        trigger_words=["detail boost"],
        recommended_weight=0.7,
        family_id="sdxl",
    )
    library_repo.create_lora(
        conn,
        name="linework",
        display_name="Linework",
        description="Adds line art.",
        tags=["line"],
        trigger_words=["line art"],
        family_id="pony",
    )

    by_family = library_repo.list_loras(conn, family_id="sdxl")
    assert [row["name"] for row in by_family] == ["detail_boost"]

    by_tag = library_repo.list_loras(conn, tag="detail")
    assert [row["name"] for row in by_tag] == ["detail_boost"]

    by_query = library_repo.list_loras(conn, q="crisp")
    assert [row["name"] for row in by_query] == ["detail_boost"]

    updated = library_repo.update_lora(
        conn,
        "detail_boost",
        display_name="Detail Boost 2",
        description="Adds controlled detail.",
        tags=["detail"],
        trigger_words=["detail boost", "sharp detail"],
        family_id="illustrious",
        recommended_weight=0.8,
        author="me",
        version="v2",
        source_url="https://example.test/lora",
    )
    assert updated is not None
    assert updated["display_name"] == "Detail Boost 2"
    assert updated["tags"] == ["detail"]
    assert updated["family_id"] == "illustrious"

    assert library_repo.delete_lora(conn, "detail_boost") is True
    assert library_repo.get_lora(conn, "detail_boost") is None
    assert library_repo.delete_lora(conn, "detail_boost") is False


def test_list_all_lora_names_returns_sorted_keys(conn):
    library_repo.create_lora(
        conn, name="zeta", display_name="Z", description="d",
        tags=[], trigger_words=[], family_id="sdxl",
    )
    library_repo.create_lora(
        conn, name="alpha", display_name="A", description="d",
        tags=[], trigger_words=[], family_id="sdxl",
    )
    assert library_repo.list_all_lora_names(conn) == ["alpha", "zeta"]


def test_create_lora_inside_outer_transaction_does_not_nest(conn):
    """After Slice 5: caller may wrap create_lora in its own BEGIN/COMMIT."""
    conn.execute("BEGIN")
    library_repo.create_lora(
        conn, name="wrapped", display_name="W", description="d",
        tags=[], trigger_words=[], family_id="sdxl",
    )
    conn.execute("COMMIT")
    assert library_repo.get_lora(conn, "wrapped") is not None


def test_update_lora_inside_outer_transaction_does_not_nest(conn):
    library_repo.create_lora(
        conn, name="x", display_name="X", description="d",
        tags=[], trigger_words=[], family_id="sdxl",
    )
    conn.execute("BEGIN")
    library_repo.update_lora(
        conn, "x", display_name="X2", description="d2",
        tags=[], trigger_words=[], family_id="sdxl",
    )
    conn.execute("COMMIT")
    assert library_repo.get_lora(conn, "x")["display_name"] == "X2"
