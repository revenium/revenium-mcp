"""Centralized AUTH_MODE parsing for env vs. clerk authentication."""
from __future__ import annotations

import os


def read_auth_mode() -> str:
    """Return the active AUTH_MODE, validated.

    Reads the AUTH_MODE environment variable (default: "env"), normalizes to
    lowercase, and rejects any value other than the supported modes. Raises
    ValueError with a clear message on unknown modes so misconfiguration
    fails fast at startup instead of degrading silently to env mode.

    Returns:
        One of ``"env"`` (default, backward-compat), ``"clerk"``, or ``"api_key"``.

    Raises:
        ValueError: when AUTH_MODE is set to an unsupported value.
    """
    mode = os.getenv("AUTH_MODE", "env").strip().lower()
    if mode not in ("env", "clerk", "api_key"):
        raise ValueError(
            f"AUTH_MODE must be 'env', 'clerk', or 'api_key', got {mode!r}"
        )
    return mode
