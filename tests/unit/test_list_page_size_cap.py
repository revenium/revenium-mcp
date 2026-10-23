"""BACK-4722: list actions accept page sizes up to the platform maximum of 100.

The platform serves at most 100 rows per page. Every list action that refuses a size
between 51 and 100 is refusing a request the platform would honour.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

import ast
import inspect

from src.revenium_mcp_server.alerts import anomaly_inventory
from src.revenium_mcp_server.client import ReveniumClient
from src.revenium_mcp_server.common import pagination_performance, platform_paging, validation
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.common.pagination_performance import (
    PaginationPerformanceManager,
    validate_pagination_with_performance,
)
from src.revenium_mcp_server.common.validation import validate_pagination_params
from src.revenium_mcp_server.tools_decomposed import (
    alert_management,
    job_management,
    product_management,
    subscription_management,
)
from src.revenium_mcp_server.tools_decomposed.ai_insights_management import AIInsightsManagement
from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement
from src.revenium_mcp_server.tools_decomposed.job_management import JobManager
from src.revenium_mcp_server.tools_decomposed.product_management import ProductManager
from src.revenium_mcp_server.tools_decomposed.source_management import SourceManager

PLATFORM_MAXIMUM = platform_paging.PLATFORM_MAX_PAGE_SIZE


def _list_client(*list_calls: str) -> MagicMock:
    client = MagicMock()
    client.team_id = "test_team_id"
    for name in list_calls:
        setattr(client, name, AsyncMock(return_value={}))
    client._extract_embedded_data = MagicMock(return_value=[])
    client._extract_pagination_info = MagicMock(return_value={"totalPages": 1, "totalElements": 0})
    return client


class TestPerformanceValidator:
    @pytest.mark.parametrize(
        ("size", "tier"),
        [
            (1, "optimal"),
            (25, "optimal"),
            (40, "medium"),
            (41, "high"),
            (50, "high"),
            (51, "high"),
            (100, "high"),
        ],
    )
    def test_performance_validator_accepts_the_platform_maximum(self, size, tier):
        result = PaginationPerformanceManager().validate_pagination_params(0, size, "t")

        assert result["validation_status"] == "valid"
        assert result["performance_tier"] == tier

    def test_performance_validator_refuses_above_the_maximum_naming_100(self):
        with pytest.raises(ValueError, match=r"^Maximum page size is 100 items$"):
            PaginationPerformanceManager().validate_pagination_params(0, 101, "t")

    def test_performance_validator_does_not_refuse_the_maximum_itself(self):
        validate_pagination_with_performance(0, 100, "t")

    def test_performance_summary_high_tier_ends_at_the_maximum(self):
        manager = PaginationPerformanceManager()
        manager.validate_pagination_params(0, 50, "t")

        thresholds = manager.get_performance_summary()["thresholds"]

        assert thresholds["high"] == "41-100 items"


@pytest.mark.asyncio
class TestListActionsAcceptTheMaximum:
    @pytest.mark.parametrize("size", [51, 75, 100])
    async def test_products_list_accepts_sizes_up_to_the_platform_maximum(self, size):
        client = _list_client("get_products")

        result = await ProductManager(client).list_products({"page": 0, "size": size})

        assert result["pagination"]["size"] == size
        client.get_products.assert_awaited_once_with(page=0, size=size)

    async def test_products_list_refuses_101_with_a_structured_error_naming_100(self):
        client = _list_client("get_products")

        with pytest.raises(ToolError) as refusal:
            await ProductManager(client).list_products({"page": 0, "size": 101})

        assert refusal.value.field == "size"
        assert "100" in refusal.value.message
        client.get_products.assert_not_awaited()

    @pytest.mark.parametrize("size", [75, 100])
    async def test_sources_list_accepts_sizes_up_to_the_platform_maximum(self, size):
        client = _list_client("get_sources")

        await SourceManager(client).list_sources({"page": 0, "size": size})

        client.get_sources.assert_awaited_once_with(page=0, size=size)

    async def test_alerts_list_accepts_size_75_instead_of_reporting_a_failure(self):
        tools = AlertManagement()
        tools.alert_manager.list_alerts = AsyncMock(return_value=[])

        await tools._handle_list(
            MagicMock(), {"resource_type": "alerts", "page": 0, "size": 75}
        )

        assert tools.alert_manager.list_alerts.await_args.args[2] == 75

    async def test_anomalies_list_accepts_size_75(self):
        tools = AlertManagement()
        tools.anomaly_manager.list_anomalies = AsyncMock(return_value=[])

        await tools._handle_list(
            MagicMock(), {"resource_type": "anomalies", "page": 0, "size": 75}
        )

        assert tools.anomaly_manager.list_anomalies.await_args.args[2] == 75

    @pytest.mark.parametrize("size", [75, 100])
    async def test_jobs_list_accepts_sizes_up_to_the_platform_maximum(self, size):
        client = _list_client("get_jobs")

        await JobManager(client).list_jobs({"page": 0, "size": size})

        client.get_jobs.assert_awaited_once_with(page=0, size=size)

    async def test_jobs_list_refuses_101_naming_100(self):
        client = _list_client("get_jobs")

        with pytest.raises(ToolError) as refusal:
            await JobManager(client).list_jobs({"page": 0, "size": 101})

        assert refusal.value.field == "size"
        assert "100" in refusal.value.message
        client.get_jobs.assert_not_awaited()

    async def test_jobs_zero_size_suggestion_names_the_real_maximum(self):
        client = _list_client("get_jobs")

        with pytest.raises(ToolError) as refusal:
            await JobManager(client).list_jobs({"page": 0, "size": 0})

        assert any("between 1 and 100" in hint for hint in refusal.value.suggestions)


def _assigned_value(source_owner, name: str) -> ast.expr:
    tree = ast.parse(inspect.getsource(source_owner))
    values = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name) and target.id == name
    ]
    assert len(values) == 1, f"{name} is assigned {len(values)} times"
    return values[0]


@pytest.mark.parametrize(
    "owner, name",
    [
        (PaginationPerformanceManager, "MAXIMUM_LIMIT"),
        (product_management, "_MAX_PRODUCTS_SIZE"),
        (subscription_management, "_MAX_SUBSCRIPTIONS_SIZE"),
        (job_management, "_MAX_JOBS_SIZE"),
    ],
)
def test_every_list_size_cap_is_the_shared_platform_cap(owner, name):
    value = _assigned_value(owner, name)

    assert isinstance(value, ast.Name) and value.id == "PLATFORM_MAX_PAGE_SIZE"
    assert getattr(owner, name) is platform_paging.PLATFORM_MAX_PAGE_SIZE


def test_the_anomaly_inventory_page_size_is_the_shared_platform_cap():
    value = _assigned_value(anomaly_inventory, "ANOMALY_PAGE_SIZE")

    assert isinstance(value, ast.Name) and value.id == "PLATFORM_MAX_PAGE_SIZE"
    assert anomaly_inventory.ANOMALY_PAGE_SIZE is platform_paging.PLATFORM_MAX_PAGE_SIZE


def test_the_insights_runs_limit_is_its_own_bound_not_the_platform_cap():
    value = _assigned_value(AIInsightsManagement, "BACKEND_PAGE_LIMIT")

    assert isinstance(value, ast.Constant) and value.value == 100


def test_the_provider_api_key_page_range_is_its_own_bound_not_the_platform_cap():
    value = _assigned_value(alert_management, "PROVIDER_API_KEY_PAGE_SIZE_RANGE")

    assert isinstance(value, ast.Tuple)
    assert [bound.value for bound in value.elts if isinstance(bound, ast.Constant)] == [1, 100]


@pytest.mark.asyncio
async def test_the_organization_name_scan_pages_at_the_shared_platform_cap(monkeypatch):
    lowered_cap = 7
    monkeypatch.setattr(platform_paging, "PLATFORM_MAX_PAGE_SIZE", lowered_cap)
    client = ReveniumClient.__new__(ReveniumClient)
    client.get_organizations = AsyncMock(
        return_value={
            "_embedded": {"organizations": [{"id": "org-1", "name": "Acme"}]},
            "page": {"number": 0, "totalPages": 1},
        }
    )

    assert await client.resolve_organization_name_to_id("Acme") == "org-1"
    assert client.get_organizations.await_args.kwargs["size"] == lowered_cap


def test_the_performance_module_reads_the_shared_platform_cap():
    assert pagination_performance.PLATFORM_MAX_PAGE_SIZE is platform_paging.PLATFORM_MAX_PAGE_SIZE


def test_the_generic_size_bound_follows_the_shared_platform_cap(monkeypatch):
    lowered_cap = 7
    monkeypatch.setattr(validation, "PLATFORM_MAX_PAGE_SIZE", lowered_cap)

    validate_pagination_params({"size": lowered_cap}, action="x")
    with pytest.raises(ToolError):
        validate_pagination_params({"size": lowered_cap + 1}, action="x")


def test_the_platform_page_cap_is_defined_in_one_place():
    from pathlib import Path

    from src.revenium_mcp_server.tools_decomposed import (
        log_analysis_constants,
        metering_management,
    )

    package_root = Path(platform_paging.__file__).resolve().parents[1]
    definitions = [
        path.relative_to(package_root).as_posix()
        for path in package_root.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name) and target.id.endswith("PLATFORM_MAX_PAGE_SIZE")
    ]
    assert definitions == ["common/platform_paging.py"]
    assert platform_paging.PLATFORM_MAX_PAGE_SIZE == 100
    assert log_analysis_constants.DEFAULT_VALUES["size"] == platform_paging.PLATFORM_MAX_PAGE_SIZE
    assert (
        metering_management._LOOKUP_MAX_PAGE_SIZE
        == metering_management._LOOKUP_DEFAULT_PAGE_SIZE
        == metering_management._PROVIDER_CATALOG_PAGE_SIZE
        == platform_paging.PLATFORM_MAX_PAGE_SIZE
    )


class TestMeteringHelpStatesTheRealPageSize:
    """BACK-4795: the metering help promises no page larger than the platform serves."""

    async def _text(self, action):
        from src.revenium_mcp_server.tools_decomposed.metering_management import (
            MeteringManagement,
        )

        result = await MeteringManagement().handle_action(action, {})
        return result[0].text

    async def test_api_endpoints_state_the_platform_maximum(self):
        text = await self._text("get_api_endpoints")
        assert text.count(f"Page size (default: 20, max: {PLATFORM_MAXIMUM})") == 2
        assert "max: 50" not in text

    async def test_lookup_help_states_the_recent_page_range(self):
        text = await self._text("get_lookup_capabilities")
        assert f"Transactions per page (1-{PLATFORM_MAXIMUM}, default: 20)" in text
        assert "1-50" not in text

    @pytest.mark.parametrize(
        "action", ["get_lookup_capabilities", "get_field_documentation", "get_examples"]
    )
    async def test_lookup_help_promises_no_thousand_row_page(self, action):
        text = await self._text(action)
        for promise in (
            "1,000 transactions per",
            "1-1000",
            "10,000 transactions",
            '"page_size": 1000',
        ):
            assert promise not in text, promise

    def test_a_lookup_page_size_above_the_platform_maximum_is_lowered_and_said(self):
        from src.revenium_mcp_server.tools_decomposed.metering_management import (
            MeteringTransactionManager,
        )

        params = MeteringTransactionManager()._extract_lookup_parameters(
            {"transaction_ids": ["tx_a"], "page_size": 1000}
        )
        assert params["page_size"] == PLATFORM_MAXIMUM
        assert (
            f"page_size 1000 is above the limit of {PLATFORM_MAXIMUM}; used {PLATFORM_MAXIMUM}"
            in params["adjustments"]
        )

    def test_the_default_lookup_page_size_is_the_platform_maximum_unmentioned(self):
        from src.revenium_mcp_server.tools_decomposed.metering_management import (
            MeteringTransactionManager,
        )

        params = MeteringTransactionManager()._extract_lookup_parameters(
            {"transaction_ids": ["tx_a"]}
        )
        assert params["page_size"] == PLATFORM_MAXIMUM
        assert params["adjustments"] == []

    def test_the_page_search_default_is_the_lookup_constant(self):
        import inspect

        from src.revenium_mcp_server.tools_decomposed import metering_management

        signature = inspect.signature(
            metering_management.MeteringTransactionManager._search_transaction_pages
        )
        assert (
            signature.parameters["page_size"].default
            == metering_management._LOOKUP_DEFAULT_PAGE_SIZE
            == PLATFORM_MAXIMUM
        )
