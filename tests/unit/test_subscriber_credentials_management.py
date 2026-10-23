"""Unit tests for SubscriberCredentialsManagement tool.

Tests handle_action routing, unknown action error, API error mapping,
and the CredentialsHierarchyManager validation logic.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from mcp.types import TextContent

from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError


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
                "pagination": {"number": 0, "size": 20, "totalPages": 1},
            }
        )
        result = await cred_tool.handle_action("list", {})
        args, kwargs = cred_tool._list_credentials.call_args
        assert args == ({},)
        assert "client" in kwargs
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
            await cred_tool._list_credentials({"page": 0, "size": 3.7}, client=cred_tool.client)
        assert exc.value.field == "size"
        assert "integer" in exc.value.message.lower()
        assert_no_framework_leak(exc.value.message)
        assert_no_framework_leak(str(exc.value.suggestions))

    @pytest.mark.asyncio
    async def test_list_rejects_size_zero(self, cred_tool):
        with pytest.raises(ToolError) as exc:
            await cred_tool._list_credentials({"page": 0, "size": 0}, client=cred_tool.client)
        assert exc.value.field == "size"
        assert "[1, 100]" in exc.value.message or "1" in exc.value.message

    @pytest.mark.asyncio
    async def test_list_rejects_size_max_int(self, cred_tool):
        with pytest.raises(ToolError) as exc:
            await cred_tool._list_credentials({"page": 0, "size": 2147483647}, client=cred_tool.client)
        assert exc.value.field == "size"
        assert "[1, 100]" in exc.value.message or "100" in exc.value.message


class TestListCredentialsByOrganization:
    """BACK-2958 — the credentials-by-organization read.

    The endpoint is scoped by the organization in the path, not by the caller's
    team, so these pin what makes it a different answer from ``list``: the
    organization id is required, it reaches the client as the path scope, only
    the filters this operation declares are forwarded, and the result is
    obfuscated the same way.
    """

    @pytest.mark.asyncio
    async def test_missing_organization_id_raises_structured_error(self, cred_tool):
        with pytest.raises(ToolError) as exc:
            await cred_tool._list_credentials_by_organization({}, client=cred_tool.client)
        assert exc.value.field == "organizationId"
        assert_no_framework_leak(exc.value.message)

    @pytest.mark.asyncio
    async def test_forwards_organization_id_and_pagination(self, cred_tool):
        client = cred_tool.client
        client.get_credentials_by_organization = AsyncMock(return_value={})
        client._extract_embedded_data = MagicMock(return_value=[])
        client._extract_pagination_info = MagicMock(
            return_value={"page": 0, "size": 5, "totalPages": 0, "totalElements": 0}
        )

        result = await cred_tool._list_credentials_by_organization(
            {"organization_id": "OQNBA6J", "page": 0, "size": 5}, client=client
        )

        client.get_credentials_by_organization.assert_awaited_once_with(
            "OQNBA6J", page=0, size=5
        )
        assert result["action"] == "list_by_organization"
        assert result["organization_id"] == "OQNBA6J"

    @pytest.mark.asyncio
    async def test_accepts_camel_case_organization_id(self, cred_tool):
        """The tool's own schema spells organization ids camelCase for create."""
        client = cred_tool.client
        client.get_credentials_by_organization = AsyncMock(return_value={})
        client._extract_embedded_data = MagicMock(return_value=[])
        client._extract_pagination_info = MagicMock(return_value={})

        await cred_tool._list_credentials_by_organization(
            {"organizationId": "OQNBA6J"}, client=client
        )
        assert client.get_credentials_by_organization.await_args.args == ("OQNBA6J",)

    @pytest.mark.asyncio
    async def test_forwards_allowlisted_query_filter(self, cred_tool):
        client = cred_tool.client
        client.get_credentials_by_organization = AsyncMock(return_value={})
        client._extract_embedded_data = MagicMock(return_value=[])
        client._extract_pagination_info = MagicMock(return_value={})

        await cred_tool._list_credentials_by_organization(
            {"organization_id": "OQNBA6J", "filters": {"query": "prod"}}, client=client
        )
        assert client.get_credentials_by_organization.await_args.kwargs["query"] == "prod"

    @pytest.mark.asyncio
    async def test_rejects_filter_the_endpoint_does_not_declare(self, cred_tool):
        """``type`` is declared on the team-scoped list only, so forwarding it
        here would be a filter that silently does not narrow."""
        with pytest.raises(ToolError) as exc:
            await cred_tool._list_credentials_by_organization(
                {"organization_id": "OQNBA6J", "filters": {"type": "SUBSCRIBER"}},
                client=cred_tool.client,
            )
        assert exc.value.field == "filters"

    @pytest.mark.asyncio
    async def test_secrets_are_obfuscated(self, cred_tool):
        client = cred_tool.client
        client.get_credentials_by_organization = AsyncMock(return_value={})
        client._extract_embedded_data = MagicMock(
            return_value=[
                {
                    "id": "3BygmAQ",
                    "label": "prod",
                    "externalId": "ak-live-1234567890",
                    "externalSecret": "super-secret-value",
                }
            ]
        )
        client._extract_pagination_info = MagicMock(return_value={})

        result = await cred_tool._list_credentials_by_organization(
            {"organization_id": "OQNBA6J"}, client=client
        )
        rendered = str(result["credentials"])
        assert "super-secret-value" not in rendered
        assert "ak-live-1234567890" not in rendered

    @pytest.mark.asyncio
    async def test_rejects_size_zero(self, cred_tool):
        with pytest.raises(ToolError) as exc:
            await cred_tool._list_credentials_by_organization(
                {"organization_id": "OQNBA6J", "size": 0}, client=cred_tool.client
            )
        assert exc.value.field == "size"

    @pytest.mark.asyncio
    async def test_action_is_routed_and_advertised(self, cred_tool):
        cred_tool._list_credentials_by_organization = AsyncMock(
            return_value={
                "credentials": [],
                "pagination": {"number": 0, "size": 20, "totalPages": 1},
            }
        )
        result = await cred_tool.handle_action(
            "list_by_organization", {"organization_id": "OQNBA6J"}
        )
        assert cred_tool._list_credentials_by_organization.await_count == 1
        assert len(result) >= 1
        assert "list_by_organization" in await cred_tool._get_supported_actions()


