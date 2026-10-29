"""Unit tests for tool_configuration/registry.py (M4 coverage batch).

Targets: ToolConfigurationRegistry initialization, register_tools_conditionally,
_register_domain dispatch, per-tool registration functions (inner closures),
JSON preprocessing branches, get_registered_tools, is_tool_registered,
_register_tool_metadata, and _register_tool_introspection.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.common.tool_surface import (
    DOMAINS_BY_KEY,
    TOOL_DOMAINS,
    public_tool_for,
)
from src.revenium_mcp_server.tool_configuration.registry import ToolConfigurationRegistry
from src.revenium_mcp_server.tool_configuration.config import ToolConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_registry(
    profile: str = "starter",
    custom_overrides: dict | None = None,
    tool_enabled: dict | None = None,
) -> ToolConfigurationRegistry:
    """Create a registry backed by a testing-safe ToolConfig."""
    tc = ToolConfig.create_for_testing(
        profile=profile,
        custom_overrides=custom_overrides or {},
        tool_enabled=tool_enabled or {},
    )
    return ToolConfigurationRegistry(tool_config=tc)


def _make_mock_mcp() -> MagicMock:
    """Return a minimal FastMCP mock. mcp.tool() returns a MagicMock used as decorator."""
    return MagicMock()


async def _get_registered_closure(registry, method_name: str) -> object:
    """Call a _register_* method and return the closure both of its published tools run."""
    mcp = _make_mock_mcp()
    register_method = getattr(registry, method_name)
    with patch.object(registry.tool_config, "is_tool_enabled", return_value=True):
        await register_method(mcp)
    return mcp.tool.call_args_list[0][0][0].__wrapped__


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestToolConfigurationRegistryInit:
    def test_default_init_creates_tool_config(self):
        """When no tool_config supplied, a ToolConfig() is created automatically."""
        with patch(
            "src.revenium_mcp_server.tool_configuration.registry.ToolConfig"
        ) as MockTC:
            instance = MockTC.return_value
            instance.profile = "starter"
            registry = ToolConfigurationRegistry()
            MockTC.assert_called_once_with()
            assert registry.tool_config is instance

    def test_custom_tool_config_stored(self):
        """Supplied tool_config is stored without replacement."""
        tc = ToolConfig.create_for_testing(profile="business")
        registry = ToolConfigurationRegistry(tool_config=tc)
        assert registry.tool_config is tc

    def test_initial_registered_tools_empty(self):
        """No tools are registered after initialization — public API reflects empty state."""
        registry = _make_registry()
        assert registry.get_registered_tools() == set()
        assert registry.is_tool_registered("manage_alerts") is False


# ---------------------------------------------------------------------------
# register_tools_conditionally
# ---------------------------------------------------------------------------

def _registered_keys(mock_reg) -> list:
    return [c.args[1].key for c in mock_reg.call_args_list]


class TestRegisterToolsConditionally:
    @pytest.mark.asyncio
    async def test_starter_registers_exactly_the_starter_domains(self):
        """Starter profile registers the domains whose public tools it lists."""
        from src.revenium_mcp_server.tool_configuration.profiles import PROFILE_DEFINITIONS

        registry = _make_registry(profile="starter")

        with patch.object(registry, "_register_domain", new_callable=AsyncMock) as mock_reg:
            await registry.register_tools_conditionally(_make_mock_mcp())

        expected = {
            domain.key
            for domain in TOOL_DOMAINS
            if set(domain.public_names) & PROFILE_DEFINITIONS["starter"]
        }
        assert set(_registered_keys(mock_reg)) == expected

    @pytest.mark.asyncio
    async def test_business_registers_every_domain(self):
        """Business profile registers every domain of the surface."""
        registry = _make_registry(profile="business")

        with patch.object(registry, "_register_domain", new_callable=AsyncMock) as mock_reg:
            await registry.register_tools_conditionally(_make_mock_mcp())

        assert _registered_keys(mock_reg) == [domain.key for domain in TOOL_DOMAINS]

    @pytest.mark.asyncio
    async def test_a_domain_with_every_tool_disabled_is_skipped(self):
        """A domain whose public tools are all disabled is never registered."""
        registry = _make_registry(
            profile="starter",
            tool_enabled={"get_alerts": False, "manage_alerts": False},
        )

        with patch.object(registry, "_register_domain", new_callable=AsyncMock) as mock_reg:
            await registry.register_tools_conditionally(_make_mock_mcp())

        assert "manage_alerts" not in _registered_keys(mock_reg)


# ---------------------------------------------------------------------------
# _register_domain dispatch
# ---------------------------------------------------------------------------

class TestRegisterDomainDispatch:
    def test_every_domain_has_a_registrar(self):
        registry = _make_registry()

        assert set(registry._domain_registrars()) == set(DOMAINS_BY_KEY)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("key,method_name", [
        ("get_business_analytics", "_register_business_analytics_management"),
        ("manage_alerts", "_register_manage_alerts"),
        ("manage_slack", "_register_slack_management"),
        ("manage_metering", "_register_manage_metering"),
        ("manage_system_setup", "_register_system_setup"),
        ("system_diagnostics", "_register_system_diagnostics"),
        ("manage_sources", "_register_manage_sources"),
        ("manage_workflows", "_register_manage_workflows"),
        ("manage_credentials", "_register_manage_subscriber_credentials"),
        ("manage_products", "_register_manage_products"),
        ("manage_customers", "_register_manage_customers"),
        ("manage_subscriptions", "_register_manage_subscriptions"),
        ("manage_usage_meters", "_register_manage_metering_elements"),
        ("get_capabilities", "_register_manage_capabilities"),
        ("tool_introspection", "_register_tool_introspection"),
    ])
    async def test_dispatches_to_correct_method(self, key, method_name):
        """_register_domain calls the dedicated registration method for each domain."""
        registry = _make_registry(profile="business")
        mcp = _make_mock_mcp()

        with patch.object(registry, method_name, new_callable=AsyncMock) as mock_method, \
             patch.object(registry, "_register_tool_metadata", new_callable=AsyncMock):
            await registry._register_domain(mcp, DOMAINS_BY_KEY[key])
            mock_method.assert_called_once_with(mcp)

    @pytest.mark.asyncio
    async def test_enabled_public_names_are_recorded_after_success(self):
        """After successful dispatch, the domain's enabled public tools are recorded."""
        registry = _make_registry(profile="business")

        with patch.object(registry, "_register_system_setup", new_callable=AsyncMock), \
             patch.object(registry, "_register_tool_metadata", new_callable=AsyncMock):
            await registry._register_domain(_make_mock_mcp(), DOMAINS_BY_KEY["manage_system_setup"])

        assert registry.is_tool_registered("get_system_setup")
        assert registry.is_tool_registered("manage_system_setup")

    @pytest.mark.asyncio
    async def test_exception_in_method_does_not_propagate_or_record(self):
        """If a registration method raises, _register_domain swallows it and records nothing."""
        registry = _make_registry(profile="business")

        with patch.object(
            registry, "_register_system_setup",
            new_callable=AsyncMock, side_effect=RuntimeError("boom")
        ):
            await registry._register_domain(_make_mock_mcp(), DOMAINS_BY_KEY["manage_system_setup"])

        assert not registry.is_tool_registered("get_system_setup")

    @pytest.mark.asyncio
    async def test_metadata_registered_under_the_domain_key(self):
        """_register_tool_metadata is called with the domain key after dispatch."""
        registry = _make_registry(profile="business")

        with patch.object(registry, "_register_system_setup", new_callable=AsyncMock), \
             patch.object(registry, "_register_tool_metadata", new_callable=AsyncMock) as mock_meta:
            await registry._register_domain(_make_mock_mcp(), DOMAINS_BY_KEY["manage_system_setup"])

        mock_meta.assert_called_once_with("manage_system_setup")


# ---------------------------------------------------------------------------
# get_registered_tools / is_tool_registered
# ---------------------------------------------------------------------------

class TestRegistryState:
    def test_is_tool_registered_true_for_added_tool(self):
        """is_tool_registered returns True when the tool is in _registered_tools."""
        registry = _make_registry()
        registry._registered_tools.add("manage_alerts")

        assert registry.is_tool_registered("manage_alerts") is True

    def test_is_tool_registered_false_for_absent_tool(self):
        """is_tool_registered returns False for a tool not in _registered_tools."""
        registry = _make_registry()

        assert registry.is_tool_registered("manage_alerts") is False


# ---------------------------------------------------------------------------
# _register_tool_metadata
# ---------------------------------------------------------------------------

class TestRegisterToolMetadata:
    @pytest.mark.asyncio
    async def test_tool_introspection_returns_early_without_warning_or_import(self):
        """tool_introspection causes early return: no warning logged, no importlib call made."""
        registry = _make_registry()

        with patch(
            "src.revenium_mcp_server.tool_configuration.registry.logger"
        ) as mock_logger, patch("importlib.import_module") as mock_import:
            await registry._register_tool_metadata("tool_introspection")
            mock_logger.warning.assert_not_called()
            # importlib must NOT be called for the early-return path
            called_names = [c.args[0] for c in mock_import.call_args_list]
            assert "revenium_mcp_server.tools_decomposed.tool_introspection" not in called_names

    @pytest.mark.asyncio
    async def test_unknown_tool_logs_warning_with_tool_name(self):
        """An unknown tool name logs a warning containing the tool name."""
        registry = _make_registry()

        with patch(
            "src.revenium_mcp_server.tool_configuration.registry.logger"
        ) as mock_logger:
            await registry._register_tool_metadata("unknown_tool_xyz")
            mock_logger.warning.assert_called()
            warning_msg = mock_logger.warning.call_args[0][0]
            assert "unknown_tool_xyz" in warning_msg

    @pytest.mark.asyncio
    async def test_known_domain_registers_its_class(self):
        """A known domain key registers its tool class with the introspection engine."""
        from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement

        registry = _make_registry()
        mock_introspection = MagicMock()
        mock_introspection.register_tool_metadata = AsyncMock()

        with patch(
            "src.revenium_mcp_server.introspection.integration.introspection_integration",
            mock_introspection,
        ):
            await registry._register_tool_metadata("manage_alerts")

        mock_introspection.register_tool_metadata.assert_awaited_once_with(
            "manage_alerts", AlertManagement
        )

    @pytest.mark.asyncio
    async def test_registration_error_logs_warning_not_raises(self):
        """A failing introspection registration is logged, not propagated."""
        registry = _make_registry()
        mock_introspection = MagicMock()
        mock_introspection.register_tool_metadata = AsyncMock(side_effect=RuntimeError("down"))

        with patch(
            "src.revenium_mcp_server.introspection.integration.introspection_integration",
            mock_introspection,
        ), patch("src.revenium_mcp_server.tool_configuration.registry.logger") as mock_logger:
            await registry._register_tool_metadata("manage_alerts")

        mock_logger.warning.assert_called()


# ---------------------------------------------------------------------------
# _register_tool_introspection
# ---------------------------------------------------------------------------

class TestRegisterToolIntrospection:
    @pytest.mark.asyncio
    async def test_delegates_add_introspection_tool_to_server(self):
        """_register_tool_introspection calls add_introspection_tool_to_server(mcp)."""
        registry = _make_registry()
        mcp = _make_mock_mcp()

        mock_integration = MagicMock()
        mock_integration.add_introspection_tool_to_server = AsyncMock()

        with patch(
            "src.revenium_mcp_server.introspection.integration.introspection_integration",
            mock_integration,
        ):
            await registry._register_tool_introspection(mcp)

        mock_integration.add_introspection_tool_to_server.assert_called_once_with(mcp)


# ---------------------------------------------------------------------------
# JSON preprocessing — manage_alerts (anomaly_data)
# ---------------------------------------------------------------------------

class TestManageAlertsJsonPreprocessing:
    """Tests for the inner manage_alerts closure's anomaly_data JSON handling."""

    @pytest.mark.asyncio
    async def test_valid_json_string_anomaly_data_is_parsed(self):
        """anomaly_data sent as a valid JSON string is converted to a dict before execution."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_alerts")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(
                action="create",
                anomaly_data='{"name": "test", "threshold": 50}',
            )

        assert isinstance(captured_args.get("anomaly_data"), dict)
        assert captured_args["anomaly_data"]["name"] == "test"

    @pytest.mark.asyncio
    async def test_malformed_json_string_anomaly_data_raises(self):
        """Malformed anomaly_data JSON string raises a ToolError."""
        from src.revenium_mcp_server.common.error_handling import ToolError

        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_alerts")

        with pytest.raises(ToolError) as raised:
            await registered_fn(
                action="create",
                anomaly_data="not valid json {{{{",
            )

        assert raised.value.field == "anomaly_data"
        assert raised.value.message.startswith("Invalid JSON for anomaly_data:")

    @pytest.mark.asyncio
    async def test_dict_anomaly_data_passed_through_unchanged(self):
        """dict anomaly_data is forwarded to execution without modification."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_alerts")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(
                action="create",
                anomaly_data={"name": "dict_alert"},
            )

        assert isinstance(captured_args.get("anomaly_data"), dict)
        assert captured_args["anomaly_data"]["name"] == "dict_alert"


# ---------------------------------------------------------------------------
# BACK-2374 — manage_alerts budget-progress closure params
# ---------------------------------------------------------------------------

class TestManageAlertsBudgetProgressParams:
    """The manage_alerts closure must accept anomaly_ids (list|JSON-string),
    include_trend, and now — FastMCP derives its input model from the
    signature."""

    async def _capture(self, **call_kwargs):
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_alerts")
        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            result = await registered_fn(**call_kwargs)
        return captured_args, result

    @pytest.mark.asyncio
    async def test_anomaly_ids_list_passed_through(self):
        captured, _ = await self._capture(
            action="get_budget_progress", anomaly_ids=["a1", "a2"]
        )
        assert captured.get("anomaly_ids") == ["a1", "a2"]

    @pytest.mark.asyncio
    async def test_anomaly_ids_json_string_is_parsed_to_list(self):
        captured, _ = await self._capture(
            action="get_budget_progress", anomaly_ids='["a1", "a2"]'
        )
        assert captured.get("anomaly_ids") == ["a1", "a2"]

    @pytest.mark.asyncio
    async def test_anomaly_ids_non_list_json_rejected(self):
        from src.revenium_mcp_server.common.error_handling import ToolError

        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_alerts")
        with pytest.raises(ToolError) as raised:
            await registered_fn(
                action="get_budget_progress", anomaly_ids='{"not": "a list"}'
            )
        assert raised.value.field == "anomaly_ids"
        assert raised.value.message.startswith("Invalid JSON for anomaly_ids:")
        assert "anomaly_ids must be a JSON array" in raised.value.message

    @pytest.mark.asyncio
    async def test_anomaly_ids_malformed_json_rejected(self):
        from src.revenium_mcp_server.common.error_handling import ToolError

        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_alerts")
        with pytest.raises(ToolError) as raised:
            await registered_fn(
                action="get_budget_progress", anomaly_ids="not json {{{"
            )
        assert raised.value.field == "anomaly_ids"
        assert raised.value.message.startswith("Invalid JSON for anomaly_ids:")
        assert "anomaly_ids must be a JSON array" in raised.value.message

    @pytest.mark.asyncio
    async def test_include_trend_and_now_forwarded(self):
        captured, _ = await self._capture(
            action="get_budget_portfolio",
            include_trend=True,
            now="2026-07-01T00:00:00Z",
        )
        assert captured.get("include_trend") is True
        assert captured.get("now") == "2026-07-01T00:00:00Z"


