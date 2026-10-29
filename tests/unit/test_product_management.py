"""Unit tests for Product Management tools.

Tests the ProductManager and ProductManagement classes from the decomposed tools module.
Focuses on CRUD operations, validation logic, and error handling paths.
"""

import asyncio
import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.tools_decomposed.product_management import (
    ProductManager,
    ProductManagement,
    ProductValidator,
)
from src.revenium_mcp_server.api_field_mapper import APIFieldMapper
from src.revenium_mcp_server.auth import AuthConfig
from src.revenium_mcp_server.client import ReveniumAPIError, ReveniumClient
from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError
from mcp.types import TextContent


STORED_PRODUCT = {
    "id": "prod_1",
    "name": "Gold",
    "version": "1.0.0",
    "description": "old",
    "paymentSource": "INVOICE_ONLY_NO_PAYMENT",
    "plan": {
        "type": "SUBSCRIPTION",
        "name": "Gold plan",
        "currency": "USD",
        "tiers": [{"name": "Tier 1", "up_to": None, "unit_amount": "0.01"}],
    },
}

PREVIEW_BODY_HEADING = "**Body the update would send:**"


def _recording_product_client() -> ReveniumClient:
    """A real client whose product GET serves STORED_PRODUCT and whose PUT is recorded."""
    client = ReveniumClient(
        auth_config=AuthConfig(
            api_key="test-key-xyz",
            team_id="team_abc",
            base_url="https://api.test.revenium.ai",
            timeout=5.0,
            max_retries=0,
        )
    )
    client.get_product_by_id = AsyncMock(return_value=json.loads(json.dumps(STORED_PRODUCT)))
    client.put = AsyncMock(return_value={"id": "prod_1"})
    return client


def _previewed_body(preview_text: str) -> dict:
    assert PREVIEW_BODY_HEADING in preview_text
    body_text = preview_text.split(PREVIEW_BODY_HEADING, 1)[1].split("**Dry Run:**", 1)[0]
    return json.loads(body_text)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_client():
    """Create a mock ReveniumClient for ProductManager."""
    client = MagicMock()
    client.team_id = "test_team_id_456"
    client.get_products = AsyncMock()
    client.get_product_by_id = AsyncMock()
    client.create_product = AsyncMock()
    client.update_product = AsyncMock()
    client.delete_product = AsyncMock()
    client.get_sources = AsyncMock()
    client._extract_embedded_data = MagicMock()
    client._extract_pagination_info = MagicMock()
    return client


@pytest.fixture
def product_manager(mock_client):
    """Create ProductManager with mocked client."""
    return ProductManager(mock_client)


@pytest.fixture
def product_mgmt():
    """Create ProductManagement instance (top-level tool)."""
    return ProductManagement()


# ===========================================================================
# ProductManager CRUD Tests
# ===========================================================================


class TestProductManagerList:
    """Test ProductManager.list_products behavior."""

    @pytest.mark.asyncio
    async def test_list_products_returns_paginated_result(self, product_manager, mock_client):
        """Listing products returns data with pagination metadata."""
        mock_client.get_products.return_value = {"_embedded": {"products": []}}
        mock_client._extract_embedded_data.return_value = [
            {"id": "p1", "name": "Product A"},
            {"id": "p2", "name": "Product B"},
        ]
        mock_client._extract_pagination_info.return_value = {
            "totalPages": 3,
            "totalElements": 25,
        }

        result = await product_manager.list_products({"page": 1, "size": 10})

        assert result["action"] == "list"
        assert len(result["data"]) == 2
        assert result["pagination"]["page"] == 1
        assert result["pagination"]["size"] == 10
        assert result["pagination"]["total_pages"] == 3
        assert result["pagination"]["total_items"] == 25
        assert result["pagination"]["has_next"] is True
        assert result["pagination"]["has_previous"] is True
        mock_client.get_products.assert_called_once_with(page=1, size=10)

    @pytest.mark.asyncio
    async def test_list_products_defaults_page_zero(self, product_manager, mock_client):
        """Listing without explicit page/size uses defaults."""
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {"totalPages": 1, "totalElements": 0}

        result = await product_manager.list_products({})

        mock_client.get_products.assert_called_once_with(page=0, size=20)
        assert result["pagination"]["has_previous"] is False

    @pytest.mark.asyncio
    async def test_list_products_last_page_has_no_next(self, product_manager, mock_client):
        """has_next is False when on the last page."""
        mock_client._extract_embedded_data.return_value = [{"id": "p1"}]
        mock_client._extract_pagination_info.return_value = {"totalPages": 2, "totalElements": 12}

        result = await product_manager.list_products({"page": 1, "size": 10})

        assert result["pagination"]["has_next"] is False

    @pytest.mark.asyncio
    async def test_list_products_rejects_string_page_with_structured_error(
        self, product_manager, mock_client
    ):
        """Wrong-type page must raise a structured ToolError before reaching the client.

        BACK-1112 audit shape — page='not_a_number' previously crashed inside
        validate_pagination_with_performance with a Python TypeError ("'<' not
        supported between instances of 'str' and 'int'") that leaked to the caller.
        """
        from src.revenium_mcp_server.common.error_handling import ToolError

        with pytest.raises(ToolError) as exc_info:
            await product_manager.list_products({"page": "not_a_number"})

        err = exc_info.value
        assert getattr(err, "field", None) == "page"
        # No raw Python TypeError leak
        assert "not supported between instances" not in str(err)
        # Must not have reached the client
        mock_client.get_products.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_products_rejects_negative_page(self, product_manager, mock_client):
        """Negative page surfaces as a structured 400."""
        from src.revenium_mcp_server.common.error_handling import ToolError

        with pytest.raises(ToolError) as exc_info:
            await product_manager.list_products({"page": -1})

        assert getattr(exc_info.value, "field", None) == "page"
        mock_client.get_products.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_products_rejects_string_size_with_structured_error(
        self, product_manager, mock_client
    ):
        """Wrong-type size must raise a structured ToolError before reaching the client.

        Mirrors the page wrong-type guard: size='big' must not crash inside
        validate_pagination_with_performance and must surface as a structured 400.
        """
        from src.revenium_mcp_server.common.error_handling import ToolError

        with pytest.raises(ToolError) as exc_info:
            await product_manager.list_products({"page": 0, "size": "big"})

        err = exc_info.value
        assert getattr(err, "field", None) == "size"
        # No raw Python TypeError leak
        assert "not supported between instances" not in str(err)
        mock_client.get_products.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_products_rejects_oversized_size(self, product_manager, mock_client):
        """size above the configured maximum surfaces as a structured 400."""
        from src.revenium_mcp_server.common.error_handling import ToolError

        with pytest.raises(ToolError) as exc_info:
            await product_manager.list_products({"page": 0, "size": 99999})

        assert getattr(exc_info.value, "field", None) == "size"
        mock_client.get_products.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_products_rejects_bool_page(self, product_manager, mock_client):
        """Boolean page (True/False) must be rejected as wrong-type, not silently coerced.

        Python's bool is a subclass of int, so `isinstance(True, int)` is True. The
        guard must explicitly reject booleans to avoid passing True/False to the API.
        """
        from src.revenium_mcp_server.common.error_handling import ToolError

        with pytest.raises(ToolError) as exc_info:
            await product_manager.list_products({"page": True})

        assert getattr(exc_info.value, "field", None) == "page"
        mock_client.get_products.assert_not_called()

        with pytest.raises(ToolError) as exc_info:
            await product_manager.list_products({"page": False, "size": 10})

        # False is also an int subclass; should be rejected just like True.
        assert getattr(exc_info.value, "field", None) == "page"
        mock_client.get_products.assert_not_called()


