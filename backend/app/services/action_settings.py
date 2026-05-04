"""Per-action LLM sampling-settings: validation, encoding, resolution.

Each LLM action carries a bundle of optional OpenAI-compat sampling
parameters. Bundles are stored as JSON in
``app_settings.default_<action>_settings`` (app-wide default), and for
session-scoped actions also in ``sessions.<action>_settings``
(per-session override). At call time, ``resolve`` merges them per-key —
the session value wins when set, otherwise the app default is used.

The ``comfy_import`` action is global rather than session-scoped: it
drives the per-node import wizard's LLM enrichment step, which produces
catalog rows keyed by class_type, not by session. Only the app-default
column exists for it; ``resolve_for_session`` falls back to a
session-less default lookup when called for this action.

This module is the single source of truth for which keys are allowed
and their value ranges. Adding a new sampling parameter here
automatically flows to every action and to the API validation layer.
"""
from __future__ import annotations

import json
from typing import Any, Literal

Action = Literal["analyze", "chat", "summarize", "generate", "comfy_import"]
ACTIONS: tuple[Action, ...] = (
    "analyze", "chat", "summarize", "generate", "comfy_import",
)


class ActionSettingsError(ValueError):
    """Raised for malformed bundles. The API layer maps to HTTP 400."""


def _check_number(key: str, value: Any, *, lo: float, hi: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ActionSettingsError(f"{key}: expected number, got {type(value).__name__}")
    f = float(value)
    if f < lo or f > hi:
        raise ActionSettingsError(f"{key}: must be in [{lo}, {hi}], got {f}")
    return f


def _check_int(key: str, value: Any, *, lo: int | None = None, hi: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ActionSettingsError(f"{key}: expected integer, got {type(value).__name__}")
    if lo is not None and value < lo:
        raise ActionSettingsError(f"{key}: must be >= {lo}, got {value}")
    if hi is not None and value > hi:
        raise ActionSettingsError(f"{key}: must be <= {hi}, got {value}")
    return value


# Allowed keys + per-key validators. Keep in sync with the frontend field
# registry (frontend/src/components/organisms/ActionSettingsModal/fields.ts).
_VALIDATORS = {
    "temperature":       lambda v: _check_number("temperature", v, lo=0.0, hi=2.0),
    "top_p":             lambda v: _check_number("top_p", v, lo=0.0, hi=1.0),
    "top_k":             lambda v: _check_int("top_k", v, lo=0),
    "max_tokens":        lambda v: _check_int("max_tokens", v, lo=1),
    "presence_penalty":  lambda v: _check_number("presence_penalty", v, lo=-2.0, hi=2.0),
    "frequency_penalty": lambda v: _check_number("frequency_penalty", v, lo=-2.0, hi=2.0),
    "repeat_penalty":    lambda v: _check_number("repeat_penalty", v, lo=0.0, hi=2.0),
    "seed":              lambda v: _check_int("seed", v),
}
ALLOWED_KEYS = frozenset(_VALIDATORS.keys())


def parse_bundle(value: Any) -> dict[str, Any]:
    """Validate an incoming bundle. Returns a normalized dict.

    Accepts either a dict (already-decoded) or a JSON string. Unknown keys
    raise ``ActionSettingsError``. Keys with ``None`` values are dropped —
    "no override" is expressed by absence, not by null.
    """
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ActionSettingsError(f"invalid JSON: {exc}") from exc
        return parse_bundle(decoded)
    if not isinstance(value, dict):
        raise ActionSettingsError(
            f"bundle must be an object, got {type(value).__name__}",
        )
    out: dict[str, Any] = {}
    for k, v in value.items():
        if k not in ALLOWED_KEYS:
            raise ActionSettingsError(f"unknown key: {k!r}")
        if v is None:
            continue
        out[k] = _VALIDATORS[k](v)
    return out


def encode_bundle(bundle: dict[str, Any] | None) -> str | None:
    """Encode a validated bundle for storage. Returns None for empty/None."""
    if not bundle:
        return None
    return json.dumps(bundle, ensure_ascii=False, sort_keys=True)


def decode_bundle(raw: str | None) -> dict[str, Any] | None:
    """Decode a stored bundle. Returns None if the column is NULL.

    Returns an empty dict for the rare case where a non-NULL string
    decodes to ``{}`` — that means the user explicitly cleared all
    overrides for the action while still keeping the row distinct from
    "inherit the whole default bundle".
    """
    if raw is None:
        return None
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(decoded, dict):
        return {}
    # Defensive: drop unknown keys / None values picked up from older rows.
    return {k: v for k, v in decoded.items() if k in ALLOWED_KEYS and v is not None}


def resolve(
    session_bundle: dict[str, Any] | None,
    default_bundle: dict[str, Any] | None,
) -> dict[str, Any]:
    """Per-key merge: session override wins, otherwise inherit default.

    A NULL session bundle inherits the full default. A non-NULL session
    bundle inherits only the keys it does not specify.
    """
    base = dict(default_bundle or {})
    if session_bundle is None:
        return base
    base.update({k: v for k, v in session_bundle.items() if v is not None})
    return base


SESSION_SCOPED_ACTIONS: tuple[Action, ...] = (
    "analyze", "chat", "summarize", "generate",
)


# Builtin baseline used when neither the user nor the migration set a
# default — ``settings_repo.get_default_bundle`` folds these in when the
# stored column is NULL. Only ``comfy_import`` carries baked-in
# defaults: it's the one action where running with no overrides
# produces unusable output (reasoning models burn the token budget on
# <think> blocks). The other four happily run on the model's native
# sampling, so we leave them empty.
BUILTIN_DEFAULTS: dict[Action, dict[str, Any]] = {
    "comfy_import": {"temperature": 0.1, "max_tokens": 2000},
}


def resolve_for_session(
    conn: Any, session: dict[str, Any], action: Action,
) -> dict[str, Any]:
    """High-level resolver used by API call sites.

    Reads the per-action default bundle from app_settings and merges it
    with the session's per-action override. ``session`` is the row dict
    returned by ``session_repo.get_session`` (with bundles already
    decoded). Returns the final bundle ready to pass as ``sampling=`` to
    the lmstudio_client functions.

    Global actions (``comfy_import``) have no session-scope column; the
    app-default bundle is returned directly.
    """
    # Local import keeps this module free of storage-layer cycles.
    from app.storage import settings_repo

    default_bundle = settings_repo.get_default_bundle(conn, action)
    if action not in SESSION_SCOPED_ACTIONS:
        return default_bundle
    session_bundle = session.get(f"{action}_settings")
    return resolve(session_bundle, default_bundle)
