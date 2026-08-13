"""Unit tests for Customer Management tools.

Tests the CustomerManagement, UserManager, SubscriberManager, OrganizationManager,
TeamManager, CustomerValidator, CustomerAnalytics, and BaseManager classes.
Focuses on CRUD operations, validation logic, error handling, and action routing.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.tools_decomposed.customer_management import (
    MARKETPLACE_CONCURRENCY_NOTE,
    MARKETPLACE_DIVERGENCE_NOTE,
    MARKETPLACE_RECLASSIFICATION_NOTE,
    MARKETPLACE_SETTINGS_EXAMPLE,
    BaseManager,
    CustomerAnalytics,
    CustomerManagement,
    CustomerValidator,
    OrganizationManager,
    SubscriberManager,
    TeamManager,
    UserManager,
)
from src.revenium_mcp_server.client import ReveniumAPIError
from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError
from src.revenium_mcp_server.common.update_configs import UpdateConfigs
from mcp.types import TextContent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client():
    """Create a mock ReveniumClient for managers."""
    client = MagicMock()
    client.team_id = "test_team_id_456"
    client.auth_config = MagicMock()
    client.auth_config.tenant_id = "test_tenant_id"
    client.auth_config.team_id = "test_team_id_456"

    # User methods
    client.get_users = AsyncMock(return_value={})
    client.get_user_by_id = AsyncMock()
    client.get_user_by_email = AsyncMock()
    client.lookup_user_by_email = AsyncMock()
    client.create_user = AsyncMock()
    client.update_user = AsyncMock()
    client.delete_user = AsyncMock()

    # Subscriber methods
    client.get_subscribers = AsyncMock(return_value={})
    client.get_subscriber_by_id = AsyncMock()
    client.get_subscriber_by_email = AsyncMock()
    client.lookup_subscriber_by_email = AsyncMock()
    client.create_subscriber = AsyncMock()
    client.update_subscriber = AsyncMock()
    client.delete_subscriber = AsyncMock()

    # Organization methods
    client.get_organizations = AsyncMock(return_value={})
    client.get_organization_by_id = AsyncMock()
    client.create_organization = AsyncMock()
    client.update_organization = AsyncMock()
    client.delete_organization = AsyncMock()

    # Team methods
    client.get_teams = AsyncMock(return_value={})
    client.get_team_by_id = AsyncMock()
    client.create_team = AsyncMock()
    client.update_team = AsyncMock()
    client.delete_team = AsyncMock()
    client.get_team_marketplace_settings = AsyncMock(
        return_value={"internalMarketplaceNames": []}
    )
    client.update_team_marketplace_settings = AsyncMock(
        return_value={"internalMarketplaceNames": []}
    )

    # Helpers
    client._extract_embedded_data = MagicMock(return_value=[])
    client._extract_pagination_info = MagicMock(
        return_value={"totalPages": 1, "totalElements": 0}
    )

    return client


@pytest.fixture
def user_manager(mock_client):
    return UserManager(mock_client)


@pytest.fixture
def subscriber_manager(mock_client):
    return SubscriberManager(mock_client)


@pytest.fixture
def org_manager(mock_client):
    return OrganizationManager(mock_client)


@pytest.fixture
def team_manager(mock_client):
    return TeamManager(mock_client)


@pytest.fixture
def customer_mgmt():
    return CustomerManagement()


# ===========================================================================
# BaseManager Tests
# ===========================================================================


class TestBaseManager:
    """Test BaseManager shared functionality."""

    def test_populate_call_count_fixes_undefined_resource_type(self, mock_client):
        """Fixes 'undefined' resourceType in callCountElementDefinition."""
        mgr = BaseManager(mock_client)
        resource = {
            "name": "Test User",
            "callCountElementDefinition": {
                "id": "elem_1",
                "resourceType": "undefined",
                "label": "Valid Label",
            },
        }
        mgr._populate_call_count_element_definition(resource)
        assert resource["callCountElementDefinition"]["resourceType"] == "meteringElementDefinition"

    def test_populate_call_count_fixes_missing_resource_type(self, mock_client):
        """Fixes missing resourceType in callCountElementDefinition."""
        mgr = BaseManager(mock_client)
        resource = {
            "name": "Test User",
            "callCountElementDefinition": {
                "id": "elem_1",
                "label": "Valid Label",
            },
        }
        mgr._populate_call_count_element_definition(resource)
        assert resource["callCountElementDefinition"]["resourceType"] == "meteringElementDefinition"

    def test_populate_call_count_fixes_undefined_label(self, mock_client):
        """Fixes 'undefined' label using resource name and element id."""
        mgr = BaseManager(mock_client)
        resource = {
            "name": "Alice",
            "callCountElementDefinition": {
                "id": "elem_42",
                "resourceType": "meteringElementDefinition",
                "label": "undefined",
            },
        }
        mgr._populate_call_count_element_definition(resource)
        label = resource["callCountElementDefinition"]["label"]
        assert "Alice" in label
        assert "elem_42" in label

    def test_populate_call_count_definitions_in_list(self, mock_client):
        """Processes a list of resources, fixing callCountElementDefinition in each."""
        mgr = BaseManager(mock_client)
        resources = [
            {
                "name": "User1",
                "callCountElementDefinition": {
                    "id": "e1",
                    "resourceType": "undefined",
                    "label": "ok",
                },
            },
            {
                "name": "User2",
                "callCountElementDefinition": {
                    "id": "e2",
                    "resourceType": "valid",
                    "label": "undefined",
                },
            },
        ]
        mgr._populate_call_count_definitions_in_list(resources)
        assert resources[0]["callCountElementDefinition"]["resourceType"] == "meteringElementDefinition"
        assert "User2" in resources[1]["callCountElementDefinition"]["label"]

    def test_populate_skips_when_no_call_count_definition(self, mock_client):
        """No-op when resource lacks callCountElementDefinition."""
        mgr = BaseManager(mock_client)
        resource = {"name": "No CallCount"}
        mgr._populate_call_count_element_definition(resource)
        assert "callCountElementDefinition" not in resource


# ===========================================================================
# UserManager Tests
# ===========================================================================


class TestUserManagerList:
    """Test UserManager.list_users behavior."""

    @pytest.mark.asyncio
    async def test_list_users_returns_paginated_result(self, user_manager, mock_client):
        mock_client._extract_embedded_data.return_value = [
            {"id": "u1", "name": "User A"},
            {"id": "u2", "name": "User B"},
        ]
        mock_client._extract_pagination_info.return_value = {
            "totalPages": 2, "totalElements": 15
        }

        result = await user_manager.list_users({"page": 0, "size": 10})

        assert result["action"] == "list"
        assert result["resource_type"] == "users"
        assert len(result["users"]) == 2
        assert result["total_found"] == 2
        mock_client.get_users.assert_called_once_with(page=0, size=10)

    @pytest.mark.asyncio
    async def test_list_users_defaults(self, user_manager, mock_client):
        """Uses default page=0, size=20 when not specified."""
        mock_client._extract_embedded_data.return_value = []
        result = await user_manager.list_users({})
        mock_client.get_users.assert_called_once_with(page=0, size=20)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "bad_args, bad_field",
        [
            ({"page": -1}, "page"),
            ({"size": 0}, "size"),
            ({"size": 101}, "size"),
        ],
    )
    async def test_list_users_rejects_out_of_range_pagination(
        self, user_manager, mock_client, bad_args, bad_field
    ):
        """Out-of-range page/size are rejected with a structured ToolError before
        the client is called (BACK-1146; sister to BACK-1111/1112/1145)."""
        with pytest.raises(ToolError) as exc:
            await user_manager.list_users(bad_args)
        assert exc.value.field == bad_field
        mock_client.get_users.assert_not_called()


class TestUserManagerGet:
    """Test UserManager.get_user behavior."""

    @pytest.mark.asyncio
    async def test_get_user_by_id(self, user_manager, mock_client):
        mock_client.get_user_by_id.return_value = {"id": "u1", "email": "a@b.com"}
        result = await user_manager.get_user({"user_id": "u1"})
        assert result["id"] == "u1"
        mock_client.get_user_by_id.assert_called_once_with("u1")

    @pytest.mark.asyncio
    async def test_get_user_by_email(self, user_manager, mock_client):
        mock_client.get_user_by_email.return_value = {"id": "u2", "email": "test@co.com"}
        result = await user_manager.get_user({"email": "test@co.com"})
        assert result["email"] == "test@co.com"
        mock_client.get_user_by_email.assert_called_once_with("test@co.com")

    @pytest.mark.asyncio
    async def test_get_user_missing_id_and_email_raises(self, user_manager):
        with pytest.raises(ToolError) as exc_info:
            await user_manager.get_user({})
        assert "user_id or email" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_get_user_404_raises_not_found(self, user_manager, mock_client):
        mock_client.get_user_by_id.side_effect = ReveniumAPIError("Not found", status_code=404)
        with pytest.raises(ToolError) as exc_info:
            await user_manager.get_user({"user_id": "bad_id"})
        assert "not found" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_get_user_400_raises_validation_error(self, user_manager, mock_client):
        mock_client.get_user_by_id.side_effect = ReveniumAPIError("Bad request", status_code=400)
        with pytest.raises(ToolError) as exc_info:
            await user_manager.get_user({"user_id": "!!!invalid!!!"})
        assert "invalid" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_get_user_500_reraises(self, user_manager, mock_client):
        """Non-400/404 API errors are re-raised as-is."""
        mock_client.get_user_by_id.side_effect = ReveniumAPIError("Server error", status_code=500)
        with pytest.raises(ReveniumAPIError):
            await user_manager.get_user({"user_id": "u1"})


class TestUserManagerLookup:
    """Test UserManager.lookup_user behavior (lookup-by-email)."""

    @pytest.mark.asyncio
    async def test_lookup_user_success(self, user_manager, mock_client):
        mock_client.lookup_user_by_email.return_value = {"id": "u9", "email": "joao@acme.com"}
        result = await user_manager.lookup_user({"email": "joao@acme.com"})
        assert result["id"] == "u9"
        mock_client.lookup_user_by_email.assert_called_once_with("joao@acme.com")

    @pytest.mark.asyncio
    async def test_lookup_user_missing_email_raises(self, user_manager, mock_client):
        with pytest.raises(ToolError) as exc_info:
            await user_manager.lookup_user({})
        assert "email" in str(exc_info.value).lower()
        mock_client.lookup_user_by_email.assert_not_called()

    @pytest.mark.asyncio
    async def test_lookup_user_malformed_email_no_api_call(self, user_manager, mock_client):
        with pytest.raises(ToolError) as exc_info:
            await user_manager.lookup_user({"email": "not-an-email"})
        assert "email" in str(exc_info.value).lower()
        mock_client.lookup_user_by_email.assert_not_called()

    @pytest.mark.asyncio
    async def test_lookup_user_blank_email_no_api_call(self, user_manager, mock_client):
        with pytest.raises(ToolError):
            await user_manager.lookup_user({"email": "   "})
        mock_client.lookup_user_by_email.assert_not_called()

    @pytest.mark.asyncio
    async def test_lookup_user_empty_local_part_no_api_call(self, user_manager, mock_client):
        with pytest.raises(ToolError):
            await user_manager.lookup_user({"email": "@acme.com"})
        mock_client.lookup_user_by_email.assert_not_called()

    @pytest.mark.asyncio
    async def test_lookup_user_empty_domain_part_no_api_call(self, user_manager, mock_client):
        with pytest.raises(ToolError):
            await user_manager.lookup_user({"email": "joao@"})
        mock_client.lookup_user_by_email.assert_not_called()

    @pytest.mark.asyncio
    async def test_lookup_user_404_raises_not_found_naming_email(self, user_manager, mock_client):
        mock_client.lookup_user_by_email.side_effect = ReveniumAPIError("User not found", status_code=404)
        with pytest.raises(ToolError) as exc_info:
            await user_manager.lookup_user({"email": "ghost@acme.com"})
        message = str(exc_info.value).lower()
        assert "not found" in message
        assert "ghost@acme.com" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_lookup_user_500_reraises(self, user_manager, mock_client):
        mock_client.lookup_user_by_email.side_effect = ReveniumAPIError("Server error", status_code=500)
        with pytest.raises(ReveniumAPIError):
            await user_manager.lookup_user({"email": "joao@acme.com"})


class TestUserManagerCreate:
    """Test UserManager.create_user behavior."""

    @pytest.mark.asyncio
    async def test_create_user_with_user_data(self, user_manager, mock_client):
        mock_client.create_user.return_value = {"id": "u_new", "email": "new@co.com"}
        with patch(
            "src.revenium_mcp_server.tools_decomposed.customer_management.get_config_value",
            return_value="owner_123",
        ):
            result = await user_manager.create_user({
                "user_data": {"email": "new@co.com", "firstName": "New", "lastName": "User", "roles": ["ROLE_API_CONSUMER"]}
            })
        assert result["id"] == "u_new"
        create_call_data = mock_client.create_user.call_args[0][0]
        assert create_call_data["teamIds"] == ["test_team_id_456"]
        assert create_call_data["ownerId"] == "owner_123"

    @pytest.mark.asyncio
    async def test_create_user_auto_generates_from_name(self, user_manager, mock_client):
        """When only name is provided, auto-generates user_data."""
        mock_client.create_user.return_value = {"id": "u_auto"}
        with patch(
            "src.revenium_mcp_server.tools_decomposed.customer_management.get_config_value",
            return_value=None,
        ):
            result = await user_manager.create_user({"name": "John Doe"})
        create_call_data = mock_client.create_user.call_args[0][0]
        assert create_call_data["firstName"] == "John"
        assert create_call_data["lastName"] == "Doe"
        assert "ROLE_API_CONSUMER" in create_call_data["roles"]

    @pytest.mark.asyncio
    async def test_create_user_missing_data_raises(self, user_manager):
        with pytest.raises(ToolError) as exc_info:
            await user_manager.create_user({})
        assert "user_data" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_create_user_skips_owner_id_when_not_available(self, user_manager, mock_client):
        """When REVENIUM_OWNER_ID is not set, ownerId is not added."""
        mock_client.create_user.return_value = {"id": "u_no_owner"}
        with patch(
            "src.revenium_mcp_server.tools_decomposed.customer_management.get_config_value",
            return_value=None,
        ):
            await user_manager.create_user({
                "user_data": {"email": "a@b.com", "firstName": "A", "lastName": "B", "roles": ["ROLE_API_CONSUMER"]}
            })
        create_call_data = mock_client.create_user.call_args[0][0]
        assert "ownerId" not in create_call_data


class TestUserManagerUpdate:

    @pytest.mark.asyncio
    async def test_update_user_missing_id_raises(self, user_manager):
        with pytest.raises(ToolError):
            await user_manager.update_user({"user_data": {"firstName": "X"}})

    @pytest.mark.asyncio
    async def test_update_user_missing_data_raises(self, user_manager):
        with pytest.raises(ToolError):
            await user_manager.update_user({"user_id": "u1"})

    @pytest.mark.asyncio
    async def test_update_user_delegates_to_handler(self, user_manager, mock_client):
        user_manager.update_handler.update_with_merge = AsyncMock(
            return_value={"id": "u1", "firstName": "Updated"}
        )
        user_manager.update_config_factory.get_config = MagicMock(return_value={"resource_type": "customers"})

        result = await user_manager.update_user(
            {"user_id": "u1", "user_data": {"firstName": "Updated"}}
        )
        assert result["firstName"] == "Updated"
        user_manager.update_handler.update_with_merge.assert_called_once()


class TestUserManagerDelete:

    @pytest.mark.asyncio
    async def test_delete_user_missing_id_raises(self, user_manager):
        with pytest.raises(ToolError):
            await user_manager.delete_user({})

    @pytest.mark.asyncio
    async def test_delete_user_succeeds(self, user_manager, mock_client):
        mock_client.delete_user.return_value = {"deleted": True}
        result = await user_manager.delete_user({"user_id": "u_del"})
        mock_client.delete_user.assert_called_once_with("u_del")


# ===========================================================================
# SubscriberManager Tests
# ===========================================================================


class TestSubscriberManagerListPagination:
    """Pagination boundary validation for SubscriberManager.list_subscribers (BACK-1146)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "bad_args, bad_field",
        [
            ({"page": -1}, "page"),
            ({"size": 0}, "size"),
            ({"size": 101}, "size"),
        ],
    )
    async def test_list_subscribers_rejects_out_of_range_pagination(
        self, subscriber_manager, mock_client, bad_args, bad_field
    ):
        with pytest.raises(ToolError) as exc:
            await subscriber_manager.list_subscribers(bad_args)
        assert exc.value.field == bad_field
        mock_client.get_subscribers.assert_not_called()


