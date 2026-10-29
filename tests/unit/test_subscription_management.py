"""Unit tests for Subscription Management tools.

Tests the SubscriptionManager and SubscriptionManagement classes from the decomposed tools module.
Focuses on CRUD operations, product discovery/validation, search filtering, and error handling.
"""

import json
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch

from src.revenium_mcp_server.tools_decomposed.subscription_management import (
    SubscriptionHierarchyManager,
    SubscriptionManager,
    SubscriptionManagement,
)
from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError
from src.revenium_mcp_server.client import ReveniumAPIError, ReveniumClient
from mcp.types import TextContent
from tests.unit._helpers_recording_client import recording_client
from tests.unit._helpers_list_heading import LIST_HEADING_CASES, heading_and_body, rows


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
    client.delete_subscription = AsyncMock()
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

    @pytest.mark.asyncio
    async def test_list_subscriptions_rejects_string_page_with_structured_error(
        self, sub_manager, mock_client
    ):
        """Wrong-type page must raise a structured ToolError before reaching the client.

        This is the BACK-1111 audit shape — page='not_a_number' previously bubbled up
        as a raw Pydantic error with errors.pydantic.dev URL leakage.
        """
        from src.revenium_mcp_server.common.error_handling import ToolError

        with pytest.raises(ToolError) as exc_info:
            await sub_manager.list_subscriptions({"page": "not_a_number"})

        err = exc_info.value
        assert getattr(err, "field", None) == "page"
        # Structured envelope, no Pydantic URL leak
        assert "pydantic.dev" not in str(err)
        # Must not have reached the client
        mock_client.get_subscriptions.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_subscriptions_rejects_negative_page(self, sub_manager, mock_client):
        """Negative page surfaces as a structured 400 (not Pydantic / not 5xx)."""
        from src.revenium_mcp_server.common.error_handling import ToolError

        with pytest.raises(ToolError) as exc_info:
            await sub_manager.list_subscriptions({"page": -1})

        assert getattr(exc_info.value, "field", None) == "page"
        mock_client.get_subscriptions.assert_not_called()

    @pytest.mark.asyncio
    async def test_discover_products_rejects_string_page_with_structured_error(
        self, sub_manager, mock_client
    ):
        """discover_products: wrong-type page must raise structured ToolError before client call."""
        with pytest.raises(ToolError) as exc_info:
            await sub_manager.discover_products({"page": "not_a_number"})

        err = exc_info.value
        assert getattr(err, "field", None) == "page"
        assert "pydantic.dev" not in str(err)
        mock_client.get_products.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_supporting_data_rejects_string_page_with_structured_error(
        self, sub_manager, mock_client
    ):
        """get_supporting_data: wrong-type page must raise structured ToolError before client call."""
        with pytest.raises(ToolError) as exc_info:
            await sub_manager.get_supporting_data({"page": "not_a_number"})

        err = exc_info.value
        assert getattr(err, "field", None) == "page"
        assert "pydantic.dev" not in str(err)
        mock_client.get_organizations.assert_not_called()
        mock_client.get_products.assert_not_called()
        mock_client.get_subscribers.assert_not_called()
        mock_client.get_credentials.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_subscriptions_rejects_string_page_with_structured_error(
        self, sub_manager, mock_client
    ):
        """search_subscriptions: wrong-type page must raise structured ToolError before client call."""
        with pytest.raises(ToolError) as exc_info:
            await sub_manager.search_subscriptions({"page": "not_a_number"})

        err = exc_info.value
        assert getattr(err, "field", None) == "page"
        assert "pydantic.dev" not in str(err)
        mock_client.get_subscriptions.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_metrics_rejects_string_page_with_structured_error(self, mock_client):
        """SubscriptionAnalytics.get_metrics: wrong-type page must raise structured ToolError before client call."""
        from src.revenium_mcp_server.tools_decomposed.subscription_management import (
            SubscriptionAnalytics,
        )

        analytics = SubscriptionAnalytics(mock_client)

        with pytest.raises(ToolError) as exc_info:
            await analytics.get_metrics({"page": "not_a_number"})

        err = exc_info.value
        assert getattr(err, "field", None) == "page"
        assert "pydantic.dev" not in str(err)
        mock_client.get_subscriptions.assert_not_called()


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
    async def test_get_subscription_403_raises_not_found(self, sub_manager, mock_client):
        """BACK-2938: the platform answers 403 for an id that does not exist,
        and the raw "HTTP 403: Access Denied" read as a permissions problem."""
        mock_client.get_subscription_by_id = AsyncMock(
            side_effect=ReveniumAPIError(message="Access Denied", status_code=403)
        )

        with pytest.raises(ToolError) as exc_info:
            await sub_manager.get_subscription({"subscription_id": "jM7Bz8P"})

        assert exc_info.value.error_code == ErrorCodes.RESOURCE_NOT_FOUND
        assert "jM7Bz8P" in exc_info.value.message
        assert "not found" in exc_info.value.message.lower()
        assert "Access Denied" not in exc_info.value.message
        assert any("team-scoped" in s for s in exc_info.value.suggestions)

    @pytest.mark.asyncio
    async def test_get_subscription_500_propagates(self, sub_manager, mock_client):
        """A server failure is not evidence the subscription is missing."""
        mock_client.get_subscription_by_id = AsyncMock(
            side_effect=ReveniumAPIError(message="boom", status_code=500)
        )

        with pytest.raises(ReveniumAPIError):
            await sub_manager.get_subscription({"subscription_id": "sub1"})

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
# SubscriptionManager - Billing reads
# ===========================================================================


class TestSubscriptionManagerBilledAmount:
    """Test SubscriptionManager.get_billed_amount behavior."""

    @pytest.mark.asyncio
    async def test_returns_amount_billed(self, sub_manager, mock_client):
        mock_client.get_subscription_billed_amount = AsyncMock(
            return_value={"amountBilled": 42.5}
        )
        result = await sub_manager.get_billed_amount({"subscription_id": "sub1"})
        assert result["amountBilled"] == 42.5
        mock_client.get_subscription_billed_amount.assert_called_once_with("sub1")

    @pytest.mark.asyncio
    async def test_zero_billed_is_valid(self, sub_manager, mock_client):
        mock_client.get_subscription_billed_amount = AsyncMock(
            return_value={"amountBilled": 0.0}
        )
        result = await sub_manager.get_billed_amount({"subscription_id": "sub1"})
        assert result["amountBilled"] == 0.0

    @pytest.mark.asyncio
    async def test_missing_id_raises(self, sub_manager):
        with pytest.raises(ToolError) as exc_info:
            await sub_manager.get_billed_amount({})
        assert "subscription_id" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_non_numeric_amount_raises_not_silent_zero(self, sub_manager, mock_client):
        """A missing/non-numeric amountBilled is a contract failure, not a zero."""
        mock_client.get_subscription_billed_amount = AsyncMock(
            return_value={"amountBilled": None}
        )
        with pytest.raises(ToolError) as exc_info:
            await sub_manager.get_billed_amount({"subscription_id": "sub1"})
        assert "amountbilled" in str(exc_info.value).lower() or "unexpected" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_missing_field_raises(self, sub_manager, mock_client):
        mock_client.get_subscription_billed_amount = AsyncMock(return_value={})
        with pytest.raises(ToolError):
            await sub_manager.get_billed_amount({"subscription_id": "sub1"})

    @pytest.mark.asyncio
    async def test_404_raises_not_found(self, sub_manager, mock_client):
        mock_client.get_subscription_billed_amount = AsyncMock(
            side_effect=ReveniumAPIError(message="Not found", status_code=404)
        )
        with pytest.raises(ToolError) as exc_info:
            await sub_manager.get_billed_amount({"subscription_id": "bad"})
        assert "not found" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_403_raises_not_found(self, sub_manager, mock_client):
        mock_client.get_subscription_billed_amount = AsyncMock(
            side_effect=ReveniumAPIError(message="Forbidden", status_code=403)
        )
        with pytest.raises(ToolError) as exc_info:
            await sub_manager.get_billed_amount({"subscription_id": "other_team"})
        assert "not found" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_400_raises_validation_error(self, sub_manager, mock_client):
        mock_client.get_subscription_billed_amount = AsyncMock(
            side_effect=ReveniumAPIError(message="Bad request", status_code=400)
        )
        with pytest.raises(ToolError) as exc_info:
            await sub_manager.get_billed_amount({"subscription_id": "!!!"})
        assert "invalid" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_500_reraises(self, sub_manager, mock_client):
        mock_client.get_subscription_billed_amount = AsyncMock(
            side_effect=ReveniumAPIError(message="Server error", status_code=500)
        )
        with pytest.raises(ReveniumAPIError):
            await sub_manager.get_billed_amount({"subscription_id": "x"})


