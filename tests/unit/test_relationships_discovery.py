"""Unit tests for relationships.discovery module.

Tests ResourceRelationshipDiscovery including relationship pattern matching,
node creation from data, timestamp parsing, relationship strength mapping,
and graph operations.
"""

import pytest
from datetime import datetime

from src.revenium_mcp_server.relationships.discovery import ResourceRelationshipDiscovery
from src.revenium_mcp_server.relationships.graph import (
    RelationshipStrength,
    RelationshipType,
)


@pytest.fixture
def discovery():
    """Create a fresh discovery engine."""
    return ResourceRelationshipDiscovery()


class TestDiscoverRelationshipsFromData:
    """Test relationship discovery from resource data."""

    def test_discovers_single_id_relationship(self, discovery):
        """Single ID field creates one relationship edge."""
        data = {"id": "prod1", "organization_id": "org1"}
        edges = discovery.discover_relationships_from_data("products", data)
        assert len(edges) >= 1
        org_edges = [e for e in edges if e.target_node.resource_type == "organizations"]
        assert len(org_edges) == 1
        assert org_edges[0].target_node.resource_id == "org1"

    def test_discovers_list_id_relationships(self, discovery):
        """List of IDs creates one edge per ID."""
        data = {"id": "prod1", "source_ids": ["s1", "s2", "s3"]}
        edges = discovery.discover_relationships_from_data("products", data)
        source_edges = [e for e in edges if e.target_node.resource_type == "sources"]
        assert len(source_edges) == 3

    def test_empty_field_skipped(self, discovery):
        """Empty or None field values produce no edges."""
        data = {"id": "prod1", "organization_id": ""}
        edges = discovery.discover_relationships_from_data("products", data)
        org_edges = [e for e in edges if e.target_node.resource_type == "organizations"]
        assert len(org_edges) == 0

    def test_unknown_resource_type_returns_empty(self, discovery):
        """Unknown resource type returns empty list."""
        edges = discovery.discover_relationships_from_data("unknown_type", {"id": "x"})
        assert edges == []

    def test_none_values_in_list_skipped(self, discovery):
        """None values within a list field are skipped."""
        data = {"id": "prod1", "source_ids": ["s1", None, "s2"]}
        edges = discovery.discover_relationships_from_data("products", data)
        source_edges = [e for e in edges if e.target_node.resource_type == "sources"]
        assert len(source_edges) == 2


class TestCreateNodeFromData:
    """Test node creation from resource data."""

    def test_extracts_id_and_name(self, discovery):
        """Node uses id and name fields from data."""
        data = {"id": "p1", "name": "Widget", "status": "active"}
        node = discovery._create_node_from_data("products", data)
        assert node.resource_id == "p1"
        assert node.resource_type == "products"
        assert node.name == "Widget"
        assert node.status == "active"

    def test_uses_resource_id_fallback(self, discovery):
        """Falls back to resource_id when id is absent."""
        data = {"resource_id": "r1"}
        node = discovery._create_node_from_data("products", data)
        assert node.resource_id == "r1"

    def test_uses_title_fallback_for_name(self, discovery):
        """Falls back to title when name is absent."""
        data = {"id": "p1", "title": "My Product"}
        node = discovery._create_node_from_data("products", data)
        assert node.name == "My Product"

    def test_parses_timestamps(self, discovery):
        """created_at and updated_at are parsed from data."""
        data = {
            "id": "p1",
            "created_at": "2025-06-01T10:00:00Z",
            "updated_at": "2025-06-15T10:00:00Z",
        }
        node = discovery._create_node_from_data("products", data)
        assert node.created_at is not None
        assert node.updated_at is not None
        assert node.created_at.year == 2025


