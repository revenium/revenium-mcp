"""Parameter extraction from natural language queries.

This module provides parameter extraction capabilities for the AI routing system,
supporting both AI-powered and rule-based parameter extraction with validation.
"""

# Standard library imports
from typing import Any, Dict, List, Optional

# Third-party imports
from loguru import logger

# Local imports
from .models import ExtractedParameters
from .parameter_normalizers import ParameterNormalizers
from .parameter_patterns import ParameterPatterns
from .parameter_validators import ParameterValidators

# Constants for operation requirements
OPERATION_REQUIREMENTS = {
    "products.create": ["name"],
    "alerts.list": [],
    "subscriptions.list": [],
    "customers.create": ["email"],
    "workflows.start": ["workflow_type"],
}

# Extraction order to prioritize specific patterns over generic ones
EXTRACTION_ORDER = [
    "name",
    "email",
    "product_type",
    "workflow_type",
    "time_period",
    "status",
    "priority",
    "amount",
    "date",
    "id",  # ID last to avoid conflicts
]


class ParameterExtractor:
    """Extracts parameters from natural language queries.

    This class provides rule-based parameter extraction using regex patterns
    and normalization functions. It supports the 5 core operations:
    1. Product management (create, list, update)
    2. Customer management (create, list, update)
    3. Workflow management (start, monitor)
    4. Alert management (create, list, configure)
    5. Analytics queries (cost, usage, performance)
    """

    def __init__(self):
        """Initialize the parameter extractor with patterns and normalizers."""
        self.pattern_manager = ParameterPatterns()
        self.normalizer_manager = ParameterNormalizers()
        self.validator_manager = ParameterValidators()

        # For backward compatibility
        self.patterns = self.pattern_manager.patterns
        self.normalizers = self.normalizer_manager.normalizers

    def extract_parameters(
        self, query: str, expected_parameters: Optional[List[str]] = None
    ) -> ExtractedParameters:
        """Extract parameters from a natural language query.

        Args:
            query: Natural language query text
            expected_parameters: List of expected parameter names

        Returns:
            ExtractedParameters with extracted values and metadata
        """
        logger.debug(f"Extracting parameters from query: {query[:100]}...")

        extracted = {}
        confidence_scores = []

        # Extract using rule-based patterns in priority order
        for param_type in EXTRACTION_ORDER:
            if param_type in self.patterns:
                extracted_value = self._extract_single_parameter(query, param_type)
                if extracted_value is not None:
                    extracted[param_type] = extracted_value
                    confidence_scores.append(0.8)  # Rule-based extraction confidence
                    logger.debug(f"Extracted {param_type}: {extracted_value}")

        # Calculate overall confidence
        overall_confidence = (
            sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0.0
        )

        # Determine missing parameters
        missing_parameters = self._find_missing_parameters(extracted, expected_parameters)

        return ExtractedParameters(
            parameters=extracted,
            confidence=overall_confidence,
            missing_parameters=missing_parameters,
            extraction_method="rule_based",
            raw_query=query,
        )

    def _extract_single_parameter(self, query: str, param_type: str) -> Optional[Any]:
        """Extract a single parameter type from query."""
        patterns = self.patterns[param_type]

        for pattern in patterns:
            matches = pattern.findall(query)
            if matches:
                # Take the first match for each parameter type
                raw_value = matches[0] if isinstance(matches[0], str) else matches[0][0]

                # Normalize the extracted value
                if param_type in self.normalizers:
                    normalized_value = self.normalizers[param_type](raw_value)
                    if normalized_value is not None:
                        return normalized_value
                break

        return None

    def _find_missing_parameters(
        self, extracted: Dict[str, Any], expected_parameters: Optional[List[str]]
    ) -> List[str]:
        """Find missing parameters from expected list."""
        if not expected_parameters:
            return []

        return [param for param in expected_parameters if param not in extracted]

    def validate_parameters(
        self,
        parameters: Dict[str, Any],
        required_parameters: List[str],
        operation_context: Optional[str] = None,
    ) -> List[str]:
        """Validate extracted parameters against requirements."""
        return self.validator_manager.validate_parameters(
            parameters, required_parameters, operation_context
        )

    def extract_and_validate_parameters(
        self, query: str, operation_context: str, expected_parameters: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Extract and validate parameters for a specific operation."""
        # Extract parameters
        extracted_params = self.extract_parameters(query, expected_parameters)

        # Determine required parameters based on operation context
        required_params = self._get_required_parameters_for_operation(operation_context)

        # Validate parameters
        validation_errors = self.validate_parameters(
            extracted_params.parameters, required_params, operation_context
        )

        # Calculate extraction quality score
        quality_score = self._calculate_extraction_quality(
            extracted_params, required_params, validation_errors
        )

        # Generate recommendations
        recommendations = self._generate_parameter_recommendations(
            extracted_params, required_params, validation_errors, operation_context
        )

        return {
            "extracted_parameters": extracted_params,
            "validation_errors": validation_errors,
            "required_parameters": required_params,
            "quality_score": quality_score,
            "recommendations": recommendations,
            "is_valid": len(validation_errors) == 0,
            "operation_context": operation_context,
        }

    def _get_required_parameters_for_operation(self, operation_context: str) -> List[str]:
        """Get required parameters for a specific operation."""
        return OPERATION_REQUIREMENTS.get(operation_context, [])

    def _calculate_extraction_quality(
        self,
        extracted_params: ExtractedParameters,
        required_params: List[str],
        validation_errors: List[str],
    ) -> float:
        """Calculate extraction quality score (0.0 to 1.0)."""
        if not required_params:
            # If no required parameters, base score on confidence and validation
            # Give a reasonable base score for operations without required params
            base_score = max(0.6, extracted_params.confidence)  # Minimum 0.6 for valid operations
            error_penalty = len(validation_errors) * 0.2
            return max(0.0, min(1.0, base_score - error_penalty))

        # Calculate based on required parameter coverage
        required_coverage = sum(
            1
            for param in required_params
            if param in extracted_params.parameters
            and extracted_params.parameters[param] is not None
        ) / len(required_params)

        # Apply confidence and validation penalties
        confidence_factor = extracted_params.confidence
        error_penalty = len(validation_errors) * 0.1

        quality_score = (required_coverage * 0.6 + confidence_factor * 0.4) - error_penalty
        return max(0.0, min(1.0, quality_score))

    def _generate_parameter_recommendations(
        self,
        extracted_params: ExtractedParameters,
        required_params: List[str],
        validation_errors: List[str],
        operation_context: str,
    ) -> List[str]:
        """Generate recommendations for improving parameter extraction."""
        recommendations = []

        # Check for missing required parameters
        missing_required = [
            param
            for param in required_params
            if param not in extracted_params.parameters
            or extracted_params.parameters[param] is None
        ]

        if missing_required:
            recommendations.append(
                f"Add missing required parameters: {', '.join(missing_required)}"
            )

        # Operation-specific recommendations
        recommendations.extend(
            self._get_operation_specific_recommendations(
                operation_context, extracted_params.parameters
            )
        )

        # General quality recommendations
        if extracted_params.confidence < 0.7:
            recommendations.append(
                "Consider using more specific language for better parameter extraction"
            )

        if validation_errors:
            recommendations.append("Fix validation errors: " + "; ".join(validation_errors))

        return recommendations

    def _get_operation_specific_recommendations(
        self, operation_context: str, parameters: Dict[str, Any]
    ) -> List[str]:
        """Get operation-specific recommendations."""
        recommendations = []

        if operation_context == "products.create":
            if "name" not in parameters:
                recommendations.append("Try: 'create a product called [ProductName]'")
            if "product_type" not in parameters:
                recommendations.append(
                    "Consider specifying product type: 'with type api/usage/subscription/metering'"
                )

        elif operation_context == "customers.create":
            if "email" not in parameters:
                recommendations.append("Try: 'add customer [email@domain.com]'")
            if "name" not in parameters:
                recommendations.append("Consider adding name: 'named [Customer Name]'")

        elif operation_context == "workflows.start":
            if "workflow_type" not in parameters:
                recommendations.append(
                    "Try: 'start workflow [subscription_setup/customer_onboarding/product_creation]'"
                )

        return recommendations