class TestSubscriptionManagerQuotaConsumed:
    """Test SubscriptionManager.get_quota_consumed behavior."""

    @pytest.mark.asyncio
    async def test_returns_limit_and_consumed(self, sub_manager, mock_client):
        mock_client.get_subscription_quota_consumed = AsyncMock(
            return_value={"limit": 1000, "consumed": 250}
        )
        result = await sub_manager.get_quota_consumed({"subscription_id": "sub1"})
        assert result["limit"] == 1000
        assert result["consumed"] == 250
        mock_client.get_subscription_quota_consumed.assert_called_once_with("sub1")

    @pytest.mark.asyncio
    async def test_zero_values_valid(self, sub_manager, mock_client):
        mock_client.get_subscription_quota_consumed = AsyncMock(
            return_value={"limit": 0, "consumed": 0}
        )
        result = await sub_manager.get_quota_consumed({"subscription_id": "sub1"})
        assert result["limit"] == 0
        assert result["consumed"] == 0

    @pytest.mark.asyncio
    async def test_missing_id_raises(self, sub_manager):
        with pytest.raises(ToolError) as exc_info:
            await sub_manager.get_quota_consumed({})
        assert "subscription_id" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_non_numeric_raises_not_silent_zero(self, sub_manager, mock_client):
        mock_client.get_subscription_quota_consumed = AsyncMock(
            return_value={"limit": None, "consumed": None}
        )
        with pytest.raises(ToolError):
            await sub_manager.get_quota_consumed({"subscription_id": "sub1"})

    @pytest.mark.asyncio
    async def test_partial_field_raises(self, sub_manager, mock_client):
        mock_client.get_subscription_quota_consumed = AsyncMock(
            return_value={"limit": 100}
        )
        with pytest.raises(ToolError):
            await sub_manager.get_quota_consumed({"subscription_id": "sub1"})

    @pytest.mark.asyncio
    async def test_404_raises_not_found(self, sub_manager, mock_client):
        mock_client.get_subscription_quota_consumed = AsyncMock(
            side_effect=ReveniumAPIError(message="Not found", status_code=404)
        )
        with pytest.raises(ToolError) as exc_info:
            await sub_manager.get_quota_consumed({"subscription_id": "bad"})
        assert "not found" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_403_raises_not_found(self, sub_manager, mock_client):
        mock_client.get_subscription_quota_consumed = AsyncMock(
            side_effect=ReveniumAPIError(message="Forbidden", status_code=403)
        )
        with pytest.raises(ToolError) as exc_info:
            await sub_manager.get_quota_consumed({"subscription_id": "other"})
        assert "not found" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_500_reraises(self, sub_manager, mock_client):
        mock_client.get_subscription_quota_consumed = AsyncMock(
            side_effect=ReveniumAPIError(message="Server error", status_code=500)
        )
        with pytest.raises(ReveniumAPIError):
            await sub_manager.get_quota_consumed({"subscription_id": "x"})


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
    async def test_create_with_only_a_name_is_refused_not_given_the_first_product(
        self, sub_manager, mock_client
    ):
        """A name alone used to bill the first product to an invented address."""
        mock_client.get_products = AsyncMock(return_value={})
        mock_client._extract_embedded_data.return_value = [{"id": "auto_prod_1"}]

        with pytest.raises(ToolError) as exc_info:
            await sub_manager.create_subscription({"name": "Auto Sub"})

        assert exc_info.value.field == "subscription_data"
        mock_client.get_products.assert_not_awaited()
        mock_client.create_subscription.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_create_auto_generate_no_products_raises(self, sub_manager, mock_client):
        """A name alone is refused before any product is read."""
        mock_client.get_products = AsyncMock(return_value={})
        mock_client._extract_embedded_data.return_value = []

        with pytest.raises(ToolError):
            await sub_manager.create_subscription({"name": "No Products Sub"})
        mock_client.get_products.assert_not_awaited()


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

    @pytest.mark.asyncio
    async def test_update_hint_lists_only_fields_the_platform_accepts(self, sub_manager):
        with pytest.raises(ToolError) as exc_info:
            await sub_manager.update_subscription({"subscription_id": "sub1"})

        hint = exc_info.value.examples["updatable_fields"]
        assert "status" not in hint
        assert "metadata" not in hint
        assert "expiration" in hint

    @pytest.mark.asyncio
    async def test_update_with_status_is_refused_and_names_the_expiration_route(
        self, sub_manager
    ):
        """The platform write contract has no status, so a "pause" used to be PUT,
        ignored and reported as a success."""
        sub_manager.update_handler.update_with_merge = AsyncMock(return_value={"id": "sub1"})

        with pytest.raises(ToolError) as exc_info:
            await sub_manager.update_subscription(
                {
                    "subscription_id": "sub1",
                    "subscription_data": {"status": "paused", "name": "Renamed"},
                }
            )

        assert exc_info.value.field == "status"
        assert "expiration" in exc_info.value.message
        sub_manager.update_handler.update_with_merge.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "subscription_data, unknown",
        [
            ({"description": "x"}, "description"),
            ({"name": "Renamed", "description": "x"}, "description"),
            ({"product_id": "p2"}, "product_id"),
            ({"updated": "2026-01-01"}, "updated"),
            ({"quotaNotificationThreshold": 0.75}, "quotaNotificationThreshold"),
        ],
    )
    async def test_update_with_a_field_the_write_contract_lacks_is_refused(
        self, sub_manager, mock_client, subscription_data, unknown
    ):
        """The platform drops a field its write contract lacks and still answers 200,
        so the update used to report success for a value that was never stored."""
        sub_manager.update_handler.update_with_merge = AsyncMock(return_value={"id": "sub1"})

        with pytest.raises(ToolError) as exc_info:
            await sub_manager.update_subscription(
                {"subscription_id": "sub1", "subscription_data": subscription_data}
            )

        assert exc_info.value.field == unknown
        assert "nothing was changed" in exc_info.value.message
        hint = exc_info.value.examples["updatable_fields"]
        assert "expiration" in hint and "productId" in hint
        mock_client.get_subscription_by_id.assert_not_awaited()
        sub_manager.update_handler.update_with_merge.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_refusal_names_every_field_the_platform_would_not_store(
        self, sub_manager, mock_client
    ):
        sub_manager.update_handler.update_with_merge = AsyncMock(return_value={"id": "sub1"})

        with pytest.raises(ToolError) as exc_info:
            await sub_manager.update_subscription(
                {
                    "subscription_id": "sub1",
                    "subscription_data": {"name": "R", "description": "x", "product_id": "p"},
                }
            )

        assert exc_info.value.field == "description"
        assert exc_info.value.value == ["description", "product_id"]
        mock_client.get_subscription_by_id.assert_not_awaited()
        sub_manager.update_handler.update_with_merge.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("subscription_data", [[{"name": "R"}], "name=R"])
    async def test_update_whose_data_is_not_an_object_is_refused(
        self, sub_manager, mock_client, subscription_data
    ):
        sub_manager.update_handler.update_with_merge = AsyncMock(return_value={"id": "sub1"})

        with pytest.raises(ToolError) as exc_info:
            await sub_manager.update_subscription(
                {"subscription_id": "sub1", "subscription_data": subscription_data}
            )

        assert exc_info.value.field == "subscription_data"
        sub_manager.update_handler.update_with_merge.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "subscription_data",
        [
            {"name": "Renamed"},
            {"expiration": "2027-01-01T00:00:00Z"},
            {"subscriberId": "u1"},
            {"clientEmailAddress": "ops@company.com"},
        ],
    )
    async def test_update_with_write_contract_fields_reaches_the_platform(
        self, sub_manager, subscription_data
    ):
        """Guard: the refusal must not block a field the platform stores."""
        sub_manager.update_handler.update_with_merge = AsyncMock(return_value={"id": "sub1"})
        sub_manager.update_config_factory.get_config = MagicMock(return_value={})

        await sub_manager.update_subscription(
            {"subscription_id": "sub1", "subscription_data": subscription_data}
        )

        sub_manager.update_handler.update_with_merge.assert_awaited_once()

    def test_write_field_set_matches_the_spec(self):
        from src.revenium_mcp_server.tools_decomposed.subscription_management import (
            _SUBSCRIPTION_WRITE_FIELDS,
        )

        spec_path = (
            Path(__file__).resolve().parents[2] / "specs" / "openapi" / "hypercurrent.json"
        )
        if not spec_path.exists():
            pytest.skip(
                "specs/openapi/ is internal-only and not part of the public export "
                "(see public-allowlist-mcp.txt); the spec check runs in the internal repo"
            )
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        properties = spec["components"]["schemas"]["SubscriptionResource_Write"]["properties"]
        writable = {name for name, prop in properties.items() if not prop.get("readOnly")}

        assert _SUBSCRIPTION_WRITE_FIELDS == writable | {"subscriberId"}