class TestSubscriberManagerList:

    @pytest.mark.asyncio
    async def test_list_subscribers_returns_result(self, subscriber_manager, mock_client):
        mock_client._extract_embedded_data.return_value = [
            {"id": "s1", "subscriberId": "sub1", "email": "s@co.com"},
        ]
        mock_client._extract_pagination_info.return_value = {"totalPages": 1, "totalElements": 1}

        result = await subscriber_manager.list_subscribers({"page": 0, "size": 10})

        assert result["action"] == "list"
        assert result["resource_type"] == "subscribers"
        assert result["total_found"] == 1


class TestSubscriberManagerGet:

    @pytest.mark.asyncio
    async def test_get_subscriber_by_id(self, subscriber_manager, mock_client):
        mock_client.get_subscriber_by_id.return_value = {"id": "s1", "subscriberId": "sub1"}
        result = await subscriber_manager.get_subscriber({"subscriber_id": "s1"})
        assert result["id"] == "s1"

    @pytest.mark.asyncio
    async def test_get_subscriber_by_email(self, subscriber_manager, mock_client):
        mock_client.get_subscriber_by_email.return_value = {"id": "s2", "subscriberId": "sub2", "email": "s@b.com"}
        result = await subscriber_manager.get_subscriber({"email": "s@b.com"})
        assert result["email"] == "s@b.com"

    @pytest.mark.asyncio
    async def test_get_subscriber_missing_params_raises(self, subscriber_manager):
        with pytest.raises(ToolError):
            await subscriber_manager.get_subscriber({})

    @pytest.mark.asyncio
    async def test_get_subscriber_404_raises(self, subscriber_manager, mock_client):
        mock_client.get_subscriber_by_id.side_effect = ReveniumAPIError("Not found", status_code=404)
        with pytest.raises(ToolError) as exc_info:
            await subscriber_manager.get_subscriber({"subscriber_id": "bad"})
        assert "not found" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_get_subscriber_400_raises(self, subscriber_manager, mock_client):
        mock_client.get_subscriber_by_email.side_effect = ReveniumAPIError("Bad request", status_code=400)
        with pytest.raises(ToolError) as exc_info:
            await subscriber_manager.get_subscriber({"email": "bad"})
        assert "invalid" in str(exc_info.value).lower()


class TestSubscriberManagerLookup:
    """Test SubscriberManager.lookup_subscriber behavior (lookup-by-email)."""

    @pytest.mark.asyncio
    async def test_lookup_subscriber_success(self, subscriber_manager, mock_client):
        mock_client.lookup_subscriber_by_email.return_value = {
            "id": "s9", "subscriberId": "sub9", "email": "joao@acme.com"
        }
        result = await subscriber_manager.lookup_subscriber({"email": "joao@acme.com"})
        assert result["id"] == "s9"
        mock_client.lookup_subscriber_by_email.assert_called_once_with("joao@acme.com")

    @pytest.mark.asyncio
    async def test_lookup_subscriber_enhances_roles(self, subscriber_manager, mock_client):
        """Success result is passed through the subscriber enhancer (roles surfaced)."""
        mock_client.lookup_subscriber_by_email.return_value = {
            "id": "s9", "subscriberId": "sub9", "email": "joao@acme.com"
        }
        result = await subscriber_manager.lookup_subscriber({"email": "joao@acme.com"})
        assert result["roles"] == ["ROLE_API_CONSUMER"]

    @pytest.mark.asyncio
    async def test_lookup_subscriber_missing_email_raises(self, subscriber_manager, mock_client):
        with pytest.raises(ToolError) as exc_info:
            await subscriber_manager.lookup_subscriber({})
        assert "email" in str(exc_info.value).lower()
        mock_client.lookup_subscriber_by_email.assert_not_called()

    @pytest.mark.asyncio
    async def test_lookup_subscriber_malformed_email_no_api_call(self, subscriber_manager, mock_client):
        with pytest.raises(ToolError) as exc_info:
            await subscriber_manager.lookup_subscriber({"email": "not-an-email"})
        assert "email" in str(exc_info.value).lower()
        mock_client.lookup_subscriber_by_email.assert_not_called()

    @pytest.mark.asyncio
    async def test_lookup_subscriber_empty_domain_no_api_call(self, subscriber_manager, mock_client):
        with pytest.raises(ToolError):
            await subscriber_manager.lookup_subscriber({"email": "bob@"})
        mock_client.lookup_subscriber_by_email.assert_not_called()

    @pytest.mark.asyncio
    async def test_lookup_subscriber_404_raises_not_found_naming_email(self, subscriber_manager, mock_client):
        mock_client.lookup_subscriber_by_email.side_effect = ReveniumAPIError(
            "Subscriber not found", status_code=404
        )
        with pytest.raises(ToolError) as exc_info:
            await subscriber_manager.lookup_subscriber({"email": "ghost@acme.com"})
        assert "not found" in str(exc_info.value).lower()
        assert "ghost@acme.com" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_lookup_subscriber_500_reraises(self, subscriber_manager, mock_client):
        mock_client.lookup_subscriber_by_email.side_effect = ReveniumAPIError(
            "Server error", status_code=500
        )
        with pytest.raises(ReveniumAPIError):
            await subscriber_manager.lookup_subscriber({"email": "joao@acme.com"})


