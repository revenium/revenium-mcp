"""Unit tests for enhanced_server.py — dynamic_mcp_tool, safe_extract_text,
create_enhanced_server, send_mcp_log_message, and lifespan_manager."""

import os
import sys
from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.types import EmbeddedResource, ImageContent, TextContent

# Ensure clean LOG_LEVEL for tests
os.environ.setdefault("LOG_LEVEL", "ERROR")


# ---------------------------------------------------------------------------
# safe_extract_text
# ---------------------------------------------------------------------------


class TestSafeExtractText:
    """Tests for safe_extract_text — pure function, no side effects."""

    def test_extracts_text_from_text_content(self):
        from src.revenium_mcp_server.enhanced_server import safe_extract_text

        result = [TextContent(type="text", text="hello world")]
        assert safe_extract_text(result) == "hello world"

    def test_empty_list_returns_no_result(self):
        from src.revenium_mcp_server.enhanced_server import safe_extract_text

        assert safe_extract_text([]) == "No result"

    def test_image_content_returns_no_result(self):
        from src.revenium_mcp_server.enhanced_server import safe_extract_text

        image = MagicMock(spec=ImageContent)
        result = safe_extract_text([image])
        assert result == "No result"

    def test_embedded_resource_returns_no_result(self):
        from src.revenium_mcp_server.enhanced_server import safe_extract_text

        resource = MagicMock(spec=EmbeddedResource)
        result = safe_extract_text([resource])
        assert result == "No result"

    def test_uses_only_first_item(self):
        from src.revenium_mcp_server.enhanced_server import safe_extract_text

        items = [
            TextContent(type="text", text="first"),
            TextContent(type="text", text="second"),
        ]
        assert safe_extract_text(items) == "first"

    def test_empty_string_text_content_returned_as_is(self):
        from src.revenium_mcp_server.enhanced_server import safe_extract_text

        result = [TextContent(type="text", text="")]
        assert safe_extract_text(result) == ""


# ---------------------------------------------------------------------------
# dynamic_mcp_tool decorator
# ---------------------------------------------------------------------------


class TestDynamicMcpTool:
    """Tests for dynamic_mcp_tool decorator factory."""

    def test_sets_docstring_from_registry(self):
        from src.revenium_mcp_server.enhanced_server import dynamic_mcp_tool

        with patch(
            "src.revenium_mcp_server.enhanced_server.get_tool_description",
            return_value="My tool description",
        ):
            decorator = dynamic_mcp_tool("manage_products")

            def my_func():
                pass

            result = decorator(my_func)
            assert result.__doc__ == "My tool description"

    def test_returns_original_function(self):
        from src.revenium_mcp_server.enhanced_server import dynamic_mcp_tool

        with patch(
            "src.revenium_mcp_server.enhanced_server.get_tool_description",
            return_value="desc",
        ):
            decorator = dynamic_mcp_tool("any_tool")

            def my_func():
                return 42

            result = decorator(my_func)
            assert result is my_func

    def test_fallback_docstring_on_registry_exception(self):
        from src.revenium_mcp_server.enhanced_server import dynamic_mcp_tool

        with patch(
            "src.revenium_mcp_server.enhanced_server.get_tool_description",
            side_effect=RuntimeError("registry unavailable"),
        ):
            decorator = dynamic_mcp_tool("missing_tool")

            def my_func():
                pass

            result = decorator(my_func)
            # Fallback description should mention the tool name
            assert "missing_tool" in result.__doc__

    def test_fallback_still_returns_function(self):
        from src.revenium_mcp_server.enhanced_server import dynamic_mcp_tool

        with patch(
            "src.revenium_mcp_server.enhanced_server.get_tool_description",
            side_effect=KeyError("not found"),
        ):
            decorator = dynamic_mcp_tool("broken_tool")

            def my_func():
                pass

            result = decorator(my_func)
            assert result is my_func

    def test_fallback_docstring_contains_description_unavailable(self):
        from src.revenium_mcp_server.enhanced_server import dynamic_mcp_tool

        with patch(
            "src.revenium_mcp_server.enhanced_server.get_tool_description",
            side_effect=ValueError("error"),
        ):
            decorator = dynamic_mcp_tool("my_tool")

            def my_func():
                pass

            result = decorator(my_func)
            assert "description unavailable" in result.__doc__