# ===========================================================================
# SubscriptionManager - Cancel/Delete
# ===========================================================================


class TestSubscriptionManagerDelete:
    """Test delete subscription behavior."""

    @pytest.mark.asyncio
    async def test_delete_missing_id_raises(self, sub_manager):
        """Delete without subscription_id raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await sub_manager.delete_subscription({})

        assert "subscription_id" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_delete_calls_the_delete_endpoint(self, sub_manager, mock_client):
        mock_client.delete_subscription.return_value = {"deleted": True}

        await sub_manager.delete_subscription({"subscription_id": "sub_d"})

        mock_client.delete_subscription.assert_called_once_with("sub_d")


# ===========================================================================
# SubscriptionManager - Search
# ===========================================================================


class TestSubscriptionManagerSearch:
    """SubscriptionManager.search_subscriptions forwards one term and reports the platform total.

    BACK-4709: rows are platform-shaped; they carry no `customer` or
    `subscriber` key, which the old client-side filter read.
    """

    @pytest.mark.asyncio
    async def test_search_sends_the_query_term(self, sub_manager, mock_client):
        mock_client._extract_embedded_data.return_value = [
            {"id": "s1", "name": "Premium Sub", "subscriberEmail": "a@b.com", "product": None},
        ]
        mock_client._extract_pagination_info.return_value = {"totalElements": 1}

        result = await sub_manager.search_subscriptions({"search_query": "premium"})

        mock_client.get_subscriptions.assert_awaited_once_with(page=0, size=50, query="premium")
        assert result["total_found"] == 1
        assert result["subscriptions"][0]["matched_on"] == ["name"]

    @pytest.mark.asyncio
    async def test_search_by_customer_name_matches_the_organization(self, sub_manager, mock_client):
        mock_client._extract_embedded_data.return_value = [
            {"id": "s1", "name": "Sub", "organization": {"id": "o1", "name": None, "label": "Acme Corp"}},
        ]
        mock_client._extract_pagination_info.return_value = {"totalElements": 1}

        result = await sub_manager.search_subscriptions({"customer_name": "acme"})

        mock_client.get_subscriptions.assert_awaited_once_with(page=0, size=50, query="acme")
        assert result["subscriptions"][0]["matched_on"] == ["organization.label"]
        assert result["exact_field_matches_on_page"] == 1

    @pytest.mark.asyncio
    async def test_search_by_product_name_matches_the_product(self, sub_manager, mock_client):
        mock_client._extract_embedded_data.return_value = [
            {"id": "s1", "name": "Sub", "product": {"id": "p1", "label": "Pro Plan"}},
        ]
        mock_client._extract_pagination_info.return_value = {"totalElements": 1}

        result = await sub_manager.search_subscriptions({"product_name": "pro plan"})

        mock_client.get_subscriptions.assert_awaited_once_with(page=0, size=50, query="pro plan")
        assert result["subscriptions"][0]["matched_on"] == ["product.label"]
        assert result["exact_field_matches_on_page"] == 1

    @pytest.mark.asyncio
    async def test_search_no_match_returns_empty(self, sub_manager, mock_client):
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {"totalElements": 0}

        result = await sub_manager.search_subscriptions({"search_query": "nonexistent"})

        assert result["total_found"] == 0
        assert result["returned"] == 0
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
    @pytest.mark.parametrize("page_info, row_count, page, heading, total", LIST_HEADING_CASES)
    async def test_list_heading_counts_the_page_against_the_platform_total(
        self, sub_mgmt, page_info, row_count, page, heading, total
    ):
        """The heading counts the page against the platform total, not the rows alone."""
        with patch.object(sub_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_gc.return_value = mock_client
            mock_client.get_subscriptions = AsyncMock(return_value={})
            mock_client._extract_embedded_data.return_value = rows(row_count)
            mock_client._extract_pagination_info.return_value = page_info

            result = await sub_mgmt.handle_action("list", {"page": page, "size": 20})

        shown_heading, body = heading_and_body(result[0].text)
        assert shown_heading == heading.format(noun="subscriptions")
        assert body["total_records"] == total
        assert body["page"] == page
        assert body["total_found"] == row_count

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
        """BACK-2937: the missing-name refusal raises so isError is set."""
        with patch.object(sub_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_gc.return_value = mock_client

            with pytest.raises(ToolError) as exc_info:
                await sub_mgmt.handle_action("create", {"subscription_data": {}})

        assert "Missing Required Field" in exc_info.value.message
        assert exc_info.value.field == "name"

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

    @pytest.mark.asyncio
    async def test_get_billed_amount_action_routes_and_renders(self, sub_mgmt):
        """get_billed_amount routes and renders the billed amount."""
        with patch.object(sub_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_gc.return_value = mock_client
            mock_client.get_subscription_billed_amount = AsyncMock(
                return_value={"amountBilled": 12.75}
            )
            result = await sub_mgmt.handle_action(
                "get_billed_amount", {"subscription_id": "sub1"}
            )
        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
        assert "12.75" in result[0].text

    @pytest.mark.asyncio
    async def test_get_quota_consumed_action_routes_and_renders(self, sub_mgmt):
        """get_quota_consumed routes and renders limit/consumed."""
        with patch.object(sub_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_gc.return_value = mock_client
            mock_client.get_subscription_quota_consumed = AsyncMock(
                return_value={"limit": 1000, "consumed": 250}
            )
            result = await sub_mgmt.handle_action(
                "get_quota_consumed", {"subscription_id": "sub1"}
            )
        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
        assert "1000" in result[0].text
        assert "250" in result[0].text

    @pytest.mark.asyncio
    async def test_billing_reads_in_supported_actions(self, sub_mgmt):
        actions = await sub_mgmt._get_supported_actions()
        assert "get_billed_amount" in actions
        assert "get_quota_consumed" in actions

    @pytest.mark.asyncio
    async def test_billing_reads_in_structured_capabilities(self, sub_mgmt):
        caps = await sub_mgmt._get_tool_capabilities()
        all_params = {k for c in caps for k in c.parameters}
        assert "get_billed_amount" in all_params
        assert "get_quota_consumed" in all_params

    @pytest.mark.asyncio
    async def test_get_metrics_advertises_only_arguments_it_reads(self, sub_mgmt):
        """get_metrics reads filters, page and size; nothing reads a date range."""
        caps = await sub_mgmt._get_tool_capabilities()
        advertised = {
            name
            for capability in caps
            for name in capability.parameters.get("get_metrics", {})
        }
        examples = [
            example
            for capability in caps
            for example in capability.examples
            if "get_metrics(" in example
        ]

        assert advertised
        assert advertised <= {"filters", "page", "size"}
        assert examples
        assert not [example for example in examples if "date_range" in example]


# ===========================================================================
# SubscriptionValidator tests
# ===========================================================================


class TestListSubscriptionsRejectsFloatPageNoLeak:
    """BACK-1270 / item #5 — float page must reject without leaking Pydantic."""

    @pytest.mark.asyncio
    async def test_float_page_returns_clean_error(self, sub_manager):
        from tests.unit._helpers_no_framework_leak import assert_no_framework_leak
        with pytest.raises(ToolError) as exc:
            await sub_manager.list_subscriptions({"page": 3.7, "size": 20})
        assert exc.value.field == "page"
        assert_no_framework_leak(exc.value.message)
        assert_no_framework_leak(str(exc.value.suggestions))




# ===========================================================================
# BACK-1311 — Sanitizer integration through SubscriptionManager methods
# ===========================================================================


class TestListSubscriptionsSanitizesNestedProductSentinels:
    """Audit finding A.2 — backend-returned nested product placeholders must
    be normalized by the time the manager returns."""

    @pytest.mark.asyncio
    async def test_list_sanitizes_nested_product_undefined(self, sub_manager, mock_client):
        leaky_subscription = {
            "id": "3ByYBQK",
            "resourceType": "subscription",
            "label": "valid@example.com",
            "product": {
                "id": "jM7Bz8P",
                "resourceType": "undefined",
                "label": "undefined",
                "created": "4/2/26, 1:29 PM",
                "updated": "4/2/26, 1:29 PM",
                "_links": {"self": {"href": "/profitstream/v2/api/products/jM7Bz8P"}},
            },
        }
        mock_client._extract_embedded_data.return_value = [leaky_subscription]
        mock_client._extract_pagination_info.return_value = {}

        result = await sub_manager.list_subscriptions({})

        product = result["subscriptions"][0]["product"]
        assert product["resourceType"] == "product"  # inferred from path
        assert product["label"] is None
        assert product["created"] is None
        assert product["updated"] is None
        # Identity preserved
        assert product["id"] == "jM7Bz8P"
        assert product["_links"]["self"]["href"] == "/profitstream/v2/api/products/jM7Bz8P"