class TestProductManagerGet:
    """Test ProductManager.get_product behavior."""

    @pytest.mark.asyncio
    async def test_get_product_returns_data(self, product_manager, mock_client):
        """Getting a product by ID returns it wrapped with metadata."""
        mock_client.get_product_by_id.return_value = {"id": "p1", "name": "My Product"}

        result = await product_manager.get_product({"product_id": "p1"})

        assert result["action"] == "get"
        assert result["product_id"] == "p1"
        assert result["data"]["name"] == "My Product"
        mock_client.get_product_by_id.assert_called_once_with("p1")

    @pytest.mark.asyncio
    async def test_get_product_missing_id_raises_error(self, product_manager):
        """Getting a product without product_id raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await product_manager.get_product({})

        assert "product_id" in str(exc_info.value).lower()


class TestProductManagerCreate:
    """Test ProductManager.create_product behavior."""

    @pytest.mark.asyncio
    async def test_create_product_from_name_auto_generates_data(self, product_manager, mock_client):
        """Auto-generation mode builds product_data from name only."""
        mock_client.get_sources.return_value = {"_embedded": {"sources": []}}
        mock_client._extract_embedded_data.return_value = [{"id": "src_1"}]
        mock_client.create_product.return_value = {"id": "p_new", "name": "My API"}

        with patch(
            "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
        ) as MockEngine:
            MockEngine.validate_for_mcp.return_value = {"isError": False, "content": []}
            with patch(
                "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
                return_value=None,
            ):
                result = await product_manager.create_product({"name": "My API", "auto_generate": True})

        assert result["action"] == "create"
        assert result["data"]["id"] == "p_new"
        # Verify product was created with auto-generated data
        create_call_data = mock_client.create_product.call_args[0][0]
        assert create_call_data["name"] == "My API"
        assert "plan" in create_call_data
        assert create_call_data["teamId"] == "test_team_id_456"

    @pytest.mark.asyncio
    async def test_create_product_missing_all_params_raises_error(self, product_manager):
        """Create without product_data, description, or name raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await product_manager.create_product({"auto_generate": False})

        assert "product_data" in str(exc_info.value).lower() or "description" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_create_product_with_description_nlp_fallback(self, product_manager, mock_client):
        """Create with description but no NLP processor uses fallback parsing."""
        mock_client.get_sources.return_value = {}
        mock_client._extract_embedded_data.return_value = []
        mock_client.create_product.return_value = {"id": "p_nlp", "name": "API Service"}

        with patch(
            "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
        ) as MockEngine:
            MockEngine.validate_for_mcp.return_value = {"isError": False, "content": []}
            with patch(
                "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
                return_value=None,
            ):
                result = await product_manager.create_product(
                    {"description": "A premium API access plan"}
                )

        assert result["action"] == "create"
        create_call_data = mock_client.create_product.call_args[0][0]
        # Fallback parsing should detect "api" and set name
        assert create_call_data["name"] == "API Service"

    @pytest.mark.asyncio
    async def test_create_product_validation_failure_raises(self, product_manager, mock_client):
        """Create raises when ProductValidationEngine reports errors."""
        mock_client.get_sources.return_value = {}
        mock_client._extract_embedded_data.return_value = []

        with patch(
            "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
        ) as MockEngine:
            MockEngine.validate_for_mcp.return_value = {
                "isError": True,
                "content": [{"text": "Deprecated paymentSource value"}],
            }
            with patch(
                "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
                return_value=None,
            ):
                with pytest.raises(ToolError) as exc_info:
                    await product_manager.create_product(
                        {"name": "Bad Product", "auto_generate": True}
                    )

                assert "validation" in str(exc_info.value).lower() or "deprecated" in str(exc_info.value).lower()

    async def _create_and_map(self, product_manager, mock_client, product_data):
        mock_client.get_sources.return_value = {}
        mock_client._extract_embedded_data.return_value = [{"id": "default_src"}]
        mock_client.create_product.return_value = {"id": "p_new", "name": "P"}
        with patch(
            "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
        ) as MockEngine:
            MockEngine.validate_for_mcp.return_value = {"isError": False, "content": []}
            with patch(
                "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
                return_value=None,
            ):
                await product_manager.create_product({"product_data": product_data})
        return APIFieldMapper.map_product_fields(mock_client.create_product.call_args[0][0])

    @pytest.mark.asyncio
    async def test_minimal_create_body_has_no_invented_source_and_is_not_published(
        self, product_manager, mock_client
    ):
        """BACK-4662: a product created without naming a source stays a draft."""
        body = await self._create_and_map(
            product_manager,
            mock_client,
            {"name": "P", "version": "1.0.0", "plan": {"name": "PP", "tiers": [{"name": "t"}]}},
        )
        assert body["published"] is False
        assert "sourceIds" not in body
        assert mock_client.get_sources.await_count == 0

    @pytest.mark.asyncio
    async def test_snake_case_source_ids_are_not_replaced_by_a_default(
        self, product_manager, mock_client
    ):
        body = await self._create_and_map(
            product_manager,
            mock_client,
            {"name": "P", "version": "1.0.0", "plan": {"name": "PP"}, "source_ids": ["own_src"]},
        )
        assert body["sourceIds"] == ["own_src"]

    @pytest.mark.asyncio
    async def test_explicit_published_and_source_ids_are_sent_as_given(
        self, product_manager, mock_client
    ):
        body = await self._create_and_map(
            product_manager,
            mock_client,
            {
                "name": "P",
                "version": "1.0.0",
                "plan": {"name": "PP"},
                "published": True,
                "sourceIds": ["own_src"],
            },
        )
        assert body["published"] is True
        assert body["sourceIds"] == ["own_src"]
        assert mock_client.get_sources.await_count == 0

    @pytest.mark.asyncio
    async def test_both_source_spellings_camel_wins(self, product_manager, mock_client):
        body = await self._create_and_map(
            product_manager,
            mock_client,
            {
                "name": "P",
                "version": "1.0.0",
                "plan": {"name": "PP"},
                "sourceIds": ["camel"],
                "source_ids": ["snake"],
            },
        )
        assert body["sourceIds"] == ["camel"]

    @pytest.mark.asyncio
    async def test_empty_camel_source_list_still_wins_over_snake(
        self, product_manager, mock_client
    ):
        body = await self._create_and_map(
            product_manager,
            mock_client,
            {
                "name": "P",
                "version": "1.0.0",
                "plan": {"name": "PP"},
                "sourceIds": [],
                "source_ids": ["snake"],
            },
        )
        assert body.get("sourceIds") in (None, [])

    @pytest.mark.asyncio
    async def test_explicit_null_published_is_sent_as_false(self, product_manager, mock_client):
        body = await self._create_and_map(
            product_manager,
            mock_client,
            {"name": "P", "version": "1.0.0", "plan": {"name": "PP"}, "published": None},
        )
        assert body["published"] is False

    @staticmethod
    def _usage_based_product_data(**extra):
        return {
            "name": "P",
            "version": "1.0.0",
            "description": "d",
            "paymentSource": "INVOICE_ONLY_NO_PAYMENT",
            "plan": {
                "name": "PP",
                "type": "SUBSCRIPTION",
                "currency": "USD",
                "period": "MONTH",
                "tiers": [],
                "ratingAggregations": [
                    {
                        "name": "a",
                        "elementDefinitionId": "e1",
                        "aggregationType": "SUM",
                        "tiers": [{"name": "u", "up_to": None, "unit_amount": "0.01"}],
                    }
                ],
            },
            **extra,
        }

    @pytest.mark.asyncio
    async def test_usage_based_create_keeps_snake_case_source_ids(
        self, product_manager, mock_client
    ):
        mock_client.get_sources.return_value = {}
        mock_client._extract_embedded_data.return_value = [{"id": "default_src"}]
        mock_client.create_product.return_value = {"id": "p_new", "name": "P"}
        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            await product_manager.create_product(
                {"product_data": self._usage_based_product_data(source_ids=["own_src"])}
            )
        body = APIFieldMapper.map_product_fields(mock_client.create_product.call_args[0][0])
        assert body["sourceIds"] == ["own_src"]

    @pytest.mark.asyncio
    async def test_usage_based_create_without_source_is_refused_with_a_usable_hint(
        self, product_manager, mock_client
    ):
        mock_client.get_sources.return_value = {}
        mock_client._extract_embedded_data.return_value = [{"id": "default_src"}]
        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            with pytest.raises(ToolError) as exc_info:
                await product_manager.create_product(
                    {"product_data": self._usage_based_product_data()}
                )
        text = str(exc_info.value.message)
        assert "get_sources(action='list')" in text
        assert "QOjOkbW" not in text
        mock_client.create_product.assert_not_awaited()


