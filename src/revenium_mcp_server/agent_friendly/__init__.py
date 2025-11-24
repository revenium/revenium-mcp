"""Agent-Friendly MCP Server Framework.

This module provides shared interfaces, utilities, and patterns for creating
agent-friendly MCP tools that provide excellent developer and AI agent experience.

The framework standardizes:
- Schema discovery and introspection
- Smart defaults and simplified creation
- Enhanced error handling with suggestions
- Natural language query support
- Cross-tool workflow integration
"""

from .base_implementations import (
    BaseAgentFriendlyTool,
    StandardNaturalLanguageProcessor,
    StandardSchemaDiscovery,
    StandardValidationEngine,
)
from .error_handling import AgentFriendlyError, ErrorFormatter, SchemaError, ValidationError
from .error_library import ErrorExamples, ErrorLibrary
from .interfaces import (
    AgentFriendlyTool,
    NaturalLanguageProcessor,
    SchemaDiscovery,
    SmartDefaults,
    ValidationEngine,
)
from .response_formatting import (
    AgentSummaryResponse,
    CapabilitiesResponse,
    ExamplesResponse,
    StandardResponse,
    ValidationResponse,
)
from .standard_formatter import UnifiedResponseFormatter

# Error handling framework
from .unified_error_handler import (
    ErrorCategory,
    ErrorSeverity,
    StandardizedError,
    UnifiedErrorHandler,
    with_error_handling,
)

__all__ = [
    # Core interfaces
    "AgentFriendlyTool",
    "SchemaDiscovery",
    "SmartDefaults",
    "ValidationEngine",
    "NaturalLanguageProcessor",
    # Base implementations
    "BaseAgentFriendlyTool",
    "StandardSchemaDiscovery",
    "StandardValidationEngine",
    "StandardNaturalLanguageProcessor",
    # Error handling
    "AgentFriendlyError",
    "ValidationError",
    "SchemaError",
    "ErrorFormatter",
    # Response formatting
    "StandardResponse",
    "AgentSummaryResponse",
    "ExamplesResponse",
    "ValidationResponse",
    "CapabilitiesResponse",
    "UnifiedResponseFormatter",
    # Error handling framework
    "UnifiedErrorHandler",
    "StandardizedError",
    "ErrorSeverity",
    "ErrorCategory",
    "with_error_handling",
    "ErrorLibrary",
    "ErrorExamples",
]

# Version information
__version__ = "0.1.1"
__author__ = "Revenium MCP Team"
__description__ = "Agent-Friendly MCP Server Framework"