class TestGetSubscriptionSanitizesNestedProductSentinels:
    @pytest.mark.asyncio
    async def test_get_sanitizes_nested_product(self, sub_manager, mock_client):
        leaky = {
            "id": "3ByYBQK",
            "resourceType": "subscription",
            "product": {
                "id": "jM7Bz8P",
                "resourceType": "undefined",
                "label": "undefined",
                "created": "4/2/26, 1:29 PM",
                "_links": {"self": {"href": "/profitstream/v2/api/products/jM7Bz8P"}},
            },
        }
        mock_client.get_subscription_by_id = AsyncMock(return_value=leaky)

        result = await sub_manager.get_subscription({"subscription_id": "3ByYBQK"})

        product = result["product"]
        assert product["resourceType"] == "product"
        assert product["label"] is None
        assert product["created"] is None


class TestSearchSubscriptionsSanitizesNestedProductSentinels:
    @pytest.mark.asyncio
    async def test_search_sanitizes_nested_product(self, sub_manager, mock_client):
        leaky = {
            "id": "3ByYBQK",
            "name": "match-on-name",
            "resourceType": "subscription",
            "product": {
                "id": "jM7Bz8P",
                "resourceType": "undefined",
                "label": "undefined",
                "created": "4/2/26, 1:29 PM",
                "_links": {"self": {"href": "/profitstream/v2/api/products/jM7Bz8P"}},
            },
        }
        mock_client._extract_embedded_data.return_value = [leaky]
        mock_client._extract_pagination_info.return_value = {}

        result = await sub_manager.search_subscriptions({"search_query": "match"})

        assert len(result["subscriptions"]) == 1
        product = result["subscriptions"][0]["product"]
        assert product["resourceType"] == "product"
        assert product["label"] is None
        assert product["created"] is None


class TestCreateSubscriptionSanitizesNestedProductSentinels:
    @pytest.mark.asyncio
    async def test_create_sanitizes_nested_product(self, sub_manager, mock_client):
        leaky = {
            "id": "3ByYBQK",
            "resourceType": "subscription",
            "product": {
                "id": "jM7Bz8P",
                "resourceType": "undefined",
                "label": "undefined",
                "created": "4/2/26, 1:29 PM",
                "_links": {"self": {"href": "/profitstream/v2/api/products/jM7Bz8P"}},
            },
        }
        mock_client.create_subscription = AsyncMock(return_value=leaky)
        # Bypass discover_products / context7 paths — pass subscription_data directly
        result = await sub_manager.create_subscription({
            "subscription_data": {
                "name": "test-sub",
                "product_id": "jM7Bz8P",
                "clientEmailAddress": "test@example.com",
            },
        })
        product = result["product"]
        assert product["resourceType"] == "product"
        assert product["label"] is None
        assert product["created"] is None


class TestSubscriptionsPaginationSafeInteger:
    """Values beyond 2^53 must hit the safe-integer guard, not the
    bounds check — and the float-corrupted value must not be echoed back."""

    def test_size_beyond_safe_range_rejected_without_echo(self):
        from src.revenium_mcp_server.tools_decomposed.subscription_management import (
            _validate_subscriptions_pagination,
        )

        corrupted = int(float(2**63))
        with pytest.raises(ToolError) as exc_info:
            _validate_subscriptions_pagination(page=0, size=corrupted)
        msg = str(exc_info.value)
        assert "exceeds safe integer range" in msg
        assert str(corrupted) not in msg

    def test_page_beyond_safe_range_rejected_without_echo(self):
        from src.revenium_mcp_server.tools_decomposed.subscription_management import (
            _validate_subscriptions_pagination,
        )

        corrupted = int(float(2**63))
        with pytest.raises(ToolError) as exc_info:
            _validate_subscriptions_pagination(page=corrupted, size=20)
        msg = str(exc_info.value)
        assert "exceeds safe integer range" in msg
        assert str(corrupted) not in msg


