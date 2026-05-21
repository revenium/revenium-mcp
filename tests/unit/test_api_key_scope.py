"""Tests for APIKeyScope enum (mirror of backend's APIKeyScope)."""
from src.revenium_mcp_server.auth.api_key_scope import APIKeyScope


def test_known_values():
    """Sync guard: fails if anyone adds/removes a value without bumping this test."""
    assert set(APIKeyScope) == {
        APIKeyScope.METERING,
        APIKeyScope.READ,
        APIKeyScope.WRITE,
    }, "backend APIKeyScope changed — update the enum and this test together"


def test_values_are_uppercase():
    """Canonical form must match backend (UPPERCASE)."""
    assert all(s.value == s.value.upper() for s in APIKeyScope)
    assert all(s.value == s.name for s in APIKeyScope)


def test_str_enum_equality_with_raw_string():
    """StrEnum behavior: enum member compares equal to its string value."""
    assert APIKeyScope.READ == "READ"
    assert APIKeyScope.WRITE == "WRITE"
    assert APIKeyScope.METERING == "METERING"
