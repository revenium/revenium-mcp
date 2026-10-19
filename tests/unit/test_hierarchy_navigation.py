"""Unit tests for hierarchy/navigation_service.py.

Tests the HierarchyNavigationService which provides bidirectional navigation
across Products -> Subscriptions -> Credentials hierarchy.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.revenium_mcp_server.hierarchy.navigation_service import (
    HierarchyNavigationService,
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



class TestSubscriptionWalkPageFailure:
    """A failed subscriptions page must never be answered from a partial list."""

    PAGE_SIZE = 50

    @staticmethod
    def _serve_pages(mock_client, pages):
        """Serve ``pages[n]`` for page n; an Exception entry makes that page fail."""

        def fetch(page, size):
            entry = pages[page]
            if isinstance(entry, Exception):
                raise entry
            return {"items": entry}

        mock_client.get_subscriptions = AsyncMock(side_effect=fetch)
        mock_client._extract_embedded_data = MagicMock(side_effect=lambda r: r["items"])

    @staticmethod
    def _requested_pages(mock_client):
        return [c.kwargs["page"] for c in mock_client.get_subscriptions.await_args_list]

    @staticmethod
    def _product_subs(start, count, product_id="prod_1"):
        return [
            {"id": f"sub_{n}", "product_id": product_id}
            for n in range(start, start + count)
        ]

    @staticmethod
    def _credential_subs(start, count, credential_id="cred_other"):
        return [
            {"id": f"sub_{n}", "credentials": [{"id": credential_id}]}
            for n in range(start, start + count)
        ]

    @staticmethod
    def _assert_incomplete(result, failed_page):
        assert result.success is False
        assert getattr(result, "incomplete", False) is True
        assert f"page {failed_page}" in result.error_message
        assert "incomplete" in result.error_message
        assert result.related_entities == []

    @pytest.fixture
    def product_exists(self, mock_client):
        mock_client.get_product_by_id = AsyncMock(
            return_value={"id": "prod_1", "name": "Test"}
        )

    @pytest.fixture
    def credential_exists(self, mock_client):
        mock_client.get_credential_by_id = AsyncMock(
            return_value={"id": "cred_1", "label": "Cred"}
        )

    @pytest.mark.asyncio
    async def test_product_walk_failing_on_first_page_reports_incomplete(
        self, nav_service, mock_client, product_exists
    ):
        self._serve_pages(mock_client, [RuntimeError("502 Bad Gateway")])

        result = await nav_service.get_subscriptions_for_product("prod_1")

        self._assert_incomplete(result, 0)
        assert nav_service._cache == {}
        assert self._requested_pages(mock_client) == [0]

    @pytest.mark.asyncio
    async def test_product_walk_failing_after_matches_returns_no_partial_list(
        self, nav_service, mock_client, product_exists
    ):
        self._serve_pages(
            mock_client,
            [self._product_subs(0, self.PAGE_SIZE), RuntimeError("502 Bad Gateway")],
        )

        result = await nav_service.get_subscriptions_for_product("prod_1")

        self._assert_incomplete(result, 1)
        assert nav_service._cache == {}
        assert self._requested_pages(mock_client) == [0, 1]

    @pytest.mark.asyncio
    async def test_product_walk_retries_after_a_failed_page(
        self, nav_service, mock_client, product_exists
    ):
        pages = [self._product_subs(0, self.PAGE_SIZE), RuntimeError("timeout")]
        self._serve_pages(mock_client, pages)
        first = await nav_service.get_subscriptions_for_product("prod_1")
        assert first.success is False

        pages[1] = self._product_subs(self.PAGE_SIZE, 3)
        second = await nav_service.get_subscriptions_for_product("prod_1")

        assert second.success is True
        assert len(second.related_entities) == self.PAGE_SIZE + 3
        assert self._requested_pages(mock_client) == [0, 1, 0, 1]

    @pytest.mark.asyncio
    async def test_complete_product_walk_reads_every_page_and_caches(
        self, nav_service, mock_client, product_exists
    ):
        self._serve_pages(
            mock_client,
            [
                self._product_subs(0, self.PAGE_SIZE),
                self._product_subs(self.PAGE_SIZE, self.PAGE_SIZE),
                self._product_subs(2 * self.PAGE_SIZE, 3),
            ],
        )

        result = await nav_service.get_subscriptions_for_product("prod_1")

        assert result.success is True
        assert len(result.related_entities) == 2 * self.PAGE_SIZE + 3
        assert result.metadata["subscription_count"] == 2 * self.PAGE_SIZE + 3
        assert "product_subscriptions_prod_1" in nav_service._cache
        assert self._requested_pages(mock_client) == [0, 1, 2]

    @pytest.mark.asyncio
    async def test_walk_of_exactly_one_full_page_then_empty_page_is_complete(
        self, nav_service, mock_client, product_exists
    ):
        self._serve_pages(mock_client, [self._product_subs(0, self.PAGE_SIZE), []])

        result = await nav_service.get_subscriptions_for_product("prod_1")

        assert result.success is True
        assert getattr(result, "incomplete", False) is False
        assert len(result.related_entities) == self.PAGE_SIZE
        assert "product_subscriptions_prod_1" in nav_service._cache
        assert self._requested_pages(mock_client) == [0, 1]

    @pytest.mark.asyncio
    async def test_malformed_subscription_does_not_fail_the_walk(
        self, nav_service, mock_client, product_exists, credential_exists
    ):
        malformed = {"id": "sub_bad", "credentials": None, "product": "a string"}
        odd_credentials = {"id": "sub_odd", "credentials": ["not-a-dict", None]}
        page_0 = [malformed, odd_credentials] + self._credential_subs(
            0, self.PAGE_SIZE - 2
        )
        match = {
            "id": "sub_match",
            "product": {"id": "prod_1"},
            "credentials": [{"id": "cred_1"}],
        }
        self._serve_pages(mock_client, [page_0, [match]])

        by_product = await nav_service.get_subscriptions_for_product("prod_1")
        by_credential = await nav_service.get_subscription_for_credential("cred_1")

        assert by_product.success is True
        assert [s["id"] for s in by_product.related_entities] == ["sub_match"]
        assert by_credential.success is True
        assert [s["id"] for s in by_credential.related_entities] == ["sub_match"]
        assert self._requested_pages(mock_client) == [0, 1, 0, 1]

    @pytest.mark.asyncio
    async def test_credential_walk_failing_on_first_page_does_not_say_no_subscriptions(
        self, nav_service, mock_client, credential_exists
    ):
        self._serve_pages(mock_client, [RuntimeError("502 Bad Gateway")])

        result = await nav_service.get_subscription_for_credential("cred_1")

        self._assert_incomplete(result, 0)
        assert "No subscriptions found" not in result.error_message
        assert nav_service._cache == {}
        assert self._requested_pages(mock_client) == [0]

    @pytest.mark.asyncio
    async def test_credential_walk_failing_before_the_match_reports_incomplete(
        self, nav_service, mock_client, credential_exists
    ):
        self._serve_pages(
            mock_client,
            [self._credential_subs(0, self.PAGE_SIZE), RuntimeError("timeout")],
        )

        result = await nav_service.get_subscription_for_credential("cred_1")

        self._assert_incomplete(result, 1)
        assert "No subscriptions found" not in result.error_message
        assert nav_service._cache == {}
        assert self._requested_pages(mock_client) == [0, 1]

    @pytest.mark.asyncio
    async def test_credential_found_on_first_page_then_later_page_fails_reports_incomplete(
        self, nav_service, mock_client, credential_exists
    ):
        page_0 = self._credential_subs(0, self.PAGE_SIZE - 1) + self._credential_subs(
            99, 1, credential_id="cred_1"
        )
        self._serve_pages(mock_client, [page_0, RuntimeError("timeout")])

        result = await nav_service.get_subscription_for_credential("cred_1")

        self._assert_incomplete(result, 1)
        assert nav_service._cache == {}
        assert self._requested_pages(mock_client) == [0, 1]

    @pytest.mark.asyncio
    async def test_credential_with_no_subscription_after_full_walk_still_says_none_found(
        self, nav_service, mock_client, credential_exists
    ):
        self._serve_pages(
            mock_client,
            [self._credential_subs(0, self.PAGE_SIZE), self._credential_subs(50, 2)],
        )

        result = await nav_service.get_subscription_for_credential("cred_1")

        assert result.success is False
        assert getattr(result, "incomplete", False) is False
        assert result.error_message == (
            "No subscriptions found that reference this credential"
        )
        assert self._requested_pages(mock_client) == [0, 1]

    @pytest.mark.asyncio
    async def test_product_for_credential_carries_the_incomplete_walk(
        self, nav_service, mock_client, credential_exists
    ):
        self._serve_pages(
            mock_client,
            [self._credential_subs(0, self.PAGE_SIZE), RuntimeError("timeout")],
        )

        result = await nav_service.get_product_for_credential("cred_1")

        assert result.success is False
        assert getattr(result, "incomplete", False) is True
        assert "page 1" in result.error_message
        assert nav_service._cache == {}

    @pytest.mark.asyncio
    async def test_full_hierarchy_from_product_fails_when_subscription_walk_is_incomplete(
        self, nav_service, mock_client, product_exists
    ):
        self._serve_pages(
            mock_client,
            [self._product_subs(0, self.PAGE_SIZE), RuntimeError("502 Bad Gateway")],
        )

        result = await nav_service.get_full_hierarchy("products", "prod_1")

        self._assert_incomplete(result, 1)
        assert not any(k.startswith("full_hierarchy_") for k in nav_service._cache)
        assert self._requested_pages(mock_client) == [0, 1]

    @pytest.mark.asyncio
    async def test_full_hierarchy_from_credential_fails_when_subscription_walk_is_incomplete(
        self, nav_service, mock_client, credential_exists
    ):
        self._serve_pages(
            mock_client,
            [self._credential_subs(0, self.PAGE_SIZE), RuntimeError("502 Bad Gateway")],
        )

        result = await nav_service.get_full_hierarchy("credentials", "cred_1")

        self._assert_incomplete(result, 1)
        assert not any(k.startswith("full_hierarchy_") for k in nav_service._cache)
        assert self._requested_pages(mock_client) == [0, 1]
