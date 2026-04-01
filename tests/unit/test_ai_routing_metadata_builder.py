"""Unit tests for ai_routing.metadata_builder module.

Tests ReveniumMetadataBuilder: routing metadata, tool execution metadata,
error metadata, custom metadata, and configuration handling.
"""

import pytest

from src.revenium_mcp_server.ai_routing.metadata_builder import (
    MCPMetadataConfig,
    ReveniumMetadataBuilder,
    build_routing_metadata,
)


@pytest.fixture
def config():
    return MCPMetadataConfig(
        product="TestMCP",
        agent_type="test-agent",
        organization_id="test-org",
        subscription_id="test-sub",
        enable_detailed_tracking=True,
        include_query_context=True,
    )


@pytest.fixture
def builder(config):
    return ReveniumMetadataBuilder(config=config)


class TestBuildRoutingMetadata:
    """Tests for build_routing_metadata method."""

    def test_includes_base_fields(self, builder):
        meta = builder.build_routing_metadata(
            query="list products",
            tool_context="products",
            available_tools=["products", "alerts"],
        )
        assert meta["product"] == "TestMCP"
        assert meta["agent"] == "test-agent"
        assert meta["organization_id"] == "test-org"
        assert "trace_id" in meta
        assert meta["task_type"] == "query-routing-products"

    def test_uses_provided_session_id(self, builder):
        meta = builder.build_routing_metadata(
            query="test",
            tool_context="products",
            available_tools=["products"],
            session_id="custom-session-123",
        )
        assert meta["trace_id"] == "custom-session-123"

    def test_detailed_tracking_fields_present(self, builder):
        meta = builder.build_routing_metadata(
            query="test", tool_context="products", available_tools=["products"]
        )
        assert "task_id" in meta
        assert "response_quality_score" in meta

    def test_query_context_fields_present(self, builder):
        meta = builder.build_routing_metadata(
            query="test query",
            tool_context="products",
            available_tools=["products", "alerts"],
        )
        assert meta["query_length"] == len("test query")
        assert meta["available_tools_count"] == 2
        assert meta["tool_context"] == "products"
        assert meta["primary_tool"] == "products"

    def test_primary_tool_unknown_when_not_in_available(self, builder):
        meta = builder.build_routing_metadata(
            query="test",
            tool_context="nonexistent",
            available_tools=["products"],
        )
        assert meta["primary_tool"] == "unknown"

    def test_no_detailed_tracking_when_disabled(self, config):
        config.enable_detailed_tracking = False
        builder = ReveniumMetadataBuilder(config=config)
        meta = builder.build_routing_metadata(
            query="test", tool_context="products", available_tools=[]
        )
        assert "task_id" not in meta

    def test_no_query_context_when_disabled(self, config):
        config.include_query_context = False
        builder = ReveniumMetadataBuilder(config=config)
        meta = builder.build_routing_metadata(
            query="test", tool_context="products", available_tools=[]
        )
        assert "query_length" not in meta


class TestBuildToolExecutionMetadata:
    """Tests for build_tool_execution_metadata method."""

    def test_includes_base_and_execution_fields(self, builder):
        meta = builder.build_tool_execution_metadata(
            tool_name="products",
            action="create",
            parameters={"name": "test"},
        )
        assert meta["task_type"] == "tool-execution-products-create"
        assert meta["tool_name"] == "products"
        assert meta["action"] == "create"
        assert meta["parameter_count"] == 1

    def test_uses_session_id(self, builder):
        meta = builder.build_tool_execution_metadata(
            tool_name="products",
            action="list",
            parameters={},
            session_id="sess-42",
        )
        assert meta["trace_id"] == "sess-42"


class TestBuildErrorMetadata:
    """Tests for build_error_metadata method."""

    def test_includes_error_fields(self, builder):
        meta = builder.build_error_metadata(
            error_type="validation", error_context="parameter_check"
        )
        assert meta["task_type"] == "error-handling-validation"
        assert meta["error_type"] == "validation"
        assert meta["error_context"] == "parameter_check"
        assert meta["response_quality_score"] == 0.1

    def test_uses_session_id(self, builder):
        meta = builder.build_error_metadata(
            error_type="timeout",
            error_context="ai_client",
            session_id="err-session",
        )
        assert meta["trace_id"] == "err-session"


class TestBuildCustomMetadata:
    """Tests for build_custom_metadata method."""

    def test_includes_custom_fields(self, builder):
        meta = builder.build_custom_metadata(
            task_type="custom-analysis",
            custom_fields={"custom_key": "custom_value"},
        )
        assert meta["task_type"] == "custom-analysis"
        assert meta["custom_key"] == "custom_value"

    def test_no_custom_fields(self, builder):
        meta = builder.build_custom_metadata(task_type="simple-task")
        assert meta["task_type"] == "simple-task"
        assert "task_id" in meta  # detailed tracking adds this

    def test_custom_fields_dont_override_base_unless_specified(self, builder):
        meta = builder.build_custom_metadata(
            task_type="test",
            custom_fields={"task_id": "my-custom-id"},
        )
        # Custom field should take precedence since it's set before setdefault
        assert meta["task_id"] == "my-custom-id"


class TestDefaultConfig:
    """Tests for default configuration loading."""

    def test_convenience_function_works(self):
        meta = build_routing_metadata(
            query="test",
            tool_context="products",
            available_tools=["products"],
        )
        assert "product" in meta
        assert "trace_id" in meta
