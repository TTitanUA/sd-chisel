from pathlib import Path

import pytest

from app.cli.dev_seed import run_dev_seed
from app.cli.mvp_data_js import load_mvp_library_data, parse_js_value
from app.config import resolve_data_root
from app.storage import db as db_mod
from app.storage import library_repo
from app.storage.migrations import apply_pending

MINIMAL_DATA_JS = """
const FAMILIES = [
  { id: 'sdxl', display_name: 'SDXL', prompt_guide: 'guide' },
];
const MODELS = [
  { name: 'm1', display_name: 'M1', family_id: 'sdxl', description: 'd', author: 'a', version: '1' },
];
const LORAS = [
  { name: 'l1', display_name: 'L1', family_id: 'sdxl', tags: ['t'], trigger_words: ['tw'], recommended_weight: 0.5, author: 'x', description: 'desc' },
];
"""


@pytest.fixture
def conn(tmp_path):
    c = db_mod.connect(tmp_path / "t.db")
    apply_pending(c, Path(__file__).parent.parent / "migrations")
    yield c
    c.close()


def test_parse_js_trailing_commas():
    v = parse_js_value("""[ { a: 1, b: 'x', }, ]""")
    assert v == [{"a": 1, "b": "x"}]


def test_load_mvp_library_data_minimal(tmp_path):
    p = tmp_path / "data.js"
    p.write_text(MINIMAL_DATA_JS, encoding="utf-8")
    f, m, loras = load_mvp_library_data(p)
    assert len(f) == 1 and f[0]["id"] == "sdxl"
    assert len(m) == 1 and m[0]["name"] == "m1"
    assert len(loras) == 1 and loras[0]["name"] == "l1"


def test_load_real_mvp_data_js():
    data_js = resolve_data_root().parent / "mvp-ui-mock" / "app" / "data.js"
    f, m, loras = load_mvp_library_data(data_js)
    assert len(f) == 10
    assert len(m) == 50
    assert len(loras) == 50


def test_run_dev_seed_inserts_lora_family(conn, tmp_path):
    p = tmp_path / "data.js"
    p.write_text(MINIMAL_DATA_JS, encoding="utf-8")
    stats = run_dev_seed(conn, data_js=p)
    # Migration already seeds the same 10 families (incl. sdxl)
    assert stats["families"] == (0, 1)
    assert stats["models"] == (1, 0)
    assert stats["loras"] == (1, 0)

    fam = library_repo.get_family(conn, "sdxl")
    assert fam is not None

    m = library_repo.get_model(conn, "m1")
    assert m is not None and m["family_id"] == "sdxl"

    lora = library_repo.get_lora(conn, "l1")
    assert lora is not None
    assert lora["family_id"] == "sdxl"
    row = conn.execute("SELECT family_id FROM loras WHERE name = ?", ("l1",)).fetchone()
    assert row is not None and row[0] == "sdxl"


def test_run_dev_seed_idempotent(conn, tmp_path):
    p = tmp_path / "data.js"
    p.write_text(MINIMAL_DATA_JS, encoding="utf-8")
    s1 = run_dev_seed(conn, data_js=p)
    s2 = run_dev_seed(conn, data_js=p)
    assert s1["models"] == (1, 0)
    assert s2["families"] == (0, 1)
    assert s2["models"] == (0, 1)
    assert s2["loras"] == (0, 1)


def test_run_dev_seed_skips_model_with_bad_family(conn, tmp_path):
    bad = """
const FAMILIES = [
  { id: 'sdxl', display_name: 'SDXL', prompt_guide: 'g' },
];
const MODELS = [
  { name: 'bad_m', display_name: 'Bad', family_id: 'missing', description: 'd' },
];
const LORAS = [
  { name: 'l2', display_name: 'L2', family_id: 'sdxl', tags: [], trigger_words: [], description: 'x' },
];
"""
    p = tmp_path / "data.js"
    p.write_text(bad, encoding="utf-8")
    stats = run_dev_seed(conn, data_js=p)
    assert library_repo.get_model(conn, "bad_m") is None
    assert stats["models"] == (0, 1)
    l2 = library_repo.get_lora(conn, "l2")
    assert l2 is not None
    assert l2["name"] == "l2"
