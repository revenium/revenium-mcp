"""Extended unit tests for subscription_management.py — targeting uncovered lines.

Covers:
- SubscriptionManager: discover_products, validate_product, list/get/create/update/cancel/delete,
  get_supporting_data, search_subscriptions, subscription_nlp, create_simple, create_from_text
- SubscriptionAnalytics: get_metrics
- SubscriptionManagement: handle_action routing, _handle_crud_actions, _handle_hierarchy_actions,
  _handle_unknown_action, _handle_get_capabilities, _build_enhanced_capabilities_text,
  _format_capabilities_response, _format_examples_response, _format_validation_response,
  _handle_get_agent_summary, metadata provider methods
"""

import inspect
import re

import pytest
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.client import ReveniumAPIError, ReveniumClient
from src.revenium_mcp_server.tools_decomposed import subscription_management
from src.revenium_mcp_server.tools_decomposed.subscription_management import (
    SubscriptionAnalytics,
    SubscriptionHierarchyManager,
    SubscriptionManagement,
    SubscriptionManager,
    SubscriptionValidator,
)
from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError
from mcp.types import TextContent
from tests.unit._helpers_recording_client import recording_client


# ---------------------------------------------------------------------------
# Helpers / Fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeNavigationResult:
    success: bool
    entity_type: str = "subscriptions"
    entity_id: str = ""
    related_entities: List[Dict[str, Any]] = field(default_factory=list)
    navigation_path: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None


@dataclass
class FakeValidationIssue:
    severity: str = "error"
    code: str = "TEST"
    message: str = "test issue"
    entity_type: str = "subscriptions"
    entity_id: Optional[str] = None
    field: Optional[str] = None


@dataclass
class FakeValidationResult:
    valid: bool
    operation_type: str = "create"
    entity_type: str = "subscriptions"
    entity_id: Optional[str] = None
    issues: List[Any] = field(default_factory=list)
    warnings: List[Any] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.team_id = "team_123"
    client.api_key = "test_key"
    client.base_url = "https://api.test.revenium.ai"
    client.get_products = AsyncMock()
    client.get_product_by_id = AsyncMock()
    client.get_subscriptions = AsyncMock()
    client.get_subscription_by_id = AsyncMock()
    client.create_subscription = AsyncMock()
    client.delete_subscription = AsyncMock()
    client.get_organizations = AsyncMock()
    client.get_subscribers = AsyncMock()
    client.get_credentials = AsyncMock()
    client.create_credential = AsyncMock()
    client._extract_embedded_data = MagicMock()
    client._extract_pagination_info = MagicMock(return_value={"totalElements": 5, "page": 0, "size": 20})
    return client


@pytest.fixture
def sub_manager(mock_client):
    mgr = SubscriptionManager(mock_client)
    mgr.update_handler = MagicMock()
    mgr.update_handler.update_with_merge = AsyncMock(return_value={"id": "sub_1", "updated": True})
    mgr.update_config_factory = MagicMock()
    mgr.update_config_factory.get_config = MagicMock(return_value={"entity": "subscriptions"})
    return mgr


@pytest.fixture
def analytics(mock_client):
    return SubscriptionAnalytics(mock_client)


@pytest.fixture
def hierarchy_mgr(mock_client):
    mgr = SubscriptionHierarchyManager(mock_client)
    mgr.navigation_service = MagicMock()
    mgr.lookup_service = MagicMock()
    mgr.validator = MagicMock()
    return mgr


@pytest.fixture
def sub_management():
    with patch(
        "src.revenium_mcp_server.tools_decomposed.subscription_management.SubscriptionValidator"
    ):
        mgmt = SubscriptionManagement(ucm_helper=None)
    return mgmt


# ===========================================================================
# SubscriptionManager — discover_products
# ===========================================================================


class TestDiscoverProducts:
    async def test_discover_products_no_filter(self, sub_manager, mock_client):
        mock_client.get_products.return_value = {"_embedded": {}}
        mock_client._extract_embedded_data.return_value = [
            {"id": "p1", "name": "Product A", "description": "Desc A", "published": True},
            {"id": "p2", "name": "Product B", "description": "Desc B", "published": False},
        ]
        result = await sub_manager.discover_products({})
        assert result["action"] == "discover_products"
        assert result["total_found"] == 2
        assert len(result["products"]) == 2
        assert result["products"][0]["status"] == "Available for subscriptions"
        assert result["products"][1]["status"] == "Not available (unpublished)"

    async def test_discover_products_with_search(self, sub_manager, mock_client):
        mock_client.get_products.return_value = {}
        mock_client._extract_embedded_data.return_value = [
            {"id": "p1", "name": "Premium Plan", "description": "High tier", "published": True},
            {"id": "p2", "name": "Basic Plan", "description": "Low tier", "published": True},
        ]
        result = await sub_manager.discover_products({"search_query": "premium"})
        assert result["total_found"] == 1
        assert result["products"][0]["id"] == "p1"

    async def test_discover_products_search_in_description(self, sub_manager, mock_client):
        mock_client.get_products.return_value = {}
        mock_client._extract_embedded_data.return_value = [
            {"id": "p1", "name": "Plan A", "description": "enterprise grade", "published": True},
        ]
        result = await sub_manager.discover_products({"search_query": "enterprise"})
        assert result["total_found"] == 1

    async def test_discover_products_exception(self, sub_manager, mock_client):
        mock_client.get_products.side_effect = Exception("API down")
        result = await sub_manager.discover_products({})
        assert "error" in result
        assert "fallback_guidance" in result

    async def test_discover_products_pagination(self, sub_manager, mock_client):
        mock_client.get_products.return_value = {}
        mock_client._extract_embedded_data.return_value = []
        result = await sub_manager.discover_products({"page": 2, "size": 5})
        mock_client.get_products.assert_called_once_with(page=2, size=5)


# ===========================================================================
# SubscriptionManager — validate_product_for_subscription
# ===========================================================================


class TestValidateProduct:
    async def test_validate_missing_product_id(self, sub_manager):
        with pytest.raises(ToolError):
            await sub_manager.validate_product_for_subscription({})

    async def test_validate_product_not_found(self, sub_manager, mock_client):
        mock_client.get_product_by_id.return_value = None
        result = await sub_manager.validate_product_for_subscription({"product_id": "p_bad"})
        assert result["valid"] is False
        assert "not found" in result["error"]

    async def test_validate_product_unpublished(self, sub_manager, mock_client):
        mock_client.get_product_by_id.return_value = {"id": "p1", "name": "Draft", "published": False}
        result = await sub_manager.validate_product_for_subscription({"product_id": "p1"})
        assert result["valid"] is False
        assert "not published" in result["error"]

    async def test_validate_product_published(self, sub_manager, mock_client):
        mock_client.get_product_by_id.return_value = {"id": "p1", "name": "Prod", "published": True}
        result = await sub_manager.validate_product_for_subscription({"product_id": "p1"})
        assert result["valid"] is True
        assert "status" in result

    async def test_validate_product_exception(self, sub_manager, mock_client):
        mock_client.get_product_by_id.side_effect = Exception("boom")
        result = await sub_manager.validate_product_for_subscription({"product_id": "p1"})
        assert result["valid"] is False
        assert "Validation failed" in result["error"]


# ===========================================================================
# SubscriptionManager — list / get / create / update / cancel / delete
# ===========================================================================


