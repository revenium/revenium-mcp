"""Unit tests for mcp_compliance resource_classes, resource_helpers, and resource_management_helpers.

Covers:
- resource_classes.py: MCPResource, ResourceSubscription, ResourceType, ResourceMimeType
- resource_helpers.py: get_builtin_resource_definitions, generate_mock_content_by_type
- resource_management_helpers.py: create_resource_response, check_existing_subscription,
  remove_subscription, notify_subscribers, build_subscription_stats, etc.
"""

import pytest
from datetime import datetime

from src.revenium_mcp_server.mcp_compliance.resource_classes import (
    MCPResource,
    ResourceMimeType,
    ResourceSubscription,
    ResourceType,
)
from src.revenium_mcp_server.mcp_compliance.resource_helpers import (
    generate_mock_content_by_type,
    get_builtin_resource_definitions,
)
from src.revenium_mcp_server.mcp_compliance.resource_management_helpers import (
    add_subscription_to_list,
    build_subscription_stats,
    check_existing_subscription,
    create_resource_metadata,
    create_resource_response,
    get_mime_types_list,
    get_resource_types_list,
    notify_subscribers,
    remove_subscription,
)


class TestMCPResource:
    """Test MCPResource dataclass behavior."""

    def test_defaults_filled_on_creation(self):
        """last_modified and version get defaults on creation."""
        resource = MCPResource(
            uri="revenium://test/r1",
            name="Test",
            description="A test resource",
            mime_type=ResourceMimeType.JSON,
            resource_type=ResourceType.ANALYTICS,
        )
        assert resource.last_modified is not None
        assert resource.version == "1.0"

    def test_explicit_values_preserved(self):
        """Explicitly set last_modified and version are not overridden."""
        dt = datetime(2025, 1, 1)
        resource = MCPResource(
            uri="revenium://test/r1",
            name="Test",
            description="Desc",
            mime_type=ResourceMimeType.JSON,
            resource_type=ResourceType.ANALYTICS,
            last_modified=dt,
            version="2.0",
        )
        assert resource.last_modified == dt
        assert resource.version == "2.0"

    def test_to_mcp_resource_dict(self):
        """to_mcp_resource_dict produces correct MCP-format dictionary."""
        resource = MCPResource(
            uri="revenium://test/r1",
            name="Test",
            description="Desc",
            mime_type=ResourceMimeType.JSON,
            resource_type=ResourceType.ANALYTICS,
            annotations={"key": "val"},
        )
        d = resource.to_mcp_resource_dict()
        assert d["uri"] == "revenium://test/r1"
        assert d["name"] == "Test"
        assert d["mimeType"] == "application/json"
        assert d["annotations"] == {"key": "val"}

    @pytest.mark.asyncio
    async def test_load_content_updates_last_modified(self):
        """Successful content load updates last_modified timestamp."""
        resource = MCPResource(
            uri="revenium://test/r1",
            name="Test",
            description="Desc",
            mime_type=ResourceMimeType.JSON,
            resource_type=ResourceType.ANALYTICS,
        )
        before = resource.last_modified

        async def provider(res):
            return {"data": "loaded"}

        content = await resource.load_content(provider)
        assert content == {"data": "loaded"}
        assert resource.last_modified >= before

    @pytest.mark.asyncio
    async def test_load_content_raises_on_failure(self):
        """Content provider failure propagates the exception."""
        resource = MCPResource(
            uri="revenium://test/r1",
            name="Test",
            description="Desc",
            mime_type=ResourceMimeType.JSON,
            resource_type=ResourceType.ANALYTICS,
        )

        async def failing_provider(res):
            raise RuntimeError("provider failed")

        with pytest.raises(RuntimeError, match="provider failed"):
            await resource.load_content(failing_provider)


class TestResourceSubscription:
    """Test ResourceSubscription behavior."""

    def test_should_notify_returns_true(self):
        """Current implementation always returns True for should_notify."""
        sub = ResourceSubscription(uri="revenium://test/r1", subscriber_id="sub1")
        resource = MCPResource(
            uri="revenium://test/r1",
            name="Test",
            description="Desc",
            mime_type=ResourceMimeType.JSON,
            resource_type=ResourceType.ANALYTICS,
        )
        assert sub.should_notify(resource) is True

    def test_mark_notified_updates_state(self):
        """mark_notified increments count and sets timestamp."""
        sub = ResourceSubscription(uri="revenium://test/r1", subscriber_id="sub1")
        assert sub.notification_count == 0
        assert sub.last_notification is None

        sub.mark_notified()
        assert sub.notification_count == 1
        assert sub.last_notification is not None

        sub.mark_notified()
        assert sub.notification_count == 2


class TestBuiltinResourceDefinitions:
    """Test that builtin resource definitions are valid."""

    def test_returns_non_empty_list(self):
        """At least one builtin resource is defined."""
        resources = get_builtin_resource_definitions()
        assert len(resources) > 0

    def test_uris_are_unique(self):
        """All resource URIs are distinct."""
        resources = get_builtin_resource_definitions()
        uris = [r.uri for r in resources]
        assert len(uris) == len(set(uris))


