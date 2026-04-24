from __future__ import annotations

import secrets

_ID_BYTES = 5


def new_id() -> str:
    """Generate a 10-char hex id (~1 trillion combinations; PK collision retried by caller)."""
    return secrets.token_hex(_ID_BYTES)