# ---------------------------------------------------------------------------
# JSON preprocessing — manage_sources (source_data)
# ---------------------------------------------------------------------------

class TestManageSourcesJsonPreprocessing:
    @pytest.mark.asyncio
    async def test_malformed_source_data_raises(self):
        """Malformed source_data JSON string raises a ToolError."""
        from src.revenium_mcp_server.common.error_handling import ToolError

        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_sources")

        with pytest.raises(ToolError) as raised:
            await registered_fn(
                action="create",
                source_data="{bad json",
            )

        assert raised.value.field == "source_data"
        assert raised.value.message.startswith("Invalid JSON for source_data:")

    @pytest.mark.asyncio
    async def test_valid_json_string_source_data_is_parsed(self):
        """Valid JSON string source_data is converted to dict."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_sources")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(
                action="create",
                source_data='{"name": "MySource", "type": "API"}',
            )

        assert isinstance(captured_args.get("source_data"), dict)
        assert captured_args["source_data"]["name"] == "MySource"


# ---------------------------------------------------------------------------
# get_business_analytics closure — dimension forwarding
# ---------------------------------------------------------------------------

class TestBusinessAnalyticsDimensionForwarding:
    @pytest.mark.asyncio
    async def test_dimension_forwarded_to_execution(self):
        """The dimension param must reach standardized_tool_execution arguments."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(
            registry, "_register_business_analytics_management"
        )

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(
                action="get_filter_options",
                dimension="models",
                period="THIRTY_DAYS",
            )

        assert captured_args.get("dimension") == "models"
        assert captured_args.get("action") == "get_filter_options"

    @pytest.mark.asyncio
    async def test_dimension_omitted_when_none(self):
        """When dimension is not supplied it is stripped (None values removed)."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(
            registry, "_register_business_analytics_management"
        )

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(action="get_capabilities")

        assert "dimension" not in captured_args


class TestBusinessAnalyticsUserCostsPageSize:
    """FRONT-3434: get_user_costs reaches its handler with a page of 100 users unless the caller
    sends a size, while the other actions keep the tool's default of 20."""

    @pytest.mark.asyncio
    async def test_page_size_default_follows_the_action(self):
        registered_fn = await _get_registered_closure(
            _make_registry(), "_register_business_analytics_management"
        )
        calls: list = []

        async def fake_execution(tool_name, action, arguments, tool_class):
            calls.append(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(action="get_user_costs", period="THIRTY_DAYS")
            await registered_fn(action="get_user_costs", period="THIRTY_DAYS", size=10)
            await registered_fn(action="get_department_costs", period="THIRTY_DAYS")

        assert [call["size"] for call in calls] == [100, 10, 20]


class TestBusinessAnalyticsCalendarRange:
    """FRONT-3434: start_date and end_date reach the cost actions through the registered tool."""

    @pytest.mark.asyncio
    async def test_registered_tool_declares_both(self):
        from fastmcp import FastMCP

        mcp = FastMCP("front-3434")
        await _make_registry()._register_business_analytics_management(mcp)
        tools = {tool.name: tool for tool in await mcp.list_tools(run_middleware=False)}
        properties = tools["get_business_analytics"].parameters["properties"]
        assert "start_date" in properties
        assert "end_date" in properties

    @pytest.mark.asyncio
    async def test_both_are_forwarded_to_a_cost_action_and_omitted_when_absent(self):
        registered_fn = await _get_registered_closure(
            _make_registry(), "_register_business_analytics_management"
        )
        calls: list = []

        async def fake_execution(tool_name, action, arguments, tool_class):
            calls.append(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(
                action="get_provider_costs", start_date="2026-09-01", end_date="2026-09-30"
            )
            await registered_fn(
                action="get_team_costs",
                params={"start_date": "2026-09-01", "end_date": "2026-09-30"},
            )
            await registered_fn(action="get_provider_costs", period="THIRTY_DAYS")

        assert (calls[0]["start_date"], calls[0]["end_date"]) == ("2026-09-01", "2026-09-30")
        assert (calls[1]["start_date"], calls[1]["end_date"]) == ("2026-09-01", "2026-09-30")
        assert "start_date" not in calls[2] and "end_date" not in calls[2]


# ---------------------------------------------------------------------------
# manage_metering closure — ticket/skill attribution forwarding
# ---------------------------------------------------------------------------

class TestManageMeteringAttributionForwarding:
    """The registered MCP boundary must declare and forward the ticket and
    skill attribution fields — handler support beneath an undeclared
    parameter is unreachable for every MCP client (FastMCP builds the tool
    schema from the closure signature and rejects unknown parameters)."""

    ATTRIBUTION = {
        "ticket_id": "JIRA-42",
        "skill_name": "portfolio-analyzer",
        "skill_source": "plugin",
        "skill_kind": "workflow",
        "skill_plugin_name": "finance-pack",
        "skill_marketplace_name": "acme-marketplace",
        "skill_invocation_trigger": "user-slash",
    }

    @pytest.mark.asyncio
    async def test_attribution_fields_forwarded_to_execution(self):
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_metering")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(action="submit_ai_transaction", **self.ATTRIBUTION)

        for key, value in self.ATTRIBUTION.items():
            assert captured_args.get(key) == value, key

    @pytest.mark.asyncio
    async def test_attribution_fields_omitted_when_absent(self):
        """Absent attribution fields are stripped with the other None values —
        the payload builder's omit-if-unset contract starts at the boundary."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_metering")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(action="get_capabilities")

        for key in self.ATTRIBUTION:
            assert key not in captured_args


# ---------------------------------------------------------------------------
# JSON preprocessing — manage_workflows (context, workflow_data)
# ---------------------------------------------------------------------------

class TestManageWorkflowsJsonPreprocessing:
    @pytest.mark.asyncio
    async def test_malformed_context_raises(self):
        """Malformed context JSON string raises a ToolError."""
        from src.revenium_mcp_server.common.error_handling import ToolError

        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_workflows")

        with pytest.raises(ToolError) as raised:
            await registered_fn(
                action="start",
                context="{invalid",
            )

        assert raised.value.field == "context"
        assert raised.value.message.startswith("Invalid JSON for context:")

    @pytest.mark.asyncio
    async def test_malformed_workflow_data_raises(self):
        """Malformed workflow_data JSON string raises a ToolError."""
        from src.revenium_mcp_server.common.error_handling import ToolError

        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_workflows")

        with pytest.raises(ToolError) as raised:
            await registered_fn(
                action="create",
                context=None,
                workflow_data="{broken",
            )

        assert raised.value.field == "workflow_data"
        assert raised.value.message.startswith("Invalid JSON for workflow_data:")

    @pytest.mark.asyncio
    async def test_valid_json_context_parsed(self):
        """Valid JSON string context is converted to dict before forwarding."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_workflows")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(
                action="start",
                context='{"customer_email": "a@b.com"}',
            )

        assert isinstance(captured_args.get("context"), dict)
        assert captured_args["context"]["customer_email"] == "a@b.com"


# ---------------------------------------------------------------------------
# JSON preprocessing — manage_credentials (credential_data)
# ---------------------------------------------------------------------------

class TestManageSubscriberCredentialsJsonPreprocessing:
    @pytest.mark.asyncio
    async def test_malformed_credential_data_raises(self):
        """Malformed credential_data JSON string raises a ToolError."""
        from src.revenium_mcp_server.common.error_handling import ToolError

        registry = _make_registry()
        registered_fn = await _get_registered_closure(
            registry, "_register_manage_subscriber_credentials"
        )

        with pytest.raises(ToolError) as raised:
            await registered_fn(
                action="create",
                credential_data="not-json",
            )

        assert raised.value.field == "credential_data"
        assert raised.value.message.startswith("Invalid JSON for credential_data:")

    @pytest.mark.asyncio
    async def test_valid_json_credential_data_parsed(self):
        """Valid JSON string credential_data is converted to dict."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(
            registry, "_register_manage_subscriber_credentials"
        )

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(
                action="create",
                credential_data='{"label": "mykey", "subscriberId": "sub_1"}',
            )

        assert isinstance(captured_args.get("credential_data"), dict)
        assert captured_args["credential_data"]["label"] == "mykey"


# ---------------------------------------------------------------------------
# JSON preprocessing — manage_products (product_data, resource_data)
# ---------------------------------------------------------------------------

class TestManageProductsJsonPreprocessing:
    @pytest.mark.asyncio
    async def test_malformed_product_data_raises(self):
        """Malformed product_data JSON string raises a ToolError."""
        from src.revenium_mcp_server.common.error_handling import ToolError

        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_products")

        with pytest.raises(ToolError) as raised:
            await registered_fn(
                action="create",
                product_data="{broken-json",
            )

        assert raised.value.field == "product_data"
        assert raised.value.message.startswith("Invalid JSON for product_data:")

    @pytest.mark.asyncio
    async def test_malformed_resource_data_raises(self):
        """Malformed resource_data JSON string raises a ToolError (product_data=None)."""
        from src.revenium_mcp_server.common.error_handling import ToolError

        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_products")

        with pytest.raises(ToolError) as raised:
            await registered_fn(
                action="create",
                product_data=None,
                resource_data="bad json>>",
            )

        assert raised.value.field == "resource_data"
        assert raised.value.message.startswith("Invalid JSON for resource_data:")

    @pytest.mark.asyncio
    async def test_valid_product_data_json_parsed(self):
        """Valid JSON string product_data is converted to dict."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_products")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(
                action="create",
                product_data='{"name": "Prod1", "version": "1.0.0"}',
            )

        assert isinstance(captured_args.get("product_data"), dict)
        assert captured_args["product_data"]["name"] == "Prod1"


# ---------------------------------------------------------------------------
# manage_products create_simple convenience params (name / description)
# ---------------------------------------------------------------------------

class TestManageProductsCreateSimpleParams:
    """The documented create_simple(name=..., description=...) shape must reach the handler."""

    @pytest.mark.asyncio
    async def test_create_simple_name_and_description_forwarded_through_closure(self):
        """Top-level name/description ride the closure into arguments for create_simple."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_products")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(
                action="create_simple",
                name="My AI Product",
                description="Premium API access",
            )

        assert captured_args["action"] == "create_simple"
        assert captured_args["name"] == "My AI Product"
        assert captured_args["description"] == "Premium API access"

    @pytest.mark.asyncio
    async def test_create_simple_omitted_description_is_dropped_for_handler_default(self):
        """name alone is enough; an omitted description is stripped so the handler default applies."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_products")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(action="create_simple", name="My AI Product")

        assert captured_args["name"] == "My AI Product"
        assert "description" not in captured_args


# ---------------------------------------------------------------------------
# JSON preprocessing — manage_customers (resource_data + resource_id mapping)
# ---------------------------------------------------------------------------

class TestManageCustomersJsonPreprocessing:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("dry_run", [True, "true"])
    async def test_department_removal_arguments_reach_the_tool_with_dry_run_as_bool(
        self, dry_run
    ):
        """person_id and dry_run are bound; a string dry_run arrives as the bool it spells."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_customers")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(action="delete_department_person", person_id=97, dry_run=dry_run)

        assert captured_args["person_id"] == 97
        assert captured_args["dry_run"] is True

    @pytest.mark.asyncio
    async def test_malformed_resource_data_raises(self):
        """Malformed resource_data JSON raises a ToolError."""
        from src.revenium_mcp_server.common.error_handling import ToolError

        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_customers")

        with pytest.raises(ToolError) as raised:
            await registered_fn(
                action="update",
                resource_data="{garbage",
            )

        assert raised.value.field == "resource_data"
        assert raised.value.message.startswith("Invalid JSON for resource_data:")

    @pytest.mark.asyncio
    async def test_resource_id_mapped_to_organization_id_for_organizations(self):
        """When resource_type='organizations', resource_id is mapped to organization_id."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_customers")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(
                action="get",
                resource_type="organizations",
                resource_id="org_abc",
            )

        assert captured_args.get("organization_id") == "org_abc"

    @pytest.mark.asyncio
    async def test_resource_id_mapped_to_user_id_for_users(self):
        """When resource_type='users', resource_id is mapped to user_id."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_customers")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(
                action="get",
                resource_type="users",
                resource_id="user_123",
            )

        assert captured_args.get("user_id") == "user_123"

    @pytest.mark.asyncio
    async def test_resource_id_mapped_to_subscriber_id(self):
        """When resource_type='subscribers', resource_id maps to subscriber_id."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_customers")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(
                action="get",
                resource_type="subscribers",
                resource_id="sub_456",
            )

        assert captured_args.get("subscriber_id") == "sub_456"

    @pytest.mark.asyncio
    async def test_resource_id_mapped_to_team_id(self):
        """When resource_type='teams', resource_id maps to team_id."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_customers")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(
                action="get",
                resource_type="teams",
                resource_id="team_789",
            )

        assert captured_args.get("team_id") == "team_789"

    @pytest.mark.asyncio
    async def test_valid_json_resource_data_remaps_org_data(self):
        """Valid JSON string resource_data with organizations type sets organization_data."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_customers")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(
                action="update",
                resource_type="organizations",
                resource_id="org_abc",
                resource_data='{"name": "NewName"}',
            )

        assert captured_args.get("organization_data") == {"name": "NewName"}

    @pytest.mark.asyncio
    async def test_email_forwarded_for_lookup_user(self):
        """The email scalar is forwarded through to the tool for lookup_user."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_customers")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(
                action="lookup_user",
                email="joao@acme.com",
            )

        assert captured_args.get("email") == "joao@acme.com"

    @pytest.mark.asyncio
    async def test_email_forwarded_for_lookup_subscriber(self):
        """The email scalar is forwarded through to the tool for lookup_subscriber."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_customers")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(
                action="lookup_subscriber",
                email="joao@acme.com",
            )

        assert captured_args.get("email") == "joao@acme.com"


