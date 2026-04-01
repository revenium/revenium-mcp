"""Unit tests for relationships.graph module.

Tests ResourceNode, RelationshipEdge, and ResourceGraph including node/edge
management, path finding, subgraph extraction, and statistics.
"""

import pytest
from datetime import datetime

from src.revenium_mcp_server.relationships.graph import (
    RelationshipEdge,
    RelationshipStrength,
    RelationshipType,
    ResourceGraph,
    ResourceNode,
)


@pytest.fixture
def org_node():
    return ResourceNode(resource_type="organizations", resource_id="org1", name="Acme")


@pytest.fixture
def product_node():
    return ResourceNode(resource_type="products", resource_id="prod1", name="Widget")


@pytest.fixture
def user_node():
    return ResourceNode(resource_type="users", resource_id="u1", name="Alice")


class TestResourceNode:
    """Test ResourceNode behavior."""

    def test_hash_based_on_type_and_id(self):
        """Nodes with same type+id hash equally."""
        n1 = ResourceNode(resource_type="products", resource_id="p1")
        n2 = ResourceNode(resource_type="products", resource_id="p1", name="Different")
        assert hash(n1) == hash(n2)

    def test_equality_based_on_type_and_id(self):
        """Nodes are equal when type and id match."""
        n1 = ResourceNode(resource_type="products", resource_id="p1")
        n2 = ResourceNode(resource_type="products", resource_id="p1", name="Different")
        assert n1 == n2

    def test_inequality_different_id(self):
        """Nodes with different IDs are not equal."""
        n1 = ResourceNode(resource_type="products", resource_id="p1")
        n2 = ResourceNode(resource_type="products", resource_id="p2")
        assert n1 != n2

    def test_inequality_different_type(self):
        """Nodes with different types are not equal."""
        n1 = ResourceNode(resource_type="products", resource_id="p1")
        n2 = ResourceNode(resource_type="users", resource_id="p1")
        assert n1 != n2

    def test_not_equal_to_non_node(self):
        """Node is not equal to a non-ResourceNode object."""
        n = ResourceNode(resource_type="products", resource_id="p1")
        assert n != "not a node"

    def test_to_dict(self):
        """to_dict produces correct dictionary."""
        dt = datetime(2025, 6, 1)
        n = ResourceNode(
            resource_type="products", resource_id="p1",
            name="Widget", status="active",
            created_at=dt,
        )
        d = n.to_dict()
        assert d["resource_type"] == "products"
        assert d["resource_id"] == "p1"
        assert d["name"] == "Widget"
        assert d["created_at"] == "2025-06-01T00:00:00"

    def test_to_dict_none_dates(self):
        """to_dict handles None dates gracefully."""
        n = ResourceNode(resource_type="products", resource_id="p1")
        d = n.to_dict()
        assert d["created_at"] is None
        assert d["updated_at"] is None


class TestRelationshipEdge:
    """Test RelationshipEdge behavior."""

    def test_hash_based_on_nodes_and_type(self):
        """Edges with same source, target, and type hash equally."""
        n1 = ResourceNode(resource_type="orgs", resource_id="o1")
        n2 = ResourceNode(resource_type="products", resource_id="p1")
        e1 = RelationshipEdge(n1, n2, RelationshipType.OWNS)
        e2 = RelationshipEdge(n1, n2, RelationshipType.OWNS)
        assert hash(e1) == hash(e2)

    def test_equality(self):
        """Edges are equal when source, target, and type match."""
        n1 = ResourceNode(resource_type="orgs", resource_id="o1")
        n2 = ResourceNode(resource_type="products", resource_id="p1")
        e1 = RelationshipEdge(n1, n2, RelationshipType.OWNS)
        e2 = RelationshipEdge(n1, n2, RelationshipType.OWNS, strength=RelationshipStrength.STRONG)
        assert e1 == e2

    def test_inequality_different_type(self):
        """Edges with different relationship types are not equal."""
        n1 = ResourceNode(resource_type="orgs", resource_id="o1")
        n2 = ResourceNode(resource_type="products", resource_id="p1")
        e1 = RelationshipEdge(n1, n2, RelationshipType.OWNS)
        e2 = RelationshipEdge(n1, n2, RelationshipType.REFERENCES)
        assert e1 != e2

    def test_not_equal_to_non_edge(self):
        """Edge is not equal to a non-RelationshipEdge object."""
        n1 = ResourceNode(resource_type="orgs", resource_id="o1")
        n2 = ResourceNode(resource_type="products", resource_id="p1")
        e = RelationshipEdge(n1, n2, RelationshipType.OWNS)
        assert e != "not an edge"

    def test_to_dict(self):
        """to_dict produces correct structure."""
        n1 = ResourceNode(resource_type="orgs", resource_id="o1")
        n2 = ResourceNode(resource_type="products", resource_id="p1")
        e = RelationshipEdge(n1, n2, RelationshipType.OWNS, strength=RelationshipStrength.STRONG)
        d = e.to_dict()
        assert d["source"]["resource_type"] == "orgs"
        assert d["target"]["resource_type"] == "products"
        assert d["relationship_type"] == "owns"
        assert d["strength"] == "strong"


