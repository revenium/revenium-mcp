"""Unit tests for Subscription Management tools.

Tests the SubscriptionManager and SubscriptionManagement classes from the decomposed tools module.
Focuses on CRUD operations, product discovery/validation, search filtering, and error handling.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.tools_decomposed.subscription_management import (
    SubscriptionManager,
    SubscriptionManagement,
)
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.client import ReveniumAPIError
from mcp.types import TextContent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_client():
    """Create a mock ReveniumClient for SubscriptionManager."""
    client = MagicMock()
    client.team_id = "test_team_id_456"
    client.get_subscriptions = AsyncMock()
    client.get_subscription_by_id = AsyncMock()
    client.create_subscription = AsyncMock()
    client.cancel_subscription = AsyncMock()
    client.get_products = AsyncMock()
    client.get_product_by_id = AsyncMock()
    client.get_organizations = AsyncMock()
    client.get_subscribers = AsyncMock()
    client.get_credentials = AsyncMock()
    client._extract_embedded_data = MagicMock()
    client._extract_pagination_info = MagicMock()
    return client


@pytest.fixture
def sub_manager(mock_client):
    """Create SubscriptionManager with mocked client."""
    return SubscriptionManager(mock_client)


@pytest.fixture
def sub_mgmt():
    """Create SubscriptionManagement instance (top-level tool)."""
    return SubscriptionManagement()


# ===========================================================================
# SubscriptionManager - Discover Products
# ===========================================================================


class TestSubscriptionManagerDiscoverProducts:
    """Test SubscriptionManager.discover_products behavior."""

    @pytest.mark.asyncio
    async def test_discover_products_returns_formatted_list(self, sub_manager, mock_client):
        """discover_products returns product list with billing warnings."""
        mock_client._extract_embedded_data.return_value = [
            {"id": "p1", "name": "Product A", "published": True, "description": "Desc A"},
        ]
        mock_client._extract_pagination_info.return_value = {"totalPages": 1}

        result = await sub_manager.discover_products({})

        assert result["action"] == "discover_products"
        assert result["total_found"] == 1
        assert result["products"][0]["id"] == "p1"
        assert result["products"][0]["status"] == "Available for subscriptions"
        assert "billing_warning" in result

    @pytest.mark.asyncio
    async def test_discover_products_filters_by_search_query(self, sub_manager, mock_client):
        """discover_products filters products by search query."""
        mock_client._extract_embedded_data.return_value = [
            {"id": "p1", "name": "Premium API", "description": ""},
            {"id": "p2", "name": "Basic Plan", "description": ""},
        ]
        mock_client._extract_pagination_info.return_value = {"totalPages": 1}

        result = await sub_manager.discover_products({"search_query": "premium"})

        assert result["total_found"] == 1
        assert result["products"][0]["id"] == "p1"

    @pytest.mark.asyncio
    async def test_discover_products_unpublished_status(self, sub_manager, mock_client):
        """Unpublished products get 'Not available' status."""
        mock_client._extract_embedded_data.return_value = [
            {"id": "p1", "name": "Draft", "published": False},
        ]
        mock_client._extract_pagination_info.return_value = {"totalPages": 1}

        result = await sub_manager.discover_products({})

        assert "Not available" in result["products"][0]["status"]

    @pytest.mark.asyncio
    async def test_discover_products_handles_api_error(self, sub_manager, mock_client):
        """discover_products returns error guidance when API call fails."""
        mock_client.get_products = AsyncMock(side_effect=RuntimeError("API down"))

        result = await sub_manager.discover_products({})

        assert "error" in result
        assert "fallback_guidance" in result


# ===========================================================================
# SubscriptionManager - Validate Product
# ===========================================================================


class TestSubscriptionManagerValidateProduct:
    """Test SubscriptionManager.validate_product_for_subscription behavior."""

    @pytest.mark.asyncio
    async def test_validate_missing_product_id_raises(self, sub_manager):
        """Validation without product_id raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await sub_manager.validate_product_for_subscription({})

        assert "product_id" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_validate_published_product_returns_valid(self, sub_manager, mock_client):
        """Published product validates as valid for subscriptions."""
        mock_client.get_product_by_id.return_value = {
            "id": "p1", "name": "Active Product", "published": True, "description": "Good"
        }

        result = await sub_manager.validate_product_for_subscription({"product_id": "p1"})

        assert result["valid"] is True
        assert result["published"] is True

    @pytest.mark.asyncio
    async def test_validate_unpublished_product_returns_invalid(self, sub_manager, mock_client):
        """Unpublished product validates as invalid."""
        mock_client.get_product_by_id.return_value = {
            "id": "p1", "name": "Draft", "published": False
        }

        result = await sub_manager.validate_product_for_subscription({"product_id": "p1"})

        assert result["valid"] is False
        assert "not published" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_validate_product_not_found_returns_invalid(self, sub_manager, mock_client):
        """Non-existent product returns invalid with guidance."""
        mock_client.get_product_by_id.return_value = None

        result = await sub_manager.validate_product_for_subscription({"product_id": "bad_id"})

        assert result["valid"] is False
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_validate_product_api_error_returns_invalid(self, sub_manager, mock_client):
        """API error during validation returns error result."""
        mock_client.get_product_by_id = AsyncMock(side_effect=RuntimeError("timeout"))

        result = await sub_manager.validate_product_for_subscription({"product_id": "p1"})

        assert result["valid"] is False
        assert "failed" in result["error"].lower()


