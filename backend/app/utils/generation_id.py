"""Stable, sortable, unique IDs for ComfyUI generations.

Phase 3 stamps every workflow run with a generation id used for two
unrelated purposes:

- Disk layout: each run writes to
  ``data/images/<sid>/output/<generation_id>/<label>.<ext>`` so the
  history list and the file system stay in sync without a JOIN.
- History sort order: the lexicographic order of the id matches the
  chronological order of the run, so the UI can sort the history list
  by id without an extra ``created_at`` lookup.

Format: ``YYYYMMDD-HHMMSS-RRRRRR`` where ``RRRRRR`` is six lowercase
hex characters from :mod:`secrets`. Examples::

    20260508-143012-a3f4b2
    20260131-002359-0e1f9c

The seconds-resolution prefix sorts correctly across days, the
six-hex suffix gives 16M combinations per second (effectively
collision-free), and the dashed shape is filesystem-safe on every
platform sd-chisel runs on. ``re.fullmatch(_GENERATION_ID_RE, …)``
verifies the shape — used by tests and by future deserialisers.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone

_RAND_HEX_LEN = 6


GENERATION_ID_PATTERN: re.Pattern[str] = re.compile(
    r"^\d{8}-\d{6}-[0-9a-f]{6}$",
)


def new_generation_id(now: datetime | None = None) -> str:
    """Mint a fresh generation id. ``now`` is overridable for tests; in
    production callers pass nothing and the function uses UTC."""
    when = now or datetime.now(timezone.utc)
    stamp = when.strftime("%Y%m%d-%H%M%S")
    suffix = secrets.token_hex(_RAND_HEX_LEN // 2)
    # token_hex(n) yields 2*n chars; the //2 above keeps us at exactly
    # _RAND_HEX_LEN characters of entropy.
    return f"{stamp}-{suffix}"


def is_generation_id(value: str) -> bool:
    """True if ``value`` looks like a generation id we minted."""
    return bool(GENERATION_ID_PATTERN.fullmatch(value))
