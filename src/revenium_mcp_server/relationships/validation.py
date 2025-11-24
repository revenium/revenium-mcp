"""Cross-Resource Validation.

This module provides validation capabilities for cross-resource operations
to ensure data integrity and relationship consistency.
"""

from datetime import datetime
from typing import Any, Dict, List

from loguru import logger


class ValidationRule:
    """Represents a validation rule for cross-resource operations."""

    def __init__(self, name: str, description: str, rule_type: str, severity: str = "error"):
        """Initialize a validation rule.

        Args:
            name: Name of the rule
            description: Description of what the rule validates
            rule_type: Type of rule (dependency, integrity, business)
            severity: Severity level (error, warning, info)
        """
        self.name = name
        self.description = description
        self.rule_type = rule_type
        self.severity = severity

    def validate(self, operation: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Validate an operation against this rule.

        Args:
            operation: Operation to validate
            context: Validation context

        Returns:
            Validation result
        """
        # Base implementation - subclasses should override
        return {"rule_name": self.name, "passed": True, "message": "Base rule validation passed"}


class DependencyValidationRule(ValidationRule):
    """Validates dependency relationships between resources."""

    def __init__(self):
        super().__init__(
            name="dependency_validation",
            description="Validates that required dependencies exist and are valid",
            rule_type="dependency",
            severity="error",
        )

    def validate(self, operation: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Validate dependency requirements."""
        resource_type = operation.get("resource_type")
        resource_data = operation.get("resource_data", {})

        # Check for required dependencies based on resource type
        required_deps = self._get_required_dependencies(resource_type)
        missing_deps = []

        for dep_field, dep_type in required_deps.items():
            if dep_field in resource_data:
                dep_value = resource_data[dep_field]
                if not dep_value or (isinstance(dep_value, list) and len(dep_value) == 0):
                    missing_deps.append(
                        {
                            "field": dep_field,
                            "type": dep_type,
                            "message": f"Required {dep_type} reference is missing",
                        }
                    )

        if missing_deps:
            return {
                "rule_name": self.name,
                "passed": False,
                "severity": self.severity,
                "message": f"Missing required dependencies for {resource_type}",
                "missing_dependencies": missing_deps,
                "suggestions": [
                    f"Ensure {dep['field']} references a valid {dep['type']}"
                    for dep in missing_deps
                ],
            }

        return {
            "rule_name": self.name,
            "passed": True,
            "message": "All required dependencies are present",
        }

    def _get_required_dependencies(self, resource_type: str) -> Dict[str, str]:
        """Get required dependencies for a resource type.

        Args:
            resource_type: Type of resource

        Returns:
            Dictionary mapping field names to dependency types
        """
        dependency_map = {
            "subscriptions": {"product_id": "products"},
            "alerts": {"organization_id": "organizations"},
            "teams": {"organization_id": "organizations"},
            "users": {"organization_id": "organizations"},
        }

        return dependency_map.get(resource_type, {})


class IntegrityValidationRule(ValidationRule):
    """Validates data integrity across related resources."""

    def __init__(self):
        super().__init__(
            name="integrity_validation",
            description="Validates data integrity and consistency across related resources",
            rule_type="integrity",
            severity="warning",
        )

    def validate(self, operation: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Validate data integrity."""
        resource_type = operation.get("resource_type")
        resource_data = operation.get("resource_data", {})

        integrity_issues = []

        # Check for common integrity issues
        if resource_type == "products":
            # Validate product-specific integrity
            if "source_ids" in resource_data:
                source_ids = resource_data["source_ids"]
                if isinstance(source_ids, list) and len(source_ids) > 10:
                    integrity_issues.append(
                        {
                            "field": "source_ids",
                            "issue": "Too many source references",
                            "message": "Products with more than 10 sources may have performance issues",
                        }
                    )

        elif resource_type == "subscriptions":
            # Validate subscription-specific integrity
            start_date = resource_data.get("start_date")
            end_date = resource_data.get("end_date")

            if start_date and end_date:
                try:
                    if isinstance(start_date, str):
                        start_date = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
                    if isinstance(end_date, str):
                        end_date = datetime.fromisoformat(end_date.replace("Z", "+00:00"))

                    if end_date <= start_date:
                        integrity_issues.append(
                            {
                                "field": "end_date",
                                "issue": "Invalid date range",
                                "message": "End date must be after start date",
                            }
                        )
                except ValueError:
                    integrity_issues.append(
                        {
                            "field": "dates",
                            "issue": "Invalid date format",
                            "message": "Dates must be in ISO format",
                        }
                    )

        if integrity_issues:
            return {
                "rule_name": self.name,
                "passed": False,
                "severity": self.severity,
                "message": f"Data integrity issues found for {resource_type}",
                "integrity_issues": integrity_issues,
                "suggestions": [
                    f"Fix {issue['field']}: {issue['message']}" for issue in integrity_issues
                ],
            }

        return {
            "rule_name": self.name,
            "passed": True,
            "message": "Data integrity validation passed",
        }


class BusinessRuleValidationRule(ValidationRule):
    """Validates business rules and constraints."""

    def __init__(self):
        super().__init__(
            name="business_rule_validation",
            description="Validates business rules and organizational constraints",
            rule_type="business",
            severity="error",
        )

    def validate(self, operation: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Validate business rules."""
        resource_type = operation.get("resource_type")
        resource_data = operation.get("resource_data", {})
        operation_type = operation.get("type", "create")

        business_violations = []

        # Check business rules based on resource type
        if resource_type == "products":
            # Product business rules
            name = resource_data.get("name", "")
            if len(name) < 3:
                business_violations.append(
                    {
                        "rule": "product_name_length",
                        "message": "Product name must be at least 3 characters long",
                    }
                )

            # Check for duplicate names (would need context from existing products)
            existing_products = context.get("existing_products", [])
            if any(p.get("name") == name for p in existing_products):
                business_violations.append(
                    {
                        "rule": "product_name_uniqueness",
                        "message": f"Product name '{name}' already exists",
                    }
                )

        elif resource_type == "subscriptions":
            # Subscription business rules
            if operation_type == "create":
                product_id = resource_data.get("product_id")
                if not product_id:
                    business_violations.append(
                        {
                            "rule": "subscription_product_required",
                            "message": "Subscriptions must be associated with a product",
                        }
                    )

        elif resource_type == "alerts":
            # Alert business rules
            threshold = resource_data.get("threshold")
            if threshold is not None:
                try:
                    threshold_value = float(threshold)
                    if threshold_value <= 0:
                        business_violations.append(
                            {
                                "rule": "alert_threshold_positive",
                                "message": "Alert threshold must be a positive number",
                            }
                        )
                except (ValueError, TypeError):
                    business_violations.append(
                        {
                            "rule": "alert_threshold_numeric",
                            "message": "Alert threshold must be a valid number",
                        }
                    )

        if business_violations:
            return {
                "rule_name": self.name,
                "passed": False,
                "severity": self.severity,
                "message": f"Business rule violations found for {resource_type}",
                "business_violations": business_violations,
                "suggestions": [
                    f"Fix business rule: {violation['message']}"
                    for violation in business_violations
                ],
            }

        return {
            "rule_name": self.name,
            "passed": True,
            "message": "Business rule validation passed",
        }


class CrossResourceValidator:
    """Validates cross-resource operations and relationships."""

    def __init__(self):
        """Initialize the cross-resource validator."""
        self.rules = [
            DependencyValidationRule(),
            IntegrityValidationRule(),
            BusinessRuleValidationRule(),
        ]
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the validator."""
        if self._initialized:
            return

        logger.info("Initializing Cross-Resource Validator")
        self._initialized = True
        logger.info("Cross-Resource Validator initialized successfully")

    async def validate_operation(self, operation: Dict[str, Any]) -> Dict[str, Any]:
        """Validate a cross-resource operation.

        Args:
            operation: Operation to validate

        Returns:
            Validation result
        """
        try:
            # Build validation context
            context = await self._build_validation_context(operation)

            # Run all validation rules
            validation_results = []
            errors = []
            warnings = []

            for rule in self.rules:
                try:
                    result = rule.validate(operation, context)
                    validation_results.append(result)

                    if not result.get("passed", True):
                        if result.get("severity") == "error":
                            errors.append(result)
                        elif result.get("severity") == "warning":
                            warnings.append(result)

                except Exception as e:
                    logger.error(f"Error running validation rule {rule.name}: {e}")
                    errors.append(
                        {
                            "rule_name": rule.name,
                            "passed": False,
                            "severity": "error",
                            "message": f"Validation rule failed: {str(e)}",
                        }
                    )

            # Determine overall validation status
            overall_passed = len(errors) == 0

            return {
                "validation_passed": overall_passed,
                "has_warnings": len(warnings) > 0,
                "error_count": len(errors),
                "warning_count": len(warnings),
                "errors": errors,
                "warnings": warnings,
                "all_results": validation_results,
                "operation": operation,
                "recommendations": self._generate_recommendations(errors, warnings),
            }

        except Exception as e:
            logger.error(f"Error during cross-resource validation: {e}")
            return {
                "validation_passed": False,
                "error_count": 1,
                "warning_count": 0,
                "errors": [
                    {
                        "rule_name": "validation_system",
                        "passed": False,
                        "severity": "error",
                        "message": f"Validation system error: {str(e)}",
                    }
                ],
                "warnings": [],
                "operation": operation,
            }

    async def _build_validation_context(self, operation: Dict[str, Any]) -> Dict[str, Any]:
        """Build validation context for the operation.

        Args:
            operation: Operation being validated

        Returns:
            Validation context dictionary
        """
        # In a real implementation, this would fetch related data
        # For now, return a basic context
        return {
            "timestamp": datetime.now().isoformat(),
            "operation_id": operation.get("id", "unknown"),
            "existing_products": [],  # Would be fetched from API
            "existing_sources": [],  # Would be fetched from API
            "user_permissions": {},  # Would be fetched from auth system
        }

    def _generate_recommendations(
        self, errors: List[Dict[str, Any]], warnings: List[Dict[str, Any]]
    ) -> List[str]:
        """Generate recommendations based on validation results.

        Args:
            errors: List of validation errors
            warnings: List of validation warnings

        Returns:
            List of recommendation strings
        """
        recommendations = []

        if errors:
            recommendations.append("Fix all validation errors before proceeding")
            for error in errors:
                if "suggestions" in error:
                    recommendations.extend(error["suggestions"])

        if warnings:
            recommendations.append("Consider addressing validation warnings")
            for warning in warnings:
                if "suggestions" in warning:
                    recommendations.extend(warning["suggestions"])

        if not errors and not warnings:
            recommendations.append("Operation validation passed - safe to proceed")

        return recommendations


# Global validator instance
relationship_validator = CrossResourceValidator()