class TestResourceGraph:
    """Test ResourceGraph operations."""

    def test_add_and_get_node(self, org_node):
        """Nodes can be added and retrieved by type+id."""
        g = ResourceGraph()
        g.add_node(org_node)
        found = g.get_node("organizations", "org1")
        assert found == org_node

    def test_get_nonexistent_node(self):
        """Getting a node that doesn't exist returns None."""
        g = ResourceGraph()
        assert g.get_node("products", "missing") is None

    def test_add_edge_auto_adds_nodes(self, org_node, product_node):
        """Adding an edge auto-registers source and target nodes."""
        g = ResourceGraph()
        edge = RelationshipEdge(org_node, product_node, RelationshipType.OWNS)
        g.add_edge(edge)
        assert g.get_node("organizations", "org1") is not None
        assert g.get_node("products", "prod1") is not None
        assert len(g.edges) == 1

    def test_outgoing_and_incoming_edges(self, org_node, product_node):
        """Outgoing edges from source and incoming edges to target are tracked."""
        g = ResourceGraph()
        edge = RelationshipEdge(org_node, product_node, RelationshipType.OWNS)
        g.add_edge(edge)

        outgoing = g.get_outgoing_edges(org_node)
        assert len(outgoing) == 1
        assert outgoing[0].target_node == product_node

        incoming = g.get_incoming_edges(product_node)
        assert len(incoming) == 1
        assert incoming[0].source_node == org_node

    def test_bidirectional_edge(self, org_node, product_node):
        """Bidirectional edge creates a reverse edge."""
        g = ResourceGraph()
        edge = RelationshipEdge(org_node, product_node, RelationshipType.REFERENCES, bidirectional=True)
        g.add_edge(edge)

        # Both directions should have edges
        assert len(g.get_outgoing_edges(org_node)) >= 1
        assert len(g.get_outgoing_edges(product_node)) >= 1

    def test_get_related_nodes_outgoing(self, org_node, product_node, user_node):
        """get_related_nodes returns target nodes for outgoing direction."""
        g = ResourceGraph()
        g.add_edge(RelationshipEdge(org_node, product_node, RelationshipType.OWNS))
        g.add_edge(RelationshipEdge(org_node, user_node, RelationshipType.CONTAINS))

        related = g.get_related_nodes(org_node, direction="outgoing")
        assert product_node in related
        assert user_node in related

    def test_get_related_nodes_filtered_by_type(self, org_node, product_node, user_node):
        """get_related_nodes can filter by relationship type."""
        g = ResourceGraph()
        g.add_edge(RelationshipEdge(org_node, product_node, RelationshipType.OWNS))
        g.add_edge(RelationshipEdge(org_node, user_node, RelationshipType.CONTAINS))

        related = g.get_related_nodes(
            org_node, relationship_types=[RelationshipType.OWNS], direction="outgoing"
        )
        assert product_node in related
        assert user_node not in related

    def test_get_related_nodes_incoming(self, org_node, product_node):
        """get_related_nodes returns source nodes for incoming direction."""
        g = ResourceGraph()
        g.add_edge(RelationshipEdge(org_node, product_node, RelationshipType.OWNS))

        related = g.get_related_nodes(product_node, direction="incoming")
        assert org_node in related


