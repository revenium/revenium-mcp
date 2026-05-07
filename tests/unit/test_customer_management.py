"""Unit tests for Customer Management tools.

Tests the CustomerManagement, UserManager, SubscriberManager, OrganizationManager,
TeamManager, CustomerValidator, CustomerAnalytics, and BaseManager classes.
Focuses on CRUD operations, validation logic, error handling, and action routing.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.tools_decomposed.customer_management import (
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
from src.revenium_mcp_server.common.error_handling import ToolError
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
    client.create_user = AsyncMock()
    client.update_user = AsyncMock()
    client.delete_user = AsyncMock()

    # Subscriber methods
    client.get_subscribers = AsyncMock(return_value={})
    client.get_subscriber_by_id = AsyncMock()
    client.get_subscriber_by_email = AsyncMock()
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
        assert len(result["examples"]) == 4  # users, subscribers, organizations, teams

    def test_get_examples_for_specific_resource_type(self):
        validator = CustomerValidator()
        validator.schema_discovery = None
        result = validator.get_examples(resource_type="users")
        assert "examples" in result
        assert len(result["examples"]) == 1

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
