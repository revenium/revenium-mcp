"""Error Library with Common Error Patterns and Examples.

This module provides a comprehensive library of common error patterns,
examples, and recovery guidance for MCP tools.
"""

from typing import Any, Dict, List, Optional

from .unified_error_handler import ErrorCategory, ErrorSeverity, StandardizedError


class ErrorLibrary:
    """Library of common error patterns with examples and guidance."""

    @staticmethod
    def missing_action_error(valid_actions: List[str]) -> StandardizedError:
        """Error for missing action parameter."""
        return StandardizedError(
            message="Missing required parameter: action",
            error_code="MISSING_ACTION",
            category=ErrorCategory.VALIDATION,
            field_errors={"action": "This parameter is required"},
            suggestions=[
                "Specify an action parameter in your request",
                f"Valid actions: {', '.join(valid_actions)}",
                "Use get_capabilities() to see all available actions",
            ],
            examples={"valid_request": {"action": valid_actions[0] if valid_actions else "list"}},
            recovery_actions=[
                "Add an 'action' parameter to your request",
                "Choose from the valid actions listed above",
            ],
        )

    @staticmethod
    def invalid_action_error(provided_action: str, valid_actions: List[str]) -> StandardizedError:
        """Error for invalid action parameter."""
        return StandardizedError(
            message=f"Invalid action: {provided_action}",
            error_code="INVALID_ACTION",
            category=ErrorCategory.VALIDATION,
            field_errors={"action": f"'{provided_action}' is not a valid action"},
            suggestions=[
                f"Use one of the valid actions: {', '.join(valid_actions)}",
                "Check the spelling of your action parameter",
                "Use get_capabilities() to see all available actions",
            ],
            examples={"valid_request": {"action": valid_actions[0] if valid_actions else "list"}},
            recovery_actions=[
                f"Change 'action' to one of: {', '.join(valid_actions)}",
                "Retry with a valid action",
            ],
        )

    @staticmethod
    def missing_id_error(id_field: str, resource_type: str) -> StandardizedError:
        """Error for missing ID parameter."""
        return StandardizedError(
            message=f"Missing required parameter: {id_field}",
            error_code="MISSING_ID",
            category=ErrorCategory.VALIDATION,
            field_errors={id_field: f"{resource_type} ID is required for this operation"},
            suggestions=[
                f"Provide the {id_field} parameter",
                f"Use list() to see available {resource_type} IDs",
                "Ensure you're using the correct ID format",
            ],
            examples={"valid_request": {id_field: f"{resource_type.lower()}_123"}},
            recovery_actions=[
                f"Add the '{id_field}' parameter to your request",
                f"Get a valid ID from the list() action",
            ],
        )

    @staticmethod
    def resource_not_found_error(resource_type: str, resource_id: str) -> StandardizedError:
        """Error for resource not found."""
        return StandardizedError(
            message=f"{resource_type} not found: {resource_id}",
            error_code="RESOURCE_NOT_FOUND",
            category=ErrorCategory.NOT_FOUND,
            suggestions=[
                f"Verify the {resource_type} ID is correct",
                f"Check if the {resource_type} was deleted",
                f"Use list() to see available {resource_type}s",
                "Ensure you have permission to access this resource",
            ],
            context={"resource_type": resource_type, "resource_id": resource_id},
            recovery_actions=[
                f"Use list() to find the correct {resource_type} ID",
                "Create the resource if it doesn't exist",
            ],
        )

    @staticmethod
    def authentication_error() -> StandardizedError:
        """Error for authentication failures."""
        return StandardizedError(
            message="Authentication failed",
            error_code="AUTHENTICATION_FAILED",
            category=ErrorCategory.AUTHENTICATION,
            severity=ErrorSeverity.ERROR,
            suggestions=[
                "Check your API key is correct",
                "Verify your credentials haven't expired",
                "Ensure you're using the correct authentication method",
                "Check environment variables are set correctly",
            ],
            examples={
                "environment_setup": {
                    "REVENIUM_API_KEY": "your_api_key_here",
                    "REVENIUM_TEAM_ID": "your_team_id",
                    "REVENIUM_OWNER_ID": "your_owner_id",
                }
            },
            recovery_actions=[
                "Update your API credentials",
                "Re-authenticate and retry the operation",
            ],
        )

    @staticmethod
    def permission_denied_error(operation: str, resource: str) -> StandardizedError:
        """Error for permission denied."""
        return StandardizedError(
            message=f"Permission denied for operation '{operation}' on resource '{resource}'",
            error_code="PERMISSION_DENIED",
            category=ErrorCategory.AUTHORIZATION,
            suggestions=[
                "Check if you have the required permissions",
                "Verify your team membership",
                "Contact your administrator for access",
                "Ensure you're using the correct team ID",
            ],
            context={"operation": operation, "resource": resource},
            recovery_actions=[
                "Request the necessary permissions from your administrator",
                "Verify you're operating within your team's scope",
            ],
        )

    @staticmethod
    def rate_limit_error(retry_after: Optional[int] = None) -> StandardizedError:
        """Error for rate limiting."""
        message = "Rate limit exceeded"
        if retry_after:
            message += f". Retry after {retry_after} seconds"

        suggestions = [
            "Reduce the frequency of your requests",
            "Implement exponential backoff in your application",
            "Consider batching operations where possible",
        ]

        recovery_actions = ["Wait before retrying the request"]

        if retry_after:
            suggestions.append(f"Wait at least {retry_after} seconds before retrying")
            recovery_actions.append(f"Wait {retry_after} seconds and retry")
        else:
            suggestions.append("Wait 60 seconds before retrying")
            recovery_actions.append("Wait 60 seconds and retry")

        context = {}
        if retry_after:
            context["retry_after_seconds"] = retry_after

        return StandardizedError(
            message=message,
            error_code="RATE_LIMIT_EXCEEDED",
            category=ErrorCategory.RATE_LIMIT,
            suggestions=suggestions,
            context=context,
            recovery_actions=recovery_actions,
        )

    @staticmethod
    def validation_failed_error(
        field_errors: Dict[str, str], examples: Optional[Dict[str, Any]] = None
    ) -> StandardizedError:
        """Error for validation failures."""
        return StandardizedError(
            message="Validation failed",
            error_code="VALIDATION_FAILED",
            category=ErrorCategory.VALIDATION,
            field_errors=field_errors,
            suggestions=[
                "Fix the validation errors listed above",
                "Check the field formats and requirements",
                "Use get_examples() to see working configurations",
                "Use validate() with dry_run=True to test your data",
            ],
            examples=examples,
            recovery_actions=["Correct the invalid fields", "Retry with valid data"],
        )

    @staticmethod
    def configuration_error(
        setting_name: str, issue: str, suggestions: Optional[List[str]] = None
    ) -> StandardizedError:
        """Error for configuration issues."""
        default_suggestions = [
            f"Check the '{setting_name}' configuration",
            "Verify all required settings are provided",
            "Use get_capabilities() to see configuration requirements",
        ]

        return StandardizedError(
            message=f"Configuration error for '{setting_name}': {issue}",
            error_code="CONFIGURATION_ERROR",
            category=ErrorCategory.CONFIGURATION,
            suggestions=suggestions or default_suggestions,
            context={"setting_name": setting_name, "issue": issue},
            recovery_actions=[
                f"Fix the '{setting_name}' configuration",
                "Retry with correct settings",
            ],
        )

    @staticmethod
    def business_rule_violation_error(
        rule_name: str, violation: str, suggestions: Optional[List[str]] = None
    ) -> StandardizedError:
        """Error for business rule violations."""
        default_suggestions = [
            f"Review the '{rule_name}' business rule requirements",
            "Adjust your request to comply with business rules",
            "Contact support if you need clarification on the rules",
        ]

        return StandardizedError(
            message=f"Business rule violation: {violation}",
            error_code="BUSINESS_RULE_VIOLATION",
            category=ErrorCategory.BUSINESS_RULE,
            suggestions=suggestions or default_suggestions,
            context={"rule_name": rule_name, "violation": violation},
            recovery_actions=[
                "Modify your request to comply with business rules",
                "Retry with compliant data",
            ],
        )

    @staticmethod
    def system_error(operation: str, details: Optional[str] = None) -> StandardizedError:
        """Error for system-level issues."""
        message = f"System error during {operation}"
        if details:
            message += f": {details}"

        return StandardizedError(
            message=message,
            error_code="SYSTEM_ERROR",
            category=ErrorCategory.SYSTEM,
            severity=ErrorSeverity.CRITICAL,
            suggestions=[
                "Try the operation again in a few moments",
                "Check the system status page",
                "Contact support if the issue persists",
            ],
            context={"operation": operation, "details": details},
            recovery_actions=[
                "Retry the operation after a short delay",
                "Contact technical support if the error continues",
            ],
        )


