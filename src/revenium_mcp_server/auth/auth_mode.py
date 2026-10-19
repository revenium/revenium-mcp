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


def auth_mode_is_explicit() -> bool:
    """Return True when the operator set AUTH_MODE.

    False means read_auth_mode's ``"env"`` default applies.
    """
    return os.getenv("AUTH_MODE") is not None


def credentials_are_per_request() -> bool:
    """True when each caller brings its own credential.

    One process then serves many organizations, so process-wide state mixes them.
    """
    return read_auth_mode() in ("clerk", "api_key")
