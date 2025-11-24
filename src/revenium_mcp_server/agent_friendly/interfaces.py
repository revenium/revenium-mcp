"""Core interfaces for agent-friendly MCP tools.

This module defines the standard interfaces that all agent-friendly tools
should implement to provide consistent experience across the MCP server.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union

from mcp.types import EmbeddedResource, ImageContent, TextContent


class AgentFriendlyTool(ABC):
    """Interface for agent-friendly MCP tools.

    All tools implementing this interface provide standardized agent-friendly
    features including schema discovery, smart defaults, and enhanced validation.
    """

    @abstractmethod
    async def get_agent_summary(self) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Provide quick-start guidance for agents.

        Returns:
            Quick overview with common use cases and next steps
        """
        pass

    @abstractmethod
    async def get_capabilities(self) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Provide comprehensive schema discovery.

        Returns:
            Complete capabilities including valid options, fields, and constraints
        """
        pass

    @abstractmethod
    async def get_examples(
        self, example_type: Optional[str] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Provide working examples for common use cases.

        Args:
            example_type: Optional filter for specific example types

        Returns:
            Working examples that can be copy-pasted and modified
        """
        pass

    @abstractmethod
    async def validate(
        self, data: Dict[str, Any], dry_run: bool = True
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Validate configuration with detailed feedback.

        Args:
            data: Configuration to validate
            dry_run: Whether to perform dry-run validation only

        Returns:
            Validation results with specific errors and suggestions
        """
        pass

    @abstractmethod
    async def create_simple(
        self, **kwargs
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Create resource with smart defaults and minimal input.

        Args:
            **kwargs: Minimal required parameters

        Returns:
            Creation result with guidance for further customization
        """
        pass


class SchemaDiscovery(ABC):
    """Interface for schema discovery and introspection."""

    @abstractmethod
    def get_schema(self) -> Dict[str, Any]:
        """Get complete schema information.

        Returns:
            Schema dictionary with fields, types, constraints, and examples
        """
        pass

    @abstractmethod
    def get_field_info(self, field_name: str) -> Dict[str, Any]:
        """Get detailed information about a specific field.

        Args:
            field_name: Name of the field

        Returns:
            Field information including type, constraints, examples, and description
        """
        pass

    @abstractmethod
    def get_valid_values(self, field_name: str) -> List[Any]:
        """Get valid values for a field.

        Args:
            field_name: Name of the field

        Returns:
            List of valid values for the field
        """
        pass


class SmartDefaults(ABC):
    """Interface for intelligent default value generation."""

    @abstractmethod
    def get_defaults(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Generate smart defaults based on context.

        Args:
            context: Context information for generating defaults

        Returns:
            Dictionary of field names to default values
        """
        pass

    @abstractmethod
    def get_minimal_required(self) -> List[str]:
        """Get list of minimal required fields for simple creation.

        Returns:
            List of field names that are absolutely required
        """
        pass


class ValidationEngine(ABC):
    """Interface for comprehensive validation."""

    @abstractmethod
    def validate_schema(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate data against schema.

        Args:
            data: Data to validate

        Returns:
            Validation result with errors and suggestions
        """
        pass

    @abstractmethod
    def validate_business_rules(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate business rules and constraints.

        Args:
            data: Data to validate

        Returns:
            Business rule validation result
        """
        pass

    @abstractmethod
    def validate_dependencies(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate dependencies and relationships.

        Args:
            data: Data to validate

        Returns:
            Dependency validation result
        """
        pass


class NaturalLanguageProcessor(ABC):
    """Interface for natural language query processing."""

    @abstractmethod
    def parse_query(self, query: str) -> Dict[str, Any]:
        """Parse natural language query into structured parameters.

        Args:
            query: Natural language query string

        Returns:
            Structured parameters extracted from query
        """
        pass

    @abstractmethod
    def parse_date_expression(self, expression: str) -> Dict[str, Any]:
        """Parse natural date expressions.

        Args:
            expression: Date expression like "last month", "past week"

        Returns:
            Parsed date range or specific date
        """
        pass

    @abstractmethod
    def suggest_intent(self, query: str) -> List[str]:
        """Suggest possible intents for ambiguous queries.

        Args:
            query: Query string

        Returns:
            List of suggested intents or actions
        """
        pass