class TestSubscriptionDryRunProductParity:
    """dry_run must reject a nonexistent product_id like live create does, on
    both create modes. BACK-2249 fixed only auto_generate=False; BACK-5092
    found the default auto_generate=True preview still approving a product
    the backend rejects with 'Couldn't decode'."""

    @staticmethod
    def _missing_product(product_id):
        """The 400 the platform answers for an id it cannot decode."""
        return ReveniumAPIError(
            "Invalid Product ID",
            status_code=400,
            response_data={"error_data": f"Failed to decode hashed id: {product_id}"},
        )

    @staticmethod
    async def _preview(sub_mgmt, sub_manager, product_id, auto_generate):
        return await sub_mgmt._handle_crud_actions(
            "create",
            {
                "subscription_data": {
                    "name": "probe",
                    "product_id": product_id,
                    "clientEmailAddress": "a@b.io",
                },
                "auto_generate": auto_generate,
                "dry_run": True,
            },
            sub_manager,
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("auto_generate", [True, False])
    async def test_dry_run_rejects_nonexistent_product(
        self, sub_mgmt, sub_manager, mock_client, auto_generate
    ):
        mock_client.get_product_by_id = AsyncMock(
            side_effect=self._missing_product("NONEXISTENT_PROD")
        )
        with pytest.raises(ToolError) as exc:
            await self._preview(sub_mgmt, sub_manager, "NONEXISTENT_PROD", auto_generate)
        assert exc.value.field == "product_id"
        assert exc.value.value == "NONEXISTENT_PROD"
        assert exc.value.error_code == ErrorCodes.VALIDATION_ERROR
        assert "Dry Run Preview" not in exc.value.message
        assert "NONEXISTENT_PROD" in exc.value.message
        assert "\u2014" not in exc.value.message
        mock_client.get_product_by_id.assert_awaited_once_with("NONEXISTENT_PROD")

    @pytest.mark.asyncio
    async def test_both_modes_refuse_a_nonexistent_product_with_the_same_text(
        self, sub_mgmt, sub_manager, mock_client
    ):
        mock_client.get_product_by_id = AsyncMock(side_effect=self._missing_product("ZZZZZZZ"))
        messages = []
        for auto_generate in (True, False):
            with pytest.raises(ToolError) as exc:
                await self._preview(sub_mgmt, sub_manager, "ZZZZZZZ", auto_generate)
            messages.append(exc.value.message)
        assert messages[0] == messages[1]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("auto_generate", [True, False])
    async def test_dry_run_accepts_existing_product(
        self, sub_mgmt, sub_manager, mock_client, auto_generate
    ):
        mock_client.get_product_by_id = AsyncMock(return_value={"id": "prod_ok", "name": "P"})
        result = await self._preview(sub_mgmt, sub_manager, "prod_ok", auto_generate)
        assert "Dry Run Preview" in result[0].text
        mock_client.get_product_by_id.assert_awaited_once_with("prod_ok")
        mock_client.create_subscription.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("auto_generate", [True, False])
    async def test_dry_run_refuses_a_product_the_platform_answers_404_for(
        self, sub_mgmt, sub_manager, mock_client, auto_generate
    ):
        mock_client.get_product_by_id = AsyncMock(
            side_effect=ReveniumAPIError("Product not found", status_code=404)
        )
        with pytest.raises(ToolError) as exc:
            await self._preview(sub_mgmt, sub_manager, "gone", auto_generate)
        assert exc.value.field == "product_id"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("auto_generate", [True, False])
    @pytest.mark.parametrize(
        "failure",
        [
            ReveniumAPIError("Request failed: GET /products timed out"),
            ReveniumAPIError("The platform asked to wait 30 seconds", status_code=429),
            ReveniumAPIError("HTTP 500: upstream", status_code=500),
        ],
        ids=["transport", "lockout", "server-error"],
    )
    async def test_a_failed_product_read_is_not_reported_as_a_missing_product(
        self, sub_mgmt, sub_manager, mock_client, auto_generate, failure
    ):
        mock_client.get_product_by_id = AsyncMock(side_effect=failure)
        with pytest.raises(ReveniumAPIError) as exc:
            await self._preview(sub_mgmt, sub_manager, "prod_ok", auto_generate)
        assert exc.value is failure
        mock_client.create_subscription.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("auto_generate", [True, False])
    async def test_dry_run_lets_unexpected_errors_propagate(
        self, sub_mgmt, sub_manager, mock_client, auto_generate
    ):
        """Only API rejections become the dry-run validation message;
        transport/programming errors must not be echoed into user text."""
        mock_client.get_product_by_id = AsyncMock(side_effect=RuntimeError("socket exploded"))
        with pytest.raises(RuntimeError):
            await self._preview(sub_mgmt, sub_manager, "prod_x", auto_generate)

    @pytest.mark.asyncio
    async def test_expert_preview_refuses_a_malformed_invoice_address(
        self, sub_mgmt, sub_manager, mock_client
    ):
        mock_client.get_product_by_id = AsyncMock(return_value={"id": "prod_ok"})

        with pytest.raises(ToolError) as exc:
            await sub_mgmt._handle_crud_actions(
                "create",
                {
                    "subscription_data": {
                        "name": "probe",
                        "product_id": "prod_ok",
                        "clientEmailAddress": "bob@company",
                    },
                    "auto_generate": False,
                    "dry_run": True,
                },
                sub_manager,
            )

        assert exc.value.field == "clientEmailAddress"
        mock_client.create_subscription.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_auto_generate_preview_refuses_a_malformed_invoice_address(
        self, sub_mgmt, sub_manager, mock_client
    ):
        with pytest.raises(ToolError) as exc:
            await sub_mgmt._handle_crud_actions(
                "create",
                {
                    "subscription_data": {
                        "name": "probe",
                        "product_id": "prod_ok",
                        "clientEmailAddress": "bob@company",
                    },
                    "auto_generate": True,
                    "dry_run": True,
                },
                sub_manager,
            )

        assert exc.value.field == "clientEmailAddress"
        mock_client.create_subscription.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_preview_shows_the_trimmed_invoice_address(
        self, sub_mgmt, sub_manager, mock_client
    ):
        mock_client.get_product_by_id = AsyncMock(return_value={"id": "prod_ok"})

        result = await sub_mgmt._handle_crud_actions(
            "create",
            {
                "subscription_data": {
                    "name": "probe",
                    "product_id": "prod_ok",
                    "clientEmailAddress": "  ops@company.com  ",
                },
                "auto_generate": False,
                "dry_run": True,
            },
            sub_manager,
        )

        text = result[0].text
        assert "Dry Run Preview" in text
        assert '"clientEmailAddress": "ops@company.com"' in text

    @pytest.mark.asyncio
    async def test_validate_refuses_a_malformed_invoice_address(self, sub_mgmt, mock_client):
        with patch.object(
            SubscriptionManagement, "get_client", AsyncMock(return_value=mock_client)
        ):
            with pytest.raises(ToolError) as exc:
                await sub_mgmt.handle_action(
                    "validate",
                    {
                        "subscription_data": {
                            "name": "probe",
                            "productId": "prod_ok",
                            "clientEmailAddress": "bob@company",
                        }
                    },
                )

        assert exc.value.field == "clientEmailAddress"


# ===========================================================================
# BACK-2944 - clientEmailAddress is format-validated before the platform call
# ===========================================================================


class TestClientEmailAddressValidation:
    """The invoice address is documented as an email address, so enforce that locally.

    Before this, a create with clientEmailAddress "not-an-email" reached the platform,
    which derived a client user labelled "not-an-email" from it. The platform has no
    opinion on the format, so the check has to be MCP-side.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "bad_email",
        [
            "not-an-email",
            "missing-at-sign.com",
            "no-domain@",
            "@no-local-part.com",
            "spaces in@example.com",
            "trailing@dot.",
            12345,
        ],
    )
    async def test_create_rejects_a_non_email_invoice_address(
        self, sub_manager, mock_client, bad_email
    ):
        """create raises a structured validation error and never calls the platform."""
        with pytest.raises(ToolError) as exc:
            await sub_manager.create_subscription(
                {
                    "subscription_data": {
                        "name": "mcp-test-bad-email",
                        "productId": "prod_x",
                        "clientEmailAddress": bad_email,
                    }
                }
            )

        assert exc.value.field == "clientEmailAddress"
        assert "valid email address" in exc.value.message
        assert exc.value.suggestions, "the error should tell the caller how to fix it"
        mock_client.create_subscription.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "good_email",
        [
            "user@company.com",
            "first.last+tag@sub.domain.co.uk",
            "  padded@example.com  ",
        ],
    )
    async def test_create_accepts_a_real_email_address(
        self, sub_manager, mock_client, good_email
    ):
        """A well-formed address reaches the platform trimmed of surrounding whitespace."""
        mock_client.create_subscription.return_value = {"id": "sub_1"}

        result = await sub_manager.create_subscription(
            {
                "subscription_data": {
                    "name": "mcp-test-good-email",
                    "productId": "prod_x",
                    "clientEmailAddress": good_email,
                }
            }
        )

        assert result["id"] == "sub_1"
        sent = mock_client.create_subscription.await_args.args[0]
        assert sent["clientEmailAddress"] == good_email.strip()

    @pytest.mark.asyncio
    async def test_create_simple_rejects_a_non_email_invoice_address(
        self, sub_manager, mock_client
    ):
        """The create_simple path validates too, before any product lookup."""
        with pytest.raises(ToolError) as exc:
            await sub_manager.create_simple(
                {"product_id": "prod_x", "clientEmailAddress": "not-an-email"}
            )

        assert exc.value.field == "clientEmailAddress"
        mock_client.create_subscription.assert_not_awaited()

    def test_missing_address_is_left_to_the_required_field_check(self, sub_manager):
        """An absent value is not this check's business - it has its own better message."""
        from src.revenium_mcp_server.tools_decomposed.subscription_management import (
            _validate_client_email_address,
        )

        _validate_client_email_address(None)
        _validate_client_email_address("")

    @pytest.mark.asyncio
    async def test_create_from_text_rejects_a_non_email_invoice_address(
        self, sub_manager, mock_client
    ):
        """The natural-language path validates before it looks the product up."""
        with pytest.raises(ToolError) as exc:
            await sub_manager.create_from_text(
                {
                    "text": "Monthly subscription for the ops team",
                    "product_id": "prod_x",
                    "clientEmailAddress": "not-an-email",
                }
            )

        assert exc.value.field == "clientEmailAddress"
        assert "valid email address" in exc.value.message
        mock_client.create_subscription.assert_not_awaited()
        mock_client.get_product_by_id.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_create_from_text_rejects_a_bad_address_pulled_from_the_text(
        self, sub_manager, mock_client
    ):
        """An address the analyzer extracts from free text is checked the same way."""
        with patch.object(
            sub_manager,
            "_analyze_subscription_text",
            AsyncMock(
                return_value={"product_id": "prod_x", "clientEmailAddress": "not-an-email"}
            ),
        ):
            with pytest.raises(ToolError) as exc:
                await sub_manager.create_from_text(
                    {"text": "Subscribe not-an-email to the basic plan"}
                )

        assert exc.value.field == "clientEmailAddress"
        mock_client.create_subscription.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_create_from_text_still_accepts_a_real_address(self, sub_manager, mock_client):
        """A well-formed address reaches the platform with the address unchanged."""
        mock_client.get_product_by_id = AsyncMock(
            return_value={"id": "prod_x", "name": "Basic", "published": True}
        )
        mock_client.create_subscription.return_value = {"id": "sub_nl"}

        result = await sub_manager.create_from_text(
            {
                "text": "Monthly subscription for the ops team",
                "product_id": "prod_x",
                "clientEmailAddress": "ops@company.com",
            }
        )

        assert result["id"] == "sub_nl"
        sent = mock_client.create_subscription.await_args.args[0]
        assert sent["clientEmailAddress"] == "ops@company.com"

    def test_credentials_path_rejects_a_non_email_invoice_address(self, mock_client):
        """The create_with_credentials path builds its own payload and is guarded too."""
        mock_client.create_credential = AsyncMock()
        mgr = SubscriptionHierarchyManager(mock_client)

        with pytest.raises(ToolError) as exc:
            mgr._prepare_credentials_subscription_data(
                {"productId": "prod_x", "clientEmailAddress": "not-an-email"}, {}
            )

        assert exc.value.field == "clientEmailAddress"
        mock_client.create_subscription.assert_not_awaited()
        mock_client.create_credential.assert_not_awaited()

    def test_credentials_path_trims_a_padded_address(self, mock_client):
        """The address the credentials flow forwards is the trimmed one."""
        mgr = SubscriptionHierarchyManager(mock_client)

        prepared = mgr._prepare_credentials_subscription_data(
            {"productId": "prod_x"}, {"clientEmailAddress": "  ops@company.com  "}
        )

        assert prepared["clientEmailAddress"] == "ops@company.com"

    @pytest.mark.asyncio
    async def test_update_rejects_a_non_email_invoice_address(self, sub_manager, mock_client):
        """An update can rewrite the billing identity, so it is checked too."""
        with pytest.raises(ToolError) as exc:
            await sub_manager.update_subscription(
                {
                    "subscription_id": "sub_1",
                    "subscription_data": {"clientEmailAddress": "not-an-email"},
                }
            )

        assert exc.value.field == "clientEmailAddress"

    @pytest.mark.asyncio
    async def test_update_that_does_not_touch_the_address_is_unaffected(
        self, sub_manager, mock_client
    ):
        """A partial update naming other fields never reaches the email check."""
        sub_manager.update_handler = MagicMock()
        sub_manager.update_handler.update_with_merge = AsyncMock(
            return_value={"id": "sub_1", "name": "Renamed"}
        )

        result = await sub_manager.update_subscription(
            {"subscription_id": "sub_1", "subscription_data": {"name": "Renamed"}}
        )

        assert result["name"] == "Renamed"


# ===========================================================================
# Every advertised action is routed (BACK-4709)
# ===========================================================================


class _Unrouted(Exception):
    """Raised in place of the unknown-action refusal so a test can see it was reached."""


def _response_text(response):
    return "\n".join(item.text for item in response if isinstance(item, TextContent))


class TestEveryListedSubscriptionActionIsRouted:
    """The supported-actions list names only actions the dispatcher routes."""

    @pytest.mark.asyncio
    async def test_no_supported_action_reaches_the_unknown_action_refusal(self):
        tool = SubscriptionManagement()
        client = create_autospec(ReveniumClient, instance=True)
        unrouted = []

        with patch.object(tool, "get_client", new_callable=AsyncMock, return_value=client), \
                patch.object(tool, "_handle_unknown_action", side_effect=_Unrouted):
            for action in await tool._get_supported_actions():
                try:
                    await tool.handle_action(action, {})
                except _Unrouted:
                    unrouted.append(action)
                except Exception:
                    # Empty arguments make most actions refuse; only the
                    # unknown-action refusal means the action was never routed.
                    pass

        assert unrouted == []

    @pytest.mark.asyncio
    async def test_removed_create_shortcuts_are_not_advertised(self):
        tool = SubscriptionManagement()
        client = create_autospec(ReveniumClient, instance=True)
        texts = []

        with patch.object(tool, "get_client", new_callable=AsyncMock, return_value=client):
            for action in ("get_tool_metadata", "get_agent_summary", "get_capabilities"):
                texts.append(_response_text(await tool.handle_action(action, {})))
            with pytest.raises(ToolError) as exc:
                await tool.handle_action("no_such_action", {})

        texts.extend(await tool._get_quick_start_guide())
        texts.append(exc.value.message)
        texts.append(json.dumps(exc.value.examples))
        advertised = "\n".join(texts)

        assert "create_simple" not in advertised
        assert "create_from_text" not in advertised


# ===========================================================================
# search_subscriptions uses the platform search (BACK-4709)
# ===========================================================================


def _subscription_rows():
    """Platform-shaped subscription rows: no `subscriber` or `customer` key."""
    return [
        {
            "id": "3Byq3Aj",
            "name": "Gold monthly",
            "subscriberEmail": "jane@acme.com",
            "clientEmailAddress": "billing@acme.com",
            "organization": {"id": "GjbeEne", "name": None, "label": "Engineering"},
            "product": {"id": "p1", "name": "Gold", "label": "Gold"},
        },
        {
            "id": "jM7KJAK",
            "name": "Trial for jane@acme.com",
            "subscriberEmail": "bob@acme.com",
            "clientEmailAddress": "bob@acme.com",
            "organization": {"id": "6oyYXe8", "name": None, "label": "UNCLASSIFIED"},
            "product": None,
        },
    ]


def _subscriptions_answer(rows, page=None):
    """Answer the subscription list with `rows`; fail any other request."""
    page = page if page is not None else {"size": 50, "totalElements": 5, "totalPages": 1, "number": 0}

    def answer(method, url, params):
        if method == "GET" and url.endswith("/profitstream/v2/api/subscriptions"):
            return {"_embedded": {"subscriptionResourceList": rows}, "page": page}
        raise AssertionError(f"unexpected {method} {url}")

    return answer


class TestSearchSubscriptionsUsesPlatformSearch:
    """The search sends its one term as the platform `query` and reports the platform total."""

    @pytest.mark.asyncio
    async def test_email_search_sends_the_platform_query_and_reports_its_total(self, monkeypatch):
        rows = _subscription_rows()
        client, requests = recording_client(monkeypatch, _subscriptions_answer(rows))

        result = await SubscriptionManager(client).search_subscriptions(
            {"subscriber_email": "jane@acme.com"}
        )

        assert len(requests) == 1
        assert requests[0]["params"]["query"] == "jane@acme.com"
        assert requests[0]["params"]["teamId"] == "team_1"
        assert result["total_found"] == 5
        assert result["returned"] == len(rows)
        assert [row["id"] for row in result["subscriptions"]] == ["3Byq3Aj", "jM7KJAK"]

    @pytest.mark.asyncio
    async def test_customer_name_search_sends_the_name_as_the_query(self, monkeypatch):
        client, requests = recording_client(monkeypatch, _subscriptions_answer(_subscription_rows()))

        result = await SubscriptionManager(client).search_subscriptions({"customer_name": "Engineering"})

        assert requests[0]["params"]["query"] == "Engineering"
        assert result["subscriptions"][0]["matched_on"] == ["organization.label"]
        assert result["exact_field_matches_on_page"] == 1

    @pytest.mark.asyncio
    async def test_two_search_terms_are_refused_before_any_request(self, monkeypatch):
        client, requests = recording_client(monkeypatch, _subscriptions_answer(_subscription_rows()))

        with pytest.raises(ToolError) as exc:
            await SubscriptionManager(client).search_subscriptions(
                {"subscriber_email": "jane@acme.com", "customer_name": "Engineering"}
            )

        assert "one search term" in exc.value.message
        # Only the inputs the caller sent are named.
        assert "product_name" not in exc.value.message
        assert "search_query" not in exc.value.message
        assert requests == []

    @pytest.mark.asyncio
    async def test_each_row_says_which_fields_contain_the_term(self, monkeypatch):
        client, _ = recording_client(monkeypatch, _subscriptions_answer(_subscription_rows()))

        result = await SubscriptionManager(client).search_subscriptions(
            {"subscriber_email": "JANE@acme.com"}
        )

        assert [row["matched_on"] for row in result["subscriptions"]] == [["subscriberEmail"], ["name"]]
        assert result["exact_field_matches_on_page"] == 1
        assert "match_basis" in result

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "key, term, field_label",
        [
            ("customer_name", "Engineering", "organization name"),
            ("subscriber_email", "jane@acme.com", "subscriber email"),
            ("product_name", "Gold", "product name"),
        ],
    )
    async def test_a_field_search_says_what_its_total_counts(
        self, monkeypatch, key, term, field_label
    ):
        """total_found is the platform's all-field count, never a count of the field searched."""
        client, _ = recording_client(monkeypatch, _subscriptions_answer(_subscription_rows()))

        result = await SubscriptionManager(client).search_subscriptions({key: term})

        assert result["total_found"] == 5
        basis = result["total_found_basis"]
        assert term in basis
        assert f"not only those matching on the {field_label}" in basis
        assert f"exact_field_matches_on_page counts this page's rows matching on the {field_label}" in basis
        other_labels = {"organization name", "subscriber email", "product name"} - {field_label}
        assert not any(f"matching on the {label}" in basis for label in other_labels)

    @pytest.mark.asyncio
    async def test_a_general_search_says_its_total_counts_any_field(self, monkeypatch):
        client, _ = recording_client(monkeypatch, _subscriptions_answer(_subscription_rows()))

        result = await SubscriptionManager(client).search_subscriptions({"search_query": "acme"})

        basis = result["total_found_basis"]
        assert "'acme'" in basis
        assert "not only those matching" not in basis

    @pytest.mark.asyncio
    async def test_a_search_without_a_term_has_no_total_basis(self, monkeypatch):
        """Guard: without a term total_found is every subscription, which needs no note."""
        client, _ = recording_client(monkeypatch, _subscriptions_answer(_subscription_rows()))

        result = await SubscriptionManager(client).search_subscriptions({})

        assert "total_found_basis" not in result

    @pytest.mark.asyncio
    async def test_page_and_size_are_forwarded(self, monkeypatch):
        client, requests = recording_client(monkeypatch, _subscriptions_answer(_subscription_rows()))

        await SubscriptionManager(client).search_subscriptions(
            {"customer_name": "Engineering", "page": 2, "size": 10}
        )

        assert requests[0]["params"]["page"] == 2
        assert requests[0]["params"]["size"] == 10

    @pytest.mark.asyncio
    async def test_a_body_without_a_total_reports_the_total_as_unknown(self, monkeypatch):
        rows = _subscription_rows()
        client, _ = recording_client(
            monkeypatch, _subscriptions_answer(rows, page={"size": 50, "number": 0})
        )

        result = await SubscriptionManager(client).search_subscriptions({"customer_name": "Engineering"})

        assert result["total_found"] is None
        assert result["returned"] == len(rows)

    @pytest.mark.asyncio
    async def test_a_plus_address_is_sent_exactly(self, monkeypatch):
        client, requests = recording_client(monkeypatch, _subscriptions_answer([]))

        await SubscriptionManager(client).search_subscriptions({"subscriber_email": "jane+x@acme.com"})

        assert requests[0]["params"]["query"] == "jane+x@acme.com"

    @pytest.mark.asyncio
    async def test_a_padded_term_is_trimmed(self, monkeypatch):
        client, requests = recording_client(monkeypatch, _subscriptions_answer([]))

        await SubscriptionManager(client).search_subscriptions({"customer_name": "  Engineering "})

        assert requests[0]["params"]["query"] == "Engineering"

    @pytest.mark.asyncio
    async def test_absent_terms_from_the_registered_tool_send_no_query(self, monkeypatch):
        client, requests = recording_client(monkeypatch, _subscriptions_answer([]))

        await SubscriptionManager(client).search_subscriptions(
            {"subscriber_email": None, "customer_name": ""}
        )

        assert "query" not in requests[0]["params"]


