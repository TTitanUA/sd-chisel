"""Unit tests for app.services.comfy_slot_map_service (Phase 2.5)."""
from __future__ import annotations

import pytest

from app.services import comfy_slot_map_service as svc


def _bucket(*items: dict) -> dict[str, list[dict]]:
    """Build a candidate-bucket dict keyed by each item's kind."""
    out: dict[str, list[dict]] = {kind: [] for kind in (
        "text", "multiline_text", "image", "image_alpha",
        "number_int", "number_float", "boolean",
        "enum", "lora_name", "checkpoint_name",
    )}
    for item in items:
        out[item["kind"]].append(item)
    return out


def _candidate(
    node_id: str,
    input_name: str,
    *,
    kind: str,
    metadata: dict | None = None,
    current_value=None,
    node_class_type: str | None = None,
) -> dict:
    # ``node_class_type`` defaults to "X" for non-image kinds and to
    # "LoadImage" for image kinds — the latter is required by the
    # validator's defence-in-depth guard, and writing it everywhere by
    # hand would just churn the test bodies.
    if node_class_type is None:
        node_class_type = "LoadImage" if kind in ("image", "image_alpha") else "X"
    return {
        "node_id": node_id,
        "input_name": input_name,
        "node_class_type": node_class_type,
        "node_display_name": None,
        "node_title": None,
        "node_in_catalog": True,
        "current_value": current_value,
        "kind": kind,
        "metadata": metadata or {},
    }


# --- upgrade_slot_map ----------------------------------------------------


def test_upgrade_none_returns_empty_v2():
    out = svc.upgrade_slot_map(raw=None, candidates=_bucket())
    assert out == {"version": 2, "slots": []}


def test_upgrade_v1_three_slots_to_v2():
    cand_pos = _candidate("6", "text", kind="multiline_text", metadata={"multiline": True})
    cand_neg = _candidate("7", "text", kind="text", metadata={"multiline": False})
    cand_img = _candidate("10", "image", kind="image")
    candidates = _bucket(cand_pos, cand_neg, cand_img)

    raw_v1 = {
        "positive_prompt": {"node_id": "6", "input_name": "text"},
        "negative_prompt": {"node_id": "7", "input_name": "text"},
        "main_image": {"node_id": "10", "input_name": "image"},
    }
    out = svc.upgrade_slot_map(raw=raw_v1, candidates=candidates)
    assert out["version"] == 2
    assert [s["label"] for s in out["slots"]] == [
        "positive_prompt", "negative_prompt", "main_image",
    ]
    # kind is borrowed from the candidate, not assumed.
    assert out["slots"][0]["kind"] == "multiline_text"
    assert out["slots"][1]["kind"] == "text"
    assert out["slots"][2]["kind"] == "image"
    assert [s["binding"] for s in out["slots"]] == ["llm", "llm", "user_image"]


def test_upgrade_v1_drops_assignments_with_no_matching_candidate():
    candidates = _bucket(_candidate("6", "text", kind="text"))
    raw_v1 = {
        "positive_prompt": {"node_id": "6", "input_name": "text"},
        "negative_prompt": {"node_id": "9999", "input_name": "ghost"},
        "main_image": None,
    }
    out = svc.upgrade_slot_map(raw=raw_v1, candidates=candidates)
    assert [s["label"] for s in out["slots"]] == ["positive_prompt"]


def test_upgrade_v2_drops_slots_with_kind_drift():
    """If the underlying input's kind changed (e.g. workflow replaced
    and the input is now a number), the upgrade silently drops the
    slot — the editor will show the user."""
    saved = {
        "version": 2,
        "slots": [
            {
                "label": "kept",
                "group": None, "ordinal": 1, "description": None,
                "kind": "text",
                "origin": {"node_id": "6", "input_name": "text"},
                "binding": "llm", "metadata": {},
            },
            {
                "label": "drifted",
                "group": None, "ordinal": 2, "description": None,
                "kind": "text",
                "origin": {"node_id": "3", "input_name": "seed"},
                "binding": "llm", "metadata": {},
            },
        ],
    }
    candidates = _bucket(
        _candidate("6", "text", kind="text"),
        _candidate("3", "seed", kind="number_int"),
    )
    out = svc.upgrade_slot_map(raw=saved, candidates=candidates)
    assert [s["label"] for s in out["slots"]] == ["kept"]


# --- infer_mode ----------------------------------------------------------


def test_infer_mode_t2i_when_no_image_user_binding():
    payload = {
        "version": 2,
        "slots": [
            {
                "label": "p", "kind": "text",
                "origin": {"node_id": "6", "input_name": "text"},
                "binding": "llm", "metadata": {},
            },
        ],
    }
    assert svc.infer_mode(payload) == "t2i"


