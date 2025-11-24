"""Parameter mapping for converting AI routing parameters to tool-specific formats.

This module handles the transformation of extracted parameters from natural language
queries into the specific parameter formats expected by different MCP tools.
"""

# Standard library imports
from typing import Any, Dict, List

# Third-party imports
from loguru import logger

# Local imports
from .models import ExtractedParameters


class ParameterMappingError(Exception):
    """Exception raised when parameter mapping fails."""

    pass


class ParameterMapper:
    """Maps extracted parameters to tool-specific parameter formats."""

    def __init__(self):
        """Initialize parameter mapper with operation mappings."""
        self.operation_mappings = self._build_operation_mappings()

    def _build_operation_mappings(self) -> Dict[str, Dict[str, Any]]:
        """Build parameter mapping configurations for each operation."""
        mappings = {}

        # Build mappings for each operation type
        mappings.update(self._build_product_mappings())
        mappings.update(self._build_customer_mappings())
        mappings.update(self._build_workflow_mappings())
        mappings.update(self._build_alert_mappings())
        mappings.update(self._build_subscription_mappings())

        return mappings

    def _build_product_mappings(self) -> Dict[str, Dict[str, Any]]:
        """Build parameter mappings for product operations."""
        return {
            "products.create": {
                "required_params": ["name"],
                "optional_params": ["product_type", "description"],
                "parameter_transformations": {
                    "name": "product_data.name",
                    "product_type": "product_data.type",
                    "description": "product_data.description",
                },
                "defaults": {
                    "product_data.type": "api",
                    "product_data.description": lambda params: f"Product created via AI routing: {params.get('name', 'Unknown')}",
                },
            }
        }

    def _build_customer_mappings(self) -> Dict[str, Dict[str, Any]]:
        """Build parameter mappings for customer operations."""
        return {
            "customers.create": {
                "required_params": ["email"],
                "optional_params": ["name", "organization_name"],
                "parameter_transformations": {
                    "email": "subscriber_data.email",
                    "name": "subscriber_data.name",
                    "organization_name": "organization_data.name",
                },
                "defaults": {
                    "resource_type": "subscribers",
                    "subscriber_data.role": "ROLE_API_CONSUMER",
                    "subscriber_data.name": lambda params: params.get("email", "").split("@")[0],
                },
            }
        }

    def _build_workflow_mappings(self) -> Dict[str, Dict[str, Any]]:
        """Build parameter mappings for workflow operations."""
        return {
            "workflows.start": {
                "required_params": ["workflow_type"],
                "optional_params": ["context"],
                "parameter_transformations": {
                    "workflow_type": "workflow_type",
                    "context": "context",
                },
                "defaults": {"context": {}},
            }
        }

    def _build_alert_mappings(self) -> Dict[str, Dict[str, Any]]:
        """Build parameter mappings for alert operations."""
        return {
            "alerts.list": {
                "required_params": [],
                "optional_params": ["time_period", "status", "page", "size"],
                "parameter_transformations": {
                    "time_period": "filters.time_period",
                    "status": "filters.status",
                    "page": "page",
                    "size": "size",
                },
                "defaults": {"page": 0, "size": 20},
            }
        }

    def _build_subscription_mappings(self) -> Dict[str, Dict[str, Any]]:
        """Build parameter mappings for subscription operations."""
        return {
            "subscriptions.list": {
                "required_params": [],
                "optional_params": ["status", "customer_email", "page", "size"],
                "parameter_transformations": {
                    "status": "filters.status",
                    "customer_email": "filters.customer_email",
                    "page": "page",
                    "size": "size",
                },
                "defaults": {"page": 0, "size": 20},
            }
        }

    def map_parameters(
        self, operation_key: str, extracted_params: ExtractedParameters
    ) -> Dict[str, Any]:
        """Map extracted parameters to tool-specific format.

        Args:
            operation_key: Operation identifier (e.g., 'products.create')
            extracted_params: Parameters extracted from natural language

        Returns:
            Mapped parameters ready for tool execution

        Raises:
            ParameterMappingError: If mapping fails
        """
        if operation_key not in self.operation_mappings:
            return self._map_generic_parameters(extracted_params)

        mapping_config = self.operation_mappings[operation_key]
        mapped_params = {"action": operation_key.split(".")[1]}

        # Apply parameter transformations
        transformed_params = self._apply_transformations(
            extracted_params.parameters, mapping_config
        )

        # Apply defaults
        final_params = self._apply_defaults(
            transformed_params, mapping_config, extracted_params.parameters
        )

        mapped_params.update(final_params)

        logger.debug(f"Mapped parameters for {operation_key}: {mapped_params}")
        return mapped_params

    def _apply_transformations(
        self, params: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply parameter transformations based on configuration."""
        transformed = {}
        transformations = config.get("parameter_transformations", {})

        for source_param, target_path in transformations.items():
            if source_param in params and params[source_param] is not None:
                self._set_nested_value(transformed, target_path, params[source_param])

        return transformed

    def _apply_defaults(
        self, params: Dict[str, Any], config: Dict[str, Any], original_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply default values based on configuration."""
        defaults = config.get("defaults", {})

        for default_path, default_value in defaults.items():
            if not self._has_nested_value(params, default_path):
                # Handle callable defaults
                if callable(default_value):
                    value = default_value(original_params)
                else:
                    value = default_value

                self._set_nested_value(params, default_path, value)

        return params

    def _set_nested_value(self, data: Dict[str, Any], path: str, value: Any) -> None:
        """Set a nested value using dot notation path."""
        keys = path.split(".")
        current = data

        # Navigate to the parent of the target key
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]

        # Set the final value
        current[keys[-1]] = value

    def _has_nested_value(self, data: Dict[str, Any], path: str) -> bool:
        """Check if a nested value exists using dot notation path."""
        keys = path.split(".")
        current = data

        try:
            for key in keys:
                current = current[key]
            return True
        except (KeyError, TypeError):
            return False

    def _map_generic_parameters(self, extracted_params: ExtractedParameters) -> Dict[str, Any]:
        """Map parameters for operations without specific mapping configuration."""
        mapped_params = {}

        # Copy all extracted parameters directly
        for param_name, param_value in extracted_params.parameters.items():
            if param_value is not None:
                mapped_params[param_name] = param_value

        return mapped_params

    def get_required_parameters(self, operation_key: str) -> List[str]:
        """Get required parameters for an operation."""
        if operation_key not in self.operation_mappings:
            return []

        return self.operation_mappings[operation_key].get("required_params", [])

    def get_optional_parameters(self, operation_key: str) -> List[str]:
        """Get optional parameters for an operation."""
        if operation_key not in self.operation_mappings:
            return []

        return self.operation_mappings[operation_key].get("optional_params", [])

    def validate_parameters(
        self, operation_key: str, extracted_params: ExtractedParameters
    ) -> List[str]:
        """Validate that required parameters are present."""
        required_params = self.get_required_parameters(operation_key)
        missing_params = []

        for param in required_params:
            if (
                param not in extracted_params.parameters
                or extracted_params.parameters[param] is None
            ):
                missing_params.append(param)

        return missing_params