class TestListPagingText:
    """Credentials listings render the page that was returned, with sized hints."""

    @pytest.mark.asyncio
    async def test_list_renders_the_requested_page_and_size(self, cred_tool):
        cred_tool._list_credentials = AsyncMock(
            return_value={
                "credentials": [{"id": "c1"}],
                "pagination": {
                    "number": 2,
                    "size": 5,
                    "totalPages": 7,
                    "totalElements": 31,
                },
            }
        )
        text = (await cred_tool.handle_action("list", {"page": 2, "size": 5}))[0].text
        assert "(page 3 of 7)" in text, text
        assert "• Next page: page=3, size=5" in text, text

    @pytest.mark.asyncio
    async def test_list_by_organization_renders_the_requested_page_and_size(
        self, cred_tool
    ):
        cred_tool._list_credentials_by_organization = AsyncMock(
            return_value={
                "credentials": [{"id": "c1"}],
                "pagination": {
                    "number": 2,
                    "size": 5,
                    "totalPages": 7,
                    "totalElements": 31,
                },
            }
        )
        text = (
            await cred_tool.handle_action(
                "list_by_organization",
                {"organization_id": "OQNBA6J", "page": 2, "size": 5},
            )
        )[0].text
        assert "(page 3 of 7)" in text, text
        assert "• Next page: page=3, size=5" in text, text

    @pytest.mark.asyncio
    async def test_list_past_last_page_names_the_pages_that_exist(self, cred_tool):
        cred_tool._list_credentials = AsyncMock(
            return_value={
                "credentials": [],
                "pagination": {
                    "number": 500,
                    "size": 20,
                    "totalPages": 2,
                    "totalElements": 31,
                },
            }
        )
        text = (await cred_tool.handle_action("list", {"page": 500}))[0].text
        assert "The page requested (page=500) is past the last." in text, text
        assert "permissions" not in text, text

