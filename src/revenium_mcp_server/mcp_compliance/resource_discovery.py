"""MCP Resource Discovery Engine.

This module implements the MCP resource discovery system that integrates
with the protocol handler to provide resources/list and resources/read
endpoints according to the MCP specification.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from loguru import logger

from .error_handling import (
    MCPError,
    create_internal_error,
    create_invalid_params_error,
)
from .protocol_handler import protocol_handler
from .resources import MCPResource, ResourceType, resource_manager


class MCPResourceDiscoveryEngine:
    """Handles MCP resource discovery and access operations."""

    def __init__(self):
        """Initialize the resource discovery engine."""
        self.resource_manager = resource_manager
        self._register_mcp_handlers()

    def _register_mcp_handlers(self):
        """Register MCP protocol handlers for resource operations."""
        # Register request handlers
        protocol_handler.register_request_handler("resources/list", self._handle_resources_list)
        protocol_handler.register_request_handler("resources/read", self._handle_resources_read)
        protocol_handler.register_request_handler(
            "resources/subscribe", self._handle_resources_subscribe
        )
        protocol_handler.register_request_handler(
            "resources/unsubscribe", self._handle_resources_unsubscribe
        )

        logger.info("Registered MCP resource discovery handlers")

    async def _handle_resources_list(
        self, params: Dict[str, Any], request_id: Optional[Union[str, int]]
    ) -> Dict[str, Any]:
        """Handle resources/list MCP request.

        Args:
            params: Request parameters
            request_id: Request ID for response correlation

        Returns:
            MCP response with resource list
        """
        try:
            # Extract optional filter parameters
            resource_type_filter = params.get("type")

            # Convert string to ResourceType enum if provided
            resource_type = None
            if resource_type_filter:
                try:
                    resource_type = ResourceType(resource_type_filter)
                except ValueError:
                    available_types = [rt.value for rt in ResourceType]
                    raise create_invalid_params_error(
                        message=f"Invalid resource type: {resource_type_filter}",
                        field="type",
                        value=resource_type_filter,
                        expected=f"One of: {', '.join(available_types)}",
                        suggestions=[
                            f"Use one of the supported types: {', '.join(available_types)}",
                            "Omit the type parameter to list all resources",
                        ],
                    )

            # Get resources from manager
            resources = await self.resource_manager.list_resources(resource_type)

            # Build MCP response
            response = {"jsonrpc": "2.0", "id": request_id, "result": {"resources": resources}}

            logger.debug(f"Listed {len(resources)} resources (type filter: {resource_type_filter})")
            return response

        except MCPError:
            raise
        except Exception as e:
            logger.error(f"Error in resources/list: {e}")
            raise create_internal_error(
                message=f"Resource listing failed: {str(e)}", context={"params": params}
            )

    async def _handle_resources_read(
        self, params: Dict[str, Any], request_id: Optional[Union[str, int]]
    ) -> Dict[str, Any]:
        """Handle resources/read MCP request.

        Args:
            params: Request parameters
            request_id: Request ID for response correlation

        Returns:
            MCP response with resource content
        """
        try:
            # Validate required parameters
            if "uri" not in params:
                raise create_invalid_params_error(
                    message="Missing required parameter: uri",
                    field="uri",
                    expected="Valid resource URI",
                    suggestions=[
                        "Provide a resource URI (e.g., 'revenium://analytics/cost-trends')",
                        "Use resources/list to discover available resource URIs",
                    ],
                )

            uri = params["uri"]

            # Validate URI format
            if not isinstance(uri, str) or not uri.startswith("revenium://"):
                raise create_invalid_params_error(
                    message="Invalid resource URI format",
                    field="uri",
                    value=uri,
                    expected="URI starting with 'revenium://'",
                    suggestions=[
                        "Use the format: revenium://category/resource-name",
                        "Example: revenium://analytics/cost-trends",
                    ],
                )

            # Read resource content
            resource_data = await self.resource_manager.read_resource(uri)

            # Build MCP response
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "contents": [
                        {
                            "uri": resource_data["uri"],
                            "mimeType": resource_data["mimeType"],
                            "text": self._format_resource_content(resource_data),
                        }
                    ]
                },
            }

            logger.debug(f"Read resource: {uri}")
            return response

        except MCPError:
            raise
        except Exception as e:
            logger.error(f"Error in resources/read: {e}")
            raise create_internal_error(
                message=f"Resource reading failed: {str(e)}", context={"params": params}
            )

    async def _handle_resources_subscribe(
        self, params: Dict[str, Any], request_id: Optional[Union[str, int]]
    ) -> Dict[str, Any]:
        """Handle resources/subscribe MCP request.

        Args:
            params: Request parameters
            request_id: Request ID for response correlation

        Returns:
            MCP response confirming subscription
        """
        try:
            # Validate required parameters
            if "uri" not in params:
                raise create_invalid_params_error(
                    message="Missing required parameter: uri",
                    field="uri",
                    expected="Valid resource URI",
                    suggestions=["Provide a resource URI to subscribe to"],
                )

            uri = params["uri"]

            # Use request ID as subscriber ID (in real implementation, this would be session-based)
            subscriber_id = str(request_id) if request_id else f"sub_{datetime.now().timestamp()}"

            # Subscribe to resource
            success = await self.resource_manager.subscribe_to_resource(uri, subscriber_id)

            # Build MCP response
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"subscribed": success, "uri": uri, "subscriberId": subscriber_id},
            }

            logger.debug(f"Subscribed {subscriber_id} to resource: {uri}")
            return response

        except MCPError:
            raise
        except Exception as e:
            logger.error(f"Error in resources/subscribe: {e}")
            raise create_internal_error(
                message=f"Resource subscription failed: {str(e)}", context={"params": params}
            )

    async def _handle_resources_unsubscribe(
        self, params: Dict[str, Any], request_id: Optional[Union[str, int]]
    ) -> Dict[str, Any]:
        """Handle resources/unsubscribe MCP request.

        Args:
            params: Request parameters
            request_id: Request ID for response correlation

        Returns:
            MCP response confirming unsubscription
        """
        try:
            # Validate required parameters
            if "uri" not in params:
                raise create_invalid_params_error(
                    message="Missing required parameter: uri",
                    field="uri",
                    expected="Valid resource URI",
                )

            uri = params["uri"]
            subscriber_id = params.get("subscriberId", str(request_id))

            # Unsubscribe from resource
            success = await self.resource_manager.unsubscribe_from_resource(uri, subscriber_id)

            # Build MCP response
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"unsubscribed": success, "uri": uri, "subscriberId": subscriber_id},
            }

            logger.debug(f"Unsubscribed {subscriber_id} from resource: {uri}")
            return response

        except MCPError:
            raise
        except Exception as e:
            logger.error(f"Error in resources/unsubscribe: {e}")
            raise create_internal_error(
                message=f"Resource unsubscription failed: {str(e)}", context={"params": params}
            )

    def _format_resource_content(self, resource_data: Dict[str, Any]) -> str:
        """Format resource content for MCP response.

        Args:
            resource_data: Resource data from manager

        Returns:
            Formatted content string
        """
        content = resource_data["content"]
        mime_type = resource_data["mimeType"]

        if mime_type == "application/json":
            import json

            return json.dumps(content, indent=2, default=str)
        elif mime_type in ["text/plain", "text/markdown", "text/html"]:
            return str(content)
        elif mime_type == "text/csv":
            # Convert JSON data to CSV format if possible
            if isinstance(content, list) and content:
                import csv
                import io

                output = io.StringIO()
                if isinstance(content[0], dict):
                    writer = csv.DictWriter(output, fieldnames=content[0].keys())
                    writer.writeheader()
                    writer.writerows(content)
                    return output.getvalue()
            return str(content)
        else:
            # Default to string representation
            return str(content)

    async def get_discovery_stats(self) -> Dict[str, Any]:
        """Get resource discovery statistics.

        Returns:
            Dictionary with discovery statistics
        """
        stats = await self.resource_manager.get_subscription_stats()

        # Add discovery-specific stats
        stats.update(
            {
                "supported_operations": ["list", "read", "subscribe", "unsubscribe"],
                "supported_resource_types": self.resource_manager.get_available_resource_types(),
                "supported_mime_types": self.resource_manager.get_supported_mime_types(),
                "discovery_engine_version": "1.0.0",
            }
        )

        return stats

    async def trigger_resource_change_notification(self, uri: str) -> List[str]:
        """Trigger resource change notification for testing.

        Args:
            uri: Resource URI that changed

        Returns:
            List of notified subscriber IDs
        """
        return await self.resource_manager.notify_resource_changed(uri)

    async def get_resource_by_uri(self, uri: str) -> Optional[MCPResource]:
        """Get a specific resource by URI.

        Args:
            uri: Resource URI to retrieve

        Returns:
            MCPResource instance if found, None otherwise
        """
        return await self.resource_manager.get_resource_by_uri(uri)


# Global resource discovery engine instance
resource_discovery_engine = MCPResourceDiscoveryEngine()
