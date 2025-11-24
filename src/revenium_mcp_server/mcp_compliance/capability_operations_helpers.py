"""Helper functions for capability operations.

This module contains helper functions extracted from the main capability manager
to maintain compliance with the 300-line limit per module.
"""

from typing import Any, Callable, Dict, List, Optional

from loguru import logger


def get_default_capabilities() -> Dict[str, Any]:
    """Get default MCP capability definitions."""
    # Import here to avoid circular imports
    from .capability_manager import CapabilityInfo

    return {
        "tools": CapabilityInfo(
            name="tools",
            sub_capabilities={"listChanged": True},
            metadata={
                "description": "Tool execution and management",
                "tool_count": 11,
                "supports_introspection": True,
            },
        ),
        "resources": CapabilityInfo(
            name="resources",
            sub_capabilities={"subscribe": True, "listChanged": True},
            metadata={
                "description": "Business intelligence resource access",
                "resource_types": ["analytics", "transactions", "alerts", "reports", "dashboards"],
                "supports_subscriptions": True,
            },
        ),
        "prompts": CapabilityInfo(
            name="prompts",
            sub_capabilities={"listChanged": True},
            metadata={
                "description": "Business analytics prompt templates",
                "template_count": 0,  # Will be updated when prompts are implemented
                "supports_parameters": True,
            },
        ),
        "logging": CapabilityInfo(
            name="logging",
            sub_capabilities={},
            metadata={
                "description": "Server logging and diagnostics",
                "log_levels": ["DEBUG", "INFO", "WARNING", "ERROR"],
                "supports_structured_logs": True,
            },
        ),
    }


def register_capability_in_dict(capabilities: Dict, capability) -> bool:
    """Register a capability in the capabilities dictionary."""
    if capability.name in capabilities:
        logger.warning(f"Capability {capability.name} already exists, updating")

    capabilities[capability.name] = capability
    logger.info(f"Registered capability: {capability.name}")
    return True


def update_capability_in_dict(capabilities: Dict, name: str, **updates) -> bool:
    """Update an existing capability in the dictionary."""
    if name not in capabilities:
        logger.warning(f"Capability {name} not found for update")
        return False

    capability = capabilities[name]

    # Update fields
    for field, value in updates.items():
        if hasattr(capability, field):
            setattr(capability, field, value)
        else:
            logger.warning(f"Unknown capability field: {field}")

    logger.info(f"Updated capability: {name}")
    return True


def enable_capability_in_dict(capabilities: Dict, name: str) -> bool:
    """Enable a capability in the dictionary."""
    if name not in capabilities:
        return False

    capabilities[name].enabled = True
    logger.info(f"Enabled capability: {name}")
    return True


def disable_capability_in_dict(capabilities: Dict, name: str) -> bool:
    """Disable a capability in the dictionary."""
    if name not in capabilities:
        return False

    capabilities[name].enabled = False
    logger.info(f"Disabled capability: {name}")
    return True


def get_capabilities_mcp_format(capabilities: Dict) -> Dict[str, Any]:
    """Get capabilities in MCP format."""
    mcp_capabilities = {}

    for name, capability in capabilities.items():
        if capability.enabled:
            mcp_capabilities[name] = capability.to_mcp_format()

    return mcp_capabilities


def update_server_info_fields(server_info, **updates) -> bool:
    """Update server information fields."""
    updated = False

    for field, value in updates.items():
        if hasattr(server_info, field):
            setattr(server_info, field, value)
            updated = True
            logger.debug(f"Updated server info field: {field}")
        else:
            logger.warning(f"Unknown server info field: {field}")

    if updated:
        logger.info("Updated server information")

    return updated


def add_change_listener_to_list(listeners: List, listener: Callable[[str], None]) -> None:
    """Add a capability change listener to the list."""
    if listener not in listeners:
        listeners.append(listener)
        logger.debug("Added capability change listener")


def remove_change_listener_from_list(listeners: List, listener: Callable[[str], None]) -> None:
    """Remove a capability change listener from the list."""
    if listener in listeners:
        listeners.remove(listener)
        logger.debug("Removed capability change listener")


async def notify_capability_changed(
    listeners: List, capability_name: str, notification_funcs: Dict
) -> None:
    """Notify listeners of capability changes."""
    # Notify registered listeners
    for listener in listeners:
        try:
            listener(capability_name)
        except Exception as e:
            logger.error(f"Error notifying capability change listener: {e}")

    # Send MCP notifications based on capability type
    if capability_name in notification_funcs:
        try:
            await notification_funcs[capability_name]()
        except Exception as e:
            logger.error(f"Error sending {capability_name} notification: {e}")


async def send_notification(notification_type: str, send_func) -> None:
    """Helper function to send capability change notifications."""
    try:
        await send_func()
        logger.debug(f"Sent {notification_type}/list_changed notification")
    except Exception as e:
        logger.error(f"Failed to send {notification_type}/list_changed notification: {e}")


def build_capability_stats(capabilities: Dict) -> Dict[str, Any]:
    """Build capability statistics dictionary."""
    enabled_capabilities = [cap for cap in capabilities.values() if cap.enabled]
    disabled_capabilities = [cap for cap in capabilities.values() if not cap.enabled]

    stats = {
        "total_capabilities": len(capabilities),
        "enabled_capabilities": len(enabled_capabilities),
        "disabled_capabilities": len(disabled_capabilities),
        "capabilities_by_name": list(capabilities.keys()),
        "capabilities_by_status": {
            "enabled": [cap.name for cap in enabled_capabilities],
            "disabled": [cap.name for cap in disabled_capabilities],
        },
        "sub_capabilities_count": {},
    }

    # Count sub-capabilities
    for capability in capabilities.values():
        if capability.sub_capabilities:
            stats["sub_capabilities_count"][capability.name] = len(capability.sub_capabilities)

    return stats