class TestSubscriberManagerCreate:

    @pytest.mark.asyncio
    async def test_create_subscriber_missing_data_raises(self, subscriber_manager):
        with pytest.raises(ToolError):
            await subscriber_manager.create_subscriber({})

    @pytest.mark.asyncio
    async def test_create_subscriber_with_data(self, subscriber_manager, mock_client):
        mock_client.create_subscriber.return_value = {"id": "s_new", "subscriberId": "sub_new"}
        mock_client._extract_embedded_data.return_value = [{"id": "org_1"}]
        with patch(
            "src.revenium_mcp_server.tools_decomposed.customer_management.get_config_value",
            return_value="owner_1",
        ):
            result = await subscriber_manager.create_subscriber({
                "subscriber_data": {
                    "email": "sub@co.com",
                    "firstName": "Sub",
                    "lastName": "User",
                    "organizationIds": ["org_1"],
                    "roles": ["ROLE_API_CONSUMER"],
                }
            })
        assert result["id"] == "s_new"

    @pytest.mark.asyncio
    async def test_create_subscriber_auto_resolves_org_ids(self, subscriber_manager, mock_client):
        """When organizationIds not provided, auto-resolves from first org."""
        mock_client.get_organizations.return_value = {}
        mock_client._extract_embedded_data.return_value = [{"id": "auto_org_1"}]
        mock_client.create_subscriber.return_value = {"id": "s_auto", "subscriberId": "sub_auto"}
        with patch(
            "src.revenium_mcp_server.tools_decomposed.customer_management.get_config_value",
            return_value=None,
        ):
            await subscriber_manager.create_subscriber({
                "subscriber_data": {
                    "email": "sub@co.com",
                    "firstName": "Sub",
                    "lastName": "User",
                }
            })
        create_data = mock_client.create_subscriber.call_args[0][0]
        assert create_data["organizationIds"] == ["auto_org_1"]
        assert create_data["roles"] == ["ROLE_API_CONSUMER"]

    @pytest.mark.asyncio
    async def test_create_subscriber_no_orgs_raises(self, subscriber_manager, mock_client):
        """When no organizations exist, raises error about missing organizationIds."""
        mock_client.get_organizations.return_value = {}
        mock_client._extract_embedded_data.return_value = []
        with patch(
            "src.revenium_mcp_server.tools_decomposed.customer_management.get_config_value",
            return_value=None,
        ):
            with pytest.raises(ToolError) as exc_info:
                await subscriber_manager.create_subscriber({
                    "subscriber_data": {"email": "sub@co.com", "firstName": "S", "lastName": "U"}
                })
            assert "organizationids" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_create_subscriber_400_invalid_org_id(self, subscriber_manager, mock_client):
        """400 error with 'Failed to decode hashed Id' gives specific org ID error."""
        mock_client.create_subscriber.side_effect = ReveniumAPIError(
            "Failed to decode hashed Id: [bad_org_id]", status_code=400
        )
        with patch(
            "src.revenium_mcp_server.tools_decomposed.customer_management.get_config_value",
            return_value=None,
        ):
            with pytest.raises(ToolError) as exc_info:
                await subscriber_manager.create_subscriber({
                    "subscriber_data": {
                        "email": "sub@co.com", "firstName": "S", "lastName": "U",
                        "organizationIds": ["bad_org_id"], "roles": ["ROLE_API_CONSUMER"],
                    }
                })
            assert "invalid organization id" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_create_subscriber_400_generic(self, subscriber_manager, mock_client):
        """Generic 400 error gives general validation error."""
        mock_client.create_subscriber.side_effect = ReveniumAPIError(
            "Bad request", status_code=400
        )
        with patch(
            "src.revenium_mcp_server.tools_decomposed.customer_management.get_config_value",
            return_value=None,
        ):
            with pytest.raises(ToolError) as exc_info:
                await subscriber_manager.create_subscriber({
                    "subscriber_data": {
                        "email": "sub@co.com", "firstName": "S", "lastName": "U",
                        "organizationIds": ["org_1"], "roles": ["ROLE_API_CONSUMER"],
                    }
                })
            assert "invalid subscriber data" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_create_subscriber_404_raises(self, subscriber_manager, mock_client):
        mock_client.create_subscriber.side_effect = ReveniumAPIError("Not found", status_code=404)
        with patch(
            "src.revenium_mcp_server.tools_decomposed.customer_management.get_config_value",
            return_value=None,
        ):
            with pytest.raises(ToolError) as exc_info:
                await subscriber_manager.create_subscriber({
                    "subscriber_data": {
                        "email": "s@c.com", "firstName": "S", "lastName": "U",
                        "organizationIds": ["org_1"], "roles": ["ROLE_API_CONSUMER"],
                    }
                })
            assert "not found" in str(exc_info.value).lower()


class TestSubscriberManagerUpdate:

    @pytest.mark.asyncio
    async def test_update_subscriber_missing_id_raises(self, subscriber_manager):
        with pytest.raises(ToolError):
            await subscriber_manager.update_subscriber({"subscriber_data": {"name": "X"}})

    @pytest.mark.asyncio
    async def test_update_subscriber_missing_data_raises(self, subscriber_manager):
        with pytest.raises(ToolError):
            await subscriber_manager.update_subscriber({"subscriber_id": "s1"})

    @pytest.mark.asyncio
    async def test_update_subscriber_delegates_to_handler(self, subscriber_manager, mock_client):
        subscriber_manager.update_handler.update_with_merge = AsyncMock(
            return_value={"id": "s1", "subscriberId": "sub1", "firstName": "Updated"}
        )
        subscriber_manager.update_config_factory.get_config = MagicMock(return_value={})

        result = await subscriber_manager.update_subscriber(
            {"subscriber_id": "s1", "subscriber_data": {"firstName": "Updated"}}
        )
        assert result["firstName"] == "Updated"


class TestSubscriberManagerDelete:

    @pytest.mark.asyncio
    async def test_delete_subscriber_missing_id_raises(self, subscriber_manager):
        with pytest.raises(ToolError):
            await subscriber_manager.delete_subscriber({})

    @pytest.mark.asyncio
    async def test_delete_subscriber_succeeds(self, subscriber_manager, mock_client):
        mock_client.delete_subscriber.return_value = {"deleted": True}
        result = await subscriber_manager.delete_subscriber({"subscriber_id": "s_del"})
        mock_client.delete_subscriber.assert_called_once_with("s_del")


class TestSubscriberEnhanceResponse:

    def test_enhance_adds_roles_for_subscriber(self, subscriber_manager):
        """Adds ROLE_API_CONSUMER when subscriberId present and roles missing."""
        data = {"subscriberId": "sub_1", "email": "s@co.com"}
        result = subscriber_manager._enhance_subscriber_response(data)
        assert result["roles"] == ["ROLE_API_CONSUMER"]

    def test_enhance_preserves_existing_roles(self, subscriber_manager):
        """Does not overwrite existing roles."""
        data = {"subscriberId": "sub_1", "roles": ["ROLE_CUSTOM"]}
        result = subscriber_manager._enhance_subscriber_response(data)
        assert result["roles"] == ["ROLE_CUSTOM"]

    def test_enhance_skips_when_no_subscriber_id(self, subscriber_manager):
        """Does not add roles when subscriberId is not present."""
        data = {"email": "s@co.com"}
        result = subscriber_manager._enhance_subscriber_response(data)
        assert "roles" not in result

    def test_enhance_skips_non_dict(self, subscriber_manager):
        """Returns non-dict data unchanged."""
        result = subscriber_manager._enhance_subscriber_response("not a dict")
        assert result == "not a dict"


# ===========================================================================
# OrganizationManager Tests
# ===========================================================================


