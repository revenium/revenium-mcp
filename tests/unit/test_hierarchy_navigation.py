"""Unit tests for hierarchy/navigation_service.py.

Tests the HierarchyNavigationService which provides bidirectional navigation
across Products -> Subscriptions -> Credentials hierarchy.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.revenium_mcp_server.hierarchy.navigation_service import (
    HierarchyNavigationService,
    HierarchyPath,
    NavigationResult,
)


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.get_product_by_id = AsyncMock()
    client.get_subscription_by_id = AsyncMock()
    client.get_credential_by_id = AsyncMock()
    client.get_subscriptions = AsyncMock()
    client._extract_embedded_data = MagicMock(return_value=[])
    return client


@pytest.fixture
def nav_service(mock_client):
    return HierarchyNavigationService(client=mock_client)


class TestGetSubscriptionsForProduct:
    """Test downward navigation: Product -> Subscriptions."""

    @pytest.mark.asyncio
    async def test_product_not_found(self, nav_service, mock_client):
        """Returns failure when product does not exist."""
        mock_client.get_product_by_id = AsyncMock(return_value=None)
        result = await nav_service.get_subscriptions_for_product("prod_999")
        assert result.success is False
        assert "not found" in result.error_message

    @pytest.mark.asyncio
    async def test_product_exists_no_subscriptions(self, nav_service, mock_client):
        """Returns empty list when product has no subscriptions."""
        mock_client.get_product_by_id = AsyncMock(return_value={"id": "prod_1", "name": "Test"})
        mock_client.get_subscriptions = AsyncMock(return_value={})
        mock_client._extract_embedded_data = MagicMock(return_value=[])
        result = await nav_service.get_subscriptions_for_product("prod_1")
        assert result.success is True
        assert result.related_entities == []

    @pytest.mark.asyncio
    async def test_product_with_matching_subscriptions(self, nav_service, mock_client):
        """Returns subscriptions that reference the product."""
        mock_client.get_product_by_id = AsyncMock(return_value={"id": "prod_1", "name": "Test"})
        mock_client._extract_embedded_data = MagicMock(return_value=[
            {"id": "sub_1", "product_id": "prod_1", "name": "Sub 1"},
            {"id": "sub_2", "product_id": "prod_2", "name": "Sub 2"},  # different product
        ])
        result = await nav_service.get_subscriptions_for_product("prod_1")
        assert result.success is True
        assert len(result.related_entities) == 1
        assert result.related_entities[0]["id"] == "sub_1"

    @pytest.mark.asyncio
    async def test_matches_productId_field(self, nav_service, mock_client):
        """Matches subscriptions using productId (camelCase variant)."""
        mock_client.get_product_by_id = AsyncMock(return_value={"id": "prod_1", "name": "Test"})
        mock_client._extract_embedded_data = MagicMock(return_value=[
            {"id": "sub_1", "productId": "prod_1", "name": "Sub 1"},
        ])
        result = await nav_service.get_subscriptions_for_product("prod_1")
        assert len(result.related_entities) == 1

    @pytest.mark.asyncio
    async def test_matches_nested_product_id(self, nav_service, mock_client):
        """Matches subscriptions using nested product.id field."""
        mock_client.get_product_by_id = AsyncMock(return_value={"id": "prod_1", "name": "Test"})
        mock_client._extract_embedded_data = MagicMock(return_value=[
            {"id": "sub_1", "product": {"id": "prod_1"}, "name": "Sub 1"},
        ])
        result = await nav_service.get_subscriptions_for_product("prod_1")
        assert len(result.related_entities) == 1

    @pytest.mark.asyncio
    async def test_api_error_during_product_lookup(self, nav_service, mock_client):
        """Returns failure when product lookup raises."""
        mock_client.get_product_by_id = AsyncMock(side_effect=RuntimeError("API down"))
        result = await nav_service.get_subscriptions_for_product("prod_1")
        assert result.success is False
        assert "Error accessing product" in result.error_message


class TestGetCredentialsForSubscription:
    """Test downward navigation: Subscription -> Credentials."""

    @pytest.mark.asyncio
    async def test_subscription_not_found(self, nav_service, mock_client):
        """Returns failure when subscription does not exist."""
        mock_client.get_subscription_by_id = AsyncMock(return_value=None)
        result = await nav_service.get_credentials_for_subscription("sub_999")
        assert result.success is False
        assert "not found" in result.error_message

    @pytest.mark.asyncio
    async def test_subscription_with_credentials(self, nav_service, mock_client):
        """Returns full credential objects for subscription."""
        mock_client.get_subscription_by_id = AsyncMock(return_value={
            "id": "sub_1",
            "name": "Test Sub",
            "credentials": [{"id": "cred_1"}],
        })
        mock_client.get_credential_by_id = AsyncMock(return_value={
            "id": "cred_1",
            "label": "Test Cred",
        })
        result = await nav_service.get_credentials_for_subscription("sub_1")
        assert result.success is True
        assert len(result.related_entities) == 1
        assert result.related_entities[0]["id"] == "cred_1"

    @pytest.mark.asyncio
    async def test_subscription_without_credentials(self, nav_service, mock_client):
        """Returns empty list when subscription has no credentials."""
        mock_client.get_subscription_by_id = AsyncMock(return_value={
            "id": "sub_1",
            "name": "Test Sub",
        })
        result = await nav_service.get_credentials_for_subscription("sub_1")
        assert result.success is True
        assert result.related_entities == []

    @pytest.mark.asyncio
    async def test_credential_fetch_failure_falls_back(self, nav_service, mock_client):
        """Falls back to credential reference when full fetch fails."""
        mock_client.get_subscription_by_id = AsyncMock(return_value={
            "id": "sub_1",
            "name": "Test Sub",
            "credentials": [{"id": "cred_1", "label": "ref_only"}],
        })
        mock_client.get_credential_by_id = AsyncMock(side_effect=RuntimeError("fail"))
        result = await nav_service.get_credentials_for_subscription("sub_1")
        assert result.success is True
        assert len(result.related_entities) == 1
        assert result.related_entities[0]["label"] == "ref_only"

    @pytest.mark.asyncio
    async def test_subscription_api_error(self, nav_service, mock_client):
        """Returns failure when subscription lookup raises."""
        mock_client.get_subscription_by_id = AsyncMock(side_effect=RuntimeError("API down"))
        result = await nav_service.get_credentials_for_subscription("sub_1")
        assert result.success is False


class TestGetProductForSubscription:
    """Test upward navigation: Subscription -> Product."""

    @pytest.mark.asyncio
    async def test_subscription_not_found(self, nav_service, mock_client):
        """Returns failure when subscription does not exist."""
        mock_client.get_subscription_by_id = AsyncMock(return_value=None)
        result = await nav_service.get_product_for_subscription("sub_999")
        assert result.success is False
        assert "not found" in result.error_message

    @pytest.mark.asyncio
    async def test_subscription_has_product_id(self, nav_service, mock_client):
        """Navigates up to product using product_id field."""
        mock_client.get_subscription_by_id = AsyncMock(return_value={
            "id": "sub_1",
            "product_id": "prod_1",
        })
        mock_client.get_product_by_id = AsyncMock(return_value={
            "id": "prod_1",
            "name": "Test Product",
        })
        result = await nav_service.get_product_for_subscription("sub_1")
        assert result.success is True
        assert len(result.related_entities) == 1
        assert result.related_entities[0]["id"] == "prod_1"


