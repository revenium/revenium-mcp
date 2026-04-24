"""Unit tests for tool_configuration/registry.py (M4 coverage batch).

Targets: ToolConfigurationRegistry initialization, register_tools_conditionally,
_register_single_tool dispatch, per-tool registration functions (inner closures),
JSON preprocessing branches, get_registered_tools, is_tool_registered,
_register_tool_metadata, and _register_tool_introspection.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.tool_configuration.registry import (
    ToolConfigurationRegistry,
    TOOL_REGISTRATION_PRIORITY_ORDER,
)
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
    """Call a _register_* method and return the inner async function it decorated."""
    mcp = _make_mock_mcp()
    register_method = getattr(registry, method_name)
    await register_method(mcp)
    return mcp.tool.return_value.call_args[0][0]


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
# TOOL_REGISTRATION_PRIORITY_ORDER constant
# ---------------------------------------------------------------------------

class TestPriorityOrderConstant:
    def test_contains_all_starter_tools(self):
        """Every starter-profile tool name appears in the priority order list."""
        starter_tools = {
            "system_setup", "slack_management", "tool_introspection",
            "manage_alerts", "business_analytics_management",
            "manage_metering", "system_diagnostics",
        }
        for tool in starter_tools:
            assert tool in TOOL_REGISTRATION_PRIORITY_ORDER

    def test_contains_all_business_tools(self):
        """All business-only tool names appear in the priority order list."""
        business_tools = {
            "manage_sources", "manage_workflows", "manage_subscriber_credentials",
            "manage_products", "manage_customers", "manage_subscriptions",
            "manage_metering_elements", "manage_capabilities",
        }
        for tool in business_tools:
            assert tool in TOOL_REGISTRATION_PRIORITY_ORDER

    def test_no_duplicates_in_priority_order(self):
        """Priority order list contains no duplicate entries."""
        assert len(TOOL_REGISTRATION_PRIORITY_ORDER) == len(set(TOOL_REGISTRATION_PRIORITY_ORDER))


# ---------------------------------------------------------------------------
# register_tools_conditionally
# ---------------------------------------------------------------------------

class TestRegisterToolsConditionally:
    @pytest.mark.asyncio
    async def test_starter_registers_exactly_starter_tools(self):
        """Starter profile registers exactly the 7 starter tools."""
        registry = _make_registry(profile="starter")
        mcp = _make_mock_mcp()

        with patch.object(registry, "_register_single_tool", new_callable=AsyncMock) as mock_reg, \
             patch.object(registry, "_register_tool_metadata", new_callable=AsyncMock):
            await registry.register_tools_conditionally(mcp)

        registered_names = {c.args[1] for c in mock_reg.call_args_list}
        from src.revenium_mcp_server.tool_configuration.profiles import PROFILE_DEFINITIONS
        assert registered_names == PROFILE_DEFINITIONS["starter"]

    @pytest.mark.asyncio
    async def test_business_registers_exactly_business_tools(self):
        """Business profile registers exactly the 15 business tools — no more, no less."""
        registry = _make_registry(profile="business")
        mcp = _make_mock_mcp()

        with patch.object(registry, "_register_single_tool", new_callable=AsyncMock) as mock_reg, \
             patch.object(registry, "_register_tool_metadata", new_callable=AsyncMock):
            await registry.register_tools_conditionally(mcp)

        registered_names = {c.args[1] for c in mock_reg.call_args_list}
        from src.revenium_mcp_server.tool_configuration.profiles import PROFILE_DEFINITIONS
        assert registered_names == PROFILE_DEFINITIONS["business"]

    @pytest.mark.asyncio
    async def test_disabled_tool_is_skipped(self):
        """A tool disabled via tool_enabled override is never passed to _register_single_tool."""
        registry = _make_registry(
            profile="starter",
            tool_enabled={"manage_alerts": False},
        )
        mcp = _make_mock_mcp()

        with patch.object(registry, "_register_single_tool", new_callable=AsyncMock) as mock_reg, \
             patch.object(registry, "_register_tool_metadata", new_callable=AsyncMock):
            await registry.register_tools_conditionally(mcp)

        called_names = [c.args[1] for c in mock_reg.call_args_list]
        assert "manage_alerts" not in called_names

    @pytest.mark.asyncio
    async def test_tools_registered_in_priority_order(self):
        """Tools are registered in the sequence defined by TOOL_REGISTRATION_PRIORITY_ORDER."""
        registry = _make_registry(profile="starter")
        mcp = _make_mock_mcp()

        with patch.object(registry, "_register_single_tool", new_callable=AsyncMock) as mock_reg, \
             patch.object(registry, "_register_tool_metadata", new_callable=AsyncMock):
            await registry.register_tools_conditionally(mcp)

        call_order = [c.args[1] for c in mock_reg.call_args_list]
        for i in range(len(call_order) - 1):
            idx_a = TOOL_REGISTRATION_PRIORITY_ORDER.index(call_order[i])
            idx_b = TOOL_REGISTRATION_PRIORITY_ORDER.index(call_order[i + 1])
            assert idx_a < idx_b

    @pytest.mark.asyncio
    async def test_extra_enabled_tool_not_in_priority_order_still_registered(self):
        """A tool enabled via override but absent from the priority list is registered at the end."""
        registry = _make_registry(
            profile="starter",
            tool_enabled={"ghost_tool_xyz": True},
        )
        mcp = _make_mock_mcp()

        with patch.object(registry, "_register_single_tool", new_callable=AsyncMock) as mock_reg, \
             patch.object(registry, "_register_tool_metadata", new_callable=AsyncMock):
            await registry.register_tools_conditionally(mcp)

        called_names = [c.args[1] for c in mock_reg.call_args_list]
        assert "ghost_tool_xyz" in called_names
        # It must appear AFTER all priority-ordered tools
        priority_positions = [
            called_names.index(n)
            for n in called_names
            if n in TOOL_REGISTRATION_PRIORITY_ORDER
        ]
        ghost_position = called_names.index("ghost_tool_xyz")
        if priority_positions:
            assert ghost_position > max(priority_positions)


# ---------------------------------------------------------------------------
# _register_single_tool dispatch
# ---------------------------------------------------------------------------

class TestRegisterSingleToolDispatch:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_name,method_name", [
        ("business_analytics_management", "_register_business_analytics_management"),
        ("manage_alerts",                 "_register_manage_alerts"),
        ("slack_management",              "_register_slack_management"),
        ("manage_metering",               "_register_manage_metering"),
        ("system_setup",                  "_register_system_setup"),
        ("system_diagnostics",            "_register_system_diagnostics"),
        ("manage_sources",                "_register_manage_sources"),
        ("manage_workflows",              "_register_manage_workflows"),
        ("manage_subscriber_credentials", "_register_manage_subscriber_credentials"),
        ("manage_products",               "_register_manage_products"),
        ("manage_customers",              "_register_manage_customers"),
        ("manage_subscriptions",          "_register_manage_subscriptions"),
        ("manage_metering_elements",      "_register_manage_metering_elements"),
        ("manage_capabilities",           "_register_manage_capabilities"),
        ("tool_introspection",            "_register_tool_introspection"),
    ])
    async def test_dispatches_to_correct_method(self, tool_name, method_name):
        """_register_single_tool calls the dedicated registration method for each known tool."""
        registry = _make_registry()
        mcp = _make_mock_mcp()

        with patch.object(registry, method_name, new_callable=AsyncMock) as mock_method, \
             patch.object(registry, "_register_tool_metadata", new_callable=AsyncMock):
            await registry._register_single_tool(mcp, tool_name)
            mock_method.assert_called_once_with(mcp)

    @pytest.mark.asyncio
    async def test_unknown_tool_not_added_to_registered_set(self):
        """An unknown tool name results in no entry added to _registered_tools."""
        registry = _make_registry()
        mcp = _make_mock_mcp()

        await registry._register_single_tool(mcp, "totally_unknown_tool")

        assert not registry.is_tool_registered("totally_unknown_tool")

    @pytest.mark.asyncio
    async def test_known_tool_added_to_registered_set_after_success(self):
        """After successful dispatch, the tool name is added to _registered_tools."""
        registry = _make_registry()
        mcp = _make_mock_mcp()

        with patch.object(registry, "_register_system_setup", new_callable=AsyncMock), \
             patch.object(registry, "_register_tool_metadata", new_callable=AsyncMock):
            await registry._register_single_tool(mcp, "system_setup")

        assert registry.is_tool_registered("system_setup")

    @pytest.mark.asyncio
    async def test_exception_in_method_does_not_propagate(self):
        """If a registration method raises, _register_single_tool swallows the exception."""
        registry = _make_registry()
        mcp = _make_mock_mcp()

        with patch.object(
            registry, "_register_system_setup",
            new_callable=AsyncMock, side_effect=RuntimeError("boom")
        ):
            # Must not raise
            await registry._register_single_tool(mcp, "system_setup")

    @pytest.mark.asyncio
    async def test_exception_prevents_tool_added_to_registered_set(self):
        """If registration raises, the tool is NOT added to _registered_tools."""
        registry = _make_registry()
        mcp = _make_mock_mcp()

        with patch.object(
            registry, "_register_system_setup",
            new_callable=AsyncMock, side_effect=RuntimeError("boom")
        ):
            await registry._register_single_tool(mcp, "system_setup")

        assert not registry.is_tool_registered("system_setup")

    @pytest.mark.asyncio
    async def test_metadata_registered_for_known_tool(self):
        """_register_tool_metadata is called with the tool name after dispatch."""
        registry = _make_registry()
        mcp = _make_mock_mcp()

        with patch.object(registry, "_register_system_setup", new_callable=AsyncMock), \
             patch.object(registry, "_register_tool_metadata", new_callable=AsyncMock) as mock_meta:
            await registry._register_single_tool(mcp, "system_setup")

        mock_meta.assert_called_once_with("system_setup")


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
    async def test_known_tool_invokes_importlib(self):
        """A known tool triggers importlib to load the tools_decomposed module."""
        registry = _make_registry()

        mock_introspection = MagicMock()
        mock_introspection.register_tool_metadata = AsyncMock()

        mock_module = MagicMock()
        mock_module.AlertManagement = MagicMock()

        import_calls: list = []

        original_import = __import__("importlib").import_module

        def capturing_import(name, *args, **kwargs):
            import_calls.append(name)
            if name == "revenium_mcp_server.tools_decomposed.alert_management":
                return mock_module
            return original_import(name, *args, **kwargs)

        with patch("importlib.import_module", side_effect=capturing_import), \
             patch(
                 "src.revenium_mcp_server.introspection.integration.introspection_integration",
                 mock_introspection,
             ):
            await registry._register_tool_metadata("manage_alerts")

        assert "revenium_mcp_server.tools_decomposed.alert_management" in import_calls

    @pytest.mark.asyncio
    async def test_import_error_logs_warning_not_raises(self):
        """If importlib.import_module raises ImportError, it is caught as a warning (no propagation)."""
        registry = _make_registry()

        with patch("importlib.import_module", side_effect=ImportError("missing")) as mock_import:
            # Must not raise
            await registry._register_tool_metadata("manage_alerts")

        mock_import.assert_called_once()


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
    async def test_malformed_json_string_anomaly_data_returns_error_text(self):
        """Malformed anomaly_data JSON string returns a TextContent error message."""
        from mcp.types import TextContent

        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_alerts")

        result = await registered_fn(
            action="create",
            anomaly_data="not valid json {{{{",
        )

        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "anomaly_data" in result[0].text.lower()

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
# JSON preprocessing — manage_sources (source_data)
# ---------------------------------------------------------------------------

class TestManageSourcesJsonPreprocessing:
    @pytest.mark.asyncio
    async def test_malformed_source_data_returns_error_text(self):
        """Malformed source_data JSON string returns a TextContent error response."""
        from mcp.types import TextContent

        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_sources")

        result = await registered_fn(
            action="create",
            source_data="{bad json",
        )

        assert len(result) == 1
        assert isinstance(result[0], TextContent)

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
# JSON preprocessing — manage_workflows (context, workflow_data)
# ---------------------------------------------------------------------------

class TestManageWorkflowsJsonPreprocessing:
    @pytest.mark.asyncio
    async def test_malformed_context_returns_error_text(self):
        """Malformed context JSON string returns a TextContent error response."""
        from mcp.types import TextContent

        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_workflows")

        result = await registered_fn(
            action="start",
            context="{invalid",
        )

        assert len(result) == 1
        assert isinstance(result[0], TextContent)

    @pytest.mark.asyncio
    async def test_malformed_workflow_data_returns_error_text(self):
        """Malformed workflow_data JSON string returns a TextContent error response."""
        from mcp.types import TextContent

        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_workflows")

        result = await registered_fn(
            action="create",
            context=None,
            workflow_data="{broken",
        )

        assert len(result) == 1
        assert isinstance(result[0], TextContent)

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
# JSON preprocessing — manage_subscriber_credentials (credential_data)
# ---------------------------------------------------------------------------

class TestManageSubscriberCredentialsJsonPreprocessing:
    @pytest.mark.asyncio
    async def test_malformed_credential_data_returns_error_text(self):
        """Malformed credential_data JSON string returns a TextContent error."""
        from mcp.types import TextContent

        registry = _make_registry()
        registered_fn = await _get_registered_closure(
            registry, "_register_manage_subscriber_credentials"
        )

        result = await registered_fn(
            action="create",
            credential_data="not-json",
        )

        assert len(result) == 1
        assert isinstance(result[0], TextContent)

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
    async def test_malformed_product_data_returns_error_text(self):
        """Malformed product_data JSON string returns a TextContent error."""
        from mcp.types import TextContent

        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_products")

        result = await registered_fn(
            action="create",
            product_data="{broken-json",
        )

        assert len(result) == 1
        assert isinstance(result[0], TextContent)

    @pytest.mark.asyncio
    async def test_malformed_resource_data_returns_error_text(self):
        """Malformed resource_data JSON string returns a TextContent error (product_data=None)."""
        from mcp.types import TextContent

        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_products")

        result = await registered_fn(
            action="create",
            product_data=None,
            resource_data="bad json>>",
        )

        assert len(result) == 1
        assert isinstance(result[0], TextContent)

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
# JSON preprocessing — manage_customers (resource_data + resource_id mapping)
# ---------------------------------------------------------------------------

class TestManageCustomersJsonPreprocessing:
    @pytest.mark.asyncio
    async def test_malformed_resource_data_returns_error_text(self):
        """Malformed resource_data JSON returns a TextContent error."""
        from mcp.types import TextContent

        registry = _make_registry()
        registered_fn = await _get_registered_closure(registry, "_register_manage_customers")

        result = await registered_fn(
            action="update",
            resource_data="{garbage",
        )

        assert len(result) == 1
        assert isinstance(result[0], TextContent)

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


# ---------------------------------------------------------------------------
# JSON preprocessing — manage_subscriptions (subscription_data)
# ---------------------------------------------------------------------------

class TestManageSubscriptionsJsonPreprocessing:
    @pytest.mark.asyncio
    async def test_malformed_subscription_data_returns_error_text(self):
        """Malformed subscription_data JSON string returns TextContent error."""
        from mcp.types import TextContent

        registry = _make_registry()
        registered_fn = await _get_registered_closure(
            registry, "_register_manage_subscriptions"
        )

        result = await registered_fn(
            action="create",
            subscription_data="{bad",
        )

        assert len(result) == 1
        assert isinstance(result[0], TextContent)

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
# JSON preprocessing — manage_metering_elements (element_data)
# ---------------------------------------------------------------------------

class TestManageMeteringElementsJsonPreprocessing:
    @pytest.mark.asyncio
    async def test_malformed_element_data_returns_error_text(self):
        """Malformed element_data JSON string returns TextContent error."""
        from mcp.types import TextContent

        registry = _make_registry()
        registered_fn = await _get_registered_closure(
            registry, "_register_manage_metering_elements"
        )

        result = await registered_fn(
            action="create",
            element_data="{{not-json",
        )

        assert len(result) == 1
        assert isinstance(result[0], TextContent)

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
# system_setup and system_diagnostics closures
# ---------------------------------------------------------------------------

class TestSystemSetupClosure:
    @pytest.mark.asyncio
    async def test_boolean_flags_converted_and_none_stripped(self):
        """system_setup boolean params are converted and None params are stripped."""
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
        """system_setup closure calls standardized_tool_execution with tool_name='system_setup'."""
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

        assert captured["tool_name"] == "system_setup"


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
