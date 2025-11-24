"""Comprehensive validation system for Product models and API compatibility.

This module provides robust validation for Product, Plan, Tier, Element, SetupFee,
and RatingAggregation models to ensure data integrity and API compatibility.
"""

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from .exceptions import ValidationError
from .models import (
    AggregationType,
    BillingPeriod,
    Currency,
    PlanType,
    RatingAggregationType,
)


class ProductValidator:
    """Comprehensive validation utilities for Product models."""

    # Validation constants
    MAX_NAME_LENGTH = 255
    MAX_DESCRIPTION_LENGTH = 2000
    MAX_VERSION_LENGTH = 50
    MAX_TAGS_COUNT = 50
    MAX_TAG_LENGTH = 100
    MAX_TIERS_COUNT = 20
    MAX_ELEMENTS_COUNT = 50
    MAX_SETUP_FEES_COUNT = 10
    MAX_RATING_AGGREGATIONS_COUNT = 20

    # Regex patterns
    VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9]+)?$")
    EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
    ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

    @staticmethod
    def validate_product_name(name: Any) -> str:
        """Validate product name."""
        if not name:
            raise ValidationError(
                message="Product name is required",
                field="name",
                expected="Non-empty string",
                suggestion="Provide a descriptive name for your product",
                example={"name": "My API Service"},
            )

        str_name = str(name).strip()
        if len(str_name) < 2:
            raise ValidationError(
                message="Product name must be at least 2 characters long",
                field="name",
                value=str_name,
                expected="String with at least 2 characters",
                suggestion="Use a more descriptive product name",
                example={"name": "API Service Basic"},
            )

        if len(str_name) > ProductValidator.MAX_NAME_LENGTH:
            raise ValidationError(
                message=f"Product name exceeds maximum length of {ProductValidator.MAX_NAME_LENGTH}",
                field="name",
                value=str_name[:50] + "...",
                expected=f"String with at most {ProductValidator.MAX_NAME_LENGTH} characters",
                suggestion="Use a shorter, more concise product name",
                example={"name": "API Service Pro"},
            )

        return str_name

    @staticmethod
    def validate_product_version(version: Any) -> str:
        """Validate product version format (semantic versioning)."""
        if not version:
            raise ValidationError(
                message="Product version is required",
                field="version",
                expected="Semantic version format (e.g., 1.0.0)",
            )

        str_version = str(version).strip()
        if not ProductValidator.VERSION_PATTERN.match(str_version):
            raise ValidationError(
                message="Invalid version format",
                field="version",
                value=str_version,
                expected="Semantic version format (e.g., 1.0.0, 2.1.3-beta)",
            )

        return str_version

    @staticmethod
    def validate_email_list(
        emails: List[str], field_name: str = "notification_addresses"
    ) -> List[str]:
        """Validate list of email addresses."""
        if not emails:
            return []

        if not isinstance(emails, list):
            raise ValidationError(
                message=f"{field_name} must be a list",
                field=field_name,
                value=type(emails).__name__,
                expected="List of email addresses",
            )

        validated_emails = []
        for i, email in enumerate(emails):
            if not email:
                continue

            str_email = str(email).strip().lower()
            if not ProductValidator.EMAIL_PATTERN.match(str_email):
                raise ValidationError(
                    message=f"Invalid email format at position {i}",
                    field=field_name,
                    value=str_email,
                    expected="Valid email format (e.g., user@example.com)",
                )

            if str_email not in validated_emails:  # Remove duplicates
                validated_emails.append(str_email)

        return validated_emails

    @staticmethod
    def validate_id_list(ids: List[str], field_name: str) -> List[str]:
        """Validate list of IDs."""
        if not ids:
            return []

        if not isinstance(ids, list):
            raise ValidationError(
                message=f"{field_name} must be a list",
                field=field_name,
                value=type(ids).__name__,
                expected="List of ID strings",
            )

        validated_ids = []
        for i, id_value in enumerate(ids):
            if not id_value:
                continue

            str_id = str(id_value).strip()
            if not ProductValidator.ID_PATTERN.match(str_id):
                raise ValidationError(
                    message=f"Invalid ID format at position {i}",
                    field=field_name,
                    value=str_id,
                    expected="Alphanumeric characters, hyphens, and underscores only",
                )

            if str_id not in validated_ids:  # Remove duplicates
                validated_ids.append(str_id)

        return validated_ids

    @staticmethod
    def validate_tags(tags: List[str]) -> List[str]:
        """Validate product tags."""
        if not tags:
            return []

        if not isinstance(tags, list):
            raise ValidationError(
                message="Tags must be a list",
                field="tags",
                value=type(tags).__name__,
                expected="List of tag strings",
            )

        if len(tags) > ProductValidator.MAX_TAGS_COUNT:
            raise ValidationError(
                message=f"Too many tags (maximum {ProductValidator.MAX_TAGS_COUNT})",
                field="tags",
                value=len(tags),
                expected=f"List with at most {ProductValidator.MAX_TAGS_COUNT} items",
            )

        validated_tags = []
        for i, tag in enumerate(tags):
            if not tag:
                continue

            str_tag = str(tag).strip()
            if len(str_tag) > ProductValidator.MAX_TAG_LENGTH:
                raise ValidationError(
                    message=f"Tag at position {i} exceeds maximum length",
                    field="tags",
                    value=str_tag[:20] + "...",
                    expected=f"String with at most {ProductValidator.MAX_TAG_LENGTH} characters",
                )

            if str_tag not in validated_tags:  # Remove duplicates
                validated_tags.append(str_tag)

        return validated_tags

    @staticmethod
    def validate_decimal_amount(amount: Any, field_name: str, min_value: float = 0.0) -> Decimal:
        """Validate monetary amount as Decimal."""
        if amount is None:
            raise ValidationError(
                message=f"{field_name} is required", field=field_name, expected="Numeric value"
            )

        try:
            if isinstance(amount, Decimal):
                decimal_amount = amount
            elif isinstance(amount, (int, float)):
                decimal_amount = Decimal(str(amount))
            else:
                decimal_amount = Decimal(str(amount))
        except (InvalidOperation, ValueError):
            raise ValidationError(
                message=f"Invalid {field_name} format",
                field=field_name,
                value=str(amount),
                expected="Valid numeric value",
            )

        if decimal_amount < Decimal(str(min_value)):
            raise ValidationError(
                message=f"{field_name} cannot be negative",
                field=field_name,
                value=str(decimal_amount),
                expected=f"Value >= {min_value}",
            )

        # Round to 2 decimal places for monetary values
        return decimal_amount.quantize(Decimal("0.01"))

    @staticmethod
    def validate_positive_integer(value: Any, field_name: str) -> int:
        """Validate positive integer."""
        if value is None:
            raise ValidationError(
                message=f"{field_name} is required", field=field_name, expected="Positive integer"
            )

        try:
            int_value = int(value)
        except (ValueError, TypeError):
            raise ValidationError(
                message=f"Invalid {field_name} format",
                field=field_name,
                value=str(value),
                expected="Integer value",
            )

        if int_value <= 0:
            raise ValidationError(
                message=f"{field_name} must be positive",
                field=field_name,
                value=int_value,
                expected="Positive integer (> 0)",
            )

        return int_value

    @staticmethod
    def validate_enum_value(value: Any, enum_class: type, field_name: str) -> Any:
        """Validate enum value."""
        if value is None:
            try:
                valid_values = [e.value for e in enum_class]
            except TypeError:
                valid_values = ["(enum values)"]
            raise ValidationError(
                message=f"{field_name} is required",
                field=field_name,
                expected=f"One of: {', '.join(valid_values)}",
                suggestion=f"Provide a valid {field_name} value",
                example={field_name: valid_values[0] if valid_values else "EXAMPLE"},
            )

        # If already an enum instance, validate it's the right type
        if isinstance(value, enum_class):
            return value

        # Try to convert string to enum
        str_value = str(value).upper()
        try:
            for enum_item in enum_class:
                if enum_item.value.upper() == str_value:
                    return enum_item
        except TypeError:
            # Handle case where enum_class is not iterable
            pass

        try:
            valid_values = [e.value for e in enum_class]
        except TypeError:
            valid_values = ["(enum values)"]

        raise ValidationError(
            message=f"Invalid {field_name} value",
            field=field_name,
            value=str(value),
            expected=f"One of: {', '.join(valid_values)}",
            suggestion=f"Use one of the valid {field_name} values",
            example={field_name: valid_values[0] if valid_values else "EXAMPLE"},
        )