# ---------------------------------------------------------------------------
# JSON preprocessing — manage_subscriptions (subscription_data)
# ---------------------------------------------------------------------------

class TestManageSubscriptionsJsonPreprocessing:
    @pytest.mark.asyncio
    async def test_malformed_subscription_data_raises(self):
        """Malformed subscription_data JSON string raises a ToolError."""
        from src.revenium_mcp_server.common.error_handling import ToolError

        registry = _make_registry()
        registered_fn = await _get_registered_closure(
            registry, "_register_manage_subscriptions"
        )

        with pytest.raises(ToolError) as raised:
            await registered_fn(
                action="create",
                subscription_data="{bad",
            )

        assert raised.value.field == "subscription_data"
        assert raised.value.message.startswith("Invalid JSON for subscription_data:")

    @pytest.mark.asyncio
    async def test_valid_subscription_data_json_parsed(self):
        """Valid JSON string subscription_data is converted to dict."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(
            registry, "_register_manage_subscriptions"
        )

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(
                action="create",
                subscription_data='{"name": "Sub1", "productId": "prod_1"}',
            )

        assert isinstance(captured_args.get("subscription_data"), dict)
        assert captured_args["subscription_data"]["name"] == "Sub1"


# ---------------------------------------------------------------------------
# JSON preprocessing — manage_usage_meters (element_data)
# ---------------------------------------------------------------------------

class TestManageMeteringElementsJsonPreprocessing:
    @pytest.mark.asyncio
    async def test_malformed_element_data_raises(self):
        """Malformed element_data JSON string raises a ToolError."""
        from src.revenium_mcp_server.common.error_handling import ToolError

        registry = _make_registry()
        registered_fn = await _get_registered_closure(
            registry, "_register_manage_metering_elements"
        )

        with pytest.raises(ToolError) as raised:
            await registered_fn(
                action="create",
                element_data="{{not-json",
            )

        assert raised.value.field == "element_data"
        assert raised.value.message.startswith("Invalid JSON for element_data:")

    @pytest.mark.asyncio
    async def test_valid_element_data_json_parsed(self):
        """Valid JSON string element_data is converted to dict."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(
            registry, "_register_manage_metering_elements"
        )

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(
                action="create",
                element_data='{"name": "Elem1", "type": "NUMBER"}',
            )

        assert isinstance(captured_args.get("element_data"), dict)
        assert captured_args["element_data"]["name"] == "Elem1"


# ---------------------------------------------------------------------------
# Numeric / boolean preprocessing (spot-checks via inner closures)
# ---------------------------------------------------------------------------

class TestNumericBooleanPreprocessing:
    @pytest.mark.asyncio
    async def test_string_page_converted_to_int_business_analytics(self):
        """String 'page' parameter is converted to int before forwarding."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(
            registry, "_register_business_analytics_management"
        )

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(action="list", page="3", size="50")

        assert captured_args["page"] == 3
        assert isinstance(captured_args["page"], int)

    @pytest.mark.asyncio
    async def test_string_dry_run_converted_to_bool_slack_management(self):
        """String 'true' dry_run is converted to bool True before forwarding."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(
            registry, "_register_slack_management"
        )

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(action="list", dry_run="true")

        assert captured_args.get("dry_run") is True

    @pytest.mark.asyncio
    async def test_none_values_removed_from_arguments(self):
        """None-valued arguments are stripped before being passed to standardized_tool_execution."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(
            registry, "_register_manage_capabilities"
        )

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(
                action="get_capabilities",
                capability_name=None,
                resource_type=None,
                value=None,
            )

        assert "capability_name" not in captured_args
        assert "resource_type" not in captured_args
        assert "value" not in captured_args


# ---------------------------------------------------------------------------
# manage_system_setup and system_diagnostics closures
# ---------------------------------------------------------------------------

class TestSystemSetupClosure:
    @pytest.mark.asyncio
    async def test_boolean_flags_converted_and_none_stripped(self):
        """manage_system_setup boolean params are converted and None params are stripped."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_system_setup")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(
                action="show_welcome",
                show_environment="true",
                include_recommendations="false",
                email=None,
            )

        assert captured_args.get("show_environment") is True
        assert captured_args.get("include_recommendations") is False
        assert "email" not in captured_args

    @pytest.mark.asyncio
    async def test_forwarded_to_system_setup_tool(self):
        """manage_system_setup closure calls standardized_tool_execution with tool_name='manage_system_setup'."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_system_setup")

        captured: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured["tool_name"] = tool_name
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(action="show_welcome")

        assert captured["tool_name"] == "manage_system_setup"


class TestSystemDiagnosticsClosure:
    @pytest.mark.asyncio
    async def test_boolean_params_converted(self):
        """system_diagnostics boolean params are converted from strings."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(
            registry, "_register_system_diagnostics"
        )

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(
                action="system_health",
                include_recommendations="true",
                include_sensitive="false",
                show_detailed_analysis="true",
            )

        assert captured_args.get("include_recommendations") is True
        assert captured_args.get("include_sensitive") is False
        assert captured_args.get("show_detailed_analysis") is True

    @pytest.mark.asyncio
    async def test_forwarded_to_system_diagnostics_tool(self):
        """system_diagnostics closure calls standardized_tool_execution with correct tool_name."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(
            registry, "_register_system_diagnostics"
        )

        captured: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured["tool_name"] = tool_name
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(action="system_health")

        assert captured["tool_name"] == "system_diagnostics"


class TestSystemDiagnosticsIngestionErrorCode:
    """BACK-3980: the error_code filter reaches get_ingestion_failures through the registered tool."""

    @staticmethod
    async def _registered_server():
        from fastmcp import FastMCP

        mcp = FastMCP("back-3980")
        await _make_registry()._register_system_diagnostics(mcp)
        return mcp

    @pytest.mark.asyncio
    async def test_registered_tool_declares_error_code(self):
        mcp = await self._registered_server()
        tools = {tool.name: tool for tool in await mcp.list_tools(run_middleware=False)}
        assert "error_code" in tools["system_diagnostics"].parameters["properties"]

    @pytest.mark.asyncio
    async def test_error_code_is_forwarded_and_omitted_when_absent(self):
        registered_fn = await _get_registered_closure(
            _make_registry(), "_register_system_diagnostics"
        )
        calls: list = []

        async def fake_execution(tool_name, action, arguments, tool_class):
            calls.append(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(action="get_ingestion_failures", error_code="PRODUCT_NOT_FOUND")
            await registered_fn(action="get_ingestion_failures")

        assert calls[0]["error_code"] == "PRODUCT_NOT_FOUND"
        assert "error_code" not in calls[1]

    @pytest.mark.asyncio
    async def test_invalid_error_code_is_refused_through_the_registered_tool(self):
        from fastmcp import Client
        from fastmcp.exceptions import ToolError as FastMCPToolError

        mcp = await self._registered_server()
        mock = AsyncMock(return_value={"page": {"totalElements": 0}})
        with patch(
            "src.revenium_mcp_server.client.ReveniumClient.get_ingestion_failures",
            new=mock,
        ):
            async with Client(mcp) as client:
                with pytest.raises(FastMCPToolError) as exc_info:
                    await client.call_tool(
                        "system_diagnostics",
                        {"action": "get_ingestion_failures", "error_code": "UNKNOWN_PRODUCT"},
                    )

        message = str(exc_info.value)
        assert "UNKNOWN_PRODUCT" in message
        assert "PRODUCT_NOT_FOUND" in message
        assert "SUBSCRIPTION_RELATIONSHIP_NOT_FOUND" in message
        mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# manage_metering closure
# ---------------------------------------------------------------------------

class TestManageMeteringClosure:
    @pytest.mark.asyncio
    async def test_string_numeric_params_converted(self):
        """manage_metering numeric string params are converted to int before forwarding."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_metering")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(
                action="submit",
                input_tokens="100",
                output_tokens="200",
                duration_ms="1500",
            )

        assert captured_args["input_tokens"] == 100
        assert isinstance(captured_args["input_tokens"], int)
        assert captured_args["output_tokens"] == 200
        assert captured_args["duration_ms"] == 1500

    @pytest.mark.asyncio
    async def test_boolean_dry_run_converted(self):
        """manage_metering string dry_run is converted to bool."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_metering")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(action="submit", dry_run="true")

        assert captured_args.get("dry_run") is True

    @pytest.mark.asyncio
    async def test_transaction_ids_array_preprocessing(self):
        """manage_metering transaction_ids string value goes through array preprocessing."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_metering")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(
                action="verify",
                transaction_ids=["txn_1", "txn_2"],
            )

        # List should be preserved as-is
        assert captured_args.get("transaction_ids") == ["txn_1", "txn_2"]

    @pytest.mark.asyncio
    async def test_forwarded_to_manage_metering_tool(self):
        """manage_metering closure uses tool_name='manage_metering' in execution."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_metering")

        captured: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured["tool_name"] = tool_name
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(action="get_capabilities")

        assert captured["tool_name"] == "manage_metering"


# ---------------------------------------------------------------------------
# Remaining manage_customers data remapping branches
# ---------------------------------------------------------------------------

class TestManageCustomersDataRemapping:
    @pytest.mark.asyncio
    async def test_resource_data_remapped_to_subscriber_data_for_subscribers_type(self):
        """When resource_type='subscribers', dict resource_data is also set as subscriber_data."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_customers")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(
                action="create",
                resource_type="subscribers",
                resource_data={"email": "sub@example.com"},
            )

        assert captured_args.get("subscriber_data") == {"email": "sub@example.com"}

    @pytest.mark.asyncio
    async def test_resource_data_remapped_to_team_data_for_teams_type(self):
        """When resource_type='teams', dict resource_data is also set as team_data."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_customers")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(
                action="create",
                resource_type="teams",
                resource_data={"name": "TeamAlpha"},
            )

        assert captured_args.get("team_data") == {"name": "TeamAlpha"}

    @pytest.mark.asyncio
    async def test_valid_json_resource_data_remaps_subscriber_data(self):
        """Valid JSON string resource_data with subscribers type sets subscriber_data."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_customers")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(
                action="update",
                resource_type="subscribers",
                resource_id="sub_1",
                resource_data='{"email": "new@example.com"}',
            )

        assert captured_args.get("subscriber_data") == {"email": "new@example.com"}

    @pytest.mark.asyncio
    async def test_valid_json_resource_data_remaps_user_data(self):
        """Valid JSON string resource_data with users type sets user_data."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_customers")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(
                action="update",
                resource_type="users",
                resource_id="user_1",
                resource_data='{"name": "Alice"}',
            )

        assert captured_args.get("user_data") == {"name": "Alice"}


# ---------------------------------------------------------------------------
# manage_products valid resource_data JSON parse (line 973)
# ---------------------------------------------------------------------------

class TestManageProductsResourceDataParsing:
    @pytest.mark.asyncio
    async def test_valid_json_resource_data_parsed_to_dict(self):
        """Valid JSON string resource_data in manage_products is converted to dict."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_products")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(
                action="create",
                product_data=None,
                resource_data='{"name": "ResX", "version": "2.0"}',
            )

        assert isinstance(captured_args.get("resource_data"), dict)
        assert captured_args["resource_data"]["name"] == "ResX"


class TestManageToolsFastMCPSignature:
    """FastMCP builds its Pydantic model from the registered function's
    signature, not from get_schema(). Undeclared kwargs raise a raw
    `unexpected_keyword_argument` error, and plain-string params reject
    other JSON scalars with a `string_type` Pydantic leak — these tests
    guard both surfaces.
    """

    @pytest.mark.asyncio
    async def test_signature_accepts_period_and_group(self):
        """period and group must be declared so the analytics contract
        (SEVEN_DAYS etc.) doesn't trip FastMCP validation."""
        import inspect

        registry = _make_registry(profile="business")
        fn = await _get_registered_closure(registry, "_register_manage_tools")
        sig = inspect.signature(fn)
        assert "period" in sig.parameters, (
            "period missing from manage_tools signature — callers passing "
            "period='SEVEN_DAYS' will hit a raw Pydantic framework error"
        )
        assert "group" in sig.parameters, (
            "group missing from manage_tools signature — callers passing "
            "group='TOTAL' will hit a raw Pydantic framework error"
        )

    @pytest.mark.asyncio
    async def test_period_string_reaches_downstream_execution(self):
        """period='SEVEN_DAYS' must be forwarded to standardized_tool_execution
        (the inner closure's single call-out), proving the kwarg survives
        Python dispatch end-to-end."""
        registry = _make_registry(profile="business")
        fn = await _get_registered_closure(registry, "_register_manage_tools")

        captured: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await fn(action="get_cost_breakdown", period="SEVEN_DAYS", group="TOTAL")

        assert captured.get("period") == "SEVEN_DAYS"
        assert captured.get("group") == "TOTAL"

    @pytest.mark.asyncio
    async def test_int_tool_id_raises_structured_tool_error(self):
        """tool_id=<int> must surface a structured ToolError (field='tool_id'),
        not a raw Pydantic string_type leak."""
        from src.revenium_mcp_server.common.error_handling import ToolError

        registry = _make_registry(profile="business")
        fn = await _get_registered_closure(registry, "_register_manage_tools")

        with pytest.raises(ToolError) as exc:
            await fn(action="get", tool_id=12345)

        assert exc.value.field == "tool_id"
        assert "string" in exc.value.message.lower()
        assert "12345" in exc.value.message

    @pytest.mark.asyncio
    async def test_int_tool_name_raises_structured_tool_error(self):
        """Same contract for tool_name — the fix must cover the full set of
        ID/name string fields, not just tool_id."""
        from src.revenium_mcp_server.common.error_handling import ToolError

        registry = _make_registry(profile="business")
        fn = await _get_registered_closure(registry, "_register_manage_tools")

        with pytest.raises(ToolError) as exc:
            await fn(action="search", tool_name=999)

        assert exc.value.field == "tool_name"

    @pytest.mark.asyncio
    async def test_int_action_raises_structured_tool_error(self):
        """action is widened to JSON scalar at the framework boundary;
        non-string values must still surface a structured ToolError rather
        than leaking a Pydantic string_type error."""
        from src.revenium_mcp_server.common.error_handling import ToolError

        registry = _make_registry(profile="business")
        fn = await _get_registered_closure(registry, "_register_manage_tools")

        with pytest.raises(ToolError) as exc:
            await fn(action=123)

        assert exc.value.field == "action"
        assert "string" in exc.value.message.lower()

    @pytest.mark.asyncio
    async def test_string_tool_id_passes_through_unchanged(self):
        """Happy path — a properly-typed tool_id reaches downstream execution."""
        registry = _make_registry(profile="business")
        fn = await _get_registered_closure(registry, "_register_manage_tools")

        captured: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await fn(action="get", tool_id="valid-tool-id")

        assert captured.get("tool_id") == "valid-tool-id"


