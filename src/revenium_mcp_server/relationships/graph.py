"""Resource Graph Data Structures.

This module provides graph data structures for representing and navigating
resource relationships in the Revenium platform.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class RelationshipType(Enum):
    """Types of relationships between resources."""

    OWNS = "owns"
    BELONGS_TO = "belongs_to"
    REFERENCES = "references"
    DEPENDS_ON = "depends_on"
    CREATES = "creates"
    MONITORS = "monitors"
    CONFIGURES = "configures"
    SUBSCRIBES_TO = "subscribes_to"
    MANAGES = "manages"
    CONTAINS = "contains"


class RelationshipStrength(Enum):
    """Strength of relationships between resources."""

    WEAK = "weak"
    MEDIUM = "medium"
    STRONG = "strong"
    CRITICAL = "critical"


@dataclass
class ResourceNode:
    """Represents a resource node in the relationship graph."""

    resource_type: str
    resource_id: str
    name: Optional[str] = None
    status: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def __hash__(self) -> int:
        """Make node hashable for use in sets and as dict keys."""
        return hash((self.resource_type, self.resource_id))

    def __eq__(self, other) -> bool:
        """Check equality based on resource type and ID."""
        if not isinstance(other, ResourceNode):
            return False
        return self.resource_type == other.resource_type and self.resource_id == other.resource_id

    def to_dict(self) -> Dict[str, Any]:
        """Convert node to dictionary representation."""
        return {
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "name": self.name,
            "status": self.status,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


@dataclass
class RelationshipEdge:
    """Represents a relationship edge between two resource nodes."""

    source_node: ResourceNode
    target_node: ResourceNode
    relationship_type: RelationshipType
    strength: RelationshipStrength = RelationshipStrength.MEDIUM
    bidirectional: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None

    def __hash__(self) -> int:
        """Make edge hashable for use in sets."""
        return hash((self.source_node, self.target_node, self.relationship_type))

    def __eq__(self, other) -> bool:
        """Check equality based on nodes and relationship type."""
        if not isinstance(other, RelationshipEdge):
            return False
        return (
            self.source_node == other.source_node
            and self.target_node == other.target_node
            and self.relationship_type == other.relationship_type
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert edge to dictionary representation."""
        return {
            "source": self.source_node.to_dict(),
            "target": self.target_node.to_dict(),
            "relationship_type": self.relationship_type.value,
            "strength": self.strength.value,
            "bidirectional": self.bidirectional,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ResourceGraph:
    """Graph structure for managing resource relationships."""

    def __init__(self):
        """Initialize an empty resource graph."""
        self.nodes: Dict[Tuple[str, str], ResourceNode] = {}
        self.edges: Set[RelationshipEdge] = set()
        self.adjacency_list: Dict[ResourceNode, List[RelationshipEdge]] = {}
        self.reverse_adjacency_list: Dict[ResourceNode, List[RelationshipEdge]] = {}

    def add_node(self, node: ResourceNode) -> None:
        """Add a node to the graph.

        Args:
            node: Resource node to add
        """
        key = (node.resource_type, node.resource_id)
        self.nodes[key] = node
        if node not in self.adjacency_list:
            self.adjacency_list[node] = []
        if node not in self.reverse_adjacency_list:
            self.reverse_adjacency_list[node] = []

    def add_edge(self, edge: RelationshipEdge) -> None:
        """Add an edge to the graph.

        Args:
            edge: Relationship edge to add
        """
        # Ensure nodes exist
        self.add_node(edge.source_node)
        self.add_node(edge.target_node)

        # Add edge
        self.edges.add(edge)
        self.adjacency_list[edge.source_node].append(edge)
        self.reverse_adjacency_list[edge.target_node].append(edge)

        # Add reverse edge if bidirectional
        if edge.bidirectional:
            reverse_edge = RelationshipEdge(
                source_node=edge.target_node,
                target_node=edge.source_node,
                relationship_type=edge.relationship_type,
                strength=edge.strength,
                bidirectional=False,  # Avoid infinite recursion
                metadata=edge.metadata,
                created_at=edge.created_at,
            )
            self.edges.add(reverse_edge)
            self.adjacency_list[edge.target_node].append(reverse_edge)
            self.reverse_adjacency_list[edge.source_node].append(reverse_edge)

    def get_node(self, resource_type: str, resource_id: str) -> Optional[ResourceNode]:
        """Get a node by resource type and ID.

        Args:
            resource_type: Type of resource
            resource_id: ID of resource

        Returns:
            Resource node or None if not found
        """
        return self.nodes.get((resource_type, resource_id))

    def get_outgoing_edges(self, node: ResourceNode) -> List[RelationshipEdge]:
        """Get all outgoing edges from a node.

        Args:
            node: Source node

        Returns:
            List of outgoing edges
        """
        return self.adjacency_list.get(node, [])

    def get_incoming_edges(self, node: ResourceNode) -> List[RelationshipEdge]:
        """Get all incoming edges to a node.

        Args:
            node: Target node

        Returns:
            List of incoming edges
        """
        return self.reverse_adjacency_list.get(node, [])

    def get_related_nodes(
        self,
        node: ResourceNode,
        relationship_types: Optional[List[RelationshipType]] = None,
        direction: str = "both",
    ) -> List[ResourceNode]:
        """Get nodes related to the given node.

        Args:
            node: Source node
            relationship_types: Filter by relationship types
            direction: Direction to search ("outgoing", "incoming", "both")

        Returns:
            List of related nodes
        """
        related_nodes = []

        if direction in ("outgoing", "both"):
            for edge in self.get_outgoing_edges(node):
                if not relationship_types or edge.relationship_type in relationship_types:
                    related_nodes.append(edge.target_node)

        if direction in ("incoming", "both"):
            for edge in self.get_incoming_edges(node):
                if not relationship_types or edge.relationship_type in relationship_types:
                    related_nodes.append(edge.source_node)

        return related_nodes

    def find_path(
        self, start_node: ResourceNode, end_node: ResourceNode, max_depth: int = 5
    ) -> Optional[List[RelationshipEdge]]:
        """Find a path between two nodes using BFS.

        Args:
            start_node: Starting node
            end_node: Target node
            max_depth: Maximum search depth

        Returns:
            List of edges forming the path, or None if no path found
        """
        if start_node == end_node:
            return []

        queue = [(start_node, [])]
        visited = {start_node}

        while queue:
            current_node, path = queue.pop(0)

            if len(path) >= max_depth:
                continue

            for edge in self.get_outgoing_edges(current_node):
                if edge.target_node not in visited:
                    new_path = path + [edge]

                    if edge.target_node == end_node:
                        return new_path

                    visited.add(edge.target_node)
                    queue.append((edge.target_node, new_path))

        return None

    def get_subgraph(self, root_node: ResourceNode, max_depth: int = 2) -> "ResourceGraph":
        """Get a subgraph starting from a root node.

        Args:
            root_node: Root node for subgraph
            max_depth: Maximum depth to traverse

        Returns:
            New ResourceGraph containing the subgraph
        """
        subgraph = ResourceGraph()
        visited = set()
        queue = [(root_node, 0)]

        while queue:
            current_node, depth = queue.pop(0)

            if current_node in visited or depth > max_depth:
                continue

            visited.add(current_node)
            subgraph.add_node(current_node)

            # Add outgoing edges and nodes
            for edge in self.get_outgoing_edges(current_node):
                subgraph.add_edge(edge)
                if depth < max_depth:
                    queue.append((edge.target_node, depth + 1))

        return subgraph

    def to_dict(self) -> Dict[str, Any]:
        """Convert graph to dictionary representation.

        Returns:
            Dictionary representation of the graph
        """
        return {
            "nodes": [node.to_dict() for node in self.nodes.values()],
            "edges": [edge.to_dict() for edge in self.edges],
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
        }

    def get_statistics(self) -> Dict[str, Any]:
        """Get graph statistics.

        Returns:
            Dictionary containing graph statistics
        """
        resource_type_counts = {}
        relationship_type_counts = {}

        for node in self.nodes.values():
            resource_type_counts[node.resource_type] = (
                resource_type_counts.get(node.resource_type, 0) + 1
            )

        for edge in self.edges:
            rel_type = edge.relationship_type.value
            relationship_type_counts[rel_type] = relationship_type_counts.get(rel_type, 0) + 1

        return {
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
            "resource_types": resource_type_counts,
            "relationship_types": relationship_type_counts,
            "average_degree": len(self.edges) * 2 / len(self.nodes) if self.nodes else 0,
        }