# ===========================================================================
# SubscriptionManager - List/Get
# ===========================================================================


class TestSubscriptionManagerList:
    """Test SubscriptionManager.list_subscriptions behavior."""

    @pytest.mark.asyncio
    async def test_list_subscriptions_returns_result(self, sub_manager, mock_client):
        """List returns subscriptions with pagination info."""
        mock_client._extract_embedded_data.return_value = [
            {"id": "sub1", "name": "Sub A"},
        ]
        mock_client._extract_pagination_info.return_value = {"totalPages": 1}

        result = await sub_manager.list_subscriptions({})

        assert result["action"] == "list"
        assert result["total_found"] == 1
        assert len(result["subscriptions"]) == 1

    @pytest.mark.asyncio
    async def test_list_subscriptions_uses_defaults(self, sub_manager, mock_client):
        """List uses default page=0, size=20."""
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {}

        await sub_manager.list_subscriptions({})

        mock_client.get_subscriptions.assert_called_once_with(page=0, size=20)


class TestSubscriptionManagerGet:
    """Test SubscriptionManager.get_subscription behavior."""

    @pytest.mark.asyncio
    async def test_get_subscription_returns_data(self, sub_manager, mock_client):
        """Getting subscription by ID returns data."""
        mock_client.get_subscription_by_id.return_value = {"id": "sub1", "name": "My Sub"}

        result = await sub_manager.get_subscription({"subscription_id": "sub1"})

        assert result["id"] == "sub1"
        mock_client.get_subscription_by_id.assert_called_once_with("sub1")

    @pytest.mark.asyncio
    async def test_get_subscription_missing_id_raises(self, sub_manager):
        """Get without subscription_id raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await sub_manager.get_subscription({})

        assert "subscription_id" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_get_subscription_404_raises_not_found(self, sub_manager, mock_client):
        """404 API error raises ToolError with NOT_FOUND context."""
        mock_client.get_subscription_by_id = AsyncMock(
            side_effect=ReveniumAPIError(message="Not found", status_code=404)
        )

        with pytest.raises(ToolError) as exc_info:
            await sub_manager.get_subscription({"subscription_id": "bad_id"})

        assert "not found" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_get_subscription_400_raises_validation_error(self, sub_manager, mock_client):
        """400 API error raises ToolError about invalid ID format."""
        mock_client.get_subscription_by_id = AsyncMock(
            side_effect=ReveniumAPIError(message="Bad request", status_code=400)
        )

        with pytest.raises(ToolError) as exc_info:
            await sub_manager.get_subscription({"subscription_id": "!!!"})

        assert "invalid" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_get_subscription_500_reraises(self, sub_manager, mock_client):
        """500 API error is re-raised as-is."""
        mock_client.get_subscription_by_id = AsyncMock(
            side_effect=ReveniumAPIError(message="Server error", status_code=500)
        )

        with pytest.raises(ReveniumAPIError):
            await sub_manager.get_subscription({"subscription_id": "x"})


# ===========================================================================
# SubscriptionManager - Create
# ===========================================================================


class TestSubscriptionManagerCreate:
    """Test SubscriptionManager.create_subscription behavior."""

    @pytest.mark.asyncio
    async def test_create_missing_all_params_raises(self, sub_manager):
        """Create without subscription_data or name raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await sub_manager.create_subscription({})

        assert "subscription_data" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_create_with_data_adds_team_id(self, sub_manager, mock_client):
        """Create auto-adds teamId from client."""
        mock_client.create_subscription.return_value = {"id": "sub_new"}

        await sub_manager.create_subscription({
            "subscription_data": {
                "name": "Test Sub",
                "productId": "p1",
                "clientEmailAddress": "test@example.com",
            }
        })

        data = mock_client.create_subscription.call_args[0][0]
        assert data["teamId"] == "test_team_id_456"

    @pytest.mark.asyncio
    async def test_create_maps_product_id_to_productId(self, sub_manager, mock_client):
        """Create maps product_id to productId for API compatibility."""
        mock_client.create_subscription.return_value = {"id": "sub_new"}

        await sub_manager.create_subscription({
            "subscription_data": {
                "name": "Test",
                "product_id": "p1",
                "clientEmailAddress": "test@example.com",
            }
        })

        data = mock_client.create_subscription.call_args[0][0]
        assert data["productId"] == "p1"

    @pytest.mark.asyncio
    async def test_create_auto_generates_from_name(self, sub_manager, mock_client):
        """Create with name-only auto-generates subscription_data including product lookup."""
        mock_client.get_products = AsyncMock(return_value={})
        mock_client._extract_embedded_data.return_value = [{"id": "auto_prod_1"}]
        mock_client.create_subscription.return_value = {"id": "sub_auto"}

        result = await sub_manager.create_subscription({"name": "Auto Sub"})

        data = mock_client.create_subscription.call_args[0][0]
        assert data["name"] == "Auto Sub"
        assert data["productId"] == "auto_prod_1"
        assert "@example.com" in data["clientEmailAddress"]

    @pytest.mark.asyncio
    async def test_create_auto_generate_no_products_raises(self, sub_manager, mock_client):
        """Auto-generate fails with structured error when no products exist."""
        mock_client.get_products = AsyncMock(return_value={})
        mock_client._extract_embedded_data.return_value = []

        with pytest.raises(ToolError):
            await sub_manager.create_subscription({"name": "No Products Sub"})


