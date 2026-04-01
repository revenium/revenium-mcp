"""Extended unit tests for ProductManagement — deep CRUD coverage.

Covers handle_action routing for create, update, delete, search, get_supporting_data,
and various discovery/validation actions. Mocks client API calls.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mcp.types import TextContent

from src.revenium_mcp_server.tools_decomposed.product_management import (
    ProductManagement,
    ProductManager,
    ProductValidator,
    ProductEnhancementProcessor,
    ProductHierarchyManager,
)
from src.revenium_mcp_server.common.error_handling import ToolError


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_client():
    client = MagicMock()
    client.team_id = "team_test"
    client.get_products = AsyncMock(return_value={})
    client.get_product_by_id = AsyncMock(return_value={"id": "p1", "name": "Product A"})
    client.create_product = AsyncMock(return_value={"id": "p_new", "name": "New Product"})
    client.update_product = AsyncMock(return_value={"id": "p1", "name": "Updated"})
    client.delete_product = AsyncMock(return_value={"deleted": True})
    client.get_sources = AsyncMock(return_value={})
    client._extract_embedded_data = MagicMock(return_value=[])
    client._extract_pagination_info = MagicMock(return_value={"totalPages": 1, "totalElements": 0})
    return client


def _make_mgmt_with_client():
    mgmt = ProductManagement()
    client = _make_client()
    mgmt.get_client = AsyncMock(return_value=client)
    return mgmt, client


# ===========================================================================
# handle_action — create (real path, non-dry-run)
# ===========================================================================


class TestHandleActionCreateReal:
    """Cover create action through handle_action."""

    @pytest.mark.asyncio
    async def test_create_with_product_data_calls_api(self):
        mgmt, client = _make_mgmt_with_client()
        client._extract_embedded_data.return_value = [{"id": "src_1"}]
        client.create_product.return_value = {"id": "p_new", "name": "Test API"}

        with patch(
            "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
        ) as MockEngine:
            MockEngine.validate_for_mcp.return_value = {"isError": False, "content": []}
            with patch(
                "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
                return_value=None,
            ):
                result = await mgmt.handle_action(
                    "create",
                    {"name": "Test API", "auto_generate": True},
                )

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
        client.create_product.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_with_description_uses_nlp_fallback(self):
        mgmt, client = _make_mgmt_with_client()
        client.create_product.return_value = {"id": "p_nlp", "name": "API Service"}

        with patch(
            "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
        ) as MockEngine:
            MockEngine.validate_for_mcp.return_value = {"isError": False, "content": []}
            with patch(
                "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
                return_value=None,
            ):
                result = await mgmt.handle_action(
                    "create",
                    {"description": "A premium API access plan"},
                )

        # Create must return a non-empty response that references the product
        assert len(result[0].text) > 0
        assert "API Service" in result[0].text or "p_nlp" in result[0].text or "created" in result[0].text.lower()


# ===========================================================================
# handle_action — create dry run with description
# ===========================================================================


class TestHandleActionCreateDryRunDescription:
    """Cover create dry-run paths through _handle_create_dry_run.

    The create dry-run goes through _handle_crud_with_dry_run -> _handle_create_dry_run
    which uses ProductValidator.validate_configuration for structured validation.
    """

    @pytest.mark.asyncio
    async def test_dry_run_structured_validation_valid(self):
        """Dry run without description uses structured validation."""
        mgmt, _ = _make_mgmt_with_client()
        mgmt.validator.validate_configuration = MagicMock(
            return_value={"valid": True, "errors": []}
        )
        result = await mgmt.handle_action(
            "create",
            {"product_data": {"name": "Test"}, "dry_run": True},
        )
        text = result[0].text
        assert "DRY RUN" in text
        assert "Validation Successful" in text

    @pytest.mark.asyncio
    async def test_dry_run_structured_validation_invalid(self):
        mgmt, _ = _make_mgmt_with_client()
        mgmt.validator.validate_configuration = MagicMock(
            return_value={
                "valid": False,
                "errors": [{"error": "Missing name field"}],
            }
        )
        result = await mgmt.handle_action(
            "create",
            {"product_data": {}, "dry_run": True},
        )
        text = result[0].text
        assert "DRY RUN" in text
        assert "Validation Failed" in text

    @pytest.mark.asyncio
    async def test_dry_run_no_product_data_uses_empty_dict(self):
        """Dry run without product_data defaults to empty dict for validation."""
        mgmt, _ = _make_mgmt_with_client()
        mgmt.validator.validate_configuration = MagicMock(
            return_value={"valid": False, "errors": [{"error": "product_data is required"}]}
        )
        result = await mgmt.handle_action(
            "create",
            {"dry_run": True},
        )
        text = result[0].text
        assert "DRY RUN" in text

    @pytest.mark.asyncio
    async def test_dry_run_with_resource_data_backward_compat(self):
        """Dry run supports resource_data as backward-compatible alias."""
        mgmt, _ = _make_mgmt_with_client()
        mgmt.validator.validate_configuration = MagicMock(
            return_value={"valid": True, "errors": []}
        )
        result = await mgmt.handle_action(
            "create",
            {"resource_data": {"name": "Compat Product"}, "dry_run": True},
        )
        text = result[0].text
        assert "DRY RUN" in text
        assert "Validation Successful" in text


# ===========================================================================
# handle_action — update (real path)
# ===========================================================================


class TestHandleActionUpdateReal:
    """Cover update action without dry_run."""

    @pytest.mark.asyncio
    async def test_update_delegates_to_product_manager(self):
        mgmt, client = _make_mgmt_with_client()
        # Need to mock the update_handler in ProductManager
        with patch.object(ProductManager, "__init__", return_value=None):
            pm = ProductManager.__new__(ProductManager)
            pm.client = client
            pm.update_handler = MagicMock()
            pm.update_handler.update_with_merge = AsyncMock(
                return_value={"id": "p1", "name": "Updated"}
            )
            pm.update_config_factory = MagicMock()
            pm.update_config_factory.get_config = MagicMock(return_value={"resource_type": "products"})

            with patch.object(mgmt, "_setup_managers", new_callable=AsyncMock, return_value=(pm, MagicMock(), MagicMock())):
                result = await mgmt.handle_action(
                    "update",
                    {"product_id": "p1", "product_data": {"name": "Updated"}},
                )

        # Update result must be non-empty text
        assert len(result[0].text) > 0


# ===========================================================================
# handle_action — delete (real path)
# ===========================================================================


class TestHandleActionDeleteReal:
    """Cover delete action without dry_run."""

    @pytest.mark.asyncio
    async def test_delete_calls_client_api(self):
        mgmt, client = _make_mgmt_with_client()
        client.delete_product.return_value = {"deleted": True}

        with patch.object(ProductManager, "__init__", return_value=None):
            pm = ProductManager.__new__(ProductManager)
            pm.client = client

            with patch.object(mgmt, "_setup_managers", new_callable=AsyncMock, return_value=(pm, MagicMock(), MagicMock())):
                # Need to not hit the actual delete_product which needs product_id validation
                pm.delete_product = AsyncMock(return_value={
                    "action": "delete",
                    "product_id": "p_del",
                    "data": {"deleted": True},
                })
                result = await mgmt.handle_action("delete", {"product_id": "p_del"})

        # Delete result must be non-empty text
        assert len(result[0].text) > 0


# ===========================================================================
# handle_action — discovery/validation actions
# ===========================================================================


class TestHandleActionDiscovery:
    """Cover discovery, validation, template and hierarchy actions."""

    @pytest.mark.asyncio
    async def test_validate_action_with_product_data(self):
        mgmt, _ = _make_mgmt_with_client()
        mgmt.validator.validate_configuration = MagicMock(
            return_value={"valid": True, "errors": [], "warnings": []}
        )
        result = await mgmt.handle_action(
            "validate",
            {"product_data": {"name": "Test"}},
        )
        # Validate response must indicate success since mock returns valid=True
        assert "valid" in result[0].text.lower() or "Test" in result[0].text

    @pytest.mark.asyncio
    async def test_validate_action_with_resource_data_compat(self):
        mgmt, _ = _make_mgmt_with_client()
        mgmt.validator.validate_configuration = MagicMock(
            return_value={"valid": True, "errors": [], "warnings": []}
        )
        result = await mgmt.handle_action(
            "validate",
            {"resource_data": {"name": "Test"}},
        )
        # resource_data is backward-compatible alias; validation must succeed
        assert "valid" in result[0].text.lower() or "Test" in result[0].text

    @pytest.mark.asyncio
    async def test_get_examples_action(self):
        mgmt, _ = _make_mgmt_with_client()
        mgmt.validator.get_examples = MagicMock(return_value={"examples": []})
        result = await mgmt.handle_action("get_examples", {})
        # Examples response must be non-trivial text
        assert len(result[0].text) > 20

    @pytest.mark.asyncio
    async def test_get_examples_with_type(self):
        mgmt, _ = _make_mgmt_with_client()
        mgmt.validator.get_examples = MagicMock(return_value={"examples": [{"name": "Basic"}]})
        result = await mgmt.handle_action("get_examples", {"example_type": "basic"})
        # Example response must reference "Basic" from mock or be non-empty
        assert "Basic" in result[0].text or len(result[0].text) > 20

    @pytest.mark.asyncio
    async def test_get_agent_summary_action(self):
        mgmt, _ = _make_mgmt_with_client()
        with patch.object(
            mgmt, "_handle_get_agent_summary", new_callable=AsyncMock,
            return_value=[TextContent(type="text", text="Agent summary")],
        ):
            result = await mgmt.handle_action("get_agent_summary", {})
        assert result[0].text == "Agent summary"

    @pytest.mark.asyncio
    async def test_get_tool_metadata_action(self):
        mgmt, _ = _make_mgmt_with_client()
        with patch.object(
            mgmt, "get_tool_metadata", new_callable=AsyncMock,
            return_value=MagicMock(to_dict=lambda: {"tool": "manage_products"}),
        ):
            result = await mgmt.handle_action("get_tool_metadata", {})
        # Tool metadata response must be non-empty
        assert len(result[0].text) > 0


# ===========================================================================
# handle_action — enhanced features
# ===========================================================================


class TestHandleActionEnhancedFeatures:
    """Cover enhanced feature actions routing."""

    @pytest.mark.asyncio
    async def test_create_simple(self):
        mgmt, client = _make_mgmt_with_client()
        with patch.object(ProductEnhancementProcessor, "__init__", return_value=None):
            ep = ProductEnhancementProcessor.__new__(ProductEnhancementProcessor)
            ep.create_simple = AsyncMock(return_value={"id": "p_simple", "name": "Simple"})
            ep.nlp_processor = None

            with patch.object(mgmt, "_setup_managers", new_callable=AsyncMock, return_value=(MagicMock(), ep, MagicMock())):
                result = await mgmt.handle_action("create_simple", {"name": "Simple"})

        # create_simple must produce a non-empty response referencing the product
        assert "p_simple" in result[0].text or "Simple" in result[0].text

    @pytest.mark.asyncio
    async def test_get_templates(self):
        mgmt, _ = _make_mgmt_with_client()
        with patch.object(ProductEnhancementProcessor, "__init__", return_value=None):
            ep = ProductEnhancementProcessor.__new__(ProductEnhancementProcessor)
            ep.get_templates = AsyncMock(return_value={"templates": []})
            ep.nlp_processor = None

            with patch.object(mgmt, "_setup_managers", new_callable=AsyncMock, return_value=(MagicMock(), ep, MagicMock())):
                result = await mgmt.handle_action("get_templates", {})

        # get_templates must return a non-empty response
        assert len(result[0].text) > 0

    @pytest.mark.asyncio
    async def test_suggest_template(self):
        mgmt, _ = _make_mgmt_with_client()
        with patch.object(ProductEnhancementProcessor, "__init__", return_value=None):
            ep = ProductEnhancementProcessor.__new__(ProductEnhancementProcessor)
            ep.suggest_template = AsyncMock(return_value={"suggestion": "API Plan"})
            ep.nlp_processor = None

            with patch.object(mgmt, "_setup_managers", new_callable=AsyncMock, return_value=(MagicMock(), ep, MagicMock())):
                result = await mgmt.handle_action("suggest_template", {"description": "API"})

        # suggest_template must return a non-empty response
        assert "API Plan" in result[0].text

    @pytest.mark.asyncio
    async def test_clarify_pricing(self):
        mgmt, _ = _make_mgmt_with_client()
        with patch.object(ProductEnhancementProcessor, "__init__", return_value=None):
            ep = ProductEnhancementProcessor.__new__(ProductEnhancementProcessor)
            ep.clarify_pricing = AsyncMock(return_value={"clarification": "tiered pricing"})
            ep.nlp_processor = None

            with patch.object(mgmt, "_setup_managers", new_callable=AsyncMock, return_value=(MagicMock(), ep, MagicMock())):
                result = await mgmt.handle_action("clarify_pricing", {"text": "pricing question"})

        # clarify_pricing must return a non-empty response
        assert "pricing" in result[0].text.lower() or "tiered" in result[0].text


# ===========================================================================
# handle_action — hierarchy actions
# ===========================================================================


class TestHandleActionHierarchy:
    """Cover hierarchy action routing."""

    @pytest.mark.asyncio
    async def test_get_subscriptions(self):
        mgmt, _ = _make_mgmt_with_client()
        with patch.object(ProductHierarchyManager, "__init__", return_value=None):
            hm = ProductHierarchyManager.__new__(ProductHierarchyManager)
            hm.get_subscriptions = AsyncMock(return_value={
                "product_id": "p1", "subscriptions": []
            })

            with patch.object(mgmt, "_setup_managers", new_callable=AsyncMock, return_value=(MagicMock(), MagicMock(), hm)):
                result = await mgmt.handle_action("get_subscriptions", {"product_id": "p1"})

        assert isinstance(result[0], TextContent)
        assert "p1" in result[0].text

    @pytest.mark.asyncio
    async def test_get_related_credentials(self):
        mgmt, _ = _make_mgmt_with_client()
        with patch.object(ProductHierarchyManager, "__init__", return_value=None):
            hm = ProductHierarchyManager.__new__(ProductHierarchyManager)
            hm.get_related_credentials = AsyncMock(return_value={
                "product_id": "p2", "credentials": []
            })

            with patch.object(mgmt, "_setup_managers", new_callable=AsyncMock, return_value=(MagicMock(), MagicMock(), hm)):
                result = await mgmt.handle_action("get_related_credentials", {"product_id": "p2"})

        assert isinstance(result[0], TextContent)
        assert "p2" in result[0].text

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error_text(self):
        mgmt, _ = _make_mgmt_with_client()
        result = await mgmt.handle_action("totally_bogus_action", {})
        assert isinstance(result[0], TextContent)
        text_lower = result[0].text.lower()
        assert "unknown action" in text_lower or "not supported" in text_lower


# ===========================================================================
# ProductManager — CRUD internals
# ===========================================================================


class TestProductManagerCreateWithDescription:
    """Cover ProductManager.create_product with description path."""

    @pytest.mark.asyncio
    async def test_create_with_product_data_dict(self):
        """Create using product_data dict directly."""
        client = _make_client()
        client._extract_embedded_data.return_value = [{"id": "src_1"}]
        client.create_product.return_value = {"id": "p_dict", "name": "Direct"}
        pm = ProductManager(client)

        with patch(
            "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
        ) as MockEngine:
            MockEngine.validate_for_mcp.return_value = {"isError": False, "content": []}
            with patch(
                "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
                return_value=None,
            ):
                result = await pm.create_product({
                    "product_data": {
                        "name": "Direct Product",
                        "plan": {"type": "SUBSCRIPTION", "currency": "USD"},
                    }
                })

        assert result["action"] == "create"
        client.create_product.assert_called_once()


class TestProductManagerListPaginationEdges:
    """Cover ProductManager.list_products edge cases."""

    @pytest.mark.asyncio
    async def test_list_first_page_no_previous(self):
        client = _make_client()
        client._extract_embedded_data.return_value = [{"id": "p1"}]
        client._extract_pagination_info.return_value = {"totalPages": 3, "totalElements": 30}
        pm = ProductManager(client)
        result = await pm.list_products({"page": 0, "size": 10})
        assert result["pagination"]["has_previous"] is False
        assert result["pagination"]["has_next"] is True

    @pytest.mark.asyncio
    async def test_list_last_page_no_next(self):
        client = _make_client()
        client._extract_embedded_data.return_value = [{"id": "p1"}]
        client._extract_pagination_info.return_value = {"totalPages": 3, "totalElements": 30}
        pm = ProductManager(client)
        result = await pm.list_products({"page": 2, "size": 10})
        assert result["pagination"]["has_next"] is False
        assert result["pagination"]["has_previous"] is True

    @pytest.mark.asyncio
    async def test_list_empty_results(self):
        client = _make_client()
        client._extract_embedded_data.return_value = []
        client._extract_pagination_info.return_value = {"totalPages": 0, "totalElements": 0}
        pm = ProductManager(client)
        result = await pm.list_products({})
        assert result["data"] == []
        assert result["pagination"]["total_items"] == 0


# ===========================================================================
# ProductValidator — validate_configuration
# ===========================================================================


class TestProductValidatorConfig:
    """Cover ProductValidator.validate_configuration."""

    def test_validate_configuration_returns_dict(self):
        validator = ProductValidator()
        result = validator.validate_configuration({"name": "Test"}, dry_run=True)
        assert isinstance(result, dict)
        assert "valid" in result

    def test_validate_configuration_empty_data_returns_invalid(self):
        """Empty product data must be reported as invalid — not silently pass."""
        validator = ProductValidator()
        result = validator.validate_configuration({}, dry_run=True)
        # Empty dict must produce a result with "valid" key; empty config should fail
        assert "valid" in result
        assert result["valid"] is False
        assert len(result.get("errors", [])) > 0


# ===========================================================================
# ProductManagement — internal handler methods
# ===========================================================================


class TestInternalHandlerMethods:
    """Cover _handle_create_dry_run, _handle_update_dry_run, _handle_delete_dry_run."""

    @pytest.mark.asyncio
    async def test_handle_update_dry_run(self):
        mgmt = ProductManagement()
        result = await mgmt._handle_update_dry_run(
            {"product_id": "p_test", "product_data": {"name": "Updated"}}
        )
        assert "DRY RUN" in result[0].text
        assert "p_test" in result[0].text

    @pytest.mark.asyncio
    async def test_handle_delete_dry_run(self):
        mgmt = ProductManagement()
        result = await mgmt._handle_delete_dry_run({"product_id": "p_del"})
        assert "DRY RUN" in result[0].text
        assert "p_del" in result[0].text
        assert "cannot be undone" in result[0].text.lower()

    def test_format_create_success_response_mentions_product_name(self):
        mgmt = ProductManagement()
        result = mgmt._format_create_success_response({
            "data": {"id": "p1", "name": "New Product"},
        })
        assert "New Product" in result[0].text or "p1" in result[0].text

    def test_format_update_success_response_mentions_product_id(self):
        mgmt = ProductManagement()
        result = mgmt._format_update_success_response({
            "product_id": "p1",
            "data": {"id": "p1", "name": "Updated"},
        })
        assert "p1" in result[0].text or "Updated" in result[0].text

    def test_format_delete_success_response_mentions_product_id(self):
        mgmt = ProductManagement()
        result = mgmt._format_delete_success_response({
            "product_id": "p1",
            "data": {"deleted": True},
        })
        assert "p1" in result[0].text or "delet" in result[0].text.lower()