class TestSubscriptionCreateTeamAndBodyShape:
    """BACK-4852: a create names a team or refuses it, and a non-object body is refused by name."""

    @staticmethod
    async def _expert_create(sub_mgmt, sub_manager, subscription_data):
        return await sub_mgmt._handle_crud_actions(
            "create",
            {"subscription_data": subscription_data, "auto_generate": False},
            sub_manager,
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("body", [["name", "Monthly"], "Monthly", 7])
    async def test_a_non_object_subscription_data_is_refused_by_name(
        self, sub_mgmt, sub_manager, mock_client, body
    ):
        with pytest.raises(ToolError) as exc:
            await self._expert_create(sub_mgmt, sub_manager, body)

        assert exc.value.field == "subscription_data"
        assert "must be an object" in exc.value.message
        assert "nothing was created" in exc.value.message
        mock_client.create_subscription.assert_not_called()

    @pytest.mark.asyncio
    async def test_the_manager_refuses_a_non_object_body_too(self, sub_manager, mock_client):
        with pytest.raises(ToolError) as exc:
            await sub_manager.create_subscription({"subscription_data": "Monthly"})

        assert exc.value.field == "subscription_data"
        mock_client.create_subscription.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("team", ["team_given", {"id": "team_given"}])
    async def test_a_team_in_subscription_data_is_honoured(
        self, sub_mgmt, sub_manager, mock_client, team
    ):
        mock_client.create_subscription.return_value = {"id": "sub_new"}
        await self._expert_create(
            sub_mgmt,
            sub_manager,
            {
                "name": "Monthly",
                "product_id": "prod_1",
                "clientEmailAddress": "buyer@acme.test",
                "team": team,
            },
        )

        body = mock_client.create_subscription.call_args[0][0]
        assert body["teamId"] == "team_given"
        assert "team" not in body

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "team_fields, filed_team",
        [
            ({"team": None}, "team_configured"),
            ({"team": ""}, "team_configured"),
            ({"teamId": ""}, "team_configured"),
            ({"team": {"id": "team_given"}, "teamId": ""}, "team_given"),
        ],
    )
    async def test_an_empty_team_or_team_id_names_no_team(
        self, sub_mgmt, sub_manager, mock_client, team_fields, filed_team
    ):
        mock_client.team_id = "team_configured"
        mock_client.create_subscription.return_value = {"id": "sub_new"}
        await self._expert_create(
            sub_mgmt,
            sub_manager,
            {
                "name": "Monthly",
                "product_id": "prod_1",
                "clientEmailAddress": "buyer@acme.test",
                **team_fields,
            },
        )

        body = mock_client.create_subscription.call_args[0][0]
        assert body["teamId"] == filed_team
        assert "team" not in body

    @pytest.mark.asyncio
    async def test_two_different_teams_are_refused(self, sub_mgmt, sub_manager, mock_client):
        with pytest.raises(ToolError) as exc:
            await self._expert_create(
                sub_mgmt,
                sub_manager,
                {
                    "name": "Monthly",
                    "product_id": "prod_1",
                    "clientEmailAddress": "buyer@acme.test",
                    "team": "team_a",
                    "teamId": "team_b",
                },
            )

        assert exc.value.field == "subscription_data.teamId"
        mock_client.create_subscription.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("stored_team", ["team_sub", {"id": "team_sub"}])
    async def test_an_update_keeps_the_stored_team(self, mock_client, stored_team):
        from src.revenium_mcp_server.common.partial_update_handler import PartialUpdateHandler
        from src.revenium_mcp_server.common.update_configs import UpdateConfigs

        mock_client.get_subscription_by_id = AsyncMock(
            return_value={"id": "s1", "name": "Old", "team": stored_team}
        )
        mock_client.update_subscription = AsyncMock()
        body = await PartialUpdateHandler().build_update_payload(
            resource_id="s1",
            partial_data={"name": "New"},
            config=UpdateConfigs.create_subscriptions_config(mock_client),
            action_context="update subscription",
        )

        assert body["teamId"] == "team_sub"


