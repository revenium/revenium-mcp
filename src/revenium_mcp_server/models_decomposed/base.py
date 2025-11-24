"""Base model classes and common patterns for Revenium data models.

This module contains the foundational model classes and mixins that are used
across all domain-specific models in the MCP server.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class BaseReveniumModel(BaseModel):
    """Base model for all Revenium API responses and data structures.

    This base class provides common configuration and utility methods
    that are shared across all Revenium data models.
    """

    model_config = ConfigDict(
        extra="allow",  # Allow extra fields from API
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary, excluding None values.

        Returns:
            Dictionary representation of the model
        """
        return self.model_dump(exclude_none=True)

    def to_json(self) -> str:
        """Convert model to JSON string.

        Returns:
            JSON string representation of the model
        """
        return self.model_dump_json(exclude_none=True)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseReveniumModel":
        """Create model instance from dictionary.

        Args:
            data: Dictionary containing model data

        Returns:
            Model instance
        """
        return cls(**data)


class TimestampMixin(BaseModel):
    """Mixin for models that include timestamp fields.

    Provides created_at and updated_at fields with appropriate defaults.
    """

    created_at: Optional[datetime] = Field(None, description="Creation timestamp")
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")


class IdentifierMixin(BaseModel):
    """Mixin for models that include an ID field.

    Provides a standard id field that can be used across different model types.
    """

    id: Optional[str] = Field(None, description="Unique identifier")


class MetadataMixin(BaseModel):
    """Mixin for models that include metadata fields.

    Provides a flexible metadata field for storing additional information.
    """

    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")


class StatusMixin(BaseModel):
    """Mixin for models that include a status field.

    Provides a generic status field that can be customized by specific models.
    """

    status: Optional[str] = Field(None, description="Current status")


# Common response models


class APIResponse(BaseReveniumModel):
    """Generic API response wrapper for standard API responses."""

    success: bool = Field(True, description="Whether the request was successful")
    data: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = Field(
        None, description="Response data"
    )
    message: Optional[str] = Field(None, description="Response message")
    error: Optional[str] = Field(None, description="Error message if any")
    total: Optional[int] = Field(None, description="Total count for paginated responses")
    page: Optional[int] = Field(None, description="Current page for paginated responses")
    per_page: Optional[int] = Field(None, description="Items per page for paginated responses")


class ListResponse(BaseReveniumModel):
    """Response model for list operations with pagination support."""

    items: List[Dict[str, Any]] = Field(default_factory=list, description="List of items")
    total: int = Field(0, description="Total number of items")
    page: int = Field(1, description="Current page number")
    per_page: int = Field(20, description="Items per page")
    has_more: bool = Field(False, description="Whether there are more pages")


# REMOVED: Hardcoded validation enums - now using UCM-only validation
# These enums were used for validation but are now replaced with dynamic UCM capabilities

# Note: These enums are preserved as comments for reference but should not be used for validation
# Currency options: USD, EUR, GBP, CAD, AUD, JPY
# BillingPeriod options: MONTH, YEAR, QUARTER, WEEK, DAY
# TrialPeriod options: DAY, WEEK, MONTH
# AggregationType options: SUM, COUNT, MAX, MIN, AVERAGE, LAST


class RatingAggregationType(str, Enum):
    """Rating aggregation type enumeration."""

    SUM = "SUM"
    COUNT = "COUNT"
    MAX = "MAX"
    MIN = "MIN"
    AVERAGE = "AVERAGE"


# Utility functions for model validation


def validate_email_address(email: str) -> str:
    """Validate email address format.

    Args:
        email: Email address to validate

    Returns:
        Validated email address

    Raises:
        ValueError: If email format is invalid
    """
    import re

    email_pattern = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
    if not email_pattern.match(email):
        raise ValueError(f"Invalid email address: {email}")
    return email


def validate_positive_number(
    value: Union[int, float], field_name: str = "value"
) -> Union[int, float]:
    """Validate that a number is positive.

    Args:
        value: Number to validate
        field_name: Name of the field for error messages

    Returns:
        Validated number

    Raises:
        ValueError: If number is not positive
    """
    if value is not None and value <= 0:
        raise ValueError(f"{field_name} must be positive")
    return value


def validate_non_empty_string(value: str, field_name: str = "value") -> str:
    """Validate that a string is not empty.

    Args:
        value: String to validate
        field_name: Name of the field for error messages

    Returns:
        Validated string

    Raises:
        ValueError: If string is empty
    """
    if not value or not value.strip():
        raise ValueError(f"{field_name} cannot be empty")
    return value.strip()