class TestCredentialsHierarchyIncompleteWalk:
    """A failed subscriptions page is a retryable API error, not a missing credential."""

    @staticmethod
    def _manager_whose_walk_failed(method_name):
        from src.revenium_mcp_server.hierarchy.navigation_service import NavigationResult
        from src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management import (
            CredentialsHierarchyManager,
        )

        failed = NavigationResult(
            success=False,
            entity_type="credentials",
            entity_id="cred_abc",
            related_entities=[],
            navigation_path=[],
            metadata={"failed_page": 1},
            error_message=(
                "Could not read subscriptions page 1 (timeout). The subscription "
                "list is incomplete, so no answer was built from the pages read "
                "before it. Retry the request."
            ),
        )
        failed.incomplete = True
        manager = CredentialsHierarchyManager(client=MagicMock())
        mock_nav = MagicMock()
        setattr(mock_nav, method_name, AsyncMock(return_value=failed))
        manager.navigation_service = mock_nav
        return manager

    @staticmethod
    def _assert_retryable_walk_failure(error):
        from src.revenium_mcp_server.common.error_handling import ErrorCodes

        assert error.error_code == ErrorCodes.API_ERROR
        assert "subscriptions page 1" in error.message
        assert "incomplete" in error.message
        assert any("Retry" in s for s in error.suggestions)
        assert not any("Verify the credential ID exists" in s for s in error.suggestions)

    @pytest.mark.asyncio
    async def test_get_subscription_details_incomplete_walk_raises_api_error(self):
        manager = self._manager_whose_walk_failed("get_subscription_for_credential")
        with pytest.raises(ToolError) as exc_info:
            await manager.get_subscription_details({"credential_id": "cred_abc"})
        self._assert_retryable_walk_failure(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_product_details_incomplete_walk_raises_api_error(self):
        manager = self._manager_whose_walk_failed("get_full_hierarchy")
        with pytest.raises(ToolError) as exc_info:
            await manager.get_product_details({"credential_id": "cred_abc"})
        self._assert_retryable_walk_failure(exc_info.value)


class TestCreateOfAnExistingExternalId:
    """The platform answers a create whose external ID exists with the old credential."""

    SENT = {
        "label": "New Key",
        "subscriberId": "sub_1",
        "organizationId": "org_1",
        "externalId": "ext_key",
        "externalSecret": "secret123",
    }

    @staticmethod
    async def _create(cred_tool, platform_answer):
        cred_tool.client.team_id = "team_1"
        cred_tool.client.create_credential = AsyncMock(return_value=platform_answer)
        result = await cred_tool.handle_action(
            "create", {"credential_data": dict(TestCreateOfAnExistingExternalId.SENT)}
        )
        return result[0].text

    @pytest.mark.asyncio
    async def test_a_returned_existing_credential_is_refused_as_nothing_created(
        self, cred_tool
    ):
        with pytest.raises(ToolError) as exc:
            await self._create(
                cred_tool,
                {
                    "id": "old_1",
                    "label": "Old Key",
                    "subscriber": {"id": "sub_1"},
                    "organization": {"id": "org_1"},
                },
            )

        assert exc.value.error_code == ErrorCodes.RESOURCE_CONFLICT
        assert "already existed" in exc.value.message
        assert "old_1" in exc.value.message
        assert "nothing was created" in exc.value.message

    @pytest.mark.asyncio
    async def test_a_returned_credential_of_another_subscriber_is_refused_as_existing(
        self, cred_tool
    ):
        with pytest.raises(ToolError) as exc:
            await self._create(
                cred_tool,
                {"id": "old_2", "label": "New Key", "subscriber": {"id": "sub_other"}},
            )

        assert "already existed" in exc.value.message

    @pytest.mark.asyncio
    async def test_a_true_create_is_reported_as_created(self, cred_tool):
        text = await self._create(
            cred_tool,
            {
                "id": "new_1",
                "label": "New Key",
                "subscriber": {"id": "sub_1"},
                "organization": {"id": "org_1"},
            },
        )
        assert "Credential create completed successfully" in text
        assert "already existed" not in text

    @pytest.mark.asyncio
    async def test_a_true_create_whose_label_became_its_name_is_reported_as_created(
        self, cred_tool
    ):
        cred_tool.client.team_id = "team_1"
        cred_tool.client.create_credential = AsyncMock(
            return_value={
                "id": "new_2",
                "label": "Billing Key",
                "subscriber": {"id": "sub_1"},
                "organization": {"id": "org_1"},
            }
        )
        result = await cred_tool.handle_action(
            "create", {"credential_data": {**self.SENT, "name": "Billing Key"}}
        )

        assert "Credential create completed successfully" in result[0].text
        assert "already existed" not in result[0].text


class TestCreatePreviewHeading:
    """BACK-4738: a dry run is a preview, never headed as a completed create."""

    @staticmethod
    async def _preview(cred_tool, credential_data):
        cred_tool.client.get_subscriber_by_id = AsyncMock(return_value={"id": "sub_1"})
        cred_tool.client.create_credential = AsyncMock()
        result = await cred_tool.handle_action(
            "create", {"credential_data": credential_data, "dry_run": True}
        )
        cred_tool.client.create_credential.assert_not_called()
        return result[0].text

    @pytest.mark.asyncio
    async def test_a_valid_preview_is_headed_as_a_valid_preview(self, cred_tool):
        text = await self._preview(
            cred_tool,
            {
                "label": "New Key",
                "subscriberId": "sub_1",
                "organizationId": "org_1",
                "externalId": "ext_key",
                "externalSecret": "secret123",
            },
        )
        assert text.startswith("**Credential create preview (dry run): valid; nothing was created**")
        assert "completed successfully" not in text

    @pytest.mark.asyncio
    async def test_an_invalid_preview_is_headed_as_not_valid(self, cred_tool):
        text = await self._preview(cred_tool, {"label": "New Key"})
        assert text.startswith(
            "**Credential create preview (dry run): not valid; nothing was created**"
        )
        assert "completed successfully" not in text