# ===========================================================================
# BACK-5092 - a create preview is built from the same checks as the live create
# ===========================================================================

# The audit's "Example 1" payload: name, product and invoice address plus the
# fields the platform drops on create.
_UNSTORED_CREATE_FIELDS = {
    "billing_address": {"street": "123 Business St", "city": "San Francisco", "country": "US"},
    "description": "Monthly subscription",
    "metadata": {"customer_tier": "premium"},
    "payment_method": {"type": "card", "details": {"last_four": "4242"}},
}
_UNSTORED_NOTE = "Not stored by the platform: billing_address, description, metadata, payment_method."


def _create_arguments(auto_generate, dry_run, **extra_fields):
    return {
        "subscription_data": {
            "name": "mcp-test-sub-ex1",
            "product_id": "jM7Bz8P",
            "clientEmailAddress": "mcp-test@example.com",
            **extra_fields,
        },
        "auto_generate": auto_generate,
        "dry_run": dry_run,
    }


def _previewed_payload(text):
    return json.loads(text.split("```json\n", 1)[1].split("\n```", 1)[0])


def _stored_create_fields():
    from src.revenium_mcp_server.common.subscription_create_fields import (
        SUBSCRIPTION_CREATE_UNAPPLIED_DATES,
    )
    from src.revenium_mcp_server.tools_decomposed.subscription_management import (
        _CREATE_ONLY_KEYS,
        _SUBSCRIPTION_WRITE_FIELDS,
    )

    return (_SUBSCRIPTION_WRITE_FIELDS | _CREATE_ONLY_KEYS) - set(
        SUBSCRIPTION_CREATE_UNAPPLIED_DATES
    )