# ---------------------------------------------------------------------------
# send_mcp_log_message
# ---------------------------------------------------------------------------


class TestSendMcpLogMessage:
    """Tests for send_mcp_log_message — writes formatted output to stderr."""

    @pytest.mark.asyncio
    async def test_writes_to_stderr(self):
        from src.revenium_mcp_server.enhanced_server import send_mcp_log_message

        captured = StringIO()
        with patch.object(sys, "stderr", captured):
            await send_mcp_log_message("info", "test data", "test-logger")

        output = captured.getvalue()
        assert "test data" in output
        assert "test-logger" in output

    @pytest.mark.asyncio
    async def test_level_uppercased_in_output(self):
        from src.revenium_mcp_server.enhanced_server import send_mcp_log_message

        captured = StringIO()
        with patch.object(sys, "stderr", captured):
            await send_mcp_log_message("warning", "some message")

        output = captured.getvalue()
        assert "WARNING" in output

    @pytest.mark.asyncio
    async def test_default_logger_name_used(self):
        from src.revenium_mcp_server.enhanced_server import send_mcp_log_message

        captured = StringIO()
        with patch.object(sys, "stderr", captured):
            await send_mcp_log_message("debug", "msg")

        output = captured.getvalue()
        assert "revenium-mcp" in output

    @pytest.mark.asyncio
    async def test_no_exception_on_stderr_failure(self):
        from src.revenium_mcp_server.enhanced_server import send_mcp_log_message

        broken_stderr = MagicMock()
        broken_stderr.write = MagicMock(side_effect=IOError("broken pipe"))
        # Should not raise
        with patch.object(sys, "stderr", broken_stderr):
            await send_mcp_log_message("error", "data")


# ---------------------------------------------------------------------------
# create_enhanced_server
# ---------------------------------------------------------------------------


class TestCreateEnhancedServer:
    """Tests for create_enhanced_server factory function."""

    def test_returns_fastmcp_instance(self):
        from fastmcp import FastMCP

        from src.revenium_mcp_server.enhanced_server import create_enhanced_server

        with patch.dict(os.environ, {"LOG_LEVEL": "ERROR"}, clear=False):
            mcp = create_enhanced_server()
        assert isinstance(mcp, FastMCP)
        assert "revenium" in mcp.name.lower()

    def test_server_name_contains_version(self):
        from src.revenium_mcp_server.enhanced_server import create_enhanced_server
        from src.revenium_mcp_server.version import get_package_version

        with patch.dict(os.environ, {"LOG_LEVEL": "ERROR"}, clear=False):
            mcp = create_enhanced_server()
        version = get_package_version()
        assert version in mcp.name

    def test_server_name_full_format(self):
        """Server name follows the exact format 'Revenium MCP Server vX.Y.Z'."""
        from src.revenium_mcp_server.enhanced_server import create_enhanced_server
        from src.revenium_mcp_server.version import get_package_version

        with patch.dict(os.environ, {"LOG_LEVEL": "ERROR"}, clear=False):
            mcp = create_enhanced_server()
        version = get_package_version()
        assert f"Revenium MCP Server v{version}" == mcp.name

    def test_log_level_env_var_determines_log_level(self):
        """When LOG_LEVEL is set to DEBUG, the server is created with a DEBUG-capable logger.

        Verified by confirming the server is created without error AND the name/instructions
        reflect a fully initialized server (loguru reconfiguration must complete without raising).
        """
        from src.revenium_mcp_server.enhanced_server import create_enhanced_server
        from src.revenium_mcp_server.version import get_package_version

        with patch.dict(
            os.environ, {"LOG_LEVEL": "DEBUG", "MCP_STARTUP_VERBOSE": "false"}, clear=False
        ):
            mcp = create_enhanced_server()
        # If loguru raised on invalid level, we'd never reach this assertion
        assert get_package_version() in mcp.name

    def test_startup_verbose_true_produces_verbose_log_output(self):
        """With MCP_STARTUP_VERBOSE=true, verbose messages are emitted to stderr."""
        from src.revenium_mcp_server.enhanced_server import create_enhanced_server

        env = {k: v for k, v in os.environ.items() if k != "LOG_LEVEL"}
        env["MCP_STARTUP_VERBOSE"] = "true"
        env["UCM_WARNINGS_ENABLED"] = "false"

        captured = StringIO()
        with patch.dict(os.environ, env, clear=True):
            with patch.object(sys, "stderr", captured):
                create_enhanced_server()
        output = captured.getvalue()
        # The verbose path logs "Configuration will be auto-discovered on-demand when needed"
        assert "auto-discovered" in output

    def test_ucm_warnings_enabled_produces_warning_log(self):
        """With UCM_WARNINGS_ENABLED=true and verbose mode, UCM warning state is logged."""
        from src.revenium_mcp_server.enhanced_server import create_enhanced_server

        env = {k: v for k, v in os.environ.items() if k != "LOG_LEVEL"}
        env["MCP_STARTUP_VERBOSE"] = "true"
        env["UCM_WARNINGS_ENABLED"] = "true"

        captured = StringIO()
        with patch.dict(os.environ, env, clear=True):
            with patch.object(sys, "stderr", captured):
                create_enhanced_server()
        output = captured.getvalue()
        # The verbose path logs UCM warning status
        assert "UCM warnings" in output


