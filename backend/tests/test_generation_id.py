"""Unit tests for app.utils.generation_id."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.utils.generation_id import (
    GENERATION_ID_PATTERN,
    is_generation_id,
    new_generation_id,
)


def test_format_matches_pattern():
    gid = new_generation_id()
    assert GENERATION_ID_PATTERN.fullmatch(gid)
    assert is_generation_id(gid)


def test_format_with_explicit_now():
    when = datetime(2026, 5, 8, 14, 30, 12, tzinfo=timezone.utc)
    gid = new_generation_id(when)
    assert gid.startswith("20260508-143012-")
    # Six hex chars after the second dash.
    assert len(gid) == len("20260508-143012-") + 6


def test_unique_ids_in_quick_succession():
    ids = {new_generation_id() for _ in range(50)}
    assert len(ids) == 50  # six hex = 16M combinations, no collisions expected


@pytest.mark.parametrize("bad", [
    "",
    "not-an-id",
    "20260508T143012-a3f4b2",  # wrong separator
    "20260508-143012-A3F4B2",  # uppercase hex
    "20260508-143012-a3f4b",   # too short
    "20260508-143012-a3f4b2x", # trailing junk
])
def test_is_generation_id_rejects_bad_strings(bad):
    assert not is_generation_id(bad)
