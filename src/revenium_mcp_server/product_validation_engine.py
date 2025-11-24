"""Product Validation Engine for preventing common API errors.

This module implements proactive validation following MCP server best practices
to catch deprecated values, invalid field combinations, and common mistakes
before making API calls.

Based on research of leading MCP servers (Supabase, Notion, Spring AI).
"""

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class ValidationError:
    """Represents a validation error following MCP patterns."""

    field: str
    value: Any
    error: str
    suggestion: str
    severity: str = "error"  # "error", "warning", "info"
    example: Optional[Dict[str, Any]] = None  # Working example to fix the issue


@dataclass
class ValidationResult:
    """Result of validation check with MCP-compatible formatting."""

    is_valid: bool
    errors: List[ValidationError]
    warnings: List[ValidationError]

    @property
    def has_errors(self) -> bool:
        """Check if there are any errors."""
        return len(self.errors) > 0

    @property
    def has_warnings(self) -> bool:
        """Check if there are any warnings."""
        return len(self.warnings) > 0

    def to_mcp_response(self) -> Dict[str, Any]:
        """Convert to MCP-compatible response format."""
        if self.is_valid:
            if self.has_warnings:
                # Validation passed but has warnings - show both success and warnings
                warning_text = self._format_mcp_warnings()
                return {
                    "isError": False,
                    "content": [
                        {
                            "type": "text",
                            "text": f"✅ **Validation Passed** - Ready for API call\n\n{warning_text}",
                        }
                    ],
                }
            else:
                # Validation passed with no warnings
                return {
                    "isError": False,
                    "content": [
                        {"type": "text", "text": "✅ **Validation Passed** - Ready for API call"}
                    ],
                }
        else:
            error_text = self._format_mcp_errors()
            return {"isError": True, "content": [{"type": "text", "text": error_text}]}

    def _format_mcp_errors(self) -> str:
        """Format errors in MCP-friendly format."""
        lines = ["❌ **Validation Failed** - Issues found before API call:"]

        if self.errors:
            lines.append("\n**🚨 Critical Issues (must fix):**")
            for error in self.errors:
                lines.append(f"• **{error.field}**: {error.error}")
                lines.append(f"  💡 **Fix**: {error.suggestion}")
                if error.example:
                    lines.append(f"  ✅ **Example**: `{json.dumps(error.example)}`")

        if self.warnings:
            lines.append("\n**⚠️ Warnings (recommended fixes):**")
            for warning in self.warnings:
                lines.append(f"• **{warning.field}**: {warning.error}")
                lines.append(f"  💡 **Suggestion**: {warning.suggestion}")

        lines.append("\n**📋 Use get_examples() to see current working templates**")
        lines.append("**🔍 Use validate() to test your data before creating**")

        return "\n".join(lines)

    def _format_mcp_warnings(self) -> str:
        """Format warnings in MCP-friendly format."""
        lines = ["**⚠️ Warnings (recommended fixes):**"]

        for warning in self.warnings:
            lines.append(f"• **{warning.field}**: {warning.error}")
            lines.append(f"  💡 **Suggestion**: {warning.suggestion}")

        lines.append("\n**📋 Use get_examples() to see current working templates**")

        return "\n".join(lines)


