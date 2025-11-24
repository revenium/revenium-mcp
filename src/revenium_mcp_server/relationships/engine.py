"""Resource Relationship Engine.

This module provides the central engine for managing resource relationships,
including discovery, validation, and querying capabilities.
"""

import asyncio
from typing import Any, Dict, List, Optional

from loguru import logger

from .discovery import ResourceRelationshipDiscovery
from .graph import RelationshipEdge, RelationshipType
from .validation import CrossResourceValidator


class ResourceRelationshipEngine:
    """Central engine for managing resource relationships."""

    def __init__(self):
        """Initialize the relationship engine."""
        self.discovery = ResourceRelationshipDiscovery()
        self.validator = CrossResourceValidator()
        self._lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the relationship engine."""
        if self._initialized:
            return

        logger.info("Initializing Resource Relationship Engine")

        # Initialize components
        await self.validator.initialize()

        self._initialized = True
        logger.info("Resource Relationship Engine initialized successfully")

    async def add_resource(
        self, resource_type: str, resource_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Add a resource and discover its relationships.

        Args:
            resource_type: Type of the resource
            resource_data: Resource data dictionary

        Returns:
            Result dictionary with relationship information
        """
        async with self._lock:
            try:
                # Add resource to discovery engine
                self.discovery.add_resource(resource_type, resource_data)

                # Get the resource ID
                resource_id = resource_data.get("id") or resource_data.get("resource_id", "unknown")

                # Get discovered relationships
                relationships = self.discovery.get_resource_relationships(
                    resource_type, str(resource_id)
                )

                logger.info(f"Added resource {resource_type}:{resource_id} with relationships")

                return {
                    "success": True,
                    "resource_type": resource_type,
                    "resource_id": str(resource_id),
                    "relationships": relationships,
                    "message": f"Resource {resource_type}:{resource_id} added successfully",
                }

            except Exception as e:
                logger.error(f"Error adding resource {resource_type}: {e}")
                return {
                    "success": False,
                    "error": str(e),
                    "message": f"Failed to add resource {resource_type}",
                }

    async def get_resource_relationships(
        self, resource_type: str, resource_id: str
    ) -> Dict[str, Any]:
        """Get all relationships for a specific resource.

        Args:
            resource_type: Type of the resource
            resource_id: ID of the resource

        Returns:
            Dictionary containing relationship information
        """
        try:
            relationships = self.discovery.get_resource_relationships(resource_type, resource_id)

            if "error" in relationships:
                return {
                    "success": False,
                    "error": relationships["error"],
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                }

            return {
                "success": True,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "relationships": relationships,
            }

        except Exception as e:
            logger.error(f"Error getting relationships for {resource_type}:{resource_id}: {e}")
            return {
                "success": False,
                "error": str(e),
                "resource_type": resource_type,
                "resource_id": resource_id,
            }

    async def find_related_resources(
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
        try:
            related = self.discovery.find_related_resources(
                resource_type, resource_id, relationship_types, max_depth
            )

            if "error" in related:
                return {
                    "success": False,
                    "error": related["error"],
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                }

            return {
                "success": True,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "related_resources": related,
            }

        except Exception as e:
            logger.error(f"Error finding related resources for {resource_type}:{resource_id}: {e}")
            return {
                "success": False,
                "error": str(e),
                "resource_type": resource_type,
                "resource_id": resource_id,
            }

    async def validate_cross_resource_operation(self, operation: Dict[str, Any]) -> Dict[str, Any]:
        """Validate a cross-resource operation.

        Args:
            operation: Operation to validate

        Returns:
            Validation result
        """
        try:
            result = await self.validator.validate_operation(operation)
            return {"success": True, "validation_result": result}

        except Exception as e:
            logger.error(f"Error validating cross-resource operation: {e}")
            return {"success": False, "error": str(e), "operation": operation}

    async def get_dependency_graph(self) -> Dict[str, Any]:
        """Get the complete resource dependency graph.

        Returns:
            Dictionary containing the dependency graph
        """
        try:
            graph_dict = self.discovery.graph.to_dict()
            statistics = self.discovery.graph.get_statistics()

            return {
                "success": True,
                "graph": graph_dict,
                "statistics": statistics,
                "summary": self.discovery.get_relationship_summary(),
            }

        except Exception as e:
            logger.error(f"Error getting dependency graph: {e}")
            return {"success": False, "error": str(e)}

    async def get_relationship_patterns(self) -> Dict[str, Any]:
        """Get available relationship patterns.

        Returns:
            Dictionary containing relationship patterns
        """
        try:
            patterns = self.discovery._relationship_patterns

            # Format patterns for agent consumption
            formatted_patterns = {}
            for resource_type, pattern_data in patterns.items():
                formatted_patterns[resource_type] = {
                    "supported_relationships": list(pattern_data.keys()),
                    "field_mappings": {
                        field: {"target_type": target_type, "relationship_type": rel_type.value}
                        for field, (target_type, rel_type) in pattern_data.get(
                            "field_mappings", {}
                        ).items()
                    },
                }

            return {
                "success": True,
                "patterns": formatted_patterns,
                "available_relationship_types": [rt.value for rt in RelationshipType],
                "total_patterns": len(patterns),
            }

        except Exception as e:
            logger.error(f"Error getting relationship patterns: {e}")
            return {"success": False, "error": str(e)}

    async def analyze_resource_impact(
        self, resource_type: str, resource_id: str, operation: str = "delete"
    ) -> Dict[str, Any]:
        """Analyze the impact of an operation on a resource.

        Args:
            resource_type: Type of the resource
            resource_id: ID of the resource
            operation: Operation to analyze (delete, update, etc.)

        Returns:
            Impact analysis result
        """
        try:
            # Get the resource node
            node = self.discovery.graph.get_node(resource_type, resource_id)
            if not node:
                return {
                    "success": False,
                    "error": f"Resource {resource_type}:{resource_id} not found",
                }

            # Get incoming relationships (resources that depend on this one)
            incoming_edges = self.discovery.graph.get_incoming_edges(node)

            # Get outgoing relationships (resources this one depends on)
            outgoing_edges = self.discovery.graph.get_outgoing_edges(node)

            # Analyze impact based on operation
            impact_analysis = {
                "resource": node.to_dict(),
                "operation": operation,
                "dependent_resources": [
                    {
                        "resource": edge.source_node.to_dict(),
                        "relationship_type": edge.relationship_type.value,
                        "strength": edge.strength.value,
                        "impact_level": self._assess_impact_level(edge, operation),
                    }
                    for edge in incoming_edges
                ],
                "dependency_resources": [
                    {
                        "resource": edge.target_node.to_dict(),
                        "relationship_type": edge.relationship_type.value,
                        "strength": edge.strength.value,
                        "impact_level": self._assess_impact_level(edge, operation),
                    }
                    for edge in outgoing_edges
                ],
                "total_affected_resources": len(incoming_edges) + len(outgoing_edges),
                "high_impact_count": len(
                    [
                        edge
                        for edge in incoming_edges + outgoing_edges
                        if self._assess_impact_level(edge, operation) == "high"
                    ]
                ),
            }

            return {"success": True, "impact_analysis": impact_analysis}

        except Exception as e:
            logger.error(f"Error analyzing resource impact for {resource_type}:{resource_id}: {e}")
            return {
                "success": False,
                "error": str(e),
                "resource_type": resource_type,
                "resource_id": resource_id,
            }

    def _assess_impact_level(self, edge: RelationshipEdge, operation: str) -> str:
        """Assess the impact level of an operation on a relationship.

        Args:
            edge: Relationship edge
            operation: Operation being performed

        Returns:
            Impact level (low, medium, high)
        """
        if operation == "delete":
            # Deletion has higher impact on critical relationships
            if edge.strength.value == "critical":
                return "high"
            elif edge.strength.value == "strong":
                return "medium"
            else:
                return "low"
        elif operation == "update":
            # Updates generally have lower impact
            if edge.strength.value == "critical":
                return "medium"
            else:
                return "low"
        else:
            return "low"

    async def get_navigation_path(
        self,
        from_resource_type: str,
        from_resource_id: str,
        to_resource_type: str,
        to_resource_id: str,
    ) -> Dict[str, Any]:
        """Find a navigation path between two resources.

        Args:
            from_resource_type: Source resource type
            from_resource_id: Source resource ID
            to_resource_type: Target resource type
            to_resource_id: Target resource ID

        Returns:
            Navigation path result
        """
        try:
            from_node = self.discovery.graph.get_node(from_resource_type, from_resource_id)
            to_node = self.discovery.graph.get_node(to_resource_type, to_resource_id)

            if not from_node:
                return {
                    "success": False,
                    "error": f"Source resource {from_resource_type}:{from_resource_id} not found",
                }

            if not to_node:
                return {
                    "success": False,
                    "error": f"Target resource {to_resource_type}:{to_resource_id} not found",
                }

            # Find path
            path = self.discovery.graph.find_path(from_node, to_node)

            if path is None:
                return {
                    "success": True,
                    "path_found": False,
                    "message": f"No path found between {from_resource_type}:{from_resource_id} and {to_resource_type}:{to_resource_id}",
                }

            # Format path for agent consumption
            formatted_path = [
                {
                    "step": i + 1,
                    "from": edge.source_node.to_dict(),
                    "to": edge.target_node.to_dict(),
                    "relationship": edge.relationship_type.value,
                    "strength": edge.strength.value,
                }
                for i, edge in enumerate(path)
            ]

            return {
                "success": True,
                "path_found": True,
                "path_length": len(path),
                "navigation_path": formatted_path,
                "from_resource": from_node.to_dict(),
                "to_resource": to_node.to_dict(),
            }

        except Exception as e:
            logger.error(f"Error finding navigation path: {e}")
            return {"success": False, "error": str(e)}


# Global relationship engine instance
relationship_engine = ResourceRelationshipEngine()
