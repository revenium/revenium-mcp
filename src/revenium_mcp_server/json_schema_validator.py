"""JSON Schema Validation for MCP Tools.

This module provides comprehensive JSON Schema validation for all MCP tool parameters
to ensure consistent validation and provide clear, actionable error messages.
"""

from typing import Any, Dict, List

from loguru import logger

# Using custom validation logic for MCP tool parameters
# This provides better error messages and agent-friendly feedback

# Note: ValidationError and StandardErrorBuilder imports removed as they're not used
# This module uses custom validation logic with structured error responses


class JSONSchemaValidator:
    """Comprehensive JSON Schema validator for MCP tools."""

    def __init__(self):
        """Initialize the JSON Schema validator with all tool schemas."""
        self.schemas = self._build_all_schemas()
        self.validator_cache: Dict[str, Any] = {}

    def validate_tool_parameters(
        self, tool_name: str, parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate tool parameters against schema rules.

        Args:
            tool_name: Name of the MCP tool
            parameters: Parameters to validate

        Returns:
            Validation result with errors and suggestions
        """
        if tool_name not in self.schemas:
            return {
                "valid": False,
                "errors": [f"No schema defined for tool: {tool_name}"],
                "suggestions": ["Check tool name spelling", "Ensure tool is supported"],
            }

        schema = self.schemas[tool_name]

        try:
            # Use custom validation logic for comprehensive parameter validation
            errors = self._validate_against_schema(parameters, schema)

            if not errors:
                return {
                    "valid": True,
                    "errors": [],
                    "suggestions": [],
                    "validated_data": parameters,
                }

            return {
                "valid": False,
                "errors": errors,
                "suggestions": self._generate_suggestions_for_errors(errors, tool_name),
            }

        except Exception as e:
            logger.error(f"Schema validation failed for {tool_name}: {e}")
            return {
                "valid": False,
                "errors": [f"Schema validation error: {str(e)}"],
                "suggestions": ["Check parameter format", "Refer to tool documentation"],
            }

    def _validate_against_schema(
        self, parameters: Dict[str, Any], schema: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Custom validation logic against schema."""
        errors = []

        # Check required parameters
        required = schema.get("required", [])
        for req_param in required:
            if req_param not in parameters:
                errors.append(
                    {
                        "field": req_param,
                        "message": f"Missing required parameter: {req_param}",
                        "expected": f"Required parameter '{req_param}'",
                        "provided": "missing",
                    }
                )

        # Check parameter types and constraints
        properties = schema.get("properties", {})
        for param_name, param_value in parameters.items():
            if param_name in properties:
                param_schema = properties[param_name]
                param_errors = self._validate_parameter(param_name, param_value, param_schema)
                errors.extend(param_errors)

        return errors

    def _validate_parameter(
        self, param_name: str, param_value: Any, param_schema: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Validate a single parameter against its schema."""
        errors = []

        # Handle anyOf validation (multiple type options)
        if "anyOf" in param_schema:
            any_of_schemas = param_schema["anyOf"]
            valid_for_any = False

            for sub_schema in any_of_schemas:
                # Check if value is valid for this sub-schema
                sub_errors = self._validate_parameter(param_name, param_value, sub_schema)
                if not sub_errors:
                    valid_for_any = True
                    break

            if not valid_for_any:
                # Collect expected types for error message
                expected_types = []
                for sub_schema in any_of_schemas:
                    if "type" in sub_schema:
                        expected_types.append(sub_schema["type"])

                errors.append(
                    {
                        "field": param_name,
                        "message": f"Invalid type for '{param_name}': expected one of {expected_types}, got {type(param_value).__name__}",
                        "expected": f"Value of type: {' or '.join(expected_types)}",
                        "provided": str(param_value),
                    }
                )
                return errors  # Skip other validations if type is wrong

        # Type validation (for single type schemas)
        elif "type" in param_schema:
            expected_type = param_schema["type"]
            if not self._check_type(param_value, expected_type):
                errors.append(
                    {
                        "field": param_name,
                        "message": f"Invalid type for '{param_name}': expected {expected_type}, got {type(param_value).__name__}",
                        "expected": f"Value of type {expected_type}",
                        "provided": str(param_value),
                    }
                )
                return errors  # Skip other validations if type is wrong

        # Enum validation
        if "enum" in param_schema:
            valid_values = param_schema["enum"]
            if param_value not in valid_values:
                errors.append(
                    {
                        "field": param_name,
                        "message": f"Invalid value for '{param_name}': must be one of {valid_values}",
                        "expected": f"One of: {', '.join(map(str, valid_values))}",
                        "provided": str(param_value),
                    }
                )

        # Get the effective type for further validations
        effective_type = param_schema.get("type")
        if "anyOf" in param_schema:
            # For anyOf, determine the effective type based on the value
            for sub_schema in param_schema["anyOf"]:
                if "type" in sub_schema and self._check_type(param_value, sub_schema["type"]):
                    effective_type = sub_schema["type"]
                    break

        # String validations
        if effective_type == "string" and isinstance(param_value, str):
            # Length validations
            if "minLength" in param_schema and len(param_value) < param_schema["minLength"]:
                errors.append(
                    {
                        "field": param_name,
                        "message": f"'{param_name}' is too short: minimum {param_schema['minLength']} characters required",
                        "expected": f"String with at least {param_schema['minLength']} characters",
                        "provided": f"String with {len(param_value)} characters",
                    }
                )

            if "maxLength" in param_schema and len(param_value) > param_schema["maxLength"]:
                errors.append(
                    {
                        "field": param_name,
                        "message": f"'{param_name}' is too long: maximum {param_schema['maxLength']} characters allowed",
                        "expected": f"String with at most {param_schema['maxLength']} characters",
                        "provided": f"String with {len(param_value)} characters",
                    }
                )

        # Number validations
        if effective_type in ["integer", "number"] and isinstance(param_value, (int, float)):
            if "minimum" in param_schema and param_value < param_schema["minimum"]:
                errors.append(
                    {
                        "field": param_name,
                        "message": f"'{param_name}' is too small: minimum value is {param_schema['minimum']}",
                        "expected": f"Number >= {param_schema['minimum']}",
                        "provided": str(param_value),
                    }
                )

            if "maximum" in param_schema and param_value > param_schema["maximum"]:
                errors.append(
                    {
                        "field": param_name,
                        "message": f"'{param_name}' is too large: maximum value is {param_schema['maximum']}",
                        "expected": f"Number <= {param_schema['maximum']}",
                        "provided": str(param_value),
                    }
                )

        return errors

    def _check_type(self, value: Any, expected_type: str) -> bool:
        """Check if value matches expected type."""
        if expected_type == "string":
            return isinstance(value, str)
        elif expected_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        elif expected_type == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        elif expected_type == "boolean":
            return isinstance(value, bool)
        elif expected_type == "array":
            return isinstance(value, list)
        elif expected_type == "object":
            return isinstance(value, dict)
        else:
            return True  # Unknown type, assume valid

    def _generate_suggestions_for_errors(
        self, errors: List[Dict[str, Any]], tool_name: str
    ) -> List[str]:
        """Generate actionable suggestions based on validation errors."""
        suggestions = []

        for error in errors:
            field = error.get("field", "")
            message = error.get("message", "")

            if "Missing required parameter" in message:
                suggestions.append(f"Add the required '{field}' parameter to your request")
                suggestions.append(
                    f"Use get_capabilities action to see all required parameters for {tool_name}"
                )
            elif "Invalid type" in message:
                suggestions.append(f"Check the data type for '{field}' parameter")
                suggestions.append("Use get_examples action to see correct parameter formats")
            elif "Invalid value" in message and "must be one of" in message:
                suggestions.append(f"Use a valid value for '{field}' parameter")
                suggestions.append("Check the tool capabilities for valid options")
            elif "too short" in message or "too long" in message:
                suggestions.append(f"Check the length requirements for '{field}' parameter")
            elif "too small" in message or "too large" in message:
                suggestions.append(f"Check the value range for '{field}' parameter")

        # Add general suggestions
        suggestions.extend(
            [
                "Use validate action to check your configuration before submitting",
                "Refer to get_examples for working templates",
                "Check the tool documentation for parameter requirements",
            ]
        )

        return list(set(suggestions))  # Remove duplicates

    def _build_all_schemas(self) -> Dict[str, Dict[str, Any]]:
        """Build JSON schemas for all MCP tools."""
        return {
            "manage_products": self._build_products_schema(),
            "manage_subscriptions": self._build_subscriptions_schema(),
            "manage_sources": self._build_sources_schema(),
            "manage_customers": self._build_customers_schema(),
            "manage_alerts": self._build_alerts_schema(),
            "manage_workflows": self._build_workflows_schema(),
        }

    def _build_products_schema(self) -> Dict[str, Any]:
        """Build JSON schema for manage_products tool."""
        return {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "Manage Products Parameters",
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list",
                        "get",
                        "create",
                        "update",
                        "delete",
                        "get_capabilities",
                        "get_examples",
                        "validate",
                        "get_agent_summary",
                        "create_simple",
                        "get_templates",
                        "suggest_template",
                        "create_from_description",
                        "create_with_subscription",
                    ],
                    "description": "Action to perform on products",
                },
                "product_id": {
                    "type": "string",
                    "pattern": "^[a-zA-Z0-9_-]+$",
                    "minLength": 1,
                    "maxLength": 100,
                    "description": "Product ID for get, update, delete operations",
                },
                "product_data": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "minLength": 2,
                            "maxLength": 255,
                            "description": "Product name",
                        },
                        "version": {
                            "type": "string",
                            "pattern": "^[0-9]+\\.[0-9]+\\.[0-9]+(-[a-zA-Z0-9]+)?$",
                            "description": "Product version (semantic versioning)",
                        },
                        "description": {
                            "type": "string",
                            "maxLength": 2000,
                            "description": "Product description",
                        },
                        "plan": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": ["CHARGE", "SUBSCRIPTION", "USAGE"],
                                    "description": "Plan type",
                                },
                                "name": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": 255,
                                    "description": "Plan name",
                                },
                                "currency": {
                                    "type": "string",
                                    "enum": ["USD", "EUR", "GBP", "CAD", "AUD", "JPY"],
                                    "description": "Currency code",
                                },
                            },
                            "required": ["type", "name", "currency"],
                            "description": "Pricing plan configuration",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string", "maxLength": 100},
                            "maxItems": 50,
                            "description": "Product tags",
                        },
                    },
                    "description": "Product data for create/update operations",
                },
                "page": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Page number for pagination (0-based)",
                },
                "size": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Number of items per page",
                },
                "filters": {
                    "type": "object",
                    "description": "Additional filters for list operations",
                },
                "description": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 1000,
                    "description": "Natural language description for create_from_description actions",
                },
                "text": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 1000,
                    "description": "Alternative parameter name for description",
                },
                "field": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 100,
                    "description": "Specific field name for schema operations",
                },
                "template": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 100,
                    "description": "Template name for get_templates action",
                },
                "name": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 100,
                    "description": "Alternative parameter name for template or product name",
                },
                "requirements": {
                    "oneOf": [{"type": "string"}, {"type": "object"}],
                    "description": "Requirements for suggest_template action (string or object)",
                },
                "domain": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 50,
                    "description": "Business domain for business operations",
                },
                "business_domain": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 50,
                    "description": "Alternative parameter name for domain",
                },
                "pricing_model": {
                    "type": "string",
                    "enum": ["subscription", "usage_based"],
                    "description": "Pricing model for create_simple action",
                },
                "per_unit_price": {
                    "type": "number",
                    "minimum": 0,
                    "description": "Price per unit for usage-based pricing in create_simple action",
                },
                "monthly_price": {
                    "type": "number",
                    "minimum": 0,
                    "description": "Monthly price for subscription pricing in create_simple action",
                },
                "setup_fee": {
                    "type": "number",
                    "minimum": 0,
                    "description": "Setup fee amount for create_simple action",
                },
                "type": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 50,
                    "description": "Product type for create_simple action",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Validate only without creating for validate action",
                },
                "subscription_data": {
                    "type": "object",
                    "properties": {
                        "product_id": {
                            "type": "string",
                            "minLength": 1,
                            "description": "Product ID for the subscription (auto-populated by create_with_subscription)",
                        },
                        "name": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 255,
                            "description": "Subscription name",
                        },
                        "description": {
                            "type": "string",
                            "maxLength": 1000,
                            "description": "Subscription description",
                        },
                        "clientEmailAddress": {
                            "type": "string",
                            "format": "email",
                            "description": "Customer email address for the subscription",
                        },
                        "start_date": {
                            "type": "string",
                            "format": "date",
                            "description": "Subscription start date (ISO format)",
                        },
                        "end_date": {
                            "type": "string",
                            "format": "date",
                            "description": "Subscription end date (ISO format)",
                        },
                    },
                    "description": "Subscription data for create_with_subscription action",
                },
            },
            "required": ["action"],
            "allOf": [
                {
                    "if": {"properties": {"action": {"const": "get"}}},
                    "then": {"required": ["product_id"]},
                },
                {
                    "if": {"properties": {"action": {"const": "create"}}},
                    "then": {
                        "required": ["product_data"],
                        "properties": {"product_data": {"required": ["name", "version", "plan"]}},
                    },
                },
                {
                    "if": {"properties": {"action": {"const": "update"}}},
                    "then": {"required": ["product_id", "product_data"]},
                },
                {
                    "if": {"properties": {"action": {"const": "delete"}}},
                    "then": {"required": ["product_id"]},
                },
                {
                    "if": {"properties": {"action": {"const": "create_simple"}}},
                    "then": {"required": ["name"]},
                },
                {
                    "if": {"properties": {"action": {"const": "create_with_subscription"}}},
                    "then": {
                        "required": ["product_data", "subscription_data"],
                        "properties": {
                            "product_data": {"required": ["name", "version", "plan"]},
                            "subscription_data": {"required": ["name"]},
                        },
                    },
                },
            ],
        }

    def _build_subscriptions_schema(self) -> Dict[str, Any]:
        """Build JSON schema for manage_subscriptions tool."""
        return {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "Manage Subscriptions Parameters",
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list",
                        "get",
                        "create",
                        "update",
                        "cancel",
                        "get_capabilities",
                        "get_examples",
                        "validate",
                        "get_agent_summary",
                        "create_simple",
                        "create_from_text",
                        "get_product_details",
                        "get_credentials",
                        "create_with_credentials",
                    ],
                    "description": "Action to perform on subscriptions",
                },
                "subscription_id": {
                    "type": "string",
                    "pattern": "^[a-zA-Z0-9_-]+$",
                    "minLength": 1,
                    "maxLength": 100,
                    "description": "Subscription ID",
                },
                "subscription_data": {
                    "type": "object",
                    "properties": {
                        "product_id": {
                            "type": "string",
                            "minLength": 1,
                            "description": "Product ID for the subscription",
                        },
                        "customer_id": {
                            "type": "string",
                            "minLength": 1,
                            "description": "Customer ID",
                        },
                        "plan_id": {"type": "string", "minLength": 1, "description": "Plan ID"},
                    },
                    "description": "Subscription data",
                },
                "page": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Page number for pagination",
                },
                "size": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Number of items per page",
                },
                "filters": {"type": "object", "description": "Additional filters"},
                "text": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 1000,
                    "description": "Natural language description for create_from_text action",
                },
                "credentials_data": {
                    "type": "object",
                    "properties": {
                        "label": {
                            "type": "string",
                            "minLength": 1,
                            "description": "Display name for the credential",
                        },
                        "name": {
                            "type": "string",
                            "minLength": 1,
                            "description": "Internal name for the credential",
                        },
                        "subscriberId": {
                            "type": "string",
                            "minLength": 1,
                            "description": "ID of the subscriber",
                        },
                        "organizationId": {
                            "type": "string",
                            "minLength": 1,
                            "description": "ID of the organization",
                        },
                        "externalId": {
                            "type": "string",
                            "minLength": 1,
                            "description": "External credential identifier",
                        },
                        "externalSecret": {
                            "type": "string",
                            "minLength": 1,
                            "description": "Secret/password for the credential",
                        },
                    },
                    "description": "Credential data for create_with_credentials action",
                },
                "product_id": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 100,
                    "description": "Product ID for create_simple action",
                },
                "clientEmailAddress": {
                    "type": "string",
                    "format": "email",
                    "description": "Client email address for create_simple action",
                },
                "name": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 200,
                    "description": "Subscription name for create_simple action",
                },
                "type": {
                    "type": "string",
                    "enum": ["monthly", "annual", "quarterly", "trial"],
                    "description": "Subscription type for create_simple action",
                },
                "subscription_type": {
                    "type": "string",
                    "enum": ["monthly", "annual", "quarterly", "trial"],
                    "description": "Alternative parameter for subscription type",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Validate only without creating for validate action",
                },
            },
            "required": ["action"],
        }

    def _build_sources_schema(self) -> Dict[str, Any]:
        """Build JSON schema for manage_sources tool."""
        return {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "Manage Sources Parameters",
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list",
                        "get",
                        "create",
                        "update",
                        "delete",
                        "get_capabilities",
                        "get_examples",
                        "validate",
                        "get_agent_summary",
                        "create_source",
                        "create_from_text",
                        "get_tool_metadata",
                    ],
                    "description": "Action to perform on sources",
                },
                "source_id": {
                    "type": "string",
                    "pattern": "^[a-zA-Z0-9_-]+$",
                    "minLength": 1,
                    "maxLength": 100,
                    "description": "Source ID for get, update, delete operations",
                },
                "source_data": {
                    "type": "object",
                    "description": "Source configuration data for create, update, validate operations",
                },
                # Context7 user-friendly parameters for create_source action
                "name": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 255,
                    "description": "Source name - primary user-required field",
                },
                "type": {
                    "type": "string",
                    "enum": ["api", "stream", "ai", "API", "STREAM", "AI"],
                    "description": "Source type (case-insensitive)",
                },
                "url": {"type": "string", "description": "Source URL/endpoint"},
                # Pagination parameters
                "page": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Page number for pagination (0-based)",
                },
                "size": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Number of items per page",
                },
                "filters": {
                    "type": "object",
                    "description": "Additional filters for list operations",
                },
                # Natural language creation
                "text": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Natural language description for create_from_text action",
                },
                # Validation and testing
                "dry_run": {
                    "type": "boolean",
                    "description": "Validate only without executing for create, update, delete operations",
                },
                # Discovery parameters
                "example_type": {
                    "type": "string",
                    "description": "Type of examples to retrieve for get_examples action",
                },
                # Enhanced creation parameters
                "stream_url": {
                    "type": "string",
                    "description": "Stream URL for stream-type sources",
                },
                "model_endpoint": {
                    "type": "string",
                    "description": "Model endpoint for AI-type sources",
                },
                "connection_string": {
                    "type": "string",
                    "description": "Connection string for database sources",
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        }

    def _build_customers_schema(self) -> Dict[str, Any]:
        """Build JSON schema for manage_customers tool."""
        return {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "Manage Customers Parameters",
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list",
                        "get",
                        "create",
                        "update",
                        "delete",
                        "analyze",
                        "get_agent_summary",
                        "get_capabilities",
                        "get_examples",
                        "validate",
                        "create_simple",
                    ],
                    "description": "Action to perform",
                },
                "resource_type": {
                    "type": "string",
                    "enum": ["users", "subscribers", "organizations", "teams", "relationships"],
                    "description": "Type of customer resource",
                },
                "user_id": {
                    "type": "string",
                    "pattern": "^[a-zA-Z0-9_-]+$",
                    "description": "User ID",
                },
                "subscriber_id": {
                    "type": "string",
                    "pattern": "^[a-zA-Z0-9_-]+$",
                    "description": "Subscriber ID",
                },
                "organization_id": {
                    "type": "string",
                    "pattern": "^[a-zA-Z0-9_-]+$",
                    "description": "Organization ID",
                },
                "team_id": {
                    "type": "string",
                    "pattern": "^[a-zA-Z0-9_-]+$",
                    "description": "Team ID",
                },
                "email": {"type": "string", "format": "email", "description": "Email address"},
                "user_data": {
                    "type": "object",
                    "description": "User data for create/update operations",
                },
                "subscriber_data": {
                    "type": "object",
                    "description": "Subscriber data for create/update operations",
                },
                "organization_data": {
                    "type": "object",
                    "description": "Organization data for create/update operations",
                },
                "team_data": {
                    "type": "object",
                    "description": "Team data for create/update operations",
                },
                "page": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Page number for pagination",
                },
                "size": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Number of items per page",
                },
                "filters": {"type": "object", "description": "Additional filters"},
            },
            "required": ["action"],
        }

    def _build_alerts_schema(self) -> Dict[str, Any]:
        """Build JSON schema for manage_alerts tool."""
        return {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "Manage Alerts Parameters",
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list",
                        "get",
                        "create",
                        "update",
                        "delete",
                        "clear_all",
                        "get_metrics",
                        "query",
                        "bulk_update",
                        "analytics",
                        "create_from_text",
                        "get_capabilities",
                        "get_examples",
                        "validate",
                        "get_agent_summary",
                        "test_cumulative_usage",
                        "create_budget_alert",
                        "create_simple",
                        "list_metrics",
                        "enable",
                        "disable",
                        "enable_multiple",
                        "disable_multiple",
                        "enable_all",
                        "disable_all",
                        "toggle_status",
                        "get_status",
                        "create_cumulative_usage_alert",
                        "create_threshold_alert",
                    ],
                    "description": "Action to perform on alerts/anomalies",
                },
                "resource_type": {
                    "type": "string",
                    "enum": ["anomalies", "alerts"],
                    "description": "Type of alert resource",
                },
                "anomaly_id": {
                    "type": "string",
                    "pattern": "^[a-zA-Z0-9_-]+$",
                    "description": "Anomaly ID",
                },
                "alert_id": {
                    "type": "string",
                    "pattern": "^[a-zA-Z0-9_-]+$",
                    "description": "Alert ID",
                },
                "anomaly_data": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "minLength": 2,
                            "maxLength": 255,
                            "description": "Alert/anomaly name",
                        },
                        "description": {
                            "type": "string",
                            "maxLength": 2000,
                            "description": "Alert/anomaly description",
                        },
                        "alertType": {
                            "type": "string",
                            "enum": ["THRESHOLD", "CUMULATIVE_USAGE", "RELATIVE_CHANGE"],
                            "description": "Type of alert",
                        },
                        "enabled": {
                            "type": "boolean",
                            "description": "Whether the alert is enabled",
                        },
                        "notificationAddresses": {
                            "type": "array",
                            "items": {"type": "string", "format": "email"},
                            "description": "Email addresses for notifications",
                        },
                        "detection_rules": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "rule_type": {
                                        "type": "string",
                                        "enum": [
                                            "THRESHOLD",
                                            "CUMULATIVE_USAGE",
                                            "RELATIVE_CHANGE",
                                        ],
                                    },
                                    "metric": {
                                        "type": "string",
                                        "enum": [
                                            "total_cost",
                                            "cost_per_transaction",
                                            "token_count",
                                            "input_tokens",
                                            "output_tokens",
                                            "requests_per_second",
                                            "error_rate",
                                        ],
                                    },
                                    "operator": {
                                        "type": "string",
                                        "enum": [">=", ">", "<=", "<", "==", "!="],
                                    },
                                    "value": {"type": "number", "minimum": 0},
                                    "time_window": {
                                        "type": "string",
                                        "enum": [
                                            "daily",
                                            "weekly",
                                            "monthly",
                                            "quarterly",
                                            "1m",
                                            "5m",
                                            "15m",
                                            "30m",
                                            "1h",
                                            "2h",
                                            "4h",
                                            "8h",
                                            "12h",
                                            "1d",
                                            "7d",
                                            "30d",
                                        ],
                                    },
                                },
                                "required": ["rule_type", "metric", "operator", "value"],
                            },
                            "description": "Detection rules for the alert",
                        },
                        "filters": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "dimension": {
                                        "type": "string",
                                        "enum": [
                                            "PRODUCT",
                                            "ORGANIZATION",
                                            "SUBSCRIBER",
                                            "MODEL",
                                            "PROVIDER",
                                            "TASK_TYPE",
                                            "TRACE_ID",
                                            "SUBSCRIPTION_ID",
                                            "PRODUCT_ID",
                                            "AGENT",
                                            "SUBSCRIBER_CREDENTIAL_NAME",
                                            "SUBSCRIBER_CREDENTIAL",
                                        ],
                                        "description": "Filter dimension to apply",
                                    },
                                    "operator": {
                                        "type": "string",
                                        "enum": [
                                            "IS",
                                            "IS_NOT",
                                            "CONTAINS",
                                            "STARTS_WITH",
                                            "ENDS_WITH",
                                        ],
                                        "description": "Filter operator",
                                    },
                                    "value": {
                                        "type": "string",
                                        "minLength": 1,
                                        "description": "Filter value to match against",
                                    },
                                },
                                "required": ["dimension", "operator", "value"],
                                "additionalProperties": False,
                            },
                            "description": "Array of filter objects to scope alerts to specific dimensions",
                        },
                    },
                    "description": "Alert/anomaly data",
                },
                "page": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Page number for pagination",
                },
                "size": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Number of items per page",
                },
                "filters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "dimension": {
                                "type": "string",
                                "enum": [
                                    "PRODUCT",
                                    "ORGANIZATION",
                                    "SUBSCRIBER",
                                    "MODEL",
                                    "PROVIDER",
                                    "TASK_TYPE",
                                    "TRACE_ID",
                                    "SUBSCRIPTION_ID",
                                    "PRODUCT_ID",
                                    "AGENT",
                                    "SUBSCRIBER_CREDENTIAL_NAME",
                                    "SUBSCRIBER_CREDENTIAL",
                                ],
                                "description": "Filter dimension to apply",
                            },
                            "operator": {
                                "type": "string",
                                "enum": ["IS", "IS_NOT", "CONTAINS", "STARTS_WITH", "ENDS_WITH"],
                                "description": "Filter operator",
                            },
                            "value": {
                                "type": "string",
                                "minLength": 1,
                                "description": "Filter value to match against",
                            },
                        },
                        "required": ["dimension", "operator", "value"],
                        "additionalProperties": False,
                    },
                    "description": "Array of filter objects to scope alerts to specific dimensions. Each filter contains dimension, operator, and value.",
                },
                "query": {"type": "string", "description": "Natural language query for alerts"},
                "metric": {
                    "type": "string",
                    "enum": [
                        "TOTAL_COST",
                        "COST_PER_TRANSACTION",
                        "TOKEN_COUNT",
                        "INPUT_TOKEN_COUNT",
                        "OUTPUT_TOKEN_COUNT",
                        "CACHED_TOKEN_COUNT",
                        "TOKENS_PER_SECOND",
                        "REQUESTS_PER_SECOND",
                        "ERROR_RATE",
                        "ERROR_COUNT",
                    ],
                    "description": "Metric type for get_examples action",
                },
                "anomaly_ids": {
                    "type": "array",
                    "items": {"type": "string", "pattern": "^[a-zA-Z0-9_-]+$"},
                    "description": "List of anomaly IDs for bulk operations",
                },
                "confirm": {
                    "type": "boolean",
                    "description": "Confirmation flag for bulk operations (enable_all, disable_all)",
                },
                "text": {
                    "type": "string",
                    "description": "Natural language description for enable/disable operations",
                },
                "name": {
                    "type": "string",
                    "description": "Alert name for enhanced creation methods",
                },
                "threshold": {
                    "anyOf": [{"type": "number", "minimum": 0}, {"type": "string"}],
                    "description": "Alert threshold value",
                },
                "period": {
                    "type": "string",
                    "description": "Period for budget threshold alerts (daily, weekly, monthly, quarterly)",
                },
                "period_minutes": {
                    "anyOf": [{"type": "number", "minimum": 1}, {"type": "string"}],
                    "description": "Period in minutes for spike detection alerts",
                },
                "email": {
                    "type": "string",
                    "format": "email",
                    "description": "Notification email address",
                },

                "alert_type": {
                    "type": "string",
                    "enum": ["cumulative_usage", "threshold"],
                    "description": "Alert type for get_examples action to show specific examples",
                },
            },
            "required": ["action"],
        }

    def _build_workflows_schema(self) -> Dict[str, Any]:
        """Build JSON schema for manage_workflows tool."""
        return {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "Manage Workflows Parameters",
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list",
                        "get",
                        "start",
                        "next_step",
                        "complete_step",
                        "get_capabilities",
                        "get_examples",
                        "validate",
                        "get_agent_summary",
                        "create_simple",
                        "create_from_text",
                    ],
                    "description": "Action to perform on workflows",
                },
                "workflow_id": {
                    "type": "string",
                    "pattern": "^[a-zA-Z0-9_-]+$",
                    "description": "Workflow ID",
                },
                "workflow_type": {
                    "type": "string",
                    "enum": [
                        "customer_onboarding",
                        "product_launch",
                        "alert_setup",
                        "data_pipeline",
                        "subscription_management",
                    ],
                    "description": "Type of workflow for create_simple action",
                },
                "customer_email": {
                    "type": "string",
                    "format": "email",
                    "description": "Customer email for workflow context",
                },
                "organization_name": {
                    "type": "string",
                    "description": "Organization name for workflow context",
                },
                "product_name": {
                    "type": "string",
                    "description": "Product name for workflow context",
                },
                "context": {
                    "type": "object",
                    "description": "Initial context data for workflow execution",
                },
                "step_result": {"type": "object", "description": "Result data from completed step"},
                "text": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 1000,
                    "description": "Natural language description for create_from_text action",
                },
                "name": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 200,
                    "description": "Workflow name for create_simple action",
                },
                "description": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 500,
                    "description": "Workflow description for create_simple action",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Validate only without creating for validate action",
                },
            },
            "required": ["action"],
        }


# Global validator instance
json_schema_validator = JSONSchemaValidator()
