"""Unit tests for introspection/integration.py — IntrospectionIntegration class.

Each test uses a fresh IntrospectionIntegration instance with its own isolated
ToolIntrospectionEngine so that the global singleton does not contaminate results.
"""

import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.types import TextContent

from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.introspection.engine import ToolIntrospectionEngine
from src.revenium_mcp_server.introspection.integration import IntrospectionIntegration
from src.revenium_mcp_server.introspection.metadata import (
    PerformanceMetrics,
    ToolCapability,
    ToolMetadata,
    ToolType,
)

os.environ.setdefault("LOG_LEVEL", "ERROR")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_performance_metrics(success_rate: float = 1.0, error_count: int = 0) -> MagicMock:
    pm = MagicMock(spec=PerformanceMetrics)
    pm.success_rate = success_rate
    pm.error_count = error_count
    return pm


def _make_metadata(
    name: str = "test_tool",
    success_rate: float = 1.0,
    capabilities: list = None,
    supported_actions: list = None,
    quick_start_guide: list = None,
    agent_summary: str = "tool summary",
    tool_type_value: str = "crud",
    description: str = None,
    version: str = "1.0.0",
) -> MagicMock:
    m = MagicMock(spec=ToolMetadata)
    m.name = name
    m.description = description or f"Description of {name}"
    m.version = version
    m.tool_type = MagicMock()
    m.tool_type.value = tool_type_value
    m.agent_summary = agent_summary
    m.capabilities = capabilities or []
    m.supported_actions = supported_actions or ["list", "get"]
    m.quick_start_guide = quick_start_guide or []
    m.dependencies = []
    m.performance_metrics = _make_performance_metrics(success_rate=success_rate)
    return m


def _make_provider(metadata: MagicMock = None) -> MagicMock:
    provider = MagicMock()
    provider.get_tool_metadata = AsyncMock(return_value=metadata or _make_metadata())
    provider.update_performance_metrics = AsyncMock()
    provider.handle_action = AsyncMock(
        return_value=[TextContent(type="text", text="default result")]
    )
    return provider


def _fresh_integ(ucm_integration_service=None) -> IntrospectionIntegration:
    """Return a new IntrospectionIntegration backed by an isolated engine."""
    integ = IntrospectionIntegration(ucm_integration_service=ucm_integration_service)
    # Replace the shared global engine with a fresh one to isolate tests
    integ.engine = ToolIntrospectionEngine()
    return integ


# ---------------------------------------------------------------------------
# IntrospectionIntegration.initialize
# ---------------------------------------------------------------------------


class TestInitialize:
    """initialize() sets _initialized and is idempotent."""

    @pytest.mark.asyncio
    async def test_initialize_sets_initialized_flag(self):
        integ = _fresh_integ()
        assert integ._initialized is False
        await integ.initialize()
        assert integ._initialized is True

    @pytest.mark.asyncio
    async def test_initialize_is_idempotent(self):
        integ = _fresh_integ()
        await integ.initialize()
        await integ.initialize()
        assert integ._initialized is True

    @pytest.mark.asyncio
    async def test_second_initialize_does_not_change_engine_state(self):
        """Second call returns immediately; engine stays in same state."""
        integ = _fresh_integ()
        await integ.initialize()
        count_after_first = len(await integ.engine.list_tools())
        await integ.initialize()
        count_after_second = len(await integ.engine.list_tools())
        assert count_after_first == count_after_second


# ---------------------------------------------------------------------------
# IntrospectionIntegration._get_ucm_helper
# ---------------------------------------------------------------------------


class TestGetUcmHelper:
    """_get_ucm_helper returns None or UCM helper depending on service availability."""

    def test_returns_none_when_no_service(self):
        integ = _fresh_integ()
        result = integ._get_ucm_helper("My Tool")
        assert result is None

    def test_returns_helper_when_service_present(self):
        mock_service = MagicMock()
        mock_helper = MagicMock()
        mock_service.get_integration_helper.return_value = mock_helper

        integ = _fresh_integ(ucm_integration_service=mock_service)
        result = integ._get_ucm_helper("My Tool")
        assert result is mock_helper

    def test_helper_returned_is_exactly_what_service_provides(self):
        """The helper returned is the same object the service's get_integration_helper() returns."""
        sentinel = object()
        mock_service = MagicMock()
        mock_service.get_integration_helper.return_value = sentinel

        integ = _fresh_integ(ucm_integration_service=mock_service)
        result = integ._get_ucm_helper("Any Tool")
        assert result is sentinel

    def test_no_service_after_construction_returns_none(self):
        integ = _fresh_integ()
        integ.ucm_integration_service = None
        assert integ._get_ucm_helper("Tool X") is None


