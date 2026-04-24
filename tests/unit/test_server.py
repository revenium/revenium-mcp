"""Unit tests for MCP server."""

import os
from unittest.mock import patch

from src.revenium_mcp_server import enhanced_server


def _mock_get_config_value(values):
    """Return a fake get_config_value that reads per-test values from `values`.

    Mirrors the real signature `get_config_value(key, default=None)` and falls
    back to `default` for any key not in the dict. Used to make tests that
    assert on env-driven config behavior deterministic regardless of the
    developer's on-disk `.revenium_cache` state — production code reads config
    via `get_config_value`, so patching it bypasses the cache lookup.
    """
    def _fn(key, default=None):
        return values.get(key, default)
    return _fn


class TestMCPServer:
    """Test MCP server functionality."""

    def test_server_imports(self):
        """Test that server module imports successfully."""
        from src.revenium_mcp_server import enhanced_server as server
        assert hasattr(server, 'main')

    def test_main_function_exists(self):
        """Test that main function exists and is callable."""
        assert hasattr(enhanced_server, 'main')
        assert callable(enhanced_server.main)

    def test_environment_variable_loading(self, mock_env_vars):
        """Test that environment variables are properly loaded."""
        # This test verifies our test environment setup
        assert os.getenv("REVENIUM_API_KEY") == "test_api_key_12345"
        assert os.getenv("REVENIUM_BASE_URL") == "https://api.test.revenium.ai"
        assert os.getenv("LOG_LEVEL") == "ERROR"


class TestCheckAppBaseUrlDrift:
    """BACK-1094: startup warning fires when REVENIUM_BASE_URL is configured
    but REVENIUM_APP_BASE_URL is not — analytics calls would silently default
    to the production app host.
    """

    def test_warns_when_base_set_without_app_base(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.dev.revenium.ai")
        monkeypatch.delenv("REVENIUM_APP_BASE_URL", raising=False)
        with patch(
            "src.revenium_mcp_server.enhanced_server.get_config_value",
            side_effect=_mock_get_config_value(
                {
                    "REVENIUM_BASE_URL": "https://api.dev.revenium.ai",
                    "REVENIUM_APP_BASE_URL": None,
                }
            ),
        ):
            msg = enhanced_server._check_app_base_url_drift()
        assert msg is not None
        assert "https://api.dev.revenium.ai" in msg
        assert "REVENIUM_APP_BASE_URL" in msg

    def test_silent_when_app_base_also_set(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_BASE_URL", "https://api.dev.revenium.ai")
        monkeypatch.setenv("REVENIUM_APP_BASE_URL", "https://app.dev.revenium.ai")
        with patch(
            "src.revenium_mcp_server.enhanced_server.get_config_value",
            side_effect=_mock_get_config_value(
                {
                    "REVENIUM_BASE_URL": "https://api.dev.revenium.ai",
                    "REVENIUM_APP_BASE_URL": "https://app.dev.revenium.ai",
                }
            ),
        ):
            assert enhanced_server._check_app_base_url_drift() is None

    def test_silent_when_base_url_unset(self, monkeypatch):
        """No REVENIUM_BASE_URL override → using production defaults for both → no drift risk."""
        monkeypatch.delenv("REVENIUM_BASE_URL", raising=False)
        monkeypatch.delenv("REVENIUM_APP_BASE_URL", raising=False)
        with patch(
            "src.revenium_mcp_server.enhanced_server.get_config_value",
            side_effect=_mock_get_config_value(
                {"REVENIUM_BASE_URL": None, "REVENIUM_APP_BASE_URL": None}
            ),
        ):
            assert enhanced_server._check_app_base_url_drift() is None
