"""Tests for the centralized TRANSPORT_MODE parser and HTTP host/port readers."""
from __future__ import annotations

import pytest


# ── read_transport_mode ──────────────────────────────────────────


def test_transport_mode_defaults_to_stdio(monkeypatch):
    from src.revenium_mcp_server.transport_mode import read_transport_mode

    monkeypatch.delenv("TRANSPORT_MODE", raising=False)
    assert read_transport_mode() == "stdio"


def test_transport_mode_accepts_stdio(monkeypatch):
    from src.revenium_mcp_server.transport_mode import read_transport_mode

    monkeypatch.setenv("TRANSPORT_MODE", "stdio")
    assert read_transport_mode() == "stdio"


def test_transport_mode_accepts_http(monkeypatch):
    from src.revenium_mcp_server.transport_mode import read_transport_mode

    monkeypatch.setenv("TRANSPORT_MODE", "http")
    assert read_transport_mode() == "http"


def test_transport_mode_case_insensitive(monkeypatch):
    from src.revenium_mcp_server.transport_mode import read_transport_mode

    monkeypatch.setenv("TRANSPORT_MODE", "HTTP")
    assert read_transport_mode() == "http"


def test_transport_mode_strips_whitespace(monkeypatch):
    from src.revenium_mcp_server.transport_mode import read_transport_mode

    monkeypatch.setenv("TRANSPORT_MODE", "  http  ")
    assert read_transport_mode() == "http"


def test_transport_mode_rejects_unknown(monkeypatch):
    from src.revenium_mcp_server.transport_mode import read_transport_mode

    monkeypatch.setenv("TRANSPORT_MODE", "sse")
    with pytest.raises(ValueError, match="TRANSPORT_MODE must be"):
        read_transport_mode()


def test_transport_mode_rejects_empty_string(monkeypatch):
    from src.revenium_mcp_server.transport_mode import read_transport_mode

    monkeypatch.setenv("TRANSPORT_MODE", "")
    with pytest.raises(ValueError, match="TRANSPORT_MODE must be"):
        read_transport_mode()


# ── read_http_host ────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_alias_warnings():
    """Reset the per-process alias-warning dedup so each test starts clean."""
    from src.revenium_mcp_server import transport_mode

    transport_mode._warned_aliases.clear()
    yield
    transport_mode._warned_aliases.clear()


def test_http_host_defaults_to_loopback(monkeypatch):
    from src.revenium_mcp_server.transport_mode import read_http_host

    monkeypatch.delenv("MCP_HOST", raising=False)
    monkeypatch.delenv("MCP_HTTP_HOST", raising=False)
    assert read_http_host() == "127.0.0.1"


def test_http_host_reads_MCP_HOST(monkeypatch):
    from src.revenium_mcp_server import transport_mode
    from src.revenium_mcp_server.transport_mode import read_http_host

    monkeypatch.setenv("MCP_HOST", "127.0.0.1")
    monkeypatch.delenv("MCP_HTTP_HOST", raising=False)

    warnings: list[str] = []
    monkeypatch.setattr(
        transport_mode.logger, "warning", lambda msg: warnings.append(msg)
    )
    assert read_http_host() == "127.0.0.1"
    assert warnings == []  # no deprecation, no conflict


def test_http_host_falls_back_to_deprecated_alias_with_warning(monkeypatch):
    from src.revenium_mcp_server import transport_mode
    from src.revenium_mcp_server.transport_mode import read_http_host

    monkeypatch.delenv("MCP_HOST", raising=False)
    monkeypatch.setenv("MCP_HTTP_HOST", "10.0.0.1")

    warnings: list[str] = []
    monkeypatch.setattr(
        transport_mode.logger, "warning", lambda msg: warnings.append(msg)
    )
    assert read_http_host() == "10.0.0.1"
    assert any("MCP_HTTP_HOST" in m and "deprecated" in m.lower() for m in warnings)


def test_http_host_prefers_MCP_HOST_when_both_set(monkeypatch):
    from src.revenium_mcp_server import transport_mode
    from src.revenium_mcp_server.transport_mode import read_http_host

    monkeypatch.setenv("MCP_HOST", "127.0.0.1")
    monkeypatch.setenv("MCP_HTTP_HOST", "10.0.0.1")

    warnings: list[str] = []
    monkeypatch.setattr(
        transport_mode.logger, "warning", lambda msg: warnings.append(msg)
    )
    assert read_http_host() == "127.0.0.1"
    assert any("MCP_HOST" in m and "MCP_HTTP_HOST" in m for m in warnings)


