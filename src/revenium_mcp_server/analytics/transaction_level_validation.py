"""Transaction-level analytics parameter validation infrastructure.

This module provides comprehensive parameter validation for all discovered
transaction-level parameters following existing validation patterns.
"""

from typing import Any, Dict

from loguru import logger

from ..common.error_handling import create_structured_validation_error


class TransactionLevelParameterValidator:
    """Comprehensive parameter validator for transaction-level analytics.

    Provides validation for all discovered transaction-level parameters:
    - All 11 time periods
    - All 5 aggregation types
    - Endpoint-specific parameters (tokenType, group)
    - Maintains backward compatibility with existing parameter validation
    """

    def __init__(self):
        """Initialize the transaction-level parameter validator."""
        logger.info("Initializing TransactionLevelParameterValidator")

        # API-verified time periods only (based on systematic API testing)
        self.supported_periods = [
            "SEVEN_DAYS",
            "THIRTY_DAYS",
            "TWELVE_MONTHS",
            "HOUR",
            "EIGHT_HOURS",
            "TWENTY_FOUR_HOURS",
        ]

        # All 5 aggregation types
        self.supported_aggregations = ["TOTAL", "MEAN", "MAXIMUM", "MINIMUM", "MEDIAN"]

        # Supported token types for tokens_per_minute_by_provider endpoint
        self.supported_token_types = ["TOTAL", "INPUT", "OUTPUT"]

        # Endpoint-specific parameter requirements
        self.endpoint_specific_parameters = {
            "tokens_per_minute_by_provider": {
                "required": ["tokenType"],
                "optional": ["group"],
                "supported_token_types": self.supported_token_types,
            },
            "cost_metrics_by_agents_over_time": {
                "required": [],
                "optional": ["group"],
                "supported_groups": self.supported_aggregations,
            },
            "performance_metrics_by_agents": {
                "required": [],
                "optional": ["group"],
                "supported_groups": self.supported_aggregations,
            },
        }

    def validate_period(self, period: str, field_name: str = "period") -> None:
        """Validate time period parameter.

        Args:
            period: Time period to validate
            field_name: Name of the field being validated

        Raises:
            ToolError: If period is invalid
        """
        if period not in self.supported_periods:
            raise create_structured_validation_error(
                message=f"Invalid {field_name}: {period}",
                field=field_name,
                value=period,
                suggestions=[f"Use one of: {', '.join(self.supported_periods)}"],
                examples={
                    "valid_periods": self.supported_periods,
                    "common_periods": ["SEVEN_DAYS", "THIRTY_DAYS", "TWELVE_MONTHS"],
                    "natural_language_mapping": {
                        "last week": "SEVEN_DAYS",
                        "last 30 days": "THIRTY_DAYS",
                        "last month": "THIRTY_DAYS",  # Mapped to closest supported period
                        "last quarter": "TWELVE_MONTHS",  # Mapped to closest supported period
                        "last year": "TWELVE_MONTHS",
                    },
                },
            )

    def validate_aggregation(self, aggregation: str, field_name: str = "group") -> None:
        """Validate aggregation type parameter.

        Args:
            aggregation: Aggregation type to validate
            field_name: Name of the field being validated

        Raises:
            ToolError: If aggregation is invalid
        """
        if aggregation not in self.supported_aggregations:
            raise create_structured_validation_error(
                message=f"Invalid {field_name}: {aggregation}",
                field=field_name,
                value=aggregation,
                suggestions=[f"Use one of: {', '.join(self.supported_aggregations)}"],
                examples={
                    "valid_aggregations": self.supported_aggregations,
                    "aggregation_descriptions": {
                        "TOTAL": "Sum all values (default)",
                        "MEAN": "Calculate average values",
                        "MAXIMUM": "Find peak/highest values",
                        "MINIMUM": "Find lowest values",
                        "MEDIAN": "Calculate median values",
                    },
                    "natural_language_mapping": {
                        "total": "TOTAL",
                        "average": "MEAN",
                        "mean": "MEAN",
                        "maximum": "MAXIMUM",
                        "peak": "MAXIMUM",
                        "minimum": "MINIMUM",
                        "lowest": "MINIMUM",
                        "median": "MEDIAN",
                    },
                },
            )

    def validate_token_type(self, token_type: str, field_name: str = "tokenType") -> None:
        """Validate token type parameter for token usage endpoints.

        Args:
            token_type: Token type to validate
            field_name: Name of the field being validated

        Raises:
            ToolError: If token type is invalid
        """
        if token_type not in self.supported_token_types:
            raise create_structured_validation_error(
                message=f"Invalid {field_name}: {token_type}",
                field=field_name,
                value=token_type,
                suggestions=[f"Use one of: {', '.join(self.supported_token_types)}"],
                examples={
                    "valid_token_types": self.supported_token_types,
                    "token_type_descriptions": {
                        "TOTAL": "All tokens (input + output)",
                        "INPUT": "Input tokens only",
                        "OUTPUT": "Output tokens only",
                    },
                },
            )

    def validate_endpoint_specific_parameters(
        self, endpoint_name: str, parameters: Dict[str, Any]
    ) -> None:
        """Validate endpoint-specific parameters.

        Args:
            endpoint_name: Name of the endpoint
            parameters: Parameters to validate

        Raises:
            ToolError: If endpoint-specific parameters are invalid
        """
        if endpoint_name not in self.endpoint_specific_parameters:
            # No specific validation required for this endpoint
            return

        endpoint_config = self.endpoint_specific_parameters[endpoint_name]

        # Validate required parameters
        for required_param in endpoint_config.get("required", []):
            if required_param not in parameters:
                raise create_structured_validation_error(
                    message=f"Missing required parameter for {endpoint_name}: {required_param}",
                    field=required_param,
                    value=None,
                    suggestions=[
                        f"Provide {required_param} parameter for {endpoint_name} endpoint"
                    ],
                    examples=self._get_endpoint_examples(endpoint_name),
                )

        # Validate tokenType for token endpoints
        if "tokenType" in parameters and "supported_token_types" in endpoint_config:
            self.validate_token_type(parameters["tokenType"])

        # Validate group parameter for endpoints that support it
        if "group" in parameters and "supported_groups" in endpoint_config:
            self.validate_aggregation(parameters["group"])

    def validate_transaction_level_query(
        self, endpoint_name: str, parameters: Dict[str, Any]
    ) -> None:
        """Comprehensive validation for transaction-level analytics queries.

        Args:
            endpoint_name: Name of the transaction-level endpoint
            parameters: Query parameters to validate

        Raises:
            ToolError: If any parameters are invalid
        """
        logger.info(f"Validating transaction-level query for {endpoint_name}")

        # Validate period if present
        if "period" in parameters:
            self.validate_period(parameters["period"])

        # Validate aggregation if present
        if "group" in parameters:
            self.validate_aggregation(parameters["group"])

        # Validate team_id (required for all endpoints)
        if "teamId" not in parameters:
            raise create_structured_validation_error(
                message="Missing required parameter: teamId",
                field="teamId",
                value=None,
                suggestions=["Provide teamId parameter for all analytics queries"],
                examples={
                    "basic_query": {"teamId": "team-123", "period": "SEVEN_DAYS"},
                    "with_aggregation": {
                        "teamId": "team-456",
                        "period": "THIRTY_DAYS",
                        "group": "MEAN",
                    },
                },
            )

        # Validate endpoint-specific parameters
        self.validate_endpoint_specific_parameters(endpoint_name, parameters)

        logger.info(f"Transaction-level query validation passed for {endpoint_name}")

    def _get_endpoint_examples(self, endpoint_name: str) -> Dict[str, Any]:
        """Get examples for specific endpoints.

        Args:
            endpoint_name: Name of the endpoint

        Returns:
            Dictionary of examples for the endpoint
        """
        examples = {
            "tokens_per_minute_by_provider": {
                "basic": {"teamId": "team-123", "period": "SEVEN_DAYS", "tokenType": "TOTAL"},
                "with_aggregation": {
                    "teamId": "team-456",
                    "period": "THIRTY_DAYS",
                    "tokenType": "INPUT",
                    "group": "MEAN",
                },
                "output_tokens": {
                    "teamId": "team-789",
                    "period": "THIRTY_DAYS",
                    "tokenType": "OUTPUT",
                    "group": "MAXIMUM",
                },
            },
            "cost_metrics_by_agents_over_time": {
                "basic": {"teamId": "team-123", "period": "SEVEN_DAYS"},
                "with_aggregation": {
                    "teamId": "team-456",
                    "period": "THIRTY_DAYS",
                    "group": "MEDIAN",
                },
            },
            "performance_metrics_by_agents": {
                "basic": {"teamId": "team-123", "period": "SEVEN_DAYS"},
                "with_aggregation": {
                    "teamId": "team-456",
                    "period": "THIRTY_DAYS",
                    "group": "MEAN",
                },
            },
        }

        return examples.get(
            endpoint_name,
            {
                "basic": {"teamId": "team-123", "period": "SEVEN_DAYS"},
                "with_aggregation": {
                    "teamId": "team-456",
                    "period": "THIRTY_DAYS",
                    "group": "TOTAL",
                },
            },
        )

    def get_supported_parameters(self) -> Dict[str, Any]:
        """Get all supported parameters for transaction-level analytics.

        Returns:
            Dictionary of all supported parameters and their values
        """
        return {
            "supported_periods": self.supported_periods,
            "supported_aggregations": self.supported_aggregations,
            "supported_token_types": self.supported_token_types,
            "endpoint_specific_parameters": self.endpoint_specific_parameters,
            "parameter_descriptions": {
                "period": "Time period for analysis",
                "group": "Aggregation type (TOTAL, MEAN, MAXIMUM, MINIMUM, MEDIAN)",
                "tokenType": "Token type for usage analysis (TOTAL, INPUT, OUTPUT)",
                "teamId": "Team identifier (required for all queries)",
            },
        }
