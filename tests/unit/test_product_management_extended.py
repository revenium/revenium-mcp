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
    client.get_organization_by_id = AsyncMock(return_value={"id": "org_1"})
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

    The preview runs ProductManager.prepare_create_payload, the builder the
    real create uses, so it validates with ProductValidationEngine.validate_for_mcp.
    """

    _ENGINE = "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"
    _CONFIG = "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value"

    async def _preview(self, arguments, *, valid=True):
        mgmt, client = _make_mgmt_with_client()
        with patch(self._ENGINE) as MockEngine, patch(self._CONFIG, return_value=None):
            MockEngine.validate_for_mcp.return_value = {
                "isError": not valid,
                "content": [{"type": "text", "text": "Missing name field"}],
            }
            result = await mgmt.handle_action("create", {**arguments, "dry_run": True})
        client.create_product.assert_not_awaited()
        return result

    @pytest.mark.asyncio
    async def test_dry_run_structured_validation_valid(self):
        """Dry run without description uses structured validation."""
        result = await self._preview({"product_data": {"name": "Test"}})
        text = result[0].text
        assert "DRY RUN" in text
        assert "Validation Successful" in text
        assert "**Input Mode:** structured" in text

    @pytest.mark.asyncio
    async def test_dry_run_structured_validation_invalid(self):
        from src.revenium_mcp_server.common.error_handling import ToolError

        with pytest.raises(ToolError) as exc_info:
            await self._preview({"product_data": {"name": "Bad"}}, valid=False)
        assert "Missing name field" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_dry_run_no_product_data_uses_empty_dict(self):
        """A preview with nothing to build is refused the way the real create is."""
        from src.revenium_mcp_server.common.error_handling import ToolError

        with pytest.raises(ToolError):
            await self._preview({})

    @pytest.mark.asyncio
    async def test_dry_run_with_resource_data_backward_compat(self):
        """Dry run supports resource_data as backward-compatible alias."""
        result = await self._preview({"resource_data": {"name": "Compat Product"}})
        text = result[0].text
        assert "DRY RUN" in text
        assert "Validation Successful" in text
        assert "**Name:** Compat Product" in text


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
    async def test_create_simple_answer_says_unpublished_and_no_source(self):
        mgmt, client = _make_mgmt_with_client()
        with patch.object(ProductEnhancementProcessor, "__init__", return_value=None):
            ep = ProductEnhancementProcessor.__new__(ProductEnhancementProcessor)
            ep.create_simple = AsyncMock(
                return_value={"id": "p_simple", "name": "Simple", "published": False, "sources": []}
            )
            ep.nlp_processor = None

            with patch.object(mgmt, "_setup_managers", new_callable=AsyncMock, return_value=(MagicMock(), ep, MagicMock())):
                result = await mgmt.handle_action("create_simple", {"name": "Simple"})

        first = result[0].text.splitlines()[0]
        assert "not published" in first
        assert "No data source" in first

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
    async def test_unknown_action_raises_tool_error(self):
        """Unknown action must propagate ToolError so the MCP envelope reports isError=true."""
        from src.revenium_mcp_server.common.error_handling import ToolError

        mgmt, _ = _make_mgmt_with_client()
        with pytest.raises(ToolError) as exc_info:
            await mgmt.handle_action("totally_bogus_action", {})
        msg = str(exc_info.value).lower()
        assert "unknown action" in msg or "not supported" in msg


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


def _previewed_body(preview_text: str) -> dict:
    heading = "**Body the update would send:**"
    assert heading in preview_text
    return json.loads(preview_text.split(heading, 1)[1].split("**Dry Run:**", 1)[0])


def _preview_manager(product_id: str) -> ProductManager:
    client = MagicMock()
    client.team_id = "team_abc"
    client.get_product_by_id = AsyncMock(
        return_value={
            "id": product_id,
            "name": "Stored",
            "version": "1.0.0",
            "paymentSource": "INVOICE_ONLY_NO_PAYMENT",
            "plan": {"type": "SUBSCRIPTION", "tiers": [{"name": "t1"}]},
        }
    )
    client.prepare_product_update_body = lambda body: body
    client.update_product = AsyncMock()
    return ProductManager(client)


class TestInternalHandlerMethods:
    """Cover _handle_create_dry_run, _handle_update_dry_run, _handle_delete_dry_run."""

    @pytest.mark.asyncio
    async def test_handle_update_dry_run(self):
        mgmt = ProductManagement()
        manager = _preview_manager("p_test")
        result = await mgmt._handle_update_dry_run(
            {"product_id": "p_test", "product_data": {"name": "Updated"}}, manager
        )
        assert "DRY RUN" in result[0].text
        assert "p_test" in result[0].text
        body = _previewed_body(result[0].text)
        assert body["name"] == "Updated"
        assert body["version"] == "1.0.0"
        assert body["paymentSource"] == "INVOICE_ONLY_NO_PAYMENT"
        manager.client.get_product_by_id.assert_awaited()
        manager.client.update_product.assert_not_awaited()

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


# ===========================================================================
# Next steps printed after a product create
# ===========================================================================


def _printed_subscriber_call():
    """The add-subscribers call a create answer prints, as (keywords, text)."""
    import ast

    answer = ProductManagement()._format_create_success_response(
        {"data": {"id": "p1", "name": "New Product"}}
    )[0].text
    start = answer.index("manage_customers(")
    depth = 0
    for end in range(start, len(answer)):
        if answer[end] == "(":
            depth += 1
        elif answer[end] == ")":
            depth -= 1
            if depth == 0:
                break
    call_text = answer[start : end + 1]
    call = ast.parse(call_text.replace("...", "None"), mode="eval").body
    keywords = {kw.arg: ast.literal_eval(kw.value) for kw in call.keywords}
    return keywords, call_text


def _subscriber_arguments(keywords, **extra):
    """Fill the printed placeholders with concrete values, keeping every printed key."""
    concrete = {
        "email": "a@example.com",
        "firstName": "A",
        "lastName": "B",
        "organizationIds": ["org_1"],
    }
    filled = dict(keywords)
    for data_key in ("resource_data", "subscriber_data"):
        data = filled.get(data_key)
        if isinstance(data, dict):
            filled[data_key] = {key: concrete.get(key, "x") for key in data}
        elif data is not None:
            filled[data_key] = dict(concrete)
    return {**filled, **extra}


def _customers_client():
    client = MagicMock()
    client.team_id = "team_test"
    client.create_subscriber = AsyncMock(
        return_value={"id": "sub_1", "email": "a@example.com", "roles": []}
    )
    client.create_organization = AsyncMock(return_value={"id": "org_new"})
    client.get_organizations = AsyncMock(return_value={})
    client._extract_embedded_data = MagicMock(return_value=[{"id": "org_first"}])
    return client


class TestCreateNextSteps:
    """The add-subscribers step every create answer prints must be a call the
    customers tool accepts, and it must create a subscriber."""

    @pytest.mark.asyncio
    async def test_every_create_answer_prints_a_subscriber_call_the_customers_tool_accepts(self):
        import inspect
        from pathlib import Path

        import src.revenium_mcp_server.tools_decomposed.product_management as module
        from tests.unit.test_tool_config_registry_m4 import (
            _get_registered_closure,
            _make_registry,
        )

        closure = await _get_registered_closure(
            _make_registry(profile="business"), "_register_manage_customers"
        )
        declared = set(inspect.signature(closure).parameters)
        keywords, call_text = _printed_subscriber_call()

        assert sorted(set(keywords) - declared) == [], call_text
        assert keywords.get("resource_type") == "subscribers", call_text
        assert "organizationIds" in (keywords.get("resource_data") or {}), call_text
        assert "subscriber_data={" not in Path(module.__file__).read_text()

    @pytest.mark.asyncio
    async def test_the_printed_subscriber_call_previews_a_subscriber(self):
        from src.revenium_mcp_server.tools_decomposed.customer_management import (
            CustomerManagement,
        )
        from tests.unit.test_tool_config_registry_m4 import _call_through_the_boundary

        keywords, call_text = _printed_subscriber_call()
        with patch.object(
            CustomerManagement, "get_client", AsyncMock(return_value=_customers_client())
        ):
            is_error, text, _ = await _call_through_the_boundary(
                "_register_manage_customers",
                "manage_customers",
                _subscriber_arguments(keywords, dry_run=True),
                execute=True,
            )

        assert not is_error, f"{call_text}\n{text}"
        assert "Would create subscriber" in text

    @pytest.mark.asyncio
    async def test_the_printed_subscriber_call_creates_a_subscriber_not_an_organization(self):
        from src.revenium_mcp_server.tools_decomposed.customer_management import (
            CustomerManagement,
        )
        from tests.unit.test_tool_config_registry_m4 import _call_through_the_boundary

        keywords, call_text = _printed_subscriber_call()
        client = _customers_client()
        with patch.object(CustomerManagement, "get_client", AsyncMock(return_value=client)):
            is_error, text, _ = await _call_through_the_boundary(
                "_register_manage_customers",
                "manage_customers",
                _subscriber_arguments(keywords),
                execute=True,
            )

        assert not is_error, f"{call_text}\n{text}"
        client.create_organization.assert_not_awaited()
        client.create_subscriber.assert_awaited_once()
        sent = client.create_subscriber.await_args[0][0]
        for key in keywords["resource_data"]:
            assert key in sent, key
        assert sent["organizationIds"] == ["org_1"]


class TestCreateWithSubscriptionThroughHandleAction:
    """The live create_with_subscription answer tolerates a platform response
    without optional blocks once both records exist."""

    @pytest.mark.asyncio
    async def test_creates_both_and_answers_without_a_client_block(self):
        mgmt, client = _make_mgmt_with_client()
        client.get_metering_element_definitions = AsyncMock(return_value={})
        client.get_organizations = AsyncMock(return_value={})
        client._extract_embedded_data.return_value = [{"id": "src_1"}]
        client.create_product.return_value = {"id": "p_new", "name": "P"}
        client.create_subscription = AsyncMock(return_value={"id": "sub_new"})
        validation = MagicMock(valid=True, issues=[])

        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ), patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_cross_tier_validator"
        ) as validator_factory:
            validator_factory.return_value.validate_hierarchy_operation = AsyncMock(
                return_value=validation
            )
            result = await mgmt.handle_action(
                "create_with_subscription",
                {
                    "product_data": {
                        "name": "P",
                        "version": "1.0.0",
                        "plan": {"type": "SUBSCRIPTION", "name": "Plan", "currency": "USD"},
                    },
                    "subscription_data": {
                        "name": "S",
                        "clientEmailAddress": "a@example.com",
                        "organizationId": "org_1",
                    },
                },
            )

        client.create_product.assert_awaited_once()
        client.create_subscription.assert_awaited_once()
        assert client.create_subscription.await_args[0][0]["productId"] == "p_new"
        assert "p_new" in result[0].text
        assert "sub_new" in result[0].text


# ===========================================================================
# create preview runs the same builder as the real create
# ===========================================================================


def _flat_fee_product_data():
    return ProductValidator().get_examples()["flat_fee_example"]["template"]["product_data"]


_CREATE_FORMS = {
    "description_only": lambda: {"description": "An API product billed per call"},
    "name_only": lambda: {"name": "x"},
    "structured_valid": lambda: {"product_data": _flat_fee_product_data()},
    "resource_data_alias": lambda: {"resource_data": _flat_fee_product_data()},
    "hybrid": lambda: {
        "description": "An API product billed per call",
        "product_data": {"name": "Custom"},
    },
    "nothing": lambda: {},
    "name_without_auto_generate": lambda: {"name": "x", "auto_generate": False},
    "deprecated_plan": lambda: {
        "product_data": {
            **_flat_fee_product_data(),
            "plan": {**_flat_fee_product_data()["plan"], "type": "CHARGE"},
        }
    },
}


async def _create_outcome(arguments):
    """Run one create through handle_action: (answer text or None, error or None, client)."""
    from src.revenium_mcp_server.common.error_handling import ToolError

    mgmt, client = _make_mgmt_with_client()
    client._extract_embedded_data.return_value = [{"id": "src_1"}]
    with patch(
        "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
        return_value=None,
    ):
        try:
            result = await mgmt.handle_action("create", arguments)
        except ToolError as error:
            return None, error, client
    return result[0].text, None, client


class TestCreatePreviewMatchesRealCreate:
    """A preview gives the verdict the real create would give, and names the
    product the real create would send."""

    @pytest.mark.parametrize("form", sorted(_CREATE_FORMS))
    @pytest.mark.asyncio
    async def test_preview_verdict_matches_the_real_create(self, form):
        preview_text, preview_error, preview_client = await _create_outcome(
            {**_CREATE_FORMS[form](), "dry_run": True}
        )
        preview_client.create_product.assert_not_awaited()

        _, real_error, real_client = await _create_outcome(_CREATE_FORMS[form]())

        assert (preview_error is None) == (real_error is None), (
            preview_text or preview_error,
            real_error,
        )
        if real_error is None:
            sent_name = real_client.create_product.call_args[0][0]["name"]
            assert f"**Name:** {sent_name}" in preview_text, preview_text


class TestCreatePreviewShowsTheSentBody:
    """The preview's configuration is the body the real create sends."""

    @pytest.mark.asyncio
    async def test_configuration_is_field_mapped_and_carries_the_team(self):
        import json

        product_data = {
            **_flat_fee_product_data(),
            "plan": {
                **_flat_fee_product_data()["plan"],
                "tiers": [{"name": "Base", "up_to": 1000, "unit_amount": "0.5"}],
            },
        }
        mgmt, client = _make_mgmt_with_client()
        client.team_id = "team_7"
        with patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ):
            result = await mgmt.handle_action(
                "create", {"product_data": product_data, "dry_run": True}
            )

        text = result[0].text
        body = json.loads(text.split("```json\n", 1)[1].split("\n```", 1)[0])
        tier = body["plan"]["tiers"][0]
        assert tier["upTo"] == 1000
        assert tier["unitAmount"] == "0.5"
        assert "up_to" not in tier and "unit_amount" not in tier
        assert body["teamId"] == "team_7"
        assert "**Name:** " in text and "**Plan Type:** " in text
