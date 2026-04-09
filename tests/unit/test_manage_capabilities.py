"""Unit tests for ManageCapabilities tool.

Tests the ManageCapabilities class which handles UCM capability management
actions including get_capabilities, verify_capability, and health status.
"""

import pytest
from unittest.mock import AsyncMock, patch

from src.revenium_mcp_server.tools_decomposed.manage_capabilities import (
    ManageCapabilities,
    CapabilityRequest,
)
from mcp.types import TextContent


@pytest.fixture
def capabilities_tool():
    """Create ManageCapabilities instance."""
    return ManageCapabilities()


class TestCapabilityRequest:
    """Test the CapabilityRequest dataclass."""

    def test_all_fields(self):
        """All four fields are independently stored and accessible."""
        req = CapabilityRequest(
            action="verify_capability",
            resource_type="products",
            capability_name="currencies",
            value="USD",
        )
        assert req.action == "verify_capability"
        assert req.resource_type == "products"
        assert req.capability_name == "currencies"
        assert req.value == "USD"


class TestManageCapabilitiesActions:
    """Test handle_action routing to correct handlers."""

    @pytest.mark.asyncio
    async def test_get_examples_returns_markdown(self, capabilities_tool):
        """get_examples action returns formatted markdown with usage guidance."""
        result = await capabilities_tool.handle_action("get_examples", {})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "Examples" in result[0].text
        assert "get_capabilities" in result[0].text

    @pytest.mark.asyncio
    @patch("src.revenium_mcp_server.tools_decomposed.manage_capabilities.ucm_integration_service")
    async def test_get_capabilities_without_resource_type(self, mock_ucm, capabilities_tool):
        """get_capabilities without resource_type shows all available types."""
        mock_ucm.get_available_resource_types = AsyncMock(
            return_value=["products", "subscriptions", "customers"]
        )
        result = await capabilities_tool.handle_action("get_capabilities", {})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        text = result[0].text
        assert "products" in text
        assert "subscriptions" in text
        assert "customers" in text
        assert "Available Resource Types" in text

    @pytest.mark.asyncio
    @patch("src.revenium_mcp_server.tools_decomposed.manage_capabilities.ucm_integration_service")
    async def test_get_capabilities_with_resource_type(self, mock_ucm, capabilities_tool):
        """get_capabilities with resource_type shows specific capabilities."""
        mock_ucm.get_ucm_capabilities = AsyncMock(
            return_value={"currencies": ["USD", "EUR"], "billing_models": ["subscription"]}
        )
        result = await capabilities_tool.handle_action(
            "get_capabilities", {"resource_type": "products"}
        )
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        text = result[0].text
        assert "products" in text
        assert "currencies" in text
        assert "billing_models" in text
        assert "USD" in text
        assert "EUR" in text

    @pytest.mark.asyncio
    @patch("src.revenium_mcp_server.tools_decomposed.manage_capabilities.ucm_integration_service")
    async def test_verify_capability_valid(self, mock_ucm, capabilities_tool):
        """verify_capability with valid value returns Valid status."""
        mock_ucm.validate_capability_value = AsyncMock(return_value=True)
        result = await capabilities_tool.handle_action("verify_capability", {
            "resource_type": "products",
            "capability_name": "currencies",
            "value": "USD",
        })
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        text = result[0].text
        assert "Valid" in text
        assert "products" in text
        assert "currencies" in text
        assert "USD" in text
        assert "Invalid" not in text

    @pytest.mark.asyncio
    @patch("src.revenium_mcp_server.tools_decomposed.manage_capabilities.ucm_integration_service")
    async def test_verify_capability_invalid(self, mock_ucm, capabilities_tool):
        """verify_capability with invalid value returns Invalid status."""
        mock_ucm.validate_capability_value = AsyncMock(return_value=False)
        result = await capabilities_tool.handle_action("verify_capability", {
            "resource_type": "products",
            "capability_name": "currencies",
            "value": "INVALID",
        })
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        text = result[0].text
        assert "Invalid" in text
        assert "products" in text
        assert "currencies" in text
        assert "INVALID" in text

    @pytest.mark.asyncio
    async def test_verify_capability_missing_params(self, capabilities_tool):
        """verify_capability with missing params returns error listing them."""
        result = await capabilities_tool.handle_action("verify_capability", {})
        text = result[0].text
        assert "resource_type" in text
        assert "capability_name" in text
        assert "value" in text

    @pytest.mark.asyncio
    @patch("src.revenium_mcp_server.tools_decomposed.manage_capabilities.ucm_integration_service")
    async def test_refresh_capabilities(self, mock_ucm, capabilities_tool):
        """refresh_capabilities returns refresh status."""
        mock_ucm.refresh_all_capabilities = AsyncMock(
            return_value={"status": "refreshed", "types_updated": 5}
        )
        result = await capabilities_tool.handle_action("refresh_capabilities", {})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        text = result[0].text
        assert "Refreshed" in text
        assert "refreshed" in text
        assert "types_updated" in text
        assert "5" in text

    @pytest.mark.asyncio
    @patch("src.revenium_mcp_server.tools_decomposed.manage_capabilities.ucm_integration_service")
    async def test_get_health_status(self, mock_ucm, capabilities_tool):
        """get_health_status returns UCM health information."""
        mock_ucm.get_health_status = AsyncMock(
            return_value={"status": "healthy", "uptime": "24h"}
        )
        result = await capabilities_tool.handle_action("get_health_status", {})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        text = result[0].text
        assert "Health Status" in text
        assert "healthy" in text
        assert "uptime" in text
        assert "24h" in text

    @pytest.mark.asyncio
    async def test_unsupported_action_returns_error(self, capabilities_tool):
        """Unsupported action returns structured error with valid actions."""
        result = await capabilities_tool.handle_action("totally_bogus", {})
        text = result[0].text
        assert "totally_bogus" in text

    @pytest.mark.asyncio
    @patch("src.revenium_mcp_server.tools_decomposed.manage_capabilities.ucm_integration_service")
    async def test_manage_capabilities_action(self, mock_ucm, capabilities_tool):
        """manage_capabilities action returns all capabilities overview."""
        mock_ucm.get_all_capabilities = AsyncMock(
            return_value={"products": {}, "subscriptions": {}}
        )
        result = await capabilities_tool.handle_action("manage_capabilities", {})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        text = result[0].text
        assert "Capabilities Management" in text
        assert "products" in text
        assert "subscriptions" in text
        assert "2" in text  # len(capabilities_overview) == 2

    @pytest.mark.asyncio
    @patch("src.revenium_mcp_server.tools_decomposed.manage_capabilities.ucm_integration_service")
    async def test_get_resource_type(self, mock_ucm, capabilities_tool):
        """get_resource_type returns list of available resource types."""
        mock_ucm.get_available_resource_types = AsyncMock(
            return_value=["products", "subscriptions"]
        )
        result = await capabilities_tool.handle_action("get_resource_type", {})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        text = result[0].text
        assert "Resource Types" in text
        assert "products" in text
        assert "subscriptions" in text

    @pytest.mark.asyncio
    @patch("src.revenium_mcp_server.tools_decomposed.manage_capabilities.ucm_integration_service")
    async def test_get_capability_specific(self, mock_ucm, capabilities_tool):
        """get_capability with capability_name returns specific value."""
        mock_ucm.get_capability_value = AsyncMock(return_value="USD,EUR,GBP")
        result = await capabilities_tool.handle_action("get_capability", {
            "resource_type": "products",
            "capability_name": "currencies",
        })
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        text = result[0].text
        assert "Capability Value" in text
        assert "products" in text
        assert "currencies" in text
        assert "USD,EUR,GBP" in text

    @pytest.mark.asyncio
    @patch("src.revenium_mcp_server.tools_decomposed.manage_capabilities.ucm_integration_service")
    async def test_get_capability_all_for_type(self, mock_ucm, capabilities_tool):
        """get_capability without capability_name returns all for resource type."""
        mock_ucm.get_ucm_capabilities = AsyncMock(
            return_value={"currencies": ["USD"]}
        )
        result = await capabilities_tool.handle_action("get_capability", {
            "resource_type": "products",
        })
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        text = result[0].text
        assert "All Capabilities" in text
        assert "products" in text
        assert "currencies" in text
        assert "USD" in text

    @pytest.mark.asyncio
    async def test_exception_during_handling_returns_error(self, capabilities_tool):
        """Unexpected exception during handling returns formatted error."""
        with patch.object(
            capabilities_tool, "_create_request", side_effect=RuntimeError("boom")
        ):
            result = await capabilities_tool.handle_action("get_capabilities", {})
            assert len(result) == 1
            assert isinstance(result[0], TextContent)
            text = result[0].text
            assert "boom" in text
            assert len(text) > 0


class TestMissingVerifyParams:
    """Test _get_missing_verify_params helper."""

    def test_all_missing(self, capabilities_tool):
        """All params missing returns all three names."""
        req = CapabilityRequest(action="verify_capability")
        missing = capabilities_tool._get_missing_verify_params(req)
        assert set(missing) == {"resource_type", "capability_name", "value"}

    def test_none_missing(self, capabilities_tool):
        """All params provided returns empty list."""
        req = CapabilityRequest(
            action="verify_capability",
            resource_type="products",
            capability_name="currencies",
            value="USD",
        )
        missing = capabilities_tool._get_missing_verify_params(req)
        assert missing == []
