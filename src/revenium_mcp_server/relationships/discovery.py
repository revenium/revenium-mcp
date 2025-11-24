"""Resource Relationship Discovery.

This module provides automated discovery of resource relationships
based on API patterns and data model analysis.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from .graph import (
    RelationshipEdge,
    RelationshipStrength,
    RelationshipType,
    ResourceGraph,
    ResourceNode,
)


class ResourceRelationshipDiscovery:
    """Discovers and maps resource relationships in the Revenium platform."""

    def __init__(self):
        """Initialize the relationship discovery engine."""
        self.graph = ResourceGraph()
        self._relationship_patterns = self._initialize_relationship_patterns()

    def _initialize_relationship_patterns(self) -> Dict[str, Dict[str, Any]]:
        """Initialize known relationship patterns based on API analysis.

        Returns:
            Dictionary of relationship patterns
        """
        return {
            # Product relationships
            "products": {
                "owns": ["subscriptions"],
                "references": ["sources", "organizations", "teams"],
                "configures": ["alerts"],
                "depends_on": ["organizations"],
                "field_mappings": {
                    "source_ids": ("sources", RelationshipType.REFERENCES),
                    "organization_id": ("organizations", RelationshipType.BELONGS_TO),
                    "team_id": ("teams", RelationshipType.BELONGS_TO),
                },
            },
            # Subscription relationships
            "subscriptions": {
                "belongs_to": ["products", "users", "organizations"],
                "references": ["teams"],
                "field_mappings": {
                    "product_id": ("products", RelationshipType.BELONGS_TO),
                    "user_id": ("users", RelationshipType.BELONGS_TO),
                    "organization_id": ("organizations", RelationshipType.BELONGS_TO),
                    "team_id": ("teams", RelationshipType.REFERENCES),
                },
            },
            # Source relationships
            "sources": {
                "belongs_to": ["organizations", "teams"],
                "monitors": ["products"],
                "configures": ["alerts"],
                "field_mappings": {
                    "organization_id": ("organizations", RelationshipType.BELONGS_TO),
                    "team_id": ("teams", RelationshipType.BELONGS_TO),
                },
            },
            # User relationships
            "users": {
                "belongs_to": ["organizations"],
                "manages": ["teams"],
                "owns": ["subscriptions"],
                "field_mappings": {
                    "organization_id": ("organizations", RelationshipType.BELONGS_TO),
                    "team_ids": ("teams", RelationshipType.MANAGES),
                    "subscription_ids": ("subscriptions", RelationshipType.OWNS),
                },
            },
            # Organization relationships
            "organizations": {
                "contains": ["teams", "users"],
                "owns": ["products", "sources", "subscriptions"],
                "manages": ["alerts"],
                "field_mappings": {},
            },
            # Team relationships
            "teams": {
                "belongs_to": ["organizations"],
                "manages": ["products", "sources", "users"],
                "configures": ["alerts"],
                "field_mappings": {
                    "organization_id": ("organizations", RelationshipType.BELONGS_TO),
                    "member_ids": ("users", RelationshipType.CONTAINS),
                },
            },
            # Alert relationships
            "alerts": {
                "monitors": ["products", "sources"],
                "belongs_to": ["organizations", "teams"],
                "references": ["users"],
                "field_mappings": {
                    "product_id": ("products", RelationshipType.MONITORS),
                    "source_id": ("sources", RelationshipType.MONITORS),
                    "organization_id": ("organizations", RelationshipType.BELONGS_TO),
                    "team_id": ("teams", RelationshipType.BELONGS_TO),
                    "user_id": ("users", RelationshipType.REFERENCES),
                },
            },
        }

    def discover_relationships_from_data(
        self, resource_type: str, resource_data: Dict[str, Any]
    ) -> List[RelationshipEdge]:
        """Discover relationships from resource data.

        Args:
            resource_type: Type of the resource
            resource_data: Resource data dictionary

        Returns:
            List of discovered relationship edges
        """
        relationships = []

        if resource_type not in self._relationship_patterns:
            logger.warning(f"No relationship patterns defined for resource type: {resource_type}")
            return relationships

        patterns = self._relationship_patterns[resource_type]
        source_node = self._create_node_from_data(resource_type, resource_data)

        # Process field mappings
        field_mappings = patterns.get("field_mappings", {})
        for field_name, (target_type, relationship_type) in field_mappings.items():
            field_value = resource_data.get(field_name)

            if field_value:
                if isinstance(field_value, list):
                    # Handle list of IDs
                    for target_id in field_value:
                        if target_id:
                            target_node = ResourceNode(
                                resource_type=target_type, resource_id=str(target_id)
                            )
                            edge = RelationshipEdge(
                                source_node=source_node,
                                target_node=target_node,
                                relationship_type=relationship_type,
                                strength=self._determine_relationship_strength(relationship_type),
                                created_at=datetime.now(),
                            )
                            relationships.append(edge)
                else:
                    # Handle single ID
                    target_node = ResourceNode(
                        resource_type=target_type, resource_id=str(field_value)
                    )
                    edge = RelationshipEdge(
                        source_node=source_node,
                        target_node=target_node,
                        relationship_type=relationship_type,
                        strength=self._determine_relationship_strength(relationship_type),
                        created_at=datetime.now(),
                    )
                    relationships.append(edge)

        return relationships

    def _create_node_from_data(
        self, resource_type: str, resource_data: Dict[str, Any]
    ) -> ResourceNode:
        """Create a resource node from data.

        Args:
            resource_type: Type of the resource
            resource_data: Resource data dictionary

        Returns:
            Resource node
        """
        resource_id = resource_data.get("id") or resource_data.get("resource_id", "unknown")
        name = resource_data.get("name") or resource_data.get("title")
        status = resource_data.get("status")

        # Extract creation/update timestamps
        created_at = None
        updated_at = None

        if "created_at" in resource_data:
            created_at = self._parse_timestamp(resource_data["created_at"])
        if "updated_at" in resource_data:
            updated_at = self._parse_timestamp(resource_data["updated_at"])

        return ResourceNode(
            resource_type=resource_type,
            resource_id=str(resource_id),
            name=name,
            status=status,
            metadata=resource_data,
            created_at=created_at,
            updated_at=updated_at,
        )

    def _parse_timestamp(self, timestamp_value: Any) -> Optional[datetime]:
        """Parse timestamp from various formats.

        Args:
            timestamp_value: Timestamp value to parse

        Returns:
            Parsed datetime or None
        """
        if isinstance(timestamp_value, datetime):
            return timestamp_value

        if isinstance(timestamp_value, str):
            try:
                # Try ISO format first
                return datetime.fromisoformat(timestamp_value.replace("Z", "+00:00"))
            except ValueError:
                try:
                    # Try other common formats
                    return datetime.strptime(timestamp_value, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    logger.warning(f"Could not parse timestamp: {timestamp_value}")
                    return None

        return None

    def _determine_relationship_strength(
        self, relationship_type: RelationshipType
    ) -> RelationshipStrength:
        """Determine relationship strength based on type.

        Args:
            relationship_type: Type of relationship

        Returns:
            Relationship strength
        """
        strength_mapping = {
            RelationshipType.BELONGS_TO: RelationshipStrength.CRITICAL,
            RelationshipType.OWNS: RelationshipStrength.STRONG,
            RelationshipType.DEPENDS_ON: RelationshipStrength.STRONG,
            RelationshipType.MANAGES: RelationshipStrength.STRONG,
            RelationshipType.CONTAINS: RelationshipStrength.MEDIUM,
            RelationshipType.MONITORS: RelationshipStrength.MEDIUM,
            RelationshipType.CONFIGURES: RelationshipStrength.MEDIUM,
            RelationshipType.REFERENCES: RelationshipStrength.WEAK,
            RelationshipType.SUBSCRIBES_TO: RelationshipStrength.MEDIUM,
            RelationshipType.CREATES: RelationshipStrength.STRONG,
        }

        return strength_mapping.get(relationship_type, RelationshipStrength.MEDIUM)

    def add_resource(self, resource_type: str, resource_data: Dict[str, Any]) -> None:
        """Add a resource and discover its relationships.

        Args:
            resource_type: Type of the resource
            resource_data: Resource data dictionary
        """
        # Create and add the main node
        node = self._create_node_from_data(resource_type, resource_data)
        self.graph.add_node(node)

        # Discover and add relationships
        relationships = self.discover_relationships_from_data(resource_type, resource_data)
        for edge in relationships:
            self.graph.add_edge(edge)

        logger.debug(
            f"Added resource {resource_type}:{node.resource_id} with {len(relationships)} relationships"
        )

    def get_resource_relationships(self, resource_type: str, resource_id: str) -> Dict[str, Any]:
        """Get all relationships for a specific resource.

        Args:
            resource_type: Type of the resource
            resource_id: ID of the resource

        Returns:
            Dictionary containing relationship information
        """
        node = self.graph.get_node(resource_type, resource_id)
        if not node:
            return {"error": f"Resource {resource_type}:{resource_id} not found"}

        outgoing_edges = self.graph.get_outgoing_edges(node)
        incoming_edges = self.graph.get_incoming_edges(node)

        return {
            "resource": node.to_dict(),
            "outgoing_relationships": [edge.to_dict() for edge in outgoing_edges],
            "incoming_relationships": [edge.to_dict() for edge in incoming_edges],
            "related_resources": {
                "owns": [
                    edge.target_node.to_dict()
                    for edge in outgoing_edges
                    if edge.relationship_type == RelationshipType.OWNS
                ],
                "belongs_to": [
                    edge.target_node.to_dict()
                    for edge in outgoing_edges
                    if edge.relationship_type == RelationshipType.BELONGS_TO
                ],
                "references": [
                    edge.target_node.to_dict()
                    for edge in outgoing_edges
                    if edge.relationship_type == RelationshipType.REFERENCES
                ],
                "manages": [
                    edge.target_node.to_dict()
                    for edge in outgoing_edges
                    if edge.relationship_type == RelationshipType.MANAGES
                ],
            },
        }

    def get_relationship_summary(self) -> Dict[str, Any]:
        """Get a summary of all relationships in the graph.

        Returns:
            Relationship summary dictionary
        """
        return {
            "graph_statistics": self.graph.get_statistics(),
            "relationship_patterns": list(self._relationship_patterns.keys()),
            "total_resources": len(self.graph.nodes),
            "total_relationships": len(self.graph.edges),
        }

    def find_related_resources(
        self,
        resource_type: str,
        resource_id: str,
        relationship_types: Optional[List[str]] = None,
        max_depth: int = 2,
    ) -> Dict[str, Any]:
        """Find resources related to the given resource.

        Args:
            resource_type: Type of the source resource
            resource_id: ID of the source resource
            relationship_types: Filter by relationship types
            max_depth: Maximum depth to search

        Returns:
            Dictionary containing related resources
        """
        node = self.graph.get_node(resource_type, resource_id)
        if not node:
            return {"error": f"Resource {resource_type}:{resource_id} not found"}

        # Convert string relationship types to enum
        rel_type_enums = None
        if relationship_types:
            rel_type_enums = []
            for rel_type in relationship_types:
                try:
                    rel_type_enums.append(RelationshipType(rel_type))
                except ValueError:
                    logger.warning(f"Unknown relationship type: {rel_type}")

        # Get subgraph
        subgraph = self.graph.get_subgraph(node, max_depth)

        return {
            "source_resource": node.to_dict(),
            "related_graph": subgraph.to_dict(),
            "search_depth": max_depth,
            "relationship_types_filter": relationship_types,
        }


# Global discovery instance
relationship_discovery = ResourceRelationshipDiscovery()