# ---------------------------------------------------------------------------
# IntrospectionIntegration.register_tool_metadata
# ---------------------------------------------------------------------------


class TestRegisterToolMetadata:
    """register_tool_metadata registers tool class instances with the engine."""

    @pytest.mark.asyncio
    async def test_registers_tool_in_engine(self):
        integ = _fresh_integ()
        await integ.initialize()

        mock_instance = _make_provider()
        MockClass = MagicMock(return_value=mock_instance)

        await integ.register_tool_metadata("new_tool", MockClass)
        tools = await integ.engine.list_tools()
        assert "new_tool" in tools

    @pytest.mark.asyncio
    async def test_underscore_tool_name_works(self):
        """Tool names with underscores are accepted without error."""
        integ = _fresh_integ()
        await integ.initialize()

        mock_instance = _make_provider()
        MockClass = MagicMock(return_value=mock_instance)

        await integ.register_tool_metadata("manage_products", MockClass)
        tools = await integ.engine.list_tools()
        assert "manage_products" in tools

    @pytest.mark.asyncio
    async def test_construction_failure_does_not_raise(self):
        """If the tool class constructor raises, register_tool_metadata swallows it."""
        integ = _fresh_integ()
        await integ.initialize()

        class BrokenTool:
            def __init__(self, **kwargs):
                raise RuntimeError("construction failed")

        await integ.register_tool_metadata("broken_tool", BrokenTool)
        tools = await integ.engine.list_tools()
        assert "broken_tool" not in tools

    @pytest.mark.asyncio
    async def test_ucm_helper_injected_when_service_available(self):
        mock_helper = MagicMock()
        mock_service = MagicMock()
        mock_service.get_integration_helper.return_value = mock_helper

        integ = _fresh_integ(ucm_integration_service=mock_service)
        await integ.initialize()

        captured_kwargs = {}

        class CapturingTool:
            def __init__(self, **kwargs):
                captured_kwargs.update(kwargs)

            async def get_tool_metadata(self):
                return _make_metadata()

            async def update_performance_metrics(self, *args):
                pass

        await integ.register_tool_metadata("capturing_tool", CapturingTool)
        assert captured_kwargs.get("ucm_helper") is mock_helper


# ---------------------------------------------------------------------------
# IntrospectionIntegration.get_server_summary
# ---------------------------------------------------------------------------


class TestGetServerSummary:
    """get_server_summary returns a dictionary with required keys."""

    @pytest.mark.asyncio
    async def test_returns_dict_with_required_keys(self):
        integ = _fresh_integ()
        await integ.initialize()
        summary = await integ.get_server_summary()
        assert "introspection_enabled" in summary
        assert "registered_tools" in summary
        assert "available_actions" in summary

    @pytest.mark.asyncio
    async def test_introspection_enabled_is_true(self):
        integ = _fresh_integ()
        await integ.initialize()
        summary = await integ.get_server_summary()
        assert summary["introspection_enabled"] is True

    @pytest.mark.asyncio
    async def test_registered_tools_count_reflects_engine(self):
        integ = _fresh_integ()
        await integ.initialize()

        summary_before = await integ.get_server_summary()
        count_before = summary_before["registered_tools"]

        provider = _make_provider()
        await integ.engine.register_tool("counted_tool", provider)

        summary_after = await integ.get_server_summary()
        assert summary_after["registered_tools"] == count_before + 1

    @pytest.mark.asyncio
    async def test_available_actions_includes_list_tools(self):
        integ = _fresh_integ()
        await integ.initialize()
        summary = await integ.get_server_summary()
        assert "list_tools" in summary["available_actions"]

    @pytest.mark.asyncio
    async def test_average_success_rate_is_100_on_fresh_instance(self):
        """A fresh integration with no tools reports 100% average success rate."""
        integ = _fresh_integ()
        await integ.initialize()
        summary = await integ.get_server_summary()
        assert summary["average_success_rate"] == 100.0


# ---------------------------------------------------------------------------
# IntrospectionIntegration.validate_tool_health
# ---------------------------------------------------------------------------


