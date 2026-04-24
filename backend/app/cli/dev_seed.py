"""CLI: seed library tables from `mvp-ui-mock/app/data.js`.

Invoke:  uv run dev-seed

Idempotent insert-only: existing rows (by primary key) are left unchanged.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Any

from app.cli.mvp_data_js import MvpDataParseError, load_mvp_library_data
from app.config import resolve_data_root
from app.storage import db as db_mod
from app.storage import library_repo as lib
from app.storage.migrations import apply_pending

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def resolve_mvp_data_js() -> Path:
    """`<repo>/mvp-ui-mock/app/data.js` relative to the repository root."""
    return resolve_data_root(anchor_file=Path(__file__)).parent / "mvp-ui-mock" / "app" / "data.js"


def run_dev_seed(
    conn: sqlite3.Connection,
    *,
    data_js: Path | None = None,
    library: tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]] | None = None,
) -> dict[str, tuple[int, int]]:
    """Insert missing families, models, loras from mock. Returns label -> (created, skipped)."""
    if library is None:
        if data_js is None:
            raise ValueError("pass data_js or library=")
        families, models, loras = load_mvp_library_data(data_js)
    else:
        families, models, loras = library
    fam_ids = {str(f["id"]) for f in families}

    fam_c = fam_s = 0
    mod_c = mod_s = 0
    lora_c = lora_s = 0
    warnings: list[str] = []

    for row in families:
        fid = str(row["id"])
        if lib.get_family(conn, fid):
            fam_s += 1
            continue
        lib.create_family(
            conn,
            id=fid,
            display_name=str(row["display_name"]),
            prompt_guide=str(row["prompt_guide"]),
        )
        fam_c += 1

    for row in models:
        name = str(row["name"])
        if lib.get_model(conn, name):
            mod_s += 1
            continue
        family_id = str(row["family_id"])
        if family_id not in fam_ids:
            warnings.append(
                f"model {name!r}: family_id {family_id!r} not in mvp FAMILIES; skipped"
            )
            mod_s += 1
            continue
        desc = row.get("description")
        lib.create_model(
            conn,
            name=name,
            display_name=str(row["display_name"]),
            family_id=family_id,
            description=None if desc is None else str(desc),
            author=None if row.get("author") is None else str(row["author"]),
            version=None if row.get("version") is None else str(row["version"]),
            source_url=None,
        )
        mod_c += 1

    for row in loras:
        name = str(row["name"])
        if lib.get_lora(conn, name):
            lora_s += 1
            continue
        raw_fid = row.get("family_id")
        if raw_fid is None or (isinstance(raw_fid, str) and not raw_fid.strip()):
            warnings.append(f"lora {name!r}: family_id is required; skipped")
            lora_s += 1
            continue
        family_id = str(raw_fid).strip()
        if family_id not in fam_ids:
            warnings.append(
                f"lora {name!r}: family_id {family_id!r} not in mvp FAMILIES; skipped"
            )
            lora_s += 1
            continue
        if lib.get_family(conn, family_id) is None:
            warnings.append(f"lora {name!r}: family missing in DB {family_id!r}; skipped")
            lora_s += 1
            continue

        tags = row.get("tags") or []
        triggers = row.get("trigger_words") or []
        if not isinstance(tags, list) or not isinstance(triggers, list):
            warnings.append(f"lora {name!r}: tags/trigger_words must be lists; skipped")
            lora_s += 1
            continue

        rw = row.get("recommended_weight")
        lib.create_lora(
            conn,
            name=name,
            display_name=str(row["display_name"]),
            description=str(row["description"]),
            tags=[str(t) for t in tags],
            trigger_words=[str(t) for t in triggers],
            family_id=family_id,
            recommended_weight=float(rw) if rw is not None else None,
            author=None if row.get("author") is None else str(row["author"]),
            version=None if row.get("version") is None else str(row["version"]),
            source_url=None,
        )
        lora_c += 1

    for w in warnings:
        print(f"Warning: {w}", file=sys.stderr)

    return {
        "families": (fam_c, fam_s),
        "models": (mod_c, mod_s),
        "loras": (lora_c, lora_s),
    }


def main() -> None:
    data_js = resolve_mvp_data_js()
    if not data_js.is_file():
        print(f"dev-seed: data file not found: {data_js}", file=sys.stderr)
        sys.exit(1)

    try:
        library = load_mvp_library_data(data_js)
    except (MvpDataParseError, FileNotFoundError) as e:
        print(f"dev-seed: failed to read {data_js}: {e}", file=sys.stderr)
        sys.exit(1)

    conn = db_mod.connect()
    try:
        applied = apply_pending(conn, MIGRATIONS_DIR)
        stats = run_dev_seed(conn, library=library)
        print(f"Applied {applied} migration(s). DB at {db_mod.db_path()}")
        for label, (created, skipped) in stats.items():
            print(f"  {label}: created={created} skipped={skipped}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