# ---------------------------------------------------------------------------
# JSON preprocessing — manage_agents (agent_data / filters)
# ---------------------------------------------------------------------------

class TestManageAgentsJsonPreprocessing:
    """Tests for the inner manage_agents closure's dict-param JSON handling."""

    @pytest.mark.asyncio
    async def test_valid_json_string_agent_data_is_parsed(self):
        """agent_data sent as a valid JSON object string is converted to a dict."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_agents")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(
                action="create",
                agent_data='{"telemetryKey": "my-agent"}',
            )

        assert isinstance(captured_args.get("agent_data"), dict)
        assert captured_args["agent_data"]["telemetryKey"] == "my-agent"

    @pytest.mark.asyncio
    async def test_malformed_json_string_agent_data_raises(self):
        from src.revenium_mcp_server.common.error_handling import ToolError

        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_agents")

        with pytest.raises(ToolError) as raised:
            await registered_fn(action="create", agent_data="not json {{{{")

        assert raised.value.field == "agent_data"
        assert raised.value.message.startswith("Invalid JSON for agent_data:")
        assert "agent_data must be a JSON object" in raised.value.message

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scalar", ['"just-a-string"', "1", "[]", "true"])
    async def test_non_object_json_agent_data_raises(self, scalar):
        """JSON that parses to a non-dict is rejected with a structured message
        instead of reaching the manager and failing on .get()."""
        from src.revenium_mcp_server.common.error_handling import ToolError

        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_agents")

        with pytest.raises(ToolError) as raised:
            await registered_fn(action="create", agent_data=scalar)

        assert raised.value.field == "agent_data"
        assert raised.value.message.startswith("Invalid JSON for agent_data:")
        assert "agent_data must be a JSON object" in raised.value.message

    @pytest.mark.asyncio
    async def test_non_object_json_filters_raises(self):
        from src.revenium_mcp_server.common.error_handling import ToolError

        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_agents")

        with pytest.raises(ToolError) as raised:
            await registered_fn(action="list", filters="[]")

        assert raised.value.field == "filters"
        assert raised.value.message.startswith("Invalid JSON for filters:")
        assert "filters must be a JSON object" in raised.value.message

    @pytest.mark.asyncio
    async def test_squad_params_forwarded_through_closure(self):
        """squad_id/squad_name/status/period ride the closure into arguments."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_agents")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(
                action="list_squad_executions",
                squad_id="sq_9",
                squad_name="checkout",
                status="COMPLETED",
                period="SEVEN_DAYS",
            )

        assert captured_args["squad_id"] == "sq_9"
        assert captured_args["squad_name"] == "checkout"
        assert captured_args["status"] == "COMPLETED"
        assert captured_args["period"] == "SEVEN_DAYS"


class TestManageCostControlsJsonPreprocessing:
    """Tests for the inner manage_cost_controls closure's dict-param JSON handling."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("sent, expected", [("true", True), ("false", False), (True, True)])
    async def test_include_advisory_reaches_the_tool_as_a_boolean(self, sent, expected):
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_cost_controls")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(action="get_enforcement_rules", include_advisory=sent)

        assert captured_args["include_advisory"] is expected

    @pytest.mark.asyncio
    async def test_valid_json_string_control_data_is_parsed(self):
        """control_data sent as a valid JSON object string is converted to a dict."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_cost_controls")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(
                action="create",
                control_data='{"name": "Monthly Guardrail", "hardLimit": 1000}',
            )

        assert isinstance(captured_args.get("control_data"), dict)
        assert captured_args["control_data"]["name"] == "Monthly Guardrail"

    @pytest.mark.asyncio
    async def test_malformed_json_string_control_data_raises(self):
        from src.revenium_mcp_server.common.error_handling import ToolError

        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_cost_controls")

        with pytest.raises(ToolError) as raised:
            await registered_fn(action="create", control_data="not json {{{{")

        assert raised.value.field == "control_data"
        assert raised.value.message.startswith("Invalid JSON for control_data:")
        assert "control_data must be a JSON object" in raised.value.message

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scalar", ['"just-a-string"', "1", "[]", "true"])
    async def test_non_object_json_control_data_raises(self, scalar):
        """JSON that parses to a non-dict is rejected with a structured message
        instead of reaching the manager and failing on .get()."""
        from src.revenium_mcp_server.common.error_handling import ToolError

        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_cost_controls")

        with pytest.raises(ToolError) as raised:
            await registered_fn(action="create", control_data=scalar)

        assert raised.value.field == "control_data"
        assert raised.value.message.startswith("Invalid JSON for control_data:")
        assert "control_data must be a JSON object" in raised.value.message

    @pytest.mark.asyncio
    async def test_non_object_json_filters_raises(self):
        from src.revenium_mcp_server.common.error_handling import ToolError

        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_cost_controls")

        with pytest.raises(ToolError) as raised:
            await registered_fn(action="list", filters="[]")

        assert raised.value.field == "filters"
        assert raised.value.message.startswith("Invalid JSON for filters:")
        assert "filters must be a JSON object" in raised.value.message


class TestManageCostControlsNumericPreprocessing:
    """The closure coerces numeric-string page/size before dispatch."""

    @pytest.mark.asyncio
    async def test_string_page_and_size_are_coerced(self):
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_cost_controls")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(action="list", page="2", size="5")

        assert captured_args["page"] == 2
        assert captured_args["size"] == 5


class TestManageCostControlsFilterValuesForwarding:
    """BACK-4887: list_filter_values and its dimension reach the tool through the closure."""

    @pytest.mark.asyncio
    async def test_signature_declares_dimension(self):
        import inspect

        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_cost_controls")

        assert "dimension" in inspect.signature(registered_fn).parameters

    @pytest.mark.asyncio
    async def test_action_and_dimension_are_forwarded(self):
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_cost_controls")

        captured: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured.update(arguments, routed_action=action)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(action="list_filter_values", dimension="PROVIDER")

        assert captured["routed_action"] == "list_filter_values"
        assert captured["dimension"] == "PROVIDER"

    @pytest.mark.asyncio
    async def test_the_closure_tool_class_lists_the_action(self):
        from src.revenium_mcp_server.tools_decomposed.cost_controls_management import (
            CostControlsManagement,
        )

        schema = await CostControlsManagement()._get_input_schema()

        assert "list_filter_values" in schema["properties"]["action"]["enum"]


class TestManageCostControlsDepartmentPreviewForwarding:
    """parent_department_id must be declared on the closure or FastMCP rejects it
    before the tool ever sees it (the signature, not get_schema(), is the model)."""

    @pytest.mark.asyncio
    async def test_signature_declares_parent_department_id(self):
        import inspect

        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_cost_controls")

        assert "parent_department_id" in inspect.signature(registered_fn).parameters

    @pytest.mark.asyncio
    @pytest.mark.parametrize("value", [173, "173"])
    async def test_parent_department_id_forwarded_unchanged(self, value):
        """Both an int and a digit string are legitimate, so the closure must
        forward the value as sent and leave coercion to the tool."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_cost_controls")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(action="preview_department_group", parent_department_id=value)

        assert captured_args["parent_department_id"] == value

    @pytest.mark.asyncio
    async def test_parent_department_id_none_is_stripped(self):
        """An unset optional must not reach the tool as an explicit None."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_cost_controls")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(action="list")

        assert "parent_department_id" not in captured_args


class TestBusinessAnalyticsAggregationForwarding:
    """The new aggregation closure param is forwarded (and None-stripped)."""

    @pytest.mark.asyncio
    async def test_aggregation_forwarded(self):
        registry = _make_registry()
        registered_fn = await _get_registered_closure(
            registry, "_register_business_analytics_management"
        )
        captured: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(action="get_task_costs", aggregation="aggregated")
        assert captured["aggregation"] == "aggregated"

    @pytest.mark.asyncio
    async def test_aggregation_none_stripped(self):
        registry = _make_registry()
        registered_fn = await _get_registered_closure(
            registry, "_register_business_analytics_management"
        )
        captured: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(action="get_task_costs")
        assert "aggregation" not in captured


class TestBusinessAnalyticsBillingReadClosure:
    async def _run(self, **kwargs):
        registry = _make_registry()
        registered_fn = await _get_registered_closure(
            registry, "_register_business_analytics_management"
        )
        captured: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(**kwargs)
        return captured

    @pytest.mark.asyncio
    async def test_scalar_billing_params_forwarded(self):
        captured = await self._run(
            action="list_invoices",
            invoice_number="INV-1",
            starting_amount="10",
            ending_amount="100",
        )
        assert captured["invoice_number"] == "INV-1"
        # numeric strings coerced to float
        assert captured["starting_amount"] == 10.0
        assert captured["ending_amount"] == 100.0

    @pytest.mark.asyncio
    async def test_refund_and_period_charge_params_forwarded(self):
        captured = await self._run(
            action="list_period_charges",
            minimum="5",
            maximum="50",
            cursor="CUR-1",
            invoice_id="inv_9",
        )
        assert captured["minimum"] == 5.0
        assert captured["maximum"] == 50.0
        assert captured["cursor"] == "CUR-1"
        assert captured["invoice_id"] == "inv_9"

    @pytest.mark.asyncio
    async def test_pay_states_and_states_json_string_parsed_to_list(self):
        captured = await self._run(
            action="list_invoices",
            pay_states='["UNPAID", "PARTIALLY_PAID"]',
            states='["FINALIZED"]',
        )
        assert captured["pay_states"] == ["UNPAID", "PARTIALLY_PAID"]
        assert captured["states"] == ["FINALIZED"]

    @pytest.mark.asyncio
    async def test_pay_states_native_list_preserved(self):
        captured = await self._run(
            action="list_invoices",
            pay_states=["UNPAID"],
            states=["FINALIZED", "DRAFT"],
        )
        assert captured["pay_states"] == ["UNPAID"]
        assert captured["states"] == ["FINALIZED", "DRAFT"]

    @pytest.mark.asyncio
    async def test_non_list_states_string_left_for_tool_to_reject(self):
        """A non-JSON-array string is left as-is (the anomaly_ids precedent):
        the array preprocessor keeps it a string so the tool layer rejects it,
        rather than silently wrapping a scalar in a list."""
        captured = await self._run(action="list_invoices", states="FINALIZED")
        assert captured["states"] == "FINALIZED"
        assert not isinstance(captured["states"], list)

    @pytest.mark.asyncio
    async def test_none_billing_params_stripped(self):
        captured = await self._run(action="list_refunds")
        for key in (
            "invoice_number",
            "pay_states",
            "states",
            "starting_amount",
            "ending_amount",
            "minimum",
            "maximum",
            "cursor",
            "invoice_id",
        ):
            assert key not in captured


class TestBusinessAnalyticsSkillReadClosure:
    """The closure signature is the tool's public schema — a handler reading
    arguments["skill_id"] is unreachable unless the parameter is declared."""

    async def _run(self, **kwargs):
        registry = _make_registry()
        registered_fn = await _get_registered_closure(
            registry, "_register_business_analytics_management"
        )
        captured: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(**kwargs)
        return captured

    @pytest.mark.asyncio
    async def test_signature_declares_skill_id_and_sort(self):
        import inspect

        registry = _make_registry()
        fn = await _get_registered_closure(
            registry, "_register_business_analytics_management"
        )
        params = inspect.signature(fn).parameters
        assert "skill_id" in params
        assert "sort" in params

    @pytest.mark.asyncio
    async def test_skill_params_forwarded(self):
        captured = await self._run(
            action="list_skills", period="NINETY_DAYS", sort="totalCost,DESC"
        )
        assert captured["period"] == "NINETY_DAYS"
        assert captured["sort"] == "totalCost,DESC"

    @pytest.mark.asyncio
    async def test_skill_id_forwarded(self):
        captured = await self._run(action="get_skill", skill_id="JMwX9g4")
        assert captured["action"] == "get_skill"
        assert captured["skill_id"] == "JMwX9g4"

    @pytest.mark.asyncio
    async def test_none_skill_params_stripped(self):
        captured = await self._run(action="list_skills")
        assert "skill_id" not in captured
        assert "sort" not in captured


class TestBusinessAnalyticsSeatUtilizationClosure:
    """get_seat_utilization is undrivable unless its parameters are declared on
    the closure — FastMCP builds the tool schema from the signature."""

    async def _run(self, **kwargs):
        registry = _make_registry()
        registered_fn = await _get_registered_closure(
            registry, "_register_business_analytics_management"
        )
        captured: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(**kwargs)
        return captured

    @pytest.mark.asyncio
    async def test_signature_declares_the_seat_params(self):
        import inspect

        registry = _make_registry()
        fn = await _get_registered_closure(
            registry, "_register_business_analytics_management"
        )
        params = inspect.signature(fn).parameters
        assert "from_date" in params
        assert "to_date" in params
        assert "team_id" in params

    @pytest.mark.asyncio
    async def test_seat_params_forwarded(self):
        captured = await self._run(
            action="get_seat_utilization",
            from_date="2026-08-01",
            to_date="2026-08-22",
            team_id="JMwaj9y",
        )
        assert captured["action"] == "get_seat_utilization"
        assert captured["from_date"] == "2026-08-01"
        assert captured["to_date"] == "2026-08-22"
        assert captured["team_id"] == "JMwaj9y"

    @pytest.mark.asyncio
    async def test_omitted_team_id_is_stripped_so_the_client_resolves_it(self):
        captured = await self._run(
            action="get_seat_utilization", from_date="2026-08-01", to_date="2026-08-22"
        )
        assert "team_id" not in captured