class ProductValidationEngine:
    """Comprehensive Product Validation Engine for Revenium Platform API.

    **Phase 1 (Immediate)**: Prevents CHARGE vs SUBSCRIPTION deprecated plan type error
    **Phase 2 (Comprehensive)**: Full product management workflow validation

    Follows MCP server best practices discovered from research of leading servers.
    Prevents API errors before they reach the Revenium API, improving agent success rates.
    """

    # REMOVED: Hardcoded validation arrays - now using UCM-only validation
    # All validation now relies on UCM capabilities and API verification

    # Deprecated values with specific migration guidance
    DEPRECATED_VALUES = {
        "plan.type": {
            "CHARGE": {
                "message": "CHARGE plan type was deprecated in 2024",
                "suggestion": "Use 'SUBSCRIPTION' instead",
                "api_error_prevented": "Failed to create product: This Plan Type has been Deprecated, new Plans with this type can no longer be created: CHARGE; only these types are allowed: SUBSCRIPTION",
                "working_example": {
                    "plan": {
                        "type": "SUBSCRIPTION",
                        "name": "Standard Plan",
                        "currency": "USD",
                        "period": "MONTH",
                        "tiers": [
                            {"name": "Basic Tier", "starting_from": 0, "unit_amount": "29.99"}
                        ],
                    }
                },
            },
            "ONE_TIME": {
                "message": "ONE_TIME plan type was deprecated in 2024",
                "suggestion": "Use 'SUBSCRIPTION' with single billing cycle",
                "working_example": {
                    "plan": {
                        "type": "SUBSCRIPTION",
                        "name": "One-Time Plan",
                        "currency": "USD",
                        "billing_cycle": "one_time",
                        "tiers": [
                            {"name": "Single Payment", "up_to": None, "unit_amount": "99.99"}
                        ],
                    }
                },
            },
        }
    }

    # Required field combinations (enhanced based on API discovery)
    REQUIRED_FIELDS = {
        "product": ["name", "description", "version", "plan"],
        "plan": ["type", "name", "currency", "tiers"],
        "plan_subscription": [
            "type",
            "name",
            "currency",
            "tiers",
            "period",
        ],  # SUBSCRIPTION plans need period
        "tier": ["name", "up_to"],  # CORRECTED: starting_from is auto-generated, not user input
    }

    # REMOVED: Hardcoded VALID_PERIODS array - now using UCM-only validation
    # All period validation now relies on UCM capabilities and API verification

    @classmethod
    def validate_for_mcp(cls, product_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate product data and return MCP-compatible response.

        This is the main method for MCP tools to use for validation.
        Returns MCP-style response with isError flag and formatted content.

        Args:
            product_data: Product data to validate

        Returns:
            MCP-compatible response dict
        """
        validation_result = cls.validate_product_data(product_data)
        return validation_result.to_mcp_response()

    @classmethod
    def validate_product_data(cls, product_data: Dict[str, Any]) -> ValidationResult:
        """Comprehensive validation of product data.

        Args:
            product_data: Product data to validate

        Returns:
            ValidationResult with errors and warnings
        """
        errors = []
        warnings = []

        # Check required fields
        errors.extend(cls._validate_required_fields(product_data))

        # Check for deprecated values
        errors.extend(cls._validate_deprecated_values(product_data))

        # Check for invalid values
        errors.extend(cls._validate_field_values(product_data))

        # Check field combinations and business rules
        business_rule_errors = cls._validate_field_combinations(product_data)
        # Separate errors from warnings
        for error in business_rule_errors:
            if error.severity == "error":
                errors.append(error)
            else:
                warnings.append(error)

        return ValidationResult(is_valid=len(errors) == 0, errors=errors, warnings=warnings)

    @classmethod
    def _validate_required_fields(cls, data: Dict[str, Any]) -> List[ValidationError]:
        """Validate required fields are present."""
        errors = []

        # Check top-level required fields
        for field in cls.REQUIRED_FIELDS["product"]:
            if field not in data:
                errors.append(
                    ValidationError(
                        field=field,
                        value=None,
                        error=f"Required field '{field}' is missing",
                        suggestion=f"Add '{field}' to your product data",
                    )
                )

        # Check plan required fields (enhanced for SUBSCRIPTION plans)
        if "plan" in data and isinstance(data["plan"], dict):
            plan_data = data["plan"]
            plan_type = plan_data.get("type")

            # Use different required fields based on plan type
            if plan_type == "SUBSCRIPTION":
                required_fields = cls.REQUIRED_FIELDS["plan_subscription"]
            else:
                required_fields = cls.REQUIRED_FIELDS["plan"]

            for field in required_fields:
                if field not in plan_data:
                    if field == "period" and plan_type == "SUBSCRIPTION":
                        errors.append(
                            ValidationError(
                                field=f"plan.{field}",
                                value=None,
                                error=f"SUBSCRIPTION plans require a 'period' field",
                                suggestion="Add 'period' to your plan configuration. Use UCM get_capabilities to see valid periods",
                                example={"plan": {"period": "MONTHLY"}},
                            )
                        )
                    else:
                        errors.append(
                            ValidationError(
                                field=f"plan.{field}",
                                value=None,
                                error=f"Required plan field '{field}' is missing",
                                suggestion=f"Add '{field}' to your plan configuration",
                            )
                        )

            # Check tier required fields
            if "tiers" in plan_data and isinstance(plan_data["tiers"], list):
                for i, tier in enumerate(plan_data["tiers"]):
                    if isinstance(tier, dict):
                        for field in cls.REQUIRED_FIELDS["tier"]:
                            if field not in tier:
                                errors.append(
                                    ValidationError(
                                        field=f"plan.tiers[{i}].{field}",
                                        value=None,
                                        error=f"Required tier field '{field}' is missing",
                                        suggestion=f"Add '{field}' to tier {i}",
                                    )
                                )

        return errors

    @classmethod
    def _validate_deprecated_values(cls, data: Dict[str, Any]) -> List[ValidationError]:
        """Check for deprecated field values."""
        errors = []

        # Check plan type (CRITICAL: Prevents CHARGE vs SUBSCRIPTION error)
        if "plan" in data and isinstance(data["plan"], dict):
            plan_type = data["plan"].get("type")
            if plan_type in cls.DEPRECATED_VALUES["plan.type"]:
                deprecated_info = cls.DEPRECATED_VALUES["plan.type"][plan_type]
                errors.append(
                    ValidationError(
                        field="plan.type",
                        value=plan_type,
                        error=f"❌ DEPRECATED: {deprecated_info['message']}",
                        suggestion=deprecated_info["suggestion"],
                        severity="error",
                        example=deprecated_info.get("working_example"),
                    )
                )

        return errors

    @classmethod
    def _validate_field_values(cls, data: Dict[str, Any]) -> List[ValidationError]:
        """Validate field values against current valid values."""
        errors = []

        # Check plan type
        if "plan" in data and isinstance(data["plan"], dict):
            plan_data = data["plan"]

            # UCM-only validation - let the API handle plan type validation
            plan_type = plan_data.get("type")
            if not plan_type:
                errors.append(
                    ValidationError(
                        field="plan.type",
                        value=plan_type,
                        error="Plan type is required",
                        suggestion="Use UCM get_capabilities to see valid types",
                    )
                )

            # UCM-only validation - let the API handle currency validation
            currency = plan_data.get("currency")
            if not currency:
                errors.append(
                    ValidationError(
                        field="plan.currency",
                        value=currency,
                        error="Currency is required",
                        suggestion="Use UCM get_capabilities to see valid currencies",
                    )
                )

            # UCM-only validation - let the API handle period validation
            if plan_type == "SUBSCRIPTION":
                period = plan_data.get("period")
                if not period:
                    errors.append(
                        ValidationError(
                            field="plan.period",
                            value=period,
                            error="Period is required for SUBSCRIPTION plans",
                            suggestion="Use UCM get_capabilities to see valid periods for SUBSCRIPTION plans",
                        )
                    )

        # Payment source validation with supported values
        payment_source = data.get("paymentSource")  # FIXED: Use correct API field name
        if not payment_source:
            errors.append(
                ValidationError(
                    field="paymentSource",
                    value=payment_source,
                    error="Payment source is required",
                    suggestion="Use 'INVOICE_ONLY_NO_PAYMENT' for manual invoices or 'EXTERNAL_PAYMENT_NOTIFICATION' for tracked payments",
                )
            )
        elif payment_source not in ["INVOICE_ONLY_NO_PAYMENT", "EXTERNAL_PAYMENT_NOTIFICATION"]:
            # Add warning for unsupported payment sources (like STRIPE)
            if payment_source == "STRIPE":
                errors.append(
                    ValidationError(
                        field="paymentSource",
                        value=payment_source,
                        error="STRIPE payment source is not supported via MCP API",
                        suggestion="Use 'INVOICE_ONLY_NO_PAYMENT' or 'EXTERNAL_PAYMENT_NOTIFICATION'. Stripe products must be configured through the Revenium UI",
                        severity="error",
                    )
                )
            else:
                errors.append(
                    ValidationError(
                        field="paymentSource",
                        value=payment_source,
                        error=f"Payment source '{payment_source}' is not supported",
                        suggestion="Use 'INVOICE_ONLY_NO_PAYMENT' or 'EXTERNAL_PAYMENT_NOTIFICATION'",
                        severity="error",
                    )
                )

        return errors

    @classmethod
    def _validate_field_combinations(cls, data: Dict[str, Any]) -> List[ValidationError]:
        """Validate field combinations and business rules discovered from testing."""
        warnings = []
        errors = []

        # Check if tiers are properly configured
        if "plan" in data and isinstance(data["plan"], dict):
            plan_data = data["plan"]
            tiers = []  # Initialize tiers to prevent UnboundLocalError
            if "tiers" in plan_data and isinstance(plan_data["tiers"], list):
                tiers = plan_data["tiers"]

                if len(tiers) == 0:
                    warnings.append(
                        ValidationError(
                            field="plan.tiers",
                            value=[],
                            error="No pricing tiers defined",
                            suggestion="Add at least one pricing tier",
                            severity="warning",
                        )
                    )
                else:
                    # CRITICAL BUSINESS RULE: Only one tier can be unlimited (no up_to) across ALL tiers in ALL aggregations
                    unlimited_tiers = [
                        i for i, tier in enumerate(tiers) if tier.get("up_to") is None
                    ]

                    # Count unlimited tiers in ratingAggregations as well
                    total_unlimited_count = len(unlimited_tiers)
                    rating_aggregations = plan_data.get("ratingAggregations", [])

                    for agg_idx, aggregation in enumerate(rating_aggregations):
                        agg_tiers = aggregation.get("tiers", [])
                        for tier_idx, tier in enumerate(agg_tiers):
                            if tier.get("up_to") is None:
                                total_unlimited_count += 1

                    if total_unlimited_count > 1:
                        errors.append(
                            ValidationError(
                                field="plan.tiers + plan.ratingAggregations.tiers",
                                value=f"Total unlimited tiers across all aggregations: {total_unlimited_count}",
                                error="Cannot have more than one tier with unlimited usage (up_to is null) across ALL tiers in ALL aggregations",
                                suggestion="Only ONE tier across the entire product can be unlimited. Use separate aggregations for different metering elements, each with limited tiers except one.",
                                severity="error",
                            )
                        )

                    # BUSINESS RULE: Tier pricing validation
                    for i, tier in enumerate(tiers):
                        # Check for deprecated starting_from field
                        if "starting_from" in tier:
                            warnings.append(
                                ValidationError(
                                    field=f"plan.tiers[{i}]",
                                    value="Contains starting_from field",
                                    error="Tier starting_from is auto-generated by the API and should not be provided in user input",
                                    suggestion="Remove 'starting_from' - the API automatically calculates starting values from tier ordering and up_to values",
                                    severity="warning",
                                )
                            )

                        # Check for required pricing fields
                        unit_amount = tier.get("unit_amount")
                        flat_amount = tier.get("flat_amount")

                        if unit_amount is None and flat_amount is None:
                            errors.append(
                                ValidationError(
                                    field=f"plan.tiers[{i}]",
                                    value="Missing both unit_amount and flat_amount",
                                    error="Tier must have either unit_amount or flat_amount (or both). Use unit_amount for per-unit pricing (e.g., per API call) or flat_amount for one-time fees (e.g., setup costs).",
                                    suggestion="Add 'unit_amount': '0.01' for per-unit pricing or 'flat_amount': '10.00' for one-time fees",
                                    severity="error",
                                )
                            )

                        # Validate unit_amount if provided
                        if unit_amount is not None:
                            try:
                                amount_value = float(unit_amount)
                                if amount_value < 0:
                                    errors.append(
                                        ValidationError(
                                            field=f"plan.tiers[{i}].unit_amount",
                                            value=unit_amount,
                                            error=f"Unit amount cannot be negative: {unit_amount}",
                                            suggestion="Use a positive value or 0.00 for free tiers",
                                            severity="error",
                                        )
                                    )
                            except (ValueError, TypeError):
                                errors.append(
                                    ValidationError(
                                        field=f"plan.tiers[{i}].unit_amount",
                                        value=unit_amount,
                                        error=f"Unit amount must be a valid number: {unit_amount}",
                                        suggestion="Use a decimal string format like '0.10' or '29.99'",
                                        severity="error",
                                    )
                                )

                        # Validate flat_amount if provided
                        if flat_amount is not None:
                            try:
                                amount_value = float(flat_amount)
                                if amount_value < 0:
                                    errors.append(
                                        ValidationError(
                                            field=f"plan.tiers[{i}].flat_amount",
                                            value=flat_amount,
                                            error=f"Flat amount cannot be negative: {flat_amount}",
                                            suggestion="Use a positive value or 0.00 for free setup",
                                            severity="error",
                                        )
                                    )
                            except (ValueError, TypeError):
                                errors.append(
                                    ValidationError(
                                        field=f"plan.tiers[{i}].flat_amount",
                                        value=flat_amount,
                                        error=f"Flat amount must be a valid number: {flat_amount}",
                                        suggestion="Use a decimal string format like '10.00' or '99.99'",
                                        severity="error",
                                    )
                                )

                    # BUSINESS RULE: Validate tier ordering by up_to values
                    for i in range(len(tiers) - 1):
                        current_tier = tiers[i]
                        next_tier = tiers[i + 1]

                        current_up_to = current_tier.get("up_to")
                        next_up_to = next_tier.get("up_to")

                        # Skip validation if either tier has unlimited range (up_to: null)
                        if current_up_to is not None and next_up_to is not None:
                            try:
                                current_val = float(current_up_to)
                                next_val = float(next_up_to)
                                if next_val <= current_val:
                                    warnings.append(
                                        ValidationError(
                                            field=f"plan.tiers[{i+1}].up_to",
                                            value=next_up_to,
                                            error=f"Tier {i+1} up_to ({next_up_to}) should be greater than tier {i} up_to ({current_up_to})",
                                            suggestion="Ensure tiers are ordered by increasing up_to values",
                                            severity="warning",
                                        )
                                    )
                            except (ValueError, TypeError):
                                # Skip validation if values can't be converted to numbers
                                pass

            # METERING ARCHITECTURE VALIDATION: Validate ratingAggregations structure
            rating_aggregations = plan_data.get("ratingAggregations", [])
            if rating_aggregations:
                for agg_idx, aggregation in enumerate(rating_aggregations):
                    # Validate elementDefinitionId is present
                    if not aggregation.get("elementDefinitionId"):
                        errors.append(
                            ValidationError(
                                field=f"plan.ratingAggregations[{agg_idx}].elementDefinitionId",
                                value=None,
                                error="Rating aggregation missing elementDefinitionId",
                                suggestion="Each rating aggregation must target a specific metering element via elementDefinitionId",
                                severity="error",
                            )
                        )

                    # Validate aggregationType is present
                    if not aggregation.get("aggregationType"):
                        warnings.append(
                            ValidationError(
                                field=f"plan.ratingAggregations[{agg_idx}].aggregationType",
                                value=None,
                                error="Rating aggregation missing aggregationType",
                                suggestion="Specify aggregationType (SUM, MAX, MIN, AVG, COUNT, etc.)",
                                severity="warning",
                            )
                        )

                    # Validate tiers structure within aggregation
                    agg_tiers = aggregation.get("tiers", [])
                    if not agg_tiers:
                        warnings.append(
                            ValidationError(
                                field=f"plan.ratingAggregations[{agg_idx}].tiers",
                                value=[],
                                error="Rating aggregation has no pricing tiers",
                                suggestion="Add at least one pricing tier to define how this metering element is billed",
                                severity="warning",
                            )
                        )

                    # Validate tier pricing structure
                    for tier_idx, tier in enumerate(agg_tiers):
                        unit_amount = tier.get("unit_amount")
                        if unit_amount is not None:
                            try:
                                amount_value = float(unit_amount)
                                if amount_value < 0:
                                    errors.append(
                                        ValidationError(
                                            field=f"plan.ratingAggregations[{agg_idx}].tiers[{tier_idx}].unit_amount",
                                            value=unit_amount,
                                            error=f"Unit amount cannot be negative: {unit_amount}",
                                            suggestion="Use a positive value or 0.00 for free tiers",
                                            severity="error",
                                        )
                                    )
                            except (ValueError, TypeError):
                                errors.append(
                                    ValidationError(
                                        field=f"plan.ratingAggregations[{agg_idx}].tiers[{tier_idx}].unit_amount",
                                        value=unit_amount,
                                        error=f"Unit amount must be a valid number: {unit_amount}",
                                        suggestion="Use a decimal string format like '0.10' or '29.99'",
                                        severity="error",
                                    )
                                )

            # GUIDANCE: If no metering elements are configured, provide guidance
            if not tiers and not rating_aggregations:
                warnings.append(
                    ValidationError(
                        field="plan",
                        value="No pricing structure defined",
                        error="Product has no pricing tiers or metering aggregations",
                        suggestion="Add either 'tiers' for simple pricing or 'ratingAggregations' for usage-based billing with metering elements",
                        severity="warning",
                    )
                )

            # MULTI-TIER RATING AGGREGATIONS VALIDATION: Check for confirmed working pattern requirements
            if rating_aggregations:
                # Check for required fields when using ratingAggregations
                if not data.get("sourceIds"):
                    errors.append(
                        ValidationError(
                            field="sourceIds",
                            value=None,
                            error="Products with ratingAggregations require sourceIds field",
                            suggestion="Add 'sourceIds': ['QOjOkbW'] to assign the product to a data source",
                            severity="error",
                        )
                    )

                # Check for multi-tier aggregations requirements
                has_multi_tier_aggregations = any(
                    len(agg.get("tiers", [])) > 1 for agg in rating_aggregations
                )

                if has_multi_tier_aggregations:
                    plan_charge = plan_data.get("charge")
                    plan_prepay = plan_data.get("prePayAllFlatRates")

                    if plan_charge is None:
                        warnings.append(
                            ValidationError(
                                field="plan.charge",
                                value=None,
                                error="Multi-tier ratingAggregations typically require a charge value",
                                suggestion="Add 'charge': 199 for multi-tier usage-based billing",
                                severity="warning",
                            )
                        )

                    if not plan_prepay:
                        warnings.append(
                            ValidationError(
                                field="plan.prePayAllFlatRates",
                                value=plan_prepay,
                                error="Multi-tier ratingAggregations typically require prePayAllFlatRates: true",
                                suggestion="Add 'prePayAllFlatRates': true for multi-tier usage-based billing",
                                severity="warning",
                            )
                        )

                # Validate tier structure for ratingAggregations
                for agg_idx, aggregation in enumerate(rating_aggregations):
                    agg_tiers = aggregation.get("tiers", [])
                    for tier_idx, tier in enumerate(agg_tiers):
                        # Check for incorrect starting_from fields in user input
                        if "starting_from" in tier:
                            warnings.append(
                                ValidationError(
                                    field=f"plan.ratingAggregations[{agg_idx}].tiers[{tier_idx}]",
                                    value="Contains starting_from field",
                                    error="Tier starting_from is auto-generated by the API and should not be provided in user input",
                                    suggestion="Remove 'starting_from' - the API automatically calculates starting values from tier ordering and up_to values",
                                    severity="warning",
                                )
                            )

                        # Check for required up_to and unit_amount fields (internal format)
                        if "up_to" not in tier:
                            errors.append(
                                ValidationError(
                                    field=f"plan.ratingAggregations[{agg_idx}].tiers[{tier_idx}].up_to",
                                    value=None,
                                    error="Rating aggregation tier missing up_to field",
                                    suggestion="Add 'up_to': '1000' for limited tiers or 'up_to': null for unlimited final tier",
                                    severity="error",
                                )
                            )

                        if "unit_amount" not in tier:
                            errors.append(
                                ValidationError(
                                    field=f"plan.ratingAggregations[{agg_idx}].tiers[{tier_idx}].unit_amount",
                                    value=None,
                                    error="Rating aggregation tier missing unit_amount field",
                                    suggestion="Add 'unit_amount': '.10' to define the pricing for this tier",
                                    severity="error",
                                )
                            )

            # UI FIELD VALIDATION: Validate new UI-visible fields
            cls._validate_ui_fields(data, errors, warnings)

        return errors + warnings

    @classmethod
    def _validate_ui_fields(
        cls, data: Dict[str, Any], errors: List[ValidationError], warnings: List[ValidationError]
    ) -> None:
        """Validate UI-specific fields that appear in the product creation interface."""

        # Setup Fees Validation (CORRECTED: Product-level setupFees with proper structure)
        setup_fees = data.get("setupFees", [])
        if setup_fees:
            if not isinstance(setup_fees, list):
                errors.append(
                    ValidationError(
                        field="setupFees",
                        value=setup_fees,
                        error="Setup fees must be an array",
                        suggestion="Use 'setupFees': [{'type': 'SUBSCRIPTION', 'name': 'Setup Fee', 'flatAmount': 100}]",
                        severity="error",
                    )
                )
            else:
                for idx, fee in enumerate(setup_fees):
                    if not isinstance(fee, dict):
                        errors.append(
                            ValidationError(
                                field=f"setupFees[{idx}]",
                                value=fee,
                                error="Each setup fee must be an object",
                                suggestion="Use {'type': 'SUBSCRIPTION', 'name': 'Setup Fee', 'flatAmount': 100}",
                                severity="error",
                            )
                        )
                    else:
                        # Validate required fields
                        if not fee.get("name"):
                            warnings.append(
                                ValidationError(
                                    field=f"setupFees[{idx}].name",
                                    value=fee.get("name"),
                                    error="Setup fee missing name",
                                    suggestion="Add a descriptive name like 'Initial Setup Fee'",
                                    severity="warning",
                                )
                            )

                        # Validate flatAmount (CORRECTED: uses flatAmount not amount)
                        flat_amount = fee.get("flatAmount")
                        if flat_amount is None:
                            errors.append(
                                ValidationError(
                                    field=f"setupFees[{idx}].flatAmount",
                                    value=flat_amount,
                                    error="Setup fee missing flatAmount",
                                    suggestion="Add 'flatAmount': 100 to specify the fee amount",
                                    severity="error",
                                )
                            )
                        else:
                            try:
                                amount_value = float(flat_amount)
                                if amount_value < 0:
                                    errors.append(
                                        ValidationError(
                                            field=f"setupFees[{idx}].flatAmount",
                                            value=flat_amount,
                                            error="Setup fee flatAmount cannot be negative",
                                            suggestion="Use a positive amount like 100",
                                            severity="error",
                                        )
                                    )
                                elif amount_value == 0:
                                    warnings.append(
                                        ValidationError(
                                            field=f"setupFees[{idx}].flatAmount",
                                            value=flat_amount,
                                            error="Setup fee flatAmount is zero",
                                            suggestion="Consider if a zero setup fee is intentional",
                                            severity="warning",
                                        )
                                    )
                            except (ValueError, TypeError):
                                errors.append(
                                    ValidationError(
                                        field=f"setupFees[{idx}].flatAmount",
                                        value=flat_amount,
                                        error="Setup fee flatAmount must be a valid number",
                                        suggestion="Use a numeric value like 100",
                                        severity="error",
                                    )
                                )

                        # Validate setup fee type (CORRECTED: SUBSCRIPTION vs ORGANIZATION)
                        fee_type = fee.get("type")
                        if not fee_type:
                            errors.append(
                                ValidationError(
                                    field=f"setupFees[{idx}].type",
                                    value=fee_type,
                                    error="Setup fee missing type",
                                    suggestion="Use 'SUBSCRIPTION' (per subscription) or 'ORGANIZATION' (per customer)",
                                    severity="error",
                                )
                            )
                        elif fee_type not in ["SUBSCRIPTION", "ORGANIZATION"]:
                            errors.append(
                                ValidationError(
                                    field=f"setupFees[{idx}].type",
                                    value=fee_type,
                                    error="Invalid setup fee type",
                                    suggestion="Use 'SUBSCRIPTION' (charged per subscription) or 'ORGANIZATION' (charged once per customer)",
                                    severity="error",
                                )
                            )

        # Free Trial Validation
        plan_data = data.get("plan", {})
        trial_duration = (
            plan_data.get("freeTrialDuration")
            or plan_data.get("trialDuration")
            or plan_data.get("trialDurationDays")
        )
        if trial_duration:
            try:
                duration_value = int(trial_duration)
                if duration_value < 0:
                    errors.append(
                        ValidationError(
                            field="plan.freeTrialDuration",
                            value=trial_duration,
                            error="Trial duration cannot be negative",
                            suggestion="Use a positive number of days like 14 or 30",
                            severity="error",
                        )
                    )
                elif duration_value > 365:
                    warnings.append(
                        ValidationError(
                            field="plan.freeTrialDuration",
                            value=trial_duration,
                            error="Trial duration longer than 1 year may be unusual",
                            suggestion="Consider a shorter trial period like 14-90 days",
                            severity="warning",
                        )
                    )
            except (ValueError, TypeError):
                errors.append(
                    ValidationError(
                        field="plan.freeTrialDuration",
                        value=trial_duration,
                        error="Trial duration must be a valid number",
                        suggestion="Use a number of days like 14 or 30",
                        severity="error",
                    )
                )

        # Product Tags Validation (REPLACES custom metadata)
        tags = data.get("tags")
        if tags is not None:
            if not isinstance(tags, list):
                errors.append(
                    ValidationError(
                        field="tags",
                        value=tags,
                        error="Product tags must be an array",
                        suggestion="Use 'tags': ['AI', 'Enterprise', 'SaaS'] format",
                        severity="error",
                    )
                )
            else:
                for idx, tag in enumerate(tags):
                    if not isinstance(tag, str):
                        errors.append(
                            ValidationError(
                                field=f"tags[{idx}]",
                                value=tag,
                                error="Each tag must be a string",
                                suggestion="Use string values like 'AI', 'Enterprise', 'SaaS'",
                                severity="error",
                            )
                        )
                    elif len(tag.strip()) == 0:
                        warnings.append(
                            ValidationError(
                                field=f"tags[{idx}]",
                                value=tag,
                                error="Empty tag found",
                                suggestion="Remove empty tags or provide meaningful tag names",
                                severity="warning",
                            )
                        )
                    elif len(tag) > 50:
                        warnings.append(
                            ValidationError(
                                field=f"tags[{idx}]",
                                value=tag,
                                error="Tag is very long (over 50 characters)",
                                suggestion="Consider shorter, more concise tag names",
                                severity="warning",
                            )
                        )

    @classmethod
    def format_validation_errors(cls, result: ValidationResult) -> str:
        """Format validation errors for display to agents."""
        if result.is_valid:
            return "**Validation Passed** - Ready for API call"

        output = ["**Validation Failed** - Issues found:"]

        # Format errors
        if result.errors:
            output.append("\n**🚨 Errors (must fix):**")
            for error in result.errors:
                output.append(f"• **{error.field}**: {error.error}")
                output.append(f"  💡 **Fix**: {error.suggestion}")

        # Format warnings
        if result.warnings:
            output.append("\n**⚠️ Warnings (recommended fixes):**")
            for warning in result.warnings:
                output.append(f"• **{warning.field}**: {warning.error}")
                output.append(f"  💡 **Suggestion**: {warning.suggestion}")

        output.append("\n**✅ Use get_examples() to see working templates**")

        return "\n".join(output)

    @classmethod
    def get_working_example(cls) -> Dict[str, Any]:
        """Get a simple, immediately usable example for tier-based pricing."""
        return {
            "name": "API Service with Volume Pricing",
            "description": "Pay-per-use API service with volume discounts",
            "version": "1.0.0",
            "paymentSource": "INVOICE_ONLY_NO_PAYMENT",  # Manual invoice payment (most common)
            "plan": {
                "type": "SUBSCRIPTION",
                "name": "API Usage Plan",
                "currency": "USD",  # All pricing in US Dollars
                "period": "MONTH",  # Monthly billing cycle
                "tiers": [
                    {
                        "name": "First 1000 API calls",
                        "up_to": 1000,  # Maximum API calls in this tier (numeric value)
                        "unit_amount": "0.01",  # $0.01 USD per API call in this tier
                    },
                    {
                        "name": "Next 4000 API calls",
                        "up_to": 5000,  # Covers calls 1001-5000
                        "unit_amount": "0.008",  # $0.008 USD per API call (volume discount)
                    },
                    {
                        "name": "Additional API calls",
                        "up_to": None,  # Unlimited tier - covers all calls above 5000
                        "unit_amount": "0.005",  # $0.005 USD per API call (best rate)
                    },
                ],
            },
        }

    @classmethod
    def get_validation_summary(cls) -> Dict[str, Any]:
        """Get summary of validation rules for agents."""
        return {
            "current_valid_values": "UCM-only validation",
            "deprecated_values": {
                field: list(values.keys()) for field, values in cls.DEPRECATED_VALUES.items()
            },
            "required_fields": cls.REQUIRED_FIELDS,
            "working_example": cls.get_working_example(),
        }

    @classmethod
    def test_charge_vs_subscription_scenario(cls) -> Dict[str, Any]:
        """Test the specific CHARGE vs SUBSCRIPTION scenario we discovered.

        This validates that our fix prevents the exact error we encountered
        during our debugging session.

        Returns:
            Test results showing before/after validation
        """
        # The problematic data that caused our original error
        problematic_data = {
            "name": "Debug Test Product",
            "description": "Test product for debugging API connectivity",
            "version": "1.0.0",
            "plan": {
                "type": "CHARGE",  # ❌ This caused the API error
                "name": "Debug Test Plan",
                "currency": "USD",
                "tiers": [{"name": "Basic Tier", "starting_from": 0, "unit_amount": "0.00"}],
            },
        }

        # Test validation
        validation_result = cls.validate_for_mcp(problematic_data)

        return {
            "test_scenario": "CHARGE vs SUBSCRIPTION deprecated plan type",
            "original_api_error": "Failed to create product: This Plan Type has been Deprecated, new Plans with this type can no longer be created: CHARGE; only these types are allowed: SUBSCRIPTION",
            "problematic_data": problematic_data,
            "validation_result": validation_result,
            "prevention_status": (
                "PREVENTED" if validation_result.get("isError") else "FAILED_TO_PREVENT"
            ),
        }
