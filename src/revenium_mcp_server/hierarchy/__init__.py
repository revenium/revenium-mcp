"""Hierarchy Management Package for Revenium MCP Server.

This package provides comprehensive hierarchy management capabilities for the
three-tier structure: Products → Subscriptions → Subscriber Credentials.

The package includes:
- HierarchyNavigationService: Bidirectional navigation and relationship traversal
- EntityLookupService: Multi-strategy entity resolution and lookup
- CrossTierValidator: Data integrity validation across hierarchy levels
- MultiEntityNLPProcessor: Natural language processing for complex queries
- CrossToolIntegrator: Workflow coordination across multiple MCP tools
"""

from .navigation_service import (
    HierarchyNavigationService,
    HierarchyPath,
    NavigationResult,
    get_hierarchy_navigation_service,
)


# For backward compatibility
def hierarchy_navigation_service():
    """Get the hierarchy navigation service instance."""
    return get_hierarchy_navigation_service()


from .entity_lookup_service import (
    EntityLookupService,
    EntityReference,
    LookupResult,
    get_entity_lookup_service,
)


# For backward compatibility
def entity_lookup_service():
    """Get the entity lookup service instance."""
    return get_entity_lookup_service()


from .cross_tier_validator import (
    CrossTierValidator,
    ImpactAnalysis,
    OperationType,
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
    get_cross_tier_validator,
)


# For backward compatibility
def cross_tier_validator():
    """Get the cross tier validator instance."""
    return get_cross_tier_validator()


from .multi_entity_nlp_processor import (
    ActionType,
    EntityMention,
    EntityType,
    ExecutionPlan,
    ExecutionResult,
    MultiEntityNLPProcessor,
    NLPResult,
    ParsedAction,
    ParsedQuery,
    QueryType,
    WorkflowStep,
    get_multi_entity_nlp_processor,
)


# For backward compatibility
def multi_entity_nlp_processor():
    """Get the multi entity NLP processor instance."""
    return get_multi_entity_nlp_processor()


__all__ = [
    "HierarchyNavigationService",
    "NavigationResult",
    "HierarchyPath",
    "hierarchy_navigation_service",
    "EntityLookupService",
    "LookupResult",
    "EntityReference",
    "entity_lookup_service",
    "CrossTierValidator",
    "ValidationResult",
    "ValidationIssue",
    "ImpactAnalysis",
    "ValidationSeverity",
    "OperationType",
    "cross_tier_validator",
    "MultiEntityNLPProcessor",
    "ParsedQuery",
    "ExecutionPlan",
    "NLPResult",
    "ExecutionResult",
    "QueryType",
    "EntityType",
    "ActionType",
    "EntityMention",
    "ParsedAction",
    "WorkflowStep",
    "multi_entity_nlp_processor",
]