class TestManageSubscriptionsBillingReadClosure:
    async def _run(self, **kwargs):
        registry = _make_registry()
        registered_fn = await _get_registered_closure(
            registry, "_register_manage_subscriptions"
        )
        captured: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(**kwargs)
        return captured

    @pytest.mark.asyncio
    async def test_subscription_id_reaches_get_billed_amount(self):
        captured = await self._run(action="get_billed_amount", subscription_id="sub_9")
        assert captured["action"] == "get_billed_amount"
        assert captured["subscription_id"] == "sub_9"

    @pytest.mark.asyncio
    async def test_subscription_id_reaches_get_quota_consumed(self):
        captured = await self._run(action="get_quota_consumed", subscription_id="sub_9")
        assert captured["action"] == "get_quota_consumed"
        assert captured["subscription_id"] == "sub_9"


class TestBillingClosureDateAndQueryParams:
    """Review: documented billing filters must be reachable via the closure."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("param,value", [
        ("start_date", "2026-01-01T00:00:00Z"),
        ("end_date", "2026-02-01T00:00:00Z"),
        ("query", "acme"),
    ])
    async def test_param_forwarded(self, param, value):
        registry = _make_registry()
        registered_fn = await _get_registered_closure(
            registry, "_register_business_analytics_management"
        )
        captured: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(action="list_invoices", **{param: value})
        assert captured[param] == value


class TestManageAiInsightsCursorParameter:
    """The continuation cursor must be reachable through the MCP boundary —
    the closure signature is the tool's public schema, so a handler that reads
    arguments["cursor"] is unreachable without the parameter declared here."""

    @pytest.mark.asyncio
    async def test_cursor_forwarded_through_closure(self):
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_ai_insights")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(action="list_feedback", run_id="r1", cursor="cont-123")

        assert captured_args["cursor"] == "cont-123"


class TestManageProductsQueryParameter:
    """manage_products advertises free-text search; the closure must declare
    `query` so FastMCP binds it and forwards it to the handler. Without the
    parameter the only search surface was the `filters` dict, whose contents
    the upstream products endpoint silently ignored.
    """

    @pytest.mark.asyncio
    async def test_signature_declares_query(self):
        """`query` must be in the registered signature — FastMCP builds its
        Pydantic model from it, so an undeclared kwarg is a hard framework
        error for the caller."""
        import inspect

        registry = _make_registry(profile="business")
        fn = await _get_registered_closure(registry, "_register_manage_products")

        assert "query" in inspect.signature(fn).parameters

    @pytest.mark.asyncio
    async def test_query_forwarded_to_execution(self):
        """query='API' rides through the closure into the handler arguments."""
        registry = _make_registry(profile="business")
        fn = await _get_registered_closure(registry, "_register_manage_products")

        captured: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await fn(action="list", query="API")

        assert captured.get("query") == "API"

    @pytest.mark.asyncio
    async def test_query_omitted_when_not_supplied(self):
        """No query means no key in arguments — the handler must not receive a
        None that would become a `query=None` upstream param."""
        registry = _make_registry(profile="business")
        fn = await _get_registered_closure(registry, "_register_manage_products")

        captured: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await fn(action="list")

        assert "query" not in captured


class TestManageAiInsightsDepartmentParameters:
    """BACK-2757: the department filters must be reachable through the MCP boundary.

    FastMCP derives the tool's accepted arguments from this closure's
    signature, so a handler reading arguments["filter_department_id"] is dead
    code until the parameter is declared here — the caller gets a binding
    error instead of a department-scoped run.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "param", ["filter_department_id", "filter_include_descendants"],
    )
    async def test_signature_declares_param(self, param):
        import inspect

        registry = _make_registry(profile="business")
        fn = await _get_registered_closure(registry, "_register_manage_ai_insights")

        assert param in inspect.signature(fn).parameters

    @pytest.mark.asyncio
    async def test_department_filters_forwarded_through_closure(self):
        registry = _make_registry(profile="business")
        fn = await _get_registered_closure(registry, "_register_manage_ai_insights")

        captured: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await fn(
                action="trigger_run",
                period_start="2026-01-01T00:00:00Z",
                period_end="2026-01-31T23:59:59Z",
                filter_department_id="173",
                filter_include_descendants=False,
            )

        assert captured["filter_department_id"] == "173"
        assert captured["filter_include_descendants"] is False

    @pytest.mark.asyncio
    async def test_include_descendants_false_survives_the_none_filter(self):
        """The closure drops None-valued arguments; False must not be dropped
        with them, or opting out of descendants would silently do nothing."""
        registry = _make_registry(profile="business")
        fn = await _get_registered_closure(registry, "_register_manage_ai_insights")

        captured: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await fn(action="trigger_run", filter_include_descendants=False)

        assert captured["filter_include_descendants"] is False


# ---------------------------------------------------------------------------
# manage_metering closure — completion provenance forwarding
# ---------------------------------------------------------------------------

class TestManageMeteringProvenanceForwarding:
    """BACK-2758: the closure signature IS manage_metering's public schema.

    effort, model_host and subscriber_email_source are read out of the
    arguments dict by the submit path, so leaving them undeclared here does
    not merely hide them — FastMCP never binds them and no MCP client can
    send them at all.
    """

    PROVENANCE = {
        "effort": "high",
        "model_host": "bedrock",
        "subscriber_email_source": "jwt",
    }

    @pytest.mark.asyncio
    async def test_signature_declares_provenance_parameters(self):
        import inspect

        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_metering")
        params = inspect.signature(registered_fn).parameters
        for key in self.PROVENANCE:
            assert key in params, key

    @pytest.mark.asyncio
    async def test_provenance_fields_forwarded_to_execution(self):
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_metering")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(action="submit_ai_transaction", **self.PROVENANCE)

        for key, value in self.PROVENANCE.items():
            assert captured_args.get(key) == value, key

    @pytest.mark.asyncio
    async def test_provenance_fields_omitted_when_absent(self):
        """An unset field is stripped with the other Nones, so it never reaches
        the payload builder as an explicit null."""
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_metering")

        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(action="submit_ai_transaction", effort="high")

        assert captured_args["effort"] == "high"
        assert "model_host" not in captured_args
        assert "subscriber_email_source" not in captured_args


class TestManageMeteringEntrypointForwarding:
    """BACK-4950: entrypoint is unreachable for MCP clients unless the closure declares it."""

    @staticmethod
    async def _forwarded_arguments(**arguments):
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_metering")
        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(action="submit_ai_transaction", **arguments)
        return captured_args

    @pytest.mark.asyncio
    async def test_entrypoint_is_forwarded_to_execution(self):
        assert (await self._forwarded_arguments(entrypoint="sdk-py"))["entrypoint"] == "sdk-py"

    @pytest.mark.asyncio
    async def test_entrypoint_is_omitted_when_absent(self):
        assert "entrypoint" not in await self._forwarded_arguments(effort="high")


class TestSystemDiagnosticsStrictIngestionClosure:
    """BACK-2770: the closure signature is system_diagnostics' public schema.

    set_strict_ingestion_mode reads enabled/dry_run/allow_ticket_jobs out of
    the arguments dict, so an undeclared parameter is not merely undocumented
    — FastMCP never binds it and the action cannot be driven at all.
    """

    @pytest.mark.asyncio
    async def test_signature_declares_strict_ingestion_parameters(self):
        import inspect

        registry = _make_registry()
        fn = await _get_registered_closure(registry, "_register_system_diagnostics")
        params = inspect.signature(fn).parameters
        assert "enabled" in params
        assert "dry_run" in params
        assert "confirm" not in params
        assert "allow_ticket_jobs" in params

    @pytest.mark.asyncio
    async def test_strict_ingestion_parameters_forwarded(self):
        registry = _make_registry()
        fn = await _get_registered_closure(registry, "_register_system_diagnostics")
        captured: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await fn(
                action="set_strict_ingestion_mode",
                enabled=True,
                allow_ticket_jobs=True,
                dry_run=True,
            )
        assert captured["enabled"] is True
        assert captured["allow_ticket_jobs"] is True
        assert captured["dry_run"] is True

    @pytest.mark.asyncio
    async def test_omitted_opt_in_is_dropped_from_arguments(self):
        """None means leave-unchanged; it must not reach the handler as a value."""
        registry = _make_registry()
        fn = await _get_registered_closure(registry, "_register_system_diagnostics")
        captured: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await fn(action="set_strict_ingestion_mode", enabled=False)
        assert "allow_ticket_jobs" not in captured

    @pytest.mark.asyncio
    async def test_string_booleans_are_preprocessed(self):
        """enabled/allow_ticket_jobs accept loose string booleans."""
        registry = _make_registry()
        fn = await _get_registered_closure(registry, "_register_system_diagnostics")
        captured: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await fn(
                action="set_strict_ingestion_mode",
                enabled="true",
                allow_ticket_jobs="true",
            )
        assert captured["enabled"] is True
        assert captured["allow_ticket_jobs"] is True

    @pytest.mark.asyncio
    async def test_attribution_detail_text_reaches_the_handler(self):
        """BACK-3096: the second tenant toggle rides the same `enabled`
        parameter. Its action name is new, so assert the pair arrives - a
        declared parameter is worth nothing if the action cannot carry it."""
        registry = _make_registry()
        fn = await _get_registered_closure(registry, "_register_system_diagnostics")
        captured: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await fn(action="set_attribution_detail_text", enabled=False)
        assert captured["action"] == "set_attribution_detail_text"
        assert captured["enabled"] is False
        # The strict-mode-only arguments must not be invented for this action.
        assert "allow_ticket_jobs" not in captured
        assert "dry_run" not in captured

    @pytest.mark.asyncio
    async def test_attribution_detail_text_accepts_a_string_boolean(self):
        """`enabled` is in the boolean-preprocessing list, so a loosely typed
        MCP client reaches the handler's isinstance check with a real bool
        instead of a validation error."""
        registry = _make_registry()
        fn = await _get_registered_closure(registry, "_register_system_diagnostics")
        captured: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await fn(action="set_attribution_detail_text", enabled="false")
        assert captured["enabled"] is False

    @pytest.mark.asyncio
    async def test_usage_billing_reaches_the_handler_with_its_dry_run(self):
        """BACK-3354: the third tenant toggle rides the same `enabled`, and it
        previews with dry_run, so both must arrive together."""
        registry = _make_registry()
        fn = await _get_registered_closure(registry, "_register_system_diagnostics")
        captured: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await fn(action="set_usage_billing", enabled=False, dry_run=True)
        assert captured["action"] == "set_usage_billing"
        assert captured["enabled"] is False
        assert captured["dry_run"] is True
        # The strict-mode-only argument must not be invented for this action.
        assert "allow_ticket_jobs" not in captured


# ---------------------------------------------------------------------------
# manage_metering closure — completion provenance forwarding
# ---------------------------------------------------------------------------


