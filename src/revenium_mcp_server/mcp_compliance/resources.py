"""MCP Resource Management System.

This module implements the Model Context Protocol (MCP) resource management
system including resource discovery, access patterns, subscriptions, and
business intelligence resource providers for Revenium platform data.

Based on MCP specification:
- Resource discovery (resources/list)
- Resource access (resources/read)
- Resource subscriptions
- Resource change notifications
- MIME type handling
"""

from typing import Any, Dict, List, Optional

from loguru import logger

from .error_handling import (
    MCPError,
    create_internal_error,
    create_resource_not_found_error,
)
from .resource_classes import MCPResource, ResourceSubscription, ResourceType, ResourceMimeType
from .resource_helpers import generate_mock_content_by_type, get_builtin_resource_definitions
from .resource_management_helpers import (
    add_subscription_to_list,
    build_subscription_stats,
    create_resource_response,
    get_mime_types_list,
    get_resource_types_list,
    load_resource_content,
    notify_subscribers,
    remove_subscription,
)

# Resource classes moved to resource_classes.py


class MCPResourceManager:
    """Manages MCP resources including discovery, access, and subscriptions."""

    def __init__(self):
        """Initialize the MCP resource manager."""
        self.resources: Dict[str, MCPResource] = {}
        self.subscriptions: Dict[str, List[ResourceSubscription]] = {}
        self.content_providers: Dict[str, callable] = {}

        # Initialize built-in resources
        self._register_builtin_resources()

    def _register_builtin_resources(self):
        """Register built-in Revenium business intelligence resources."""
        builtin_resources = get_builtin_resource_definitions()

        # Register all built-in resources
        for resource in builtin_resources:
            self.register_resource(resource)

        logger.info(f"Registered {len(builtin_resources)} built-in MCP resources")

    def register_resource(self, resource: MCPResource):
        """Register a resource with the manager.

        Args:
            resource: Resource to register
        """
        self.resources[resource.uri] = resource
        logger.debug(f"Registered MCP resource: {resource.uri}")

    def register_content_provider(self, uri: str, provider: callable):
        """Register a content provider for a resource.

        Args:
            uri: Resource URI
            provider: Async function to provide content for the resource
        """
        self.content_providers[uri] = provider
        logger.debug(f"Registered content provider for: {uri}")

    async def list_resources(
        self, resource_type: Optional[ResourceType] = None
    ) -> List[Dict[str, Any]]:
        """List available resources.

        Args:
            resource_type: Optional filter by resource type

        Returns:
            List of MCP resource dictionaries
        """
        resources = list(self.resources.values())

        # Filter by type if specified
        if resource_type:
            resources = [r for r in resources if r.resource_type == resource_type]

        # Convert to MCP format
        return [resource.to_mcp_resource_dict() for resource in resources]

    async def get_resource(self, uri: str) -> MCPResource:
        """Get a resource by URI.

        Args:
            uri: Resource URI

        Returns:
            MCPResource instance

        Raises:
            MCPError: If resource not found
        """
        if uri not in self.resources:
            available_uris = list(self.resources.keys())
            raise create_resource_not_found_error(uri=uri, available_resources=available_uris)

        return self.resources[uri]

    async def read_resource(self, uri: str) -> Dict[str, Any]:
        """Read resource content."""
        try:
            resource = await self.get_resource(uri)
            content = await self._load_resource_content(resource, uri)
            return create_resource_response(resource, content)

        except MCPError:
            raise
        except Exception as e:
            logger.error(f"Error reading resource {uri}: {e}")
            raise create_internal_error(
                message=f"Failed to read resource: {str(e)}", context={"uri": uri}
            )

    async def _load_resource_content(self, resource, uri: str):
        """Load content for a resource."""
        return await load_resource_content(
            resource, uri, self.content_providers, self._generate_mock_content
        )

    async def _generate_mock_content(self, resource: MCPResource) -> Any:
        """Generate mock content for demonstration purposes.

        Args:
            resource: Resource to generate content for

        Returns:
            Mock content based on resource type
        """
        return generate_mock_content_by_type(resource)

    async def subscribe_to_resource(self, uri: str, subscriber_id: str) -> bool:
        """Subscribe to resource change notifications."""
        # Verify resource exists
        await self.get_resource(uri)
        return self._add_subscription(uri, subscriber_id)

    def _add_subscription(self, uri: str, subscriber_id: str) -> bool:
        """Add a subscription for a resource."""
        return add_subscription_to_list(self.subscriptions, uri, subscriber_id)

    async def unsubscribe_from_resource(self, uri: str, subscriber_id: str) -> bool:
        """Unsubscribe from resource change notifications.

        Args:
            uri: Resource URI to unsubscribe from
            subscriber_id: Subscriber identifier

        Returns:
            True if unsubscription was successful
        """
        if uri not in self.subscriptions:
            return False

        # Remove subscription
        removed = remove_subscription(self.subscriptions[uri], subscriber_id)
        if removed > 0:
            logger.info(f"Unsubscribed {subscriber_id} from resource {uri}")
            return True

        return False

    async def notify_resource_changed(self, uri: str) -> List[str]:
        """Notify subscribers of resource changes.

        Args:
            uri: Resource URI that changed

        Returns:
            List of subscriber IDs that were notified
        """
        if uri not in self.subscriptions:
            return []

        try:
            resource = await self.get_resource(uri)
            notified_subscribers = notify_subscribers(self.subscriptions[uri], resource, uri)

            if notified_subscribers:
                logger.info(f"Notified {len(notified_subscribers)} subscribers of changes to {uri}")

            return notified_subscribers

        except MCPError:
            logger.error(f"Cannot notify subscribers - resource {uri} not found")
            return []

    async def get_subscription_stats(self) -> Dict[str, Any]:
        """Get subscription statistics.

        Returns:
            Dictionary with subscription statistics
        """
        return build_subscription_stats(self.resources, self.subscriptions)

    def get_available_resource_types(self) -> List[str]:
        """Get list of available resource types.

        Returns:
            List of resource type names
        """
        return get_resource_types_list()

    def get_supported_mime_types(self) -> List[str]:
        """Get list of supported MIME types.

        Returns:
            List of MIME type strings
        """
        return get_mime_types_list()


# Helper functions moved to resource_helpers.py


# Global resource manager instance
resource_manager = MCPResourceManager()