class TestCreateAnswerStatesWhatWasDone:
    """BACK-4662: the create answer says whether the product is published and
    which data sources it has, and only advises subscribing when it can take one."""

    @staticmethod
    def _answer(product):
        return ProductManagement()._format_create_success_response({"data": product})[0].text

    def test_unpublished_create_says_so_on_the_first_line(self):
        first = self._answer(
            {"id": "p1", "name": "P", "published": False, "sources": []}
        ).splitlines()[0]
        assert "not published" in first
        assert "No data source" in first

    def test_published_create_names_its_sources(self):
        first = self._answer(
            {"id": "p1", "name": "P", "published": True, "sources": [{"id": "s1", "label": "Main"}]}
        ).splitlines()[0]
        assert "is published" in first
        assert "s1" in first

    def test_unpublished_create_does_not_advise_subscribing(self):
        text = self._answer({"id": "p1", "name": "P", "published": False, "sources": []})
        assert 'manage_subscriptions(action="create"' not in text
        assert "'published': True" in text

    def test_published_create_with_a_source_advises_subscribing(self):
        text = self._answer(
            {"id": "p1", "name": "P", "published": True, "sources": [{"id": "s1"}]}
        )
        assert 'manage_subscriptions(action="create"' in text

    def test_published_create_without_a_source_does_not_advise_subscribing(self):
        text = self._answer({"id": "p1", "name": "P", "published": True, "sources": []})
        assert 'manage_subscriptions(action="create"' not in text
        assert "'sourceIds'" in text
        assert "get_sources(action='list')" in text

    def test_published_create_without_a_source_asks_only_for_a_source(self):
        text = self._answer({"id": "p1", "name": "P", "published": True, "sources": []})
        assert "attach a data source" in text
        assert "publish it" not in text
        assert "'published': True" not in text

    def test_unpublished_create_with_a_source_asks_only_to_publish(self):
        text = self._answer(
            {"id": "p1", "name": "P", "published": False, "sources": [{"id": "s1"}]}
        )
        assert "publish it" in text
        assert "attach a data source" not in text
        assert "'sourceIds'" not in text

    def test_answer_without_published_or_sources_adds_no_claim(self):
        first = self._answer({"id": "p1", "name": "P"}).splitlines()[0]
        assert first == "✅ Product 'P' created successfully"


class TestProductManagerUpdate:
    """Test ProductManager.update_product behavior."""

    @pytest.mark.asyncio
    async def test_update_product_missing_id_raises_error(self, product_manager):
        """Update without product_id raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await product_manager.update_product({"product_data": {"name": "New"}})

        assert "product_id" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_update_product_missing_data_raises_error(self, product_manager):
        """Update without product_data raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await product_manager.update_product({"product_id": "p1"})

        assert "product_data" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_update_product_delegates_to_partial_handler(self, product_manager, mock_client):
        """Update with valid params delegates to PartialUpdateHandler."""
        product_manager.update_handler.update_with_merge = AsyncMock(
            return_value={"id": "p1", "name": "Updated"}
        )
        product_manager.update_config_factory.get_config = MagicMock(return_value={"resource_type": "products"})

        result = await product_manager.update_product(
            {"product_id": "p1", "product_data": {"name": "Updated"}}
        )

        assert result["action"] == "update"
        assert result["product_id"] == "p1"
        product_manager.update_handler.update_with_merge.assert_called_once()


