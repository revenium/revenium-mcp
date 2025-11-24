"""Parameter normalization functions for extracted values.

This module contains functions to normalize and clean extracted parameter values
to ensure consistency and validity.
"""

import re
from datetime import datetime
from typing import Callable, Dict, Optional


class ParameterNormalizers:
    """Manages parameter normalization functions."""

    def __init__(self):
        """Initialize parameter normalizers."""
        self.normalizers = self._build_normalizers()

    def _build_normalizers(self) -> Dict[str, Callable]:
        """Build normalizer functions for each parameter type."""
        return {
            "name": self._normalize_name,
            "email": self._normalize_email,
            "id": self._normalize_id,
            "product_type": self._normalize_product_type,
            "workflow_type": self._normalize_workflow_type,
            "amount": self._normalize_amount,
            "date": self._normalize_date,
            "time_period": self._normalize_time_period,
            "status": self._normalize_status,
            "priority": self._normalize_priority,
        }

    def _normalize_name(self, value: str) -> Optional[str]:
        """Normalize name parameter."""
        if not value or not isinstance(value, str):
            return None

        # Clean up the name
        cleaned = value.strip().strip("\"'")

        # Basic validation
        if len(cleaned) < 1 or len(cleaned) > 100:
            return None

        return cleaned

    def _normalize_email(self, value: str) -> Optional[str]:
        """Normalize email parameter."""
        if not value or not isinstance(value, str):
            return None

        email = value.strip().lower()

        # Basic email validation
        if "@" not in email or "." not in email.split("@")[1]:
            return None

        return email

    def _normalize_id(self, value: str) -> Optional[str]:
        """Normalize ID parameter."""
        if not value or not isinstance(value, str):
            return None

        # Clean up the ID
        cleaned = value.strip()

        # Basic validation - IDs should be alphanumeric with some special chars
        if not re.match(r"^[a-zA-Z0-9_-]+$", cleaned):
            return None

        return cleaned

    def _normalize_amount(self, value: str) -> Optional[float]:
        """Normalize amount parameter."""
        if not value:
            return None

        try:
            # Remove currency symbols and convert to float
            cleaned = re.sub(r"[^\d.]", "", str(value))
            amount = float(cleaned)

            # Basic validation
            if amount < 0 or amount > 1000000:  # Reasonable limits
                return None

            return round(amount, 2)
        except (ValueError, TypeError):
            return None

    def _normalize_date(self, value: str) -> Optional[str]:
        """Normalize date parameter to ISO format."""
        if not value:
            return None

        try:
            # Try different date formats
            for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"]:
                try:
                    parsed_date = datetime.strptime(value, fmt)
                    return parsed_date.strftime("%Y-%m-%d")
                except ValueError:
                    continue

            return None
        except Exception:
            return None

    def _normalize_time_period(self, value: str) -> Optional[str]:
        """Normalize time period to standard format."""
        if not value:
            return None

        value_lower = value.lower().strip()

        # Map common time expressions
        time_mappings = {
            "yesterday": "TWENTY_FOUR_HOURS",
            "today": "TODAY",
            "last week": "SEVEN_DAYS",
            "week": "SEVEN_DAYS",  # Handle "last week" extraction
            "last month": "THIRTY_DAYS",
            "month": "THIRTY_DAYS",  # Handle "last month" extraction
            "last year": "ONE_YEAR",
            "year": "ONE_YEAR",  # Handle "last year" extraction
            "this week": "THIS_WEEK",
            "this month": "THIS_MONTH",
            "this year": "THIS_YEAR",
            "last 24 hours": "TWENTY_FOUR_HOURS",
            "last 24 hour": "TWENTY_FOUR_HOURS",
        }

        return time_mappings.get(value_lower, value_lower.upper())

    def _normalize_status(self, value: str) -> Optional[str]:
        """Normalize status parameter."""
        if not value:
            return None

        status_mappings = {
            "active": "active",
            "inactive": "inactive",
            "pending": "pending",
            "completed": "completed",
            "done": "completed",
            "failed": "failed",
            "error": "failed",
        }

        return status_mappings.get(value.lower().strip())

    def _normalize_priority(self, value: str) -> Optional[str]:
        """Normalize priority parameter."""
        if not value:
            return None

        priority_mappings = {
            "critical": "critical",
            "high": "high",
            "medium": "medium",
            "normal": "medium",
            "low": "low",
        }

        return priority_mappings.get(value.lower().strip())

    def _normalize_product_type(self, value: str) -> Optional[str]:
        """Normalize product type parameter for the 5 core operations."""
        if not value:
            return None

        product_type_mappings = {
            "api": "api",
            "usage": "usage",
            "subscription": "subscription",
            "metering": "metering",
            "billing": "subscription",  # Common alias
            "monitoring": "api",  # Common alias
        }

        # Return the value even if invalid - validation will catch it
        normalized = product_type_mappings.get(value.lower().strip())
        return normalized if normalized else value.lower().strip()

    def _normalize_workflow_type(self, value: str) -> Optional[str]:
        """Normalize workflow type parameter for the 5 core operations."""
        if not value:
            return None

        workflow_type_mappings = {
            "subscription_setup": "subscription_setup",
            "customer_onboarding": "customer_onboarding",
            "product_creation": "product_creation",
            "setup": "subscription_setup",  # Common alias
            "onboarding": "customer_onboarding",  # Common alias
            "creation": "product_creation",  # Common alias
        }

        return workflow_type_mappings.get(value.lower().strip())
