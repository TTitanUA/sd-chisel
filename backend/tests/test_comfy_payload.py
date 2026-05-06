"""Unit tests for ``comfy_payload`` — Phase 3 prep dynamic schema +
validator + slot-context block builders.

Covers the worked-example shape from
docs/comfy-workflow-plan.md (eight-slot regional workflow, mixed llm
+ frozen bindings) plus per-kind type / range / enum failures.
"""
from __future__ import annotations

import pytest

from app.services import comfy_payload


def _slot(label: str, kind: str, binding: str, **kwargs):
    return {
        "label": label,
        "group": kwargs.pop("group", None),
        "ordinal": kwargs.pop("ordinal", None),
        "description": kwargs.pop("description", None),
        "kind": kind,
        "origin": {"node_id": kwargs.pop("node_id", "1"),
                   "input_name": kwargs.pop("input_name", label)},
        "binding": binding,
        "metadata": kwargs.pop("metadata", {}),
    }


# --- validate_payload -----------------------------------------------------


def test_validate_payload_happy_path():
    slots = [
        _slot("positive", "multiline_text", "llm"),
        _slot("steps", "number_int", "llm",
              metadata={"min": 1, "max": 200}),
        _slot("cfg", "number_float", "llm",
              metadata={"min": 0, "max": 30}),
        _slot("seed", "number_int", "frozen", metadata={"value": 42}),
    ]
    raw = {
        "positive": "moody noir",
        "steps": 30,
        "cfg": 7.5,
        comfy_payload.LORAS_KEY: [{"name": "noir", "weight": 0.6}],
    }
    out = comfy_payload.validate_payload(raw, slots)
    assert out == {
        "positive": "moody noir",
        "steps": 30,
        "cfg": 7.5,
        comfy_payload.LORAS_KEY: [{"name": "noir", "weight": 0.6}],
    }


def test_validate_payload_missing_loras_defaults_to_empty():
    slots = [_slot("positive", "text", "llm")]
    out = comfy_payload.validate_payload({"positive": "x"}, slots)
    assert out[comfy_payload.LORAS_KEY] == []


def test_validate_payload_rejects_missing_field():
    slots = [_slot("positive", "text", "llm")]
    with pytest.raises(comfy_payload.PayloadValidationError) as exc:
        comfy_payload.validate_payload({comfy_payload.LORAS_KEY: []}, slots)
    assert "positive" in str(exc.value)


def test_validate_payload_rejects_wrong_type():
    slots = [_slot("steps", "number_int", "llm")]
    with pytest.raises(comfy_payload.PayloadValidationError):
        comfy_payload.validate_payload(
            {"steps": "twenty", comfy_payload.LORAS_KEY: []}, slots,
        )


def test_validate_payload_rejects_bool_for_int_slot():
    """Python ``bool`` is a subclass of ``int`` — make sure the
    validator rejects it for ``number_int`` slots."""
    slots = [_slot("steps", "number_int", "llm")]
    with pytest.raises(comfy_payload.PayloadValidationError):
        comfy_payload.validate_payload(
            {"steps": True, comfy_payload.LORAS_KEY: []}, slots,
        )


def test_validate_payload_enforces_number_range():
    slots = [_slot("steps", "number_int", "llm",
                   metadata={"min": 1, "max": 200})]
    with pytest.raises(comfy_payload.PayloadValidationError) as exc:
        comfy_payload.validate_payload(
            {"steps": 500, comfy_payload.LORAS_KEY: []}, slots,
        )
    assert "above the maximum" in str(exc.value)


def test_validate_payload_enforces_enum_membership():
    slots = [_slot("sampler", "enum", "llm",
                   metadata={"options": ["euler", "dpmpp_2m"]})]
    with pytest.raises(comfy_payload.PayloadValidationError) as exc:
        comfy_payload.validate_payload(
            {"sampler": "ddim", comfy_payload.LORAS_KEY: []}, slots,
        )
    assert "ddim" in str(exc.value)