class TestCreatePreviewNamesUnstoredFields:
    """A preview echoed billing_address, payment_method, metadata and
    description as if stored; the live create named them as dropped."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("auto_generate", [True, False])
    async def test_preview_names_every_field_the_platform_will_not_store(
        self, sub_mgmt, sub_manager, auto_generate
    ):
        arguments = _create_arguments(auto_generate, True, **_UNSTORED_CREATE_FIELDS)

        result = await sub_mgmt._handle_crud_actions("create", arguments, sub_manager)

        assert _UNSTORED_NOTE in result[0].text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("auto_generate", [True, False])
    async def test_preview_payload_holds_only_fields_the_platform_stores(
        self, sub_mgmt, sub_manager, auto_generate
    ):
        arguments = _create_arguments(auto_generate, True, **_UNSTORED_CREATE_FIELDS)

        result = await sub_mgmt._handle_crud_actions("create", arguments, sub_manager)

        assert set(_previewed_payload(result[0].text)) == {
            "name",
            "product_id",
            "clientEmailAddress",
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize("auto_generate", [True, False])
    async def test_preview_and_live_create_name_the_same_unstored_fields(
        self, sub_mgmt, sub_manager, mock_client, auto_generate
    ):
        mock_client.create_subscription = AsyncMock(return_value={"id": "jM7wn6j"})
        arguments = _create_arguments(auto_generate, True, **_UNSTORED_CREATE_FIELDS)

        preview = await sub_mgmt._handle_crud_actions("create", arguments, sub_manager)
        live = await sub_mgmt._handle_crud_actions(
            "create", {**arguments, "dry_run": False}, sub_manager
        )

        assert _UNSTORED_NOTE in preview[0].text
        assert _UNSTORED_NOTE in live[0].text


class TestCreateRefusesAStartThePlatformSetsItself:
    """The platform starts a subscription when it is created: a live create
    with a future start_date or start, or a trialEnd, came back starting at
    the create time with no trial end, so billing began on the wrong day."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("dry_run", [True, False])
    @pytest.mark.parametrize("auto_generate", [True, False])
    @pytest.mark.parametrize("field", ["start_date", "start", "trialEnd", "trial_end_date"])
    async def test_create_refuses_a_requested_start_or_trial_end(
        self, sub_mgmt, sub_manager, mock_client, field, auto_generate, dry_run
    ):
        requested = {field: "2027-01-01T00:00:00Z"}
        arguments = _create_arguments(auto_generate, dry_run, **requested)

        with pytest.raises(ToolError) as exc:
            await sub_mgmt._handle_crud_actions("create", arguments, sub_manager)

        assert exc.value.field == field
        assert exc.value.value == "2027-01-01T00:00:00Z"
        assert "2027-01-01T00:00:00Z" in exc.value.message
        assert "Dry Run Preview" not in exc.value.message
        mock_client.create_subscription.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_null_start_is_not_a_request(self, sub_mgmt, sub_manager, mock_client):
        result = await sub_mgmt._handle_crud_actions(
            "create", _create_arguments(True, True, start=None), sub_manager
        )

        assert "Dry Run Preview" in result[0].text

    @pytest.mark.asyncio
    async def test_validate_refuses_a_requested_start(self, sub_mgmt, mock_client):
        with patch.object(
            SubscriptionManagement, "get_client", AsyncMock(return_value=mock_client)
        ):
            with pytest.raises(ToolError) as exc:
                await sub_mgmt.handle_action(
                    "validate",
                    _create_arguments(True, True, start_date="2027-01-01T00:00:00Z"),
                )

        assert exc.value.field == "start_date"

    @pytest.mark.asyncio
    async def test_create_with_credentials_refuses_a_requested_start(self, mock_client):
        manager = SubscriptionHierarchyManager(mock_client)

        with pytest.raises(ToolError) as exc:
            await manager.create_with_credentials(
                {
                    "subscription_data": {
                        "name": "probe",
                        "product_id": "prod_ok",
                        "clientEmailAddress": "a@b.io",
                        "start_date": "2027-01-01T00:00:00Z",
                    },
                    "credentials_data": {"label": "k", "externalId": "x", "externalSecret": "y"},
                }
            )

        assert exc.value.field == "start_date"
        mock_client.create_subscription.assert_not_awaited()


class TestAdvertisedCreateFieldsAreStored:
    """get_capabilities listed start_date, billing_address, payment_method and
    metadata as optional create fields and every template carried them."""

    def test_schema_discovery_capabilities_list_only_stored_fields(self):
        from src.revenium_mcp_server.schema_discovery import SubscriptionSchemaDiscovery

        schema = SubscriptionSchemaDiscovery().get_subscription_capabilities()["schema"]
        fields = schema["subscription_data"]
        advertised = set(fields["required"]) | set(fields["optional"])
        assert advertised <= _stored_create_fields()

    def test_every_schema_discovery_template_carries_only_stored_fields(self):
        from src.revenium_mcp_server.schema_discovery import SubscriptionSchemaDiscovery

        examples = SubscriptionSchemaDiscovery().get_subscription_examples()["examples"]
        assert examples
        for example in examples:
            template_fields = set(example["template"])
            assert template_fields <= _stored_create_fields(), example["example_type"]

    def test_every_fallback_template_carries_only_stored_fields(self):
        from src.revenium_mcp_server.tools_decomposed.subscription_management import (
            SubscriptionValidator,
        )

        validator = SubscriptionValidator()
        validator.schema_discovery = None
        examples = validator.get_examples()["examples"]
        assert examples
        for example in examples:
            template_fields = set(example["template"])
            assert template_fields <= _stored_create_fields(), example["example_type"]

    @pytest.mark.asyncio
    async def test_ucm_capabilities_list_only_stored_fields(self):
        from src.revenium_mcp_server.capability_manager.discovery import CapabilityDiscovery

        discovery = CapabilityDiscovery(MagicMock())
        for helper in (
            "_discover_subscription_types_from_api",
            "_discover_currencies_from_api",
        ):
            setattr(discovery, helper, AsyncMock(return_value=[]))

        capabilities = await discovery._discover_subscription_capabilities()

        fields = capabilities["schema"]["subscription_data"]
        advertised = set(fields["required"]) | set(fields["optional"])
        assert advertised <= _stored_create_fields()

    @pytest.mark.asyncio
    async def test_capabilities_text_lists_only_stored_optional_fields(self, sub_mgmt):
        text = await sub_mgmt._build_enhanced_capabilities_text(None)

        section = text.split("## **Optional Fields**", 1)[1].split("\n## ", 1)[0]
        listed = {line.split("`")[1] for line in section.splitlines() if line.startswith("- `")}
        assert listed
        assert listed <= _stored_create_fields()

    @pytest.mark.asyncio
    async def test_capabilities_text_requires_the_shared_required_fields(self, sub_mgmt):
        from src.revenium_mcp_server.common.subscription_create_fields import (
            REQUIRED_SUBSCRIPTION_CREATE_FIELDS,
        )

        text = await sub_mgmt._build_enhanced_capabilities_text(None)

        section = text.split("## **Required Fields**", 1)[1].split("\n## ", 1)[0]
        listed = [line.split("`")[1] for line in section.splitlines() if line.startswith("- `")]
        assert listed == list(REQUIRED_SUBSCRIPTION_CREATE_FIELDS)

    @pytest.mark.asyncio
    async def test_capabilities_text_names_every_refused_date(self, sub_mgmt):
        from src.revenium_mcp_server.common.subscription_create_fields import (
            SUBSCRIPTION_CREATE_UNAPPLIED_DATES,
        )

        text = await sub_mgmt._build_enhanced_capabilities_text(None)

        rules = text.split("## **Business Rules**", 1)[1].split("\n## ", 1)[0]
        for field in SUBSCRIPTION_CREATE_UNAPPLIED_DATES:
            assert f"`{field}`" in rules

    def test_no_field_is_both_offered_and_named_as_unstored(self):
        from src.revenium_mcp_server.common.subscription_create_fields import (
            OPTIONAL_SUBSCRIPTION_CREATE_FIELDS,
            REQUIRED_SUBSCRIPTION_CREATE_FIELDS,
            SUBSCRIPTION_CREATE_UNAPPLIED_DATES,
            SUBSCRIPTION_CREATE_UNSTORED_FIELDS,
        )

        offered = set(REQUIRED_SUBSCRIPTION_CREATE_FIELDS) | set(
            OPTIONAL_SUBSCRIPTION_CREATE_FIELDS
        )
        assert not offered & set(SUBSCRIPTION_CREATE_UNSTORED_FIELDS)
        assert not offered & set(SUBSCRIPTION_CREATE_UNAPPLIED_DATES)

    @pytest.mark.asyncio
    async def test_every_surface_states_the_shared_create_rules(self, sub_mgmt):
        from src.revenium_mcp_server.capability_manager.discovery import CapabilityDiscovery
        from src.revenium_mcp_server.common.subscription_create_fields import (
            SUBSCRIPTION_CREATE_RULES,
            UNAPPLIED_DATES_RULE,
            UNSTORED_FIELDS_RULE,
        )
        from src.revenium_mcp_server.json_schema_validator import JSONSchemaValidator
        from src.revenium_mcp_server.schema_discovery import SubscriptionSchemaDiscovery

        discovery = CapabilityDiscovery(MagicMock())
        for helper in (
            "_discover_subscription_types_from_api",
            "_discover_currencies_from_api",
        ):
            setattr(discovery, helper, AsyncMock(return_value=[]))
        ucm_rules = (await discovery._discover_subscription_capabilities())["business_rules"]
        schema = SubscriptionSchemaDiscovery()
        text = await sub_mgmt._build_enhanced_capabilities_text(None)
        description = JSONSchemaValidator()._build_subscriptions_schema()["properties"][
            "subscription_data"
        ]["description"]

        for rule in SUBSCRIPTION_CREATE_RULES:
            assert rule in ucm_rules
            assert rule in schema.get_subscription_capabilities()["business_rules"]
            assert rule in schema.validation_rules["subscriptions"]["business_rules"]
            assert f"- {rule}\n" in text
        assert UNAPPLIED_DATES_RULE in description
        assert UNSTORED_FIELDS_RULE in description

    def test_json_schema_subscription_data_names_only_stored_fields(self):
        from src.revenium_mcp_server.json_schema_validator import JSONSchemaValidator

        schema = JSONSchemaValidator()._build_subscriptions_schema()
        properties = schema["properties"]["subscription_data"]["properties"]
        assert set(properties) <= _stored_create_fields()