class TestParseTimestamp:
    """Test timestamp parsing from various formats."""

    def test_parse_datetime_object(self, discovery):
        """datetime objects are returned as-is."""
        dt = datetime(2025, 1, 1)
        result = discovery._parse_timestamp(dt)
        assert result == dt

    def test_parse_iso_format(self, discovery):
        """ISO format strings are parsed correctly."""
        result = discovery._parse_timestamp("2025-06-01T10:00:00Z")
        assert result is not None
        assert result.year == 2025

    def test_parse_simple_format(self, discovery):
        """Simple date-time format is parsed."""
        result = discovery._parse_timestamp("2025-06-01 10:00:00")
        assert result is not None
        assert result.year == 2025

    def test_unparseable_returns_none(self, discovery):
        """Unparseable string returns None."""
        result = discovery._parse_timestamp("not-a-date")
        assert result is None

    def test_non_string_non_datetime_returns_none(self, discovery):
        """Non-string, non-datetime value returns None."""
        assert discovery._parse_timestamp(12345) is None


class TestRelationshipStrengthMapping:
    """Test relationship strength determination."""

    def test_belongs_to_is_critical(self, discovery):
        """BELONGS_TO relationships have CRITICAL strength."""
        strength = discovery._determine_relationship_strength(RelationshipType.BELONGS_TO)
        assert strength == RelationshipStrength.CRITICAL

    def test_owns_is_strong(self, discovery):
        """OWNS relationships have STRONG strength."""
        strength = discovery._determine_relationship_strength(RelationshipType.OWNS)
        assert strength == RelationshipStrength.STRONG

    def test_references_is_weak(self, discovery):
        """REFERENCES relationships have WEAK strength."""
        strength = discovery._determine_relationship_strength(RelationshipType.REFERENCES)
        assert strength == RelationshipStrength.WEAK

    def test_monitors_is_medium(self, discovery):
        """MONITORS relationships have MEDIUM strength."""
        strength = discovery._determine_relationship_strength(RelationshipType.MONITORS)
        assert strength == RelationshipStrength.MEDIUM


class TestAddResourceAndQuery:
    """Test adding resources and querying relationships."""

    def test_add_resource_populates_graph(self, discovery):
        """Adding a resource creates the node and its relationships in the graph."""
        data = {"id": "prod1", "name": "Widget", "organization_id": "org1"}
        discovery.add_resource("products", data)

        node = discovery.graph.get_node("products", "prod1")
        assert node is not None
        assert node.name == "Widget"

    def test_get_resource_relationships(self, discovery):
        """Getting relationships for an added resource returns relationship info."""
        discovery.add_resource("products", {"id": "p1", "organization_id": "org1"})
        result = discovery.get_resource_relationships("products", "p1")
        assert "resource" in result
        assert "outgoing_relationships" in result
        assert len(result["outgoing_relationships"]) > 0

    def test_get_relationships_for_missing_resource(self, discovery):
        """Getting relationships for non-existent resource returns error."""
        result = discovery.get_resource_relationships("products", "missing")
        assert "error" in result

    def test_get_relationship_summary(self, discovery):
        """Relationship summary includes graph stats."""
        discovery.add_resource("products", {"id": "p1"})
        summary = discovery.get_relationship_summary()
        assert "graph_statistics" in summary
        assert "relationship_patterns" in summary
        assert "products" in summary["relationship_patterns"]

    def test_find_related_resources(self, discovery):
        """find_related_resources returns subgraph for existing resource."""
        discovery.add_resource("products", {"id": "p1", "organization_id": "org1"})
        result = discovery.find_related_resources("products", "p1")
        assert "source_resource" in result
        assert "related_graph" in result

    def test_find_related_resources_missing(self, discovery):
        """find_related_resources returns error for missing resource."""
        result = discovery.find_related_resources("products", "missing")
        assert "error" in result

    def test_find_related_resources_with_type_filter(self, discovery):
        """find_related_resources handles relationship type filters."""
        discovery.add_resource("products", {"id": "p1", "organization_id": "org1"})
        result = discovery.find_related_resources(
            "products", "p1",
            relationship_types=["belongs_to"],
            max_depth=1,
        )
        assert "related_graph" in result

    def test_find_related_resources_with_invalid_type(self, discovery):
        """Invalid relationship type in filter is handled gracefully."""
        discovery.add_resource("products", {"id": "p1"})
        result = discovery.find_related_resources(
            "products", "p1",
            relationship_types=["invalid_type"],
        )
        assert "related_graph" in result