# ===========================================================================
# SubscriptionManager - Update
# ===========================================================================


class TestSubscriptionManagerUpdate:
    """Test SubscriptionManager.update_subscription behavior."""

    @pytest.mark.asyncio
    async def test_update_missing_id_raises(self, sub_manager):
        """Update without subscription_id raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await sub_manager.update_subscription({"subscription_data": {"name": "New"}})

        assert "subscription_id" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_update_missing_data_raises(self, sub_manager):
        """Update without subscription_data raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await sub_manager.update_subscription({"subscription_id": "sub1"})

        assert "subscription_data" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_update_delegates_to_partial_handler(self, sub_manager):
        """Update with valid params delegates to PartialUpdateHandler."""
        sub_manager.update_handler.update_with_merge = AsyncMock(
            return_value={"id": "sub1", "name": "Updated"}
        )
        sub_manager.update_config_factory.get_config = MagicMock(return_value={})

        result = await sub_manager.update_subscription(
            {"subscription_id": "sub1", "subscription_data": {"name": "Updated"}}
        )

        assert result["name"] == "Updated"
        sub_manager.update_handler.update_with_merge.assert_called_once()


# ===========================================================================
# SubscriptionManager - Cancel/Delete
# ===========================================================================


class TestSubscriptionManagerCancelDelete:
    """Test cancel and delete subscription behavior."""

    @pytest.mark.asyncio
    async def test_cancel_missing_id_raises(self, sub_manager):
        """Cancel without subscription_id raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await sub_manager.cancel_subscription({})

        assert "subscription_id" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_cancel_calls_client(self, sub_manager, mock_client):
        """Cancel delegates to client.cancel_subscription."""
        mock_client.cancel_subscription.return_value = {"cancelled": True}

        result = await sub_manager.cancel_subscription({"subscription_id": "sub_c"})

        assert result["cancelled"] is True
        mock_client.cancel_subscription.assert_called_once_with("sub_c")

    @pytest.mark.asyncio
    async def test_delete_missing_id_raises(self, sub_manager):
        """Delete without subscription_id raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await sub_manager.delete_subscription({})

        assert "subscription_id" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_delete_calls_cancel_endpoint(self, sub_manager, mock_client):
        """Delete uses cancel_subscription endpoint (DELETE verb)."""
        mock_client.cancel_subscription.return_value = {"deleted": True}

        result = await sub_manager.delete_subscription({"subscription_id": "sub_d"})

        mock_client.cancel_subscription.assert_called_once_with("sub_d")


