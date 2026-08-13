"""Tolerance for response fields relaxed from required to optional.

The upstream API relaxed a set of response fields (ids and read-model scalars)
from required to optional. The MCP previously hard-indexed several of those
values out of live response dicts, which now KeyErrors — or silently degrades —
when a legally absent field is missing. These tests pin the hardened behavior:

- Pick-first-default id lookups skip entries whose id is absent and select the
  first entry that carries one, falling back to the existing empty-result
  behavior when none does.
- Follow-up-essential ids (product/subscription) raise a structured ToolError
  when absent, never a bare KeyError and never a fabricated id.
- Read-model renderers degrade gracefully (structured error / omitted line /
  "n/a") rather than crashing or fabricating a zero.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.tools_decomposed.product_management import (
    ProductEnhancementProcessor,
    ProductHierarchyManager,
    ProductManagement,
    ProductManager,
)
from src.revenium_mcp_server.tools_decomposed.job_management import JobManager
from src.revenium_mcp_server.tools_decomposed.cost_controls_management import (
    CostControlsManagement,
)
from src.revenium_mcp_server.tools_decomposed.revenium_log_analysis import (
    ReveniumLogAnalysis,
)


_GET_CONFIG = "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value"
_VALIDATION_ENGINE = "src.revenium_mcp_server.product_validation_engine.ProductValidationEngine"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _product_client():
    client = MagicMock()
    client.team_id = "team_test"
    client.get_sources = AsyncMock(return_value={})
    client.get_metering_element_definitions = AsyncMock(return_value={})
    client.get_organizations = AsyncMock(return_value={})
    client._extract_embedded_data = MagicMock(return_value=[])
    client.create_product = AsyncMock(return_value={"id": "p_new", "name": "New"})
    client.create_subscription = AsyncMock(
        return_value={"id": "sub_new", "name": "Sub", "organizationId": "org_1"}
    )
    return client


def _make_enh_processor(client, nlp_processor=None):
    """Build a ProductEnhancementProcessor without the real NLP/template wiring."""
    proc = object.__new__(ProductEnhancementProcessor)
    proc.client = client
    proc.ucm_helper = None
    proc.nlp_processor = nlp_processor
    proc.template_library = MagicMock()
    proc.error_handler = MagicMock()
    proc.clarification_engine = MagicMock()
    return proc


def _make_hierarchy_manager(client):
    with patch(
        "src.revenium_mcp_server.tools_decomposed.product_management.get_hierarchy_navigation_service"
    ), patch(
        "src.revenium_mcp_server.tools_decomposed.product_management.get_entity_lookup_service"
    ), patch(
        "src.revenium_mcp_server.tools_decomposed.product_management.get_cross_tier_validator"
    ):
        mgr = ProductHierarchyManager(client)
    mgr.validator.validate_hierarchy_operation = AsyncMock(
        return_value=MagicMock(valid=True, issues=[])
    )
    return mgr


def _valid_product_data():
    return {
        "name": "AI Analytics Platform",
        "version": "1.0.0",
        "plan": {"type": "SUBSCRIPTION", "name": "Basic Plan", "currency": "USD"},
    }


def _valid_subscription_data():
    return {"name": "Customer Subscription", "clientEmailAddress": "customer@company.com"}


# ===========================================================================
# Pick-first-default source assignment (ProductManager.create_product)
# ===========================================================================


class TestCreateProductSourceAssignment:
    @pytest.mark.asyncio
    async def test_skips_source_entry_without_id(self):
        """A source lacking `id` is skipped in favor of the first id-bearing one."""
        client = _product_client()
        client._extract_embedded_data.return_value = [{"name": "no-id"}, {"id": "src_2"}]
        mgr = ProductManager(client)
        with patch(_VALIDATION_ENGINE) as engine, patch(_GET_CONFIG, return_value=None):
            engine.validate_for_mcp.return_value = {"isError": False, "content": []}
            await mgr.create_product({"product_data": {"name": "P", "plan": {"name": "PP"}}})
        sent = client.create_product.call_args[0][0]
        assert sent.get("sourceIds") == ["src_2"]

    @pytest.mark.asyncio
    async def test_no_source_with_id_assigns_no_default(self):
        """When no source carries an id, no default is assigned (empty-branch parity)."""
        client = _product_client()
        client._extract_embedded_data.return_value = [{"name": "no-id"}]
        mgr = ProductManager(client)
        with patch(_VALIDATION_ENGINE) as engine, patch(_GET_CONFIG, return_value=None):
            engine.validate_for_mcp.return_value = {"isError": False, "content": []}
            await mgr.create_product({"product_data": {"name": "P", "plan": {"name": "PP"}}})
        sent = client.create_product.call_args[0][0]
        assert not sent.get("sourceIds")


# ===========================================================================
# Pick-first-default source assignment (create_simple)
# ===========================================================================


class TestCreateSimpleSourceAssignment:
    @pytest.mark.asyncio
    async def test_skips_source_entry_without_id(self):
        client = _product_client()
        client._extract_embedded_data.return_value = [{"name": "no-id"}, {"id": "src_2"}]
        proc = _make_enh_processor(client)
        with patch(_GET_CONFIG, return_value=None):
            await proc.create_simple({"name": "Test"})
        sent = client.create_product.call_args[0][0]
        assert sent.get("sourceIds") == ["src_2"]

    @pytest.mark.asyncio
    async def test_no_source_with_id_assigns_no_default(self):
        client = _product_client()
        client._extract_embedded_data.return_value = [{"name": "no-id"}]
        proc = _make_enh_processor(client)
        with patch(_GET_CONFIG, return_value=None):
            await proc.create_simple({"name": "Test"})
        sent = client.create_product.call_args[0][0]
        assert not sent.get("sourceIds")


# ===========================================================================
# Pick-first-default source assignment (create_from_description, NLP path)
# ===========================================================================


class TestCreateFromDescriptionSourceAssignment:
    @pytest.mark.asyncio
    async def test_skips_source_entry_without_id(self):
        client = _product_client()
        client._extract_embedded_data.return_value = [{"name": "no-id"}, {"id": "src_2"}]
        nlp = MagicMock()
        nlp.parse_product_request.return_value = {
            "name": "My Product",
            "plan": {"name": "Plan", "currency": "USD"},
        }
        proc = _make_enh_processor(client, nlp_processor=nlp)
        with patch(_GET_CONFIG, return_value=None):
            await proc.create_from_description({"description": "a product"})
        sent = client.create_product.call_args[0][0]
        assert sent.get("sourceIds") == ["src_2"]


# ===========================================================================
# create_with_subscription — sources (empty-branch raises) and elements
# (empty-branch falls back)
# ===========================================================================


class TestCreateWithSubscriptionSourceAndElement:
    @pytest.mark.asyncio
    async def test_source_skips_entry_without_id(self):
        client = _product_client()
        client._extract_embedded_data.side_effect = [
            [{"name": "no-id"}, {"id": "src_2"}],  # sources
            [{"id": "elem_1"}],  # metering elements
            [{"id": "org_1"}],  # organizations
        ]
        mgr = _make_hierarchy_manager(client)
        with patch(_GET_CONFIG, return_value="owner_123"):
            await mgr.create_with_subscription(
                {
                    "product_data": _valid_product_data(),
                    "subscription_data": _valid_subscription_data(),
                }
            )
        sent = client.create_product.call_args[0][0]
        assert sent.get("sourceIds") == ["src_2"]

    @pytest.mark.asyncio
    async def test_all_sources_without_id_raise_tool_error(self):
        client = _product_client()
        client._extract_embedded_data.side_effect = [
            [{"name": "no-id"}],  # sources — none carry an id
            [{"id": "elem_1"}],
            [{"id": "org_1"}],
        ]
        mgr = _make_hierarchy_manager(client)
        with patch(_GET_CONFIG, return_value="owner_123"):
            with pytest.raises(ToolError):
                await mgr.create_with_subscription(
                    {
                        "product_data": _valid_product_data(),
                        "subscription_data": _valid_subscription_data(),
                    }
                )

    @pytest.mark.asyncio
    async def test_element_skips_entry_without_id(self):
        client = _product_client()
        client._extract_embedded_data.side_effect = [
            [{"id": "src_1"}],  # sources
            [{"name": "no-id"}, {"id": "elem_2"}],  # metering elements
            [{"id": "org_1"}],  # organizations
        ]
        mgr = _make_hierarchy_manager(client)
        with patch(_GET_CONFIG, return_value="owner_123"):
            await mgr.create_with_subscription(
                {
                    "product_data": _valid_product_data(),
                    "subscription_data": _valid_subscription_data(),
                }
            )
        sent = client.create_product.call_args[0][0]
        rating = sent["plan"]["ratingAggregations"][0]
        assert rating["elementDefinitionId"] == "elem_2"


# ===========================================================================
# Follow-up-essential ids — _format_create_with_subscription_response (F)
# ===========================================================================


class TestFormatCreateWithSubscriptionResponse:
    @pytest.mark.asyncio
    async def test_missing_product_id_raises_tool_error(self):
        mgmt = ProductManagement()
        result_data = {
            "result": {
                "product": {"name": "P", "sources": [], "plan": {}},
                "subscription": {"id": "s1", "name": "S"},
            }
        }
        with pytest.raises(ToolError):
            await mgmt._format_create_with_subscription_response(result_data)

    @pytest.mark.asyncio
    async def test_missing_subscription_id_raises_tool_error(self):
        mgmt = ProductManagement()
        result_data = {
            "result": {
                "product": {"id": "p1", "name": "P", "sources": [], "plan": {}},
                "subscription": {"name": "S"},
            }
        }
        with pytest.raises(ToolError):
            await mgmt._format_create_with_subscription_response(result_data)

    @pytest.mark.asyncio
    async def test_source_without_id_does_not_crash(self):
        mgmt = ProductManagement()
        result_data = {
            "result": {
                "product": {"id": "p1", "name": "P", "sources": [{"name": "no-id"}], "plan": {}},
                "subscription": {"id": "s1", "name": "S"},
            }
        }
        result = await mgmt._format_create_with_subscription_response(result_data)
        text = result[0].text
        assert "p1" in text
        assert "s1" in text


# ===========================================================================
# Follow-up-essential ids — handle_action create_with_subscription (G)
# ===========================================================================


class TestHandleActionCreateWithSubscription:
    def _mgmt_with_result(self, result):
        mgmt = ProductManagement()
        hierarchy_manager = MagicMock()
        hierarchy_manager.create_with_subscription = AsyncMock(return_value=result)
        mgmt._setup_managers = AsyncMock(
            return_value=(MagicMock(), MagicMock(), hierarchy_manager)
        )
        return mgmt

    @pytest.mark.asyncio
    async def test_missing_product_id_raises_tool_error(self):
        mgmt = self._mgmt_with_result(
            {
                "result": {
                    "product": {
                        "name": "P",
                        "sources": [],
                        "plan": {"period": "MONTH", "currency": "USD"},
                    },
                    "subscription": {"id": "s1", "name": "S", "client": {"label": "C"}},
                }
            }
        )
        with pytest.raises(ToolError):
            await mgmt.handle_action(
                "create_with_subscription",
                {"product_data": {}, "subscription_data": {}},
            )

    @pytest.mark.asyncio
    async def test_missing_subscription_id_raises_tool_error(self):
        mgmt = self._mgmt_with_result(
            {
                "result": {
                    "product": {
                        "id": "p1",
                        "name": "P",
                        "sources": [],
                        "plan": {"period": "MONTH", "currency": "USD"},
                    },
                    "subscription": {"name": "S", "client": {"label": "C"}},
                }
            }
        )
        with pytest.raises(ToolError):
            await mgmt.handle_action(
                "create_with_subscription",
                {"product_data": {}, "subscription_data": {}},
            )


# ===========================================================================
# Read-model pins (already-tolerant renderers, missing-field inputs)
# ===========================================================================


class TestJobRoiReadModel:
    @pytest.mark.asyncio
    async def test_get_job_roi_missing_fields_does_not_crash(self):
        """The single-job ROI read passes the payload through unchanged; a
        response missing ROI scalars renders without crashing or inventing
        values."""
        client = MagicMock()
        client.get_job_roi = AsyncMock(return_value={})
        mgr = JobManager(client)
        result = await mgr.get_job_roi({"job_id": "j1"})
        assert result["action"] == "get_job_roi"
        assert result["data"] == {}


class TestEnforcementRulesReadModel:
    @pytest.mark.asyncio
    async def test_missing_rules_and_compiled_at_render_cleanly(self):
        """A rule-set response missing both `rules` and `compiledAt` renders a
        zero-rule summary rather than raising."""
        client = MagicMock()
        client.get_enforcement_rules = AsyncMock(return_value={})
        mgmt = CostControlsManagement()
        mgmt.get_client = AsyncMock(return_value=client)
        result = await mgmt.handle_action("get_enforcement_rules", {})
        text = result[0].text
        assert "0 rules" in text


class TestIngestionFailuresReadModel:
    @pytest.mark.asyncio
    async def test_entry_missing_all_fields_does_not_crash(self):
        """An ingestion-failure entry missing failureTimestamp/errors/
        originalPayload renders with an 'unknown time' placeholder, no crash."""
        failures = {
            "_embedded": {"items": [{}]},
            "page": {"totalElements": 1, "totalPages": 1},
        }
        client = MagicMock()
        client.get_ingestion_failures = AsyncMock(return_value=failures)
        client._extract_embedded_data = MagicMock(
            side_effect=lambda resp: resp.get("_embedded", {}).get("items", [])
            if isinstance(resp, dict)
            else []
        )
        client._extract_pagination_info = MagicMock(
            side_effect=lambda resp: resp.get("page", {}) if isinstance(resp, dict) else {}
        )
        log_tool = ReveniumLogAnalysis()
        log_tool.get_client = AsyncMock(return_value=client)
        result = await log_tool.handle_action("get_ingestion_failures", {})
        text = result[0].text
        assert "unknown time" in text


class TestDefaultScanWindow:
    """The id-bearing scan needs more than one entry to scan: a size=1 fetch
    makes 'skip the id-less entry, take the next' structurally impossible, so
    the default-source/element lookups must request a real page to scan."""

    @pytest.mark.asyncio
    async def test_default_source_fetch_requests_a_scan_window(self):
        client = _product_client()
        mgr = ProductManager(client)
        with patch(_VALIDATION_ENGINE) as engine, patch(_GET_CONFIG, return_value=None):
            engine.validate_for_mcp.return_value = {"isError": False, "content": []}
            await mgr.create_product({"product_data": {"name": "P", "plan": {"name": "PP"}}})
        assert client.get_sources.await_args.kwargs.get("size", 1) >= 10


    @pytest.mark.asyncio
    async def test_scan_traverses_pages_when_first_page_has_no_id(self):
        """A full page of id-less entries must not end the scan: the next
        page is fetched (bounded) and its id-bearing entry wins."""
        client = _product_client()
        page0 = [{"name": f"no-id-{n}"} for n in range(20)]
        page1 = [{"id": "src_deep"}]
        client._extract_embedded_data.side_effect = [page0, page1]
        mgr = ProductManager(client)
        with patch(_VALIDATION_ENGINE) as engine, patch(_GET_CONFIG, return_value=None):
            engine.validate_for_mcp.return_value = {"isError": False, "content": []}
            await mgr.create_product({"product_data": {"name": "P", "plan": {"name": "PP"}}})
        sent = client.create_product.call_args[0][0]
        assert sent.get("sourceIds") == ["src_deep"]
        assert client.get_sources.await_count == 2

    @pytest.mark.asyncio
    async def test_scan_stops_at_a_partial_page_of_idless_entries(self):
        """A partial page proves the listing is exhausted: no further fetch,
        no default assigned."""
        client = _product_client()
        client._extract_embedded_data.side_effect = [[{"name": "no-id"}]]
        mgr = ProductManager(client)
        with patch(_VALIDATION_ENGINE) as engine, patch(_GET_CONFIG, return_value=None):
            engine.validate_for_mcp.return_value = {"isError": False, "content": []}
            await mgr.create_product({"product_data": {"name": "P", "plan": {"name": "PP"}}})
        sent = client.create_product.call_args[0][0]
        assert not sent.get("sourceIds")
        assert client.get_sources.await_count == 1

    @pytest.mark.asyncio
    async def test_scan_is_bounded(self):
        """Every page full of id-less entries: the scan gives up after its
        page budget instead of walking the whole tenant."""
        client = _product_client()
        full_idless = [{"name": "no-id"} for _ in range(20)]
        client._extract_embedded_data.side_effect = [full_idless] * 10
        mgr = ProductManager(client)
        with patch(_VALIDATION_ENGINE) as engine, patch(_GET_CONFIG, return_value=None):
            engine.validate_for_mcp.return_value = {"isError": False, "content": []}
            await mgr.create_product({"product_data": {"name": "P", "plan": {"name": "PP"}}})
        sent = client.create_product.call_args[0][0]
        assert not sent.get("sourceIds")
        assert client.get_sources.await_count <= 5


    @pytest.mark.asyncio
    async def test_bound_hit_is_reported_distinctly_from_true_absence(self):
        """Giving up at the page budget is not proof of absence: the error
        for a truncated scan must say the scan was bounded, not that no
        sources exist."""
        client = _product_client()
        full_idless = [{"name": "no-id"} for _ in range(20)]
        client._extract_embedded_data.side_effect = [full_idless] * 10
        mgr = _make_hierarchy_manager(client)
        with patch(_GET_CONFIG, return_value="owner_123"):
            with pytest.raises(ToolError) as exc:
                await mgr.create_with_subscription(
                    {
                        "product_data": _valid_product_data(),
                        "subscription_data": _valid_subscription_data(),
                    }
                )
        message = str(exc.value.message).lower()
        assert "first 100" in message or "scan" in message
        assert "no sources available" not in message

    @pytest.mark.asyncio
    async def test_true_absence_keeps_the_existing_message(self):
        client = _product_client()
        client._extract_embedded_data.side_effect = [[]]
        mgr = _make_hierarchy_manager(client)
        with patch(_GET_CONFIG, return_value="owner_123"):
            with pytest.raises(ToolError) as exc:
                await mgr.create_with_subscription(
                    {
                        "product_data": _valid_product_data(),
                        "subscription_data": _valid_subscription_data(),
                    }
                )
        assert "no sources available" in str(exc.value.message).lower()


    @pytest.mark.asyncio
    async def test_scan_reads_the_top_level_data_envelope(self):
        """The sibling consumer of this endpoint treats a top-level ``data``
        list as a supported response shape; the id scan must not convert it
        to empty and fall back while eligible entries exist. Uses the real
        extractor, not a mock."""
        from src.revenium_mcp_server.client import ReveniumClient

        client = _product_client()
        client._extract_embedded_data = ReveniumClient._extract_embedded_data.__get__(client)
        client.get_sources = AsyncMock(
            return_value={"_embedded": {"sources": [{"id": "src_1"}]}}
        )
        client.get_metering_element_definitions = AsyncMock(
            return_value={"data": [{"id": "elem_from_data"}]}
        )
        client.get_organizations = AsyncMock(
            return_value={"_embedded": {"organizations": [{"id": "org_1"}]}}
        )
        mgr = _make_hierarchy_manager(client)
        with patch(_GET_CONFIG, return_value="owner_123"):
            await mgr.create_with_subscription(
                {
                    "product_data": _valid_product_data(),
                    "subscription_data": _valid_subscription_data(),
                }
            )
        sent = client.create_product.call_args[0][0]
        aggregations = sent["plan"]["ratingAggregations"]
        assert aggregations and aggregations[0].get("elementDefinitionId") == "elem_from_data"

    @pytest.mark.asyncio
    async def test_default_element_fetch_requests_a_scan_window(self):
        client = _product_client()
        client._extract_embedded_data.side_effect = [
            [{"id": "src_1"}],  # sources
            [{"id": "elem_1"}],  # metering elements
            [{"id": "org_1"}],  # organizations
        ]
        mgr = _make_hierarchy_manager(client)
        with patch(_GET_CONFIG, return_value="owner_123"):
            await mgr.create_with_subscription(
                {
                    "product_data": _valid_product_data(),
                    "subscription_data": _valid_subscription_data(),
                }
            )
        assert (
            client.get_metering_element_definitions.await_args.kwargs.get("size", 1)
            >= 10
        )