class TestCRUDOperations:
    async def test_list_subscriptions(self, sub_manager, mock_client):
        mock_client.get_subscriptions.return_value = {}
        mock_client._extract_embedded_data.return_value = [{"id": "s1"}, {"id": "s2"}]
        result = await sub_manager.list_subscriptions({"page": 1, "size": 10})
        assert result["action"] == "list"
        assert result["total_found"] == 2

    async def test_get_subscription_missing_id(self, sub_manager):
        with pytest.raises(ToolError):
            await sub_manager.get_subscription({})

    async def test_get_subscription_success(self, sub_manager, mock_client):
        mock_client.get_subscription_by_id.return_value = {"id": "s1", "name": "Test"}
        result = await sub_manager.get_subscription({"subscription_id": "s1"})
        assert result["id"] == "s1"

    async def test_get_subscription_404(self, sub_manager, mock_client):
        from src.revenium_mcp_server.client import ReveniumAPIError
        mock_client.get_subscription_by_id.side_effect = ReveniumAPIError("Not found", status_code=404)
        with pytest.raises(ToolError, match="not found"):
            await sub_manager.get_subscription({"subscription_id": "s_bad"})

    async def test_get_subscription_400(self, sub_manager, mock_client):
        from src.revenium_mcp_server.client import ReveniumAPIError
        mock_client.get_subscription_by_id.side_effect = ReveniumAPIError("Bad", status_code=400)
        with pytest.raises(ToolError, match="Invalid subscription ID"):
            await sub_manager.get_subscription({"subscription_id": "!!!"})

    async def test_get_subscription_other_api_error(self, sub_manager, mock_client):
        from src.revenium_mcp_server.client import ReveniumAPIError
        err = ReveniumAPIError("Server error", status_code=500)
        mock_client.get_subscription_by_id.side_effect = err
        with pytest.raises(ReveniumAPIError):
            await sub_manager.get_subscription({"subscription_id": "s1"})

    async def test_create_subscription_missing_data(self, sub_manager):
        with pytest.raises(ToolError):
            await sub_manager.create_subscription({})

    @patch("src.revenium_mcp_server.tools_decomposed.subscription_management.get_config_value", return_value="owner_1")
    async def test_create_subscription_with_only_a_name_is_refused(self, mock_config, sub_manager, mock_client):
        mock_client.get_products.return_value = {}
        mock_client._extract_embedded_data.return_value = [{"id": "p1"}]
        with pytest.raises(ToolError) as exc:
            await sub_manager.create_subscription({"name": "My Sub"})
        assert exc.value.field == "subscription_data"
        mock_client.get_products.assert_not_awaited()
        mock_client.create_subscription.assert_not_awaited()

    @patch("src.revenium_mcp_server.tools_decomposed.subscription_management.get_config_value", return_value="owner_1")
    async def test_create_subscription_with_data(self, mock_config, sub_manager, mock_client):
        mock_client.create_subscription.return_value = {"id": "s_new"}
        result = await sub_manager.create_subscription({
            "subscription_data": {
                "name": "Test",
                "productId": "p1",
                "clientEmailAddress": "a@b.com",
            }
        })
        assert result["id"] == "s_new"

    @patch("src.revenium_mcp_server.tools_decomposed.subscription_management.get_config_value", return_value=None)
    async def test_create_subscription_no_owner_id(self, mock_config, sub_manager, mock_client):
        mock_client.create_subscription.return_value = {"id": "s_new"}
        result = await sub_manager.create_subscription({
            "subscription_data": {"name": "Test", "productId": "p1", "clientEmailAddress": "a@b.com"}
        })
        assert result["id"] == "s_new"

    async def test_create_subscription_product_id_mapping(self, sub_manager, mock_client):
        """Test product_id -> productId field mapping."""
        mock_client.create_subscription.return_value = {"id": "s_new"}
        with patch("src.revenium_mcp_server.tools_decomposed.subscription_management.get_config_value", return_value="o1"):
            await sub_manager.create_subscription({
                "subscription_data": {"name": "T", "product_id": "p1", "clientEmailAddress": "a@b.com"}
            })
        call_args = mock_client.create_subscription.call_args[0][0]
        assert call_args["productId"] == "p1"

    async def test_create_subscription_email_from_args(self, sub_manager, mock_client):
        mock_client.create_subscription.return_value = {"id": "s_new"}
        with patch("src.revenium_mcp_server.tools_decomposed.subscription_management.get_config_value", return_value="o1"):
            await sub_manager.create_subscription({
                "subscription_data": {"name": "T", "productId": "p1"},
                "clientEmailAddress": "x@y.com",
            })
        call_args = mock_client.create_subscription.call_args[0][0]
        assert call_args["clientEmailAddress"] == "x@y.com"

    async def test_create_auto_gen_no_products(self, sub_manager, mock_client):
        mock_client.get_products.return_value = {}
        mock_client._extract_embedded_data.return_value = []
        with pytest.raises(ToolError):
            await sub_manager.create_subscription({"name": "NoProducts"})

    async def test_create_auto_gen_exception(self, sub_manager, mock_client):
        mock_client.get_products.side_effect = Exception("boom")
        with pytest.raises(ToolError):
            await sub_manager.create_subscription({"name": "ErrSub"})

    async def test_update_subscription_missing_id(self, sub_manager):
        with pytest.raises(ToolError):
            await sub_manager.update_subscription({})

    async def test_update_subscription_missing_data(self, sub_manager):
        with pytest.raises(ToolError):
            await sub_manager.update_subscription({"subscription_id": "s1"})

    async def test_update_subscription_success(self, sub_manager):
        result = await sub_manager.update_subscription({
            "subscription_id": "s1",
            "subscription_data": {"name": "Updated"},
        })
        assert result["updated"] is True

    async def test_delete_subscription_missing_id(self, sub_manager):
        with pytest.raises(ToolError):
            await sub_manager.delete_subscription({})

    async def test_delete_subscription_success(self, sub_manager, mock_client):
        mock_client.delete_subscription.return_value = {"deleted": True}
        result = await sub_manager.delete_subscription({"subscription_id": "s1"})
        assert result["deleted"] is True


# ===========================================================================
# SubscriptionManager — get_supporting_data
# ===========================================================================


class TestGetSupportingData:
    async def test_get_all_supporting_data(self, sub_manager, mock_client):
        mock_client.get_organizations.return_value = {}
        mock_client.get_products.return_value = {}
        mock_client.get_subscribers.return_value = {}
        mock_client.get_credentials.return_value = {}
        mock_client._extract_embedded_data.return_value = [{"id": "item1"}]
        result = await sub_manager.get_supporting_data({"data_type": "all"})
        assert "organizations" in result
        assert "products" in result
        assert "subscribers" in result
        assert "credentials" in result

    async def test_get_organizations_only(self, sub_manager, mock_client):
        mock_client.get_organizations.return_value = {}
        mock_client._extract_embedded_data.return_value = [{"id": "o1", "name": "OrgA"}]
        result = await sub_manager.get_supporting_data({"data_type": "organizations"})
        assert "organizations" in result
        assert "products" not in result

    async def test_get_supporting_data_with_search(self, sub_manager, mock_client):
        mock_client.get_organizations.return_value = {}
        mock_client._extract_embedded_data.return_value = [
            {"id": "o1", "name": "Acme Corp"},
            {"id": "o2", "name": "Globex"},
        ]
        result = await sub_manager.get_supporting_data({
            "data_type": "organizations",
            "search_query": "acme",
        })
        assert len(result["organizations"]) == 1

    async def test_get_products_with_search(self, sub_manager, mock_client):
        mock_client.get_products.return_value = {}
        mock_client._extract_embedded_data.return_value = [
            {"id": "p1", "name": "Premium", "description": "high tier"},
            {"id": "p2", "name": "Basic", "description": "low tier"},
        ]
        result = await sub_manager.get_supporting_data({
            "data_type": "products",
            "search_query": "premium",
        })
        assert len(result["products"]) == 1

    async def test_get_subscribers_with_search(self, sub_manager, mock_client):
        mock_client.get_subscribers.return_value = {}
        mock_client._extract_embedded_data.return_value = [
            {"id": "sub1", "email": "alice@test.com", "name": "Alice"},
            {"id": "sub2", "email": "bob@test.com", "name": "Bob"},
        ]
        result = await sub_manager.get_supporting_data({
            "data_type": "subscribers",
            "search_query": "alice",
        })
        assert len(result["subscribers"]) == 1

    async def test_get_credentials_with_search(self, sub_manager, mock_client):
        mock_client.get_credentials.return_value = {}
        mock_client._extract_embedded_data.return_value = [
            {"id": "c1", "name": "API Key A"},
            {"id": "c2", "name": "Token B"},
        ]
        result = await sub_manager.get_supporting_data({
            "data_type": "credentials",
            "search_query": "token",
        })
        assert len(result["credentials"]) == 1

    async def test_get_supporting_data_exception(self, sub_manager, mock_client):
        mock_client.get_organizations.side_effect = Exception("fail")
        result = await sub_manager.get_supporting_data({"data_type": "all"})
        assert "error" in result


# ===========================================================================
# SubscriptionManager — search_subscriptions
# ===========================================================================


class TestSearchSubscriptions:
    """BACK-4709: one term goes to the platform as `query`; rows are platform-shaped."""

    async def test_search_no_filters(self, sub_manager, mock_client):
        mock_client.get_subscriptions.return_value = {}
        mock_client._extract_embedded_data.return_value = [
            {"id": "s1", "name": "Sub A", "subscriberEmail": "a@b.com", "product": None},
        ]
        result = await sub_manager.search_subscriptions({})
        mock_client.get_subscriptions.assert_awaited_once_with(page=0, size=50)
        assert result["total_found"] == 5
        assert result["returned"] == 1

    async def test_search_with_query(self, sub_manager, mock_client):
        mock_client.get_subscriptions.return_value = {}
        mock_client._extract_embedded_data.return_value = [
            {"id": "s1", "name": "Acme Sub", "subscriberEmail": "a@b.com"},
        ]
        result = await sub_manager.search_subscriptions({"search_query": "acme"})
        mock_client.get_subscriptions.assert_awaited_once_with(page=0, size=50, query="acme")
        assert result["subscriptions"][0]["matched_on"] == ["name"]
        assert result["exact_field_matches_on_page"] == 1

    async def test_search_query_row_matching_no_known_field_is_not_counted(self, sub_manager, mock_client):
        # The platform also matches the client username and treats _ and % as
        # wildcards, so it can return a row none of the checked fields contain.
        mock_client.get_subscriptions.return_value = {}
        mock_client._extract_embedded_data.return_value = [
            {"id": "s1", "name": "Acme Sub"},
            {"id": "s2", "name": "Other", "subscriberEmail": "x@y.com"},
        ]
        result = await sub_manager.search_subscriptions({"search_query": "acme"})
        assert result["subscriptions"][1]["matched_on"] == []
        assert result["exact_field_matches_on_page"] == 1

    async def test_search_by_customer_name(self, sub_manager, mock_client):
        mock_client.get_subscriptions.return_value = {}
        mock_client._extract_embedded_data.return_value = [
            {"id": "s1", "name": "S1", "organization": {"id": "o1", "label": "Acme Corp"}},
        ]
        result = await sub_manager.search_subscriptions({"customer_name": "acme"})
        mock_client.get_subscriptions.assert_awaited_once_with(page=0, size=50, query="acme")
        assert result["exact_field_matches_on_page"] == 1

    async def test_search_by_product_name(self, sub_manager, mock_client):
        mock_client.get_subscriptions.return_value = {}
        mock_client._extract_embedded_data.return_value = [
            {"id": "s1", "name": "S1", "product": {"id": "p1", "name": "Premium Plan"}},
        ]
        result = await sub_manager.search_subscriptions({"product_name": "premium"})
        mock_client.get_subscriptions.assert_awaited_once_with(page=0, size=50, query="premium")
        assert result["subscriptions"][0]["matched_on"] == ["product.name"]

    async def test_search_by_subscriber_email(self, sub_manager, mock_client):
        mock_client.get_subscriptions.return_value = {}
        mock_client._extract_embedded_data.return_value = [
            {"id": "s1", "name": "S1", "subscriberEmail": "alice@test.com", "clientEmailAddress": "alice@test.com"},
        ]
        result = await sub_manager.search_subscriptions({"subscriber_email": "alice"})
        mock_client.get_subscriptions.assert_awaited_once_with(page=0, size=50, query="alice")
        assert result["subscriptions"][0]["matched_on"] == ["subscriberEmail", "clientEmailAddress"]
        assert result["exact_field_matches_on_page"] == 1