class TestValidateToolHealth:
    """validate_tool_health classifies tools as healthy/unhealthy/missing."""

    @pytest.mark.asyncio
    async def test_healthy_tool_classified_correctly(self):
        integ = _fresh_integ()
        await integ.initialize()

        provider = _make_provider(metadata=_make_metadata("healthy", success_rate=0.95))
        await integ.engine.register_tool("healthy", provider)

        health = await integ.validate_tool_health()
        assert "healthy" in health["healthy_tools"]
        assert "healthy" not in health["missing_metadata"]

    @pytest.mark.asyncio
    async def test_unhealthy_tool_classified_correctly(self):
        integ = _fresh_integ()
        await integ.initialize()

        provider = _make_provider(metadata=_make_metadata("sick_tool", success_rate=0.5))
        await integ.engine.register_tool("sick_tool", provider)

        health = await integ.validate_tool_health()
        unhealthy_names = [entry["tool"] for entry in health["unhealthy_tools"]]
        assert "sick_tool" in unhealthy_names

    @pytest.mark.asyncio
    async def test_unhealthy_tool_entry_has_success_rate(self):
        integ = _fresh_integ()
        await integ.initialize()

        provider = _make_provider(metadata=_make_metadata("low_rate", success_rate=0.3))
        await integ.engine.register_tool("low_rate", provider)

        health = await integ.validate_tool_health()
        entry = next(e for e in health["unhealthy_tools"] if e["tool"] == "low_rate")
        assert entry["success_rate"] == 0.3

    @pytest.mark.asyncio
    async def test_tool_with_no_metadata_goes_to_missing(self):
        integ = _fresh_integ()
        await integ.initialize()

        no_metadata_provider = MagicMock()
        no_metadata_provider.get_tool_metadata = AsyncMock(return_value=None)
        no_metadata_provider.update_performance_metrics = AsyncMock()
        await integ.engine.register_tool("ghost_tool", no_metadata_provider)

        health = await integ.validate_tool_health()
        assert "ghost_tool" in health["missing_metadata"]

    @pytest.mark.asyncio
    async def test_circular_dependencies_always_empty_list(self):
        """circular_dependencies field is always [] per current implementation."""
        integ = _fresh_integ()
        await integ.initialize()
        health = await integ.validate_tool_health()
        assert health["circular_dependencies"] == []

    @pytest.mark.asyncio
    async def test_boundary_success_rate_at_exactly_0_8_is_healthy(self):
        integ = _fresh_integ()
        await integ.initialize()

        provider = _make_provider(metadata=_make_metadata("boundary_tool", success_rate=0.8))
        await integ.engine.register_tool("boundary_tool", provider)

        health = await integ.validate_tool_health()
        assert "boundary_tool" in health["healthy_tools"]

    @pytest.mark.asyncio
    async def test_success_rate_just_below_0_8_is_unhealthy(self):
        integ = _fresh_integ()
        await integ.initialize()

        provider = _make_provider(metadata=_make_metadata("marginal_tool", success_rate=0.79))
        await integ.engine.register_tool("marginal_tool", provider)

        health = await integ.validate_tool_health()
        unhealthy_names = [e["tool"] for e in health["unhealthy_tools"]]
        assert "marginal_tool" in unhealthy_names

    @pytest.mark.asyncio
    async def test_unhealthy_entry_includes_error_count(self):
        integ = _fresh_integ()
        await integ.initialize()

        meta = _make_metadata("error_heavy", success_rate=0.6)
        meta.performance_metrics.error_count = 5
        provider = _make_provider(metadata=meta)
        await integ.engine.register_tool("error_heavy", provider)

        health = await integ.validate_tool_health()
        entry = next(e for e in health["unhealthy_tools"] if e["tool"] == "error_heavy")
        assert entry["error_count"] == 5


# ---------------------------------------------------------------------------
# IntrospectionIntegration.handle_tool_execution
# ---------------------------------------------------------------------------


