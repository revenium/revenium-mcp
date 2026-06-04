"""Unit tests for validate_mode_combination in transport_mode.py."""
from __future__ import annotations

import pytest
from src.revenium_mcp_server.transport_mode import validate_mode_combination


def test_api_key_requires_http():
    with pytest.raises(ValueError, match="api_key.*http|http.*api_key"):
        validate_mode_combination("api_key", "stdio")


def test_api_key_http_is_allowed():
    # Should not raise
    validate_mode_combination("api_key", "http")