class TestOrganizationManagerListPagination:
    """Pagination boundary validation for OrganizationManager.list_organizations (BACK-1146)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "bad_args, bad_field",
        [
            ({"page": -1}, "page"),
            ({"size": 0}, "size"),
            ({"size": 101}, "size"),
        ],
    )
    async def test_list_organizations_rejects_out_of_range_pagination(
        self, org_manager, mock_client, bad_args, bad_field
    ):
        with pytest.raises(ToolError) as exc:
            await org_manager.list_organizations(bad_args)
        assert exc.value.field == bad_field
        mock_client.get_organizations.assert_not_called()


class TestOrganizationManagerList:

    @pytest.mark.asyncio
    async def test_list_organizations(self, org_manager, mock_client):
        mock_client._extract_embedded_data.return_value = [{"id": "o1", "name": "Org A"}]
        mock_client._extract_pagination_info.return_value = {"totalPages": 1, "totalElements": 1}

        result = await org_manager.list_organizations({})

        assert result["action"] == "list"
        assert result["resource_type"] == "organizations"
        assert result["total_found"] == 1


class TestOrganizationManagerGet:

    @pytest.mark.asyncio
    async def test_get_org_missing_id_raises(self, org_manager):
        with pytest.raises(ToolError):
            await org_manager.get_organization({})

    @pytest.mark.asyncio
    async def test_get_org_returns_data(self, org_manager, mock_client):
        mock_client.get_organization_by_id.return_value = {"id": "o1", "name": "Org A"}
        result = await org_manager.get_organization({"organization_id": "o1"})
        assert result["id"] == "o1"

    @pytest.mark.asyncio
    async def test_get_org_404_raises(self, org_manager, mock_client):
        mock_client.get_organization_by_id.side_effect = ReveniumAPIError("Not found", status_code=404)
        with pytest.raises(ToolError) as exc_info:
            await org_manager.get_organization({"organization_id": "bad"})
        assert "not found" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_get_org_400_raises(self, org_manager, mock_client):
        mock_client.get_organization_by_id.side_effect = ReveniumAPIError("Bad", status_code=400)
        with pytest.raises(ToolError) as exc_info:
            await org_manager.get_organization({"organization_id": "!!!"})
        assert "invalid" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_get_org_500_reraises(self, org_manager, mock_client):
        mock_client.get_organization_by_id.side_effect = ReveniumAPIError("Error", status_code=500)
        with pytest.raises(ReveniumAPIError):
            await org_manager.get_organization({"organization_id": "o1"})


class TestOrganizationManagerCreate:

    @pytest.mark.asyncio
    async def test_create_org_missing_data_raises(self, org_manager):
        with pytest.raises(ToolError):
            await org_manager.create_organization({})

    @pytest.mark.asyncio
    async def test_create_org_auto_populates_fields(self, org_manager, mock_client):
        """Auto-populates tenantId, parentId, metadata."""
        mock_client.create_organization.return_value = {"id": "o_new", "name": "New Org"}
        result = await org_manager.create_organization({
            "organization_data": {"name": "New Org"}
        })
        create_data = mock_client.create_organization.call_args[0][0]
        assert create_data["tenantId"] == "test_tenant_id"
        assert create_data["parentId"] == "test_team_id_456"
        assert create_data["metadata"] == ""


class TestOrganizationManagerUpdate:

    @pytest.mark.asyncio
    async def test_update_org_missing_id_raises(self, org_manager):
        with pytest.raises(ToolError):
            await org_manager.update_organization({"organization_data": {"name": "X"}})

    @pytest.mark.asyncio
    async def test_update_org_missing_data_raises(self, org_manager):
        with pytest.raises(ToolError):
            await org_manager.update_organization({"organization_id": "o1"})

    @pytest.mark.asyncio
    async def test_update_org_delegates_to_handler(self, org_manager, mock_client):
        org_manager.update_handler.update_with_merge = AsyncMock(
            return_value={"id": "o1", "name": "Updated"}
        )
        org_manager.update_config_factory.get_config = MagicMock(return_value={})
        result = await org_manager.update_organization(
            {"organization_id": "o1", "organization_data": {"name": "Updated"}}
        )
        assert result["name"] == "Updated"


class TestOrganizationManagerDelete:

    @pytest.mark.asyncio
    async def test_delete_org_missing_id_raises(self, org_manager):
        with pytest.raises(ToolError):
            await org_manager.delete_organization({})

    @pytest.mark.asyncio
    async def test_delete_org_succeeds(self, org_manager, mock_client):
        mock_client.delete_organization.return_value = {"deleted": True}
        await org_manager.delete_organization({"organization_id": "o_del"})
        mock_client.delete_organization.assert_called_once_with("o_del")


# ===========================================================================
# TeamManager Tests
# ===========================================================================


class TestTeamManagerListPagination:
    """Pagination boundary validation for TeamManager.list_teams (BACK-1146)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "bad_args, bad_field",
        [
            ({"page": -1}, "page"),
            ({"size": 0}, "size"),
            ({"size": 101}, "size"),
        ],
    )
    async def test_list_teams_rejects_out_of_range_pagination(
        self, team_manager, mock_client, bad_args, bad_field
    ):
        with pytest.raises(ToolError) as exc:
            await team_manager.list_teams(bad_args)
        assert exc.value.field == bad_field
        mock_client.get_teams.assert_not_called()


class TestTeamManagerList:

    @pytest.mark.asyncio
    async def test_list_teams(self, team_manager, mock_client):
        mock_client._extract_embedded_data.return_value = [{"id": "t1", "name": "Team A"}]
        mock_client._extract_pagination_info.return_value = {"totalPages": 1, "totalElements": 1}
        result = await team_manager.list_teams({})
        assert result["action"] == "list"
        assert result["resource_type"] == "teams"


class TestTeamManagerGet:

    @pytest.mark.asyncio
    async def test_get_team_missing_id_raises(self, team_manager):
        with pytest.raises(ToolError):
            await team_manager.get_team({})

    @pytest.mark.asyncio
    async def test_get_team_returns_data(self, team_manager, mock_client):
        mock_client.get_team_by_id.return_value = {"id": "t1", "name": "Team A"}
        result = await team_manager.get_team({"team_id": "t1"})
        assert result["id"] == "t1"

    @pytest.mark.asyncio
    async def test_get_team_404_raises(self, team_manager, mock_client):
        mock_client.get_team_by_id.side_effect = ReveniumAPIError("Not found", status_code=404)
        with pytest.raises(ToolError):
            await team_manager.get_team({"team_id": "bad"})

    @pytest.mark.asyncio
    async def test_get_team_400_raises(self, team_manager, mock_client):
        mock_client.get_team_by_id.side_effect = ReveniumAPIError("Bad", status_code=400)
        with pytest.raises(ToolError):
            await team_manager.get_team({"team_id": "!!!"})

    @pytest.mark.asyncio
    async def test_get_team_500_reraises(self, team_manager, mock_client):
        mock_client.get_team_by_id.side_effect = ReveniumAPIError("Error", status_code=500)
        with pytest.raises(ReveniumAPIError):
            await team_manager.get_team({"team_id": "t1"})


class TestTeamManagerCreate:

    @pytest.mark.asyncio
    async def test_create_team_missing_data_raises(self, team_manager):
        with pytest.raises(ToolError):
            await team_manager.create_team({})

    @pytest.mark.asyncio
    async def test_create_team_with_data(self, team_manager, mock_client):
        mock_client.create_team.return_value = {"id": "t_new", "name": "Dev Team"}
        with patch(
            "src.revenium_mcp_server.tools_decomposed.customer_management.get_config_value",
            return_value="owner_1",
        ):
            result = await team_manager.create_team({
                "team_data": {"name": "Dev Team", "organization_id": "org_1"}
            })
        create_data = mock_client.create_team.call_args[0][0]
        assert create_data["teamId"] == "test_team_id_456"
        assert create_data["ownerId"] == "owner_1"


class TestTeamManagerUpdate:

    @pytest.mark.asyncio
    async def test_update_team_missing_id_raises(self, team_manager):
        with pytest.raises(ToolError):
            await team_manager.update_team({"team_data": {"name": "X"}})

    @pytest.mark.asyncio
    async def test_update_team_missing_data_raises(self, team_manager):
        with pytest.raises(ToolError):
            await team_manager.update_team({"team_id": "t1"})


class TestTeamManagerDelete:

    @pytest.mark.asyncio
    async def test_delete_team_missing_id_raises(self, team_manager):
        with pytest.raises(ToolError):
            await team_manager.delete_team({})

    @pytest.mark.asyncio
    async def test_delete_team_succeeds(self, team_manager, mock_client):
        mock_client.delete_team.return_value = {"deleted": True}
        await team_manager.delete_team({"team_id": "t_del"})
        mock_client.delete_team.assert_called_once_with("t_del")


class TestTeamMarketplaceSettingsRead:
    """TeamManager.get_marketplace_settings."""

    @pytest.mark.asyncio
    async def test_missing_team_id_raises_without_api_call(self, team_manager, mock_client):
        with pytest.raises(ToolError) as exc:
            await team_manager.get_marketplace_settings({})
        assert exc.value.field == "team_id"
        mock_client.get_team_marketplace_settings.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_current_names(self, team_manager, mock_client):
        mock_client.get_team_marketplace_settings.return_value = {
            "internalMarketplaceNames": ["acme-internal", "revenium-tools"]
        }
        result = await team_manager.get_marketplace_settings({"team_id": "jR2kmLs"})
        assert result["team_id"] == "jR2kmLs"
        assert result["internalMarketplaceNames"] == ["acme-internal", "revenium-tools"]
        assert result["total_found"] == 2
        mock_client.get_team_marketplace_settings.assert_called_once_with("jR2kmLs")

    @pytest.mark.asyncio
    async def test_missing_field_normalizes_to_empty_list(self, team_manager, mock_client):
        """The read schema marks the array required, but an unconfigured team can omit it."""
        mock_client.get_team_marketplace_settings.return_value = {}
        result = await team_manager.get_marketplace_settings({"team_id": "jR2kmLs"})
        assert result["internalMarketplaceNames"] == []
        assert result["total_found"] == 0

    @pytest.mark.asyncio
    async def test_403_maps_to_authorization_error(self, team_manager, mock_client):
        mock_client.get_team_marketplace_settings.side_effect = ReveniumAPIError(
            "Forbidden", status_code=403
        )
        with pytest.raises(ToolError) as exc:
            await team_manager.get_marketplace_settings({"team_id": "jR2kmLs"})
        assert exc.value.error_code == ErrorCodes.API_AUTHORIZATION

    @pytest.mark.asyncio
    async def test_404_maps_to_not_found(self, team_manager, mock_client):
        mock_client.get_team_marketplace_settings.side_effect = ReveniumAPIError(
            "Not found", status_code=404
        )
        with pytest.raises(ToolError) as exc:
            await team_manager.get_marketplace_settings({"team_id": "bad"})
        assert exc.value.error_code == ErrorCodes.RESOURCE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_409_maps_to_conflict_error(self, team_manager, mock_client):
        """The only concurrency signal the endpoint documents must stay actionable."""
        mock_client.get_team_marketplace_settings.side_effect = ReveniumAPIError(
            "Conflict", status_code=409
        )
        with pytest.raises(ToolError) as exc:
            await team_manager.get_marketplace_settings({"team_id": "jR2kmLs"})
        assert exc.value.error_code == ErrorCodes.RESOURCE_CONFLICT
        assert "changed concurrently" in exc.value.message
        assert "get_marketplace_settings(team_id='jR2kmLs')" in exc.value.suggestions[0]

    @pytest.mark.asyncio
    async def test_500_reraises(self, team_manager, mock_client):
        mock_client.get_team_marketplace_settings.side_effect = ReveniumAPIError(
            "Boom", status_code=500
        )
        with pytest.raises(ReveniumAPIError):
            await team_manager.get_marketplace_settings({"team_id": "jR2kmLs"})

    @pytest.mark.asyncio
    async def test_empty_echo_and_omitted_field_read_the_same(self, team_manager, mock_client):
        """On a read there is no difference: neither shape names an internal marketplace."""
        mock_client.get_team_marketplace_settings.return_value = {
            "internalMarketplaceNames": []
        }
        from_empty = await team_manager.get_marketplace_settings({"team_id": "jR2kmLs"})

        mock_client.get_team_marketplace_settings.return_value = {}
        from_omitted = await team_manager.get_marketplace_settings({"team_id": "jR2kmLs"})

        assert from_empty["internalMarketplaceNames"] == []
        assert from_omitted["internalMarketplaceNames"] == []


