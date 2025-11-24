"""Helper functions for resource management operations.

This module contains helper functions extracted from the main resources module
to maintain compliance with the 300-line limit per module.
"""

from typing import Any, Dict, List

from loguru import logger


def create_resource_metadata(resource) -> Dict[str, Any]:
    """Create metadata dictionary for a resource."""
    return {
        "name": resource.name,
        "description": resource.description,
        "lastModified": resource.last_modified.isoformat() if resource.last_modified else None,
        "sizeBytes": resource.size_bytes,
        "version": resource.version,
        "annotations": resource.annotations,
    }


def create_resource_response(resource, content) -> Dict[str, Any]:
    """Create a complete resource response with content and metadata."""
    return {
        "uri": resource.uri,
        "mimeType": resource.mime_type.value,
        "content": content,
        "metadata": create_resource_metadata(resource),
    }


def check_existing_subscription(subscriptions: List, subscriber_id: str) -> bool:
    """Check if a subscriber is already subscribed."""
    existing = [s for s in subscriptions if s.subscriber_id == subscriber_id]
    return len(existing) > 0


def remove_subscription(subscriptions: List, subscriber_id: str) -> int:
    """Remove subscription and return count of removed subscriptions."""
    original_count = len(subscriptions)
    subscriptions[:] = [s for s in subscriptions if s.subscriber_id != subscriber_id]
    return original_count - len(subscriptions)


def notify_subscribers(subscriptions: List, resource, uri: str) -> List[str]:
    """Notify all subscribers of resource changes."""
    notified_subscribers = []

    for subscription in subscriptions:
        if subscription.should_notify(resource):
            # In a real implementation, this would send actual notifications
            # For now, we just mark as notified
            subscription.mark_notified()
            notified_subscribers.append(subscription.subscriber_id)
            logger.debug(f"Notified {subscription.subscriber_id} of changes to {uri}")

    return notified_subscribers


def build_subscription_stats(resources: Dict, subscriptions: Dict) -> Dict[str, Any]:
    """Build subscription statistics dictionary."""
    total_subscriptions = sum(len(subs) for subs in subscriptions.values())

    stats = {
        "total_resources": len(resources),
        "total_subscriptions": total_subscriptions,
        "subscribed_resources": len(subscriptions),
        "resources_by_type": {},
        "subscriptions_by_resource": {},
    }

    # Count resources by type
    for resource in resources.values():
        resource_type = resource.resource_type.value
        if resource_type not in stats["resources_by_type"]:
            stats["resources_by_type"][resource_type] = 0
        stats["resources_by_type"][resource_type] += 1

    # Count subscriptions by resource
    for uri, subs in subscriptions.items():
        stats["subscriptions_by_resource"][uri] = len(subs)

    return stats


def get_resource_types_list() -> List[str]:
    """Get list of available resource types."""
    # Import here to avoid circular imports
    from .resources import ResourceType

    return [rt.value for rt in ResourceType]


def get_mime_types_list() -> List[str]:
    """Get list of supported MIME types."""
    # Import here to avoid circular imports
    from .resources import ResourceMimeType

    return [mt.value for mt in ResourceMimeType]


def add_subscription_to_list(subscriptions: Dict, uri: str, subscriber_id: str) -> bool:
    """Add a subscription to the subscriptions list."""
    # Import here to avoid circular imports
    from .resources import ResourceSubscription

    subscription = ResourceSubscription(uri, subscriber_id)

    if uri not in subscriptions:
        subscriptions[uri] = []

    # Check if already subscribed
    if check_existing_subscription(subscriptions[uri], subscriber_id):
        logger.debug(f"Subscriber {subscriber_id} already subscribed to {uri}")
        return True

    subscriptions[uri].append(subscription)
    logger.info(f"Subscribed {subscriber_id} to resource {uri}")
    return True


async def load_resource_content(resource, uri: str, content_providers: Dict, mock_content_func):
    """Load content for a resource."""
    if uri in content_providers:
        return await resource.load_content(content_providers[uri])
    else:
        # Use mock content for demonstration
        return await resource.load_content(mock_content_func)