# ===========================================================================
# SubscriptionManager - Search
# ===========================================================================


class TestSubscriptionManagerSearch:
    """Test SubscriptionManager.search_subscriptions filtering behavior."""

    @pytest.mark.asyncio
    async def test_search_filters_by_query(self, sub_manager, mock_client):
        """Search filters subscriptions by general search query."""
        mock_client._extract_embedded_data.return_value = [
            {"id": "s1", "name": "Premium Sub", "customer": "", "product": "", "subscriber": "", "description": ""},
            {"id": "s2", "name": "Basic Sub", "customer": "", "product": "", "subscriber": "", "description": ""},
        ]
        mock_client._extract_pagination_info.return_value = {}

        result = await sub_manager.search_subscriptions({"search_query": "premium"})

        assert result["total_found"] == 1
        assert result["subscriptions"][0]["id"] == "s1"

    @pytest.mark.asyncio
    async def test_search_filters_by_customer_name(self, sub_manager, mock_client):
        """Search filters by customer_name field."""
        mock_client._extract_embedded_data.return_value = [
            {"id": "s1", "name": "Sub", "customer": "Acme Corp", "product": "", "subscriber": "", "description": ""},
            {"id": "s2", "name": "Sub", "customer": "Beta Inc", "product": "", "subscriber": "", "description": ""},
        ]
        mock_client._extract_pagination_info.return_value = {}

        result = await sub_manager.search_subscriptions({"customer_name": "acme"})

        assert result["total_found"] == 1
        assert result["subscriptions"][0]["customer"] == "Acme Corp"

    @pytest.mark.asyncio
    async def test_search_filters_by_product_name(self, sub_manager, mock_client):
        """Search filters by product_name field."""
        mock_client._extract_embedded_data.return_value = [
            {"id": "s1", "name": "Sub", "customer": "", "product": "Pro Plan", "subscriber": "", "description": ""},
            {"id": "s2", "name": "Sub", "customer": "", "product": "Free Tier", "subscriber": "", "description": ""},
        ]
        mock_client._extract_pagination_info.return_value = {}

        result = await sub_manager.search_subscriptions({"product_name": "pro plan"})

        assert result["total_found"] == 1

    @pytest.mark.asyncio
    async def test_search_no_match_returns_empty(self, sub_manager, mock_client):
        """Search with no matches returns empty list."""
        mock_client._extract_embedded_data.return_value = [
            {"id": "s1", "name": "Sub", "customer": "", "product": "", "subscriber": "", "description": ""},
        ]
        mock_client._extract_pagination_info.return_value = {}

        result = await sub_manager.search_subscriptions({"search_query": "nonexistent"})

        assert result["total_found"] == 0
        assert result["subscriptions"] == []


