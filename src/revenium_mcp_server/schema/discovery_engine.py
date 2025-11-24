"""Core schema discovery engine for MCP tools.

This module provides the foundational schema discovery functionality
that can be extended by resource-specific discovery modules.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Type

from loguru import logger
from pydantic import BaseModel


class BaseSchemaDiscovery(ABC):
    """Base class for resource-specific schema discovery."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize the schema discovery.

        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}

    @abstractmethod
    def get_capabilities(self) -> Dict[str, Any]:
        """Get capabilities for this resource type.

        Returns:
            Capabilities dictionary
        """
        pass

    @abstractmethod
    def get_examples(self, example_type: Optional[str] = None) -> Dict[str, Any]:
        """Get examples for this resource type.

        Args:
            example_type: Optional filter for specific example types

        Returns:
            Examples dictionary
        """
        pass

    @abstractmethod
    def validate_configuration(
        self, config_data: Dict[str, Any], dry_run: bool = True
    ) -> Dict[str, Any]:
        """Validate configuration for this resource type.

        Args:
            config_data: Configuration data to validate
            dry_run: Whether this is a dry run validation

        Returns:
            Validation results
        """
        pass

    def get_agent_friendly_summary(self) -> Dict[str, Any]:
        """Get agent-friendly summary for this resource type.

        Returns:
            Agent-friendly summary
        """
        capabilities = self.get_capabilities()
        examples = self.get_examples()

        return {
            "capabilities": capabilities,
            "examples": examples.get("examples", []),
            "quick_reference": self._build_quick_reference(capabilities),
            "common_patterns": self._build_common_patterns(capabilities),
        }

    def _build_quick_reference(self, capabilities: Dict[str, Any]) -> Dict[str, Any]:
        """Build quick reference from capabilities.

        Args:
            capabilities: Capabilities dictionary

        Returns:
            Quick reference dictionary
        """
        # Default implementation - can be overridden by subclasses
        return {
            "available_fields": list(capabilities.get("schema", {}).get("required", [])),
            "optional_fields": list(capabilities.get("schema", {}).get("optional", [])),
        }

    def _build_common_patterns(self, capabilities: Dict[str, Any]) -> Dict[str, Any]:
        """Build common patterns from capabilities.

        Args:
            capabilities: Capabilities dictionary

        Returns:
            Common patterns dictionary
        """
        # Default implementation - can be overridden by subclasses
        return {}


class SchemaDiscoveryEngine:
    """Core engine for schema discovery across resource types."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize the schema discovery engine.

        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        self._discoverers: Dict[str, BaseSchemaDiscovery] = {}

    def register_discoverer(self, resource_type: str, discoverer: BaseSchemaDiscovery) -> None:
        """Register a resource-specific discoverer.

        Args:
            resource_type: Type of resource
            discoverer: Schema discoverer instance
        """
        self._discoverers[resource_type] = discoverer

        # Only log in verbose startup mode
        import os

        startup_verbose = os.getenv("MCP_STARTUP_VERBOSE", "false").lower() == "true"
        if startup_verbose:
            logger.info(f"Registered schema discoverer for: {resource_type}")

    def get_capabilities(self, resource_type: str) -> Dict[str, Any]:
        """Get capabilities for a specific resource type.

        Args:
            resource_type: Type of resource

        Returns:
            Capabilities dictionary
        """
        discoverer = self._get_discoverer(resource_type)
        if discoverer:
            return discoverer.get_capabilities()

        return {
            "error": f"Unknown resource type: {resource_type}",
            "available_types": list(self._discoverers.keys()),
        }

    def get_examples(
        self, resource_type: str, example_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get examples for a specific resource type.

        INTEGRATION POINT: Central delegation to resource-specific discoverers
        CRITICAL: This method signature (resource_type, example_type) differs from
        individual discoverer signatures which only accept (example_type)

        Common debugging: If you see parameter mismatch errors, check that:
        1. MCP tool defines example_type parameter in enhanced_server.py
        2. Tool validator calls this method with both parameters
        3. Individual discoverer only expects example_type parameter

        Args:
            resource_type: Type of resource (e.g., "sources", "products")
            example_type: Optional filter for specific example types

        Returns:
            Examples dictionary with structure: {"examples": [...], "categories": [...]}
        """
        discoverer = self._get_discoverer(resource_type)
        if discoverer:
            return discoverer.get_examples(example_type)

        return {
            "error": f"No examples available for resource type: {resource_type}",
            "available_types": list(self._discoverers.keys()),
        }

    def validate_configuration(
        self, resource_type: str, config_data: Dict[str, Any], dry_run: bool = True
    ) -> Dict[str, Any]:
        """Validate configuration for a specific resource type.

        Args:
            resource_type: Type of resource
            config_data: Configuration data to validate
            dry_run: Whether this is a dry run validation

        Returns:
            Validation results
        """
        discoverer = self._get_discoverer(resource_type)
        if discoverer:
            return discoverer.validate_configuration(config_data, dry_run)

        return {
            "valid": False,
            "error": f"No validation rules for resource type: {resource_type}",
            "available_types": list(self._discoverers.keys()),
        }

    def get_agent_friendly_summary(self, resource_type: str) -> Dict[str, Any]:
        """Get agent-friendly summary for a specific resource type.

        Args:
            resource_type: Type of resource

        Returns:
            Agent-friendly summary
        """
        discoverer = self._get_discoverer(resource_type)
        if discoverer:
            return discoverer.get_agent_friendly_summary()

        return {
            "error": f"Unknown resource type: {resource_type}",
            "available_types": list(self._discoverers.keys()),
        }

    def infer_field_type(self, value: Any) -> str:
        """Infer the type of a field based on its value.

        Args:
            value: Value to analyze

        Returns:
            Inferred type string
        """
        if isinstance(value, str):
            return "string"
        elif isinstance(value, int):
            return "integer"
        elif isinstance(value, float):
            return "number"
        elif isinstance(value, bool):
            return "boolean"
        elif isinstance(value, list):
            return "array"
        elif isinstance(value, dict):
            return "object"
        elif value is None:
            return "null"
        else:
            return "unknown"

    def generate_json_schema(self, model_class: Type[BaseModel]) -> Dict[str, Any]:
        """Generate JSON schema from a Pydantic model class.

        Args:
            model_class: Pydantic model class

        Returns:
            JSON schema dictionary
        """
        return model_class.model_json_schema()

    def _get_discoverer(self, resource_type: str) -> Optional[BaseSchemaDiscovery]:
        """Get discoverer for a resource type.

        Args:
            resource_type: Type of resource

        Returns:
            Discoverer instance or None
        """
        return self._discoverers.get(resource_type)

    def _auto_register_discoverers(self):
        """Auto-register available discoverers."""
        # This will be populated as we create resource-specific discoverers
        try:
            from .alert_schema import AlertSchemaDiscovery

            self.register_discoverer("anomalies", AlertSchemaDiscovery(self.config))
            self.register_discoverer("alerts", AlertSchemaDiscovery(self.config))
        except ImportError:
            logger.debug("Alert schema discovery not available")

        # Add other discoverers as they're created
        # try:
        #     from .product_schema import ProductSchemaDiscovery
        #     self.register_discoverer("products", ProductSchemaDiscovery(self.config))
        # except ImportError:
        #     logger.debug("Product schema discovery not available")


# INTEGRATION POINT: Global schema discovery engine instance
# This is imported by all MCP tools as the central schema discovery interface
# Auto-registers all available resource-specific discoverers on initialization
schema_discovery_engine = SchemaDiscoveryEngine()
