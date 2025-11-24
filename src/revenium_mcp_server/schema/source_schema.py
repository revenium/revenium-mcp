"""Source Schema Discovery.

This module provides schema discovery and validation capabilities for source management,
using API-verified source types and following Revenium conventions.

Following development best practices:
- API-verified source types only
- Comprehensive validation rules
- Rich examples and templates
- Error handling and fallbacks
"""

from typing import Any, Dict, List, Optional

from loguru import logger

from .discovery_engine import BaseSchemaDiscovery


class SourceSchemaDiscovery(BaseSchemaDiscovery):
    """Source-specific schema discovery using API-verified capabilities."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize source schema discovery.

        Args:
            config: Optional configuration dictionary
        """
        super().__init__(config)

        # API-VERIFIED source types (tested against actual Revenium API)
        self.verified_source_types = ["API", "STREAM", "AI"]

        # Note: Source statuses removed - API doesn't support status field

    def get_capabilities(self) -> Dict[str, Any]:
        """Get comprehensive source capabilities.

        Returns:
            Source capabilities dictionary with API-verified data
        """
        return {
            "source_types": self.verified_source_types,
            # Note: source_statuses removed - API doesn't support status field
            "schema": {
                "source_data": {
                    "required": ["name", "description", "version", "type"],
                    "optional": [
                        "sourceType",
                        "syncedWithApiGateway",
                        "autoDiscoveryEnabled",
                        "tags",
                        "sourceClassifications",
                        "metadata",
                        "logoURL",
                        "devPortalLink",
                        "externalId",
                        "externalUsagePlanId",
                    ],
                }
            },
            "validation_rules": {
                "name": {"min_length": 1, "max_length": 255},
                "description": {"min_length": 1, "max_length": 1000},
                "version": {"pattern": r"^\d+\.\d+\.\d+$"},
                "type": {"enum": self.verified_source_types},
            },
            "field_constraints": {
                "name": "Source name must be unique and descriptive",
                "description": "Clear description of the source purpose",
                "version": "Semantic version format (e.g., 1.0.0)",
                "type": f"Must be one of: {', '.join(self.verified_source_types)}",
            },
            "business_rules": [
                "Source name must be unique within the organization",
                "Type must match actual source implementation",
                "Version should follow semantic versioning",
                "Description should clearly explain source purpose",
                "Optional fields enhance source discoverability",
            ],
            "api_compatibility": {
                "verified_against": "Revenium API v2",
                "last_verified": "2025-06-17",
                "source_types_tested": True,
                "required_fields_tested": True,
                "optional_fields_tested": True,
            },
        }

    def get_examples(self, example_type: Optional[str] = None) -> Dict[str, Any]:
        """Get source creation examples and templates.

        INTEGRATION POINT: Called by SchemaDiscoveryEngine.get_examples()
        CRITICAL: This method only accepts (example_type) parameter, unlike the engine
        which accepts (resource_type, example_type). The engine handles the delegation.

        DATA STRUCTURE: Returns examples with fields: name, description, use_case, template
        NOTE: Does NOT include top-level 'type' field - type must be extracted from template.type

        Args:
            example_type: Optional filter for specific example types

        Returns:
            Examples dictionary with templates and use cases with structure:
            {"examples": [{"name": str, "description": str, "use_case": str, "template": dict}], "categories": [str]}
        """
        all_examples = {
            "basic": self._get_basic_examples(),
            "advanced": self._get_advanced_examples(),
            "api_integration": self._get_api_integration_examples(),
            "streaming": self._get_streaming_examples(),
            "ai_sources": self._get_ai_source_examples(),
        }

        if example_type and example_type in all_examples:
            return {"examples": all_examples[example_type]}

        # Return all examples if no specific type requested
        return {
            "examples": [example for category in all_examples.values() for example in category],
            "categories": list(all_examples.keys()),
            "total_examples": sum(len(examples) for examples in all_examples.values()),
        }

    def validate_configuration(
        self, config_data: Dict[str, Any], dry_run: bool = True
    ) -> Dict[str, Any]:
        """Validate source configuration.

        Args:
            config_data: Source configuration to validate
            dry_run: Whether this is a dry run validation

        Returns:
            Validation results with detailed feedback
        """
        validation_result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "suggestions": [],
            "dry_run": dry_run,
            "validated_fields": [],
        }

        # Validate required fields
        required_fields = ["name", "description", "version", "type"]
        for field in required_fields:
            if field not in config_data or not config_data[field]:
                validation_result["valid"] = False
                validation_result["errors"].append(
                    {
                        "field": field,
                        "error": f"Required field '{field}' is missing or empty",
                        "suggestion": f"Provide a valid value for '{field}'",
                    }
                )
            else:
                validation_result["validated_fields"].append(field)

        # Validate source type
        if "type" in config_data:
            source_type = config_data["type"]
            if source_type not in self.verified_source_types:
                validation_result["valid"] = False
                validation_result["errors"].append(
                    {
                        "field": "type",
                        "error": f"Invalid source type: '{source_type}'",
                        "valid_values": self.verified_source_types,
                        "suggestion": f"Use one of the verified types: {', '.join(self.verified_source_types)}",
                    }
                )

        # Validate version format
        if "version" in config_data:
            version = config_data["version"]
            if not self._is_valid_version(version):
                validation_result["warnings"].append(
                    {
                        "field": "version",
                        "warning": f"Version '{version}' doesn't follow semantic versioning",
                        "suggestion": "Use format like '1.0.0' for better compatibility",
                    }
                )

        # Validate field lengths
        self._validate_field_lengths(config_data, validation_result)

        # Add type-specific suggestions
        if "type" in config_data:
            self._add_type_specific_suggestions(config_data["type"], validation_result)

        # Add success suggestions
        if validation_result["valid"]:
            validation_result["suggestions"].append(
                {
                    "type": "success",
                    "message": "Source configuration is valid and ready for creation",
                    "next_steps": [
                        "Use 'create' action to create this source",
                        "Consider adding optional metadata for better discoverability",
                        "Test source connectivity after creation",
                    ],
                }
            )

        return validation_result

    def _get_basic_examples(self) -> List[Dict[str, Any]]:
        """Get basic source examples."""
        return [
            {
                "name": "Simple API Source",
                "description": "Basic API source for data ingestion",
                "use_case": "Connect to external REST API",
                "template": {
                    "name": "External API",
                    "description": "REST API data source",
                    "version": "1.0.0",
                    "type": "API",
                },
            },
            {
                "name": "Basic Stream Source",
                "description": "Simple streaming data source",
                "use_case": "Real-time data streaming",
                "template": {
                    "name": "Data Stream",
                    "description": "Real-time streaming source",
                    "version": "1.0.0",
                    "type": "STREAM",
                },
            },
            {
                "name": "AI Data Source",
                "description": "AI-powered data source",
                "use_case": "Machine learning data pipeline",
                "template": {
                    "name": "AI Pipeline",
                    "description": "AI-powered data processing source",
                    "version": "1.0.0",
                    "type": "AI",
                },
            },
        ]

    def _get_advanced_examples(self) -> List[Dict[str, Any]]:
        """Get advanced source examples with optional fields."""
        return [
            {
                "name": "Enterprise API Source",
                "description": "Full-featured API source with all optional fields",
                "use_case": "Production API integration with comprehensive metadata",
                "template": {
                    "name": "Enterprise API Gateway",
                    "description": "Production-ready API source with comprehensive configuration",
                    "version": "2.1.0",
                    "type": "API",
                    "sourceType": "REST_API",
                    "syncedWithApiGateway": True,
                    "autoDiscoveryEnabled": True,
                    "tags": ["production", "api", "enterprise"],
                    "sourceClassifications": ["external", "third-party"],
                    "metadata": {
                        "environment": "production",
                        "owner": "data-team@company.com",
                        "sla": "99.9%",
                        "rate_limit": "1000/hour",
                    },
                    "logoURL": "https://company.com/logo.png",
                    "devPortalLink": "https://developer.company.com/api",
                    "externalId": "ext_api_12345",
                    "externalUsagePlanId": "plan_premium_001",
                },
            }
        ]

    def _get_api_integration_examples(self) -> List[Dict[str, Any]]:
        """Get API-specific integration examples."""
        return [
            {
                "name": "REST API with Metadata",
                "description": "API source with comprehensive metadata configuration",
                "use_case": "Well-documented API integration",
                "template": {
                    "name": "Well-Documented REST API",
                    "description": "REST API source with comprehensive metadata",
                    "version": "1.2.0",
                    "type": "API",
                    "metadata": {
                        "endpoint": "https://api.example.com/v1",
                        "documentation": "https://docs.example.com/api",
                    },
                },
            }
        ]

    def _get_streaming_examples(self) -> List[Dict[str, Any]]:
        """Get streaming-specific examples."""
        return [
            {
                "name": "Real-time Event Stream",
                "description": "High-throughput event streaming source",
                "use_case": "Real-time analytics and monitoring",
                "template": {
                    "name": "Event Stream",
                    "description": "Real-time event data stream",
                    "version": "1.0.0",
                    "type": "STREAM",
                    "metadata": {
                        "protocol": "websocket",
                        "format": "json",
                        "throughput": "10000/sec",
                    },
                },
            }
        ]

    def _get_ai_source_examples(self) -> List[Dict[str, Any]]:
        """Get AI-specific source examples."""
        return [
            {
                "name": "ML Model Data Source",
                "description": "AI model output as data source",
                "use_case": "Machine learning pipeline integration",
                "template": {
                    "name": "ML Model Output",
                    "description": "AI model predictions and insights",
                    "version": "1.0.0",
                    "type": "AI",
                    "metadata": {
                        "model_type": "classification",
                        "framework": "tensorflow",
                        "accuracy": "95.2%",
                    },
                },
            }
        ]

    def _is_valid_version(self, version: str) -> bool:
        """Check if version follows semantic versioning."""
        import re

        pattern = r"^\d+\.\d+\.\d+$"
        return bool(re.match(pattern, version))

    def _validate_field_lengths(
        self, config_data: Dict[str, Any], validation_result: Dict[str, Any]
    ) -> None:
        """Validate field length constraints."""
        constraints = {"name": {"min": 1, "max": 255}, "description": {"min": 1, "max": 1000}}

        for field, limits in constraints.items():
            if field in config_data:
                value = config_data[field]
                if isinstance(value, str):
                    if len(value) < limits["min"]:
                        validation_result["errors"].append(
                            {
                                "field": field,
                                "error": f"Field '{field}' is too short (minimum {limits['min']} characters)",
                                "suggestion": f"Provide a more descriptive {field}",
                            }
                        )
                    elif len(value) > limits["max"]:
                        validation_result["errors"].append(
                            {
                                "field": field,
                                "error": f"Field '{field}' is too long (maximum {limits['max']} characters)",
                                "suggestion": f"Shorten the {field} to fit within limits",
                            }
                        )

    def _add_type_specific_suggestions(
        self, source_type: str, validation_result: Dict[str, Any]
    ) -> None:
        """Add type-specific suggestions."""
        suggestions = {
            "API": [
                "Consider adding endpoint URL in metadata",
                "Add rate limiting details if applicable",
                "Include API documentation links",
            ],
            "STREAM": [
                "Specify streaming protocol in metadata",
                "Include throughput expectations",
                "Add data format information",
            ],
            "AI": [
                "Include model type and framework details",
                "Add accuracy or performance metrics",
                "Specify input/output data formats",
            ],
        }

        if source_type in suggestions:
            validation_result["suggestions"].extend(
                [
                    {"type": "enhancement", "message": suggestion}
                    for suggestion in suggestions[source_type]
                ]
            )
