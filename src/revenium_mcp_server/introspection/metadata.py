"""Tool metadata definitions and interfaces.

This module defines the core data structures and interfaces for tool metadata
representation in the MCP server introspection framework.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


class ToolType(Enum):
    """Tool type classification."""

    CRUD = "crud"
    WORKFLOW = "workflow"
    ANALYTICS = "analytics"
    UTILITY = "utility"


class DependencyType(Enum):
    """Dependency relationship types."""

    REQUIRES = "requires"
    ENHANCES = "enhances"
    CONFLICTS = "conflicts"
    OPTIONAL = "optional"
    MONITORS = "monitors"
    CREATES = "creates"  # Added for customer management tool


@dataclass
class PerformanceMetrics:
    """Performance metrics for a tool."""

    avg_response_time_ms: float = 0.0
    success_rate: float = 1.0
    total_executions: int = 0
    error_count: int = 0
    last_execution: Optional[datetime] = None
    peak_response_time_ms: float = 0.0
    min_response_time_ms: float = 0.0


@dataclass
class UsagePattern:
    """Usage pattern information for a tool."""

    pattern_name: str
    description: str
    frequency: float  # 0.0 to 1.0
    typical_sequence: List[str] = field(default_factory=list)
    common_parameters: Dict[str, Any] = field(default_factory=dict)
    success_indicators: List[str] = field(default_factory=list)


@dataclass
class ToolDependency:
    """Tool dependency information."""

    tool_name: str
    dependency_type: DependencyType
    description: str
    required_version: Optional[str] = None
    conditional: bool = False


@dataclass
class ResourceRelationship:
    """Resource relationship information."""

    resource_type: str
    relationship_type: str  # creates, requires, affects, references
    description: str
    cardinality: str = "1:N"  # 1:1, 1:N, N:N
    optional: bool = False


@dataclass
class ToolCapability:
    """Tool capability information."""

    name: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    examples: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)


@dataclass
class ToolMetadata:
    """Comprehensive tool metadata."""

    # Basic information
    name: str
    description: str
    version: str
    tool_type: ToolType

    # Capabilities and schema
    capabilities: List[ToolCapability] = field(default_factory=list)
    supported_actions: List[str] = field(default_factory=list)
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)

    # Dependencies and relationships
    dependencies: List[ToolDependency] = field(default_factory=list)
    resource_relationships: List[ResourceRelationship] = field(default_factory=list)

    # Usage and performance
    usage_patterns: List[UsagePattern] = field(default_factory=list)
    performance_metrics: PerformanceMetrics = field(default_factory=PerformanceMetrics)

    # Agent-friendly features
    agent_summary: str = ""
    quick_start_guide: List[str] = field(default_factory=list)
    common_use_cases: List[str] = field(default_factory=list)
    troubleshooting_tips: List[str] = field(default_factory=list)

    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to dictionary format."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "tool_type": self.tool_type.value,
            "capabilities": [
                {
                    "name": cap.name,
                    "description": cap.description,
                    "parameters": cap.parameters,
                    "examples": cap.examples,
                    "limitations": cap.limitations,
                }
                for cap in self.capabilities
            ],
            "supported_actions": self.supported_actions,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "dependencies": [
                {
                    "tool_name": dep.tool_name,
                    "dependency_type": dep.dependency_type.value,
                    "description": dep.description,
                    "required_version": dep.required_version,
                    "conditional": dep.conditional,
                }
                for dep in self.dependencies
            ],
            "resource_relationships": [
                {
                    "resource_type": rel.resource_type,
                    "relationship_type": rel.relationship_type,
                    "description": rel.description,
                    "cardinality": rel.cardinality,
                    "optional": rel.optional,
                }
                for rel in self.resource_relationships
            ],
            "usage_patterns": [
                {
                    "pattern_name": pattern.pattern_name,
                    "description": pattern.description,
                    "frequency": pattern.frequency,
                    "typical_sequence": pattern.typical_sequence,
                    "common_parameters": pattern.common_parameters,
                    "success_indicators": pattern.success_indicators,
                }
                for pattern in self.usage_patterns
            ],
            "performance_metrics": {
                "avg_response_time_ms": self.performance_metrics.avg_response_time_ms,
                "success_rate": self.performance_metrics.success_rate,
                "total_executions": self.performance_metrics.total_executions,
                "error_count": self.performance_metrics.error_count,
                "last_execution": (
                    self.performance_metrics.last_execution.isoformat()
                    if self.performance_metrics.last_execution
                    else None
                ),
                "peak_response_time_ms": self.performance_metrics.peak_response_time_ms,
                "min_response_time_ms": self.performance_metrics.min_response_time_ms,
            },
            "agent_summary": self.agent_summary,
            "quick_start_guide": self.quick_start_guide,
            "common_use_cases": self.common_use_cases,
            "troubleshooting_tips": self.troubleshooting_tips,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "tags": self.tags,
        }


@runtime_checkable
class MetadataProvider(Protocol):
    """Protocol for tools that provide metadata."""

    async def get_tool_metadata(self) -> ToolMetadata:
        """Get comprehensive metadata for this tool.

        Returns:
            Tool metadata instance
        """
        ...

    async def update_performance_metrics(self, execution_time_ms: float, success: bool) -> None:
        """Update performance metrics after tool execution.

        Args:
            execution_time_ms: Execution time in milliseconds
            success: Whether the execution was successful
        """
        ...
