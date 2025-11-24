"""Resource Relationship Discovery Framework.

This package provides comprehensive resource relationship discovery and mapping
capabilities for the Revenium MCP server, enabling agents to understand how
different resources relate to each other.
"""

from .discovery import ResourceRelationshipDiscovery, relationship_discovery
from .engine import ResourceRelationshipEngine, relationship_engine
from .graph import RelationshipEdge, ResourceGraph, ResourceNode
from .validation import CrossResourceValidator, relationship_validator

__all__ = [
    "ResourceRelationshipDiscovery",
    "relationship_discovery",
    "ResourceGraph",
    "ResourceNode",
    "RelationshipEdge",
    "ResourceRelationshipEngine",
    "relationship_engine",
    "CrossResourceValidator",
    "relationship_validator",
]
