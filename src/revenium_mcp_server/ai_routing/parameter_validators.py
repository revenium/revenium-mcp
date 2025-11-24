"""Parameter validation functions for extracted values.

This module contains validation functions to ensure extracted parameters
meet quality and format requirements.
"""

import re
from typing import Any, Dict, List, Optional


class ParameterValidators:
    """Manages parameter validation functions."""

    def validate_parameters(
        self,
        parameters: Dict[str, Any],
        required_parameters: List[str],
        operation_context: Optional[str] = None,
    ) -> List[str]:
        """Validate extracted parameters against requirements with enhanced validation.

        Args:
            parameters: Extracted parameters
            required_parameters: List of required parameter names
            operation_context: Context about the operation (e.g., "products.create")

        Returns:
            List of validation error messages
        """
        errors = []

        # Check for missing required parameters
        errors.extend(self._check_missing_required(parameters, required_parameters))

        # Type-specific validation
        errors.extend(self._validate_parameter_types(parameters))

        # Operation-specific validation
        if operation_context:
            errors.extend(self._validate_operation_context(parameters, operation_context))

        return errors

    def _check_missing_required(
        self, parameters: Dict[str, Any], required_parameters: List[str]
    ) -> List[str]:
        """Check for missing required parameters."""
        errors = []
        for param in required_parameters:
            if param not in parameters or parameters[param] is None:
                errors.append(f"Missing required parameter: {param}")
        return errors

    def _validate_parameter_types(self, parameters: Dict[str, Any]) -> List[str]:
        """Validate parameter types and formats."""
        errors = []

        for param, value in parameters.items():
            if value is None:
                continue

            # Email validation
            if param == "email" and value:
                if not self._validate_email(str(value)):
                    errors.append(f"Invalid email format: {value}")

            # Amount validation
            elif param == "amount" and value is not None:
                if not self._validate_amount(value):
                    errors.append(f"Invalid amount format or value: {value}")

            # Name validation
            elif param == "name" and value:
                if not self._validate_name(str(value)):
                    errors.append(f"Invalid name format: {value}")

            # ID validation
            elif param == "id" and value:
                if not self._validate_id(str(value)):
                    errors.append(f"Invalid ID format: {value}")

            # Product type validation
            elif param == "product_type" and value:
                if not self._validate_product_type(str(value)):
                    errors.append(
                        f"Invalid product type: {value}. Must be one of: api, usage, subscription, metering"
                    )

            # Workflow type validation
            elif param == "workflow_type" and value:
                if not self._validate_workflow_type(str(value)):
                    errors.append(
                        f"Invalid workflow type: {value}. Must be one of: subscription_setup, customer_onboarding, product_creation"
                    )

        return errors

    def _validate_operation_context(
        self, parameters: Dict[str, Any], operation_context: str
    ) -> List[str]:
        """Validate parameters against specific operation requirements."""
        errors = []

        if operation_context == "products.create":
            if "name" not in parameters:
                errors.append("Product creation requires a name parameter")

        elif operation_context == "customers.create":
            if "email" not in parameters:
                errors.append("Customer creation requires an email parameter")

        elif operation_context == "workflows.start":
            if "workflow_type" not in parameters:
                errors.append("Workflow start requires a workflow_type parameter")

        return errors

    def _validate_email(self, email: str) -> bool:
        """Enhanced email validation."""
        email_pattern = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
        return bool(email_pattern.match(email))

    def _validate_amount(self, amount: Any) -> bool:
        """Enhanced amount validation."""
        try:
            float_val = float(amount)
            return 0 <= float_val <= 1000000  # Reasonable limits
        except (ValueError, TypeError):
            return False

    def _validate_name(self, name: str) -> bool:
        """Enhanced name validation."""
        return 1 <= len(name.strip()) <= 100 and name.strip() != ""

    def _validate_id(self, id_value: str) -> bool:
        """Enhanced ID validation."""
        return bool(re.match(r"^[a-zA-Z0-9_-]+$", id_value)) and len(id_value) >= 1

    def _validate_product_type(self, product_type: str) -> bool:
        """Validate product type against allowed values."""
        allowed_types = {"api", "usage", "subscription", "metering"}
        return product_type.lower() in allowed_types

    def _validate_workflow_type(self, workflow_type: str) -> bool:
        """Validate workflow type against allowed values."""
        allowed_types = {"subscription_setup", "customer_onboarding", "product_creation"}
        return workflow_type.lower() in allowed_types