# ===========================================================================
# SubscriptionManager - Get Supporting Data
# ===========================================================================


class TestSubscriptionManagerSupportingData:
    """Test SubscriptionManager.get_supporting_data behavior."""

    @pytest.mark.asyncio
    async def test_get_supporting_data_all_types(self, sub_manager, mock_client):
        """get_supporting_data with data_type='all' fetches all entity types."""
        mock_client.get_organizations = AsyncMock(return_value={})
        mock_client.get_products = AsyncMock(return_value={})
        mock_client.get_subscribers = AsyncMock(return_value={})
        mock_client.get_credentials = AsyncMock(return_value={})
        mock_client._extract_embedded_data.return_value = []

        result = await sub_manager.get_supporting_data({"data_type": "all"})

        assert "organizations" in result
        assert "products" in result
        assert "subscribers" in result
        assert "credentials" in result

    @pytest.mark.asyncio
    async def test_get_supporting_data_single_type(self, sub_manager, mock_client):
        """get_supporting_data with specific type only fetches that type."""
        mock_client.get_products = AsyncMock(return_value={})
        mock_client._extract_embedded_data.return_value = [{"id": "p1"}]

        result = await sub_manager.get_supporting_data({"data_type": "products"})

        assert "products" in result
        assert "organizations" not in result

    @pytest.mark.asyncio
    async def test_get_supporting_data_handles_error(self, sub_manager, mock_client):
        """get_supporting_data returns error when API fails."""
        mock_client.get_organizations = AsyncMock(side_effect=RuntimeError("API down"))

        result = await sub_manager.get_supporting_data({"data_type": "all"})

        assert "error" in result


# ===========================================================================
# SubscriptionManagement handle_action routing tests
# ===========================================================================


class TestSubscriptionManagementHandleAction:
    """Test SubscriptionManagement.handle_action routing."""

    @pytest.mark.asyncio
    async def test_unknown_action_raises_tool_error(self, sub_mgmt):
        """Unknown action raises ToolError."""
        with patch.object(sub_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()

            with pytest.raises(ToolError) as exc_info:
                await sub_mgmt.handle_action("nonexistent_action", {})

            assert "not supported" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_list_action_returns_results(self, sub_mgmt):
        """List action returns formatted subscription list."""
        with patch.object(sub_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_gc.return_value = mock_client
            mock_client.get_subscriptions = AsyncMock(return_value={})
            mock_client._extract_embedded_data.return_value = [{"id": "sub1", "name": "A"}]
            mock_client._extract_pagination_info.return_value = {"totalPages": 1}

            result = await sub_mgmt.handle_action("list", {})

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)

    @pytest.mark.asyncio
    async def test_get_action_returns_subscription(self, sub_mgmt):
        """Get action returns subscription details."""
        with patch.object(sub_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_gc.return_value = mock_client
            mock_client.get_subscription_by_id = AsyncMock(
                return_value={"id": "sub1", "name": "Sub A"}
            )

            result = await sub_mgmt.handle_action("get", {"subscription_id": "sub1"})

        assert len(result) >= 1
        assert "sub1" in result[0].text

    @pytest.mark.asyncio
    async def test_create_auto_generate_missing_name_returns_message(self, sub_mgmt):
        """Create in auto-generate mode without name returns missing field message."""
        with patch.object(sub_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_gc.return_value = mock_client

            result = await sub_mgmt.handle_action("create", {"subscription_data": {}})

        assert len(result) >= 1
        assert "name" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_discover_products_action_routes_correctly(self, sub_mgmt):
        """discover_products routes to creation actions handler."""
        with patch.object(sub_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_gc.return_value = mock_client
            mock_client.get_products = AsyncMock(return_value={})
            mock_client._extract_embedded_data.return_value = []
            mock_client._extract_pagination_info.return_value = {}

            result = await sub_mgmt.handle_action("discover_products", {})

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)


# ===========================================================================
# SubscriptionValidator tests
# ===========================================================================