class TestTeamMarketplaceSettingsUpdate:
    """TeamManager.update_marketplace_settings — the read-then-merge write path."""

    @pytest.mark.asyncio
    async def test_missing_team_id_raises_without_api_call(self, team_manager, mock_client):
        with pytest.raises(ToolError) as exc:
            await team_manager.update_marketplace_settings(
                {"marketplace_names": ["acme-internal"]}
            )
        assert exc.value.field == "team_id"
        mock_client.get_team_marketplace_settings.assert_not_called()
        mock_client.update_team_marketplace_settings.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_names_raises_without_api_call(self, team_manager, mock_client):
        with pytest.raises(ToolError) as exc:
            await team_manager.update_marketplace_settings({"team_id": "jR2kmLs"})
        assert exc.value.field == "marketplace_names"
        mock_client.get_team_marketplace_settings.assert_not_called()
        mock_client.update_team_marketplace_settings.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_names", ["acme-internal", {"name": "acme"}, 7])
    async def test_non_list_names_rejected(self, team_manager, mock_client, bad_names):
        with pytest.raises(ToolError) as exc:
            await team_manager.update_marketplace_settings(
                {"team_id": "jR2kmLs", "marketplace_names": bad_names}
            )
        assert exc.value.field == "marketplace_names"
        mock_client.update_team_marketplace_settings.assert_not_called()

    @pytest.mark.asyncio
    async def test_blank_entry_rejected(self, team_manager, mock_client):
        with pytest.raises(ToolError) as exc:
            await team_manager.update_marketplace_settings(
                {"team_id": "jR2kmLs", "marketplace_names": ["acme-internal", "  "]}
            )
        assert exc.value.field == "marketplace_names"
        mock_client.update_team_marketplace_settings.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_list_rejected_for_add(self, team_manager, mock_client):
        with pytest.raises(ToolError) as exc:
            await team_manager.update_marketplace_settings(
                {"team_id": "jR2kmLs", "marketplace_names": []}
            )
        assert exc.value.field == "marketplace_names"
        mock_client.update_team_marketplace_settings.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_operation_rejected(self, team_manager, mock_client):
        with pytest.raises(ToolError) as exc:
            await team_manager.update_marketplace_settings({
                "team_id": "jR2kmLs",
                "marketplace_names": ["acme-internal"],
                "operation": "merge",
            })
        assert exc.value.field == "operation"
        mock_client.update_team_marketplace_settings.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_merges_with_current_list(self, team_manager, mock_client):
        """A bare PUT would drop the existing names, so add must send the union."""
        mock_client.get_team_marketplace_settings.return_value = {
            "internalMarketplaceNames": ["revenium-tools"]
        }
        mock_client.update_team_marketplace_settings.return_value = {
            "internalMarketplaceNames": ["revenium-tools", "acme-internal"]
        }

        result = await team_manager.update_marketplace_settings({
            "team_id": "jR2kmLs",
            "marketplace_names": ["acme-internal"],
        })

        mock_client.get_team_marketplace_settings.assert_called_once_with("jR2kmLs")
        sent_team_id, sent_payload = mock_client.update_team_marketplace_settings.call_args[0]
        assert sent_team_id == "jR2kmLs"
        assert sent_payload == {
            "internalMarketplaceNames": ["revenium-tools", "acme-internal"]
        }
        assert result["operation"] == "add"
        assert result["previous_internalMarketplaceNames"] == ["revenium-tools"]
        assert result["added"] == ["acme-internal"]
        assert result["removed"] == []

    @pytest.mark.asyncio
    async def test_add_is_idempotent(self, team_manager, mock_client):
        mock_client.get_team_marketplace_settings.return_value = {
            "internalMarketplaceNames": ["acme-internal"]
        }
        mock_client.update_team_marketplace_settings.return_value = {
            "internalMarketplaceNames": ["acme-internal"]
        }

        result = await team_manager.update_marketplace_settings({
            "team_id": "jR2kmLs",
            "marketplace_names": ["acme-internal"],
        })

        sent_payload = mock_client.update_team_marketplace_settings.call_args[0][1]
        assert sent_payload == {"internalMarketplaceNames": ["acme-internal"]}
        assert result["added"] == []
        assert result["removed"] == []

    @pytest.mark.asyncio
    async def test_remove_subtracts_from_current_list(self, team_manager, mock_client):
        mock_client.get_team_marketplace_settings.return_value = {
            "internalMarketplaceNames": ["acme-internal", "revenium-tools"]
        }
        mock_client.update_team_marketplace_settings.return_value = {
            "internalMarketplaceNames": ["revenium-tools"]
        }

        result = await team_manager.update_marketplace_settings({
            "team_id": "jR2kmLs",
            "marketplace_names": ["acme-internal"],
            "operation": "remove",
        })

        sent_payload = mock_client.update_team_marketplace_settings.call_args[0][1]
        assert sent_payload == {"internalMarketplaceNames": ["revenium-tools"]}
        assert result["removed"] == ["acme-internal"]
        assert result["added"] == []

    @pytest.mark.asyncio
    async def test_replace_overwrites_and_reports_losses(self, team_manager, mock_client):
        mock_client.get_team_marketplace_settings.return_value = {
            "internalMarketplaceNames": ["acme-internal", "revenium-tools"]
        }
        mock_client.update_team_marketplace_settings.return_value = {
            "internalMarketplaceNames": ["only-this"]
        }

        result = await team_manager.update_marketplace_settings({
            "team_id": "jR2kmLs",
            "marketplace_names": ["only-this"],
            "operation": "replace",
        })

        sent_payload = mock_client.update_team_marketplace_settings.call_args[0][1]
        assert sent_payload == {"internalMarketplaceNames": ["only-this"]}
        assert result["added"] == ["only-this"]
        assert set(result["removed"]) == {"acme-internal", "revenium-tools"}

    @pytest.mark.asyncio
    async def test_replace_allows_clearing_the_list(self, team_manager, mock_client):
        mock_client.get_team_marketplace_settings.return_value = {
            "internalMarketplaceNames": ["acme-internal"]
        }
        mock_client.update_team_marketplace_settings.return_value = {
            "internalMarketplaceNames": []
        }

        result = await team_manager.update_marketplace_settings({
            "team_id": "jR2kmLs",
            "marketplace_names": [],
            "operation": "replace",
        })

        sent_payload = mock_client.update_team_marketplace_settings.call_args[0][1]
        assert sent_payload == {"internalMarketplaceNames": []}
        assert result["internalMarketplaceNames"] == []
        assert result["removed"] == ["acme-internal"]

    @pytest.mark.asyncio
    async def test_duplicate_names_deduped_before_put(self, team_manager, mock_client):
        mock_client.get_team_marketplace_settings.return_value = {
            "internalMarketplaceNames": []
        }
        mock_client.update_team_marketplace_settings.return_value = {
            "internalMarketplaceNames": ["acme-internal"]
        }

        await team_manager.update_marketplace_settings({
            "team_id": "jR2kmLs",
            "marketplace_names": ["acme-internal", "acme-internal"],
            "operation": "replace",
        })

        sent_payload = mock_client.update_team_marketplace_settings.call_args[0][1]
        assert sent_payload == {"internalMarketplaceNames": ["acme-internal"]}

    @pytest.mark.asyncio
    async def test_response_surfaces_reclassification_warning(self, team_manager, mock_client):
        mock_client.get_team_marketplace_settings.return_value = {
            "internalMarketplaceNames": []
        }
        mock_client.update_team_marketplace_settings.return_value = {
            "internalMarketplaceNames": ["acme-internal"]
        }

        result = await team_manager.update_marketplace_settings({
            "team_id": "jR2kmLs",
            "marketplace_names": ["acme-internal"],
        })

        assert result["reclassification_warning"] == MARKETPLACE_RECLASSIFICATION_NOTE
        assert "THIRD_PARTY" in result["reclassification_warning"]

    @pytest.mark.asyncio
    async def test_put_403_maps_to_authorization_error(self, team_manager, mock_client):
        mock_client.get_team_marketplace_settings.return_value = {
            "internalMarketplaceNames": []
        }
        mock_client.update_team_marketplace_settings.side_effect = ReveniumAPIError(
            "Forbidden", status_code=403
        )

        with pytest.raises(ToolError) as exc:
            await team_manager.update_marketplace_settings({
                "team_id": "jR2kmLs",
                "marketplace_names": ["acme-internal"],
            })

        assert exc.value.error_code == ErrorCodes.API_AUTHORIZATION
        assert exc.value.field == "team_id"

    @pytest.mark.asyncio
    async def test_put_500_reraises(self, team_manager, mock_client):
        mock_client.get_team_marketplace_settings.return_value = {
            "internalMarketplaceNames": []
        }
        mock_client.update_team_marketplace_settings.side_effect = ReveniumAPIError(
            "Boom", status_code=500
        )

        with pytest.raises(ReveniumAPIError):
            await team_manager.update_marketplace_settings({
                "team_id": "jR2kmLs",
                "marketplace_names": ["acme-internal"],
            })

    @pytest.mark.asyncio
    async def test_put_409_maps_to_conflict_error(self, team_manager, mock_client):
        mock_client.get_team_marketplace_settings.return_value = {
            "internalMarketplaceNames": []
        }
        mock_client.update_team_marketplace_settings.side_effect = ReveniumAPIError(
            "Conflict", status_code=409
        )

        with pytest.raises(ToolError) as exc:
            await team_manager.update_marketplace_settings({
                "team_id": "jR2kmLs",
                "marketplace_names": ["acme-internal"],
            })

        assert exc.value.error_code == ErrorCodes.RESOURCE_CONFLICT
        assert "re-read" in exc.value.message

    @pytest.mark.asyncio
    async def test_falls_back_to_sent_list_when_response_omits_it(
        self, team_manager, mock_client
    ):
        mock_client.get_team_marketplace_settings.return_value = {
            "internalMarketplaceNames": []
        }
        mock_client.update_team_marketplace_settings.return_value = {}

        result = await team_manager.update_marketplace_settings({
            "team_id": "jR2kmLs",
            "marketplace_names": ["acme-internal"],
        })

        assert result["internalMarketplaceNames"] == ["acme-internal"]
        # An absent field says nothing about the stored state, so it is not a divergence.
        assert "divergence_warning" not in result

    @pytest.mark.asyncio
    async def test_empty_echo_is_reported_instead_of_the_sent_list(
        self, team_manager, mock_client
    ):
        """An echoed empty list is a real end state, not a missing field to paper over."""
        mock_client.get_team_marketplace_settings.return_value = {
            "internalMarketplaceNames": ["revenium-tools"]
        }
        mock_client.update_team_marketplace_settings.return_value = {
            "internalMarketplaceNames": []
        }

        result = await team_manager.update_marketplace_settings({
            "team_id": "jR2kmLs",
            "marketplace_names": ["acme-internal"],
        })

        assert result["requested_internalMarketplaceNames"] == [
            "revenium-tools",
            "acme-internal",
        ]
        assert result["internalMarketplaceNames"] == []
        assert result["divergence_warning"] == MARKETPLACE_DIVERGENCE_NOTE
        assert result["unexpectedly_absent"] == ["revenium-tools", "acme-internal"]
        assert result["unexpectedly_present"] == []

    @pytest.mark.asyncio
    async def test_divergent_echo_surfaces_the_interleaved_names(
        self, team_manager, mock_client
    ):
        mock_client.get_team_marketplace_settings.return_value = {
            "internalMarketplaceNames": []
        }
        mock_client.update_team_marketplace_settings.return_value = {
            "internalMarketplaceNames": ["acme-internal", "added-elsewhere"]
        }

        result = await team_manager.update_marketplace_settings({
            "team_id": "jR2kmLs",
            "marketplace_names": ["acme-internal"],
        })

        assert result["internalMarketplaceNames"] == ["acme-internal", "added-elsewhere"]
        assert result["divergence_warning"] == MARKETPLACE_DIVERGENCE_NOTE
        assert result["unexpectedly_present"] == ["added-elsewhere"]
        assert result["unexpectedly_absent"] == []

    @pytest.mark.asyncio
    async def test_reordered_echo_is_not_a_divergence(self, team_manager, mock_client):
        """The upstream array is a set, so ordering alone is not evidence of a lost update."""
        mock_client.get_team_marketplace_settings.return_value = {
            "internalMarketplaceNames": ["acme-internal", "revenium-tools"]
        }
        mock_client.update_team_marketplace_settings.return_value = {
            "internalMarketplaceNames": ["revenium-tools", "acme-internal"]
        }

        result = await team_manager.update_marketplace_settings({
            "team_id": "jR2kmLs",
            "marketplace_names": ["acme-internal", "revenium-tools"],
            "operation": "replace",
        })

        assert "divergence_warning" not in result

    @pytest.mark.asyncio
    async def test_matching_echo_still_carries_the_concurrency_note(
        self, team_manager, mock_client
    ):
        """The endpoint has no version or ETag, so the caveat rides on every response."""
        mock_client.get_team_marketplace_settings.return_value = {
            "internalMarketplaceNames": []
        }
        mock_client.update_team_marketplace_settings.return_value = {
            "internalMarketplaceNames": ["acme-internal"]
        }

        result = await team_manager.update_marketplace_settings({
            "team_id": "jR2kmLs",
            "marketplace_names": ["acme-internal"],
        })

        assert result["concurrency_note"] == MARKETPLACE_CONCURRENCY_NOTE
        assert "divergence_warning" not in result


