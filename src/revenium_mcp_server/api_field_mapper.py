"""API Field Mapper for Revenium Product API.

This module provides utilities to map between our internal model field names
and the field names expected by the Revenium API.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class APIFieldMapper:
    """Maps internal model fields to API-expected field names."""

    # Field mappings for different model types
    PLAN_FIELD_MAPPING = {
        "type": "type",  # Keep as-is (not planType in API calls)
        "period_count": "periodCount",
        "trial_period": "trialPeriod",
        "trial_period_count": "trialPeriodCount",
        "pre_pay_all_flat_rates": "prePayAllFlatRates",  # Updated to match API
        "rating_aggregations": "ratingAggregations",
        "setup_fees": "setupFees",  # CORRECTED: API uses "setupFees" at product level
        "setupFees": "setupFees",  # Direct mapping for API compatibility
        "notify_client_trial_about_to_expire": "notifyClientTrialAboutToExpire",
        "graduated": "graduated",  # Keep as-is
        "name": "name",  # Keep as-is
        "currency": "currency",  # Keep as-is
        "period": "period",  # Keep as-is
        "charge": "charge",  # Keep as-is
        "tiers": "tiers",  # Keep as-is (but contents need mapping)
        "elements": "elements",  # Keep as-is (but contents need mapping)
        # NEW UI FIELDS - Critical red-highlighted items (CORRECTED MAPPING)
        "setup_fee": "setupFee",  # Setup fee amount
        "setup_charge": "setupCharge",  # Setup charge configuration
        "free_trial_duration": "trialPeriodCount",  # FIXED: Free trial duration in days
        "free_trial_duration_days": "trialPeriodCount",  # FIXED: Alternative field name
        "trial_duration": "trialPeriodCount",  # FIXED: Trial duration
        "trial_duration_days": "trialPeriodCount",  # FIXED: Trial duration in days
        "trial_period": "trialPeriod",  # Trial period type (DAY, WEEK, MONTH)
        "notify_customer_before_trial_end": "notifyClientTrialAboutToExpire",  # FIXED: Trial notification
        # Invoicing & Payment fields
        "invoices_issued": "invoicesIssued",  # When invoices are issued
        "invoice_frequency": "invoiceFrequency",  # How often invoices are sent
        "customers_pay_via": "customersPayVia",  # Payment method
        "send_invoice_to_subscriber": "sendInvoiceToSubscriber",  # Invoice delivery
        "automatically_resend_unpaid_invoices": "automaticallyResendUnpaidInvoices",  # Auto-resend
        "allow_immediate_cancellation": "allowImmediateCancellation",  # Cancellation policy
    }

    TIER_FIELD_MAPPING = {
        "starting_from": "startingFrom",
        "up_to": "upTo",
        "unit_amount": "unitAmount",
        "flat_amount": "flatAmount",
        "name": "name",  # Keep as-is
    }

    RATING_AGGREGATION_FIELD_MAPPING = {
        "type": "aggregationType",
        "metering_element_id": "elementDefinitionId",
        "name": "name",  # Keep as-is
        "period": "period",  # Keep as-is
        "filters": "filters",  # Keep as-is
        "graduated": "graduated",  # Keep as-is
        "distinct_value": "distinctValue",
        "tiers": "tiers",  # Keep as-is (but contents need mapping)
    }

    SETUP_FEE_FIELD_MAPPING = {
        "amount": "flatAmount",
        "name": "name",  # Keep as-is
        "currency": "currency",  # Remove - not used in API
        "description": "description",  # Keep as-is
        "one_time": "oneTime",  # Keep as-is
        "type": "type",  # Add required type field
    }

    ELEMENT_FIELD_MAPPING = {
        "metering_element_definition_id": "elementDefinitionId",
        "name": "name",  # Keep as-is
        "description": "description",  # Keep as-is
        "unit_of_measure": "unitOfMeasure",
        "aggregation_type": "aggregationType",
    }

    PRODUCT_FIELD_MAPPING = {
        "source_ids": "sourceIds",
        "sla_ids": "slaIds",
        "custom_pricing_rule_ids": "customPricingRuleIds",
        "notification_addresses_on_invoice": "notificationAddressesOnInvoice",
        "coming_soon": "comingSoon",
        "metering_models": "meteringModels",
        "notify_client_on_invoice": "notifyClientOnInvoice",
        "subscription_allow_mid_period_cancellation": "subscriptionAllowMidPeriodCancellation",
        "owner_id": "ownerId",
        "team_id": "teamId",
        "payment_configuration_id": "paymentConfigurationId",
        "name": "name",  # Keep as-is
        "version": "version",  # Keep as-is
        "description": "description",  # Keep as-is
        "tags": "tags",  # Keep as-is
        "terms": "terms",  # Keep as-is
        "plan": "plan",  # Keep as-is (but contents need mapping)
        # NEW UI FIELDS - Product-level optional components (CORRECTED)
        "source_ids": "sourceIds",  # Already mapped above
        "setup_fees": "setupFees",  # CORRECTED: API uses "setupFees" at product level
        "setupFees": "setupFees",  # Direct mapping for API compatibility
        "tags": "tags",  # Product tags (WORKING - UI calls this "custom metadata")
        # Working trial fields
        "payment_source": "paymentSource",  # Payment source configuration
        "published": "published",  # Product publication status
        "status": "status",  # Product status
    }

    @staticmethod
    def map_tier_fields(tier_data: Dict[str, Any]) -> Dict[str, Any]:
        """Map tier fields from internal format to API format."""
        mapped = {}

        for internal_field, value in tier_data.items():
            api_field = APIFieldMapper.TIER_FIELD_MAPPING.get(internal_field, internal_field)
            mapped[api_field] = value

        return mapped

    @staticmethod
    def map_rating_aggregation_fields(rating_agg_data: Dict[str, Any]) -> Dict[str, Any]:
        """Map rating aggregation fields from internal format to API format."""
        mapped = {}

        for internal_field, value in rating_agg_data.items():
            if internal_field == "tiers" and isinstance(value, list):
                # Map nested tier fields
                mapped["tiers"] = [APIFieldMapper.map_tier_fields(tier) for tier in value]
            else:
                api_field = APIFieldMapper.RATING_AGGREGATION_FIELD_MAPPING.get(
                    internal_field, internal_field
                )
                mapped[api_field] = value

        return mapped

    @staticmethod
    def map_setup_fee_fields(setup_fee_data: Dict[str, Any]) -> Dict[str, Any]:
        """Map setup fee fields from internal format to API format with backward compatibility."""
        mapped = {}

        for internal_field, value in setup_fee_data.items():
            if internal_field in ["currency", "description", "one_time"]:
                # Skip fields not used in new API structure
                continue
            elif internal_field == "amount":
                # Map amount to flatAmount
                mapped["flatAmount"] = value
            elif internal_field == "type":
                # Handle backward compatibility for old type values
                mapped["type"] = APIFieldMapper._convert_setup_fee_type(value)
            else:
                api_field = APIFieldMapper.SETUP_FEE_FIELD_MAPPING.get(
                    internal_field, internal_field
                )
                mapped[api_field] = value

        # Add default type if not specified
        if "type" not in mapped:
            mapped["type"] = (
                "ORGANIZATION"  # FIXED: Default setup fee type changed from CUSTOMER to ORGANIZATION
            )

        return mapped

    @staticmethod
    def _convert_setup_fee_type(type_value: str) -> str:
        """Convert old setup fee type values to new API format.

        Provides backward compatibility for:
        - PRODUCT_LICENSE → SUBSCRIPTION
        - CUSTOMER → ORGANIZATION
        """
        # Backward compatibility mapping
        type_mapping = {
            "PRODUCT_LICENSE": "SUBSCRIPTION",
            "CUSTOMER": "ORGANIZATION",
            # New values pass through unchanged
            "SUBSCRIPTION": "SUBSCRIPTION",
            "ORGANIZATION": "ORGANIZATION",
        }

        return type_mapping.get(type_value, type_value)

    @staticmethod
    def map_element_fields(element_data: Dict[str, Any]) -> Dict[str, Any]:
        """Map element fields from internal format to API format."""
        mapped = {}

        for internal_field, value in element_data.items():
            api_field = APIFieldMapper.ELEMENT_FIELD_MAPPING.get(internal_field, internal_field)
            mapped[api_field] = value

        return mapped

    @staticmethod
    def map_plan_fields(plan_data: Dict[str, Any]) -> Dict[str, Any]:
        """Map plan fields from internal format to API format."""
        mapped = {}

        for internal_field, value in plan_data.items():
            if internal_field == "tiers" and isinstance(value, list):
                # Map nested tier fields
                mapped["tiers"] = [APIFieldMapper.map_tier_fields(tier) for tier in value]
            elif internal_field == "rating_aggregations" and isinstance(value, list):
                # Map nested rating aggregation fields
                mapped["ratingAggregations"] = [
                    APIFieldMapper.map_rating_aggregation_fields(ra) for ra in value
                ]
            elif internal_field == "setup_fees" and isinstance(value, list):
                # Map nested setup fee fields
                mapped["setups"] = [APIFieldMapper.map_setup_fee_fields(sf) for sf in value]
            elif internal_field == "elements" and isinstance(value, list):
                # Map nested element fields
                mapped["elements"] = [APIFieldMapper.map_element_fields(elem) for elem in value]
            else:
                api_field = APIFieldMapper.PLAN_FIELD_MAPPING.get(internal_field, internal_field)
                mapped[api_field] = value

        return mapped

    @staticmethod
    def map_product_fields(product_data: Dict[str, Any]) -> Dict[str, Any]:
        """Map complete product fields from internal format to API format."""
        mapped = {}

        for internal_field, value in product_data.items():
            if internal_field == "plan" and isinstance(value, dict):
                # Map nested plan fields
                mapped["plan"] = APIFieldMapper.map_plan_fields(value)
            else:
                api_field = APIFieldMapper.PRODUCT_FIELD_MAPPING.get(internal_field, internal_field)
                mapped[api_field] = value

        # Add any required fields that might be missing
        if "published" not in mapped:
            mapped["published"] = True
        if "notifyClientOnInvoice" not in mapped:
            mapped["notifyClientOnInvoice"] = False
        if "paymentSource" not in mapped:
            mapped["paymentSource"] = "INVOICE_ONLY_NO_PAYMENT"
        if "paymentConfigurationId" not in mapped:
            mapped["paymentConfigurationId"] = None
        if "subscriptionAllowMidPeriodCancellation" not in mapped:
            mapped["subscriptionAllowMidPeriodCancellation"] = False
        if "ownerId" not in mapped:
            # This should be provided by the client/environment
            logger.warning("ownerId not provided - this may cause API errors")
        if "teamId" not in mapped:
            # This should be provided by the client/environment
            logger.warning("teamId not provided - this may cause API errors")

        return mapped

    @staticmethod
    def log_field_mapping(original: Dict[str, Any], mapped: Dict[str, Any], context: str = ""):
        """Log field mapping for debugging purposes."""
        logger.debug(f"Field mapping {context}:")
        logger.debug(f"  Original fields: {list(original.keys())}")
        logger.debug(f"  Mapped fields: {list(mapped.keys())}")

        # Log any field changes
        for orig_key, orig_value in original.items():
            if orig_key not in mapped:
                # Find the mapped key
                for mapped_key, mapped_value in mapped.items():
                    if orig_value == mapped_value and orig_key != mapped_key:
                        logger.debug(f"  Mapped: {orig_key} → {mapped_key}")
                        break

    @staticmethod
    def validate_required_api_fields(mapped_data: Dict[str, Any], data_type: str) -> List[str]:
        """Validate that all required API fields are present."""
        missing_fields = []

        if data_type == "product":
            required_fields = ["name", "version", "plan"]
            for field in required_fields:
                if field not in mapped_data or not mapped_data[field]:
                    missing_fields.append(field)

        elif data_type == "plan":
            required_fields = ["name", "planType", "currency"]
            for field in required_fields:
                if field not in mapped_data or not mapped_data[field]:
                    missing_fields.append(field)

        elif data_type == "tier":
            required_fields = ["name"]
            for field in required_fields:
                if field not in mapped_data or not mapped_data[field]:
                    missing_fields.append(field)

        elif data_type == "rating_aggregation":
            required_fields = ["name", "aggregationType", "elementDefinitionId"]
            for field in required_fields:
                if field not in mapped_data or not mapped_data[field]:
                    missing_fields.append(field)

        elif data_type == "setup_fee":
            required_fields = ["name", "flatAmount", "type"]
            for field in required_fields:
                if field not in mapped_data or not mapped_data[field]:
                    missing_fields.append(field)

        return missing_fields

    @staticmethod
    def map_transaction_fields(transaction_data: Dict[str, Any]) -> Dict[str, Any]:
        """Map AI transaction fields from internal format to API format.

        Args:
            transaction_data: Transaction data to map

        Returns:
            Mapped transaction data for API submission
        """
        # For AI transactions, most fields are passed through as-is
        # This method exists for consistency and future field mapping needs
        return transaction_data.copy()