# ===========================================================================
# SubscriptionManager — subscription_nlp + helpers
# ===========================================================================


class TestSubscriptionNLP:
    async def test_nlp_missing_query(self, sub_manager):
        with pytest.raises(ToolError):
            await sub_manager.subscription_nlp({})

    async def test_nlp_list_intent(self, sub_manager, mock_client):
        mock_client.get_subscriptions.return_value = {}
        mock_client._extract_embedded_data.return_value = [{"id": "s1"}]
        result = await sub_manager.subscription_nlp({"query": "list all subscriptions"})
        assert result["action"] == "list"

    async def test_nlp_search_intent(self, sub_manager, mock_client):
        mock_client.get_subscriptions.return_value = {}
        mock_client._extract_embedded_data.return_value = []
        result = await sub_manager.subscription_nlp({"query": "find subscriptions for acme"})
        assert result["action"] == "search_subscriptions"
        # BACK-4709: the extractor yields a customer name and a general term;
        # only the more specific one is sent as the platform query.
        mock_client.get_subscriptions.assert_awaited_once_with(page=0, size=20, query="acme")

    @pytest.mark.parametrize(
        "query",
        [
            "find popcorn subscriptions",
            "search subscriptions with popcorn",
            "search subscriptions with popcorn?",
            "find subscriptions for popcorn",
        ],
    )
    async def test_nlp_search_sends_the_bare_term(self, sub_manager, mock_client, query):
        mock_client.get_subscriptions.return_value = {}
        mock_client._extract_embedded_data.return_value = []

        await sub_manager.subscription_nlp({"query": query})

        mock_client.get_subscriptions.assert_awaited_once_with(page=0, size=20, query="popcorn")

    @pytest.mark.parametrize(
        "verb", ["list", "show", "display", "view", "get", "see"]
    )
    async def test_nlp_every_list_phrase_lists_without_a_search_query(
        self, sub_manager, mock_client, verb
    ):
        mock_client.get_subscriptions.return_value = {}
        mock_client._extract_embedded_data.return_value = [{"id": "s1"}]

        result = await sub_manager.subscription_nlp({"query": f"{verb} all subscriptions"})

        assert result["action"] == "list"
        assert "query" not in mock_client.get_subscriptions.await_args.kwargs

    @pytest.mark.parametrize("query", ["list all active subscriptions", "show me subs"])
    async def test_nlp_list_phrase_with_leftover_words_still_lists(
        self, sub_manager, mock_client, query
    ):
        mock_client.get_subscriptions.return_value = {}
        mock_client._extract_embedded_data.return_value = [{"id": "s1"}]

        result = await sub_manager.subscription_nlp({"query": query})

        assert result["action"] == "list"
        assert "query" not in mock_client.get_subscriptions.await_args.kwargs

    @pytest.mark.parametrize(
        "query, term",
        [
            ("show me all subscriptions for globaltech", "globaltech"),
            ("list subscriptions for popcorn", "popcorn"),
            ("show subscriptions for popcorn", "popcorn"),
        ],
    )
    async def test_nlp_list_phrasing_with_a_customer_searches_for_it(
        self, sub_manager, mock_client, query, term
    ):
        """A list of every subscription is not an answer to a question about one customer."""
        mock_client.get_subscriptions.return_value = {}
        mock_client._extract_embedded_data.return_value = []

        result = await sub_manager.subscription_nlp({"query": query})

        assert result["action"] == "search_subscriptions"
        mock_client.get_subscriptions.assert_awaited_once_with(page=0, size=20, query=term)

    @pytest.mark.parametrize(
        "query, term_key, term",
        [
            ("list subscriptions for product popcorn", "product_name", "popcorn"),
            ("find subscriptions for product popcorn", "product_name", "popcorn"),
            ("find subscriptions for products popcorn", "product_name", "popcorn"),
            ("find subscriptions for customer acme", "customer_name", "acme"),
            ("find subscriptions for customers acme", "customer_name", "acme"),
            ("list subscriptions for organization acme", "customer_name", "acme"),
            ("list subscriptions for organizations acme", "customer_name", "acme"),
        ],
    )
    async def test_nlp_for_a_kind_word_searches_the_name_after_it(
        self, sub_manager, mock_client, query, term_key, term
    ):
        """'for product popcorn' names the product popcorn, not a customer called product."""
        mock_client.get_subscriptions.return_value = {}
        mock_client._extract_embedded_data.return_value = []

        result = await sub_manager.subscription_nlp({"query": query})

        assert result["action"] == "search_subscriptions"
        assert result["search_criteria"][term_key] == term
        mock_client.get_subscriptions.assert_awaited_once_with(page=0, size=20, query=term)

    async def test_nlp_email_search_sends_the_email(self, sub_manager, mock_client):
        mock_client.get_subscriptions.return_value = {}
        mock_client._extract_embedded_data.return_value = []
        result = await sub_manager.subscription_nlp({"query": "find subscriptions for bob@x.com"})
        assert result["search_criteria"]["subscriber_email"] == "bob@x.com"
        mock_client.get_subscriptions.assert_awaited_once_with(page=0, size=20, query="bob@x.com")

    async def test_nlp_get_intent_with_id(self, sub_manager, mock_client):
        mock_client.get_subscription_by_id.return_value = {"id": "abc123"}
        result = await sub_manager.subscription_nlp({"query": "get subscription abc123"})
        assert result["id"] == "abc123"

    async def test_nlp_get_intent_without_id(self, sub_manager, mock_client):
        # "subscription info" matches get_subscription intent but doesn't produce a
        # well-formed subscription_id (the regex may still capture 'info').
        # We just verify it doesn't crash — it either returns an error dict or a subscription.
        result = await sub_manager.subscription_nlp({"query": "subscription info"})
        # Result is either a dict with "error" key or a subscription dict
        assert isinstance(result, dict) or hasattr(result, "__getitem__")

    async def test_nlp_supporting_data_intent(self, sub_manager, mock_client):
        mock_client.get_products.return_value = {}
        mock_client._extract_embedded_data.return_value = []
        result = await sub_manager.subscription_nlp({"query": "show me products"})
        assert result["action"] == "get_supporting_data"

    async def test_nlp_create_intent(self, sub_manager):
        result = await sub_manager.subscription_nlp({"query": "create a new subscription"})
        assert result["intent"] == "create_subscription"
        assert "next_steps" in result

    async def test_nlp_unknown_intent(self, sub_manager, mock_client):
        """Default intent falls through to search."""
        mock_client.get_subscriptions.return_value = {}
        mock_client._extract_embedded_data.return_value = []
        result = await sub_manager.subscription_nlp({"query": "xyzzy"})
        # Falls to search_subscriptions default
        assert result["action"] == "search_subscriptions"

    def test_classify_intent_list(self, sub_manager):
        assert sub_manager._classify_subscription_intent("show all subscriptions") == "list_subscriptions"

    def test_classify_intent_search(self, sub_manager):
        assert sub_manager._classify_subscription_intent("find something") == "search_subscriptions"

    def test_classify_intent_get(self, sub_manager):
        assert sub_manager._classify_subscription_intent("get subscription details") == "get_subscription"

    def test_classify_intent_supporting_data(self, sub_manager):
        assert sub_manager._classify_subscription_intent("show me products") == "get_supporting_data"

    def test_classify_intent_create(self, sub_manager):
        assert sub_manager._classify_subscription_intent("create a new thing") == "create_subscription"

    def test_classify_intent_default(self, sub_manager):
        assert sub_manager._classify_subscription_intent("xyzzy") == "search_subscriptions"

    def test_extract_entities_customer(self, sub_manager):
        entities = sub_manager._extract_subscription_entities("customer acme_corp")
        assert entities.get("customer_name") == "acme_corp"

    def test_extract_entities_known_customer(self, sub_manager):
        entities = sub_manager._extract_subscription_entities("show globaltech subscriptions")
        assert entities.get("customer_name") == "globaltech"

    def test_extract_entities_product(self, sub_manager):
        entities = sub_manager._extract_subscription_entities("product premium_api stuff")
        assert "product_name" in entities

    def test_extract_entities_known_product(self, sub_manager):
        entities = sub_manager._extract_subscription_entities("automated billing plan")
        assert entities.get("product_name") == "automated billing"

    def test_extract_entities_subscription_id(self, sub_manager):
        entities = sub_manager._extract_subscription_entities("get id abc123")
        assert entities.get("subscription_id") == "abc123"

    def test_extract_entities_sub_prefix_id(self, sub_manager):
        entities = sub_manager._extract_subscription_entities("get sub_def456")
        assert entities.get("subscription_id") == "sub_def456"

    def test_extract_entities_email(self, sub_manager):
        entities = sub_manager._extract_subscription_entities("for user@example.com please")
        assert entities.get("subscriber_email") == "user@example.com"

    def test_extract_entities_data_type_products(self, sub_manager):
        entities = sub_manager._extract_subscription_entities("show products")
        assert entities.get("data_type") == "products"

    def test_extract_entities_data_type_organizations(self, sub_manager):
        entities = sub_manager._extract_subscription_entities("list organizations")
        assert entities.get("data_type") == "organizations"

    def test_extract_entities_data_type_subscribers(self, sub_manager):
        entities = sub_manager._extract_subscription_entities("find subscribers")
        assert entities.get("data_type") == "subscribers"

    def test_extract_entities_data_type_credentials(self, sub_manager):
        entities = sub_manager._extract_subscription_entities("show credentials")
        assert entities.get("data_type") == "credentials"

    def test_extract_entities_search_query(self, sub_manager):
        entities = sub_manager._extract_subscription_entities("list subscriptions for acme_corp")
        assert "search_query" in entities or "customer_name" in entities


