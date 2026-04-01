"""Unit tests for DebugAutoDiscovery tool.

Tests handle_action routing, unknown action error handling,
and the _handle_debug diagnostic report generation.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from mcp.types import TextContent

from src.revenium_mcp_server.tools_decomposed.debug_auto_discovery import (
    DebugAutoDiscovery,
)


@pytest.fixture
def debug_tool():
    """Create a DebugAutoDiscovery instance."""
    return DebugAutoDiscovery()


class TestHandleActionRouting:
    """Test that handle_action routes to the correct handler."""

    @pytest.mark.asyncio
    async def test_get_capabilities_returns_capabilities(self, debug_tool):
        """get_capabilities returns text describing diagnostic features."""
        result = await debug_tool.handle_action("get_capabilities", {})
        text = result[0].text
        assert "Debug Auto-Discovery Capabilities" in text
        assert "debug" in text
        assert "API Connectivity" in text

    @pytest.mark.asyncio
    async def test_get_examples_returns_examples(self, debug_tool):
        """get_examples returns text with diagnostic usage examples."""
        result = await debug_tool.handle_action("get_examples", {})
        text = result[0].text
        assert "Examples" in text
        assert "debug" in text

    @pytest.mark.asyncio
    async def test_unknown_action_returns_structured_error(self, debug_tool):
        """Unknown action returns error text listing valid actions."""
        result = await debug_tool.handle_action("bogus_action", {})
        text = result[0].text
        assert "bogus_action" in text or "Unknown" in text
        # Should list valid actions
        assert "debug" in text

    @pytest.mark.asyncio
    async def test_handler_exception_returns_error_text(self, debug_tool):
        """Generic exception in handler returns error text, not a raise."""
        debug_tool._handle_debug = AsyncMock(side_effect=RuntimeError("crash"))
        result = await debug_tool.handle_action("debug", {})
        text = result[0].text
        assert "Error" in text
        assert "crash" in text


class TestHandleDebug:
    """Test _handle_debug diagnostic report generation."""

    @pytest.mark.asyncio
    async def test_no_api_key_shows_skipped(self, debug_tool):
        """When REVENIUM_API_KEY is not set, API test is skipped."""
        env_patch = {
            "REVENIUM_API_KEY": None,
            "REVENIUM_TEAM_ID": None,
            "REVENIUM_TENANT_ID": None,
            "REVENIUM_OWNER_ID": None,
            "REVENIUM_DEFAULT_EMAIL": None,
            "REVENIUM_BASE_URL": None,
        }
        with patch("os.getenv", side_effect=lambda k, default=None: env_patch.get(k, default)):
            result = await debug_tool._handle_debug({})
        text = result[0].text
        assert "NOT SET" in text
        assert "SKIPPED" in text or "Critical" in text.lower()

    @pytest.mark.asyncio
    async def test_api_key_set_with_successful_api_call(self, debug_tool):
        """When API key is set and API returns 200, report shows SUCCESS."""
        env_patch = {
            "REVENIUM_API_KEY": "test-key-123",
            "REVENIUM_TEAM_ID": "team-1",
            "REVENIUM_TENANT_ID": None,
            "REVENIUM_OWNER_ID": None,
            "REVENIUM_DEFAULT_EMAIL": "test@example.com",
            "REVENIUM_BASE_URL": "https://api.test.com",
        }

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("os.getenv", side_effect=lambda k, default=None: env_patch.get(k, default)):
            with patch("httpx.AsyncClient") as MockClient:
                mock_client_instance = AsyncMock()
                mock_client_instance.get = AsyncMock(return_value=mock_response)
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_client_instance
                result = await debug_tool._handle_debug({})

        text = result[0].text
        assert "SUCCESS" in text
        assert "SET (hidden)" in text  # API key should be masked

    @pytest.mark.asyncio
    async def test_api_401_shows_auth_failure(self, debug_tool):
        """When API returns 401, report shows authentication failure."""
        env_patch = {
            "REVENIUM_API_KEY": "bad-key",
            "REVENIUM_TEAM_ID": None,
            "REVENIUM_TENANT_ID": None,
            "REVENIUM_OWNER_ID": None,
            "REVENIUM_DEFAULT_EMAIL": None,
            "REVENIUM_BASE_URL": None,
        }

        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch("os.getenv", side_effect=lambda k, default=None: env_patch.get(k, default)):
            with patch("httpx.AsyncClient") as MockClient:
                mock_client_instance = AsyncMock()
                mock_client_instance.get = AsyncMock(return_value=mock_response)
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_client_instance
                result = await debug_tool._handle_debug({})

        text = result[0].text
        assert "Authentication failed" in text or "FAILED" in text

    @pytest.mark.asyncio
    async def test_api_connection_error_shows_failure(self, debug_tool):
        """When API call raises exception, report shows FAILED."""
        env_patch = {
            "REVENIUM_API_KEY": "some-key",
            "REVENIUM_TEAM_ID": None,
            "REVENIUM_TENANT_ID": None,
            "REVENIUM_OWNER_ID": None,
            "REVENIUM_DEFAULT_EMAIL": None,
            "REVENIUM_BASE_URL": None,
        }

        with patch("os.getenv", side_effect=lambda k, default=None: env_patch.get(k, default)):
            with patch("httpx.AsyncClient") as MockClient:
                mock_client_instance = AsyncMock()
                mock_client_instance.get = AsyncMock(
                    side_effect=ConnectionError("refused")
                )
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_client_instance
                result = await debug_tool._handle_debug({})

        text = result[0].text
        assert "FAILED" in text

    @pytest.mark.asyncio
    async def test_optional_vars_missing_shows_info(self, debug_tool):
        """Missing optional vars show info message when core is working."""
        env_patch = {
            "REVENIUM_API_KEY": "valid-key",
            "REVENIUM_TEAM_ID": "team-1",
            "REVENIUM_TENANT_ID": None,
            "REVENIUM_OWNER_ID": None,
            "REVENIUM_DEFAULT_EMAIL": None,
            "REVENIUM_BASE_URL": None,
        }

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("os.getenv", side_effect=lambda k, default=None: env_patch.get(k, default)):
            with patch("httpx.AsyncClient") as MockClient:
                mock_client_instance = AsyncMock()
                mock_client_instance.get = AsyncMock(return_value=mock_response)
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_client_instance
                result = await debug_tool._handle_debug({})

        text = result[0].text
        assert "Optional" in text or "optional" in text.lower() or "TENANT_ID" in text

    @pytest.mark.asyncio
    async def test_api_400_shows_team_config_needed(self, debug_tool):
        """When API returns 400, report indicates API key valid but config needed."""
        env_patch = {
            "REVENIUM_API_KEY": "valid-key",
            "REVENIUM_TEAM_ID": None,
            "REVENIUM_TENANT_ID": None,
            "REVENIUM_OWNER_ID": None,
            "REVENIUM_DEFAULT_EMAIL": None,
            "REVENIUM_BASE_URL": None,
        }

        mock_response = MagicMock()
        mock_response.status_code = 400

        with patch("os.getenv", side_effect=lambda k, default=None: env_patch.get(k, default)):
            with patch("httpx.AsyncClient") as MockClient:
                mock_client_instance = AsyncMock()
                mock_client_instance.get = AsyncMock(return_value=mock_response)
                mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
                mock_client_instance.__aexit__ = AsyncMock(return_value=None)
                MockClient.return_value = mock_client_instance
                result = await debug_tool._handle_debug({})

        text = result[0].text
        assert "SUCCESS" in text
        assert "team" in text.lower() or "configuration" in text.lower()