class TestHandleToolExecution:
    """handle_tool_execution routes requests and tracks performance."""

    @pytest.mark.asyncio
    async def test_regular_action_returns_provider_result(self):
        integ = _fresh_integ()
        await integ.initialize()

        provider = _make_provider()
        provider.handle_action = AsyncMock(
            return_value=[TextContent(type="text", text="list result")]
        )
        await integ.engine.register_tool("my_tool", provider)

        result = await integ.handle_tool_execution("my_tool", "list", {})
        assert len(result) == 1
        assert result[0].text == "list result"

    @pytest.mark.asyncio
    async def test_get_tool_metadata_action_returns_formatted_metadata(self):
        integ = _fresh_integ()
        await integ.initialize()

        provider = _make_provider(
            metadata=_make_metadata("meta_tool", agent_summary="detailed summary")
        )
        await integ.engine.register_tool("meta_tool", provider)

        result = await integ.handle_tool_execution("meta_tool", "get_tool_metadata", {})
        assert len(result) == 1
        assert "meta_tool" in result[0].text
        assert "detailed summary" in result[0].text

    @pytest.mark.asyncio
    async def test_get_tool_metadata_action_contains_tool_metadata_header(self):
        """The get_tool_metadata response must contain a recognizable Tool Metadata header."""
        integ = _fresh_integ()
        await integ.initialize()

        provider = _make_provider(metadata=_make_metadata("header_tool"))
        await integ.engine.register_tool("header_tool", provider)

        result = await integ.handle_tool_execution("header_tool", "get_tool_metadata", {})
        # The response header contains "Tool Metadata:" followed by the tool name
        assert "Tool Metadata" in result[0].text
        assert "header_tool" in result[0].text

    @pytest.mark.asyncio
    async def test_tool_not_found_returns_error_message_in_text(self):
        """When a tool is not registered, the response must contain an error indicator."""
        integ = _fresh_integ()
        await integ.initialize()

        result = await integ.handle_tool_execution("nonexistent_tool", "list", {})
        assert len(result) == 1
        # The error response must indicate failure — not return normal content
        error_text = result[0].text
        assert "TOOL_ERROR" in error_text or "execution failed" in error_text.lower()

    @pytest.mark.asyncio
    async def test_tool_error_is_reraised_not_wrapped(self):
        """ToolError must propagate unchanged so agent receives the original message."""
        integ = _fresh_integ()
        await integ.initialize()

        provider = _make_provider()
        provider.handle_action = AsyncMock(
            side_effect=ToolError("specific validation message", error_code="VALIDATION_ERROR")
        )
        await integ.engine.register_tool("raising_tool", provider)

        with pytest.raises(ToolError) as exc_info:
            await integ.handle_tool_execution("raising_tool", "create", {})

        assert exc_info.value.message == "specific validation message"

    @pytest.mark.asyncio
    async def test_tool_error_error_code_preserved(self):
        """ToolError error_code must not be altered when re-raised."""
        integ = _fresh_integ()
        await integ.initialize()

        provider = _make_provider()
        provider.handle_action = AsyncMock(
            side_effect=ToolError("msg", error_code="MISSING_PARAMETER")
        )
        await integ.engine.register_tool("code_tool", provider)

        with pytest.raises(ToolError) as exc_info:
            await integ.handle_tool_execution("code_tool", "create", {})

        assert exc_info.value.error_code == "MISSING_PARAMETER"

    @pytest.mark.asyncio
    async def test_generic_exception_returns_error_response_not_raised(self):
        integ = _fresh_integ()
        await integ.initialize()

        provider = _make_provider()
        provider.handle_action = AsyncMock(side_effect=ValueError("something broken"))
        await integ.engine.register_tool("failing_tool", provider)

        # Should NOT raise — should return error response
        result = await integ.handle_tool_execution("failing_tool", "list", {})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)

    @pytest.mark.asyncio
    async def test_get_tool_metadata_when_metadata_is_none_falls_through_to_handle_action(self):
        """When provider returns None metadata on get_tool_metadata, falls to handle_action."""
        integ = _fresh_integ()
        await integ.initialize()

        provider = MagicMock()
        provider.get_tool_metadata = AsyncMock(return_value=None)
        provider.update_performance_metrics = AsyncMock()
        provider.handle_action = AsyncMock(
            return_value=[TextContent(type="text", text="fallback result")]
        )
        await integ.engine.register_tool("null_meta_tool", provider)

        result = await integ.handle_tool_execution("null_meta_tool", "get_tool_metadata", {})
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_returns_nonempty_list_with_text_content(self):
        """handle_tool_execution must return a non-empty list of TextContent items."""
        integ = _fresh_integ()
        await integ.initialize()

        provider = _make_provider()
        provider.handle_action = AsyncMock(
            return_value=[TextContent(type="text", text="actual content")]
        )
        await integ.engine.register_tool("typed_tool", provider)

        result = await integ.handle_tool_execution("typed_tool", "list", {})
        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
        assert result[0].text == "actual content"


# ---------------------------------------------------------------------------
# IntrospectionIntegration.generate_tool_documentation
# ---------------------------------------------------------------------------