# ---------------------------------------------------------------------------
# lifespan_manager
# ---------------------------------------------------------------------------


class TestLifespanManager:
    """Tests for lifespan_manager async context manager."""

    @pytest.mark.asyncio
    async def test_lifespan_initializes_introspection(self):
        """lifespan_manager must call initialize() on the integration object.

        We verify by using a real IntrospectionIntegration (with fresh engine) and
        confirming _initialized is True after the context runs — the observable outcome
        of initialize() being called.
        """
        from src.revenium_mcp_server.enhanced_server import lifespan_manager
        from src.revenium_mcp_server.introspection.engine import ToolIntrospectionEngine
        from src.revenium_mcp_server.introspection.integration import IntrospectionIntegration

        fresh_integ = IntrospectionIntegration()
        fresh_integ.engine = ToolIntrospectionEngine()

        with patch(
            "src.revenium_mcp_server.enhanced_server.introspection_integration",
            fresh_integ,
        ):
            async with lifespan_manager():
                pass

        assert fresh_integ._initialized is True

    @pytest.mark.asyncio
    async def test_lifespan_yields_cleanly(self):
        from src.revenium_mcp_server.enhanced_server import lifespan_manager

        with patch(
            "src.revenium_mcp_server.enhanced_server.introspection_integration"
        ) as mock_integration:
            mock_integration.initialize = AsyncMock()
            ran_body = False
            async with lifespan_manager():
                ran_body = True
            assert ran_body


# ---------------------------------------------------------------------------
# main_sync entry point
# ---------------------------------------------------------------------------


class TestMainSync:
    """Tests for main_sync entry point."""

    def test_main_sync_passes_coroutine_to_asyncio_run(self):
        """main_sync must pass an awaitable (coroutine) to asyncio.run, not None or a plain value."""
        import inspect

        from src.revenium_mcp_server.enhanced_server import main_sync

        received_arg = []

        def capture_run(coro):
            received_arg.append(coro)
            # Don't actually run it — just capture and close
            if hasattr(coro, "close"):
                coro.close()

        with patch("asyncio.run", side_effect=capture_run):
            main_sync()

        assert len(received_arg) == 1
        assert inspect.iscoroutine(received_arg[0])