class TestPrHealthClosureParameters:
    """BACK-2768 review: FastMCP derives each tool's accepted arguments from the
    registered closure's signature, so an action whose parameters the closure
    never declares is unreachable — the framework rejects the call before the
    handler that reads them ever runs."""

    @staticmethod
    async def _run(registry_method: str, **kwargs) -> dict:
        registry = _make_registry(profile="business")
        registered_fn = await _get_registered_closure(registry, registry_method)
        captured: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(**kwargs)
        return captured

    @pytest.mark.asyncio
    async def test_analytics_signature_declares_get_pr_health_params(self):
        """get_pr_health requires source, start_date and end_date — all three must
        be bindable through the get_business_analytics schema."""
        import inspect

        registry = _make_registry(profile="business")
        fn = await _get_registered_closure(
            registry, "_register_business_analytics_management"
        )
        params = inspect.signature(fn).parameters
        assert "source" in params
        assert "start_date" in params
        assert "end_date" in params

    @pytest.mark.asyncio
    async def test_get_pr_health_params_forwarded(self):
        captured = await self._run(
            "_register_business_analytics_management",
            action="get_pr_health",
            source="github",
            start_date="2026-05-17",
            end_date="2026-08-17",
        )
        assert captured["action"] == "get_pr_health"
        assert captured["source"] == "github"
        assert captured["start_date"] == "2026-05-17"
        assert captured["end_date"] == "2026-08-17"

    @pytest.mark.asyncio
    async def test_source_omitted_when_not_supplied(self):
        """An omitted source must not reach the handler as None — the validator
        distinguishes a missing source from a rejected one."""
        captured = await self._run(
            "_register_business_analytics_management", action="get_provider_costs"
        )
        assert "source" not in captured

    @pytest.mark.asyncio
    async def test_customers_signature_declares_threshold_params(self):
        """update_pr_health_settings reads aging_days/rotting_days out of the
        arguments dict, so the manage_customers closure must declare them."""
        import inspect

        registry = _make_registry(profile="business")
        fn = await _get_registered_closure(registry, "_register_manage_customers")
        params = inspect.signature(fn).parameters
        assert "team_id" in params
        assert "aging_days" in params
        assert "rotting_days" in params

    @pytest.mark.asyncio
    async def test_threshold_params_forwarded(self):
        captured = await self._run(
            "_register_manage_customers",
            action="update_pr_health_settings",
            team_id="jR2kmLs",
            aging_days=14,
            rotting_days=30,
        )
        assert captured["action"] == "update_pr_health_settings"
        assert captured["team_id"] == "jR2kmLs"
        assert captured["aging_days"] == 14
        assert captured["rotting_days"] == 30

    @pytest.mark.asyncio
    async def test_string_thresholds_coerced_to_int(self):
        """Agents serialize numbers as strings; the tool's bounds check rejects
        anything that is not a plain int, so the closure coerces first."""
        captured = await self._run(
            "_register_manage_customers",
            action="update_pr_health_settings",
            team_id="jR2kmLs",
            aging_days="7",
            rotting_days="21",
        )
        assert captured["aging_days"] == 7
        assert captured["rotting_days"] == 21

    @pytest.mark.asyncio
    async def test_unparseable_threshold_left_for_the_tool_to_reject(self):
        """A non-numeric string stays a string so the tool answers with its own
        structured error instead of the closure swallowing the value."""
        captured = await self._run(
            "_register_manage_customers",
            action="update_pr_health_settings",
            team_id="jR2kmLs",
            aging_days="soon",
        )
        assert captured["aging_days"] == "soon"

    @pytest.mark.asyncio
    async def test_thresholds_omitted_when_not_supplied(self):
        """A one-field update must leave the other key absent — a None would look
        like a supplied value to the read-merge path."""
        captured = await self._run(
            "_register_manage_customers",
            action="update_pr_health_settings",
            team_id="jR2kmLs",
            aging_days=7,
        )
        assert captured["aging_days"] == 7
        assert "rotting_days" not in captured

    @pytest.mark.asyncio
    async def test_customers_signature_declares_pr_health_field_params(self):
        import inspect

        registry = _make_registry(profile="business")
        fn = await _get_registered_closure(registry, "_register_manage_customers")
        params = inspect.signature(fn).parameters
        for name in ("assisted_only", "automation_patterns", "cutoff_date", "excluded_repos"):
            assert name in params
        for read_only in ("built_in_automation_patterns", "cutoff_date_is_default", "default_cutoff_date"):
            assert read_only not in params

    @pytest.mark.asyncio
    async def test_pr_health_field_params_forwarded(self):
        captured = await self._run(
            "_register_manage_customers",
            action="update_pr_health_settings",
            team_id="jR2kmLs",
            assisted_only=True,
            automation_patterns=["^bot$"],
            cutoff_date="2025-03-01",
            excluded_repos=["acme/app"],
        )
        assert captured["assisted_only"] is True
        assert captured["automation_patterns"] == ["^bot$"]
        assert captured["cutoff_date"] == "2025-03-01"
        assert captured["excluded_repos"] == ["acme/app"]

    @pytest.mark.asyncio
    async def test_serialized_pr_health_fields_are_decoded(self):
        captured = await self._run(
            "_register_manage_customers",
            action="update_pr_health_settings",
            team_id="jR2kmLs",
            assisted_only="false",
            automation_patterns='["^bot$"]',
            excluded_repos='["acme/app"]',
        )
        assert captured["assisted_only"] is False
        assert captured["automation_patterns"] == ["^bot$"]
        assert captured["excluded_repos"] == ["acme/app"]

    @pytest.mark.asyncio
    async def test_unrecognized_boolean_left_for_the_tool_to_reject(self):
        captured = await self._run(
            "_register_manage_customers",
            action="update_pr_health_settings",
            team_id="jR2kmLs",
            assisted_only="sometimes",
        )
        assert captured["assisted_only"] == "sometimes"

    @pytest.mark.asyncio
    async def test_pr_health_fields_omitted_when_not_supplied(self):
        captured = await self._run(
            "_register_manage_customers",
            action="update_pr_health_settings",
            team_id="jR2kmLs",
            aging_days=7,
        )
        for name in ("assisted_only", "automation_patterns", "cutoff_date", "excluded_repos"):
            assert name not in captured

    _DIGEST_PARAMS = (
        "digest_enabled",
        "rotting_alert_enabled",
        "day_of_week",
        "hour_of_day",
        "timezone",
        "slack_configuration_ids",
        "email_addresses",
    )

    @pytest.mark.asyncio
    async def test_customers_signature_declares_digest_params(self):
        """BACK-3951: update_pr_health_digest_settings reads these out of the
        arguments dict; the read-only digest echoes are never parameters."""
        import inspect

        registry = _make_registry(profile="business")
        fn = await _get_registered_closure(registry, "_register_manage_customers")
        params = inspect.signature(fn).parameters
        for name in self._DIGEST_PARAMS:
            assert name in params
        for read_only in ("slack_channels", "next_send_at", "last_outcome", "confirmed_providers"):
            assert read_only not in params

    @pytest.mark.asyncio
    async def test_digest_arguments_match_between_closure_and_input_schema(self):
        """BACK-3951 review: a client building calls from get_tool_metadata must see
        every argument update_pr_health_digest_settings accepts, typed the way the
        closure takes it, and the schema must advertise nothing the closure drops."""
        import inspect
        import typing

        from src.revenium_mcp_server.tools_decomposed.customer_management import (
            CustomerManagement,
        )
        from src.revenium_mcp_server.tools_decomposed.pr_health_digest_fields import (
            PR_HEALTH_DIGEST_FIELDS,
        )

        registry = _make_registry(profile="business")
        fn = await _get_registered_closure(registry, "_register_manage_customers")
        closure_params = inspect.signature(fn).parameters
        properties = (await CustomerManagement(ucm_helper=None)._get_input_schema())["properties"]

        action_args = {field.snake for field in PR_HEALTH_DIGEST_FIELDS}
        advertised_for_action = {
            name for name, prop in properties.items()
            if "update_pr_health_digest_settings" in prop.get("description", "")
        }

        assert action_args | {"team_id"} <= set(closure_params)
        assert action_args | {"team_id"} <= set(properties)
        assert advertised_for_action == action_args

        python_type = {"boolean": bool, "integer": int, "string": str, "array": list}
        for name in action_args:
            accepted = {typing.get_origin(t) or t for t in typing.get_args(closure_params[name].annotation)}
            assert python_type[properties[name]["type"]] in accepted, name

    @pytest.mark.asyncio
    async def test_serialized_digest_fields_are_decoded(self):
        captured = await self._run(
            "_register_manage_customers",
            action="update_pr_health_digest_settings",
            team_id="jR2kmLs",
            digest_enabled="true",
            rotting_alert_enabled="false",
            hour_of_day="0",
            slack_configuration_ids='["Zq8kP2a"]',
            email_addresses="[]",
        )
        assert captured["digest_enabled"] is True
        assert captured["rotting_alert_enabled"] is False
        assert captured["hour_of_day"] == 0
        assert captured["slack_configuration_ids"] == ["Zq8kP2a"]
        assert captured["email_addresses"] == []

    @pytest.mark.asyncio
    async def test_digest_fields_omitted_when_not_supplied(self):
        """A partial update must not grow keys the caller never named."""
        captured = await self._run(
            "_register_manage_customers",
            action="update_pr_health_digest_settings",
            team_id="jR2kmLs",
            day_of_week="FRIDAY",
        )
        assert captured["day_of_week"] == "FRIDAY"
        for name in self._DIGEST_PARAMS:
            if name != "day_of_week":
                assert name not in captured


# ---------------------------------------------------------------------------
# manage_metering closure — completion provenance forwarding
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# manage_tools closure: retired parameters must not be advertised (BACK-2936)
# ---------------------------------------------------------------------------

class TestManageToolsClosureParameters:
    @pytest.mark.asyncio
    async def test_tool_version_is_not_a_registered_parameter(self):
        """FastMCP builds the public schema from this signature, so a retired
        field has to disappear here, not only in the handler."""
        import inspect

        registry = _make_registry(profile="business")
        closure = await _get_registered_closure(registry, "_register_manage_tools")
        params = inspect.signature(closure).parameters
        assert "tool_version" not in params
        assert "version" not in params
        assert "tool_type" in params


# ---------------------------------------------------------------------------
# manage_credentials closure: both spellings the capability text
# advertises for the organization id must be declared (BACK-2958)
# ---------------------------------------------------------------------------

class TestManageJobsClosureParameters:
    @pytest.mark.asyncio
    async def test_session_id_is_registered(self):
        """BACK-2769: FastMCP builds manage_jobs' schema from this signature, so
        list_session_attributions is unreachable unless session_id is declared
        here — the BACK-2934 class of bug."""
        import inspect

        registry = _make_registry(profile="business")
        closure = await _get_registered_closure(registry, "_register_manage_jobs")
        params = inspect.signature(closure).parameters
        assert "session_id" in params
        assert "job_id" in params

    @pytest.mark.asyncio
    async def test_session_id_is_forwarded_to_the_handler(self):
        """The declared parameter must also reach `arguments`, or the handler
        raises its own missing-parameter error on a call that supplied it."""
        registry = _make_registry(profile="business")
        closure = await _get_registered_closure(registry, "_register_manage_jobs")

        captured: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await closure(
                action="list_session_attributions",
                session_id="853a73bf-d9d7-4351-a548-9d6c05648c61",
            )

        assert captured["session_id"] == "853a73bf-d9d7-4351-a548-9d6c05648c61"

    @pytest.mark.asyncio
    async def test_omitted_session_id_is_stripped_not_passed_as_none(self):
        """The trailing None-strip keeps an unset session_id out of `arguments`,
        so the handler's "absent" branch stays reachable."""
        registry = _make_registry(profile="business")
        closure = await _get_registered_closure(registry, "_register_manage_jobs")

        captured: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await closure(action="get_job_types")

        assert "session_id" not in captured


def _argument_names_read_by(node):
    """The literal ``arguments`` keys one AST node reads, if any."""
    import ast

    def is_arguments(expr):
        return isinstance(expr, ast.Name) and expr.id == "arguments"

    def literal(expr):
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            return {expr.value}
        return set()

    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and is_arguments(node.func.value)
        and node.args
    ):
        return literal(node.args[0])
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.ctx, ast.Load)
        and is_arguments(node.value)
    ):
        return literal(node.slice)
    if (
        isinstance(node, ast.Compare)
        and len(node.ops) == 1
        and isinstance(node.ops[0], ast.In)
        and is_arguments(node.comparators[0])
    ):
        return literal(node.left)
    if (
        isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "param_fields"
            for target in node.targets
        )
        and isinstance(node.value, ast.List)
    ):
        return {name for element in node.value.elts for name in literal(element)}
    return set()


def _argument_names_read_in(*module_names):
    """Every literal ``arguments`` key the named tools_decomposed modules read."""
    import ast
    from pathlib import Path

    import src.revenium_mcp_server.tools_decomposed as package

    names = set()
    for module_name in module_names:
        tree = ast.parse((Path(package.__file__).parent / module_name).read_text())
        for node in ast.walk(tree):
            names |= _argument_names_read_by(node)
    return names


class TestSubscriberCredentialsClosureParameters:
    @pytest.mark.asyncio
    async def test_both_organization_id_spellings_are_registered(self):
        """FastMCP builds the schema from this signature; an alias that only the
        handler knows about is rejected before the handler ever runs."""
        import inspect

        registry = _make_registry(profile="business")
        closure = await _get_registered_closure(registry, "_register_manage_subscriber_credentials")
        params = inspect.signature(closure).parameters
        assert "organizationId" in params
        assert "organization_id" in params
        assert "filters" in params

    #: Names a handler reads that the closure leaves undeclared on purpose.
    _DELIBERATELY_UNDECLARED = {
        "description": (
            "collides with a natural credential field and would route create "
            "through natural-language parsing; the handler file is owned by PR 443"
        ),
        "operation_type": "set by handle_action from credential_id",
    }

    _HANDLER_MODULES = (
        "subscriber_credentials_management.py",
        "credential_business_handler.py",
        "credential_documentation_handler.py",
    )

    @classmethod
    def _names_the_handlers_read(cls):
        return _argument_names_read_in(*cls._HANDLER_MODULES)

    @pytest.mark.asyncio
    async def test_every_input_the_handlers_read_is_declared(self):
        """FastMCP refuses an undeclared name, so a handler read beneath one is
        unreachable: the troubleshooting guide asked for an issue description
        and then refused the field."""
        import inspect

        registry = _make_registry(profile="business")
        closure = await _get_registered_closure(registry, "_register_manage_subscriber_credentials")
        declared = set(inspect.signature(closure).parameters)

        undeclared = (
            self._names_the_handlers_read() - declared - set(self._DELIBERATELY_UNDECLARED)
        )

        assert sorted(undeclared) == []

    @pytest.mark.asyncio
    async def test_every_schema_property_is_declared(self):
        import inspect

        from src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management import (
            SubscriberCredentialsManagement,
        )

        registry = _make_registry(profile="business")
        closure = await _get_registered_closure(registry, "_register_manage_subscriber_credentials")
        declared = set(inspect.signature(closure).parameters)
        schema = await SubscriberCredentialsManagement(ucm_helper=None)._get_input_schema()

        assert sorted(set(schema["properties"]) - declared) == []


#: Names subscription_management.py reads that manage_subscriptions leaves
#: undeclared on purpose, each with the reason.
_SUBSCRIPTIONS_DELIBERATELY_UNDECLARED = {
    "name": (
        "create's name-only fallback; the create action always builds "
        "subscription_data first"
    ),
    "clientEmailAddress": (
        "a top-level fallback for create; the documented place is "
        "subscription_data, and auto-generate fills the field before it is read"
    ),
    "text": "create_simple and create_from_text are not routed by handle_action",
    "billing_frequency": (
        "create_simple and create_from_text are not routed by handle_action"
    ),
    "type": "create_simple and create_from_text are not routed by handle_action",
    "credentials_data": "create_with_credentials is retired and no action routes to it",
}

_SUBSCRIPTION_INPUTS_TO_FORWARD = sorted(
    _argument_names_read_in("subscription_management.py")
    - set(_SUBSCRIPTIONS_DELIBERATELY_UNDECLARED)
)

_SUBSCRIPTION_SAMPLE_VALUES = {
    "page": 1,
    "size": 5,
    "filters": {"type": "STANDARD"},
    "auto_generate": False,
    "dry_run": True,
    "subscription_data": {"name": "probe"},
}


class TestManageSubscriptionsClosureParameters:
    @pytest.mark.asyncio
    async def test_every_input_the_handlers_read_is_declared(self):
        """FastMCP refuses an undeclared name, so a handler read beneath one is
        unreachable: subscription_nlp asked for a query and then refused it."""
        import inspect

        registry = _make_registry(profile="business")
        closure = await _get_registered_closure(registry, "_register_manage_subscriptions")
        declared = set(inspect.signature(closure).parameters)

        undeclared = (
            _argument_names_read_in("subscription_management.py")
            - declared
            - set(_SUBSCRIPTIONS_DELIBERATELY_UNDECLARED)
        )

        assert sorted(undeclared) == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name", _SUBSCRIPTION_INPUTS_TO_FORWARD)
    async def test_every_declared_input_reaches_the_handler(self, name):
        value = _SUBSCRIPTION_SAMPLE_VALUES.get(name, "acme")
        is_error, text, captured = await _call_through_the_boundary(
            "_register_manage_subscriptions",
            "manage_subscriptions",
            {"action": "get_capabilities", name: value},
        )

        assert not is_error, text
        assert captured.get(name) == value


