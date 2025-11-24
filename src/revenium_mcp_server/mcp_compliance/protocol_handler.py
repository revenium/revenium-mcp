"""MCP Protocol Handler for FastMCP Integration.

This module provides the integration layer between the MCP compliance system
and FastMCP, handling protocol-level operations while maintaining compatibility
with the existing FastMCP framework.
"""

from typing import Any, Callable, Dict, Optional, Union

from loguru import logger

from .error_handling import (
    MCPError,
    create_internal_error,
    create_invalid_params_error,
    create_method_not_found_error,
)
from .error_translator import format_mcp_error_response
from .lifecycle import lifecycle_manager


class MCPProtocolHandler:
    """Handles MCP protocol operations and integrates with FastMCP."""

    def __init__(self):
        """Initialize the MCP protocol handler."""
        self.lifecycle_manager = lifecycle_manager
        self.notification_handlers: Dict[str, Callable] = {}
        self.request_handlers: Dict[str, Callable] = {}

        # Register built-in handlers
        self._register_builtin_handlers()

    def _register_builtin_handlers(self) -> None:
        """Register built-in MCP protocol handlers."""
        # Request handlers
        self.request_handlers.update(
            {
                "initialize": self._handle_initialize_request,
                "ping": self._handle_ping_request,
            }
        )

        # Notification handlers
        self.notification_handlers.update(
            {
                "notifications/initialized": self._handle_initialized_notification,
            }
        )

    async def handle_mcp_request(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        request_id: Optional[Union[str, int]] = None,
    ) -> Dict[str, Any]:
        """Handle an MCP request message.

        Args:
            method: Request method name
            params: Request parameters
            request_id: Request ID for response correlation

        Returns:
            JSON-RPC response
        """
        try:
            # Validate that operation is allowed in current state
            self.lifecycle_manager.validate_operation_allowed(method)

            # Check if we have a handler for this method
            if method not in self.request_handlers:
                available_methods = list(self.request_handlers.keys())
                raise create_method_not_found_error(
                    method=method, available_methods=available_methods
                )

            # Call the handler
            handler = self.request_handlers[method]
            response = await handler(params or {}, request_id)

            logger.debug(f"Handled MCP request: {method}")
            return response

        except MCPError as e:
            # Return JSON-RPC error response
            return e.to_json_rpc_error(request_id)
        except Exception as e:
            # Convert unexpected errors to internal errors
            logger.error(f"Unexpected error handling MCP request {method}: {e}")
            internal_error = create_internal_error(
                message=f"Request handling failed: {str(e)}",
                context={"method": method, "params": params},
            )
            return internal_error.to_json_rpc_error(request_id)

    async def handle_mcp_notification(
        self, method: str, params: Optional[Dict[str, Any]] = None
    ) -> None:
        """Handle an MCP notification message.

        Args:
            method: Notification method name
            params: Notification parameters
        """
        try:
            # Check if we have a handler for this notification
            if method not in self.notification_handlers:
                logger.warning(f"No handler for notification: {method}")
                return

            # Call the handler
            handler = self.notification_handlers[method]
            await handler(params or {})

            logger.debug(f"Handled MCP notification: {method}")

        except Exception as e:
            # Notifications don't return responses, just log errors
            logger.error(f"Error handling MCP notification {method}: {e}")

    async def _handle_initialize_request(
        self, params: Dict[str, Any], request_id: Optional[Union[str, int]]
    ) -> Dict[str, Any]:
        """Handle initialize request."""
        return await self.lifecycle_manager.handle_initialize_request(params, request_id)

    async def _handle_ping_request(
        self, params: Dict[str, Any], request_id: Optional[Union[str, int]]
    ) -> Dict[str, Any]:
        """Handle ping request."""
        return await self.lifecycle_manager.handle_ping_request(params, request_id)

    async def _handle_initialized_notification(self, params: Dict[str, Any]) -> None:
        """Handle initialized notification."""
        await self.lifecycle_manager.handle_initialized_notification(params)

    def register_request_handler(self, method: str, handler: Callable) -> None:
        """Register a custom request handler.

        Args:
            method: Request method name
            handler: Async handler function
        """
        self.request_handlers[method] = handler
        logger.debug(f"Registered MCP request handler: {method}")

    def register_notification_handler(self, method: str, handler: Callable) -> None:
        """Register a custom notification handler.

        Args:
            method: Notification method name
            handler: Async handler function
        """
        self.notification_handlers[method] = handler
        logger.debug(f"Registered MCP notification handler: {method}")

    def get_server_capabilities(self) -> Dict[str, Any]:
        """Get server capabilities for initialization response.

        Returns:
            Server capabilities dictionary
        """
        return self.lifecycle_manager.server_capabilities

    def is_initialized(self) -> bool:
        """Check if the MCP server is initialized.

        Returns:
            True if server is initialized
        """
        return self.lifecycle_manager.is_initialized

    def get_protocol_version(self) -> Optional[str]:
        """Get the negotiated protocol version.

        Returns:
            Protocol version string or None if not negotiated
        """
        return self.lifecycle_manager.negotiated_protocol_version

    def get_client_info(self) -> Optional[Dict[str, Any]]:
        """Get client information from initialization.

        Returns:
            Client info dictionary or None if not initialized
        """
        return self.lifecycle_manager.client_info

    async def send_notification(
        self, method: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create a notification message to send to the client.

        Args:
            method: Notification method name
            params: Notification parameters

        Returns:
            JSON-RPC notification message
        """
        notification = {"jsonrpc": "2.0", "method": method}

        if params:
            notification["params"] = params

        logger.debug(f"Created MCP notification: {method}")
        return notification

    async def send_tools_list_changed_notification(self) -> Dict[str, Any]:
        """Send tools/list_changed notification.

        Returns:
            Notification message
        """
        return await self.send_notification("notifications/tools/list_changed")

    async def send_resources_list_changed_notification(self) -> Dict[str, Any]:
        """Send resources/list_changed notification.

        Returns:
            Notification message
        """
        return await self.send_notification("notifications/resources/list_changed")

    async def send_prompts_list_changed_notification(self) -> Dict[str, Any]:
        """Send prompts/list_changed notification.

        Returns:
            Notification message
        """
        return await self.send_notification("notifications/prompts/list_changed")

    def supports_capability(self, capability: str, sub_capability: Optional[str] = None) -> bool:
        """Check if server supports a capability.

        Args:
            capability: Main capability name
            sub_capability: Sub-capability name

        Returns:
            True if capability is supported
        """
        return self.lifecycle_manager.get_capability_support(capability, sub_capability)

    def client_supports_capability(
        self, capability: str, sub_capability: Optional[str] = None
    ) -> bool:
        """Check if client supports a capability.

        Args:
            capability: Main capability name
            sub_capability: Sub-capability name

        Returns:
            True if client supports the capability
        """
        return self.lifecycle_manager.get_client_capability_support(capability, sub_capability)

    async def shutdown(self) -> None:
        """Handle protocol handler shutdown."""
        await self.lifecycle_manager.handle_shutdown()
        logger.info("MCP protocol handler shutdown completed")


# Global protocol handler instance
protocol_handler = MCPProtocolHandler()


def with_mcp_protocol_validation(method_type: str = "request"):
    """Decorator to add MCP protocol validation to handlers.

    Args:
        method_type: Type of method ("request" or "notification")

    Returns:
        Decorator function
    """

    def decorator(func):
        async def wrapper(*args, **kwargs):
            try:
                # Validate server is initialized for non-initialization methods
                if not protocol_handler.is_initialized() and func.__name__ not in [
                    "initialize",
                    "ping",
                ]:
                    if method_type == "request":
                        error = create_invalid_params_error(
                            message="Server not initialized",
                            suggestions=["Send initialize request first"],
                        )
                        return error.to_json_rpc_error()
                    else:
                        logger.warning(
                            f"Notification {func.__name__} received before initialization"
                        )
                        return

                return await func(*args, **kwargs)

            except Exception as e:
                if method_type == "request":
                    return format_mcp_error_response(e)
                else:
                    logger.error(f"Error in notification handler {func.__name__}: {e}")

        return wrapper

    return decorator
