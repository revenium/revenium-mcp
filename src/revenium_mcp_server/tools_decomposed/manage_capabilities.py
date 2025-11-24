"""Manage UCM capabilities tool following enterprise Python standards.

This module provides unified capability management across all MCP tools,
decomposed into functions ≤25 lines with ≤3 parameters each.
"""

import json
from dataclasses import dataclass
from typing import Any, ClassVar, Dict, List, Optional, Union

from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..agent_friendly import UnifiedResponseFormatter
from ..introspection.metadata import ToolCapability
from ..capability_manager.integration_service import ucm_integration_service
from .manage_capabilities_errors import (
    create_execution_error,
    create_missing_verify_params_error,
    create_unsupported_action_error,
)
from .unified_tool_base import ToolBase


@dataclass
class CapabilityRequest:
    """Request parameters for capability operations."""

    action: str
    resource_type: Optional[str] = None
    capability_name: Optional[str] = None
    value: Optional[str] = None


class ManageCapabilities(ToolBase):
    """Manages UCM capabilities with decomposed helper functions."""

    tool_name: ClassVar[str] = "manage_capabilities"
    tool_description: ClassVar[str] = (
        "Manage unified capabilities across all MCP tools. Key actions: get_capabilities, verify_capability, refresh_capabilities, get_health_status. Use get_examples() for usage guidance and get_capabilities() for system status."
    )
    business_category: ClassVar[str] = "System & Monitoring Tools"
    tool_version = "1.0.0"

    def __init__(self, ucm_helper=None):
        """Initialize capabilities manager.

        Args:
            ucm_helper: UCM integration helper (unused, for compatibility)
        """
        super().__init__()
        self.formatter = UnifiedResponseFormatter("manage_capabilities")

    async def handle_action(
        self, action: str, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle capability management actions.

        Args:
            action: Action to perform
            arguments: Dictionary containing action parameters

        Returns:
            List of MCP content objects
        """
        try:
            request = self._create_request(action, arguments)

            if request.action == "get_capabilities":
                result = await self._handle_get_capabilities(request)
            elif request.action == "get_examples":
                result = await self._handle_get_examples(request)
            elif request.action == "verify_capability":
                result = await self._handle_verify_capability(request)
            elif request.action == "refresh_capabilities":
                result = await self._handle_refresh_capabilities()
            elif request.action == "get_health_status":
                result = await self._handle_get_health_status()
            elif request.action == "manage_capabilities":
                result = await self._handle_manage_capabilities(request)
            elif request.action == "get_resource_type":
                result = await self._handle_get_resource_type(request)
            elif request.action == "get_capability":
                result = await self._handle_get_capability(request)
            else:
                result = create_unsupported_action_error(request.action)

            return [TextContent(type="text", text=result)]

        except Exception as e:
            error_result = create_execution_error(e)
            return [TextContent(type="text", text=error_result)]

    def _create_request(self, action: str, arguments: Dict[str, Any]) -> CapabilityRequest:
        """Create capability request from action and arguments.

        Args:
            action: Action to perform
            arguments: Dictionary containing parameters

        Returns:
            Structured capability request
        """
        return CapabilityRequest(
            action=action,
            resource_type=arguments.get("resource_type"),
            capability_name=arguments.get("capability_name"),
            value=arguments.get("value"),
        )

    async def _handle_get_examples(self, request: CapabilityRequest) -> str:
        """Handle get_examples action.

        Args:
            request: Capability request with parameters

        Returns:
            Formatted examples response
        """
        return """# **UCM Capabilities Management Examples**

## **Basic Usage**

### **1. Get Capabilities for Resource Type**
```json
{
  "action": "get_capabilities",
  "resource_type": "products"
}
```

### **2. Verify Capability Value**
```json
{
  "action": "verify_capability",
  "resource_type": "products",
  "capability_name": "currencies",
  "value": "USD"
}
```

### **3. Check System Health**
```json
{
  "action": "get_health_status"
}
```

### **4. Refresh All Capabilities**
```json
{
  "action": "refresh_capabilities"
}
```

## **Available Resource Types**
- `products` - Product management capabilities
- `subscriptions` - Subscription management capabilities
- `customers` - Customer management capabilities
- `alerts` - Alert management capabilities
- `sources` - Source management capabilities
- `metering_elements` - Metering element capabilities

## **Common Workflows**

### **Configuration Validation**
1. Get capabilities: `get_capabilities(resource_type="products")`
2. Verify values: `verify_capability(resource_type="products", capability_name="currencies", value="USD")`

### **System Monitoring**
1. Check health: `get_health_status()`
2. Refresh if needed: `refresh_capabilities()`

## **Integration Notes**
- Use this tool for system diagnostics and capability validation
- Primarily for advanced users and system administrators
- Results provide real-time UCM configuration status
"""

    async def _handle_get_capabilities(self, request: CapabilityRequest) -> str:
        """Handle get_capabilities action.

        Args:
            request: Capability request with parameters

        Returns:
            Formatted capabilities response
        """
        if not request.resource_type:
            # Naive agent friendly: show all available resource types with guidance
            resource_types = await ucm_integration_service.get_available_resource_types()
            return f"""# **Capabilities Overview**

## **Available Resource Types**
{chr(10).join(f"- **{rt}** - {rt.replace('_', ' ').title()} management capabilities" for rt in resource_types)}

## **Next Steps**
Get specific capabilities for any resource type:

```json
{{"action": "get_capabilities", "resource_type": "products"}}
```

```json
{{"action": "get_capabilities", "resource_type": "subscriptions"}}
```

```json
{{"action": "get_capabilities", "resource_type": "customers"}}
```

## **Other Useful Actions**
- `get_health_status` - Check system health
- `get_examples` - See usage examples  
- `verify_capability` - Validate capability values

**💡 Tip**: Start with any resource type above to see detailed capabilities, validation rules, and supported values.
"""

        capabilities = await ucm_integration_service.get_ucm_capabilities(request.resource_type)
        return (
            f"# **Capabilities for {request.resource_type}**\n\n"
            f"```json\n{json.dumps(capabilities, indent=2)}\n```"
        )

    async def _handle_verify_capability(self, request: CapabilityRequest) -> str:
        """Handle verify_capability action.

        Args:
            request: Capability request with parameters

        Returns:
            Formatted verification response
        """
        missing_params = self._get_missing_verify_params(request)
        if missing_params:
            return create_missing_verify_params_error(missing_params)

        # Type assertions: after validation, these are guaranteed to be non-None
        assert request.resource_type is not None
        assert request.capability_name is not None
        assert request.value is not None

        is_valid = await ucm_integration_service.validate_capability_value(
            request.resource_type, request.capability_name, request.value
        )
        status = "✅ Valid" if is_valid else "❌ Invalid"

        return (
            f"# **Capability Verification**\n\n"
            f"**Resource Type**: {request.resource_type}\n"
            f"**Capability**: {request.capability_name}\n"
            f"**Value**: {request.value}\n"
            f"**Status**: {status}"
        )

    async def _handle_refresh_capabilities(self) -> str:
        """Handle refresh_capabilities action.

        Returns:
            Formatted refresh response
        """
        health_status = await ucm_integration_service.refresh_all_capabilities()
        return (
            f"# **Capabilities Refreshed**\n\n"
            f"```json\n{json.dumps(health_status, indent=2)}\n```"
        )

    async def _handle_get_health_status(self) -> str:
        """Handle get_health_status action.

        Returns:
            Formatted health status response
        """
        health_status = await ucm_integration_service.get_health_status()
        return f"# **UCM Health Status**\n\n" f"```json\n{json.dumps(health_status, indent=2)}\n```"

    def _get_missing_verify_params(self, request: CapabilityRequest) -> List[str]:
        """Get list of missing parameters for verify_capability.

        Args:
            request: Capability request to validate

        Returns:
            List of missing parameter names
        """
        missing = []
        if not request.resource_type:
            missing.append("resource_type")
        if not request.capability_name:
            missing.append("capability_name")
        if not request.value:
            missing.append("value")
        return missing

    async def _handle_manage_capabilities(self, request: CapabilityRequest) -> str:
        """Handle generic manage_capabilities action.

        Args:
            request: Capability request with parameters

        Returns:
            Formatted capabilities management response
        """
        capabilities_overview = await ucm_integration_service.get_all_capabilities()
        return (
            f"# **UCM Capabilities Management**\n\n"
            f"**Available Capabilities**: {len(capabilities_overview)} configured\n\n"
            f"```json\n{json.dumps(capabilities_overview, indent=2)}\n```\n\n"
            f"**Available Actions**: get_capabilities, get_capability, verify_capability, refresh_capabilities, get_health_status"
        )

    async def _handle_get_resource_type(self, request: CapabilityRequest) -> str:
        """Handle get_resource_type action.

        Args:
            request: Capability request with parameters

        Returns:
            Formatted resource type response
        """
        resource_types = await ucm_integration_service.get_available_resource_types()
        return (
            f"# **Available Resource Types**\n\n"
            f"```json\n{json.dumps(resource_types, indent=2)}\n```\n\n"
            f"**Note**: Use these resource types with get_capabilities() to retrieve specific capabilities."
        )

    async def _handle_get_capability(self, request: CapabilityRequest) -> str:
        """Handle get_capability action.

        Args:
            request: Capability request with parameters

        Returns:
            Formatted get capability response
        """
        if request.capability_name:
            # Get specific capability
            capability_value = await ucm_integration_service.get_capability_value(
                request.resource_type or "system", request.capability_name
            )
            return (
                f"# **Capability Value**\n\n"
                f"**Resource Type**: {request.resource_type or 'system'}\n"
                f"**Capability**: {request.capability_name}\n"
                f"**Current Value**: {capability_value}\n"
            )
        else:
            # Get all capabilities for resource type
            capabilities = await ucm_integration_service.get_ucm_capabilities(
                request.resource_type or "system"
            )
            return (
                f"# **All Capabilities for {request.resource_type or 'system'}**\n\n"
                f"```json\n{json.dumps(capabilities, indent=2)}\n```"
            )

    async def _get_input_schema(self) -> Dict[str, Any]:
        """Context7 single source of truth for manage_capabilities schema."""
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": await self._get_supported_actions(),
                    "description": "Action to perform - get_capabilities for listing capabilities, get_health_status for system status, get_examples for usage guidance",
                },
                # Resource selection parameter
                "resource_type": {
                    "type": "string",
                    "description": "Resource type for capabilities (required for get_capabilities action)",
                },
                # Capability verification parameters
                "capability_name": {
                    "type": "string",
                    "description": "Capability name for verification or individual capability operations",
                },
                "value": {"type": "string", "description": "Value to verify against capability"},
            },
            "required": ["action"],  # Context7: User-centric - only action required
            "additionalProperties": False,
        }

    async def _get_supported_actions(self) -> List[str]:
        """Get list of supported actions for capabilities management."""
        return [
            "get_capabilities",
            "get_examples",
            "verify_capability",
            "refresh_capabilities",
            "get_health_status",
            "manage_capabilities",
            "get_resource_type",
            "get_capability",
        ]

    # Metadata Provider Implementation
    async def _get_tool_capabilities(self) -> List[ToolCapability]:
        """Get capabilities management tool capabilities."""
        from ..introspection.metadata import ToolCapability

        return [
            ToolCapability(
                name="UCM Capabilities Management",
                description="Access and manage unified capabilities across all MCP tools through UCM integration",
                parameters={
                    "get_capabilities": {"resource_type": "str"},
                    "verify_capability": {"resource_type": "str", "capability_name": "str", "value": "str"},
                    "refresh_capabilities": {},
                    "get_health_status": {},
                },
                examples=[
                    "get_capabilities(resource_type='products')",
                    "verify_capability(resource_type='products', capability_name='currencies', value='USD')",
                    "refresh_capabilities()",
                    "get_health_status()",
                ],
                limitations=[
                    "Requires UCM service connectivity",
                    "Capability validation depends on UCM data quality",
                    "Some capabilities may be cached and require refresh",
                ],
            ),
            ToolCapability(
                name="System Health Monitoring",
                description="Monitor UCM system health and integration status",
                parameters={
                    "get_health_status": {},
                },
                examples=[
                    "get_health_status()",
                ],
                limitations=[
                    "Health status reflects UCM service availability only",
                ],
            ),
            ToolCapability(
                name="Capability Discovery",
                description="Discover available resource types and their capabilities",
                parameters={
                    "get_examples": {},
                    "get_resource_type": {"resource_type": "str"},
                    "get_capability": {"resource_type": "str", "capability_name": "str"},
                },
                examples=[
                    "get_examples()",
                    "get_resource_type(resource_type='products')",
                    "get_capability(resource_type='products', capability_name='currencies')",
                ],
                limitations=[
                    "Discovery limited to UCM-registered resource types",
                ],
            ),
        ]

    async def _get_quick_start_guide(self) -> List[str]:
        """Get quick start guide."""
        return [
            "Start with get_health_status() to verify UCM system connectivity",
            "Use get_capabilities(resource_type='products') to see available product capabilities",
            "Verify configuration values with verify_capability() before using in other tools",
            "Check get_examples() for comprehensive usage guidance and supported resource types",
            "Use refresh_capabilities() to update cached capability data when needed",
        ]