class ErrorExamples:
    """Library of working examples for common error scenarios."""

    @staticmethod
    def get_alert_examples() -> Dict[str, Any]:
        """Get working examples for alert creation."""
        return {
            "basic_threshold_alert": {
                "name": "High Cost Alert",
                "description": "Alert when costs exceed threshold",
                "alertType": "THRESHOLD",
                "metricType": "TOTAL_COST",
                "operatorType": ">=",
                "threshold": 100.0,
                "periodDuration": "ONE_HOUR",
                "notificationAddresses": ["admin@company.com"],
                "enabled": True,
            },
            "cumulative_usage_alert": {
                "name": "Monthly Budget Alert",
                "description": "Alert when monthly costs exceed budget",
                "alertType": "CUMULATIVE_USAGE",
                "metricType": "TOTAL_COST",
                "operatorType": ">=",
                "threshold": 1000.0,
                "periodDuration": "ONE_MONTH",
                "notificationAddresses": ["finance@company.com"],
                "enabled": True,
            },
        }

    @staticmethod
    def get_product_examples() -> Dict[str, Any]:
        """Get working examples for product creation."""
        return {
            "basic_product": {
                "name": "Basic API Access",
                "description": "Basic tier API access",
                "type": "api_access",
                "status": "active",
            },
            "tiered_product": {
                "name": "Premium API Access",
                "description": "Premium tier with higher limits",
                "type": "api_access",
                "status": "active",
                "plan": {"tiers": [{"name": "Premium", "up_to": 10000, "unit_amount": 0.01}]},
            },
        }

    @staticmethod
    def get_subscription_examples() -> Dict[str, Any]:
        """Get working examples for subscription creation."""
        return {
            "monthly_subscription": {
                "customer_email": "customer@company.com",
                "product_id": "prod_123",
                "billing_period": "monthly",
                "status": "active",
            },
            "annual_subscription": {
                "customer_email": "customer@company.com",
                "product_id": "prod_123",
                "billing_period": "yearly",
                "trial_period_days": 30,
                "status": "trialing",
            },
        }

    @staticmethod
    def get_source_examples() -> Dict[str, Any]:
        """Get working examples for source creation."""
        return {
            "api_source": {
                "name": "External API",
                "type": "api",
                "configuration": {"endpoint": "https://api.example.com/data", "method": "GET"},
            },
            "database_source": {
                "name": "Analytics Database",
                "type": "database",
                "configuration": {
                    "connection_string": "postgresql://user:pass@host:5432/db",
                    "query": "SELECT * FROM analytics_data",
                },
            },
        }

    @staticmethod
    def get_customer_examples() -> Dict[str, Any]:
        """Get working examples for customer creation."""
        return {
            "user_account": {
                "email": "user@company.com",
                "first_name": "John",
                "last_name": "Doe",
                "status": "active",
            },
            "organization": {
                "name": "Acme Corporation",
                "type": "enterprise",
                "status": "active",
                "contact_info": {"email": "contact@acme.com", "phone": "+1-555-0123"},
            },
        }