class TestGenerateToolDocumentation:
    """generate_tool_documentation produces markdown with expected structure."""

    @pytest.mark.asyncio
    async def test_returns_string_starting_with_header(self):
        integ = _fresh_integ()
        await integ.initialize()
        doc = await integ.generate_tool_documentation()
        assert doc.startswith("# MCP Server Tool Documentation")

    @pytest.mark.asyncio
    async def test_empty_engine_returns_zero_tools_header(self):
        integ = _fresh_integ()
        await integ.initialize()
        doc = await integ.generate_tool_documentation()
        assert "Total tools: 0" in doc

    @pytest.mark.asyncio
    async def test_registered_tool_appears_in_doc(self):
        integ = _fresh_integ()
        await integ.initialize()

        provider = _make_provider(metadata=_make_metadata("documented_tool"))
        await integ.engine.register_tool("documented_tool", provider)

        doc = await integ.generate_tool_documentation()
        assert "documented_tool" in doc

    @pytest.mark.asyncio
    async def test_tool_description_in_doc(self):
        integ = _fresh_integ()
        await integ.initialize()

        meta = _make_metadata("desc_tool", description="Unique description here")
        provider = _make_provider(metadata=meta)
        await integ.engine.register_tool("desc_tool", provider)

        doc = await integ.generate_tool_documentation()
        assert "Unique description here" in doc

    @pytest.mark.asyncio
    async def test_tool_version_in_doc(self):
        integ = _fresh_integ()
        await integ.initialize()

        meta = _make_metadata("ver_tool", version="3.7.2")
        provider = _make_provider(metadata=meta)
        await integ.engine.register_tool("ver_tool", provider)

        doc = await integ.generate_tool_documentation()
        assert "3.7.2" in doc

    @pytest.mark.asyncio
    async def test_quick_start_guide_appears_in_doc(self):
        integ = _fresh_integ()
        await integ.initialize()

        meta = _make_metadata("guide_tool", quick_start_guide=["Step A", "Step B"])
        provider = _make_provider(metadata=meta)
        await integ.engine.register_tool("guide_tool", provider)

        doc = await integ.generate_tool_documentation()
        assert "Step A" in doc
        assert "Step B" in doc

    @pytest.mark.asyncio
    async def test_capabilities_listed_in_doc(self):
        integ = _fresh_integ()
        await integ.initialize()

        cap = MagicMock(spec=ToolCapability)
        cap.name = "special_cap"
        cap.description = "Does something special"

        meta = _make_metadata("cap_tool", capabilities=[cap])
        provider = _make_provider(metadata=meta)
        await integ.engine.register_tool("cap_tool", provider)

        doc = await integ.generate_tool_documentation()
        assert "special_cap" in doc

    @pytest.mark.asyncio
    async def test_tools_sorted_alphabetically(self):
        integ = _fresh_integ()
        await integ.initialize()

        for name in ["zebra_tool", "alpha_tool", "middle_tool"]:
            provider = _make_provider(metadata=_make_metadata(name))
            await integ.engine.register_tool(name, provider)

        doc = await integ.generate_tool_documentation()
        positions = {
            name: doc.index(f"## {name}") if f"## {name}" in doc else doc.index(name)
            for name in ["alpha_tool", "middle_tool", "zebra_tool"]
        }
        assert positions["alpha_tool"] < positions["middle_tool"] < positions["zebra_tool"]

    @pytest.mark.asyncio
    async def test_total_tools_count_reflects_registered_count(self):
        integ = _fresh_integ()
        await integ.initialize()

        for name in ["tool_a", "tool_b", "tool_c"]:
            provider = _make_provider(metadata=_make_metadata(name))
            await integ.engine.register_tool(name, provider)

        doc = await integ.generate_tool_documentation()
        assert "Total tools: 3" in doc

    @pytest.mark.asyncio
    async def test_actions_listed_as_comma_separated_in_doc(self):
        """supported_actions must appear as a comma-separated list in the documentation."""
        integ = _fresh_integ()
        await integ.initialize()

        meta = _make_metadata("action_tool", supported_actions=["list", "get", "create", "delete"])
        provider = _make_provider(metadata=meta)
        await integ.engine.register_tool("action_tool", provider)

        doc = await integ.generate_tool_documentation()
        assert "list, get, create, delete" in doc


# ---------------------------------------------------------------------------
# IntrospectionIntegration constructor
# ---------------------------------------------------------------------------


class TestConstructor:
    """Test IntrospectionIntegration construction with and without UCM service."""

    def test_default_constructor_has_no_ucm_service(self):
        integ = IntrospectionIntegration()
        assert integ.ucm_integration_service is None

    def test_ucm_service_stored(self):
        mock_service = MagicMock()
        integ = IntrospectionIntegration(ucm_integration_service=mock_service)
        assert integ.ucm_integration_service is mock_service

    def test_not_initialized_by_default(self):
        integ = IntrospectionIntegration()
        assert integ._initialized is False

    def test_engine_attribute_set(self):
        integ = IntrospectionIntegration()
        assert integ.engine is not None
        assert callable(integ.engine.list_tools)

    def test_service_attribute_set(self):
        integ = IntrospectionIntegration()
        assert integ.service is not None
        assert callable(integ.service.handle_introspection_action)