# ===========================================================================
# SubscriptionManager — create_simple
# ===========================================================================


class TestCreateSimple:
    async def test_create_simple_missing_product_id(self, sub_manager):
        with pytest.raises(ToolError):
            await sub_manager.create_simple({"clientEmailAddress": "a@b.com"})

    async def test_create_simple_missing_email(self, sub_manager):
        with pytest.raises(ToolError):
            await sub_manager.create_simple({"product_id": "p1"})

    @patch("src.revenium_mcp_server.tools_decomposed.subscription_management.get_config_value", return_value="o1")
    async def test_create_simple_success(self, mock_config, sub_manager, mock_client):
        mock_client.get_product_by_id.return_value = {"id": "p1", "name": "Prod", "published": True}
        mock_client.create_subscription.return_value = {"id": "s_new"}
        result = await sub_manager.create_simple({
            "product_id": "p1",
            "clientEmailAddress": "a@b.com",
            "name": "Custom Name",
        })
        assert result["id"] == "s_new"

    @patch("src.revenium_mcp_server.tools_decomposed.subscription_management.get_config_value", return_value=None)
    async def test_create_simple_no_owner_id(self, mock_config, sub_manager, mock_client):
        mock_client.get_product_by_id.return_value = {"id": "p1", "name": "Prod", "published": True}
        mock_client.create_subscription.return_value = {"id": "s_new"}
        result = await sub_manager.create_simple({
            "product_id": "p1",
            "clientEmailAddress": "a@b.com",
        })
        assert result["id"] == "s_new"

    @patch("src.revenium_mcp_server.tools_decomposed.subscription_management.get_config_value", return_value="o1")
    async def test_create_simple_from_subscription_data(self, mock_config, sub_manager, mock_client):
        mock_client.get_product_by_id.return_value = {"id": "p1", "name": "Prod", "published": True}
        mock_client.create_subscription.return_value = {"id": "s_new"}
        result = await sub_manager.create_simple({
            "subscription_data": {
                "product_id": "p1",
                "clientEmailAddress": "a@b.com",
                "name": "Sub from data",
                "billing_frequency": "annual",
            }
        })
        assert result["id"] == "s_new"

    async def test_validate_simple_product_not_found(self, sub_manager, mock_client):
        mock_client.get_product_by_id.return_value = None
        with pytest.raises(ToolError):
            await sub_manager._validate_simple_product("p_bad")

    async def test_validate_simple_product_unpublished(self, sub_manager, mock_client):
        mock_client.get_product_by_id.return_value = {"id": "p1", "name": "Draft", "published": False}
        with pytest.raises(ToolError):
            await sub_manager._validate_simple_product("p1")

    async def test_unpublished_refusal_tells_how_to_attach_a_source(self, sub_manager, mock_client):
        mock_client.get_product_by_id.return_value = {"id": "p1", "name": "Draft", "published": False}
        with pytest.raises(ToolError) as exc_info:
            await sub_manager._validate_simple_product("p1")
        assert "sourceIds" in exc_info.value.examples["publish_command"]

    async def test_validate_simple_product_api_error(self, sub_manager, mock_client):
        from src.revenium_mcp_server.client import ReveniumAPIError
        mock_client.get_product_by_id.side_effect = ReveniumAPIError("err", status_code=500)
        # Should not raise, just log warning
        await sub_manager._validate_simple_product("p1")

    def test_extract_simple_parameters(self, sub_manager):
        product_id, client_email, name, freq = sub_manager._extract_simple_parameters({
            "product_id": "p1",
            "clientEmailAddress": "a@b.com",
            "name": "Test",
            "billing_frequency": "annual",
        })
        assert product_id == "p1"
        assert client_email == "a@b.com"
        assert name == "Test"
        assert freq == "annual"

    def test_extract_simple_parameters_defaults(self, sub_manager):
        _, _, _, freq = sub_manager._extract_simple_parameters({})
        assert freq == "monthly"

    def test_build_simple_config_no_name(self, sub_manager):
        with patch("src.revenium_mcp_server.tools_decomposed.subscription_management.get_config_value", return_value="o1"):
            config = sub_manager._build_simple_subscription_config("p1", "a@b.com", None, "monthly")
        assert "Monthly Subscription" in config["name"]


# ===========================================================================
# SubscriptionManager — create_from_text + helpers
# ===========================================================================


