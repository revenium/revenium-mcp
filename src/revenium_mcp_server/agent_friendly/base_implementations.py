"""Base implementations for agent-friendly MCP tools.

This module provides concrete base classes that implement the agent-friendly
interfaces with standard functionality that can be extended by specific tools.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union

from mcp.types import EmbeddedResource, ImageContent, TextContent

from .interfaces import (
    AgentFriendlyTool,
    NaturalLanguageProcessor,
    SchemaDiscovery,
    ValidationEngine,
)
from .response_formatting import (
    AgentSummaryResponse,
    CapabilitiesResponse,
    ExamplesResponse,
    ValidationResponse,
)


class BaseAgentFriendlyTool(AgentFriendlyTool):
    """Base implementation of agent-friendly tool interface.

    Provides standard implementations that can be customized by specific tools.
    """

    def __init__(self, tool_name: str, description: str):
        """Initialize base agent-friendly tool.

        Args:
            tool_name: Name of the tool
            description: Description of the tool
        """
        self.tool_name = tool_name
        self.description = description
        self.schema_discovery = StandardSchemaDiscovery()
        self.validation_engine = StandardValidationEngine()
        self.nlp_processor = StandardNaturalLanguageProcessor()

    async def get_agent_summary(self) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Provide quick-start guidance for agents."""
        # Default implementation - should be overridden by specific tools
        return AgentSummaryResponse.create_summary(
            tool_name=self.tool_name,
            description=self.description,
            key_capabilities=self._get_key_capabilities(),
            common_use_cases=self._get_common_use_cases(),
            quick_start_steps=self._get_quick_start_steps(),
            next_actions=self._get_next_actions(),
        )

    async def get_capabilities(self) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Provide comprehensive schema discovery."""
        return CapabilitiesResponse.create_capabilities(
            tool_name=self.tool_name,
            actions=self._get_available_actions(),
            schema_info=self.schema_discovery.get_schema(),
            constraints=self._get_constraints(),
        )

    async def get_examples(
        self, example_type: Optional[str] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Provide working examples for common use cases."""
        examples = self._get_examples(example_type)
        return ExamplesResponse.create_examples(
            tool_name=self.tool_name, examples=examples, example_type=example_type
        )

    async def validate(
        self, data: Dict[str, Any], dry_run: bool = True
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Validate configuration with detailed feedback."""
        errors = []
        warnings = []

        # Schema validation
        schema_result = self.validation_engine.validate_schema(data)
        if not schema_result.get("valid", True):
            errors.extend(schema_result.get("errors", []))

        # Business rules validation
        business_result = self.validation_engine.validate_business_rules(data)
        if not business_result.get("valid", True):
            errors.extend(business_result.get("errors", []))

        warnings.extend(business_result.get("warnings", []))

        is_valid = len(errors) == 0

        return ValidationResponse.create_validation_result(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            suggestions=self._get_validation_suggestions(errors),
            dry_run=dry_run,
        )

    async def create_simple(
        self, **kwargs
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Create resource with smart defaults and minimal input."""
        # This should be implemented by specific tools
        raise NotImplementedError("create_simple must be implemented by specific tools")

    # Abstract methods that should be implemented by specific tools
    def _get_key_capabilities(self) -> List[str]:
        """Get key capabilities for agent summary."""
        return ["Basic CRUD operations", "Schema discovery", "Validation"]

    def _get_common_use_cases(self) -> List[Dict[str, str]]:
        """Get common use cases for agent summary."""
        return [
            {
                "title": "List Resources",
                "description": "Retrieve and filter existing resources",
                "example": f"{self.tool_name}(action='list')",
            }
        ]

    def _get_quick_start_steps(self) -> List[str]:
        """Get quick start steps for agent summary."""
        return [
            f"Call get_capabilities() to understand available actions",
            f"Call get_examples() to see working examples",
            f"Use validate() to check your configuration",
            f"Call the appropriate action with your data",
            f"Check the response for results and next steps",
        ]

    def _get_next_actions(self) -> List[str]:
        """Get suggested next actions for agent summary."""
        return [
            f"Try: {self.tool_name}(action='get_capabilities')",
            f"Try: {self.tool_name}(action='get_examples')",
            f"Try: {self.tool_name}(action='list', page=0, size=5)",
        ]

    def _get_available_actions(self) -> List[Dict[str, Any]]:
        """Get available actions for capabilities response."""
        return [
            {
                "name": "list",
                "description": "List resources with optional filtering",
                "parameters": [
                    {
                        "name": "page",
                        "type": "integer",
                        "required": False,
                        "description": "Page number (0-based)",
                    },
                    {
                        "name": "size",
                        "type": "integer",
                        "required": False,
                        "description": "Number of items per page",
                    },
                ],
            }
        ]

    def _get_examples(self, example_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get examples for the tool."""
        return [
            {
                "title": "Basic List",
                "description": "List the first 5 resources",
                "use_case": "Getting started with the tool",
                "request": {"action": "list", "page": 0, "size": 5},
                "response": {"data": [], "total": 0, "page": 0, "size": 5},
            }
        ]

    def _get_constraints(self) -> Dict[str, Any]:
        """Get constraints for capabilities response."""
        return {
            "Rate Limits": "Standard API rate limits apply",
            "Permissions": "Requires appropriate API key permissions",
        }

    def _get_validation_suggestions(self, errors: List[Dict[str, Any]]) -> List[str]:
        """Get validation suggestions based on errors."""
        suggestions = []
        for error in errors:
            if "suggestion" in error:
                suggestions.append(error["suggestion"])
        return suggestions


class StandardSchemaDiscovery(SchemaDiscovery):
    """Standard implementation of schema discovery."""

    def __init__(self):
        self._schema = {}
        self._field_info = {}

    def get_schema(self) -> Dict[str, Any]:
        """Get complete schema information."""
        return self._schema

    def get_field_info(self, field_name: str) -> Dict[str, Any]:
        """Get detailed information about a specific field."""
        return self._field_info.get(field_name, {})

    def get_valid_values(self, field_name: str) -> List[Any]:
        """Get valid values for a field."""
        field_info = self.get_field_info(field_name)
        return field_info.get("valid_values", [])

    def set_schema(self, schema: Dict[str, Any]):
        """Set the schema information."""
        self._schema = schema

    def set_field_info(self, field_name: str, info: Dict[str, Any]):
        """Set information for a specific field."""
        self._field_info[field_name] = info


class StandardValidationEngine(ValidationEngine):
    """Standard implementation of validation engine."""

    def validate_schema(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate data against schema."""
        # Basic validation - can be extended
        errors = []

        # Check for required fields (if schema is available)
        # This is a placeholder implementation

        return {"valid": len(errors) == 0, "errors": errors}

    def validate_business_rules(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate business rules and constraints."""
        # Placeholder implementation
        return {"valid": True, "errors": [], "warnings": []}

    def validate_dependencies(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate dependencies and relationships."""
        # Placeholder implementation
        return {"valid": True, "errors": []}


class StandardNaturalLanguageProcessor(NaturalLanguageProcessor):
    """Standard implementation of natural language processor."""

    def parse_query(self, query: str) -> Dict[str, Any]:
        """Parse natural language query into structured parameters."""
        # Basic implementation - can be extended
        parsed = {}

        # Parse date expressions
        date_result = self.parse_date_expression(query)
        if date_result:
            parsed.update(date_result)

        return parsed

    def parse_date_expression(self, expression: str) -> Dict[str, Any]:
        """Parse natural date expressions."""
        expression = expression.lower()
        now = datetime.now()

        # Common date patterns
        if "last month" in expression:
            start_date = now.replace(day=1) - timedelta(days=1)
            start_date = start_date.replace(day=1)
            end_date = now.replace(day=1) - timedelta(days=1)
            return {"start": start_date.isoformat(), "end": end_date.isoformat()}

        elif "past week" in expression or "last week" in expression:
            start_date = now - timedelta(days=7)
            return {"start": start_date.isoformat(), "end": now.isoformat()}

        elif "today" in expression:
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return {"start": start_date.isoformat(), "end": now.isoformat()}

        elif "yesterday" in expression:
            yesterday = now - timedelta(days=1)
            start_date = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
            return {"start": start_date.isoformat(), "end": end_date.isoformat()}

        return {}

    def suggest_intent(self, query: str) -> List[str]:
        """Suggest possible intents for ambiguous queries."""
        query = query.lower()
        suggestions = []

        if "list" in query or "show" in query or "get" in query:
            suggestions.append("list_resources")

        if "create" in query or "add" in query or "new" in query:
            suggestions.append("create_resource")

        if "update" in query or "modify" in query or "change" in query:
            suggestions.append("update_resource")

        if "delete" in query or "remove" in query:
            suggestions.append("delete_resource")

        return suggestions