def test_validate_payload_skips_non_llm_slots():
    """Slots with non-llm bindings must NOT appear in the LLM's payload
    — they're filled from the slot map directly."""
    slots = [
        _slot("positive", "text", "llm"),
        _slot("seed", "number_int", "frozen", metadata={"value": 7}),
        _slot("main_image", "image", "user_image"),
    ]
    out = comfy_payload.validate_payload(
        {"positive": "x", comfy_payload.LORAS_KEY: []}, slots,
    )
    assert "seed" not in out
    assert "main_image" not in out


def test_validate_payload_rejects_malformed_loras():
    slots = [_slot("positive", "text", "llm")]
    with pytest.raises(comfy_payload.PayloadValidationError):
        comfy_payload.validate_payload(
            {"positive": "x",
             comfy_payload.LORAS_KEY: [{"name": "ok", "weight": 99.9}]},
            slots,
        )


def test_validate_payload_rejects_non_dict_input():
    with pytest.raises(comfy_payload.PayloadValidationError):
        comfy_payload.validate_payload([1, 2, 3], [])


# --- split_loras ---------------------------------------------------------


def test_split_loras_separates_payload_and_loras():
    payload = {
        "positive": "x",
        comfy_payload.LORAS_KEY: [{"name": "a", "weight": 0.5}],
    }
    rest, loras = comfy_payload.split_loras(payload)
    assert rest == {"positive": "x"}
    assert loras == [{"name": "a", "weight": 0.5}]


def test_split_loras_handles_missing_key():
    rest, loras = comfy_payload.split_loras({"positive": "x"})
    assert rest == {"positive": "x"}
    assert loras == []


# --- build_schema_hint ----------------------------------------------------


def test_schema_hint_lists_each_llm_slot():
    slots = [
        _slot("positive", "text", "llm"),
        _slot("steps", "number_int", "llm",
              metadata={"min": 1, "max": 200}),
        _slot("seed", "number_int", "frozen", metadata={"value": 7}),
    ]
    hint = comfy_payload.build_schema_hint(slots)
    assert "'positive'" in hint
    assert "'steps'" in hint
    # frozen slot is not in the hint (LLM doesn't fill it).
    assert "'seed'" not in hint
    assert comfy_payload.LORAS_KEY in hint
    # Number range hint shows up.
    assert "min=1" in hint and "max=200" in hint


def test_schema_hint_marks_no_slot_case():
    """When the slot map has only frozen / image slots, the hint still
    asks for ``__loras`` and notes there are no slot fields."""
    slots = [_slot("seed", "number_int", "frozen",
                   metadata={"value": 7})]
    hint = comfy_payload.build_schema_hint(slots)
    assert "no slot fields" in hint
    assert comfy_payload.LORAS_KEY in hint


def test_schema_hint_inlines_enum_options():
    slots = [_slot("sampler", "enum", "llm",
                   metadata={"options": ["euler", "ddim"]})]
    hint = comfy_payload.build_schema_hint(slots)
    assert "['euler', 'ddim']" in hint


# --- build_slot_context_block ---------------------------------------------


def test_slot_context_block_describes_every_slot():
    slots = [
        _slot("positive", "multiline_text", "llm",
              description="positive prompt"),
        _slot("seed", "number_int", "frozen", metadata={"value": 42}),
        _slot("main_image", "image", "user_image"),
    ]
    block = comfy_payload.build_slot_context_block(slots)
    assert "[fill] positive" in block
    assert "[frozen=42]" in block
    assert "[user image] main_image" in block
    assert "positive prompt" in block  # description rendered


def test_slot_context_block_empty_for_no_slots():
    assert comfy_payload.build_slot_context_block([]) == ""


# --- build_chat_slot_block (Q9) -------------------------------------------


def test_chat_slot_block_lists_each_slot_and_forbids_json():
    slots = [
        _slot("positive", "text", "llm",
              description="main positive prompt", group="Region 1"),
        _slot("seed", "number_int", "frozen", metadata={"value": 1}),
    ]
    block = comfy_payload.build_chat_slot_block(slots)
    assert "Region 1/positive (text): main positive prompt" in block
    assert "seed (int)" in block
    assert "Do not emit JSON" in block


def test_chat_slot_block_empty_for_no_slots():
    assert comfy_payload.build_chat_slot_block([]) == ""