class PlanValidator:
    """Validation utilities for Plan models."""

    @staticmethod
    def validate_plan_structure(plan_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate complete plan structure."""
        errors = []

        # Validate plan type
        try:
            plan_type = ProductValidator.validate_enum_value(
                plan_data.get("type"), PlanType, "plan.type"
            )
        except ValidationError as e:
            errors.append(e)
            plan_type = None

        # Validate currency
        try:
            ProductValidator.validate_enum_value(
                plan_data.get("currency"), Currency, "plan.currency"
            )
        except ValidationError as e:
            errors.append(e)

        # Validate tiers (at least one required, either in tiers or rating aggregations)
        tiers = plan_data.get("tiers", [])
        rating_aggregations = plan_data.get("rating_aggregations", [])

        has_plan_tiers = tiers and len(tiers) > 0
        has_rating_agg_tiers = any(
            ra.get("tiers") and len(ra.get("tiers", [])) > 0 for ra in rating_aggregations
        )

        if not has_plan_tiers and not has_rating_agg_tiers:
            errors.append(
                ValidationError(
                    message="Plan must have at least one tier (either in plan.tiers or in rating aggregations)",
                    field="plan.tiers",
                    expected="List with at least one tier, or rating aggregations with tiers",
                )
            )
        elif has_plan_tiers:
            # Validate tier structure only if plan has tiers
            try:
                TierValidator.validate_tiers_list(tiers)
            except ValidationError as e:
                errors.append(e)

        # Validate subscription-specific fields
        if plan_type == PlanType.SUBSCRIPTION:
            period = plan_data.get("period")
            if not period:
                errors.append(
                    ValidationError(
                        message="Subscription plans require a billing period",
                        field="plan.period",
                        expected=f"One of: {', '.join([p.value for p in BillingPeriod])}",
                    )
                )

        if errors:
            # Combine multiple errors into one
            error_messages = [e.message for e in errors]
            raise ValidationError(
                message=f"Plan validation failed: {'; '.join(error_messages)}",
                field="plan",
                expected="Valid plan structure",
            )

        return plan_data


class TierValidator:
    """Validation utilities for Tier models."""

    @staticmethod
    def validate_tier_range(up_to: Any) -> Any:
        """Validate tier up_to value."""
        if up_to is not None:
            end_val = ProductValidator.validate_decimal_amount(up_to, "up_to", 0.0)
            if end_val <= 0:
                raise ValidationError(
                    message="Tier up_to value must be positive",
                    field="up_to",
                    value=f"up_to: {end_val}",
                    expected="Positive number or null for unlimited tier",
                )
            return end_val

        return None

    @staticmethod
    def validate_tiers_list(tiers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Validate list of tiers for overlaps and consistency."""
        if len(tiers) > ProductValidator.MAX_TIERS_COUNT:
            raise ValidationError(
                message=f"Too many tiers (maximum {ProductValidator.MAX_TIERS_COUNT})",
                field="tiers",
                value=len(tiers),
                expected=f"List with at most {ProductValidator.MAX_TIERS_COUNT} items",
            )

        # Validate each tier
        validated_tiers = []

        for i, tier in enumerate(tiers):
            try:
                # Validate tier structure
                ProductValidator.validate_product_name(tier.get("name", f"Tier {i+1}"))

                # Validate up_to value
                TierValidator.validate_tier_range(tier.get("up_to"))

                # Validate that either unit_amount or flat_amount is provided
                unit_amount = tier.get("unit_amount")
                flat_amount = tier.get("flat_amount")

                if unit_amount is None and flat_amount is None:
                    raise ValidationError(
                        message="Tier must have either unit_amount or flat_amount (or both). Use unit_amount for per-unit pricing (e.g., per API call) or flat_amount for one-time fees (e.g., setup costs).",
                        field=f"tier[{i}]",
                        value="Missing both unit_amount and flat_amount",
                        expected="At least one pricing field: unit_amount (per-unit price) or flat_amount (one-time fee)",
                    )

                # Validate amounts if provided
                if unit_amount is not None:
                    ProductValidator.validate_decimal_amount(unit_amount, f"tier[{i}].unit_amount")
                if flat_amount is not None:
                    ProductValidator.validate_decimal_amount(flat_amount, f"tier[{i}].flat_amount")

                # Warn if starting_from is provided (should not be in user input)
                if "starting_from" in tier:
                    # This is a warning, not an error, to maintain backward compatibility
                    pass  # Warning will be handled by validation engine

                validated_tiers.append(tier)

            except ValidationError as e:
                # Create new ValidationError with updated field path
                original_field = e.details.get("field", "")
                new_field = f"tiers[{i}].{original_field}" if original_field else f"tiers[{i}]"
                raise ValidationError(
                    message=e.message,
                    field=new_field,
                    value=e.details.get("provided_value"),
                    expected=e.details.get("expected"),
                    suggestion=e.details.get("suggestion"),
                )

        # Validate tier structure rules
        TierValidator.validate_tier_structure_rules(validated_tiers)

        return validated_tiers

    @staticmethod
    def validate_tier_structure_rules(tiers: List[Dict[str, Any]]) -> None:
        """Validate tier structure rules based on Revenium API requirements.

        Rules:
        1. Final tier must ALWAYS have up_to: null (unlimited)
        2. All tiers below the final tier must have up_to values
        3. Single-tier products: Only tier has up_to: null
        4. Multi-tier products: All tiers except the last must have up_to values

        Args:
            tiers: List of validated tier dictionaries

        Raises:
            ValidationError: If tier structure rules are violated
        """
        if not tiers:
            return

        num_tiers = len(tiers)

        # Check each tier's up_to value
        for i, tier in enumerate(tiers):
            is_final_tier = i == num_tiers - 1
            up_to_value = tier.get("up_to")

            if is_final_tier:
                # Final tier must have up_to: null
                if up_to_value is not None:
                    raise ValidationError(
                        message="Final tier must have up_to: null to create an unlimited tier that handles all usage above previous tiers. This ensures all customer usage is properly billed.",
                        field=f"tiers[{i}].up_to",
                        value=str(up_to_value),
                        expected="null (creates unlimited tier for all usage above previous tier limits)",
                    )
            else:
                # Non-final tiers must have up_to values
                if up_to_value is None:
                    raise ValidationError(
                        message="Non-final tiers must have numeric up_to values to define the maximum usage in each tier. The API uses these values to automatically calculate tier ranges.",
                        field=f"tiers[{i}].up_to",
                        value="null",
                        expected="Numeric value defining tier upper limit (e.g., 1000 for first 1000 units)",
                    )

    @staticmethod
    def _ranges_overlap(
        start1: Decimal, end1: Optional[Decimal], start2: Decimal, end2: Optional[Decimal]
    ) -> bool:
        """Check if two ranges overlap."""
        # If either range is open-ended (end is None), handle specially
        if end1 is None and end2 is None:
            return start1 == start2  # Both open-ended from same point
        if end1 is None:
            return start1 < (end2 or float("inf"))
        if end2 is None:
            return start2 < end1

        # Both ranges have defined ends
        return not (end1 <= start2 or end2 <= start1)


class ElementValidator:
    """Validation utilities for Element models."""

    @staticmethod
    def validate_element_structure(element_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate element structure."""
        # Validate required fields
        if not element_data.get("metering_element_definition_id"):
            raise ValidationError(
                message="Metering element definition ID is required",
                field="metering_element_definition_id",
                expected="Non-empty string",
            )

        if not element_data.get("name"):
            raise ValidationError(
                message="Element name is required", field="name", expected="Non-empty string"
            )

        # Validate name
        ProductValidator.validate_product_name(element_data["name"])

        # Validate aggregation type if provided
        aggregation_type = element_data.get("aggregation_type")
        if aggregation_type:
            ProductValidator.validate_enum_value(
                aggregation_type, AggregationType, "aggregation_type"
            )

        return element_data

    @staticmethod
    def validate_elements_list(elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Validate list of elements."""
        if len(elements) > ProductValidator.MAX_ELEMENTS_COUNT:
            raise ValidationError(
                message=f"Too many elements (maximum {ProductValidator.MAX_ELEMENTS_COUNT})",
                field="elements",
                value=len(elements),
                expected=f"List with at most {ProductValidator.MAX_ELEMENTS_COUNT} items",
            )

        validated_elements = []
        element_ids = set()

        for i, element in enumerate(elements):
            try:
                validated_element = ElementValidator.validate_element_structure(element)

                # Check for duplicate element definition IDs
                element_id = validated_element["metering_element_definition_id"]
                if element_id in element_ids:
                    raise ValidationError(
                        message=f"Duplicate metering element definition ID: {element_id}",
                        field="metering_element_definition_id",
                        value=element_id,
                        expected="Unique element definition ID",
                    )

                element_ids.add(element_id)
                validated_elements.append(validated_element)

            except ValidationError as e:
                # Create new ValidationError with updated field path
                original_field = e.details.get("field", "")
                new_field = (
                    f"elements[{i}].{original_field}" if original_field else f"elements[{i}]"
                )
                raise ValidationError(
                    message=e.message,
                    field=new_field,
                    value=e.details.get("provided_value"),
                    expected=e.details.get("expected"),
                    suggestion=e.details.get("suggestion"),
                )

        return validated_elements


class SetupFeeValidator:
    """Validation utilities for SetupFee models."""

    @staticmethod
    def validate_setup_fee_structure(setup_fee_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate setup fee structure with backward compatibility."""
        # Validate required fields
        if not setup_fee_data.get("name"):
            raise ValidationError(
                message="Setup fee name is required", field="name", expected="Non-empty string"
            )

        # Validate name
        ProductValidator.validate_product_name(setup_fee_data["name"])

        # Validate amount/flatAmount (backward compatibility)
        amount_value = setup_fee_data.get("flatAmount") or setup_fee_data.get("amount")
        if amount_value is None:
            raise ValidationError(
                message="Setup fee amount is required (use 'flatAmount' field)",
                field="flatAmount",
                expected="Positive number",
                suggestion="Use 'flatAmount' instead of 'amount' for new API structure",
            )

        # Validate amount is positive
        ProductValidator.validate_decimal_amount(amount_value, "flatAmount", min_value=0.01)

        # Validate type with backward compatibility
        fee_type = setup_fee_data.get("type", "ORGANIZATION")
        if fee_type in ["PRODUCT_LICENSE", "CUSTOMER"]:
            # Provide migration guidance but don't fail validation
            migration_msg = {"PRODUCT_LICENSE": "SUBSCRIPTION", "CUSTOMER": "ORGANIZATION"}.get(
                fee_type, fee_type
            )

            # Log migration notice but continue processing
            import logging

            logger = logging.getLogger(__name__)
            logger.info(f"Setup fee type migration: {fee_type} → {migration_msg}")

        # Validate type is valid (after potential conversion)
        valid_types = ["SUBSCRIPTION", "ORGANIZATION", "PRODUCT_LICENSE", "CUSTOMER"]
        if fee_type not in valid_types:
            raise ValidationError(
                message=f"Invalid setup fee type: {fee_type}",
                field="type",
                expected="SUBSCRIPTION or ORGANIZATION",
                suggestion="Use SUBSCRIPTION for per-subscription fees or ORGANIZATION for per-customer fees",
            )

        # Note: currency, description, one_time fields are ignored for new API structure
        # but we don't fail validation if they're present (backward compatibility)

        return setup_fee_data

    @staticmethod
    def validate_setup_fees_list(setup_fees: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Validate list of setup fees."""
        if len(setup_fees) > ProductValidator.MAX_SETUP_FEES_COUNT:
            raise ValidationError(
                message=f"Too many setup fees (maximum {ProductValidator.MAX_SETUP_FEES_COUNT})",
                field="setup_fees",
                value=len(setup_fees),
                expected=f"List with at most {ProductValidator.MAX_SETUP_FEES_COUNT} items",
            )

        validated_fees = []
        fee_names = set()

        for i, fee in enumerate(setup_fees):
            try:
                validated_fee = SetupFeeValidator.validate_setup_fee_structure(fee)

                # Check for duplicate fee names
                fee_name = validated_fee["name"]
                if fee_name in fee_names:
                    raise ValidationError(
                        message=f"Duplicate setup fee name: {fee_name}",
                        field="name",
                        value=fee_name,
                        expected="Unique setup fee name",
                    )

                fee_names.add(fee_name)
                validated_fees.append(validated_fee)

            except ValidationError as e:
                # Create new ValidationError with updated field path
                original_field = e.details.get("field", "")
                new_field = (
                    f"setup_fees[{i}].{original_field}" if original_field else f"setup_fees[{i}]"
                )
                raise ValidationError(
                    message=e.message,
                    field=new_field,
                    value=e.details.get("provided_value"),
                    expected=e.details.get("expected"),
                    suggestion=e.details.get("suggestion"),
                )

        return validated_fees


class RatingAggregationValidator:
    """Validation utilities for RatingAggregation models."""

    @staticmethod
    def validate_rating_aggregation_structure(rating_agg_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate rating aggregation structure."""
        # Validate required fields
        if not rating_agg_data.get("name"):
            raise ValidationError(
                message="Rating aggregation name is required",
                field="name",
                expected="Non-empty string",
            )

        if not rating_agg_data.get("metering_element_id"):
            raise ValidationError(
                message="Metering element ID is required",
                field="metering_element_id",
                expected="Non-empty string",
            )

        # Validate name
        ProductValidator.validate_product_name(rating_agg_data["name"])

        # Validate aggregation type
        ProductValidator.validate_enum_value(
            rating_agg_data.get("type"), RatingAggregationType, "type"
        )

        # Validate period if provided
        period = rating_agg_data.get("period")
        if period:
            ProductValidator.validate_enum_value(period, BillingPeriod, "period")

        # Validate tiers if provided
        tiers = rating_agg_data.get("tiers", [])
        if tiers:
            TierValidator.validate_tiers_list(tiers)

        return rating_agg_data

    @staticmethod
    def validate_rating_aggregations_list(
        rating_aggs: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Validate list of rating aggregations."""
        if len(rating_aggs) > ProductValidator.MAX_RATING_AGGREGATIONS_COUNT:
            raise ValidationError(
                message=f"Too many rating aggregations (maximum {ProductValidator.MAX_RATING_AGGREGATIONS_COUNT})",
                field="rating_aggregations",
                value=len(rating_aggs),
                expected=f"List with at most {ProductValidator.MAX_RATING_AGGREGATIONS_COUNT} items",
            )

        validated_aggs = []
        agg_names = set()

        for i, agg in enumerate(rating_aggs):
            try:
                validated_agg = RatingAggregationValidator.validate_rating_aggregation_structure(
                    agg
                )

                # Check for duplicate aggregation names
                agg_name = validated_agg["name"]
                if agg_name in agg_names:
                    raise ValidationError(
                        message=f"Duplicate rating aggregation name: {agg_name}",
                        field="name",
                        value=agg_name,
                        expected="Unique rating aggregation name",
                    )

                agg_names.add(agg_name)
                validated_aggs.append(validated_agg)

            except ValidationError as e:
                # Create new ValidationError with updated field path
                original_field = e.details.get("field", "")
                new_field = (
                    f"rating_aggregations[{i}].{original_field}"
                    if original_field
                    else f"rating_aggregations[{i}]"
                )
                raise ValidationError(
                    message=e.message,
                    field=new_field,
                    value=e.details.get("provided_value"),
                    expected=e.details.get("expected"),
                    suggestion=e.details.get("suggestion"),
                )

        return validated_aggs


class ProductValidationEngine:
    """Main validation engine for complete product validation."""

    @staticmethod
    def validate_complete_product(product_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate complete product structure with all nested components."""
        errors = []

        # Validate basic product fields
        try:
            ProductValidator.validate_product_name(product_data.get("name"))
        except ValidationError as e:
            errors.append(e)

        try:
            ProductValidator.validate_product_version(product_data.get("version"))
        except ValidationError as e:
            errors.append(e)

        # Validate email notifications
        try:
            ProductValidator.validate_email_list(
                product_data.get("notification_addresses_on_invoice", []),
                "notification_addresses_on_invoice",
            )
        except ValidationError as e:
            errors.append(e)

        # Validate ID lists
        for field in ["source_ids", "sla_ids", "custom_pricing_rule_ids", "metering_models"]:
            try:
                ProductValidator.validate_id_list(product_data.get(field, []), field)
            except ValidationError as e:
                errors.append(e)

        # Validate tags
        try:
            ProductValidator.validate_tags(product_data.get("tags", []))
        except ValidationError as e:
            errors.append(e)

        # Validate plan structure
        plan_data = product_data.get("plan")
        if not plan_data:
            errors.append(
                ValidationError(
                    message="Product plan is required",
                    field="plan",
                    expected="Valid plan object",
                    suggestion="Add a plan configuration with type, name, and currency",
                    example={
                        "plan": {
                            "type": "SUBSCRIPTION",
                            "name": "Basic Plan",
                            "currency": "USD",
                            "period": "MONTH",
                            "tiers": [
                                {"name": "Standard Tier", "up_to": None, "unit_amount": "0.01"}
                            ],
                        }
                    },
                )
            )
        else:
            try:
                PlanValidator.validate_plan_structure(plan_data)

                # Validate nested components
                if "tiers" in plan_data:
                    TierValidator.validate_tiers_list(plan_data["tiers"])

                if "elements" in plan_data and plan_data["elements"]:
                    ElementValidator.validate_elements_list(plan_data["elements"])

                if "setup_fees" in plan_data and plan_data["setup_fees"]:
                    SetupFeeValidator.validate_setup_fees_list(plan_data["setup_fees"])

                if "rating_aggregations" in plan_data and plan_data["rating_aggregations"]:
                    RatingAggregationValidator.validate_rating_aggregations_list(
                        plan_data["rating_aggregations"]
                    )

            except ValidationError as e:
                errors.append(e)

        # If there are validation errors, combine them
        if errors:
            error_messages = [f"{e.details.get('field', 'unknown')}: {e.message}" for e in errors]
            raise ValidationError(
                message=f"Product validation failed with {len(errors)} errors: {'; '.join(error_messages)}",
                field="product",
                expected="Valid product structure",
            )

        return product_data

    @staticmethod
    def validate_product_for_api(product_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate product data specifically for API submission."""
        # First run complete validation
        validated_data = ProductValidationEngine.validate_complete_product(product_data)

        # Additional API-specific validations
        plan = validated_data["plan"]

        # Ensure subscription plans have required fields
        if plan.get("type") == "SUBSCRIPTION":
            if not plan.get("period"):
                raise ValidationError(
                    message="Subscription plans must specify a billing period",
                    field="plan.period",
                    expected=f"One of: {', '.join([p.value for p in BillingPeriod])}",
                )

        # Ensure at least one tier exists (either in plan.tiers or in rating aggregations)
        plan_tiers = plan.get("tiers", [])
        rating_aggregations = plan.get("rating_aggregations", [])

        has_plan_tiers = plan_tiers and len(plan_tiers) > 0
        has_rating_agg_tiers = any(
            ra.get("tiers") and len(ra.get("tiers", [])) > 0 for ra in rating_aggregations
        )

        if not has_plan_tiers and not has_rating_agg_tiers:
            raise ValidationError(
                message="Plan must have at least one pricing tier (either in plan.tiers or in rating aggregations)",
                field="plan.tiers",
                expected="List with at least one tier, or rating aggregations with tiers",
            )

        return validated_data