# ===========================================================================
# CustomerValidator Tests
# ===========================================================================


class TestCustomerValidator:

    @pytest.mark.asyncio
    async def test_get_capabilities_with_ucm(self):
        mock_ucm = MagicMock()
        mock_ucm.ucm = MagicMock()
        mock_ucm.ucm.get_capabilities = AsyncMock(return_value={
            "resource_types": ["organizations", "users"],
            "schemas": {"subscribers": {"required": ["email"]}},
        })
        validator = CustomerValidator(ucm_integration_helper=mock_ucm)
        result = await validator.get_capabilities()
        # Should override subscriber fields
        assert result["schemas"]["subscribers"]["required"] == [
            "email", "firstName", "lastName", "organizationIds", "roles"
        ]

    @pytest.mark.asyncio
    async def test_get_capabilities_ucm_failure_falls_back(self):
        """When UCM fails, falls back to schema_discovery or hardcoded."""
        mock_ucm = MagicMock()
        mock_ucm.ucm = MagicMock()
        mock_ucm.ucm.get_capabilities = AsyncMock(side_effect=RuntimeError("UCM down"))
        validator = CustomerValidator(ucm_integration_helper=mock_ucm)
        # Force no schema_discovery
        validator.schema_discovery = None
        result = await validator.get_capabilities()
        # Should return hardcoded fallback
        assert "resource_types" in result
        assert "organizations" in result["resource_types"]

    @pytest.mark.asyncio
    async def test_get_capabilities_no_ucm_no_schema_returns_fallback(self):
        validator = CustomerValidator(ucm_integration_helper=None)
        validator.schema_discovery = None
        result = await validator.get_capabilities()
        assert "resource_types" in result
        assert "user_roles" in result

    @pytest.mark.asyncio
    async def test_get_capabilities_schema_discovery_fallback(self):
        """Falls back to schema_discovery when no UCM."""
        mock_schema = MagicMock()
        mock_schema.get_customer_capabilities.return_value = {
            "resource_types": ["organizations"],
            "schemas": {"subscribers": {"required": ["email"]}},
        }
        validator = CustomerValidator(ucm_integration_helper=None)
        validator.schema_discovery = mock_schema
        result = await validator.get_capabilities()
        # Should override subscriber fields even with schema discovery
        assert result["schemas"]["subscribers"]["required"] == [
            "email", "firstName", "lastName", "organizationIds", "roles"
        ]

    def test_get_examples_returns_all_examples(self):
        validator = CustomerValidator()
        validator.schema_discovery = None
        result = validator.get_examples()
        assert "examples" in result
        # users, subscribers, organizations, teams + team marketplace settings
        assert len(result["examples"]) == 5

    def test_get_examples_for_teams_includes_marketplace_settings(self):
        validator = CustomerValidator()
        validator.schema_discovery = None
        result = validator.get_examples(resource_type="teams")
        names = [example["name"] for example in result["examples"]]
        assert "Update Team Internal-Marketplace Settings" in names

    def test_get_examples_for_specific_resource_type(self):
        validator = CustomerValidator()
        validator.schema_discovery = None
        result = validator.get_examples(resource_type="users")
        assert "examples" in result
        assert len(result["examples"]) == 1
        assert MARKETPLACE_SETTINGS_EXAMPLE not in result["examples"]

    def test_get_examples_for_unknown_resource_type_excludes_marketplace_settings(self):
        """The catch-all must honour the same guard as the teams branch."""
        validator = CustomerValidator()
        validator.schema_discovery = None
        result = validator.get_examples(resource_type="products")
        names = [example["name"] for example in result["examples"]]
        assert "Update Team Internal-Marketplace Settings" not in names

    def test_get_examples_schema_discovery_teams_includes_marketplace_settings(self):
        mock_schema = MagicMock()
        mock_schema.get_customer_examples.return_value = {
            "examples": [{"name": "Create Team", "template": {"name": "Dev"}}]
        }
        validator = CustomerValidator()
        validator.schema_discovery = mock_schema
        result = validator.get_examples(resource_type="teams")
        names = [example["name"] for example in result["examples"]]
        assert "Update Team Internal-Marketplace Settings" in names

    def test_get_examples_schema_discovery_other_type_excludes_marketplace_settings(self):
        mock_schema = MagicMock()
        mock_schema.get_customer_examples.return_value = {
            "examples": [{"name": "Create Product", "template": {"name": "Plan"}}]
        }
        validator = CustomerValidator()
        validator.schema_discovery = mock_schema
        result = validator.get_examples(resource_type="products")
        names = [example["name"] for example in result["examples"]]
        assert "Update Team Internal-Marketplace Settings" not in names

    def test_get_examples_injects_the_marketplace_example_once(self):
        """Repeated calls share the module-level example, so the guard must not stack it."""
        validator = CustomerValidator()
        validator.schema_discovery = None
        first = validator.get_examples(resource_type="teams")
        second = validator.get_examples(resource_type="teams")
        for result in (first, second):
            names = [example["name"] for example in result["examples"]]
            assert names.count("Update Team Internal-Marketplace Settings") == 1

    def test_get_roles_returns_structure(self):
        validator = CustomerValidator()
        roles = validator.get_roles()
        assert "roles_by_resource_type" in roles
        assert "users" in roles["roles_by_resource_type"]
        assert "subscribers" in roles["roles_by_resource_type"]

    @pytest.mark.asyncio
    async def test_validate_configuration_no_schema_raises(self):
        validator = CustomerValidator()
        validator.schema_discovery = None
        with pytest.raises(ToolError) as exc_info:
            await validator.validate_configuration("organizations", {"name": "Test"})
        assert "unavailable" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_validate_configuration_delegates_to_schema(self):
        mock_schema = MagicMock()
        mock_schema.validate_customer_configuration.return_value = {"valid": True}
        validator = CustomerValidator()
        validator.schema_discovery = mock_schema
        result = await validator.validate_configuration("organizations", {"name": "Test"}, dry_run=True)
        assert result["valid"] is True
        mock_schema.validate_customer_configuration.assert_called_once_with(
            {"name": "Test"}, "organizations", True
        )


# ===========================================================================
# CustomerAnalytics Tests
# ===========================================================================