class TestManageSubscriptionsTopLevelInputs:
    """Each subscriptions action that reads a top-level input gets it through
    the registered tool instead of a "not a recognized parameter" refusal."""

    @staticmethod
    async def _call(arguments, *, execute=False, client=None):
        """With ``execute`` the real subscriptions handler answers, on ``client``.

        The handler is called directly rather than through the introspection
        registry, which other tests fill with instances this patch cannot reach.
        """
        if not execute:
            return await _call_through_the_boundary(
                "_register_manage_subscriptions", "manage_subscriptions", arguments
            )
        from src.revenium_mcp_server.tools_decomposed.subscription_management import (
            SubscriptionManagement,
        )

        async def real_handler(tool_name, action, arguments, tool_class):
            return await SubscriptionManagement(ucm_helper=None).handle_action(
                action, arguments
            )

        with patch.object(
            SubscriptionManagement, "get_client", AsyncMock(return_value=client)
        ), patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=real_handler,
        ):
            return await _call_through_the_boundary(
                "_register_manage_subscriptions",
                "manage_subscriptions",
                arguments,
                execute=True,
            )

    @staticmethod
    def _client():
        client = MagicMock()
        client.team_id = "team_1"
        for method in (
            "get_organizations",
            "get_products",
            "get_subscribers",
            "get_credentials",
            "get_subscriptions",
        ):
            setattr(client, method, AsyncMock(return_value={}))
        client._extract_embedded_data = MagicMock(return_value=[])
        client._extract_pagination_info = MagicMock(return_value={})
        return client

    @pytest.mark.asyncio
    async def test_search_subscriptions_takes_search_query_at_the_top_level(self):
        is_error, text, captured = await self._call(
            {"action": "search_subscriptions", "search_query": "acme"}
        )

        assert not is_error, text
        assert captured["search_query"] == "acme"

    @pytest.mark.asyncio
    async def test_search_subscriptions_takes_product_name_at_the_top_level(self):
        is_error, text, captured = await self._call(
            {"action": "search_subscriptions", "product_name": "Gold"}
        )

        assert not is_error, text
        assert captured["product_name"] == "Gold"

    @pytest.mark.asyncio
    async def test_discover_products_takes_search_query_at_the_top_level(self):
        is_error, text, captured = await self._call(
            {"action": "discover_products", "search_query": "gold"}
        )

        assert not is_error, text
        assert captured["search_query"] == "gold"

    @pytest.mark.asyncio
    async def test_get_supporting_data_uses_its_data_type(self):
        client = self._client()

        is_error, text, _ = await self._call(
            {"action": "get_supporting_data", "data_type": "products", "size": 2},
            execute=True,
            client=client,
        )

        assert not is_error, text
        client.get_products.assert_awaited_once()
        client.get_organizations.assert_not_awaited()
        client.get_subscribers.assert_not_awaited()
        client.get_credentials.assert_not_awaited()
        assert '"products"' in text
        assert '"organizations"' not in text

    @pytest.mark.asyncio
    async def test_get_supporting_data_refuses_an_unknown_data_type(self):
        client = self._client()

        is_error, text, _ = await self._call(
            {"action": "get_supporting_data", "data_type": "produtcs"},
            execute=True,
            client=client,
        )

        assert is_error, text
        assert "produtcs" in text
        assert "products" in text.replace("produtcs", "")
        client.get_products.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_subscription_nlp_uses_its_query(self):
        client = self._client()

        is_error, text, _ = await self._call(
            {"action": "subscription_nlp", "query": "list all subscriptions"},
            execute=True,
            client=client,
        )

        assert not is_error, text
        client.get_subscriptions.assert_awaited()

    @pytest.mark.asyncio
    async def test_get_examples_uses_its_example_type(self):
        is_error, text, _ = await self._call(
            {"action": "get_examples", "example_type": "trial_period"},
            execute=True,
            client=self._client(),
        )

        assert not is_error, text
        assert "## **Example 1: Trial Subscription**" in text
        assert "## **Example 2" not in text
        assert "Enterprise Trial" in text

    @pytest.mark.asyncio
    async def test_get_examples_refuses_an_unknown_template_and_lists_the_valid_names(
        self,
    ):
        is_error, text, _ = await self._call(
            {"action": "get_examples", "example_type": "nope"},
            execute=True,
            client=self._client(),
        )

        assert is_error, text
        assert "nope" in text
        assert "trial_period" in text
        assert "annual_billing" in text


class TestManageMeteringPromptContextForwarding:
    """BACK-3383: the closure signature is manage_metering's public schema, so
    the prompt-context fields are unreachable until declared there."""

    PROMPT_CONTEXT = {
        "prompt_id": "0f2b8a54-6c31-4d7e-9a10-b5c7d2e84f63",
        "prompt_length": 412,
        "query_source": "repl_main_thread",
        "speed": "fast",
        "subagent_type": "general-purpose",
    }

    @staticmethod
    async def _call(**kwargs):
        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_metering")
        captured_args: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured_args.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(action="submit_ai_transaction", **kwargs)
        return captured_args

    @pytest.mark.asyncio
    async def test_signature_declares_prompt_context_parameters(self):
        import inspect

        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_metering")
        params = inspect.signature(registered_fn).parameters
        for key in self.PROMPT_CONTEXT:
            assert key in params, key

    @pytest.mark.asyncio
    async def test_prompt_context_forwarded_to_execution(self):
        captured_args = await self._call(**self.PROMPT_CONTEXT)
        for key, value in self.PROMPT_CONTEXT.items():
            assert captured_args.get(key) == value, key

    @pytest.mark.asyncio
    async def test_string_prompt_length_is_coerced_to_int(self):
        captured_args = await self._call(prompt_length="412")
        assert captured_args["prompt_length"] == 412

    @pytest.mark.asyncio
    async def test_absent_prompt_context_is_not_forwarded(self):
        captured_args = await self._call(speed="fast")
        assert captured_args["speed"] == "fast"
        for key in ("prompt_id", "prompt_length", "query_source", "subagent_type"):
            assert key not in captured_args


class TestManageAlertsProviderAndGroupLimit:
    """provider (search_provider_api_keys) and group_limit (get_budget_portfolio) reach
    the handler at the top level, as the advertised schema promises, not only inside params."""

    @pytest.mark.asyncio
    async def test_registered_tool_declares_both(self):
        from fastmcp import FastMCP

        mcp = FastMCP("alerts-top-level")
        await _make_registry()._register_manage_alerts(mcp)
        tools = {tool.name: tool for tool in await mcp.list_tools(run_middleware=False)}
        properties = tools["manage_alerts"].parameters["properties"]
        assert "provider" in properties
        assert "group_limit" in properties

    @pytest.mark.asyncio
    async def test_both_are_forwarded_and_omitted_when_absent(self):
        registered_fn = await _get_registered_closure(_make_registry(), "_register_manage_alerts")
        calls: list = []

        async def fake_execution(tool_name, action, arguments, tool_class):
            calls.append(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await registered_fn(action="search_provider_api_keys", provider="anthropic")
            await registered_fn(action="get_budget_portfolio", group_limit=10)
            await registered_fn(action="list")

        assert calls[0]["provider"] == "anthropic"
        assert calls[1]["group_limit"] == 10
        assert "provider" not in calls[2] and "group_limit" not in calls[2]



async def _call_through_the_boundary(
    register_method_name, tool_name, arguments, *, execute=False
):
    """Call a registered tool the way an MCP client does and capture what reaches it.

    The real FastMCP binding and FrameworkLeakGuardMiddleware run, so an
    undeclared name comes back as the customer-facing refusal. With
    ``execute`` the real handler answers instead of the capturing stand-in.
    """
    from fastmcp import Client, FastMCP
    from mcp.types import TextContent

    from src.revenium_mcp_server.middleware.framework_leak_guard import (
        FrameworkLeakGuardMiddleware,
    )

    tool_name = public_tool_for(tool_name, arguments.get("action", "get_capabilities"))
    mcp = FastMCP(f"{tool_name}-boundary")
    mcp.add_middleware(FrameworkLeakGuardMiddleware())
    await getattr(_make_registry(profile="business"), register_method_name)(mcp)
    captured: dict = {}

    async def fake_execution(tool_name, action, arguments, tool_class):
        captured.update(arguments)
        return [TextContent(type="text", text="ok")]

    if execute:
        async with Client(mcp) as client:
            result = await client.call_tool(tool_name, arguments, raise_on_error=False)
    else:
        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    tool_name, arguments, raise_on_error=False
                )
    text = "\n".join(getattr(part, "text", "") for part in result.content)
    return result.is_error, text, captured


class TestManageMeteringTopLevelFilters:
    """get_capabilities lists the completions filters and submission trace
    fields as top-level arguments, so the registered tool must accept them there."""

    @pytest.mark.asyncio
    async def test_recent_transactions_take_dates_at_the_top_level(self):
        sent = {
            "start_date": "2026-10-14T00:00:00Z",
            "end_date": "2026-10-15T00:00:00Z",
            "total_cost_min": 0.5,
            "request_duration_min": 500,
        }
        is_error, text, captured = await _call_through_the_boundary(
            "_register_manage_metering",
            "manage_metering",
            {"action": "lookup_recent_transactions", **sent},
        )

        assert not is_error, text
        for name, value in sent.items():
            assert captured.get(name) == value, name
        assert type(captured["request_duration_min"]) is int
        assert type(captured["total_cost_min"]) is float

    @pytest.mark.asyncio
    async def test_submission_trace_fields_are_forwarded_at_the_top_level(self):
        sent = {
            "environment": "staging",
            "retry_number": 1,
            "usage_metadata": {"trace_type": "support-chat"},
        }
        is_error, text, captured = await _call_through_the_boundary(
            "_register_manage_metering",
            "manage_metering",
            {"action": "submit_ai_transaction", **sent},
        )

        assert not is_error, text
        for name, value in sent.items():
            assert captured.get(name) == value, name


class TestSubscriberCredentialsTopLevelInputs:
    """Each local-text action answers with the input it was given, through the
    registered tool, instead of refusing the field it asked for."""

    @staticmethod
    async def _call(arguments, *, execute=True):
        return await _call_through_the_boundary(
            "_register_manage_subscriber_credentials",
            "manage_credentials",
            arguments,
            execute=execute,
        )

    @pytest.mark.asyncio
    async def test_get_troubleshooting_guide_uses_its_input(self):
        is_error, text, _ = await self._call(
            {"action": "get_troubleshooting_guide", "issue_description": "billing missing"}
        )
        assert not is_error, text
        assert '"issue": "billing missing"' in text

    @pytest.mark.asyncio
    async def test_parse_natural_language_uses_its_input(self):
        sentence = "Create API key for john@company.com at Acme Corp"
        is_error, text, _ = await self._call(
            {"action": "parse_natural_language", "text": sentence}
        )
        assert not is_error, text
        assert '"action": "parse_natural_language"' in text
        assert sentence in text

    @pytest.mark.asyncio
    async def test_get_business_guidance_uses_its_input(self):
        is_error, text, _ = await self._call(
            {"action": "get_business_guidance", "scenario": "credential_audit"}
        )
        assert not is_error, text
        assert '"scenario": "credential_audit"' in text

    @pytest.mark.asyncio
    async def test_get_onboarding_checklist_uses_its_input(self):
        is_error, text, _ = await self._call(
            {
                "action": "get_onboarding_checklist",
                "customer_info": {"name": "Acme Corp", "email": "ops@acme.example"},
            }
        )
        assert not is_error, text
        assert "Acme Corp" in text

    @pytest.mark.asyncio
    async def test_get_onboarding_checklist_takes_customer_info_as_a_json_string(self):
        is_error, text, _ = await self._call(
            {
                "action": "get_onboarding_checklist",
                "customer_info": '{"name": "Acme Corp", "email": "ops@acme.example"}',
            }
        )
        assert not is_error, text
        assert "Acme Corp" in text

    @pytest.mark.asyncio
    async def test_analyze_billing_impact_uses_its_input(self):
        is_error, text, _ = await self._call(
            {"action": "analyze_billing_impact", "operation": "delete"}
        )
        assert not is_error, text
        assert '"operation": "delete"' in text

    @pytest.mark.asyncio
    async def test_get_examples_uses_its_input(self):
        is_error, text, _ = await self._call(
            {"action": "get_examples", "example_type": "validation"}
        )
        assert not is_error, text
        assert "Validation Examples" in text

    @pytest.mark.asyncio
    async def test_individual_create_fields_are_forwarded(self):
        secret = "s" * 12
        is_error, text, captured = await self._call(
            {
                "action": "create",
                "label": "Ops key",
                "subscriberId": "sub_1",
                "organizationId": "org_1",
                "externalId": "ext_1",
                "externalSecret": secret,
                "tags": '["a", "b"]',
                "subscriptionIds": ["subs_1"],
            },
            execute=False,
        )

        assert not is_error, text
        assert captured["label"] == "Ops key"
        assert captured["externalId"] == "ext_1"
        assert captured["externalSecret"] == secret
        assert captured["tags"] == ["a", "b"]
        assert captured["subscriptionIds"] == ["subs_1"]


