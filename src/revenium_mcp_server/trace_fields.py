"""Trace field extraction for AI transaction tracing support.

This module provides functions to extract tracing fields from usage_metadata arguments
and environment variables for distributed tracing and observability.

Follows the same pattern as revenium-middleware-openai-python-internal.
"""

import os
import re
from typing import Any, Dict, Optional


# Environment variable mappings for each trace field
# Each field can be set via multiple environment variables (first match wins)
TRACE_FIELD_ENV_VARS = {
    "environment": ["REVENIUM_ENVIRONMENT", "ENVIRONMENT", "DEPLOYMENT_ENV"],
    "region": ["REVENIUM_REGION", "AWS_REGION", "AZURE_REGION", "GCP_REGION"],
    "credential_alias": ["REVENIUM_CREDENTIAL_ALIAS"],
    "trace_type": ["REVENIUM_TRACE_TYPE"],
    "trace_name": ["REVENIUM_TRACE_NAME"],
    "parent_transaction_id": ["REVENIUM_PARENT_TRANSACTION_ID"],
    "transaction_name": ["REVENIUM_TRANSACTION_NAME"],
    "operation_type": [],  # Usually auto-detected, no default env var
    "operation_subtype": [],  # Usually passed explicitly
    "retry_number": ["REVENIUM_RETRY_NUMBER"],
}

# Field name aliases (maps camelCase to snake_case)
FIELD_ALIASES = {
    "parentSpanId": "parent_transaction_id",
    "parentTransactionId": "parent_transaction_id",
    "transactionName": "transaction_name",
    "operationType": "operation_type",
    "operationSubtype": "operation_subtype",
    "retryNumber": "retry_number",
    "traceType": "trace_type",
    "traceName": "trace_name",
    "credentialAlias": "credential_alias",
}

# API field names (snake_case to camelCase for API payload)
API_FIELD_MAPPING = {
    "environment": "environment",
    "region": "region",
    "credential_alias": "credentialAlias",
    "trace_type": "traceType",
    "trace_name": "traceName",
    "parent_transaction_id": "parentTransactionId",
    "transaction_name": "transactionName",
    "operation_type": "operationType",
    "operation_subtype": "operationSubtype",
    "retry_number": "retryNumber",
}

# Validation constraints
TRACE_TYPE_MAX_LENGTH = 128
TRACE_TYPE_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')
TRACE_NAME_MAX_LENGTH = 256


def _get_env_value(field_name: str) -> Optional[str]:
    """Get value from environment variables for a trace field.

    Args:
        field_name: The snake_case field name

    Returns:
        The value from the first matching environment variable, or None
    """
    env_vars = TRACE_FIELD_ENV_VARS.get(field_name, [])
    for env_var in env_vars:
        value = os.getenv(env_var)
        # Use 'is not None' to allow explicitly set empty strings
        if value is not None:
            return value
    return None


def _normalize_field_name(field_name: str) -> str:
    """Normalize field name to snake_case.

    Args:
        field_name: Field name in any case format

    Returns:
        Normalized snake_case field name
    """
    # Check if it's an alias (camelCase)
    if field_name in FIELD_ALIASES:
        return FIELD_ALIASES[field_name]
    return field_name


def _validate_trace_type(value: str) -> Optional[str]:
    """Validate and return trace_type value.

    Args:
        value: The trace_type value to validate

    Returns:
        Validated value or None if invalid
    """
    if not value:
        return None
    if len(value) > TRACE_TYPE_MAX_LENGTH:
        return None
    if not TRACE_TYPE_PATTERN.match(value):
        return None
    return value


def _validate_trace_name(value: str) -> str:
    """Validate and possibly truncate trace_name value.

    Args:
        value: The trace_name value to validate

    Returns:
        Validated/truncated value
    """
    if not value:
        return value
    # Auto-truncate if longer than max length
    if len(value) > TRACE_NAME_MAX_LENGTH:
        return value[:TRACE_NAME_MAX_LENGTH]
    return value


def _validate_retry_number(value: Any) -> Optional[int]:
    """Validate and convert retry_number to integer.

    Args:
        value: The retry_number value to validate

    Returns:
        Integer value or None if invalid
    """
    if value is None:
        return None
    try:
        int_value = int(value)
        if int_value < 0:
            return None
        return int_value
    except (ValueError, TypeError):
        return None


