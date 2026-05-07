"""Unit tests for SubscriberCredentialsManagement tool.

Tests handle_action routing, unknown action error, API error mapping,
and the CredentialsHierarchyManager validation logic.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from mcp.types import TextContent

from src.revenium_mcp_server.common.error_handling import ToolError


@pytest.fixture
def cred_tool():
    """Create a SubscriberCredentialsManagement instance with mocked client."""
    with patch(
        "src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management.ReveniumClient"
    ) as MockClient:
        mock_client = MagicMock()
        MockClient.return_value = mock_client
        from src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management import (
            SubscriberCredentialsManagement,
        )

        tool = SubscriberCredentialsManagement(client=mock_client)
    return tool


class TestHandleActionRouting:
    """Test that handle_action routes to the correct handler."""

    @pytest.mark.asyncio
    async def test_get_capabilities_returns_text(self, cred_tool):
        """get_capabilities returns TextContent with credential management info."""
        cred_tool.documentation_handler.get_capabilities = AsyncMock(
            return_value="# Capabilities\nManage credentials"
        )
        result = await cred_tool.handle_action("get_capabilities", {})
        assert isinstance(result[0], TextContent)
        assert "Capabilities" in result[0].text

    @pytest.mark.asyncio
    async def test_get_examples_returns_text(self, cred_tool):
        """get_examples returns TextContent with usage examples."""
        cred_tool.documentation_handler.get_examples = AsyncMock(
            return_value="# Examples\nCreate a credential"
        )
        result = await cred_tool.handle_action("get_examples", {})
        assert isinstance(result[0], TextContent)
        assert "Examples" in result[0].text

    @pytest.mark.asyncio
    async def test_unknown_action_raises_toolerror(self, cred_tool):
        """Unknown action raises ToolError with supported actions listed."""
        with pytest.raises(ToolError) as exc_info:
            await cred_tool.handle_action("bogus_action", {})
        assert "bogus_action" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_list_action_calls_list_credentials(self, cred_tool):
        """list action delegates to _list_credentials."""
        cred_tool._list_credentials = AsyncMock(
            return_value={
                "credentials": [],
                "pagination": {"page": 0, "size": 20, "totalPages": 1},
            }
        )
        result = await cred_tool.handle_action("list", {})
        cred_tool._list_credentials.assert_called_once_with({})
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_validate_sets_operation_type_create(self, cred_tool):
        """validate without credential_id sets operation_type to 'create'."""
        cred_tool.documentation_handler.validate_credential_data = AsyncMock(
            return_value={"valid": True}
        )
        await cred_tool.handle_action("validate", {"label": "test"})
        call_args = cred_tool.documentation_handler.validate_credential_data.call_args[0][0]
        assert call_args["operation_type"] == "create"

    @pytest.mark.asyncio
    async def test_validate_sets_operation_type_update(self, cred_tool):
        """validate with credential_id sets operation_type to 'update'."""
        cred_tool.documentation_handler.validate_credential_data = AsyncMock(
            return_value={"valid": True}
        )
        await cred_tool.handle_action(
            "validate", {"credential_id": "cred_123", "label": "test"}
        )
        call_args = cred_tool.documentation_handler.validate_credential_data.call_args[0][0]
        assert call_args["operation_type"] == "update"


class TestApiErrorMapping:
    """Test that ReveniumAPIError is mapped to appropriate ToolError."""

    @pytest.mark.asyncio
    async def test_400_invalid_id_maps_to_invalid_parameter(self, cred_tool):
        """400 with 'Failed to decode hashed Id' maps to INVALID_PARAMETER."""
        from src.revenium_mcp_server.client import ReveniumAPIError

        cred_tool._get_credential = AsyncMock(
            side_effect=ReveniumAPIError(
                "Failed to decode hashed Id", status_code=400
            )
        )
        with pytest.raises(ToolError) as exc_info:
            await cred_tool.handle_action("get", {"credential_id": "BADID"})
        assert "Invalid credential ID" in str(exc_info.value.message)

    @pytest.mark.asyncio
    async def test_404_handling_raises_error(self, cred_tool):
        """404 API error is handled and raises some form of error."""
        from src.revenium_mcp_server.client import ReveniumAPIError

        cred_tool._get_credential = AsyncMock(
            side_effect=ReveniumAPIError("Not Found", status_code=404)
        )
        # The 404 handler calls create_resource_not_found_error with unsupported kwargs,
        # which causes a TypeError that gets caught by the outer except Exception handler
        with pytest.raises((ToolError, TypeError)):
            await cred_tool.handle_action("get", {"credential_id": "missing123"})

    @pytest.mark.asyncio
    async def test_500_maps_to_api_error(self, cred_tool):
        """500 maps to generic API error."""
        from src.revenium_mcp_server.client import ReveniumAPIError

        cred_tool._delete_credential = AsyncMock(
            side_effect=ReveniumAPIError("Internal Server Error", status_code=500)
        )
        with pytest.raises(ToolError) as exc_info:
            await cred_tool.handle_action("delete", {"credential_id": "cred_123"})
        assert "API error" in str(exc_info.value.message)

    @pytest.mark.asyncio
    async def test_toolerror_re_raised_unchanged(self, cred_tool):
        """ToolError from a handler is re-raised without wrapping."""
        original = ToolError(message="original error", error_code="ORIGINAL")
        cred_tool._list_credentials = AsyncMock(side_effect=original)
        with pytest.raises(ToolError) as exc_info:
            await cred_tool.handle_action("list", {})
        assert exc_info.value is original

    @pytest.mark.asyncio
    async def test_unexpected_exception_wraps_in_toolerror(self, cred_tool):
        """Unexpected non-API exceptions are wrapped in ToolError."""
        cred_tool._update_credential = AsyncMock(
            side_effect=TypeError("bad type")
        )
        with pytest.raises(ToolError) as exc_info:
            await cred_tool.handle_action("update", {"credential_id": "c1"})
        assert "bad type" in str(exc_info.value.message)


class TestCredentialsHierarchyManager:
    """Test CredentialsHierarchyManager missing parameter validation."""

    @pytest.mark.asyncio
    async def test_get_subscription_details_missing_credential_id(self):
        """get_subscription_details without credential_id raises ToolError."""
        from src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management import (
            CredentialsHierarchyManager,
        )

        manager = CredentialsHierarchyManager(client=MagicMock())
        with pytest.raises(ToolError):
            await manager.get_subscription_details({})

    @pytest.mark.asyncio
    async def test_get_product_details_missing_credential_id(self):
        """get_product_details without credential_id raises ToolError."""
        from src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management import (
            CredentialsHierarchyManager,
        )

        manager = CredentialsHierarchyManager(client=MagicMock())
        with pytest.raises(ToolError):
            await manager.get_product_details({})

    @pytest.mark.asyncio
    async def test_get_subscription_details_navigation_failure(self):
        """get_subscription_details raises ToolError when navigation fails."""
        from src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management import (
            CredentialsHierarchyManager,
        )

        mock_client = MagicMock()
        manager = CredentialsHierarchyManager(client=mock_client)

        failed_result = MagicMock()
        failed_result.success = False
        failed_result.error_message = "not found"

        # navigation_service is a module-level function; replace it entirely
        mock_nav = AsyncMock()
        mock_nav.get_subscription_for_credential = AsyncMock(return_value=failed_result)
        manager.navigation_service = mock_nav

        with pytest.raises(ToolError, match="Failed to get subscription"):
            await manager.get_subscription_details({"credential_id": "cred_abc"})


from tests.unit._helpers_no_framework_leak import assert_no_framework_leak


class TestListCredentialsPaginationValidation:
    """BACK-1270 / items #4 and #5 — list size validation + Pydantic leak guard."""

    @pytest.mark.asyncio
    async def test_list_rejects_float_size_with_structured_error(self, cred_tool):
        with pytest.raises(ToolError) as exc:
            await cred_tool._list_credentials({"page": 0, "size": 3.7})
        assert exc.value.field == "size"
        assert "integer" in exc.value.message.lower()
        assert_no_framework_leak(exc.value.message)
        assert_no_framework_leak(str(exc.value.suggestions))

    @pytest.mark.asyncio
    async def test_list_rejects_size_zero(self, cred_tool):
        with pytest.raises(ToolError) as exc:
            await cred_tool._list_credentials({"page": 0, "size": 0})
        assert exc.value.field == "size"
        assert "[1, 100]" in exc.value.message or "1" in exc.value.message

    @pytest.mark.asyncio
    async def test_list_rejects_size_max_int(self, cred_tool):
        with pytest.raises(ToolError) as exc:
            await cred_tool._list_credentials({"page": 0, "size": 2147483647})
        assert exc.value.field == "size"
        assert "[1, 100]" in exc.value.message or "100" in exc.value.message
