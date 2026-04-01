"""Unit tests for mcp_compliance lifecycle module.

Tests the MCPLifecycleManager including initialization, protocol version
negotiation, capability support queries, and shutdown.
"""

import pytest

from src.revenium_mcp_server.mcp_compliance.lifecycle import MCPLifecycleManager
from src.revenium_mcp_server.mcp_compliance.error_handling import MCPError


@pytest.fixture
def lifecycle():
    """Create a fresh MCPLifecycleManager for each test."""
    return MCPLifecycleManager(server_name="test-server", server_version="1.0.0")


class TestProtocolVersionSupport:
    """Test protocol version validation."""

    def test_supported_version(self, lifecycle):
        """Known protocol versions are supported."""
        assert lifecycle.is_supported_protocol_version("2025-06-18") is True
        assert lifecycle.is_supported_protocol_version("2024-11-05") is True

    def test_unsupported_version(self, lifecycle):
        """Unknown protocol versions are not supported."""
        assert lifecycle.is_supported_protocol_version("1999-01-01") is False


class TestInitializeRequest:
    """Test MCP initialize request handling."""

    @pytest.mark.asyncio
    async def test_successful_initialization(self, lifecycle):
        """Valid init request returns server info and capabilities."""
        params = {
            "protocolVersion": "2025-06-18",
            "clientInfo": {"name": "test-client", "version": "0.1"},
            "capabilities": {"tools": {}},
        }
        response = await lifecycle.handle_initialize_request(params, request_id=1)
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert response["result"]["protocolVersion"] == "2025-06-18"
        assert response["result"]["serverInfo"]["name"] == "test-server"
        assert "capabilities" in response["result"]
        assert lifecycle.is_initialized is True
        assert lifecycle.client_info == {"name": "test-client", "version": "0.1"}

    @pytest.mark.asyncio
    async def test_instructions_included_for_newer_protocol(self, lifecycle):
        """Newer protocol versions include server instructions."""
        params = {"protocolVersion": "2025-06-18"}
        response = await lifecycle.handle_initialize_request(params, request_id=1)
        assert "instructions" in response["result"]

    @pytest.mark.asyncio
    async def test_instructions_not_included_for_old_protocol(self, lifecycle):
        """Older protocol versions do not include instructions."""
        params = {"protocolVersion": "2024-11-05"}
        response = await lifecycle.handle_initialize_request(params, request_id=1)
        assert "instructions" not in response["result"]

    @pytest.mark.asyncio
    async def test_missing_protocol_version_raises(self, lifecycle):
        """Missing protocolVersion raises MCPError."""
        with pytest.raises(MCPError):
            await lifecycle.handle_initialize_request({}, request_id=1)

    @pytest.mark.asyncio
    async def test_unsupported_protocol_version_raises(self, lifecycle):
        """Unsupported protocol version raises MCPError."""
        with pytest.raises(MCPError):
            await lifecycle.handle_initialize_request(
                {"protocolVersion": "1999-01-01"}, request_id=1
            )


class TestInitializedNotification:
    """Test handling of the initialized notification."""

    @pytest.mark.asyncio
    async def test_initialized_notification_after_init(self, lifecycle):
        """Notification accepted after successful initialization."""
        await lifecycle.handle_initialize_request(
            {"protocolVersion": "2025-06-18"}, request_id=1
        )
        # Should not raise
        await lifecycle.handle_initialized_notification()

    @pytest.mark.asyncio
    async def test_initialized_notification_before_init(self, lifecycle):
        """Notification before init logs warning but does not raise."""
        await lifecycle.handle_initialized_notification()


class TestPingRequest:
    """Test ping/pong handling."""

    @pytest.mark.asyncio
    async def test_ping_returns_empty_result(self, lifecycle):
        """Ping returns empty result with JSON-RPC format."""
        response = await lifecycle.handle_ping_request(request_id=42)
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 42
        assert response["result"] == {}


class TestShutdown:
    """Test server shutdown behavior."""

    @pytest.mark.asyncio
    async def test_shutdown_resets_state(self, lifecycle):
        """Shutdown clears initialization state."""
        await lifecycle.handle_initialize_request(
            {"protocolVersion": "2025-06-18"}, request_id=1
        )
        assert lifecycle.is_initialized is True
        await lifecycle.handle_shutdown()
        assert lifecycle.is_initialized is False
        assert lifecycle.client_info is None
        assert lifecycle.negotiated_protocol_version is None

    @pytest.mark.asyncio
    async def test_shutdown_before_init_is_noop(self, lifecycle):
        """Shutting down before initialization is harmless."""
        await lifecycle.handle_shutdown()
        assert lifecycle.is_initialized is False


class TestValidateOperationAllowed:
    """Test operation gating based on initialization state."""

    def test_init_and_ping_allowed_before_init(self, lifecycle):
        """initialize and ping are allowed before initialization."""
        lifecycle.validate_operation_allowed("initialize")
        lifecycle.validate_operation_allowed("ping")

    def test_other_operations_blocked_before_init(self, lifecycle):
        """Non-init operations raise MCPError before initialization."""
        with pytest.raises(MCPError):
            lifecycle.validate_operation_allowed("tools/list")

    @pytest.mark.asyncio
    async def test_all_operations_allowed_after_init(self, lifecycle):
        """After initialization, all operations are allowed."""
        await lifecycle.handle_initialize_request(
            {"protocolVersion": "2025-06-18"}, request_id=1
        )
        lifecycle.validate_operation_allowed("tools/list")
        lifecycle.validate_operation_allowed("resources/read")


class TestCapabilitySupport:
    """Test capability support queries."""

    def test_server_capability_exists(self, lifecycle):
        """Known server capabilities return True."""
        assert lifecycle.get_capability_support("tools") is True
        assert lifecycle.get_capability_support("resources") is True

    def test_server_capability_not_found(self, lifecycle):
        """Unknown capabilities return False."""
        assert lifecycle.get_capability_support("nonexistent") is False

    def test_server_sub_capability(self, lifecycle):
        """Sub-capability queries return correct values."""
        assert lifecycle.get_capability_support("tools", "listChanged") is True
        assert lifecycle.get_capability_support("resources", "subscribe") is True
        assert lifecycle.get_capability_support("tools", "nonexistent") is False

    @pytest.mark.asyncio
    async def test_client_capability_after_init(self, lifecycle):
        """Client capabilities are queryable after initialization."""
        await lifecycle.handle_initialize_request(
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {"listChanged": True}},
            },
            request_id=1,
        )
        assert lifecycle.get_client_capability_support("tools") is True
        assert lifecycle.get_client_capability_support("tools", "listChanged") is True
        assert lifecycle.get_client_capability_support("prompts") is False

    def test_client_capability_before_init(self, lifecycle):
        """Client capabilities return False before initialization."""
        assert lifecycle.get_client_capability_support("tools") is False


class TestGetServerStatus:
    """Test server status reporting."""

    def test_status_before_init(self, lifecycle):
        """Status reflects uninitialized state."""
        status = lifecycle.get_server_status()
        assert status["initialized"] is False
        assert status["server_name"] == "test-server"
        assert status["negotiated_protocol_version"] is None

    @pytest.mark.asyncio
    async def test_status_after_init(self, lifecycle):
        """Status reflects initialized state with client info."""
        await lifecycle.handle_initialize_request(
            {
                "protocolVersion": "2025-06-18",
                "clientInfo": {"name": "c"},
            },
            request_id=1,
        )
        status = lifecycle.get_server_status()
        assert status["initialized"] is True
        assert status["negotiated_protocol_version"] == "2025-06-18"
        assert status["client_info"]["name"] == "c"