class TestCreateFromText:
    async def test_validate_text_input_empty(self, sub_manager):
        with pytest.raises(ToolError):
            sub_manager._validate_text_input({})

    async def test_validate_text_input_valid(self, sub_manager):
        text = sub_manager._validate_text_input({"text": "hello"})
        assert text == "hello"

    def test_raise_product_safety_error(self, sub_manager):
        with pytest.raises(ToolError, match="BILLING SAFETY"):
            sub_manager._raise_product_safety_error()

    def test_raise_client_email_safety_error(self, sub_manager):
        with pytest.raises(ToolError, match="BILLING SAFETY"):
            sub_manager._raise_client_email_safety_error()

    async def test_extract_and_validate_explicit(self, sub_manager):
        product_id, email = sub_manager._extract_and_validate_parameters(
            {"product_id": "p1", "clientEmailAddress": "a@b.com"},
            {},
        )
        assert product_id == "p1"
        assert email == "a@b.com"

    async def test_extract_and_validate_from_extracted(self, sub_manager):
        product_id, email = sub_manager._extract_and_validate_parameters(
            {},
            {"product_id": "p2", "clientEmailAddress": "b@c.com"},
        )
        assert product_id == "p2"
        assert email == "b@c.com"

    async def test_extract_and_validate_missing_product(self, sub_manager):
        with pytest.raises(ToolError):
            sub_manager._extract_and_validate_parameters({}, {})

    async def test_extract_and_validate_missing_email(self, sub_manager):
        with pytest.raises(ToolError):
            sub_manager._extract_and_validate_parameters(
                {"product_id": "p1"}, {}
            )

    async def test_validate_product_safety_invalid(self, sub_manager, mock_client):
        mock_client.get_product_by_id.return_value = {"id": "p1", "published": False}
        with pytest.raises(ToolError, match="PRODUCT VALIDATION"):
            await sub_manager._validate_product_safety("p1")

    async def test_validate_product_safety_valid(self, sub_manager, mock_client):
        mock_client.get_product_by_id.return_value = {"id": "p1", "published": True, "name": "Prod"}
        result = await sub_manager._validate_product_safety("p1")
        assert result["valid"] is True

    @patch("src.revenium_mcp_server.tools_decomposed.subscription_management.get_config_value", return_value="o1")
    async def test_build_text_subscription_config(self, mock_config, sub_manager):
        config = sub_manager._build_text_subscription_config(
            "p1", "a@b.com", "Create monthly premium subscription",
            {"subscription_name": "Premium Monthly Subscription", "features_mentioned": ["premium"]},
        )
        assert config["productId"] == "p1"
        assert config["clientEmailAddress"] == "a@b.com"
        assert config["name"] == "Premium Monthly Subscription"

    @patch("src.revenium_mcp_server.tools_decomposed.subscription_management.get_config_value", return_value=None)
    async def test_build_text_subscription_config_no_owner(self, mock_config, sub_manager):
        config = sub_manager._build_text_subscription_config(
            "p1", "a@b.com", "Short text",
            {"subscription_name": None},
        )
        assert "ownerId" not in config

    async def test_create_subscription_with_safety_log(self, sub_manager, mock_client):
        mock_client.create_subscription.return_value = {"id": "s_new"}
        result = await sub_manager._create_subscription_with_safety_log(
            {"productId": "p1"}, "p1", "a@b.com"
        )
        assert result["id"] == "s_new"

    async def test_analyze_subscription_text_monthly(self, sub_manager):
        result = await sub_manager._analyze_subscription_text("Create monthly subscription")
        assert result["billing_frequency_hint"] == "monthly"
        assert result["suggested_billing_period"] == "MONTH"

    async def test_analyze_subscription_text_annual(self, sub_manager):
        result = await sub_manager._analyze_subscription_text("annual billing plan")
        assert result["billing_frequency_hint"] == "annual"
        assert result["suggested_billing_period"] == "YEAR"

    async def test_analyze_subscription_text_quarterly(self, sub_manager):
        result = await sub_manager._analyze_subscription_text("quarterly subscription")
        assert result["billing_frequency_hint"] == "quarterly"
        assert result["suggested_billing_period"] == "QUARTER"

    async def test_analyze_subscription_text_trial(self, sub_manager):
        result = await sub_manager._analyze_subscription_text("free trial subscription")
        assert result["billing_frequency_hint"] == "trial"
        assert result["subscription_category"] == "trial"

    async def test_analyze_subscription_text_features(self, sub_manager):
        result = await sub_manager._analyze_subscription_text("premium enterprise plan")
        assert "premium" in result["features_mentioned"]
        assert "enterprise" in result["features_mentioned"]
        assert "Premium Enterprise" in result["subscription_name"]

    async def test_analyze_subscription_text_no_features(self, sub_manager):
        result = await sub_manager._analyze_subscription_text("monthly plan")
        assert result["features_mentioned"] == []
        assert "Monthly" in result["subscription_name"]

    @patch("src.revenium_mcp_server.tools_decomposed.subscription_management.get_config_value", return_value="o1")
    async def test_create_from_text_full_flow(self, mock_config, sub_manager, mock_client):
        mock_client.get_product_by_id.return_value = {"id": "p1", "published": True, "name": "Prod"}
        mock_client.create_subscription.return_value = {"id": "s_new"}
        result = await sub_manager.create_from_text({
            "text": "Create monthly premium subscription",
            "product_id": "p1",
            "clientEmailAddress": "a@b.com",
        })
        assert result["id"] == "s_new"
        assert result["safety_confirmation"]["product_validated"] is True


# ===========================================================================
# SubscriptionAnalytics — get_metrics
# ===========================================================================


class TestSubscriptionAnalytics:
    async def test_get_metrics_empty(self, analytics, mock_client):
        mock_client.get_subscriptions.return_value = {}
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {"totalElements": 0}
        result = await analytics.get_metrics({})
        assert result["total_subscriptions"] == 0
        assert result["active_subscriptions"] == 0
        assert result["active_rate_in_sample"] is None


# ===========================================================================
# SubscriptionManagement — handle_action routing
# ===========================================================================


class TestHandleAction:
    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_handle_action_list(self, mock_get_client, sub_management, mock_client):
        mock_get_client.return_value = mock_client
        mock_client.get_subscriptions.return_value = {}
        mock_client._extract_embedded_data.return_value = [{"id": "s1"}]
        mock_client._extract_pagination_info.return_value = {"totalElements": 1}
        result = await sub_management.handle_action("list", {})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)

    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_handle_action_get(self, mock_get_client, sub_management, mock_client):
        mock_get_client.return_value = mock_client
        mock_client.get_subscription_by_id.return_value = {"id": "s1", "name": "Test"}
        result = await sub_management.handle_action("get", {"subscription_id": "s1"})
        assert "s1" in result[0].text

    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_handle_action_update(self, mock_get_client, sub_management, mock_client):
        mock_get_client.return_value = mock_client
        with patch(
            "src.revenium_mcp_server.tools_decomposed.subscription_management.PartialUpdateHandler"
        ) as MockHandler:
            mock_handler = MockHandler.return_value
            mock_handler.update_with_merge = AsyncMock(return_value={"id": "s1", "updated": True})
            with patch(
                "src.revenium_mcp_server.tools_decomposed.subscription_management.UpdateConfigFactory"
            ) as MockFactory:
                mock_factory = MockFactory.return_value
                mock_factory.get_config.return_value = {}
                result = await sub_management.handle_action("update", {
                    "subscription_id": "s1",
                    "subscription_data": {"name": "New Name"},
                })
        assert "updated" in result[0].text

    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_handle_action_cancel_refuses_and_sends_no_delete(
        self, mock_get_client, sub_management, mock_client
    ):
        mock_get_client.return_value = mock_client
        with pytest.raises(ToolError) as refusal:
            await sub_management.handle_action("cancel", {"subscription_id": "s1"})

        message = refusal.value.message
        assert "no cancel operation" in message
        assert "delete(subscription_id=" in message
        assert "nothing was changed" in message
        assert (
            "The only non-destructive route the API exposes is "
            "`update(subscription_id=..., subscription_data={'expiration': ...})`" in message
        )
        assert "cannot confirm that it stops billing on the platform" in message
        assert not [c for c in mock_client.mock_calls if "delete" in c[0]]

    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_handle_action_delete_says_the_record_was_deleted(
        self, mock_get_client, sub_management, mock_client
    ):
        mock_get_client.return_value = mock_client
        mock_client.delete_subscription.return_value = {"deleted": True}
        result = await sub_management.handle_action("delete", {"subscription_id": "s1"})
        assert "Subscription s1 deleted successfully" in result[0].text
        assert "permanently removed" in result[0].text
        mock_client.delete_subscription.assert_awaited_once_with("s1")

    async def test_cancel_is_not_advertised_as_an_operation(self, sub_management):
        assert "cancel" not in await sub_management._get_supported_actions()
        capabilities = await sub_management._build_enhanced_capabilities_text(None)
        assert "cancel(" not in capabilities

    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_handle_action_discover_products(self, mock_get_client, sub_management, mock_client):
        mock_get_client.return_value = mock_client
        mock_client.get_products.return_value = {}
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {}
        result = await sub_management.handle_action("discover_products", {})
        assert "Product Discovery" in result[0].text

    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_handle_action_validate_product(self, mock_get_client, sub_management, mock_client):
        mock_get_client.return_value = mock_client
        mock_client.get_product_by_id.return_value = {"id": "p1", "published": True, "name": "P"}
        result = await sub_management.handle_action("validate_product_for_subscription", {"product_id": "p1"})
        assert "Product Validation" in result[0].text

    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_handle_action_get_metrics(self, mock_get_client, sub_management, mock_client):
        mock_get_client.return_value = mock_client
        mock_client.get_subscriptions.return_value = {}
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {"totalElements": 0}
        result = await sub_management.handle_action("get_metrics", {})
        assert "Metrics" in result[0].text

    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_handle_action_search(self, mock_get_client, sub_management, mock_client):
        mock_get_client.return_value = mock_client
        mock_client.get_subscriptions.return_value = {}
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {}
        result = await sub_management.handle_action("search_subscriptions", {})
        assert "Search Results" in result[0].text

    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_handle_action_unknown(self, mock_get_client, sub_management, mock_client):
        mock_get_client.return_value = mock_client
        with pytest.raises(ToolError, match="Unknown action"):
            await sub_management.handle_action("invalid_action", {})

    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_handle_action_get_examples(self, mock_get_client, sub_management, mock_client):
        mock_get_client.return_value = mock_client
        sub_management.validator = SubscriptionValidator(ucm_integration_helper=None)
        result = await sub_management.handle_action("get_examples", {})
        assert "Examples" in result[0].text

    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_handle_action_get_capabilities(self, mock_get_client, sub_management, mock_client):
        mock_get_client.return_value = mock_client
        result = await sub_management.handle_action("get_capabilities", {})
        assert "Capabilities" in result[0].text

    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_handle_action_get_agent_summary(self, mock_get_client, sub_management, mock_client):
        mock_get_client.return_value = mock_client
        # Mock the formatter to return TextContent
        sub_management.formatter = MagicMock()
        sub_management.formatter.format_agent_summary_response.return_value = [
            TextContent(type="text", text="Agent summary")
        ]
        sub_management.formatter.start_timing = MagicMock()
        result = await sub_management.handle_action("get_agent_summary", {})
        assert len(result) >= 1

    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_handle_action_get_supporting_data(self, mock_get_client, sub_management, mock_client):
        mock_get_client.return_value = mock_client
        mock_client.get_organizations.return_value = {}
        mock_client.get_products.return_value = {}
        mock_client.get_subscribers.return_value = {}
        mock_client.get_credentials.return_value = {}
        mock_client._extract_embedded_data.return_value = []
        result = await sub_management.handle_action("get_supporting_data", {"data_type": "all"})
        assert "Supporting Data" in result[0].text

    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_handle_action_subscription_nlp(self, mock_get_client, sub_management, mock_client):
        mock_get_client.return_value = mock_client
        mock_client.get_subscriptions.return_value = {}
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {}
        result = await sub_management.handle_action("subscription_nlp", {"query": "find subscriptions"})
        assert "Natural Language" in result[0].text

    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_handle_action_validation_error(self, mock_get_client, sub_management, mock_client):
        mock_get_client.return_value = mock_client
        # Missing subscription_id should raise a ToolError
        with pytest.raises(ToolError):
            await sub_management.handle_action("get", {})