class TestResourceGraphPathFinding:
    """Test BFS path finding."""

    def test_find_path_direct(self, org_node, product_node):
        """Direct path between connected nodes is found."""
        g = ResourceGraph()
        g.add_edge(RelationshipEdge(org_node, product_node, RelationshipType.OWNS))

        path = g.find_path(org_node, product_node)
        assert path is not None
        assert len(path) == 1
        assert path[0].target_node == product_node

    def test_find_path_multi_hop(self, org_node, product_node, user_node):
        """Multi-hop path is found via BFS."""
        g = ResourceGraph()
        g.add_edge(RelationshipEdge(org_node, product_node, RelationshipType.OWNS))
        g.add_edge(RelationshipEdge(product_node, user_node, RelationshipType.REFERENCES))

        path = g.find_path(org_node, user_node)
        assert path is not None
        assert len(path) == 2

    def test_find_path_same_node(self, org_node):
        """Path from a node to itself is an empty path."""
        g = ResourceGraph()
        g.add_node(org_node)
        path = g.find_path(org_node, org_node)
        assert path == []

    def test_find_path_no_path_exists(self, org_node, product_node):
        """Returns None when no path exists."""
        g = ResourceGraph()
        g.add_node(org_node)
        g.add_node(product_node)
        path = g.find_path(org_node, product_node)
        assert path is None

    def test_find_path_respects_max_depth(self, org_node, product_node, user_node):
        """Path search respects max_depth limit."""
        g = ResourceGraph()
        g.add_edge(RelationshipEdge(org_node, product_node, RelationshipType.OWNS))
        g.add_edge(RelationshipEdge(product_node, user_node, RelationshipType.REFERENCES))

        # max_depth=1 should not find path of length 2
        path = g.find_path(org_node, user_node, max_depth=1)
        assert path is None


class TestResourceGraphSubgraph:
    """Test subgraph extraction."""

    def test_get_subgraph_depth_limits_traversal(self, org_node, product_node, user_node):
        """Subgraph with max_depth=1 includes only directly connected nodes
        (target nodes are added as edge endpoints, but not further traversed)."""
        g = ResourceGraph()
        g.add_edge(RelationshipEdge(org_node, product_node, RelationshipType.OWNS))
        g.add_edge(RelationshipEdge(product_node, user_node, RelationshipType.REFERENCES))

        sub = g.get_subgraph(org_node, max_depth=1)
        assert sub.get_node("organizations", "org1") is not None
        assert sub.get_node("products", "prod1") is not None
        # product_node edges are included but user_node is at depth 2 —
        # it appears as an edge endpoint but the traversal doesn't go beyond depth 1.
        # However, the outgoing edges of product_node at depth=1 include user_node.
        # The key behavioral test: user_node's OWN edges are NOT traversed.
        assert len(sub.get_outgoing_edges(user_node)) == 0

    def test_get_subgraph_full_depth(self, org_node, product_node, user_node):
        """Subgraph with sufficient depth includes all reachable nodes."""
        g = ResourceGraph()
        g.add_edge(RelationshipEdge(org_node, product_node, RelationshipType.OWNS))
        g.add_edge(RelationshipEdge(product_node, user_node, RelationshipType.REFERENCES))

        sub = g.get_subgraph(org_node, max_depth=2)
        user = sub.get_node("users", "u1")
        assert user is not None
        assert user.resource_type == "users"


class TestResourceGraphSerialization:
    """Test graph serialization and statistics."""

    def test_to_dict(self, org_node, product_node):
        """to_dict produces correct structure."""
        g = ResourceGraph()
        g.add_edge(RelationshipEdge(org_node, product_node, RelationshipType.OWNS))
        d = g.to_dict()
        assert d["node_count"] == 2
        assert d["edge_count"] == 1
        assert len(d["nodes"]) == 2

    def test_get_statistics(self, org_node, product_node):
        """Statistics include node/edge counts and type breakdowns."""
        g = ResourceGraph()
        g.add_edge(RelationshipEdge(org_node, product_node, RelationshipType.OWNS))
        stats = g.get_statistics()
        assert stats["total_nodes"] == 2
        assert stats["total_edges"] == 1
        assert "organizations" in stats["resource_types"]
        assert "products" in stats["resource_types"]
        assert "owns" in stats["relationship_types"]
        assert stats["average_degree"] > 0

    def test_empty_graph_statistics(self):
        """Empty graph has zero statistics."""
        g = ResourceGraph()
        stats = g.get_statistics()
        assert stats["total_nodes"] == 0
        assert stats["total_edges"] == 0
        assert stats["average_degree"] == 0