def test_infer_mode_i2i_when_user_image_slot_present():
    payload = {
        "version": 2,
        "slots": [
            {
                "label": "src", "kind": "image",
                "origin": {"node_id": "10", "input_name": "image"},
                "binding": "user_image", "metadata": {},
            },
        ],
    }
    assert svc.infer_mode(payload) == "i2i"


def test_infer_mode_ignores_frozen_image():
    payload = {
        "version": 2,
        "slots": [
            {
                "label": "ref", "kind": "image",
                "origin": {"node_id": "10", "input_name": "image"},
                "binding": "frozen", "metadata": {"value": "ref.png"},
            },
        ],
    }
    assert svc.infer_mode(payload) == "t2i"


# --- validate_slots ------------------------------------------------------


def _ok_text_slot(label="p"):
    return {
        "label": label, "group": None, "ordinal": None,
        "description": None, "kind": "text",
        "origin": {"node_id": "6", "input_name": "text"},
        "binding": "llm", "metadata": {},
    }


def test_validate_accepts_well_formed_slot():
    candidates = _bucket(_candidate("6", "text", kind="text"))
    out = svc.validate_slots(slots=[_ok_text_slot()], candidates=candidates)
    assert len(out) == 1
    assert out[0]["label"] == "p"


def test_validate_rejects_duplicate_labels():
    candidates = _bucket(
        _candidate("6", "text", kind="text"),
        _candidate("7", "text", kind="text"),
    )
    slots = [
        _ok_text_slot("dupe"),
        {
            **_ok_text_slot("dupe"),
            "origin": {"node_id": "7", "input_name": "text"},
        },
    ]
    with pytest.raises(svc.SlotMapValidationError, match="duplicate"):
        svc.validate_slots(slots=slots, candidates=candidates)


def test_validate_rejects_unknown_origin():
    candidates = _bucket(_candidate("6", "text", kind="text"))
    bad = {
        **_ok_text_slot(), "origin": {"node_id": "999", "input_name": "x"},
    }
    with pytest.raises(svc.SlotMapValidationError, match="not an eligible"):
        svc.validate_slots(slots=[bad], candidates=candidates)


def test_validate_rejects_kind_mismatch():
    candidates = _bucket(_candidate("6", "text", kind="text"))
    bad = {**_ok_text_slot(), "kind": "image"}
    with pytest.raises(svc.SlotMapValidationError, match="kind"):
        svc.validate_slots(slots=[bad], candidates=candidates)


def test_validate_rejects_disallowed_binding_for_kind():
    candidates = _bucket(_candidate("10", "image", kind="image"))
    bad = {
        "label": "img", "group": None, "ordinal": None, "description": None,
        "kind": "image",
        "origin": {"node_id": "10", "input_name": "image"},
        "binding": "llm",
        "metadata": {},
    }
    with pytest.raises(svc.SlotMapValidationError, match="not allowed"):
        svc.validate_slots(slots=[bad], candidates=candidates)


def test_validate_frozen_int_respects_range():
    candidates = _bucket(_candidate(
        "3", "seed", kind="number_int",
        metadata={"min": 0, "max": 1000},
    ))
    base = {
        "label": "seed", "group": None, "ordinal": None, "description": None,
        "kind": "number_int",
        "origin": {"node_id": "3", "input_name": "seed"},
        "binding": "frozen", "metadata": {"value": 50},
    }
    svc.validate_slots(slots=[base], candidates=candidates)

    too_high = {**base, "metadata": {"value": 9999}}
    with pytest.raises(svc.SlotMapValidationError, match="maximum"):
        svc.validate_slots(slots=[too_high], candidates=candidates)


def test_validate_frozen_enum_must_match_options():
    candidates = _bucket(_candidate(
        "8", "sampler_name", kind="enum",
        metadata={"options": ["euler", "dpmpp_2m"]},
    ))
    base = {
        "label": "sampler", "group": None, "ordinal": None, "description": None,
        "kind": "enum",
        "origin": {"node_id": "8", "input_name": "sampler_name"},
        "binding": "frozen", "metadata": {"value": "euler"},
    }
    svc.validate_slots(slots=[base], candidates=candidates)

    bad = {**base, "metadata": {"value": "ghost_sampler"}}
    with pytest.raises(svc.SlotMapValidationError, match="options"):
        svc.validate_slots(slots=[bad], candidates=candidates)


def test_validate_rejects_library_loras_binding():
    candidates = _bucket(_candidate(
        "5", "lora_name", kind="lora_name",
        metadata={"options": ["x.safetensors"]},
    ))
    bad = {
        "label": "loras", "group": None, "ordinal": None, "description": None,
        "kind": "lora_name",
        "origin": {"node_id": "5", "input_name": "lora_name"},
        "binding": "library_loras",
        "metadata": {},
    }
    with pytest.raises(svc.SlotMapValidationError):
        svc.validate_slots(slots=[bad], candidates=candidates)
