"""MCP Compliance Package.

This package provides Model Context Protocol (MCP) compliance features including:
- JSON-RPC 2.0 compliant error handling
- MCP lifecycle management
- Resource discovery and access
- Prompt template system
- Session management
- Enterprise reliability patterns

The package ensures full MCP protocol compliance while maintaining backward
compatibility with existing functionality.
"""

from .capability_manager import CapabilityInfo, MCPCapabilityManager, ServerInfo, capability_manager
from .error_handling import (
    JSONRPCErrorCode,
    MCPError,
    MCPErrorData,
    create_internal_error,
    create_invalid_params_error,
    create_method_not_found_error,
    create_resource_not_found_error,
    create_tool_execution_error,
)
from .error_translator import (
    MCPErrorTranslator,
    error_translator,
    format_mcp_error_response,
    translate_to_mcp_error,
    with_mcp_error_handling,
)
from .lifecycle import MCPLifecycleManager, lifecycle_manager
from .notifications import (
    MCPNotificationManager,
    NotificationMessage,
    NotificationType,
    notification_manager,
)
from .protocol_handler import MCPProtocolHandler, protocol_handler, with_mcp_protocol_validation
from .resource_discovery import MCPResourceDiscoveryEngine, resource_discovery_engine
from .resources import (
    MCPResource,
    MCPResourceManager,
    ResourceMimeType,
    ResourceSubscription,
    ResourceType,
    resource_manager,
)
from .session_manager import MCPSessionManager, SessionInfo, session_manager

__all__ = [
    # Error handling classes
    "MCPError",
    "JSONRPCErrorCode",
    "MCPErrorData",
    # Error creation functions
    "create_invalid_params_error",
    "create_method_not_found_error",
    "create_tool_execution_error",
    "create_resource_not_found_error",
    "create_internal_error",
    # Error translation
    "MCPErrorTranslator",
    "error_translator",
    "translate_to_mcp_error",
    "format_mcp_error_response",
    "with_mcp_error_handling",
    # Lifecycle management
    "MCPLifecycleManager",
    "lifecycle_manager",
    # Protocol handling
    "MCPProtocolHandler",
    "protocol_handler",
    "with_mcp_protocol_validation",
    # Resource management
    "MCPResource",
    "ResourceType",
    "ResourceMimeType",
    "MCPResourceManager",
    "ResourceSubscription",
    "resource_manager",
    # Resource discovery
    "MCPResourceDiscoveryEngine",
    "resource_discovery_engine",
    # Capability management
    "CapabilityInfo",
    "ServerInfo",
    "MCPCapabilityManager",
    "capability_manager",
    # Notifications
    "NotificationMessage",
    "NotificationType",
    "MCPNotificationManager",
    "notification_manager",
    # Session management
    "SessionInfo",
    "MCPSessionManager",
    "session_manager",
]
