"""Centralized TRANSPORT_MODE parsing and HTTP host/port resolution.

Kept at the top level (not under auth/) because transport selection is
orthogonal to authentication — coupling them was an artifact of Phase 2's
initial wiring (BACK-850) and is the motivation for this ticket (BACK-859).
"""
from __future__ import annotations

import os

from loguru import logger


def read_transport_mode() -> str:
    """Return the active TRANSPORT_MODE, validated.

    Reads the TRANSPORT_MODE env var (default: "stdio"), normalizes to
    lowercase, and rejects any value other than the supported modes. Raises
    ValueError with a clear message on unknown modes so misconfiguration
    fails fast at startup instead of degrading silently.

    Returns:
        Either ``"stdio"`` (default) or ``"http"``.

    Raises:
        ValueError: when TRANSPORT_MODE is set to an unsupported value.
    """
    mode = os.getenv("TRANSPORT_MODE", "stdio").strip().lower()
    if mode not in ("stdio", "http"):
        raise ValueError(
            f"TRANSPORT_MODE must be 'stdio' or 'http', got {mode!r}"
        )
    return mode


# Per-var dedup flag so each deprecation/conflict warning fires once per process.
# Tests reset this via the `reset_alias_warnings` autouse fixture.
_warned_aliases: set[str] = set()


def _warn_once(alias_name: str, message: str) -> None:
    if alias_name in _warned_aliases:
        return
    _warned_aliases.add(alias_name)
    logger.warning(message)


def _read_with_alias(primary: str, alias: str, default: str) -> tuple[str, str]:
    """Read primary env var, falling back to a deprecated alias.

    Precedence: primary > alias > default. Logs a one-time deprecation
    warning when only the alias is set, and a one-time conflict warning
    when both are set (primary wins).

    Returns:
        A tuple ``(value, source)`` where ``source`` is the env var name that
        supplied the value (``primary`` when the primary or default is used;
        ``alias`` when only the alias is set). Callers can use ``source`` to
        produce error messages that match what the user actually configured.
    """
    primary_val = os.getenv(primary, "").strip()
    alias_val = os.getenv(alias, "").strip()

    if primary_val and alias_val:
        _warn_once(
            f"{alias}:conflict",
            f"Both {primary} and {alias} are set. Using {primary}; "
            f"ignoring {alias}. {alias} is deprecated and will be removed.",
        )
        return primary_val, primary
    if primary_val:
        return primary_val, primary
    if alias_val:
        _warn_once(
            f"{alias}:deprecated",
            f"{alias} is deprecated. Use {primary} instead.",
        )
        return alias_val, alias
    return default, primary


def read_http_host() -> str:
    """Return the HTTP bind host.

    Precedence: ``MCP_HOST`` > ``MCP_HTTP_HOST`` (deprecated alias) > default
    ``127.0.0.1`` (loopback). Defaults to loopback rather than all interfaces
    so that env+http (HTTP without auth) cannot accidentally expose the
    server to network-adjacent processes. Operators who want to bind all
    interfaces must set ``MCP_HOST=0.0.0.0`` explicitly.

    Deprecation warning logged once per process if the alias is the active
    source or conflicts with the primary.
    """
    value, _ = _read_with_alias("MCP_HOST", "MCP_HTTP_HOST", "127.0.0.1")
    return value


def read_http_port() -> int:
    """Return the HTTP bind port.

    Precedence: ``MCP_PORT`` > ``MCP_HTTP_PORT`` (deprecated alias) > default
    ``8000``. Validates the value is an integer in [1, 65535]; raises
    ValueError naming the env var that actually supplied the value, so users
    who set the deprecated alias get an error pointing at the right name.
    """
    raw, source = _read_with_alias("MCP_PORT", "MCP_HTTP_PORT", "8000")
    try:
        port = int(raw)
    except ValueError:
        raise ValueError(
            f"{source} must be a valid integer, got {raw!r}"
        ) from None
    if not (1 <= port <= 65535):
        raise ValueError(
            f"{source} must be in [1, 65535], got {port}"
        )
    return port


def validate_mode_combination(auth_mode: str, transport_mode: str) -> None:
    """Enforce orthogonal-with-guardrails policy on (auth, transport) pairs.

    Allowed combinations:
        - env + stdio   -> default, silent
        - env + http    -> allowed with WARNING (HTTP without auth)
        - clerk + http  -> production path, silent
        - clerk + stdio -> ValueError (OAuth needs HTTP callbacks)

    Args:
        auth_mode: Validated AUTH_MODE value ("env" or "clerk").
        transport_mode: Validated TRANSPORT_MODE value ("stdio" or "http").

    Raises:
        ValueError: when the combination is invalid (clerk + stdio).
    """
    if auth_mode == "clerk" and transport_mode == "stdio":
        raise ValueError(
            "AUTH_MODE=clerk requires TRANSPORT_MODE=http "
            "(OAuth callbacks need an HTTP endpoint). "
            "Set TRANSPORT_MODE=http or switch AUTH_MODE=env."
        )
    if auth_mode == "env" and transport_mode == "http":
        logger.warning(
            "TRANSPORT_MODE=http with AUTH_MODE=env exposes the MCP server "
            "without authentication. Use only on trusted networks or for "
            "local development. Do NOT use in production."
        )