class TestCustomerAnalytics:

    @pytest.mark.asyncio
    async def test_analyze_users(self, mock_client):
        mock_client._extract_embedded_data.return_value = [
            {"id": "u1", "status": "active", "organizationId": "o1", "teamId": "t1"},
            {"id": "u2", "status": "inactive", "organizationId": "o1", "teamId": "t2"},
        ]
        mock_client._extract_pagination_info.return_value = {"totalElements": 2}

        analytics = CustomerAnalytics(mock_client)
        result = await analytics.analyze_customers({"resource_type": "users"})

        assert result["resource_type"] == "users"
        assert result["total_users"] == 2
        assert result["active_users"] == 1
        assert result["activity_rate"] == 50.0

    @pytest.mark.asyncio
    async def test_analyze_subscribers(self, mock_client):
        mock_client._extract_embedded_data.return_value = [
            {"status": "active"},
            {"status": "trial"},
            {"status": "inactive"},
        ]
        mock_client._extract_pagination_info.return_value = {"totalElements": 3}

        analytics = CustomerAnalytics(mock_client)
        result = await analytics.analyze_customers({"resource_type": "subscribers"})

        assert result["total_subscribers"] == 3
        assert result["active_subscribers"] == 1
        assert result["trial_subscribers"] == 1

    @pytest.mark.asyncio
    async def test_analyze_organizations(self, mock_client):
        mock_client._extract_embedded_data.return_value = [
            {"status": "active", "parentOrganizationId": "parent1"},
            {"status": "active"},
        ]
        mock_client._extract_pagination_info.return_value = {"totalElements": 2}

        analytics = CustomerAnalytics(mock_client)
        result = await analytics.analyze_customers({"resource_type": "organizations"})

        assert result["total_organizations"] == 2
        assert result["active_organizations"] == 2
        assert result["hierarchical_organizations"] == 1

    @pytest.mark.asyncio
    async def test_analyze_teams(self, mock_client):
        mock_client._extract_embedded_data.return_value = [
            {"status": "active", "organizationId": "o1"},
        ]
        mock_client._extract_pagination_info.return_value = {"totalElements": 1}

        analytics = CustomerAnalytics(mock_client)
        result = await analytics.analyze_customers({"resource_type": "teams"})

        assert result["total_teams"] == 1
        assert result["active_teams"] == 1

    @pytest.mark.asyncio
    async def test_analyze_unknown_type_raises(self, mock_client):
        analytics = CustomerAnalytics(mock_client)
        with pytest.raises(ToolError):
            await analytics.analyze_customers({"resource_type": "widgets"})

    @pytest.mark.asyncio
    async def test_get_relationships_missing_params_raises(self, mock_client):
        analytics = CustomerAnalytics(mock_client)
        with pytest.raises(ToolError):
            await analytics.get_relationships({})

    @pytest.mark.asyncio
    async def test_get_relationships_returns_placeholder(self, mock_client):
        analytics = CustomerAnalytics(mock_client)
        result = await analytics.get_relationships({
            "resource_type": "users", "resource_id": "u1"
        })
        assert result["resource_type"] == "users"
        assert result["resource_id"] == "u1"
        assert len(result["relationships"]) == 1


# ===========================================================================
# CustomerManagement handle_action routing tests
# ===========================================================================


