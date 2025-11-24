"""MCP Lifecycle Management for Protocol Compliance.

This module implements the Model Context Protocol (MCP) lifecycle management
including initialization, capability negotiation, and proper shutdown handling
as specified in the MCP specification.

Based on MCP specification:
- Initialize request/response handling
- Initialized notification support
- Protocol version negotiation
- Capability declaration and negotiation
- Ping/pong support for connection liveness
"""

from typing import Any, Dict, Optional, Union

from loguru import logger

from ..version import get_package_version
from .error_handling import (
    JSONRPCErrorCode,
    MCPError,
    create_internal_error,
    create_invalid_params_error,
)


class MCPLifecycleManager:
    """Manages MCP protocol lifecycle including initialization and capability negotiation."""

    # Supported MCP protocol versions
    SUPPORTED_PROTOCOL_VERSIONS = ["2024-11-05", "2025-03-26", "2025-06-18"]

    # Latest protocol version (preferred)
    LATEST_PROTOCOL_VERSION = "2025-06-18"

    def __init__(self, server_name: str = "revenium-mcp", server_version: Optional[str] = None):
        """Initialize the MCP lifecycle manager.

        Args:
            server_name: Name of the MCP server
            server_version: Version of the MCP server
        """
        self.server_name = server_name
        self.server_version = server_version or get_package_version()
        self.is_initialized = False
        self.client_info: Optional[Dict[str, Any]] = None
        self.negotiated_protocol_version: Optional[str] = None
        self.client_capabilities: Optional[Dict[str, Any]] = None
        self.server_capabilities = self._build_server_capabilities()

    def _build_server_capabilities(self) -> Dict[str, Any]:
        """Build server capabilities declaration.

        Returns:
            Dictionary of server capabilities
        """
        return {
            "tools": {"listChanged": True},  # Support for tools/list_changed notifications
            "resources": {
                "subscribe": True,  # Support for resource subscriptions
                "listChanged": True,  # Support for resources/list_changed notifications
            },
            "prompts": {"listChanged": True},  # Support for prompts/list_changed notifications
            "logging": {},  # Support for logging capabilities
        }

    def is_supported_protocol_version(self, version: str) -> bool:
        """Check if a protocol version is supported.

        Args:
            version: Protocol version to check

        Returns:
            True if version is supported
        """
        return version in self.SUPPORTED_PROTOCOL_VERSIONS

    async def handle_initialize_request(
        self, params: Dict[str, Any], request_id: Optional[Union[str, int]] = None
    ) -> Dict[str, Any]:
        """Handle MCP initialize request.

        Args:
            params: Initialize request parameters
            request_id: Request ID for response correlation

        Returns:
            Initialize response

        Raises:
            MCPError: If initialization fails
        """
        try:
            # Validate required parameters
            if "protocolVersion" not in params:
                raise create_invalid_params_error(
                    message="Missing required parameter: protocolVersion",
                    field="protocolVersion",
                    expected="Supported MCP protocol version",
                    suggestions=[
                        f"Provide one of: {', '.join(self.SUPPORTED_PROTOCOL_VERSIONS)}",
                        f"Latest version is: {self.LATEST_PROTOCOL_VERSION}",
                    ],
                )

            protocol_version = params["protocolVersion"]

            # Validate protocol version
            if not self.is_supported_protocol_version(protocol_version):
                raise MCPError(
                    code=JSONRPCErrorCode.INVALID_PARAMS,
                    message=f"Unsupported protocol version: {protocol_version}",
                    data={
                        "supported": self.SUPPORTED_PROTOCOL_VERSIONS,
                        "requested": protocol_version,
                        "latest": self.LATEST_PROTOCOL_VERSION,
                    },
                )

            # Store client information
            self.client_info = params.get("clientInfo", {})
            self.client_capabilities = params.get("capabilities", {})
            self.negotiated_protocol_version = protocol_version

            # Log initialization
            client_name = self.client_info.get("name", "Unknown Client")
            client_version = self.client_info.get("version", "Unknown")
            logger.info(
                f"MCP initialization from {client_name} v{client_version} using protocol {protocol_version}"
            )

            # Build initialize response
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": protocol_version,
                    "capabilities": self.server_capabilities,
                    "serverInfo": {"name": self.server_name, "version": self.server_version},
                },
            }

            # Add optional instructions for newer protocol versions
            if protocol_version in ["2025-03-26", "2025-06-18"]:
                response["result"]["instructions"] = self._get_server_instructions()

            # Mark as initialized (but not ready until initialized notification)
            self.is_initialized = True

            return response

        except MCPError:
            raise
        except Exception as e:
            logger.error(f"Error during MCP initialization: {e}")
            raise create_internal_error(
                message=f"Initialization failed: {str(e)}", context={"params": params}
            )

    def _get_server_instructions(self) -> str:
        """Get server instructions for the client.

        Returns:
            Instructions string for the client
        """
        return """
# Revenium Platform API MCP Server

This server provides comprehensive AI transaction monitoring and business analytics capabilities.

## Key Features
- AI transaction metering and cost analysis
- Natural language business analytics
- Real-time alerting and anomaly detection
- Product and subscription management
- Customer lifecycle management

## Getting Started
1. Use `introspect_tools` to discover available capabilities
2. Start with `manage_products` for product management
3. Use `analyze_business_metrics` for analytics queries
4. Set up alerts with `manage_alerts`

## Authentication
Ensure REVENIUM_API_KEY is configured for API access.
        """.strip()

    async def handle_initialized_notification(
        self, params: Optional[Dict[str, Any]] = None
    ) -> None:
        """Handle MCP initialized notification from client.

        Args:
            params: Notification parameters (usually empty)
        """
        if not self.is_initialized:
            logger.warning("Received initialized notification but server not initialized")
            return

        logger.info("MCP client initialization completed - server ready for operations")

        # Server is now fully ready for normal operations
        # This is where we could trigger any post-initialization setup

    async def handle_ping_request(
        self, params: Optional[Dict[str, Any]] = None, request_id: Optional[Union[str, int]] = None
    ) -> Dict[str, Any]:
        """Handle MCP ping request for connection liveness.

        Args:
            params: Ping parameters (usually empty)
            request_id: Request ID for response correlation

        Returns:
            Ping response (pong)
        """
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}

    async def handle_shutdown(self) -> None:
        """Handle server shutdown cleanup."""
        if self.is_initialized:
            client_name = (
                self.client_info.get("name", "Unknown Client")
                if self.client_info
                else "Unknown Client"
            )
            logger.info(f"MCP server shutting down (client: {client_name})")

            # Reset state
            self.is_initialized = False
            self.client_info = None
            self.negotiated_protocol_version = None
            self.client_capabilities = None

    def get_server_status(self) -> Dict[str, Any]:
        """Get current server status and configuration.

        Returns:
            Server status information
        """
        return {
            "initialized": self.is_initialized,
            "server_name": self.server_name,
            "server_version": self.server_version,
            "supported_protocol_versions": self.SUPPORTED_PROTOCOL_VERSIONS,
            "negotiated_protocol_version": self.negotiated_protocol_version,
            "client_info": self.client_info,
            "client_capabilities": self.client_capabilities,
            "server_capabilities": self.server_capabilities,
        }

    def validate_operation_allowed(self, operation: str) -> None:
        """Validate that an operation is allowed in the current state.

        Args:
            operation: Operation name to validate

        Raises:
            MCPError: If operation is not allowed
        """
        if not self.is_initialized and operation not in ["initialize", "ping"]:
            raise MCPError(
                code=JSONRPCErrorCode.INVALID_REQUEST,
                message=f"Operation '{operation}' not allowed before initialization",
                data={
                    "operation": operation,
                    "server_state": "not_initialized",
                    "allowed_operations": ["initialize", "ping"],
                },
            )

    def get_capability_support(self, capability: str, sub_capability: Optional[str] = None) -> bool:
        """Check if a capability is supported by the server.

        Args:
            capability: Main capability name (e.g., "tools", "resources")
            sub_capability: Sub-capability name (e.g., "listChanged", "subscribe")

        Returns:
            True if capability is supported
        """
        if capability not in self.server_capabilities:
            return False

        if sub_capability is None:
            return True

        capability_config = self.server_capabilities[capability]
        if isinstance(capability_config, dict):
            return capability_config.get(sub_capability, False)

        return False

    def get_client_capability_support(
        self, capability: str, sub_capability: Optional[str] = None
    ) -> bool:
        """Check if a capability is supported by the client.

        Args:
            capability: Main capability name
            sub_capability: Sub-capability name

        Returns:
            True if client supports the capability
        """
        if not self.client_capabilities:
            return False

        if capability not in self.client_capabilities:
            return False

        if sub_capability is None:
            return True

        capability_config = self.client_capabilities[capability]
        if isinstance(capability_config, dict):
            return capability_config.get(sub_capability, False)

        return False


# Global lifecycle manager instance
lifecycle_manager = MCPLifecycleManager()