class TestProductManagerDelete:
    """Test ProductManager.delete_product behavior."""

    @pytest.mark.asyncio
    async def test_delete_product_missing_id_raises_error(self, product_manager):
        """Delete without product_id raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await product_manager.delete_product({})

        assert "product_id" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_delete_product_succeeds(self, product_manager, mock_client):
        """Delete with valid product_id calls client and returns result."""
        mock_client.delete_product.return_value = {"deleted": True}

        result = await product_manager.delete_product({"product_id": "p_del"})

        assert result["action"] == "delete"
        assert result["product_id"] == "p_del"
        mock_client.delete_product.assert_called_once_with("p_del")


# ===========================================================================
# ProductManagement handle_action routing tests
# ===========================================================================


class TestProductManagementHandleAction:
    """Test ProductManagement.handle_action routing and dry-run modes."""

    @pytest.mark.asyncio
    async def test_unknown_action_raises_tool_error(self, product_mgmt):
        """Unknown action raises ToolError so the MCP envelope reports isError=true."""
        from src.revenium_mcp_server.common.error_handling import ToolError

        with patch.object(product_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = MagicMock()

            with pytest.raises(ToolError) as exc_info:
                await product_mgmt.handle_action("nonexistent_action", {})

        assert "not supported" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_create_dry_run_returns_preview(self, product_mgmt):
        """Create with dry_run=True returns validation preview without creating."""
        with patch.object(product_mgmt, "get_client", new_callable=AsyncMock) as mock_gc, patch(
            "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
        ) as MockEngine, patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            MockEngine.validate_for_mcp.return_value = {"isError": False, "content": []}
            mock_client = MagicMock()
            mock_client.team_id = "team_test"
            mock_client.get_sources = AsyncMock(return_value={})
            mock_client._extract_embedded_data = MagicMock(return_value=[])
            mock_gc.return_value = mock_client

            result = await product_mgmt.handle_action(
                "create",
                {"product_data": {"name": "Test"}, "dry_run": True},
            )

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
        assert "DRY RUN" in result[0].text
        # Crucially, no create call was made
        assert not mock_client.create_product.called

    @pytest.mark.asyncio
    async def test_update_dry_run_returns_preview(self, product_mgmt):
        """Update with dry_run=True returns preview without updating."""
        client = _recording_product_client()
        with patch.object(product_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = client

            result = await product_mgmt.handle_action(
                "update",
                {"product_id": "prod_1", "product_data": {"name": "New"}, "dry_run": True},
            )

        assert len(result) >= 1
        assert "DRY RUN" in result[0].text
        assert "prod_1" in result[0].text
        assert _previewed_body(result[0].text)["name"] == "New"
        assert client.put.await_count == 0

    @pytest.mark.asyncio
    async def test_update_dry_run_for_a_missing_product_raises_not_found(self, product_mgmt):
        """A preview of an edit to a product that does not exist fails like the get does."""
        client = MagicMock()
        client.team_id = "test_team_id_456"
        client.get_product_by_id = AsyncMock(
            side_effect=ReveniumAPIError("Invalid Product ID", status_code=404)
        )
        client.update_product = AsyncMock()
        with patch.object(product_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = client
            with pytest.raises(ReveniumAPIError) as not_found:
                await product_mgmt.handle_action(
                    "update",
                    {
                        "product_id": "doesNotExist9",
                        "product_data": {"description": "x"},
                        "dry_run": True,
                    },
                )

        assert "Invalid Product ID" in not_found.value.message
        client.update_product.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_dry_run_read_timeout_raises_the_update_timeout_error(self, product_mgmt):
        """A preview whose product read times out fails with the update's timeout error."""
        client = _recording_product_client()
        client.get_product_by_id = AsyncMock(side_effect=asyncio.TimeoutError())
        arguments = {"product_id": "prod_1", "product_data": {"description": "x"}}
        with patch.object(product_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = client
            with pytest.raises(ToolError) as update_timeout:
                await product_mgmt.handle_action("update", arguments)
            with pytest.raises(ToolError) as preview_timeout:
                await product_mgmt.handle_action("update", {**arguments, "dry_run": True})

        assert preview_timeout.value.error_code == ErrorCodes.API_TIMEOUT
        assert preview_timeout.value.message == update_timeout.value.message

    @pytest.mark.asyncio
    async def test_update_dry_run_body_equals_the_put_body_the_update_sends(self, product_mgmt):
        """The preview shows exactly the body the real update would PUT."""
        client = _recording_product_client()
        arguments = {"product_id": "prod_1", "product_data": {"description": "x"}}
        with patch.object(product_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = client
            preview = await product_mgmt.handle_action("update", {**arguments, "dry_run": True})
            assert client.put.await_count == 0
            await product_mgmt.handle_action("update", arguments)

        put_body = client.put.await_args.kwargs["data"]
        assert put_body["description"] == "x"
        assert _previewed_body(preview[0].text) == json.loads(json.dumps(put_body, default=str))

    @pytest.mark.asyncio
    async def test_update_dry_run_body_carries_the_products_own_team(self, product_mgmt):
        """BACK-4818: the preview and the update send the product's stored team."""
        client = _recording_product_client()
        stored = {**STORED_PRODUCT, "team": {"id": "team_prod", "label": "x"}}
        client.get_product_by_id = AsyncMock(return_value=json.loads(json.dumps(stored)))
        arguments = {"product_id": "prod_1", "product_data": {"description": "x"}}
        with patch.object(product_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = client
            preview = await product_mgmt.handle_action("update", {**arguments, "dry_run": True})
            await product_mgmt.handle_action("update", arguments)

        assert _previewed_body(preview[0].text)["teamId"] == "team_prod"
        assert client.put.await_args.kwargs["data"]["teamId"] == "team_prod"

    @pytest.mark.asyncio
    async def test_update_dry_run_refuses_a_plan_change_that_drops_every_tier(self, product_mgmt):
        """The preview refuses the same tier-removing plan change the update refuses."""
        client = _recording_product_client()
        arguments = {"product_id": "prod_1", "product_data": {"plan": {"tiers": []}}}
        with patch.object(product_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_gc.return_value = client
            with pytest.raises(ToolError) as update_refusal:
                await product_mgmt.handle_action("update", arguments)
            with pytest.raises(ToolError) as preview_refusal:
                await product_mgmt.handle_action("update", {**arguments, "dry_run": True})

        assert preview_refusal.value.message == update_refusal.value.message
        assert client.put.await_count == 0

    @pytest.mark.asyncio
    async def test_delete_dry_run_returns_preview(self, product_mgmt):
        """Delete with dry_run=True returns warning preview without deleting."""
        with patch.object(product_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_gc.return_value = mock_client

            result = await product_mgmt.handle_action(
                "delete",
                {"product_id": "p1", "dry_run": True},
            )

        assert len(result) >= 1
        assert "DRY RUN" in result[0].text
        assert "cannot be undone" in result[0].text.lower() or "warning" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_list_action_returns_formatted_products(self, product_mgmt):
        """List action returns formatted product list."""
        with patch.object(product_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_gc.return_value = mock_client
            mock_client.get_products = AsyncMock(return_value={})
            mock_client._extract_embedded_data.return_value = [{"id": "p1", "name": "A"}]
            mock_client._extract_pagination_info.return_value = {
                "totalPages": 1,
                "totalElements": 1,
            }

            result = await product_mgmt.handle_action("list", {"page": 0, "size": 10})

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)

    @pytest.mark.asyncio
    async def test_get_action_returns_product_details(self, product_mgmt):
        """Get action returns product details for valid ID."""
        with patch.object(product_mgmt, "get_client", new_callable=AsyncMock) as mock_gc:
            mock_client = MagicMock()
            mock_gc.return_value = mock_client
            mock_client.get_product_by_id = AsyncMock(
                return_value={"id": "p1", "name": "Product A"}
            )

            result = await product_mgmt.handle_action("get", {"product_id": "p1"})

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)


# ===========================================================================
# ProductValidator tests
# ===========================================================================


class TestProductValidator:
    """Test ProductValidator behavior."""

    def test_validator_initializes_with_schema_discovery(self):
        """Validator initializes schema_discovery attribute accessible from outside."""
        validator = ProductValidator()
        # schema_discovery should be set (either real or None depending on import)
        # schema_discovery attribute is accessible and functional
        val = validator.schema_discovery
        # It may be None (if schema discovery is unavailable) or a real object
        assert val is None or callable(val.get_capabilities)

    @pytest.mark.asyncio
    async def test_get_capabilities_without_ucm_raises_error(self):
        """get_capabilities without UCM integration raises ToolError."""
        validator = ProductValidator(ucm_integration_helper=None)

        with pytest.raises(ToolError) as exc_info:
            await validator.get_capabilities()

        assert "ucm" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_get_capabilities_with_ucm_returns_result(self):
        """get_capabilities delegates to UCM when available."""
        mock_ucm_helper = MagicMock()
        mock_ucm_helper.ucm = MagicMock()
        mock_ucm_helper.ucm.get_capabilities = AsyncMock(
            return_value={"actions": ["list", "create"]}
        )

        validator = ProductValidator(ucm_integration_helper=mock_ucm_helper)
        result = await validator.get_capabilities()

        assert result == {"actions": ["list", "create"]}

    @pytest.mark.asyncio
    async def test_get_capabilities_ucm_error_raises_tool_error(self):
        """get_capabilities raises ToolError when UCM service fails."""
        mock_ucm_helper = MagicMock()
        mock_ucm_helper.ucm = MagicMock()
        mock_ucm_helper.ucm.get_capabilities = AsyncMock(side_effect=RuntimeError("UCM down"))

        validator = ProductValidator(ucm_integration_helper=mock_ucm_helper)

        with pytest.raises(ToolError) as exc_info:
            await validator.get_capabilities()

        assert "ucm" in str(exc_info.value).lower()


class TestListProductsRejectsFloatSizeNoLeak:
    """BACK-1270 / item #5 — float size must reject without Pydantic URL."""

    @pytest.mark.asyncio
    async def test_float_size_returns_clean_error(self, product_manager):
        from src.revenium_mcp_server.common.error_handling import ToolError
        from tests.unit._helpers_no_framework_leak import assert_no_framework_leak
        with pytest.raises(ToolError) as exc:
            await product_manager.list_products({"page": 0, "size": 3.7})
        assert exc.value.field == "size"
        assert_no_framework_leak(exc.value.message)


class TestUpdateProductPreservesFlatAmount:
    """BACK-1270 / BACK-4860: a name-only update of a flat_amount-tier product keeps the tier.

    The platform refuses a flat-only tier in any PUT that carries the plan, so the
    update leaves the plan out and the platform keeps the stored tier as it is.
    """

    @pytest.mark.asyncio
    async def test_name_only_update_does_not_invalidate_flat_amount_tier(
        self, product_manager, mock_client
    ):
        existing = {
            "id": "prod_123",
            "name": "old",
            "version": "1.0",
            "paymentSource": "INVOICE_ONLY_NO_PAYMENT",
            "plan": {
                "tiers": [
                    {"id": None, "name": "flat", "up_to": None, "flat_amount": "1.00"}
                ]
            },
        }
        mock_client.get_product_by_id = AsyncMock(return_value=existing)
        mock_client.update_product = AsyncMock(
            side_effect=lambda _id, payload: {**existing, **payload}
        )

        result = await product_manager.update_product({
            "product_id": "prod_123",
            "product_data": {"name": "new"},
        })
        assert "data" in result
        sent = mock_client.update_product.await_args.args[1]
        assert sent["name"] == "new"
        assert "plan" not in sent
        assert result["data"]["plan"]["tiers"][0]["flat_amount"] == "1.00"


class TestProductsPaginationSafeInteger:
    """Values beyond 2^53 must hit the safe-integer guard, not the
    bounds check — and the float-corrupted value must not be echoed back."""

    def test_size_beyond_safe_range_rejected_without_echo(self):
        from src.revenium_mcp_server.tools_decomposed.product_management import (
            _validate_products_pagination,
        )

        # 2^63 as it actually arrives: JSON number decoded via float64 by
        # Go/JS MCP clients, then coerced to int (9223372036854776000).
        corrupted = int(float(2**63))
        with pytest.raises(ToolError) as exc_info:
            _validate_products_pagination(page=0, size=corrupted)
        msg = str(exc_info.value)
        assert "exceeds safe integer range" in msg
        assert str(corrupted) not in msg

    def test_page_beyond_safe_range_rejected_without_echo(self):
        from src.revenium_mcp_server.tools_decomposed.product_management import (
            _validate_products_pagination,
        )

        corrupted = int(float(2**63))
        with pytest.raises(ToolError) as exc_info:
            _validate_products_pagination(page=corrupted, size=20)
        msg = str(exc_info.value)
        assert "exceeds safe integer range" in msg
        assert str(corrupted) not in msg


class TestProductListSearchContract:
    """The list action's search surface must be honest.

    The upstream products endpoint ignores arbitrary query params, so the
    advertised free-form `filters` dict was a silent no-op: every unmatched
    filter still returned the whole catalogue. The contract is now narrow —
    `query` is the server-side search, `filters` supports `name` only (exact,
    case-sensitive, applied to the returned page), and any other filter key is
    rejected instead of forwarded.
    """

    THREE_PRODUCTS = [
        {"id": "p1", "name": "Alpha"},
        {"id": "p2", "name": "Alpha Plus"},
        {"id": "p3", "name": "Beta"},
    ]

    @staticmethod
    def _rendered_text(response):
        assert len(response) == 1
        assert isinstance(response[0], TextContent)
        return response[0].text

    @pytest.mark.asyncio
    async def test_query_forwarded_as_server_side_search(
        self, product_manager, mock_client
    ):
        """A top-level query is passed to the endpoint's `query` param."""
        mock_client._extract_embedded_data.return_value = [{"id": "p1", "name": "Alpha"}]
        mock_client._extract_pagination_info.return_value = {
            "totalPages": 1,
            "totalElements": 1,
        }

        await product_manager.list_products({"page": 0, "size": 20, "query": "Alpha"})

        mock_client.get_products.assert_called_once_with(page=0, size=20, query="Alpha")

    @pytest.mark.asyncio
    async def test_filters_name_narrows_server_side_and_matches_exactly(
        self, product_manager, mock_client, product_mgmt
    ):
        """filters={'name': X} sends query=X upstream AND keeps only the exact
        name match from the returned page — the render must count the survivor,
        not the whole page."""
        mock_client._extract_embedded_data.return_value = list(self.THREE_PRODUCTS)
        mock_client._extract_pagination_info.return_value = {
            "totalPages": 1,
            "totalElements": 3,
        }

        arguments = {"page": 0, "size": 20, "filters": {"name": "Alpha"}}
        response = await product_mgmt._handle_standard_crud_actions(
            "list", arguments, product_manager
        )

        mock_client.get_products.assert_called_once_with(page=0, size=20, query="Alpha")

        text = self._rendered_text(response)
        assert "Found 1 of 1 items" in text, text
        assert "Alpha Plus" not in text, text
        assert "Beta" not in text, text
        assert '"id": "p1"' in text, text

    @pytest.mark.asyncio
    async def test_filters_name_with_no_match_renders_empty_honestly(
        self, product_manager, mock_client, product_mgmt
    ):
        """A name nothing matches must render zero items even when the upstream
        response still carries the whole catalogue."""
        mock_client._extract_embedded_data.return_value = list(self.THREE_PRODUCTS)
        mock_client._extract_pagination_info.return_value = {
            "totalPages": 1,
            "totalElements": 3,
        }

        arguments = {"page": 0, "size": 20, "filters": {"name": "zzz-no-such-product"}}
        response = await product_mgmt._handle_standard_crud_actions(
            "list", arguments, product_manager
        )

        text = self._rendered_text(response)
        assert "Found 0 of 0 items" in text, text
        assert "No items found." in text, text
        assert "Alpha" not in text, text

    @pytest.mark.asyncio
    async def test_filters_name_match_is_case_sensitive(
        self, product_manager, mock_client
    ):
        """Exact means exact — a casing variant is not a match."""
        mock_client._extract_embedded_data.return_value = list(self.THREE_PRODUCTS)
        mock_client._extract_pagination_info.return_value = {
            "totalPages": 1,
            "totalElements": 3,
        }

        result = await product_manager.list_products(
            {"page": 0, "size": 20, "filters": {"name": "alpha"}}
        )

        assert result["data"] == []
        assert result["pagination"]["total_items"] == 0

    @pytest.mark.asyncio
    async def test_unknown_filter_key_raises_structured_error(
        self, product_manager, mock_client
    ):
        """Unsupported filter keys are rejected, never forwarded — forwarding is
        what made the old filter a silent no-op."""
        mock_client._extract_embedded_data.return_value = list(self.THREE_PRODUCTS)
        mock_client._extract_pagination_info.return_value = {
            "totalPages": 1,
            "totalElements": 3,
        }

        with pytest.raises(ToolError) as exc_info:
            await product_manager.list_products(
                {"page": 0, "size": 20, "filters": {"description": "anything"}}
            )

        err = exc_info.value
        assert err.field == "filters"
        assert "description" in str(err)
        assert "name" in str(err)
        assert "query" in str(err)
        mock_client.get_products.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_filter_key_rejected_alongside_supported_key(
        self, product_manager, mock_client
    ):
        """A valid `name` does not license an unknown sibling key."""
        mock_client._extract_embedded_data.return_value = list(self.THREE_PRODUCTS)
        mock_client._extract_pagination_info.return_value = {
            "totalPages": 1,
            "totalElements": 3,
        }

        with pytest.raises(ToolError):
            await product_manager.list_products(
                {"page": 0, "size": 20, "filters": {"name": "Alpha", "status": "ACTIVE"}}
            )

        mock_client.get_products.assert_not_called()

    @pytest.mark.asyncio
    async def test_conflicting_query_and_filters_name_raises(
        self, product_manager, mock_client
    ):
        """Two different search terms is ambiguous intent, not a merge."""
        mock_client._extract_embedded_data.return_value = list(self.THREE_PRODUCTS)
        mock_client._extract_pagination_info.return_value = {
            "totalPages": 1,
            "totalElements": 3,
        }

        with pytest.raises(ToolError) as exc_info:
            await product_manager.list_products(
                {"page": 0, "size": 20, "query": "Alpha", "filters": {"name": "Beta"}}
            )

        err = exc_info.value
        assert err.field == "query"
        assert "Alpha" in str(err)
        assert "Beta" in str(err)
        mock_client.get_products.assert_not_called()

    @pytest.mark.asyncio
    async def test_matching_query_and_filters_name_allowed(
        self, product_manager, mock_client
    ):
        """Same term in both places is redundant but unambiguous."""
        mock_client._extract_embedded_data.return_value = list(self.THREE_PRODUCTS)
        mock_client._extract_pagination_info.return_value = {
            "totalPages": 1,
            "totalElements": 3,
        }

        result = await product_manager.list_products(
            {"page": 0, "size": 20, "query": "Alpha", "filters": {"name": "Alpha"}}
        )

        mock_client.get_products.assert_called_once_with(page=0, size=20, query="Alpha")
        assert [p["id"] for p in result["data"]] == ["p1"]

    @pytest.mark.asyncio
    async def test_no_search_terms_sends_no_query_param(
        self, product_manager, mock_client
    ):
        """An unfiltered list must not invent a query param."""
        mock_client._extract_embedded_data.return_value = list(self.THREE_PRODUCTS)
        mock_client._extract_pagination_info.return_value = {
            "totalPages": 1,
            "totalElements": 3,
        }

        result = await product_manager.list_products({"page": 0, "size": 20})

        mock_client.get_products.assert_called_once_with(page=0, size=20)
        assert len(result["data"]) == 3
        assert result["pagination"]["total_items"] == 3

    @pytest.mark.asyncio
    async def test_non_dict_filters_raises_structured_error(
        self, product_manager, mock_client
    ):
        """filters must be a mapping; a string would previously explode in **kwargs."""
        with pytest.raises(ToolError) as exc_info:
            await product_manager.list_products(
                {"page": 0, "size": 20, "filters": "name=Alpha"}
            )

        assert exc_info.value.field == "filters"
        mock_client.get_products.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_string_filters_name_raises_structured_error(
        self, product_manager, mock_client
    ):
        """filters is a free-form dict with no schema behind it, so the name
        value's type is checked here rather than leaking upstream."""
        with pytest.raises(ToolError) as exc_info:
            await product_manager.list_products(
                {"page": 0, "size": 20, "filters": {"name": 123}}
            )

        assert exc_info.value.field == "filters.name"
        mock_client.get_products.assert_not_called()


def _program_pages(mock_client, pages, total_pages=None):
    """Drive the mock client through a sequence of server pages.

    ``pages`` is a list of per-page product lists. ``total_pages`` defaults to
    len(pages) and can be raised above it to simulate a server result set that
    continues past the pages the mock actually serves.
    """
    reported_total = len(pages) if total_pages is None else total_pages
    mock_client.get_products.side_effect = [
        {"_page": index} for index in range(len(pages))
    ]
    mock_client._extract_embedded_data.side_effect = list(pages)
    mock_client._extract_pagination_info.side_effect = [
        {"totalPages": reported_total, "totalElements": sum(len(p) for p in pages)}
        for _ in pages
    ]


class TestProductListExactNameCrossPageScan:
    """filters.name is an exact-lookup intent, not a page-scoped filter.

    The server-side `query` match is loose, so the exact name can legitimately
    land on any page of the loose result set. Applying the exact match only to
    the page the caller happened to request reports "no match" for a product
    that demonstrably exists — the same false-negative class the honest-filter
    work set out to remove. The scan therefore drains the query's pages and
    renders the exact-match set as one logical page.
    """

    @pytest.mark.asyncio
    async def test_exact_match_on_a_later_page_is_found(self, product_manager, mock_client):
        """The exact match sits on server page 1; page 0 holds only loose hits."""
        _program_pages(
            mock_client,
            [
                [{"id": "p1", "name": "Alpha Plus"}, {"id": "p2", "name": "Alpha Max"}],
                [{"id": "p3", "name": "Alpha"}, {"id": "p4", "name": "Alpha Mini"}],
            ],
        )

        result = await product_manager.list_products(
            {"page": 0, "size": 2, "filters": {"name": "Alpha"}}
        )

        assert [p["id"] for p in result["data"]] == ["p3"]
        assert result["pagination"]["total_items"] == 1

    @pytest.mark.asyncio
    async def test_scan_starts_at_page_zero_regardless_of_requested_page(
        self, product_manager, mock_client
    ):
        """In exact-lookup mode the caller's page does not select a server page:
        the exact-match set is the logical result, so the scan always starts at 0."""
        _program_pages(
            mock_client,
            [
                [{"id": "p1", "name": "Alpha"}],
                [{"id": "p2", "name": "Alpha Plus"}],
            ],
        )

        result = await product_manager.list_products(
            {"page": 5, "size": 1, "filters": {"name": "Alpha"}}
        )

        scanned = [call.kwargs["page"] for call in mock_client.get_products.call_args_list]
        assert scanned == [0, 1]
        assert [p["id"] for p in result["data"]] == ["p1"]
        assert result["pagination"]["page"] == 0

    @pytest.mark.asyncio
    async def test_matches_collected_across_every_scanned_page(
        self, product_manager, mock_client
    ):
        """Duplicate names across pages all survive the scan."""
        _program_pages(
            mock_client,
            [
                [{"id": "p1", "name": "Alpha"}, {"id": "p2", "name": "Alpha Plus"}],
                [{"id": "p3", "name": "Beta"}, {"id": "p4", "name": "Alpha"}],
                [{"id": "p5", "name": "Alpha"}],
            ],
        )

        result = await product_manager.list_products(
            {"page": 0, "size": 20, "filters": {"name": "Alpha"}}
        )

        assert [p["id"] for p in result["data"]] == ["p1", "p4", "p5"]

    @pytest.mark.asyncio
    async def test_scan_stops_early_on_an_empty_page(self, product_manager, mock_client):
        """A short server result set must not be paged past its end."""
        _program_pages(mock_client, [[{"id": "p1", "name": "Alpha"}], []], total_pages=9)

        await product_manager.list_products(
            {"page": 0, "size": 20, "filters": {"name": "Alpha"}}
        )

        assert mock_client.get_products.call_count == 2

    @pytest.mark.asyncio
    async def test_plain_query_still_uses_server_pagination(
        self, product_manager, mock_client
    ):
        """Without filters.name the server's own paging is correct — one request
        for the requested page, no scan."""
        mock_client._extract_embedded_data.return_value = [{"id": "p1", "name": "Alpha"}]
        mock_client._extract_pagination_info.return_value = {
            "totalPages": 4,
            "totalElements": 40,
        }

        result = await product_manager.list_products({"page": 2, "size": 10, "query": "Alpha"})

        mock_client.get_products.assert_called_once_with(page=2, size=10, query="Alpha")
        assert result["pagination"]["page"] == 2
        assert result["pagination"]["total_pages"] == 4
        assert result["pagination"]["has_next"] is True


class TestProductListNarrowedPaginationCoherence:
    """A narrowed render must not borrow the loose query's pagination.

    Reporting the survivor count as total_items while total_pages/has_next still
    describe the server's loose result set produces "Found 1 of 1 items (page 1
    of 3)" and a has_next that points at pages of non-matches.
    """

    @pytest.mark.asyncio
    async def test_narrowed_result_is_a_single_logical_page(
        self, product_manager, mock_client
    ):
        _program_pages(
            mock_client,
            [
                [{"id": "p1", "name": "Alpha"}, {"id": "p2", "name": "Alpha Plus"}],
                [{"id": "p3", "name": "Alpha Max"}],
                [{"id": "p4", "name": "Alpha Mini"}],
            ],
        )

        result = await product_manager.list_products(
            {"page": 0, "size": 20, "filters": {"name": "Alpha"}}
        )

        pagination = result["pagination"]
        assert pagination["total_items"] == 1
        assert pagination["total_pages"] == 1
        assert pagination["page"] == 0
        assert pagination["has_next"] is False
        assert pagination["has_previous"] is False

    @pytest.mark.asyncio
    async def test_narrowed_render_header_is_coherent(
        self, product_manager, mock_client, product_mgmt
    ):
        """The rendered header must not claim page 1 of 3 for a one-page result."""
        _program_pages(
            mock_client,
            [
                [{"id": "p1", "name": "Alpha"}],
                [{"id": "p2", "name": "Alpha Plus"}],
                [{"id": "p3", "name": "Alpha Max"}],
            ],
        )

        response = await product_mgmt._handle_standard_crud_actions(
            "list", {"page": 0, "size": 20, "filters": {"name": "Alpha"}}, product_manager
        )

        text = response[0].text
        assert "Found 1 of 1 items (page 1 of 1)" in text, text
        assert "Next page" not in text, text

    @pytest.mark.asyncio
    async def test_empty_narrowed_result_reports_zero_of_zero(
        self, product_manager, mock_client
    ):
        _program_pages(
            mock_client,
            [
                [{"id": "p1", "name": "Alpha Plus"}],
                [{"id": "p2", "name": "Alpha Max"}],
            ],
        )

        result = await product_manager.list_products(
            {"page": 0, "size": 20, "filters": {"name": "zzz-no-such-product"}}
        )

        assert result["data"] == []
        assert result["pagination"]["total_items"] == 0
        assert result["pagination"]["total_pages"] == 1
        assert result["pagination"]["has_next"] is False

    @pytest.mark.asyncio
    async def test_matches_beyond_size_page_the_exact_match_set(
        self, product_manager, mock_client
    ):
        """When the exact-match set itself exceeds size, total_pages/has_next
        describe that set — never the loose query's pagination."""
        _program_pages(
            mock_client,
            [
                [{"id": "p1", "name": "Alpha"}, {"id": "p2", "name": "Alpha"}],
                [{"id": "p3", "name": "Alpha"}, {"id": "p4", "name": "Alpha"}],
                [{"id": "p5", "name": "Alpha"}],
            ],
        )

        result = await product_manager.list_products(
            {"page": 0, "size": 2, "filters": {"name": "Alpha"}}
        )

        assert [p["id"] for p in result["data"]] == ["p1", "p2"]
        assert result["pagination"]["total_items"] == 5
        assert result["pagination"]["total_pages"] == 3
        assert result["pagination"]["has_next"] is True

    @pytest.mark.asyncio
    async def test_page_indexes_the_exact_match_set(self, product_manager, mock_client):
        """has_next may only advertise a page the caller can actually reach, so
        `page` indexes the match set — an unreachable next page would be the same
        class of lie as borrowing the loose query's totals."""
        _program_pages(
            mock_client,
            [
                [{"id": "p1", "name": "Alpha"}, {"id": "p2", "name": "Alpha"}],
                [{"id": "p3", "name": "Alpha"}, {"id": "p4", "name": "Alpha"}],
                [{"id": "p5", "name": "Alpha"}],
            ],
        )

        result = await product_manager.list_products(
            {"page": 1, "size": 2, "filters": {"name": "Alpha"}}
        )

        assert [p["id"] for p in result["data"]] == ["p3", "p4"]
        assert result["pagination"]["page"] == 1
        assert result["pagination"]["has_previous"] is True
        assert result["pagination"]["has_next"] is True

    @pytest.mark.asyncio
    async def test_page_past_the_match_set_is_clamped_not_stranded(
        self, product_manager, mock_client
    ):
        """A leftover page from a browse loop must not hide a found product."""
        _program_pages(
            mock_client,
            [[{"id": "p1", "name": "Alpha"}], [{"id": "p2", "name": "Alpha Plus"}]],
        )

        result = await product_manager.list_products(
            {"page": 7, "size": 20, "filters": {"name": "Alpha"}}
        )

        assert [p["id"] for p in result["data"]] == ["p1"]
        assert result["pagination"]["page"] == 0
        assert result["pagination"]["has_next"] is False
        assert result["pagination"]["has_previous"] is False


class TestProductListScanBoundHonesty:
    """A bounded scan that stops short must say so.

    Silently returning "no match" after scanning only part of the loose result
    set would recreate the false negative behind a different mechanism.
    """

    @pytest.mark.asyncio
    async def test_scan_bound_sets_possibly_incomplete(self, product_manager, mock_client):
        from src.revenium_mcp_server.tools_decomposed.product_management import (
            _NAME_FILTER_SCAN_MAX_PAGES,
        )

        pages = [
            [{"id": f"p{index}", "name": "Alpha Plus"}]
            for index in range(_NAME_FILTER_SCAN_MAX_PAGES)
        ]
        _program_pages(mock_client, pages, total_pages=_NAME_FILTER_SCAN_MAX_PAGES + 5)

        result = await product_manager.list_products(
            {"page": 0, "size": 20, "filters": {"name": "Alpha"}}
        )

        assert mock_client.get_products.call_count == _NAME_FILTER_SCAN_MAX_PAGES
        assert result["pagination"]["possibly_incomplete"] is True

    @pytest.mark.asyncio
    async def test_exhausted_scan_is_not_flagged_incomplete(
        self, product_manager, mock_client
    ):
        """Draining every page of the loose result set is a complete answer."""
        _program_pages(
            mock_client,
            [
                [{"id": "p1", "name": "Alpha Plus"}],
                [{"id": "p2", "name": "Alpha"}],
            ],
        )

        result = await product_manager.list_products(
            {"page": 0, "size": 20, "filters": {"name": "Alpha"}}
        )

        assert result["pagination"]["possibly_incomplete"] is False

    @pytest.mark.asyncio
    async def test_bounded_empty_result_renders_the_caveat(
        self, product_manager, mock_client, product_mgmt
    ):
        """The most dangerous case: zero matches after a truncated scan must not
        read as a confident "this product does not exist"."""
        from src.revenium_mcp_server.tools_decomposed.product_management import (
            _NAME_FILTER_SCAN_MAX_PAGES,
        )

        pages = [
            [{"id": f"p{index}", "name": "Alpha Plus"}]
            for index in range(_NAME_FILTER_SCAN_MAX_PAGES)
        ]
        _program_pages(mock_client, pages, total_pages=_NAME_FILTER_SCAN_MAX_PAGES + 5)

        response = await product_mgmt._handle_standard_crud_actions(
            "list", {"page": 0, "size": 20, "filters": {"name": "Alpha"}}, product_manager
        )

        text = response[0].text
        assert str(_NAME_FILTER_SCAN_MAX_PAGES) in text, text
        assert "more may exist" in text, text
        assert "continue the search with query=" in text.lower(), text

    @pytest.mark.asyncio
    async def test_bounded_nonempty_result_carries_the_flag_in_the_payload(
        self, product_manager, mock_client, product_mgmt
    ):
        from src.revenium_mcp_server.tools_decomposed.product_management import (
            _NAME_FILTER_SCAN_MAX_PAGES,
        )

        pages = [[{"id": "p0", "name": "Alpha"}]] + [
            [{"id": f"p{index}", "name": "Alpha Plus"}]
            for index in range(1, _NAME_FILTER_SCAN_MAX_PAGES)
        ]
        _program_pages(mock_client, pages, total_pages=_NAME_FILTER_SCAN_MAX_PAGES + 5)

        response = await product_mgmt._handle_standard_crud_actions(
            "list", {"page": 0, "size": 20, "filters": {"name": "Alpha"}}, product_manager
        )

        text = response[0].text
        assert '"possibly_incomplete": true' in text, text
        assert "more may exist" in text, text
        # The caveat must offer a reachable continuation: query mode has full
        # server-side pagination, so the caller can walk the remaining pages
        # even when the product id is unknown.
        assert "continue the search with query=" in text.lower(), text

    @pytest.mark.asyncio
    async def test_complete_scan_renders_no_caveat(
        self, product_manager, mock_client, product_mgmt
    ):
        _program_pages(
            mock_client,
            [[{"id": "p1", "name": "Alpha"}], [{"id": "p2", "name": "Alpha Plus"}]],
        )

        response = await product_mgmt._handle_standard_crud_actions(
            "list", {"page": 0, "size": 20, "filters": {"name": "Alpha"}}, product_manager
        )

        text = response[0].text
        assert "more may exist" not in text, text
        assert '"possibly_incomplete": false' in text, text


class TestProductInputSchemaSearchSurface:
    """Introspection metadata must advertise the parameters the tool accepts."""

    @pytest.mark.asyncio
    async def test_input_schema_advertises_query(self, product_mgmt):
        schema = await product_mgmt._get_input_schema()

        assert "query" in schema["properties"], schema["properties"]
        assert schema["properties"]["query"]["type"] == "string"

    @pytest.mark.asyncio
    async def test_input_schema_query_description_matches_the_contract(self, product_mgmt):
        description = (await product_mgmt._get_input_schema())["properties"]["query"][
            "description"
        ]

        assert "server-side" in description.lower(), description

    @pytest.mark.asyncio
    async def test_input_schema_describes_filters_as_name_only(self, product_mgmt):
        properties = (await product_mgmt._get_input_schema())["properties"]

        assert "filters" in properties, properties
        description = properties["filters"]["description"]
        assert "name" in description, description
        assert "exact" in description.lower(), description

    @pytest.mark.asyncio
    async def test_input_schema_does_not_make_search_required(self, product_mgmt):
        schema = await product_mgmt._get_input_schema()

        assert "query" not in schema["required"]
        assert "filters" not in schema["required"]


class TestProductListPagingText:
    """The list answer must keep the page size in its hints and name the pages that exist."""

    @staticmethod
    def _text(response):
        assert len(response) == 1
        return response[0].text

    @pytest.mark.asyncio
    async def test_list_past_last_page_names_the_pages_that_exist(
        self, product_manager, mock_client, product_mgmt
    ):
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {
            "totalPages": 2,
            "totalElements": 31,
        }

        response = await product_mgmt._handle_standard_crud_actions(
            "list", {"page": 500, "size": 20}, product_manager
        )

        text = self._text(response)
        assert "Found 0 of 31 items (page 501 of 2)" in text, text
        assert (
            "The page requested (page=500) is past the last. The list has 31 items "
            "on 2 pages. Pass page=1, size=20 for the last page, or page=0, size=20 "
            "for the first."
        ) in text, text
        assert "permissions" not in text, text

    @pytest.mark.asyncio
    async def test_list_next_page_hint_carries_requested_size(
        self, product_manager, mock_client, product_mgmt
    ):
        mock_client._extract_embedded_data.return_value = [
            {"id": f"p{i}", "name": f"P{i}"} for i in range(5)
        ]
        mock_client._extract_pagination_info.return_value = {
            "totalPages": 7,
            "totalElements": 31,
        }

        response = await product_mgmt._handle_standard_crud_actions(
            "list", {"page": 0, "size": 5}, product_manager
        )

        assert "• Next page: page=1, size=5" in self._text(response)