def test_http_host_alias_warning_fires_once(monkeypatch):
    """Calling read_http_host repeatedly with alias set warns only once."""
    from src.revenium_mcp_server import transport_mode
    from src.revenium_mcp_server.transport_mode import read_http_host

    monkeypatch.delenv("MCP_HOST", raising=False)
    monkeypatch.setenv("MCP_HTTP_HOST", "10.0.0.1")

    warnings: list[str] = []
    monkeypatch.setattr(
        transport_mode.logger, "warning", lambda msg: warnings.append(msg)
    )
    read_http_host()
    read_http_host()
    read_http_host()
    deprecation_msgs = [m for m in warnings if "MCP_HTTP_HOST" in m]
    assert len(deprecation_msgs) == 1


def test_http_host_treats_whitespace_only_alias_as_unset(monkeypatch):
    """MCP_HTTP_HOST set to whitespace only must fall through to default."""
    from src.revenium_mcp_server.transport_mode import read_http_host

    monkeypatch.delenv("MCP_HOST", raising=False)
    monkeypatch.setenv("MCP_HTTP_HOST", "   ")
    assert read_http_host() == "127.0.0.1"


def test_http_host_emits_both_deprecation_and_conflict_warnings_independently(monkeypatch):
    """After a deprecation warning fires for an alias, a later conflict
    must still emit its own warning (different dedup key)."""
    from src.revenium_mcp_server import transport_mode
    from src.revenium_mcp_server.transport_mode import read_http_host

    warnings: list[str] = []
    monkeypatch.setattr(
        transport_mode.logger, "warning", lambda msg: warnings.append(msg)
    )

    # Phase 1: only alias set → deprecation warning
    monkeypatch.delenv("MCP_HOST", raising=False)
    monkeypatch.setenv("MCP_HTTP_HOST", "10.0.0.1")
    read_http_host()

    # Phase 2: operator adds primary in same process → conflict warning
    monkeypatch.setenv("MCP_HOST", "127.0.0.1")
    read_http_host()

    deprecation = [m for m in warnings if "deprecated" in m.lower() and "Both" not in m]
    conflict = [m for m in warnings if "Both" in m]
    assert len(deprecation) == 1
    assert len(conflict) == 1


# ── read_http_port ────────────────────────────────────────────────


def test_http_port_defaults_to_8000(monkeypatch):
    from src.revenium_mcp_server.transport_mode import read_http_port

    monkeypatch.delenv("MCP_PORT", raising=False)
    monkeypatch.delenv("MCP_HTTP_PORT", raising=False)
    assert read_http_port() == 8000


def test_http_port_reads_MCP_PORT(monkeypatch):
    from src.revenium_mcp_server.transport_mode import read_http_port

    monkeypatch.setenv("MCP_PORT", "9000")
    monkeypatch.delenv("MCP_HTTP_PORT", raising=False)
    assert read_http_port() == 9000


def test_http_port_falls_back_to_deprecated_alias_with_warning(monkeypatch):
    from src.revenium_mcp_server import transport_mode
    from src.revenium_mcp_server.transport_mode import read_http_port

    monkeypatch.delenv("MCP_PORT", raising=False)
    monkeypatch.setenv("MCP_HTTP_PORT", "9001")

    warnings: list[str] = []
    monkeypatch.setattr(
        transport_mode.logger, "warning", lambda msg: warnings.append(msg)
    )
    assert read_http_port() == 9001
    assert any("MCP_HTTP_PORT" in m and "deprecated" in m.lower() for m in warnings)


def test_http_port_prefers_MCP_PORT_when_both_set(monkeypatch):
    from src.revenium_mcp_server import transport_mode
    from src.revenium_mcp_server.transport_mode import read_http_port

    monkeypatch.setenv("MCP_PORT", "9000")
    monkeypatch.setenv("MCP_HTTP_PORT", "9001")

    warnings: list[str] = []
    monkeypatch.setattr(
        transport_mode.logger, "warning", lambda msg: warnings.append(msg)
    )
    assert read_http_port() == 9000
    assert any("MCP_PORT" in m and "MCP_HTTP_PORT" in m for m in warnings)