class TestCustomerManagementHandleAction:

    @pytest.mark.asyncio
    async def test_unknown_action_raises_tool_error(self, customer_mgmt):
        with patch.object(customer_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()
            with pytest.raises(ToolError) as exc_info:
                await customer_mgmt.handle_action("nonexistent_action", {})
            assert "unknown action" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_list_action_routes_to_users(self, customer_mgmt):
        with patch.object(customer_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_gc.return_value = mock_client
            mock_client.get_users = AsyncMock(return_value={})
            mock_client._extract_embedded_data.return_value = [{"id": "u1"}]
            mock_client._extract_pagination_info.return_value = {"totalPages": 1, "totalElements": 1}

            result = await customer_mgmt.handle_action("list", {"resource_type": "users"})

            assert len(result) >= 1
            assert isinstance(result[0], TextContent)

    @pytest.mark.asyncio
    async def test_list_invalid_resource_type_raises(self, customer_mgmt):
        with patch.object(customer_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()
            with pytest.raises(ToolError):
                await customer_mgmt.handle_action("list", {"resource_type": "widgets"})

    @pytest.mark.asyncio
    async def test_get_action_routes_to_organizations(self, customer_mgmt):
        with patch.object(customer_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_gc.return_value = mock_client
            mock_client.get_organization_by_id = AsyncMock(return_value={"id": "o1", "name": "Org"})

            result = await customer_mgmt.handle_action("get", {
                "resource_type": "organizations", "organization_id": "o1"
            })
            assert isinstance(result[0], TextContent)
            assert "Org" in result[0].text or "o1" in result[0].text

    @pytest.mark.asyncio
    async def test_create_dry_run(self, customer_mgmt):
        with patch.object(customer_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()

            result = await customer_mgmt.handle_action("create", {
                "resource_type": "organizations",
                "resource_data": {"name": "Test Org"},
                "dry_run": True,
            })

            assert "DRY RUN" in result[0].text
            assert "Test Org" in result[0].text

    @pytest.mark.asyncio
    async def test_update_dry_run(self, customer_mgmt):
        with patch.object(customer_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()

            result = await customer_mgmt.handle_action("update", {
                "resource_type": "organizations",
                "organization_id": "o1",
                "organization_data": {"name": "New Name"},
                "dry_run": True,
            })

            assert "DRY RUN" in result[0].text

    @pytest.mark.asyncio
    async def test_delete_dry_run(self, customer_mgmt):
        with patch.object(customer_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()

            result = await customer_mgmt.handle_action("delete", {
                "resource_type": "users",
                "user_id": "u1",
                "dry_run": True,
            })

            assert "DRY RUN" in result[0].text
            assert "cannot be undone" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_get_capabilities_action(self, customer_mgmt):
        with patch.object(customer_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()
            customer_mgmt.validator.schema_discovery = None
            customer_mgmt.validator.ucm_helper = None

            result = await customer_mgmt.handle_action("get_capabilities", {})

            assert len(result) >= 1
            assert isinstance(result[0], TextContent)
            assert "capabilities" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_get_examples_action(self, customer_mgmt):
        with patch.object(customer_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()
            customer_mgmt.validator.schema_discovery = None

            result = await customer_mgmt.handle_action("get_examples", {})

            assert isinstance(result[0], TextContent)
            assert "examples" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_get_roles_action(self, customer_mgmt):
        with patch.object(customer_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()

            result = await customer_mgmt.handle_action("get_roles", {})

            assert isinstance(result[0], TextContent)
            assert "role" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_get_relationships_action(self, customer_mgmt):
        with patch.object(customer_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()

            result = await customer_mgmt.handle_action("get_relationships", {
                "resource_type": "users", "resource_id": "u1"
            })

            assert isinstance(result[0], TextContent)
            assert "relationship" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_analyze_action(self, customer_mgmt):
        with patch.object(customer_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_gc.return_value = mock_client
            mock_client.get_organizations = AsyncMock(return_value={})
            mock_client._extract_embedded_data.return_value = [{"status": "active"}]
            mock_client._extract_pagination_info.return_value = {"totalElements": 1}

            result = await customer_mgmt.handle_action("analyze", {
                "resource_type": "organizations"
            })

            assert isinstance(result[0], TextContent)
            assert "analytics" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_create_with_legacy_data_key(self, customer_mgmt):
        """Create action falls back to legacy user_data key when resource_data not provided."""
        with patch.object(customer_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_gc.return_value = mock_client
            mock_client.get_users = AsyncMock()
            mock_client.create_user = AsyncMock(return_value={"id": "u_new"})
            with patch(
                "src.revenium_mcp_server.tools_decomposed.customer_management.get_config_value",
                return_value=None,
            ):
                result = await customer_mgmt.handle_action("create", {
                    "resource_type": "users",
                    "user_data": {"email": "u@c.com", "firstName": "U", "lastName": "C", "roles": ["ROLE_API_CONSUMER"]},
                    "auto_generate": False,
                })
            assert isinstance(result[0], TextContent)
            assert "created successfully" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_delete_routes_to_correct_manager(self, customer_mgmt):
        """Delete action routes to the correct manager based on resource_type."""
        with patch.object(customer_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_gc.return_value = mock_client
            mock_client.delete_organization = AsyncMock(return_value={"deleted": True})

            result = await customer_mgmt.handle_action("delete", {
                "resource_type": "organizations",
                "organization_id": "o_del",
            })

            assert "deleted successfully" in result[0].text.lower()
            mock_client.delete_organization.assert_called_once_with("o_del")

    @pytest.mark.asyncio
    async def test_lookup_user_action_routes_to_user_manager(self, customer_mgmt):
        """lookup_user action routes to UserManager.lookup_user and renders a result."""
        with patch.object(customer_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_gc.return_value = mock_client
            mock_client.lookup_user_by_email = AsyncMock(
                return_value={"id": "u1", "email": "joao@acme.com"}
            )

            result = await customer_mgmt.handle_action("lookup_user", {"email": "joao@acme.com"})

            assert isinstance(result[0], TextContent)
            assert "joao@acme.com" in result[0].text
            mock_client.lookup_user_by_email.assert_called_once_with("joao@acme.com")

    @pytest.mark.asyncio
    async def test_lookup_subscriber_action_routes_to_subscriber_manager(self, customer_mgmt):
        """lookup_subscriber action routes to SubscriberManager.lookup_subscriber."""
        with patch.object(customer_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_gc.return_value = mock_client
            mock_client.lookup_subscriber_by_email = AsyncMock(
                return_value={"id": "s1", "subscriberId": "sub1", "email": "joao@acme.com"}
            )

            result = await customer_mgmt.handle_action(
                "lookup_subscriber", {"email": "joao@acme.com"}
            )

            assert isinstance(result[0], TextContent)
            assert "joao@acme.com" in result[0].text
            mock_client.lookup_subscriber_by_email.assert_called_once_with("joao@acme.com")

    @pytest.mark.asyncio
    async def test_lookup_user_action_malformed_email_makes_no_api_call(self, customer_mgmt):
        """Boundary validation trips before any client call for a malformed email."""
        with patch.object(customer_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_gc.return_value = mock_client
            mock_client.lookup_user_by_email = AsyncMock()

            with pytest.raises(ToolError):
                await customer_mgmt.handle_action("lookup_user", {"email": "garbage"})

            mock_client.lookup_user_by_email.assert_not_called()

    @pytest.mark.asyncio
    async def test_lookup_actions_in_supported_actions(self, customer_mgmt):
        """lookup_user and lookup_subscriber are advertised as supported actions."""
        actions = await customer_mgmt._get_supported_actions()
        assert "lookup_user" in actions
        assert "lookup_subscriber" in actions

    @pytest.mark.asyncio
    async def test_get_marketplace_settings_action_routes_to_team_manager(self, customer_mgmt):
        with patch.object(customer_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_gc.return_value = mock_client
            mock_client.get_team_marketplace_settings = AsyncMock(
                return_value={"internalMarketplaceNames": ["acme-internal"]}
            )

            result = await customer_mgmt.handle_action(
                "get_marketplace_settings", {"team_id": "jR2kmLs"}
            )

            assert isinstance(result[0], TextContent)
            assert "acme-internal" in result[0].text
            mock_client.get_team_marketplace_settings.assert_called_once_with("jR2kmLs")

    @pytest.mark.asyncio
    async def test_update_marketplace_settings_action_reads_then_writes(self, customer_mgmt):
        with patch.object(customer_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_gc.return_value = mock_client
            mock_client.get_team_marketplace_settings = AsyncMock(
                return_value={"internalMarketplaceNames": ["revenium-tools"]}
            )
            mock_client.update_team_marketplace_settings = AsyncMock(
                return_value={
                    "internalMarketplaceNames": ["revenium-tools", "acme-internal"]
                }
            )

            result = await customer_mgmt.handle_action(
                "update_marketplace_settings",
                {"team_id": "jR2kmLs", "marketplace_names": ["acme-internal"]},
            )

            mock_client.get_team_marketplace_settings.assert_called_once_with("jR2kmLs")
            sent_payload = mock_client.update_team_marketplace_settings.call_args[0][1]
            assert sent_payload == {
                "internalMarketplaceNames": ["revenium-tools", "acme-internal"]
            }
            assert isinstance(result[0], TextContent)
            assert "THIRD_PARTY" in result[0].text
            assert "WARNING" not in result[0].text

    @pytest.mark.asyncio
    async def test_update_marketplace_settings_renders_divergence_warning(self, customer_mgmt):
        """A stored list that disagrees with the sent list must lead the rendered text."""
        with patch.object(customer_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_gc.return_value = mock_client
            mock_client.get_team_marketplace_settings = AsyncMock(
                return_value={"internalMarketplaceNames": []}
            )
            mock_client.update_team_marketplace_settings = AsyncMock(
                return_value={"internalMarketplaceNames": ["added-elsewhere"]}
            )

            result = await customer_mgmt.handle_action(
                "update_marketplace_settings",
                {"team_id": "jR2kmLs", "marketplace_names": ["acme-internal"]},
            )

            assert "WARNING" in result[0].text
            assert MARKETPLACE_DIVERGENCE_NOTE in result[0].text
            assert "added-elsewhere" in result[0].text

    @pytest.mark.asyncio
    async def test_update_marketplace_settings_missing_names_makes_no_api_call(
        self, customer_mgmt
    ):
        with patch.object(customer_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_gc.return_value = mock_client
            mock_client.get_team_marketplace_settings = AsyncMock()
            mock_client.update_team_marketplace_settings = AsyncMock()

            with pytest.raises(ToolError):
                await customer_mgmt.handle_action(
                    "update_marketplace_settings", {"team_id": "jR2kmLs"}
                )

            mock_client.get_team_marketplace_settings.assert_not_called()
            mock_client.update_team_marketplace_settings.assert_not_called()

    @pytest.mark.asyncio
    async def test_marketplace_actions_in_supported_actions(self, customer_mgmt):
        actions = await customer_mgmt._get_supported_actions()
        assert "get_marketplace_settings" in actions
        assert "update_marketplace_settings" in actions

    @pytest.mark.asyncio
    async def test_capabilities_text_documents_marketplace_settings(self, customer_mgmt):
        with patch.object(customer_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()
            result = await customer_mgmt.handle_action("get_capabilities", {})

        text = result[0].text
        assert "get_marketplace_settings" in text
        assert "update_marketplace_settings" in text
        assert "THIRD_PARTY" in text
        assert MARKETPLACE_CONCURRENCY_NOTE in text

    @pytest.mark.asyncio
    async def test_marketplace_capability_advertised_in_metadata(self, customer_mgmt):
        capabilities = await customer_mgmt._get_tool_capabilities()
        names = [c.name for c in capabilities]
        assert "Team Internal-Marketplace Settings" in names

    @pytest.mark.asyncio
    async def test_marketplace_capability_states_the_concurrency_limitation(
        self, customer_mgmt
    ):
        """The read-merge-PUT cannot be made atomic, so the limitation is advertised."""
        capabilities = await customer_mgmt._get_tool_capabilities()
        marketplace = next(
            c for c in capabilities if c.name == "Team Internal-Marketplace Settings"
        )
        assert MARKETPLACE_CONCURRENCY_NOTE in marketplace.limitations


class TestCustomerManagementAutoGeneration:

    def test_apply_auto_generation_organizations(self, customer_mgmt):
        """Auto-generation adds currency and types for organizations."""
        result = customer_mgmt._apply_auto_generation(
            {"name": "Acme Corp"}, "organizations", {}
        )
        assert result["currency"] == "USD"
        assert result["types"] == ["CONSUMER"]

    def test_apply_auto_generation_users_from_email(self, customer_mgmt):
        """Auto-generation infers firstName/lastName from email."""
        result = customer_mgmt._apply_auto_generation(
            {"email": "john.doe@company.com"}, "users", {}
        )
        assert result["firstName"] == "John"
        assert result["lastName"] == "Doe"
        assert result["roles"] == ["ROLE_API_CONSUMER"]

    def test_apply_auto_generation_subscribers_from_email(self, customer_mgmt):
        """Auto-generation infers name fields for subscribers too."""
        result = customer_mgmt._apply_auto_generation(
            {"email": "jane.smith@co.com"}, "subscribers", {}
        )
        assert result["firstName"] == "Jane"
        assert result["lastName"] == "Smith"


class TestCreateCustomersConfigDefaultFields:

    def test_organization_injects_tenant_id(self, mock_client):
        mock_client.auth_config.tenant_id = "t_123"
        mock_client.auth_config.team_id = "team_456"
        config = UpdateConfigs.create_customers_config(mock_client, "organization")
        assert config.default_fields == {"tenantId": "t_123"}

    def test_organization_falls_back_to_team_id(self, mock_client):
        mock_client.auth_config.tenant_id = None
        mock_client.auth_config.team_id = "team_456"
        config = UpdateConfigs.create_customers_config(mock_client, "organization")
        assert config.default_fields == {"tenantId": "team_456"}

    def test_team_injects_tenant_id(self, mock_client):
        mock_client.auth_config.tenant_id = "t_789"
        mock_client.auth_config.team_id = "team_000"
        config = UpdateConfigs.create_customers_config(mock_client, "team")
        assert config.default_fields == {"tenantId": "t_789"}

    def test_user_injects_team_id(self, mock_client):
        mock_client.team_id = "team_456"
        config = UpdateConfigs.create_customers_config(mock_client, "user")
        assert config.default_fields == {"teamId": "team_456"}

    def test_subscriber_injects_team_id(self, mock_client):
        mock_client.team_id = "team_456"
        config = UpdateConfigs.create_customers_config(mock_client, "subscriber")
        assert config.default_fields == {"teamId": "team_456"}


from tests.unit._helpers_no_framework_leak import assert_no_framework_leak


class TestCustomerListPaginationValidation:
    """BACK-1270 / item #5 — Pydantic leak guard on manage_customers list."""

    @pytest.mark.asyncio
    async def test_list_orgs_rejects_float_size_with_structured_error(self, org_manager):
        with pytest.raises(ToolError) as exc:
            await org_manager.list_organizations({"page": 0, "size": 3.7})
        assert exc.value.field == "size"
        assert_no_framework_leak(exc.value.message)


class TestUpdateOrganizationPreservesParent:
    """BACK-1270 / item #1 — name-only update must NOT drop parent (BACK-911 regression).

    The Revenium organizations API persists the parent relationship via the scalar
    ``parentId`` field. GETs return the populated nested ``parent`` object, but PUT
    only writes the relationship if ``parentId`` is present in the payload. The
    PartialUpdateHandler must therefore project the current ``parent.id`` into
    ``parentId`` on update, otherwise a name-only patch silently nulls the parent
    server-side (the BACK-911 regression).
    """

    @pytest.mark.asyncio
    async def test_name_only_update_preserves_parent(self, org_manager, mock_client):
        existing = {
            "id": "org_123",
            "name": "old-name",
            "parent": {"id": "team_xyz", "label": "Engineering"},
            "tenantId": "tenant_a",
        }
        # The handler reads current state, merges patch, writes the merged view.
        mock_client.get_organization_by_id = AsyncMock(return_value=existing)
        mock_client.update_organization = AsyncMock(
            side_effect=lambda _id, payload: {**existing, **payload}
        )

        await org_manager.update_organization({
            "organization_id": "org_123",
            "organization_data": {"name": "new-name"},
        })

        # The payload sent upstream must carry the parent relationship in a form
        # the API persists. Either parentId (scalar id, what the server writes on
        # PUT) or a parent dict containing an id is acceptable; both must NOT be
        # absent / None.
        call_args = mock_client.update_organization.await_args
        sent_payload = (
            call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs["payload"]
        )
        parent_obj = sent_payload.get("parent")
        parent_id_scalar = sent_payload.get("parentId")
        assert parent_obj is not None or parent_id_scalar is not None, (
            f"BACK-911 regression: parent dropped on partial update. payload={sent_payload!r}"
        )
        # The ID the API uses to persist the relationship must be present on PUT.
        assert sent_payload.get("parentId") == "team_xyz", (
            "BACK-911 regression: API persists parent via parentId on PUT, but the "
            f"merged payload is missing parentId. payload={sent_payload!r}"
        )

class TestLookupEmailMultiAtRejection:
    """Review: partition() splits on the first @ only — a@b@c must be rejected."""

    def test_multiple_at_signs_rejected(self):
        from src.revenium_mcp_server.tools_decomposed.customer_management import (
            _validate_lookup_email,
        )
        from src.revenium_mcp_server.common.error_handling import ToolError
        import pytest as _pytest

        with _pytest.raises(ToolError):
            _validate_lookup_email("a@b@c.com", action="lookup_user")

    def test_single_at_still_passes(self):
        from src.revenium_mcp_server.tools_decomposed.customer_management import (
            _validate_lookup_email,
        )

        assert _validate_lookup_email("  a@b.com  ", action="lookup_user") == "a@b.com"