class TestManageMeteringUsageMetadataJsonString:
    """BACK-4674: a JSON-string usage_metadata must reach the handler as a dict."""

    @pytest.mark.asyncio
    async def test_a_json_string_usage_metadata_is_decoded(self):
        is_error, text, captured = await _call_through_the_boundary(
            "_register_manage_metering",
            "manage_metering",
            {
                "action": "submit_ai_transaction",
                "usage_metadata": '{"trace_type": "support-chat"}',
            },
        )

        assert not is_error, text
        assert captured["usage_metadata"] == {"trace_type": "support-chat"}

    @pytest.mark.asyncio
    async def test_a_json_string_usage_metadata_in_params_is_decoded(self):
        is_error, text, captured = await _call_through_the_boundary(
            "_register_manage_metering",
            "manage_metering",
            {
                "action": "submit_ai_transaction",
                "params": {"usage_metadata": '{"trace_type": "support-chat"}'},
            },
        )

        assert not is_error, text
        assert captured["usage_metadata"] == {"trace_type": "support-chat"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("raw", ["not-json", '["trace_type"]'])
    async def test_an_invalid_usage_metadata_is_an_error(self, raw):
        is_error, text, captured = await _call_through_the_boundary(
            "_register_manage_metering",
            "manage_metering",
            {"action": "submit_ai_transaction", "usage_metadata": raw},
        )

        assert is_error, text
        assert "usage_metadata must be a JSON object" in text
        assert captured == {}


class TestSubscriberCredentialsInvalidCustomerInfo:
    """BACK-4674: an unreadable customer_info is an error, not a successful call."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("raw", ["not-json", '"Acme Corp"'])
    async def test_an_invalid_customer_info_is_an_error(self, raw):
        is_error, text, _ = await _call_through_the_boundary(
            "_register_manage_subscriber_credentials",
            "manage_credentials",
            {"action": "get_onboarding_checklist", "customer_info": raw},
        )

        assert is_error, text
        assert "customer_info must be a JSON object" in text


class TestSubscriberCredentialsFieldFolding:
    """BACK-4674: a top-level credential field must not be dropped when the
    handler reads only credential_data."""

    @staticmethod
    async def _call(arguments):
        return await _call_through_the_boundary(
            "_register_manage_subscriber_credentials",
            "manage_credentials",
            arguments,
        )

    @pytest.mark.asyncio
    async def test_update_folds_top_level_fields_into_credential_data(self):
        is_error, text, captured = await self._call(
            {
                "action": "update",
                "credential_id": "cred_1",
                "externalSecret": "s" * 12,
                "tags": '["a"]',
            }
        )

        assert not is_error, text
        assert captured["credential_data"] == {
            "externalSecret": "s" * 12,
            "tags": ["a"],
        }

    @pytest.mark.asyncio
    async def test_update_merges_top_level_fields_with_credential_data(self):
        is_error, text, captured = await self._call(
            {
                "action": "update",
                "credential_id": "cred_1",
                "credential_data": '{"label": "Renamed"}',
                "externalId": "ext_2",
            }
        )

        assert not is_error, text
        assert captured["credential_data"] == {
            "label": "Renamed",
            "externalId": "ext_2",
        }

    @pytest.mark.asyncio
    async def test_create_with_credential_data_folds_top_level_fields(self):
        is_error, text, captured = await self._call(
            {
                "action": "create",
                "credential_data": {"label": "Ops key", "subscriberId": "sub_1"},
                "externalSecret": "s" * 12,
                "subscriptionIds": ["subs_1"],
            }
        )

        assert not is_error, text
        assert captured["credential_data"] == {
            "label": "Ops key",
            "subscriberId": "sub_1",
            "externalSecret": "s" * 12,
            "subscriptionIds": ["subs_1"],
        }

    @pytest.mark.asyncio
    async def test_update_folds_top_level_name_and_owner_ids(self):
        is_error, text, captured = await self._call(
            {
                "action": "update",
                "credential_id": "cred_1",
                "name": "Renamed",
                "subscriberId": "sub_2",
                "organizationId": "org_2",
            }
        )

        assert not is_error, text
        assert captured["credential_data"] == {
            "name": "Renamed",
            "subscriberId": "sub_2",
            "organizationId": "org_2",
        }

    @pytest.mark.asyncio
    async def test_create_with_credential_data_folds_top_level_owner_ids(self):
        is_error, text, captured = await self._call(
            {
                "action": "create",
                "credential_data": {"label": "Ops key"},
                "subscriberId": "sub_1",
                "organizationId": "org_1",
            }
        )

        assert not is_error, text
        assert captured["credential_data"] == {
            "label": "Ops key",
            "subscriberId": "sub_1",
            "organizationId": "org_1",
        }

    @pytest.mark.asyncio
    async def test_create_without_credential_data_is_left_to_the_handler(self):
        is_error, text, captured = await self._call(
            {"action": "create", "label": "Ops key", "externalId": "ext_1"}
        )

        assert not is_error, text
        assert "credential_data" not in captured

    @pytest.mark.asyncio
    async def test_create_with_an_empty_credential_data_is_left_to_the_handler(self):
        is_error, text, captured = await self._call(
            {
                "action": "create",
                "credential_data": "{}",
                "label": "Ops key",
                "subscriberId": "sub_1",
                "externalId": "ext_1",
            }
        )

        assert not is_error, text
        assert not captured.get("credential_data")

    @pytest.mark.asyncio
    async def test_the_same_value_both_ways_is_accepted(self):
        is_error, text, captured = await self._call(
            {
                "action": "update",
                "credential_id": "cred_1",
                "credential_data": {"label": "Same"},
                "label": "Same",
            }
        )

        assert not is_error, text
        assert captured["credential_data"] == {"label": "Same"}

    @pytest.mark.asyncio
    async def test_a_conflicting_value_is_an_error(self):
        is_error, text, captured = await self._call(
            {
                "action": "update",
                "credential_id": "cred_1",
                "credential_data": {"label": "Inside"},
                "label": "Top level",
            }
        )

        assert is_error, text
        assert "Conflicting values for label" in text
        assert captured == {}


def _stub_products_client():
    client = MagicMock()
    client.team_id = "team_test"
    client.get_sources = AsyncMock(return_value={})
    client.get_metering_element_definitions = AsyncMock(return_value={})
    client.get_organizations = AsyncMock(return_value={})
    client.create_product = AsyncMock(return_value={"id": "p_new", "name": "x"})
    client.update_product = AsyncMock(return_value={"id": "p1", "name": "x"})
    client.create_subscription = AsyncMock(return_value={"id": "sub_new"})
    client._extract_embedded_data = MagicMock(return_value=[{"id": "src_1"}])
    return client


class TestManageProductsClosureParameters:
    """Every input a products handler reads must be declared on the registered
    tool, or FastMCP refuses it before the handler runs."""

    @staticmethod
    def _names_the_handler_reads():
        import ast
        from pathlib import Path

        import src.revenium_mcp_server.tools_decomposed as package

        tree = ast.parse((Path(package.__file__).parent / "product_management.py").read_text())
        names = set()
        for node in ast.walk(tree):
            names |= _argument_names_read_by(node)
        return names

    @staticmethod
    async def _closure():
        return await _get_registered_closure(
            _make_registry(profile="business"), "_register_manage_products"
        )

    @pytest.mark.asyncio
    async def test_every_input_the_handlers_read_is_declared(self):
        import inspect

        declared = set(inspect.signature(await self._closure()).parameters)

        assert sorted(self._names_the_handler_reads() - declared) == []

    @pytest.mark.asyncio
    async def test_every_declared_input_reaches_the_handler(self):
        import inspect

        closure = await self._closure()
        sentinels = {name: object() for name in inspect.signature(closure).parameters}
        captured: dict = {}

        async def fake_execution(tool_name, action, arguments, tool_class):
            captured.update(arguments)
            return [MagicMock()]

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=fake_execution,
        ):
            await closure(**sentinels)

        for name, sentinel in sentinels.items():
            assert captured.get(name) is sentinel, name

    @pytest.mark.asyncio
    async def test_quick_create_pricing_options_reach_the_handler(self):
        sent = {
            "pricing_model": "subscription",
            "monthly_price": 29,
            "setup_fee": 50,
            "setup_fee_type": "per_customer",
        }
        is_error, text, captured = await _call_through_the_boundary(
            "_register_manage_products",
            "manage_products",
            {"action": "create_simple", "name": "x", **sent},
        )

        assert not is_error, text
        assert captured["monthly_price"] == 29.0
        for name, value in sent.items():
            assert captured.get(name) == value, name

    @pytest.mark.asyncio
    async def test_per_unit_price_reaches_the_handler(self):
        is_error, text, captured = await _call_through_the_boundary(
            "_register_manage_products",
            "manage_products",
            {"action": "create_simple", "name": "x", "per_unit_price": "0.01"},
        )

        assert not is_error, text
        assert captured["per_unit_price"] == 0.01

    @pytest.mark.parametrize(
        "subscription_data",
        [
            {"name": "Sub", "clientEmailAddress": "a@example.com", "organizationId": "org_1"},
            '{"name": "Sub", "clientEmailAddress": "a@example.com", "organizationId": "org_1"}',
        ],
        ids=["dict", "json_string"],
    )
    @pytest.mark.asyncio
    async def test_create_with_subscription_takes_subscription_data(self, subscription_data):
        is_error, text, captured = await _call_through_the_boundary(
            "_register_manage_products",
            "manage_products",
            {
                "action": "create_with_subscription",
                "product_data": {"name": "P"},
                "subscription_data": subscription_data,
            },
        )

        assert not is_error, text
        assert captured["subscription_data"] == {
            "name": "Sub",
            "clientEmailAddress": "a@example.com",
            "organizationId": "org_1",
        }

    @pytest.mark.asyncio
    async def test_malformed_subscription_data_is_an_error(self):
        is_error, text, captured = await _call_through_the_boundary(
            "_register_manage_products",
            "manage_products",
            {
                "action": "create_with_subscription",
                "product_data": {"name": "P"},
                "subscription_data": "{broken",
            },
        )

        assert is_error, text
        assert "not a recognized parameter" not in text
        assert "subscription_data" in text
        assert captured == {}

    @pytest.mark.asyncio
    async def test_clarify_pricing_and_suggest_template_take_their_inputs(self):
        is_error, text, captured = await _call_through_the_boundary(
            "_register_manage_products",
            "manage_products",
            {"action": "clarify_pricing", "text": "$29 per month"},
        )
        assert not is_error, text
        assert captured["text"] == "$29 per month"

        is_error, text, captured = await _call_through_the_boundary(
            "_register_manage_products",
            "manage_products",
            {"action": "suggest_template", "requirements": "api service"},
        )
        assert not is_error, text
        assert captured["requirements"] == "api service"

    @pytest.mark.asyncio
    async def test_clarify_pricing_answers_from_its_text(self):
        from src.revenium_mcp_server.tools_decomposed.product_management import (
            ProductManagement,
        )

        with patch.object(
            ProductManagement, "get_client", AsyncMock(return_value=_stub_products_client())
        ):
            is_error, text, _ = await _call_through_the_boundary(
                "_register_manage_products",
                "manage_products",
                {"action": "clarify_pricing", "text": "$29 per month"},
                execute=True,
            )

        assert not is_error, text
        assert "29" in text, text
        assert "Please provide pricing information" not in text

    @pytest.mark.asyncio
    async def test_suggest_template_answers_from_its_requirements(self):
        from src.revenium_mcp_server.tools_decomposed.product_management import (
            ProductManagement,
        )

        with patch.object(
            ProductManagement, "get_client", AsyncMock(return_value=_stub_products_client())
        ):
            is_error, text, _ = await _call_through_the_boundary(
                "_register_manage_products",
                "manage_products",
                {"action": "suggest_template", "requirements": "api service"},
                execute=True,
            )

        assert not is_error, text
        assert "simple_api_service" in text, text

    @pytest.mark.asyncio
    async def test_create_refuses_quick_create_prices_instead_of_ignoring_them(self):
        from src.revenium_mcp_server.tools_decomposed.product_management import (
            ProductManagement,
        )

        client = _stub_products_client()
        with patch.object(ProductManagement, "get_client", AsyncMock(return_value=client)):
            is_error, text, _ = await _call_through_the_boundary(
                "_register_manage_products",
                "manage_products",
                {"action": "create", "name": "x", "monthly_price": 29},
                execute=True,
            )

        assert is_error, text
        assert "monthly_price" in text and "create_simple" in text, text
        client.create_product.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_refuses_a_setup_fee_instead_of_ignoring_it(self):
        from src.revenium_mcp_server.tools_decomposed.product_management import (
            ProductManagement,
        )

        client = _stub_products_client()
        with patch.object(ProductManagement, "get_client", AsyncMock(return_value=client)):
            is_error, text, _ = await _call_through_the_boundary(
                "_register_manage_products",
                "manage_products",
                {
                    "action": "update",
                    "product_id": "p1",
                    "product_data": {"name": "y"},
                    "setup_fee": 0,
                },
                execute=True,
            )

        assert is_error, text
        assert "setup_fee" in text and "create_simple" in text, text
        client.update_product.assert_not_awaited()


class TestManageProductsCreatePreview:
    """A preview that would be refused is an error, not a result."""

    @pytest.mark.asyncio
    async def test_a_failed_preview_sets_the_error_flag(self):
        from src.revenium_mcp_server.tools_decomposed.product_management import (
            ProductManagement,
        )

        client = _stub_products_client()
        with patch.object(ProductManagement, "get_client", AsyncMock(return_value=client)):
            is_error, text, _ = await _call_through_the_boundary(
                "_register_manage_products",
                "manage_products",
                {"action": "create", "dry_run": True},
                execute=True,
            )

        assert is_error, text
        client.create_product.assert_not_awaited()


def _client_that_refuses_aggregations_without_an_element():
    """A products client that refuses a create body the way the dev platform does."""
    from src.revenium_mcp_server.api_field_mapper import APIFieldMapper
    from src.revenium_mcp_server.client import ReveniumAPIError

    client = _stub_products_client()

    async def create_product(product_data):
        body = APIFieldMapper.map_product_fields(product_data)
        for index, aggregation in enumerate(body.get("plan", {}).get("ratingAggregations", [])):
            if not aggregation.get("elementDefinitionId"):
                raise ReveniumAPIError(
                    "Invalid JSON format - "
                    f"plan.ratingAggregations[{index}].elementDefinitionId",
                    status_code=400,
                )
        return {"id": "p_new", "name": body.get("name")}

    client.create_product = AsyncMock(side_effect=create_product)
    return client


class TestDescriptionThatImpliesUsageBilling:
    """A description such as "billed per call" names no metering element, so the
    preview and the real create give the same verdict and the same note."""

    _DESCRIPTION = "An API product billed per call"

    async def _create(self, arguments):
        from src.revenium_mcp_server.tools_decomposed.product_management import (
            ProductManagement,
        )

        client = _client_that_refuses_aggregations_without_an_element()
        with patch.object(ProductManagement, "get_client", AsyncMock(return_value=client)):
            is_error, text, _ = await _call_through_the_boundary(
                "_register_manage_products",
                "manage_products",
                {"action": "create", **arguments},
                execute=True,
            )
        return is_error, text, client

    @pytest.mark.parametrize(
        "extra",
        [{}, {"product_data": {"name": "Custom"}}],
        ids=["description_only", "hybrid"],
    )
    @pytest.mark.asyncio
    async def test_preview_and_real_create_agree_and_both_say_usage_billing_was_left_out(
        self, extra
    ):
        arguments = {"description": self._DESCRIPTION, **extra}

        preview_error, preview_text, preview_client = await self._create(
            {**arguments, "dry_run": True}
        )
        real_error, real_text, real_client = await self._create(arguments)

        preview_client.create_product.assert_not_awaited()
        assert preview_error == real_error, (preview_text, real_text)
        assert not real_error, real_text
        sent = real_client.create_product.await_args[0][0]
        assert not sent["plan"].get("rating_aggregations"), sent
        assert not sent["plan"].get("ratingAggregations"), sent
        for text in (preview_text, real_text):
            assert "Usage billing was not set up" in text, text
            assert "Call" in text and "elementDefinitionId" in text, text