def get_trace_field_value(
    field_name: str, arguments: Dict[str, Any], usage_metadata: Optional[Dict[str, Any]] = None
) -> Optional[Any]:
    """Get a trace field value with priority: arguments > usage_metadata > env var.

    Args:
        field_name: The field name (can be camelCase or snake_case)
        arguments: Direct arguments from the caller
        usage_metadata: Optional usage_metadata dict from arguments

    Returns:
        The field value or None if not set
    """
    # Normalize field name
    normalized_name = _normalize_field_name(field_name)

    # Check direct arguments first (both normalized and original)
    # Use explicit None checks to preserve falsy values like 0 or ""
    value = arguments.get(normalized_name)
    if value is None:
        value = arguments.get(field_name)

    # Also check for camelCase aliases in arguments
    if value is None:
        for alias, target in FIELD_ALIASES.items():
            if target == normalized_name and alias in arguments:
                value = arguments[alias]
                break

    # Check usage_metadata if provided (both normalized and original)
    # Use explicit None checks to preserve falsy values like 0 or ""
    if value is None and usage_metadata:
        value = usage_metadata.get(normalized_name)
        if value is None:
            value = usage_metadata.get(field_name)
        # Also check for camelCase aliases in usage_metadata
        if value is None:
            for alias, target in FIELD_ALIASES.items():
                if target == normalized_name and alias in usage_metadata:
                    value = usage_metadata[alias]
                    break

    # Fall back to environment variable
    if value is None:
        value = _get_env_value(normalized_name)

    return value


def extract_trace_fields(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Extract all trace fields from arguments with validation.

    This function extracts the 10 tracing fields from arguments, checking both
    direct arguments and the usage_metadata nested object. Values are validated
    and mapped to their API field names.

    Args:
        arguments: Arguments dict that may contain trace fields or usage_metadata

    Returns:
        Dict with API-formatted trace fields (only non-None values included)
    """
    # Get usage_metadata if present and is a valid dict
    # Guard against non-dict values (e.g., string/list) that would raise on .get()
    usage_metadata_raw = arguments.get("usage_metadata")
    usage_metadata = usage_metadata_raw if isinstance(usage_metadata_raw, dict) else None

    trace_fields = {}

    # 1. environment
    value = get_trace_field_value("environment", arguments, usage_metadata)
    if value:
        trace_fields["environment"] = str(value)

    # 2. region
    value = get_trace_field_value("region", arguments, usage_metadata)
    if value:
        trace_fields["region"] = str(value)

    # 3. credential_alias
    value = get_trace_field_value("credential_alias", arguments, usage_metadata)
    if value:
        trace_fields["credentialAlias"] = str(value)

    # 4. trace_type (with validation)
    value = get_trace_field_value("trace_type", arguments, usage_metadata)
    if value:
        validated = _validate_trace_type(str(value))
        if validated:
            trace_fields["traceType"] = validated

    # 5. trace_name (with auto-truncation)
    value = get_trace_field_value("trace_name", arguments, usage_metadata)
    if value:
        trace_fields["traceName"] = _validate_trace_name(str(value))

    # 6. parent_transaction_id (also accepts parentSpanId, parentTransactionId)
    value = get_trace_field_value("parent_transaction_id", arguments, usage_metadata)
    if value:
        trace_fields["parentTransactionId"] = str(value)

    # 7. transaction_name (also accepts transactionName)
    value = get_trace_field_value("transaction_name", arguments, usage_metadata)
    if value:
        trace_fields["transactionName"] = str(value)

    # 8. operation_type (also accepts operationType) - can override default
    # Only include non-empty values; empty strings are rejected by validation anyway
    value = get_trace_field_value("operation_type", arguments, usage_metadata)
    if value:
        trace_fields["operationType"] = str(value)

    # 9. operation_subtype (also accepts operationSubtype)
    # Only include non-empty values for consistency with other string fields
    value = get_trace_field_value("operation_subtype", arguments, usage_metadata)
    if value:
        trace_fields["operationSubtype"] = str(value)

    # 10. retry_number (also accepts retryNumber)
    value = get_trace_field_value("retry_number", arguments, usage_metadata)
    if value is not None:
        validated = _validate_retry_number(value)
        if validated is not None:
            trace_fields["retryNumber"] = validated

    return trace_fields


# List of all trace field names (snake_case) for schema/validation purposes
TRACE_FIELD_NAMES = [
    "environment",
    "region",
    "credential_alias",
    "trace_type",
    "trace_name",
    "parent_transaction_id",
    "transaction_name",
    "operation_type",
    "operation_subtype",
    "retry_number",
]

