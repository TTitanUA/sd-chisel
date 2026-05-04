from __future__ import annotations

import pytest

from app.services import action_settings


# --- parse_bundle: validation -----------------------------------------------


def test_parse_bundle_accepts_valid_keys():
    out = action_settings.parse_bundle(
        {"temperature": 0.7, "top_p": 0.9, "top_k": 40, "max_tokens": 512},
    )
    assert out == {
        "temperature": 0.7,
        "top_p": 0.9,
        "top_k": 40,
        "max_tokens": 512,
    }


def test_parse_bundle_drops_none_values():
    out = action_settings.parse_bundle({"temperature": None, "top_p": 0.9})
    assert out == {"top_p": 0.9}


def test_parse_bundle_rejects_unknown_key():
    with pytest.raises(action_settings.ActionSettingsError):
        action_settings.parse_bundle({"foobar": 1})


def test_parse_bundle_rejects_temperature_out_of_range():
    with pytest.raises(action_settings.ActionSettingsError):
        action_settings.parse_bundle({"temperature": 5.0})


def test_parse_bundle_rejects_top_p_above_one():
    with pytest.raises(action_settings.ActionSettingsError):
        action_settings.parse_bundle({"top_p": 1.5})


def test_parse_bundle_rejects_negative_top_k():
    with pytest.raises(action_settings.ActionSettingsError):
        action_settings.parse_bundle({"top_k": -1})


def test_parse_bundle_rejects_max_tokens_zero():
    with pytest.raises(action_settings.ActionSettingsError):
        action_settings.parse_bundle({"max_tokens": 0})


def test_parse_bundle_rejects_top_k_float():
    with pytest.raises(action_settings.ActionSettingsError):
        action_settings.parse_bundle({"top_k": 3.5})


def test_parse_bundle_rejects_bool_for_number():
    # Booleans are an int subclass in Python; the validator must reject them.
    with pytest.raises(action_settings.ActionSettingsError):
        action_settings.parse_bundle({"temperature": True})


def test_parse_bundle_handles_none_input():
    assert action_settings.parse_bundle(None) == {}


def test_parse_bundle_decodes_json_string():
    assert action_settings.parse_bundle('{"temperature": 0.5}') == {"temperature": 0.5}


def test_parse_bundle_rejects_non_dict():
    with pytest.raises(action_settings.ActionSettingsError):
        action_settings.parse_bundle([1, 2, 3])


# --- encode/decode round-trip -----------------------------------------------


def test_encode_empty_returns_none():
    assert action_settings.encode_bundle({}) is None
    assert action_settings.encode_bundle(None) is None


def test_encode_decode_round_trip():
    bundle = {"temperature": 0.5, "top_p": 0.9}
    encoded = action_settings.encode_bundle(bundle)
    assert encoded is not None
    assert action_settings.decode_bundle(encoded) == bundle


def test_decode_null_returns_none():
    assert action_settings.decode_bundle(None) is None


def test_decode_garbage_returns_empty_dict():
    # Defensive: corrupt rows decode to {} so callers can keep going.
    assert action_settings.decode_bundle("not json") == {}


def test_decode_drops_unknown_keys():
    raw = '{"temperature": 0.5, "rogue": "x"}'
    assert action_settings.decode_bundle(raw) == {"temperature": 0.5}


# --- resolve: per-key fallback ---------------------------------------------


def test_resolve_null_session_inherits_full_default():
    out = action_settings.resolve(
        None, {"temperature": 0.7, "top_p": 0.9},
    )
    assert out == {"temperature": 0.7, "top_p": 0.9}


def test_resolve_session_overrides_per_key():
    out = action_settings.resolve(
        {"temperature": 0.1}, {"temperature": 0.7, "top_p": 0.9},
    )
    assert out == {"temperature": 0.1, "top_p": 0.9}


def test_resolve_session_only_when_no_default():
    out = action_settings.resolve({"temperature": 0.4}, None)
    assert out == {"temperature": 0.4}


def test_resolve_empty_when_both_empty():
    assert action_settings.resolve({}, {}) == {}


def test_resolve_drops_session_none_keys():
    out = action_settings.resolve(
        {"temperature": None, "top_p": 0.5}, {"temperature": 0.7},
    )
    assert out == {"temperature": 0.7, "top_p": 0.5}