# ===========================================================================
# SubscriptionManagement — _handle_crud_actions create branch
# ===========================================================================


class TestHandleCrudCreate:
    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_create_auto_gen_missing_name(self, mock_get_client, sub_management, mock_client):
        mock_get_client.return_value = mock_client
        # BACK-2937: the refusal raises so the envelope carries isError.
        with pytest.raises(ToolError) as exc_info:
            await sub_management.handle_action("create", {"subscription_data": {}})
        assert "Missing Required Field" in exc_info.value.message
        assert "name" in exc_info.value.message

    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_create_auto_gen_no_products_available(self, mock_get_client, sub_management, mock_client):
        mock_get_client.return_value = mock_client
        mock_client.get_products.return_value = {}
        mock_client._extract_embedded_data.return_value = []
        # BACK-4709: the refusal raises so the envelope carries isError.
        with pytest.raises(ToolError) as exc_info:
            await sub_management.handle_action("create", {
                "subscription_data": {"name": "Test Sub"}
            })
        assert "No products available" in exc_info.value.message
        mock_client.create_subscription.assert_not_awaited()

    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_create_auto_gen_product_lookup_error_propagates(self, mock_get_client, sub_management, mock_client):
        mock_get_client.return_value = mock_client
        mock_client.get_products.side_effect = ReveniumAPIError("API fail", status_code=503)
        # BACK-4709: a failed product lookup is raised, never answered as plain text.
        with pytest.raises(ReveniumAPIError):
            await sub_management.handle_action("create", {
                "subscription_data": {"name": "Test Sub"}
            })
        mock_client.create_subscription.assert_not_awaited()

    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_create_auto_gen_dry_run(self, mock_get_client, sub_management, mock_client):
        mock_get_client.return_value = mock_client
        result = await sub_management.handle_action("create", {
            "subscription_data": {
                "name": "Test Sub",
                "product_id": "p1",
                "clientEmailAddress": "a@b.com",
            },
            "dry_run": True,
        })
        text = result[0].text
        assert "Dry Run Preview" in text
        assert "AUTO-GENERATION" in text
        # Nothing was filled in: the caller sent the address, and the platform
        # does not store a description, so none is generated.
        assert "**Auto-Generated Fields:** none" in text
        assert '"description"' not in text

    @pytest.mark.parametrize("default_email", [None, "   ", "dummy@email.com"])
    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_create_without_an_invoice_address_is_refused_not_invented(
        self, mock_get_client, default_email, sub_management, mock_client, monkeypatch
    ):
        if default_email is None:
            monkeypatch.delenv("REVENIUM_DEFAULT_EMAIL", raising=False)
        else:
            monkeypatch.setenv("REVENIUM_DEFAULT_EMAIL", default_email)
        mock_get_client.return_value = mock_client
        mock_client.create_subscription.return_value = {"id": "s_new"}

        with pytest.raises(ToolError) as exc:
            await sub_management.handle_action("create", {
                "subscription_data": {"name": "Sub", "product_id": "p1"},
            })

        assert exc.value.error_code == ErrorCodes.MISSING_PARAMETER
        assert exc.value.field == "clientEmailAddress"
        assert "example.com" not in exc.value.message
        assert "invoices" in exc.value.message
        assert '"name":"Sub","product_id":"p1"' in exc.value.message
        mock_client.create_subscription.assert_not_awaited()

    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_preview_without_an_invoice_address_is_refused(
        self, mock_get_client, sub_management, mock_client, monkeypatch
    ):
        monkeypatch.delenv("REVENIUM_DEFAULT_EMAIL", raising=False)
        mock_get_client.return_value = mock_client

        with pytest.raises(ToolError) as exc:
            await sub_management.handle_action("create", {
                "subscription_data": {"name": "Sub", "product_id": "p1"},
                "dry_run": True,
            })

        assert exc.value.field == "clientEmailAddress"
        assert "example.com" not in exc.value.message
        mock_client.create_subscription.assert_not_awaited()

    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_caller_blank_address_stays_refused_and_is_not_filled_from_the_default(
        self, mock_get_client, sub_management, mock_client, monkeypatch
    ):
        """Guard: a blank address the caller sent is a bad address, not a missing one."""
        monkeypatch.setenv("REVENIUM_DEFAULT_EMAIL", "default@test.com")
        mock_get_client.return_value = mock_client

        with pytest.raises(ToolError) as exc:
            await sub_management.handle_action("create", {
                "subscription_data": {
                    "name": "Sub",
                    "product_id": "p1",
                    "clientEmailAddress": "   ",
                },
            })

        assert exc.value.field == "clientEmailAddress"
        assert exc.value.error_code == ErrorCodes.VALIDATION_ERROR
        mock_client.create_subscription.assert_not_awaited()

    @pytest.mark.parametrize("dry_run", [True, False])
    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    @patch(
        "src.revenium_mcp_server.tools_decomposed.subscription_management.get_config_value",
        return_value="o1",
    )
    async def test_an_address_filled_from_the_default_says_where_it_came_from(
        self, mock_config, mock_get_client, dry_run, sub_management, mock_client, monkeypatch
    ):
        monkeypatch.setenv("REVENIUM_DEFAULT_EMAIL", "default@test.com")
        mock_get_client.return_value = mock_client
        mock_client.create_subscription.return_value = {"id": "s_new"}

        result = await sub_management.handle_action("create", {
            "subscription_data": {"name": "Sub", "product_id": "p1"},
            "dry_run": dry_run,
        })

        text = result[0].text
        assert (
            "Invoice address default@test.com came from REVENIUM_DEFAULT_EMAIL; "
            "pass clientEmailAddress to invoice someone else."
        ) in text

    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    @patch(
        "src.revenium_mcp_server.tools_decomposed.subscription_management.get_config_value",
        return_value="o1",
    )
    @pytest.mark.parametrize("unstored", ["description", "quotaNotificationThreshold"])
    async def test_create_says_which_fields_the_platform_does_not_store(
        self, mock_config, mock_get_client, sub_management, mock_client, unstored
    ):
        mock_get_client.return_value = mock_client
        mock_client.create_subscription.return_value = {"id": "s_new"}

        result = await sub_management.handle_action("create", {
            "subscription_data": {
                "name": "Sub",
                "product_id": "p1",
                "clientEmailAddress": "a@b.com",
                unstored: "kept nowhere",
            },
        })

        text = result[0].text
        assert "Created Successfully" in text
        assert f"Not stored by the platform: {unstored}." in text

    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    @patch("src.revenium_mcp_server.tools_decomposed.subscription_management.get_config_value", return_value="o1")
    async def test_create_auto_gen_with_explicit_product(self, mock_config, mock_get_client, sub_management, mock_client):
        mock_get_client.return_value = mock_client
        mock_client.create_subscription.return_value = {"id": "s_new"}
        result = await sub_management.handle_action("create", {
            "subscription_data": {
                "name": "Test Sub",
                "productId": "p1",
                "clientEmailAddress": "a@b.com",
            },
        })
        assert "Created Successfully" in result[0].text

    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    @patch("src.revenium_mcp_server.tools_decomposed.subscription_management.get_config_value", return_value="o1")
    @patch.dict("os.environ", {"REVENIUM_DEFAULT_EMAIL": "default@test.com"})
    async def test_create_auto_gen_email_from_env(self, mock_config, mock_get_client, sub_management, mock_client):
        mock_get_client.return_value = mock_client
        mock_client.create_subscription.return_value = {"id": "s_new"}
        result = await sub_management.handle_action("create", {
            "subscription_data": {"name": "Test Sub", "product_id": "p1"},
        })
        assert "Created Successfully" in result[0].text

    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_expert_mode_missing_product_is_refused_with_the_error_flag(
        self, mock_get_client, sub_management, mock_client
    ):
        mock_get_client.return_value = mock_client
        with pytest.raises(ToolError) as exc:
            await sub_management.handle_action("create", {
                "subscription_data": {"name": "Sub"},
                "auto_generate": False,
            })
        assert exc.value.field == "product_id"
        assert exc.value.error_code == ErrorCodes.MISSING_PARAMETER
        assert "Missing Required Field" in exc.value.message
        # Quick create asks which product to use; it no longer picks one.
        assert "auto_generate=true" not in exc.value.message
        assert "smart defaults" not in exc.value.message
        assert "asks which product to use" in exc.value.message
        assert "manage_products(action='list')" in exc.value.message
        mock_client.create_subscription.assert_not_awaited()

    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_expert_mode_missing_invoice_address_is_refused_with_the_error_flag(
        self, mock_get_client, sub_management, mock_client
    ):
        mock_get_client.return_value = mock_client
        with pytest.raises(ToolError) as exc:
            await sub_management.handle_action("create", {
                "subscription_data": {"name": "Sub", "product_id": "p1"},
                "auto_generate": False,
            })
        assert exc.value.field == "clientEmailAddress"
        assert exc.value.error_code == ErrorCodes.MISSING_PARAMETER
        assert "Missing Required Field" in exc.value.message
        # Quick create refuses a missing address too, so it is no way around it.
        assert "auto_generate=true" not in exc.value.message
        assert "REVENIUM_DEFAULT_EMAIL" in exc.value.message
        mock_client.create_subscription.assert_not_awaited()

    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_create_expert_mode_dry_run(self, mock_get_client, sub_management, mock_client):
        mock_get_client.return_value = mock_client
        result = await sub_management.handle_action("create", {
            "subscription_data": {
                "name": "Sub",
                "product_id": "p1",
                "clientEmailAddress": "a@b.com",
            },
            "auto_generate": False,
            "dry_run": True,
        })
        assert "Dry Run Preview" in result[0].text
        assert "EXPLICIT CONFIGURATION" in result[0].text