def test_http_port_rejects_non_integer(monkeypatch):
    from src.revenium_mcp_server.transport_mode import read_http_port

    monkeypatch.setenv("MCP_PORT", "not-a-number")
    monkeypatch.delenv("MCP_HTTP_PORT", raising=False)
    with pytest.raises(ValueError, match="MCP_PORT must be a valid integer"):
        read_http_port()


def test_http_port_rejects_zero(monkeypatch):
    from src.revenium_mcp_server.transport_mode import read_http_port

    monkeypatch.setenv("MCP_PORT", "0")
    monkeypatch.delenv("MCP_HTTP_PORT", raising=False)
    with pytest.raises(ValueError, match=r"MCP_PORT must be in \[1, 65535\]"):
        read_http_port()


def test_http_port_rejects_above_max(monkeypatch):
    from src.revenium_mcp_server.transport_mode import read_http_port

    monkeypatch.setenv("MCP_PORT", "65536")
    monkeypatch.delenv("MCP_HTTP_PORT", raising=False)
    with pytest.raises(ValueError, match=r"MCP_PORT must be in \[1, 65535\]"):
        read_http_port()


def test_http_port_rejects_negative(monkeypatch):
    from src.revenium_mcp_server.transport_mode import read_http_port

    monkeypatch.setenv("MCP_PORT", "-1")
    monkeypatch.delenv("MCP_HTTP_PORT", raising=False)
    with pytest.raises(ValueError, match=r"MCP_PORT must be in \[1, 65535\]"):
        read_http_port()


def test_http_port_error_message_names_alias_when_alias_is_source(monkeypatch):
    """When only MCP_HTTP_PORT is set and value is invalid, the error must
    name MCP_HTTP_PORT — not MCP_PORT — so unmigrated users aren't confused.
    """
    from src.revenium_mcp_server.transport_mode import read_http_port

    monkeypatch.delenv("MCP_PORT", raising=False)
    monkeypatch.setenv("MCP_HTTP_PORT", "not-a-number")
    with pytest.raises(ValueError, match="MCP_HTTP_PORT must be a valid integer"):
        read_http_port()


def test_http_port_range_error_names_alias_when_alias_is_source(monkeypatch):
    """Same as above but for out-of-range values."""
    from src.revenium_mcp_server.transport_mode import read_http_port

    monkeypatch.delenv("MCP_PORT", raising=False)
    monkeypatch.setenv("MCP_HTTP_PORT", "70000")
    with pytest.raises(ValueError, match=r"MCP_HTTP_PORT must be in \[1, 65535\]"):
        read_http_port()


# ── validate_mode_combination ─────────────────────────────────────


def test_validate_env_stdio_is_silent(monkeypatch):
    from src.revenium_mcp_server import transport_mode
    from src.revenium_mcp_server.transport_mode import validate_mode_combination

    warnings: list[str] = []
    monkeypatch.setattr(
        transport_mode.logger, "warning", lambda msg: warnings.append(msg)
    )
    validate_mode_combination("env", "stdio")  # must not raise
    assert warnings == []


def test_validate_clerk_http_is_silent(monkeypatch):
    from src.revenium_mcp_server import transport_mode
    from src.revenium_mcp_server.transport_mode import validate_mode_combination

    warnings: list[str] = []
    monkeypatch.setattr(
        transport_mode.logger, "warning", lambda msg: warnings.append(msg)
    )
    validate_mode_combination("clerk", "http")  # must not raise
    assert warnings == []


def test_validate_env_http_warns_about_no_auth(monkeypatch):
    from src.revenium_mcp_server import transport_mode
    from src.revenium_mcp_server.transport_mode import validate_mode_combination

    warnings: list[str] = []
    monkeypatch.setattr(
        transport_mode.logger, "warning", lambda msg: warnings.append(msg)
    )
    validate_mode_combination("env", "http")
    assert any("without authentication" in m.lower() for m in warnings)


def test_validate_clerk_stdio_raises(monkeypatch):
    from src.revenium_mcp_server.transport_mode import validate_mode_combination

    with pytest.raises(ValueError, match="AUTH_MODE=clerk requires TRANSPORT_MODE=http"):
        validate_mode_combination("clerk", "stdio")