class TestGenerateMockContent:
    """Test mock content generation by resource type."""

    def _make_resource(self, resource_type):
        return MCPResource(
            uri=f"revenium://test/{resource_type.value}",
            name="Test",
            description="Desc",
            mime_type=ResourceMimeType.JSON,
            resource_type=resource_type,
        )

    def test_analytics_content(self):
        """Analytics resources produce content with metrics."""
        content = generate_mock_content_by_type(self._make_resource(ResourceType.ANALYTICS))
        assert "metrics" in content

    def test_transactions_content(self):
        """Transactions resources produce content with transactions list."""
        content = generate_mock_content_by_type(self._make_resource(ResourceType.TRANSACTIONS))
        assert "transactions" in content

    def test_alerts_content(self):
        """Alerts resources produce content with active_alerts."""
        content = generate_mock_content_by_type(self._make_resource(ResourceType.ALERTS))
        assert "active_alerts" in content

    def test_default_content(self):
        """Non-analytics/transactions/alerts types get default content."""
        content = generate_mock_content_by_type(self._make_resource(ResourceType.REPORTS))
        assert "message" in content
        assert content["resource_type"] == "reports"


class TestResourceManagementHelpers:
    """Test resource management helper functions."""

    def test_create_resource_metadata(self):
        """create_resource_metadata extracts correct fields."""
        resource = MCPResource(
            uri="revenium://test/r1",
            name="Test",
            description="Desc",
            mime_type=ResourceMimeType.JSON,
            resource_type=ResourceType.ANALYTICS,
            size_bytes=1024,
        )
        meta = create_resource_metadata(resource)
        assert meta["name"] == "Test"
        assert meta["sizeBytes"] == 1024
        assert meta["version"] == "1.0"

    def test_create_resource_response(self):
        """create_resource_response produces URI, mimeType, content, metadata."""
        resource = MCPResource(
            uri="revenium://test/r1",
            name="Test",
            description="Desc",
            mime_type=ResourceMimeType.JSON,
            resource_type=ResourceType.ANALYTICS,
        )
        resp = create_resource_response(resource, {"data": 1})
        assert resp["uri"] == "revenium://test/r1"
        assert resp["mimeType"] == "application/json"
        assert resp["content"] == {"data": 1}
        assert "metadata" in resp

    def test_check_existing_subscription_found(self):
        """Returns True when subscriber already exists."""
        sub = ResourceSubscription(uri="u", subscriber_id="s1")
        assert check_existing_subscription([sub], "s1") is True

    def test_check_existing_subscription_not_found(self):
        """Returns False when subscriber is absent."""
        sub = ResourceSubscription(uri="u", subscriber_id="s1")
        assert check_existing_subscription([sub], "s2") is False

    def test_remove_subscription(self):
        """remove_subscription removes matching subscriber and returns count."""
        subs = [
            ResourceSubscription(uri="u", subscriber_id="s1"),
            ResourceSubscription(uri="u", subscriber_id="s2"),
        ]
        removed = remove_subscription(subs, "s1")
        assert removed == 1
        assert len(subs) == 1
        assert subs[0].subscriber_id == "s2"

    def test_remove_subscription_no_match(self):
        """remove_subscription returns 0 when subscriber not found."""
        subs = [ResourceSubscription(uri="u", subscriber_id="s1")]
        removed = remove_subscription(subs, "s99")
        assert removed == 0

    def test_notify_subscribers(self):
        """notify_subscribers marks subscribers and returns their IDs."""
        resource = MCPResource(
            uri="u",
            name="R",
            description="D",
            mime_type=ResourceMimeType.JSON,
            resource_type=ResourceType.ALERTS,
        )
        subs = [
            ResourceSubscription(uri="u", subscriber_id="s1"),
            ResourceSubscription(uri="u", subscriber_id="s2"),
        ]
        notified = notify_subscribers(subs, resource, "u")
        assert set(notified) == {"s1", "s2"}
        assert subs[0].notification_count == 1
        assert subs[1].notification_count == 1

    def test_build_subscription_stats(self):
        """build_subscription_stats produces correct counts."""
        resources = {
            "u1": MCPResource(
                uri="u1", name="R1", description="D",
                mime_type=ResourceMimeType.JSON, resource_type=ResourceType.ANALYTICS,
            ),
            "u2": MCPResource(
                uri="u2", name="R2", description="D",
                mime_type=ResourceMimeType.JSON, resource_type=ResourceType.ALERTS,
            ),
        }
        subscriptions = {
            "u1": [
                ResourceSubscription(uri="u1", subscriber_id="s1"),
                ResourceSubscription(uri="u1", subscriber_id="s2"),
            ],
        }
        stats = build_subscription_stats(resources, subscriptions)
        assert stats["total_resources"] == 2
        assert stats["total_subscriptions"] == 2
        assert stats["subscribed_resources"] == 1
        assert stats["resources_by_type"]["analytics"] == 1
        assert stats["resources_by_type"]["alerts"] == 1

    def test_get_resource_types_list(self):
        """get_resource_types_list returns all ResourceType values."""
        types = get_resource_types_list()
        assert "analytics" in types
        assert "alerts" in types

    def test_get_mime_types_list(self):
        """get_mime_types_list returns all ResourceMimeType values."""
        types = get_mime_types_list()
        assert "application/json" in types
        assert "text/plain" in types

    def test_add_subscription_to_list_new(self):
        """add_subscription_to_list creates new subscription entry."""
        subs = {}
        result = add_subscription_to_list(subs, "u1", "s1")
        assert result is True
        assert len(subs["u1"]) == 1

    def test_add_subscription_to_list_duplicate(self):
        """add_subscription_to_list is idempotent for same subscriber."""
        subs = {}
        add_subscription_to_list(subs, "u1", "s1")
        add_subscription_to_list(subs, "u1", "s1")
        assert len(subs["u1"]) == 1