# ===========================================================================
# SubscriptionManagement — _handle_hierarchy_actions
# ===========================================================================


class TestHandleHierarchyActions:
    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_handle_get_product_details(self, mock_get_client, sub_management, mock_client):
        mock_get_client.return_value = mock_client
        nav_result = FakeNavigationResult(
            success=True,
            related_entities=[{"id": "p1", "name": "Product"}],
            navigation_path=["subscriptions", "products"],
        )
        with patch(
            "src.revenium_mcp_server.tools_decomposed.subscription_management.get_hierarchy_navigation_service"
        ) as mock_nav:
            mock_nav.return_value.get_product_for_subscription = AsyncMock(return_value=nav_result)
            result = await sub_management.handle_action("get_product_details", {"subscription_id": "s1"})
        assert "Product Details" in result[0].text

    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_handle_get_credentials(self, mock_get_client, sub_management, mock_client):
        mock_get_client.return_value = mock_client
        nav_result = FakeNavigationResult(
            success=True,
            related_entities=[{"id": "c1"}],
            navigation_path=["subscriptions", "credentials"],
        )
        with patch(
            "src.revenium_mcp_server.tools_decomposed.subscription_management.get_hierarchy_navigation_service"
        ) as mock_nav:
            mock_nav.return_value.get_credentials_for_subscription = AsyncMock(return_value=nav_result)
            result = await sub_management.handle_action("get_credentials", {"subscription_id": "s1"})
        assert "Credentials" in result[0].text

    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_handle_create_with_credentials_is_refused(
        self, mock_get_client, sub_management, mock_client
    ):
        mock_get_client.return_value = mock_client
        with pytest.raises(ToolError) as exc:
            await sub_management.handle_action("create_with_credentials", {
                "subscription_data": {"name": "S", "productId": "p1", "clientEmailAddress": "a@b.com"},
                "credentials_data": {"name": "Key", "type": "api_key"},
            })
        assert exc.value.error_code == ErrorCodes.ACTION_NOT_SUPPORTED
        mock_client.create_subscription.assert_not_awaited()


# ===========================================================================
# SubscriptionManagement — formatting methods
# ===========================================================================


class TestFormattingMethods:
    def test_format_capabilities_response(self, sub_management):
        caps = {
            "subscription_statuses": ["active", "trial"],
            "billing_periods": ["MONTH", "YEAR"],
            "trial_periods": ["DAY"],
            "currencies": ["USD", "EUR"],
            "schema": {
                "subscription_data": {
                    "required": ["product_id", "clientEmailAddress"],
                    "optional": ["description"],
                }
            },
            "lifecycle_states": {
                "creation": ["trial"],
                "active_states": ["active"],
                "terminal_states": ["cancelled"],
            },
            "business_rules": ["Rule 1"],
        }
        result = sub_management._format_capabilities_response(caps)
        assert len(result) == 1
        text = result[0].text
        assert "active" in text
        assert "MONTH" in text
        assert "USD" in text
        assert "Rule 1" in text

    def test_format_examples_response(self, sub_management):
        examples = {
            "examples": [
                {
                    "name": "Test Example",
                    "description": "A test",
                    "use_case": "Testing",
                    "note": "Important note",
                    "template": {"productId": "p1"},
                }
            ]
        }
        result = sub_management._format_examples_response(examples)
        assert "Test Example" in result[0].text
        assert "Important note" in result[0].text

    def test_format_examples_response_error(self, sub_management):
        examples = {"error": "Type not found", "type": "bad_type", "available_types": ["basic"]}
        with pytest.raises(ToolError):
            sub_management._format_examples_response(examples)

    def test_format_validation_response_valid(self, sub_management):
        result = sub_management._format_validation_response({
            "valid": True,
            "dry_run": True,
        })
        assert "Validation Successful" in result[0].text

    def test_format_validation_response_invalid(self, sub_management):
        result = sub_management._format_validation_response({
            "valid": False,
            "errors": [
                {"field": "product_id", "error": "Missing", "suggestion": "Add it", "valid_values": ["p1", "p2"]},
            ],
            "warnings": ["Check billing"],
            "suggestions": [
                {"type": "info", "message": "Consider X", "next_steps": ["Step 1"]},
                "Simple suggestion",
            ],
            "dry_run": True,
        })
        text = result[0].text
        assert "Validation Failed" in text
        assert "Missing" in text
        assert "Check billing" in text
        assert "Consider X" in text
        assert "Simple suggestion" in text

    async def test_build_enhanced_capabilities_text_no_ucm(self, sub_management):
        text = await sub_management._build_enhanced_capabilities_text(None)
        assert "Subscription Management Capabilities" in text
        assert "MONTH" in text
        assert "Business Rules" in text

    async def test_build_enhanced_capabilities_text_with_ucm(self, sub_management):
        ucm = {
            "billing_periods": ["MONTH", "YEAR"],
            "trial_periods": ["DAY", "WEEK"],
            "currencies": ["USD"],
            "schema": {
                "subscription_data": {
                    "required": ["product_id", "clientEmailAddress"],
                    "optional": ["description"],
                }
            },
            "lifecycle_states": {
                "creation": ["trial"],
                "active_states": ["active"],
                "terminal_states": ["cancelled"],
            },
        }
        text = await sub_management._build_enhanced_capabilities_text(ucm)
        assert "MONTH" in text
        assert "DAY" in text
        assert "USD" in text

    async def test_handle_get_capabilities_with_ucm(self, sub_management):
        mock_ucm = MagicMock()
        mock_ucm.ucm = MagicMock()
        mock_ucm.ucm.get_capabilities = AsyncMock(return_value={
            "billing_periods": ["MONTH"],
            "trial_periods": ["DAY"],
            "currencies": ["USD"],
        })
        sub_management.ucm_helper = mock_ucm
        result = await sub_management._handle_get_capabilities()
        assert "Capabilities" in result[0].text

    async def test_handle_get_capabilities_ucm_exception(self, sub_management):
        mock_ucm = MagicMock()
        mock_ucm.ucm = MagicMock()
        mock_ucm.ucm.get_capabilities = AsyncMock(side_effect=Exception("UCM down"))
        sub_management.ucm_helper = mock_ucm
        result = await sub_management._handle_get_capabilities()
        # Falls back to static capabilities
        assert "Capabilities" in result[0].text

    async def test_handle_get_capabilities_ucm_tool_error(self, sub_management):
        mock_ucm = MagicMock()
        mock_ucm.ucm = MagicMock()
        mock_ucm.ucm.get_capabilities = AsyncMock(
            side_effect=ToolError(message="UCM err", error_code="UCM_ERROR")
        )
        sub_management.ucm_helper = mock_ucm
        with pytest.raises(ToolError):
            await sub_management._handle_get_capabilities()


# ===========================================================================
# SubscriptionManagement — validate action
# ===========================================================================


class TestValidateAction:
    async def test_handle_validate_missing_data(self, sub_management):
        with pytest.raises(ToolError):
            await sub_management._handle_validate_action({})

    async def test_handle_validate_success(self, sub_management):
        mock_schema = MagicMock()
        mock_schema.validate_subscription_configuration.return_value = {
            "valid": True,
            "dry_run": True,
        }
        sub_management.validator = SubscriptionValidator(ucm_integration_helper=None)
        sub_management.validator.schema_discovery = mock_schema
        result = await sub_management._handle_validate_action({
            "subscription_data": {"productId": "p1"},
            "dry_run": True,
        })
        assert "Validation Successful" in result[0].text


# ===========================================================================
# SubscriptionManagement — metadata provider methods
# ===========================================================================


class TestMetadataProvider:
    async def test_get_tool_capabilities(self, sub_management):
        caps = await sub_management._get_tool_capabilities()
        # The read-only "Subscription Billing Reads" capability is included.
        assert len(caps) == 3
        # The create shortcuts are not routed, so they are not advertised (BACK-4709).
        assert not any(c.name == "Enhanced Creation" for c in caps)
        assert caps[0].name == "Subscription CRUD Operations"
        assert any(c.name == "Subscription Billing Reads" for c in caps)

    async def test_get_supported_actions(self, sub_management):
        actions = await sub_management._get_supported_actions()
        assert "list" in actions
        assert "create_with_credentials" not in actions

    async def test_get_input_schema(self, sub_management):
        schema = await sub_management._get_input_schema()
        assert schema["type"] == "object"
        assert "action" in schema["properties"]

    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_create_with_credentials_is_no_longer_advertised(
        self, mock_get_client, sub_management, mock_client
    ):
        """It wrote a subscription and then a credential with no preview and no
        rollback; the two-step route through manage_subscriber_credentials
        replaces it."""
        mock_get_client.return_value = mock_client
        actions = await sub_management._get_supported_actions()
        schema = await sub_management._get_input_schema()
        capabilities = (await sub_management._handle_get_capabilities())[0].text

        assert "create_with_credentials" not in actions
        assert "create_with_credentials" not in schema["properties"]["action"]["enum"]
        assert "create_with_credentials" not in capabilities
        with pytest.raises(ToolError) as exc:
            await sub_management.handle_action(
                "create_with_credentials",
                {
                    "subscription_data": {"name": "S", "productId": "p1"},
                    "credentials_data": {"name": "Key"},
                },
            )
        assert exc.value.error_code == ErrorCodes.ACTION_NOT_SUPPORTED
        mock_client.create_subscription.assert_not_awaited()
        mock_client.create_credential.assert_not_awaited()

    async def test_get_capabilities_names_every_top_level_input_it_describes(
        self, sub_management
    ):
        """Every top-level input the help lists is one the registered tool accepts,
        and the help lists the inputs the search, data, question and template
        actions read."""
        import inspect
        import re

        from src.revenium_mcp_server.tool_configuration.config import ToolConfig
        from src.revenium_mcp_server.tool_configuration.registry import (
            ToolConfigurationRegistry,
        )

        mcp = MagicMock()
        registry = ToolConfigurationRegistry(
            tool_config=ToolConfig.create_for_testing(profile="business")
        )
        await registry._register_manage_subscriptions(mcp)
        closure = mcp.tool.return_value.call_args[0][0]
        declared = set(inspect.signature(closure).parameters)

        text = (await sub_management._handle_get_capabilities())[0].text
        block = text.split("**Top-level parameters**", 1)[1].split("\n\n", 1)[0]
        listed = {
            name
            for line in block.splitlines()
            if line.startswith("- ")
            for name in re.findall(r"`([A-Za-z_]+)`", line.split(" - ", 1)[0])
        }

        assert sorted(listed - declared) == []
        for name in ("search_query", "product_name", "data_type", "query", "example_type"):
            assert name in listed, name

    async def test_get_tool_dependencies(self, sub_management):
        deps = await sub_management._get_tool_dependencies()
        assert len(deps) == 1
        assert deps[0].tool_name == "manage_alerts"

    async def test_get_resource_relationships(self, sub_management):
        rels = await sub_management._get_resource_relationships()
        assert len(rels) >= 4

    async def test_get_usage_patterns(self, sub_management):
        patterns = await sub_management._get_usage_patterns()
        assert len(patterns) == 4

    async def test_get_agent_summary(self, sub_management):
        summary = await sub_management._get_agent_summary()
        assert "Subscription Management" in summary

    async def test_get_quick_start_guide(self, sub_management):
        guide = await sub_management._get_quick_start_guide()
        assert len(guide) >= 5


# ===========================================================================
# SubscriptionManagement — handle_action exception re-raising
# ===========================================================================


class TestHandleActionExceptions:
    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_reraise_revenium_api_error(self, mock_get_client, sub_management, mock_client):
        from src.revenium_mcp_server.client import ReveniumAPIError
        mock_get_client.return_value = mock_client
        mock_client.get_subscription_by_id.side_effect = ReveniumAPIError("fail", status_code=500)
        with pytest.raises(ReveniumAPIError):
            await sub_management.handle_action("get", {"subscription_id": "s1"})

    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_reraise_generic_exception(self, mock_get_client, sub_management, mock_client):
        mock_get_client.side_effect = RuntimeError("unexpected")
        with pytest.raises(RuntimeError):
            await sub_management.handle_action("list", {})

    @patch.object(SubscriptionManagement, "get_client", new_callable=AsyncMock)
    async def test_handle_action_get_tool_metadata(self, mock_get_client, sub_management, mock_client):
        mock_get_client.return_value = mock_client
        sub_management.get_tool_metadata = AsyncMock(return_value=MagicMock(
            to_dict=MagicMock(return_value={"tool": "manage_subscriptions"})
        ))
        result = await sub_management.handle_action("get_tool_metadata", {})
        assert "manage_subscriptions" in result[0].text


# ===========================================================================
# Name-only create asks which product (BACK-4709)
# ===========================================================================


def _products_answer(products, total=None):
    """Answer the product list with `products`; fail any other request."""

    def answer(method, url, params):
        if method == "GET" and url.endswith("/profitstream/v2/api/products"):
            return {
                "_embedded": {"productResourceList": products},
                "page": {
                    "size": 5,
                    "totalElements": len(products) if total is None else total,
                    "totalPages": 1,
                    "number": 0,
                },
            }
        raise AssertionError(f"unexpected {method} {url}")

    return answer


class TestQuickCreateAsksWhichProduct:
    """A create with only a name asks for the product through the real client."""

    async def test_name_only_create_asks_which_product_with_the_error_flag(self, monkeypatch):
        client, requests = recording_client(
            monkeypatch,
            _products_answer(
                [
                    {"id": "p1", "name": "Gold", "published": True},
                    {"id": "p2", "name": "Silver", "published": True},
                ]
            ),
        )
        tool = SubscriptionManagement()

        with patch.object(tool, "get_client", new_callable=AsyncMock, return_value=client):
            with pytest.raises(ToolError) as exc:
                await tool.handle_action("create", {"subscription_data": {"name": "Monthly"}})

        assert exc.value.field == "product_id"
        assert exc.value.error_code == ErrorCodes.MISSING_PARAMETER
        assert "Gold (p1)" in exc.value.message
        assert "Silver (p2)" in exc.value.message
        assert "clientEmailAddress" in exc.value.message
        assert [(r["method"], r["url"].endswith("/profitstream/v2/api/products")) for r in requests] == [
            ("GET", True)
        ]

    async def test_retry_example_keeps_the_fields_the_caller_sent(self, monkeypatch):
        client, _ = recording_client(
            monkeypatch,
            _products_answer([{"id": "p1", "name": "Gold", "published": True}]),
        )
        tool = SubscriptionManagement()

        with patch.object(tool, "get_client", new_callable=AsyncMock, return_value=client):
            with pytest.raises(ToolError) as exc:
                await tool.handle_action(
                    "create",
                    {
                        "subscription_data": {
                            "name": "Monthly",
                            "clientEmailAddress": "jane@acme.com",
                            "expiration": "2027-01-01",
                        }
                    },
                )

        message = exc.value.message
        assert exc.value.field == "product_id"
        assert '"clientEmailAddress":"jane@acme.com"' in message
        assert '"expiration":"2027-01-01"' in message
        assert '"product_id":"<id>"' in message
        assert "<invoice address>" not in message
        assert "Also supply" not in message

    async def test_name_only_create_with_no_products_refuses_with_the_error_flag(self, monkeypatch):
        client, requests = recording_client(monkeypatch, _products_answer([]))
        tool = SubscriptionManagement()

        with patch.object(tool, "get_client", new_callable=AsyncMock, return_value=client):
            with pytest.raises(ToolError) as exc:
                await tool.handle_action("create", {"subscription_data": {"name": "Monthly"}})

        assert exc.value.field == "product_id"
        assert exc.value.error_code == ErrorCodes.MISSING_PARAMETER
        assert "No products available" in exc.value.message
        assert "this organization has none" in exc.value.message
        assert all(r["method"] == "GET" for r in requests)

    async def test_more_products_than_shown_says_how_many_and_where_to_see_the_rest(
        self, monkeypatch
    ):
        client, _ = recording_client(
            monkeypatch,
            _products_answer(
                [
                    {"id": "p1", "name": "Gold", "published": True},
                    {"id": "p2", "name": "Draft", "published": False},
                ],
                total=12,
            ),
        )
        tool = SubscriptionManagement()

        with patch.object(tool, "get_client", new_callable=AsyncMock, return_value=client):
            with pytest.raises(ToolError) as exc:
                await tool.handle_action("create", {"subscription_data": {"name": "Monthly"}})

        assert "Draft (p2, unpublished)" in exc.value.message
        assert "showing 2 of 12" in exc.value.message
        assert "discover_products" in exc.value.message

    def test_every_client_method_the_subscription_tool_calls_exists(self):
        source = inspect.getsource(subscription_management)
        called = set(re.findall(r"client\.([A-Za-z_]\w*)\(", source))

        missing = sorted(name for name in called if not hasattr(ReveniumClient, name))

        assert missing == []
