"""Consolidated AI metering management tool following MCP best practices.

This module consolidates enhanced_metering_tools.py into a single tool with unified architecture,
following the proven alert/source/customer/product/workflow management template.
"""

import asyncio
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union, Tuple, Callable, Awaitable
from loguru import logger

from mcp.types import TextContent, ImageContent, EmbeddedResource

from ..client import ReveniumClient
from ..agent_friendly import UnifiedResponseFormatter
from ..common.validation import validate_pagination_params
from ..endpoint_registry import get_endpoint_path
from .unified_tool_base import ToolBase
from ..common.error_handling import (
    ErrorCodes,
    ToolError,
    create_structured_validation_error,
    create_structured_missing_parameter_error,
)

# Performance monitoring removed - infrastructure monitoring handled externally
from ..core.response_cache import response_cache, cache_response
from ..introspection.metadata import ToolType, ToolCapability, ToolDependency, DependencyType
from ..trace_fields import extract_trace_fields


# Import Prometheus metrics if available
# Prometheus metrics removed - infrastructure monitoring handled externally


# BACK-1139: Canonical provider enum enforced on the submit_ai_transaction
# write path. Mirrors the list used by analytics_registry.validate_request,
# so a transaction that satisfies the metering enum will also satisfy the
# read-side analytics filters. Compared case-insensitively (the API persists
# upper-case but several examples in the docs use lower-case).
_VALID_PROVIDERS = (
    "OPENAI",
    "ANTHROPIC",
    "GOOGLE",
    "AZURE",
    "COHERE",
    "MISTRAL",
    "TOGETHER",
    "GROQ",
)
PROMETHEUS_METRICS_AVAILABLE = False

# Accepted transaction_id formats. The backend silently drops ids it does not
# recognize, so anything outside this whitelist must be rejected at the MCP
# boundary — otherwise submit returns "submitted" while the row never lands
# in the analytics pipeline.
#   - Internal: emitted by _generate_transaction_id (`tx_` + 12 lowercase hex)
#   - UUID:     standard 8-4-4-4-12 dashed form, case-insensitive
#   - UUID:     bare 32-char hex form, case-insensitive
# NOTE: intentionally case-sensitive — _generate_transaction_id always produces lowercase hex; uppercase tx_ ids are rejected by design.
_TX_ID_INTERNAL_RE = re.compile(r"^tx_[0-9a-f]{12}$")
_TX_ID_UUID_DASHED_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_TX_ID_UUID_BARE_RE = re.compile(r"^[0-9a-f]{32}$", re.IGNORECASE)

# Mapping from MCP argument names (snake_case) to completions API filter param names (camelCase).
# Used to build API query params for all three completions call sites.
_COMPLETIONS_FILTER_PARAM_MAP: Dict[str, str] = {
    # Date range (biggest performance win — avoids full-table scans)
    "start_date": "startDate",
    "end_date": "endDate",
    # Identity / tracing
    "transaction_id": "transactionId",
    "trace_id": "traceId",
    "trace_type": "traceType",
    "trace_name": "traceName",
    "agent": "agent",
    # Cost / performance ranges
    "total_cost_min": "totalCostMin",
    "total_cost_max": "totalCostMax",
    "request_duration_min": "requestDurationMin",
    "request_duration_max": "requestDurationMax",
    # Entity filters
    "organization_name": "organizationName",
    "subscriber_id": "subscriberId",
    "subscriber_email": "subscriberEmail",
    "subscription_id": "subscriptionId",
    "product_id": "productId",
    "credential_name": "credentialName",
    # Model / provider
    "provider": "provider",
    "model": "model",
    "model_source": "modelSource",
    # Token count ranges
    "input_token_count_min": "inputTokenCountMin",
    "input_token_count_max": "inputTokenCountMax",
    "output_token_count_min": "outputTokenCountMin",
    "output_token_count_max": "outputTokenCountMax",
    "reasoning_token_count_min": "reasoningTokenCountMin",
    "reasoning_token_count_max": "reasoningTokenCountMax",
    "cached_token_count_min": "cachedTokenCountMin",
    "cached_token_count_max": "cachedTokenCountMax",
    "total_token_count_min": "totalTokenCountMin",
    "total_token_count_max": "totalTokenCountMax",
    # Token cost ranges
    "input_token_cost_min": "inputTokenCostMin",
    "input_token_cost_max": "inputTokenCostMax",
    "output_token_cost_min": "outputTokenCostMin",
    "output_token_cost_max": "outputTokenCostMax",
    # Streaming performance
    "time_to_first_token_min": "timeToFirstTokenMin",
    "time_to_first_token_max": "timeToFirstTokenMax",
    "mediation_latency_min": "mediationLatencyMin",
    "mediation_latency_max": "mediationLatencyMax",
    # Quality / config
    "temperature_min": "temperatureMin",
    "temperature_max": "temperatureMax",
    "response_quality_score_min": "responseQualityScoreMin",
    "response_quality_score_max": "responseQualityScoreMax",
    "stop_reason": "stopReason",
    "task_type": "taskType",
    "system_fingerprint": "systemFingerprint",
    # Operational
    "operation_type": "operationType",
    "environment": "environment",
    "error_reason": "errorReason",
}


def _extract_completions_filters(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Build completions API filter params from MCP arguments, omitting absent/None/empty values."""
    return {
        api_key: arguments[arg_key]
        for arg_key, api_key in _COMPLETIONS_FILTER_PARAM_MAP.items()
        if arguments.get(arg_key) is not None and arguments.get(arg_key) != ""
    }


class MeteringTransactionManager:
    """Internal manager for AI transaction metering operations."""

    def __init__(self):
        """Initialize metering transaction manager."""
        self.transaction_store: Dict[str, Dict[str, Any]] = {}

        # Performance optimization: Cache for validation results
        self._validation_cache: Dict[str, bool] = {}
        self._cache_max_size = 1000

        # Request-scoped cache for data access optimization
        self._request_cache: Dict[str, Any] = {}

        # Performance tracking
        self._operation_times: Dict[str, List[float]] = {
            "submit": [],
            "verify": [],
            "status": [],
            "validate": [],
        }

    def _generate_transaction_id(self) -> str:
        """Generate a unique transaction ID."""
        return f"tx_{uuid.uuid4().hex[:12]}"

    def _validate_transaction_id_format(self, transaction_id: Any) -> None:
        """Reject transaction_ids the backend will silently drop.

        Auto-generated ids always satisfy this — only ids the caller supplied
        are checked. The error envelope carries field/value/examples so the
        caller can fix their input without inspecting a server-side traceback.
        """
        if not isinstance(transaction_id, str) or not transaction_id:
            raise ToolError(
                message="transaction_id must be a non-empty string (UUID or 'tx_' + 12 hex chars)",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field="transaction_id",
                value=transaction_id,
                suggestions=[
                    "Pass a UUID (e.g. '550e8400-e29b-41d4-a716-446655440000')",
                    "Or omit transaction_id entirely so submit_ai_transaction auto-generates one",
                ],
            )
        if (
            _TX_ID_INTERNAL_RE.match(transaction_id)
            or _TX_ID_UUID_DASHED_RE.match(transaction_id)
            or _TX_ID_UUID_BARE_RE.match(transaction_id)
        ):
            return
        raise ToolError(
            message=(
                f"transaction_id '{transaction_id}' is not a recognized format; "
                "the backend silently drops unrecognized ids, so the row would "
                "not be persisted."
            ),
            error_code=ErrorCodes.VALIDATION_ERROR,
            field="transaction_id",
            value=transaction_id,
            suggestions=[
                "Pass a UUID (8-4-4-4-12 dashed or 32-char bare hex)",
                "Or omit transaction_id and let submit_ai_transaction auto-generate one",
            ],
            examples={
                "valid_uuid_dashed": "550e8400-e29b-41d4-a716-446655440000",
                "valid_uuid_bare": "550e8400e29b41d4a716446655440000",
                "valid_internal": "tx_a1b2c3d4e5f6",
            },
        )

    def _transaction_ids_match(self, stored_id: Optional[str], search_id: str) -> bool:
        """Universal transaction ID matching that supports any format.

        This method enables universal transaction lookup regardless of transaction creation method:
        - Internal format: tx_abc123def456
        - OpenAI format: chatcmpl-BqjY5Wj0dcnSRHm1BTr1OCBZj3o8u
        - Anthropic format: claude-3-5-sonnet-20241022-abc123
        - Any other external format from middleware or bulk import

        Args:
            stored_id: Transaction ID as stored in the API
            search_id: Transaction ID being searched for

        Returns:
            True if the IDs match, False otherwise
        """
        if not stored_id or not search_id:
            return False

        # Exact match (most common case)
        if stored_id == search_id:
            return True

        # Case-insensitive match for robustness
        if stored_id.lower() == search_id.lower():
            return True

        # Additional format-specific matching could be added here if needed
        # For now, exact matching (case-sensitive and case-insensitive) covers
        # the universal transaction ID format support requirement

        return False

    def clear_request_cache(self) -> None:
        """Clear request-scoped cache for new request."""
        self._request_cache.clear()

    def get_request_cached(self, key: str) -> Any:
        """Get value from request-scoped cache."""
        return self._request_cache.get(key)

    def set_request_cached(self, key: str, value: Any) -> None:
        """Set value in request-scoped cache."""
        self._request_cache[key] = value

    def _iso_utc(self, dt: Optional[datetime] = None) -> str:
        """Generate ISO UTC timestamp."""
        dt = dt or datetime.now(timezone.utc)
        return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def _validate_timestamp_format(self, timestamp_str: str, field_name: str) -> None:
        """Validate timestamp format (ISO UTC with milliseconds) and raise structured error if invalid.

        Args:
            timestamp_str: Timestamp string to validate
            field_name: Name of the field for error reporting

        Raises:
            create_structured_validation_error: If timestamp format is invalid
        """
        if not isinstance(timestamp_str, str):
            raise create_structured_validation_error(
                message=(
                    f"🕒 Invalid {field_name}: Expected string, "
                    f"got {type(timestamp_str).__name__}"
                ),
                field=field_name,
                value=timestamp_str,
                suggestions=[
                    "Provide timestamp as a string in ISO UTC format",
                    "Format must be: YYYY-MM-DDTHH:MM:SS.sssZ",
                    "Example: '2025-03-02T15:30:45.123Z'",
                    "Or omit the field to use auto-population",
                ],
                examples={
                    "valid_format": "2025-03-02T15:30:45.123Z",
                    "auto_population": "Don't provide the field to auto-generate current time",
                    "iso_utc_examples": [
                        "2025-03-02T15:30:45.123Z",
                        "2025-12-25T09:15:30.456Z",
                        "2025-01-01T00:00:00.000Z",
                    ],
                },
            )

        # Check for basic ISO format with Z suffix
        if not timestamp_str.endswith("Z"):
            raise create_structured_validation_error(
                message=f"🕒 Invalid {field_name}: Must end with 'Z' for UTC timezone",
                field=field_name,
                value=timestamp_str,
                suggestions=[
                    "Add 'Z' suffix to indicate UTC timezone",
                    "Format must be: YYYY-MM-DDTHH:MM:SS.sssZ",
                    "Example: '2025-03-02T15:30:45.123Z'",
                    "Or omit the field to use auto-population",
                ],
                examples={
                    "correct_format": (
                        timestamp_str + "Z"
                        if not timestamp_str.endswith("Z")
                        else "2025-03-02T15:30:45.123Z"
                    ),
                    "invalid_formats": [
                        "2025-03-02T15:30:45.123",  # Missing Z
                        "2025-03-02T15:30:45.123+00:00",  # Wrong timezone format
                        "2025-03-02 15:30:45",  # Wrong format
                    ],
                },
            )

        try:
            # Try to parse the timestamp
            # Remove Z and add +00:00 for parsing
            parse_str = timestamp_str.replace("Z", "+00:00")
            datetime.fromisoformat(parse_str)
        except ValueError as e:
            raise create_structured_validation_error(
                message=f"🕒 Invalid {field_name} format: {str(e)}",
                field=field_name,
                value=timestamp_str,
                suggestions=[
                    "Use ISO UTC format with milliseconds: YYYY-MM-DDTHH:MM:SS.sssZ",
                    "Ensure date and time components are valid",
                    "Check for typos in the timestamp string",
                    "Or omit the field to use auto-population",
                ],
                examples={
                    "valid_format": "2025-03-02T15:30:45.123Z",
                    "format_breakdown": {
                        "year": "2025",
                        "month": "03 (01-12)",
                        "day": "02 (01-31)",
                        "hour": "15 (00-23)",
                        "minute": "30 (00-59)",
                        "second": "45 (00-59)",
                        "milliseconds": "123 (000-999)",
                        "timezone": "Z (UTC)",
                    },
                },
            )

    def _process_timestamp_field(
        self, arguments: Dict[str, Any], field_name: str, now_time: str
    ) -> str:
        """Process a timestamp field with validation and auto-population.

        Args:
            arguments: Arguments dictionary
            field_name: Name of the timestamp field
            now_time: Current time to use as fallback

        Returns:
            Validated timestamp string or auto-populated current time

        Raises:
            create_structured_validation_error: If provided timestamp format is invalid
        """
        provided_timestamp = arguments.get(field_name)

        if provided_timestamp is not None:
            # Validate provided timestamp format - this will raise structured error if invalid
            self._validate_timestamp_format(provided_timestamp, field_name)
            logger.info(f"Using provided {field_name}: {provided_timestamp}")
            return provided_timestamp
        else:
            # Auto-populate with current time
            logger.debug(f"Auto-populating {field_name} with current time")
            return now_time

    def _track_operation_time(self, operation: str, execution_time_ms: float) -> None:
        """Track operation execution time for performance monitoring."""
        # Map actions to operation categories
        operation_map = {
            "submit_ai_transaction": "submit",
            "lookup_transactions": "lookup",
            "get_transaction_status": "status",
            "validate": "validate",
        }

        op_category = operation_map.get(operation, "other")

        if op_category in self._operation_times:
            self._operation_times[op_category].append(execution_time_ms)

            # Keep only recent measurements for memory efficiency
            if len(self._operation_times[op_category]) > 100:
                self._operation_times[op_category] = self._operation_times[op_category][-50:]

    def _get_cache_key(self, data: Dict[str, Any]) -> str:
        """Generate cache key for validation results."""
        # Create a deterministic key from the data
        key_parts = []
        for field in ["model", "provider", "input_tokens", "output_tokens", "duration_ms"]:
            if field in data:
                key_parts.append(f"{field}:{data[field]}")
        return "|".join(key_parts)

    def _cache_validation_result(self, data: Dict[str, Any], result: bool) -> None:
        """Cache validation result for performance."""
        if len(self._validation_cache) >= self._cache_max_size:
            # Remove oldest entries (simple FIFO)
            keys_to_remove = list(self._validation_cache.keys())[:100]
            for key in keys_to_remove:
                del self._validation_cache[key]

        cache_key = self._get_cache_key(data)
        self._validation_cache[cache_key] = result

    def _get_cached_validation(self, data: Dict[str, Any]) -> Optional[bool]:
        """Get cached validation result if available."""
        cache_key = self._get_cache_key(data)
        return self._validation_cache.get(cache_key)

    def _validate_transaction_inputs(self, arguments: Dict[str, Any]) -> bool:
        """Validate and sanitize transaction inputs for security."""
        # Performance optimization: Check cache first
        cached_result = self._get_cached_validation(arguments)
        if cached_result is not None:
            return cached_result

        try:
            # Validate required numeric fields with enhanced type conversion
            for field in ["input_tokens", "output_tokens", "duration_ms"]:
                if field in arguments:
                    value = arguments[field]

                    # Try to convert to integer if it's a string
                    if isinstance(value, str):
                        try:
                            value = int(value)
                            # Update the arguments with the converted value
                            arguments[field] = value
                        except ValueError:
                            logger.warning(f"Cannot convert {field} to integer: {value}")
                            return False
                    elif not isinstance(value, int):
                        logger.warning(f"Invalid type for {field}: {type(value).__name__}")
                        return False

                    # Check for negative values
                    if value < 0:
                        logger.warning(f"Negative value for {field}: {value}")
                        return False

                    # Security: Prevent extremely large values that could cause issues
                    if value > 10_000_000:  # 10M tokens/ms seems reasonable upper bound
                        logger.warning(f"Suspiciously large {field}: {value}")
                        return False

            # Validate string fields
            for field in ["model", "provider"]:
                if field in arguments:
                    value = arguments[field]
                    if not isinstance(value, str) or not value.strip():
                        logger.warning(f"Invalid {field}: {value}")
                        return False
                    # Security: Prevent injection attempts
                    if len(value) > 200 or any(char in value for char in ["<", ">", '"', "'", "&"]):
                        logger.warning(f"Potentially malicious {field}: {value}")
                        return False

            # BACK-1139: mirror the provider enum check performed in the async
            # pipeline's _validate_string_fields (see lines ~802-811). The two
            # validation paths exist in parallel today (async pipeline for the
            # real submit path, sync method for the fast/test path), and must
            # stay in lock-step — lifting the _VALID_PROVIDERS tuple to module
            # scope is the cheap part; mirroring the check here is the rest.
            provider_value = arguments.get("provider")
            if isinstance(provider_value, str) and provider_value.strip():
                if provider_value.strip().upper() not in _VALID_PROVIDERS:
                    logger.warning(
                        f"Invalid provider '{provider_value}'. Must be one of: "
                        f"{', '.join(_VALID_PROVIDERS)}"
                    )
                    return False

            # Validate optional fields
            optional_string_fields = [
                "organization_id",
                "task_type",
                "agent",
                "stop_reason",
                "trace_id",
            ]
            for field in optional_string_fields:
                if field in arguments and arguments[field] is not None:
                    value = arguments[field]
                    if not isinstance(value, str):
                        logger.warning(f"Invalid type for {field}: {type(value)}")
                        return False
                    # Security: Prevent injection and limit length
                    if len(value) > 500 or any(char in value for char in ["<", ">", '"', "'", "&"]):
                        logger.warning(f"Potentially malicious {field}: {value}")
                        return False

            # Validate subscriber object if provided
            if "subscriber" in arguments and arguments["subscriber"] is not None:
                subscriber = arguments["subscriber"]
                if not isinstance(subscriber, dict):
                    logger.warning(f"Invalid subscriber type: {type(subscriber)}")
                    return False

                # Validate subscriber.id
                if "id" in subscriber and subscriber["id"] is not None:
                    if not isinstance(subscriber["id"], str) or not subscriber["id"].strip():
                        logger.warning(f"Invalid subscriber.id: {subscriber['id']}")
                        return False
                    if len(subscriber["id"]) > 500:
                        logger.warning(f"Subscriber.id too long: {len(subscriber['id'])}")
                        return False

                # Validate subscriber.email
                if "email" in subscriber and subscriber["email"] is not None:
                    if not isinstance(subscriber["email"], str) or not subscriber["email"].strip():
                        logger.warning(f"Invalid subscriber.email: {subscriber['email']}")
                        return False
                    if len(subscriber["email"]) > 500:
                        logger.warning(f"Subscriber.email too long: {len(subscriber['email'])}")
                        return False

                # Validate subscriber.credential object if provided
                if "credential" in subscriber and subscriber["credential"] is not None:
                    credential = subscriber["credential"]
                    if not isinstance(credential, dict):
                        logger.warning(f"Invalid subscriber.credential type: {type(credential)}")
                        return False

                    # Validate credential.name
                    if "name" in credential and credential["name"] is not None:
                        if (
                            not isinstance(credential["name"], str)
                            or not credential["name"].strip()
                        ):
                            logger.warning(
                                f"Invalid subscriber.credential.name: {credential['name']}"
                            )
                            return False
                        if len(credential["name"]) > 500:
                            logger.warning(
                                f"Subscriber.credential.name too long: {len(credential['name'])}"
                            )
                            return False

                    # Validate credential.value
                    if "value" in credential and credential["value"] is not None:
                        if not isinstance(credential["value"], str):
                            logger.warning(
                                f"Invalid subscriber.credential.value: {credential['value']}"
                            )
                            return False
                        if len(credential["value"]) > 500:
                            logger.warning(
                                f"Subscriber.credential.value too long: {len(credential['value'])}"
                            )
                            return False

            # Validate boolean fields
            if "is_streamed" in arguments and arguments["is_streamed"] is not None:
                if not isinstance(arguments["is_streamed"], bool):
                    logger.warning(f"Invalid is_streamed: {arguments['is_streamed']}")
                    return False

            # Cache the successful validation result
            self._cache_validation_result(arguments, True)
            return True

        except Exception as e:
            logger.error(f"Error validating transaction inputs: {e}")
            # Cache the failed validation result
            self._cache_validation_result(arguments, False)
            return False

    def _check_for_old_subscriber_format(self, arguments: Dict[str, Any]) -> Optional[str]:
        """Check for old subscriber format usage and provide migration guidance."""
        old_fields = []
        migration_guidance = []

        # Check for old subscriber fields
        if "subscriber_email" in arguments:
            old_fields.append("subscriber_email")
            migration_guidance.append(
                f"subscriber_email: '{arguments['subscriber_email']}' → "
                f"subscriber.email: '{arguments['subscriber_email']}'"
            )

        if "subscriber_id" in arguments:
            old_fields.append("subscriber_id")
            migration_guidance.append(
                f"subscriber_id: '{arguments['subscriber_id']}' → "
                f"subscriber.id: '{arguments['subscriber_id']}'"
            )

        if "subscriber_credential_name" in arguments:
            old_fields.append("subscriber_credential_name")
            migration_guidance.append(
                f"subscriber_credential_name: '{arguments['subscriber_credential_name']}' → "
                f"subscriber.credential.name: '{arguments['subscriber_credential_name']}'"
            )

        if "subscriber_credential" in arguments:
            old_fields.append("subscriber_credential")
            migration_guidance.append(
                f"subscriber_credential: '{arguments['subscriber_credential']}' → "
                f"subscriber.credential.value: '{arguments['subscriber_credential']}'"
            )

        if old_fields:
            # Build new subscriber object example
            new_subscriber = {}
            if "subscriber_id" in arguments:
                new_subscriber["id"] = arguments["subscriber_id"]
            if "subscriber_email" in arguments:
                new_subscriber["email"] = arguments["subscriber_email"]
            if "subscriber_credential_name" in arguments or "subscriber_credential" in arguments:
                credential = {}
                if "subscriber_credential_name" in arguments:
                    credential["name"] = arguments["subscriber_credential_name"]
                if "subscriber_credential" in arguments:
                    credential["value"] = arguments["subscriber_credential"]
                if credential:
                    new_subscriber["credential"] = credential

            error_msg = """⚠️ CRITICAL: **SUBSCRIBER FORMAT CHANGED**

The subscriber data structure has been updated. The old individual fields are no longer supported.

**❌ Old format detected**: {', '.join(old_fields)}

**✅ New format required**: Use a single 'subscriber' object

**Migration Guide**:
{chr(10).join(f"• {guide}" for guide in migration_guidance)}

**✅ Correct format**:
```json
"subscriber": {json.dumps(new_subscriber, indent=2)}
```

**Example with your data**:
```json
{{
  "action": "submit_ai_transaction",
  "model": "your-model",
  "provider": "your-provider",
  "input_tokens": 1500,
  "output_tokens": 800,
  "duration_ms": 2500,
  "subscriber": {json.dumps(new_subscriber, indent=2)}
}}
```

**💡 Quick Fix**: Replace the old fields with the subscriber object structure shown above."""

            return error_msg

        return None

    def _validate_field_combinations(self, arguments: Dict[str, Any]) -> List[str]:
        """Progressive validation for field combinations with specific guidance."""
        warnings = []

        # Check for potentially problematic combinations
        has_quality_score = (
            "response_quality_score" in arguments
            and arguments["response_quality_score"] is not None
        )
        has_streaming = "is_streamed" in arguments and arguments["is_streamed"] is not None
        has_timestamps = any(
            field in arguments and arguments[field] is not None
            for field in ["request_time", "response_time", "completion_start_time"]
        )
        has_subscriber = "subscriber" in arguments and arguments["subscriber"] is not None
        has_attribution = any(
            field in arguments and arguments[field] is not None
            for field in ["organization_id", "task_type", "agent"]
        )

        # Provide progressive guidance based on field combinations
        if has_quality_score and not has_streaming:
            warnings.append(
                "💡 Consider adding 'is_streamed' field when tracking response quality "
                "for complete performance metrics"
            )

        if has_streaming and arguments.get("is_streamed") and not has_timestamps:
            warnings.append(
                "💡 For streamed responses, consider adding 'completion_start_time' "
                "for accurate streaming metrics"
            )

        if has_subscriber and not has_attribution:
            warnings.append(
                "💡 When using subscriber attribution, consider adding 'organization_id' "
                "and 'task_type' for complete billing context"
            )

        if has_attribution and not has_subscriber:
            warnings.append(
                "💡 For enterprise attribution, consider adding 'subscriber' object "
                "for user-level tracking"
            )

        if has_timestamps and not all(
            field in arguments for field in ["request_time", "response_time"]
        ):
            warnings.append(
                "💡 When providing timestamps, include both 'request_time' and 'response_time' "
                "for complete timing data"
            )

        # Check for advanced field combinations
        has_task_tracking = any(
            field in arguments and arguments[field] is not None for field in ["trace_id"]
        )
        has_product_billing = any(
            field in arguments and arguments[field] is not None
            for field in ["product_id", "subscription_id"]
        )

        if has_task_tracking and not has_attribution:
            warnings.append(
                "💡 Task tracking fields work best with organization attribution "
                "(organization_id, task_type)"
            )

        if has_product_billing and not has_subscriber:
            warnings.append(
                "💡 Product billing fields should include subscriber information "
                "for accurate revenue attribution"
            )

        return warnings

    async def _validate_fast_checks(self, arguments: Dict[str, Any]) -> Optional[str]:
        """Fast validation checks that can fail early to save processing time.

        Args:
            arguments: Transaction arguments to validate

        Returns:
            Error message if validation fails, None if passes
        """

        # Check 1: Old subscriber format (most common error)
        old_format_error = self._check_for_old_subscriber_format(arguments)
        if old_format_error:
            # Performance metrics recording removed - handled by external monitoring
            return old_format_error

        # Check 2: Invalid task_id field (API compatibility)
        if "task_id" in arguments:
            return (
                "⚠️ CRITICAL: **INVALID FIELD: task_id**\n\n"
                "The 'task_id' field is not supported by the Revenium API "
                "and will cause 400 errors.\n\n"
                "**Remove this field**: task_id\n\n"
                "**Use trace_id instead**: For session/conversation tracking, use 'trace_id'\n\n"
                "**Example**:\n"
                "```json\n"
                "{\n"
                '  "trace_id": "conv_session_001",  // Use this\n'
                '  // "task_id": "task_001"        // Remove this\n'
                "}\n"
                "```\n\n"
                "**Quick Fix**: Replace 'task_id' with 'trace_id' for tracking purposes."
            )

        # Check 3: Required fields presence (fast check)
        required_fields = ["model", "provider", "input_tokens", "output_tokens", "duration_ms"]
        missing_fields = []
        for field in required_fields:
            if field not in arguments or arguments[field] is None:
                missing_fields.append(field)

        if missing_fields:
            return (
                "⚠️ CRITICAL: **MISSING REQUIRED FIELDS**\n\n"
                f"The following required fields are missing: {', '.join(missing_fields)}\n\n"
                f"**Required fields**: {', '.join(required_fields)}\n\n"
                "**Quick Fix**: Add all required fields to your request."
            )

        # Check 4: Basic type validation for critical fields (fast check)
        if not isinstance(arguments.get("model"), str):
            return "⚠️ CRITICAL: **INVALID TYPE: model**\n\nThe 'model' field must be a string."

        if not isinstance(arguments.get("provider"), str):
            return "🚨 **INVALID TYPE: provider** 🚨\n\nThe 'provider' field must be a string."

        # All fast checks passed
        # Performance metrics recording removed - handled by external monitoring
        return None

    async def _validate_required_fields(self, arguments: Dict[str, Any]) -> List[str]:
        """Async validation for required fields."""
        errors = []
        required_fields = ["model", "provider", "input_tokens", "output_tokens", "duration_ms"]

        for field in required_fields:
            if field not in arguments or arguments[field] is None:
                errors.append(f"• {field}: Required field is missing")
            elif isinstance(arguments[field], str) and arguments[field].strip() == "":
                errors.append(f"• {field}: Cannot be empty string")

        return errors

    async def _validate_numeric_fields(self, arguments: Dict[str, Any]) -> List[str]:
        """Async validation for numeric fields."""
        errors = []

        # Validate required numeric fields with enhanced type conversion
        for field in ["input_tokens", "output_tokens", "duration_ms"]:
            if field in arguments:
                value = arguments[field]
                original_value = value

                # Try to convert to integer if it's a string
                if isinstance(value, str):
                    try:
                        value = int(value)
                        arguments[field] = value
                    except ValueError:
                        errors.append(f"• {field}: Cannot convert '{original_value}' to integer")
                        continue
                elif not isinstance(value, int):
                    errors.append(f"• {field}: Expected integer, got {type(value).__name__}")
                    continue

                # Check for negative values
                if value < 0:
                    errors.append(f"• {field}: Must be positive, got {value}")
                    continue

                # Security: Prevent extremely large values
                if value > 10_000_000:
                    errors.append(f"• {field}: Value too large ({value}), maximum is 10,000,000")
                    continue

        return errors

    async def _validate_string_fields(self, arguments: Dict[str, Any]) -> List[str]:
        """Async validation for string fields."""
        errors = []

        # Validate required string fields
        for field in ["model", "provider"]:
            if field in arguments:
                value = arguments[field]
                if not isinstance(value, str):
                    errors.append(f"• {field}: Expected string, got {type(value).__name__}")
                    continue
                if not value.strip():
                    errors.append(f"• {field}: Cannot be empty")
                    continue
                # Security: Prevent injection attempts
                if len(value) > 200:
                    errors.append(f"• {field}: Too long (max 200 characters)")
                    continue
                if any(char in value for char in ["<", ">", '"', "'", "&"]):
                    errors.append(f"• {field}: Contains invalid characters")
                    continue

        # BACK-1139: enforce the documented provider enum on the write path.
        # Without this, arbitrary strings (including typos) were persisted
        # silently and corrupted downstream analytics aggregation.
        provider_value = arguments.get("provider")
        if isinstance(provider_value, str) and provider_value.strip():
            if provider_value.strip().upper() not in _VALID_PROVIDERS:
                errors.append(
                    f"• provider: Invalid provider '{provider_value}'. Must be one of: "
                    f"{', '.join(_VALID_PROVIDERS)}"
                )

        return errors

    async def _validate_optional_fields(self, arguments: Dict[str, Any]) -> List[str]:
        """Async validation for optional fields."""
        errors = []

        # Get usage_metadata early for consistent access throughout validation
        usage_metadata = arguments.get("usage_metadata") if isinstance(arguments.get("usage_metadata"), dict) else None

        # Validate optional string fields (non-trace fields - top-level only)
        optional_string_fields = [
            "organization_id",
            "task_type",
            "agent",
            "stop_reason",
            "trace_id",
            "product_id",
            "subscription_id",
            "error_reason",
        ]
        for field in optional_string_fields:
            if field in arguments and arguments[field] is not None:
                value = arguments[field]
                if not isinstance(value, str):
                    errors.append(f"• {field}: Expected string, got {type(value).__name__}")
                    continue
                if not value.strip():
                    errors.append(f"• {field}: Cannot be empty")
                    continue
                # Security: Prevent injection and limit length
                if len(value) > 500:
                    errors.append(f"• {field}: Too long (max 500 characters), got {len(value)}")
                    continue
                if any(char in value for char in ["<", ">", '"', "'", "&"]):
                    errors.append(f"• {field}: Contains invalid characters (<, >, \", ', &)")
                    continue

        # Validate trace string fields from BOTH top-level AND usage_metadata
        # These fields support both snake_case and camelCase aliases
        trace_string_fields = {
            "environment": ["environment"],
            "region": ["region"],
            "credential_alias": ["credential_alias", "credentialAlias"],
            "trace_name": ["trace_name", "traceName"],
            "parent_transaction_id": ["parent_transaction_id", "parentTransactionId", "parentSpanId"],
            "transaction_name": ["transaction_name", "transactionName"],
            "operation_subtype": ["operation_subtype", "operationSubtype"],
        }

        for canonical_name, aliases in trace_string_fields.items():
            value = None
            source = None

            # Check top-level arguments first (all aliases)
            for alias in aliases:
                if alias in arguments and arguments[alias] is not None:
                    value = arguments[alias]
                    source = alias
                    break

            # Check usage_metadata if not found in top-level
            if value is None and usage_metadata:
                for alias in aliases:
                    if alias in usage_metadata and usage_metadata[alias] is not None:
                        value = usage_metadata[alias]
                        source = f"usage_metadata.{alias}"
                        break

            # Validate the value if found
            if value is not None:
                if not isinstance(value, str):
                    errors.append(f"• {source}: Expected string, got {type(value).__name__}")
                elif not value.strip():
                    errors.append(f"• {source}: Cannot be empty")
                elif len(value) > 500:
                    errors.append(f"• {source}: Too long (max 500 characters), got {len(value)}")
                elif any(char in value for char in ["<", ">", '"', "'", "&"]):
                    errors.append(f"• {source}: Contains invalid characters (<, >, \", ', &)")

        # Validate operation_type from BOTH top-level AND usage_metadata
        operation_type_value = None
        operation_type_source = None

        # Check top-level arguments (snake_case and camelCase)
        for key in ["operation_type", "operationType"]:
            if key in arguments and arguments[key] is not None:
                operation_type_value = arguments[key]
                operation_type_source = key
                break

        # Check usage_metadata if not found in top-level
        if operation_type_value is None and usage_metadata:
            for key in ["operation_type", "operationType"]:
                if key in usage_metadata and usage_metadata[key] is not None:
                    operation_type_value = usage_metadata[key]
                    operation_type_source = f"usage_metadata.{key}"
                    break

        if operation_type_value is not None:
            if not isinstance(operation_type_value, str):
                errors.append(f"• {operation_type_source}: Expected string, got {type(operation_type_value).__name__}")
            elif not operation_type_value.strip():
                errors.append(f"• {operation_type_source}: Cannot be empty")
            # Note: operation_type values are not restricted to a fixed set anymore
            # The API accepts various operation types and validation is handled server-side

        # Validate trace_type with special constraints
        # Check all possible sources: top-level (snake_case and camelCase) and usage_metadata
        trace_type_value = None
        trace_type_source = None

        # Check top-level arguments (snake_case and camelCase)
        for key in ["trace_type", "traceType"]:
            if key in arguments and arguments[key] is not None:
                trace_type_value = arguments[key]
                trace_type_source = key
                break

        # Check usage_metadata if not found in top-level
        if trace_type_value is None and usage_metadata:
            for key in ["trace_type", "traceType"]:
                if key in usage_metadata and usage_metadata[key] is not None:
                    trace_type_value = usage_metadata[key]
                    trace_type_source = f"usage_metadata.{key}"
                    break

        if trace_type_value is not None:
            if not isinstance(trace_type_value, str):
                errors.append(f"• {trace_type_source}: Expected string, got {type(trace_type_value).__name__}")
            elif len(trace_type_value) > 128:
                errors.append(f"• {trace_type_source}: Too long (max 128 characters), got {len(trace_type_value)}")
            elif not all(c.isalnum() or c in "-_" for c in trace_type_value):
                errors.append(f"• {trace_type_source}: Only alphanumeric, hyphens, and underscores allowed")

        # Validate retry_number as integer
        # Check all possible sources: top-level (snake_case and camelCase) and usage_metadata
        retry_number_value = None
        retry_number_source = None

        # Check top-level arguments (snake_case and camelCase)
        for key in ["retry_number", "retryNumber"]:
            if key in arguments and arguments[key] is not None:
                retry_number_value = arguments[key]
                retry_number_source = key
                break

        # Check usage_metadata if not found in top-level
        if retry_number_value is None and usage_metadata:
            for key in ["retry_number", "retryNumber"]:
                if key in usage_metadata and usage_metadata[key] is not None:
                    retry_number_value = usage_metadata[key]
                    retry_number_source = f"usage_metadata.{key}"
                    break

        if retry_number_value is not None:
            try:
                int_value = int(retry_number_value)
                if int_value < 0:
                    errors.append(f"• {retry_number_source}: Must be non-negative")
            except (ValueError, TypeError):
                errors.append(f"• {retry_number_source}: Expected integer, got {type(retry_number_value).__name__}")

        return errors

    async def _validate_boolean_fields(self, arguments: Dict[str, Any]) -> List[str]:
        """Async validation for boolean fields."""
        errors = []

        if "is_streamed" in arguments and arguments["is_streamed"] is not None:
            value = arguments["is_streamed"]
            if isinstance(value, str):
                # Try to convert string to boolean
                if value.lower() in ["true", "1", "yes"]:
                    arguments["is_streamed"] = True
                elif value.lower() in ["false", "0", "no"]:
                    arguments["is_streamed"] = False
                else:
                    errors.append(f"• is_streamed: Cannot convert '{value}' to boolean")
            elif not isinstance(value, bool):
                errors.append(f"• is_streamed: Expected boolean, got {type(value).__name__}")

        return errors

    async def _validate_float_fields(self, arguments: Dict[str, Any]) -> List[str]:
        """Async validation for float fields."""
        errors = []

        if (
            "response_quality_score" in arguments
            and arguments["response_quality_score"] is not None
        ):
            value = arguments["response_quality_score"]
            try:
                # Convert to float if it's a string
                if isinstance(value, str):
                    value = float(value)
                    arguments["response_quality_score"] = value
                elif not isinstance(value, (int, float)):
                    errors.append(
                        f"• response_quality_score: Expected number, got {type(value).__name__}"
                    )
                else:
                    # Validate range 0.0 to 1.0
                    if value < 0.0 or value > 1.0:
                        errors.append(
                            f"• response_quality_score: Must be between 0.0 and 1.0, got {value}"
                        )
            except (ValueError, TypeError):
                errors.append(f"• response_quality_score: Cannot convert '{value}' to number")

        return errors

    async def _validate_timestamp_fields(self, arguments: Dict[str, Any]) -> List[str]:
        """Async validation for timestamp fields."""
        errors = []

        timestamp_fields = ["request_time", "response_time", "completion_start_time"]
        for field in timestamp_fields:
            if field in arguments and arguments[field] is not None:
                value = arguments[field]
                if not isinstance(value, str):
                    errors.append(f"• {field}: Expected ISO UTC string, got {type(value).__name__}")
                    continue

                # Check for basic ISO format with Z suffix
                if not value.endswith("Z"):
                    errors.append(f"• {field}: Must end with 'Z' for UTC timezone, got '{value}'")
                    continue

                try:
                    # Try to parse the timestamp
                    parse_str = value.replace("Z", "+00:00")
                    datetime.fromisoformat(parse_str)
                except ValueError:
                    errors.append(
                        f"• {field}: Invalid ISO UTC format, "
                        f"expected 'YYYY-MM-DDTHH:MM:SS.sssZ', got '{value}'"
                    )
                    continue

        return errors

    async def _validate_special_fields(self, arguments: Dict[str, Any]) -> List[str]:
        """Async validation for special fields like time_to_first_token."""
        errors = []

        # Validate time_to_first_token
        if "time_to_first_token" in arguments and arguments["time_to_first_token"] is not None:
            value = arguments["time_to_first_token"]
            try:
                if isinstance(value, str):
                    value = int(value)
                    arguments["time_to_first_token"] = value
                elif not isinstance(value, int):
                    errors.append(
                        f"• time_to_first_token: Expected integer, got {type(value).__name__}"
                    )
                else:
                    if value < 0:
                        errors.append(f"• time_to_first_token: Must be positive, got {value}")
                    elif value > 60000:  # 60 seconds seems like a reasonable upper bound
                        errors.append(
                            f"• time_to_first_token: Too large ({value}ms), maximum is 60,000ms"
                        )
            except (ValueError, TypeError):
                errors.append(f"• time_to_first_token: Cannot convert '{value}' to integer")

        return errors

    async def _validate_field_combinations_async(self, arguments: Dict[str, Any]) -> List[str]:
        """Async validation for field combinations."""
        # For now, delegate to the synchronous version
        # In the future, this could include async UCM validation
        return self._validate_field_combinations(arguments)

    @cache_response("validation", ttl_seconds=600)  # Cache validation results for 10 minutes
    async def _validate_transaction_inputs_async(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Async version of transaction validation with smart ordering and concurrent processing."""
        try:
            # Phase 1: Fast validation checks (fail fast for common errors)
            fast_validation_errors = await self._validate_fast_checks(arguments)
            if fast_validation_errors:
                # Performance metrics recording removed - handled by external monitoring
                return {"valid": False, "message": fast_validation_errors}

            # Phase 2: Concurrent detailed validation (only if fast checks pass)
            validation_tasks = [
                self._validate_required_fields(arguments),
                self._validate_numeric_fields(arguments),
                self._validate_string_fields(arguments),
                self._validate_optional_fields(arguments),
                self._validate_boolean_fields(arguments),
                self._validate_float_fields(arguments),
                self._validate_timestamp_fields(arguments),
                self._validate_special_fields(arguments),
            ]

            # Execute all detailed validations concurrently
            validation_results = await asyncio.gather(*validation_tasks, return_exceptions=True)

            # Performance metrics recording removed - handled by external monitoring

            # Collect all errors from validation results
            errors = []
            for result in validation_results:
                if isinstance(result, Exception):
                    logger.error(f"Validation task failed: {result}")
                    errors.append(f"• Validation error: {str(result)}")
                elif isinstance(result, list):
                    errors.extend(result)

            # Progressive validation for field combinations (async)
            combination_warnings = await self._validate_field_combinations_async(arguments)

            if errors:
                # Create comprehensive error message with field-by-field guidance
                error_count = len(errors)
                error_summary = (
                    f"⚠️ CRITICAL: **{error_count} Validation Error"
                    f"{'s' if error_count > 1 else ''} Found**"
                )

                # Group errors by category for better organization
                field_errors = []
                format_errors = []
                range_errors = []

                for error in errors:
                    if "Expected" in error or "got" in error:
                        format_errors.append(error)
                    elif "Must be" in error or "between" in error or "positive" in error:
                        range_errors.append(error)
                    else:
                        field_errors.append(error)

                detailed_message = f"{error_summary}\n\n"

                if format_errors:
                    detailed_message += "**Format Issues:**\n" + "\n".join(format_errors) + "\n\n"

                if range_errors:
                    detailed_message += (
                        "**📊 Value Range Issues:**\n" + "\n".join(range_errors) + "\n\n"
                    )

                if field_errors:
                    detailed_message += "**⚠️ Field Issues:**\n" + "\n".join(field_errors) + "\n\n"

                # Add helpful guidance based on error types
                detailed_message += "**💡 Quick Fixes:**\n"
                if any("response_quality_score" in error for error in errors):
                    detailed_message += (
                        "• response_quality_score: Use values between 0.0 (poor) and 1.0 (excellent)\n"
                    )
                if any("timestamp" in error or "time" in error for error in errors):
                    detailed_message += (
                        "• Timestamps: Use ISO UTC format like '2025-06-16T15:30:45.123Z'\n"
                    )
                if any("boolean" in error for error in errors):
                    detailed_message += "• Booleans: Use true/false, 'true'/'false', or 1/0\n"
                if any("string" in error for error in errors):
                    detailed_message += "• Strings: Ensure non-empty text without special characters (<, >, \", ', &)\n"
                if any("integer" in error for error in errors):
                    detailed_message += "• Numbers: Use positive integers for tokens and duration\n"

                detailed_message += "\n**📚 Get Help:**\n"
                detailed_message += "• Use get_examples() to see working examples\n"
                detailed_message += "• Use get_capabilities() to see all field requirements\n"
                detailed_message += (
                    "• Use parse_natural_language(text='subscriber migration') for migration help\n"
                )
                detailed_message += (
                    "• Check field compatibility with validate() before submit_ai_transaction()"
                )

                return {"valid": False, "message": detailed_message}

            # Return success with progressive guidance
            # Performance metrics recording removed - handled by external monitoring

            success_message = "All inputs are valid"
            if combination_warnings:
                success_message += "\n\n**🔍 Progressive Enhancement Suggestions:**\n" + "\n".join(
                    combination_warnings
                )
                success_message += "\n\n**Note:** These are optimization suggestions, not errors. Your transaction will work as-is."

            return {"valid": True, "message": success_message}

        except Exception as e:
            # Performance metrics recording removed - handled by external monitoring
            logger.error(f"Error in async validation: {e}")
            return {"valid": False, "message": f"Validation error: {str(e)}"}

    async def _validate_transaction_inputs_with_details(
        self, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate transaction input data with detailed error messages (async optimized)."""
        try:
            errors = []

            # Check for old subscriber format first
            old_format_error = self._check_for_old_subscriber_format(arguments)
            if old_format_error:
                return {"valid": False, "message": old_format_error}

            # Check for invalid task_id field (removed from API)
            if "task_id" in arguments:
                return {
                    "valid": False,
                    "message": "⚠️ CRITICAL: **INVALID FIELD: task_id**\n\n"
                    "The 'task_id' field is not supported by the Revenium API and will cause 400 errors.\n\n"
                    "**Remove this field**: task_id\n\n"
                    "**Use trace_id instead**: For session/conversation tracking, use 'trace_id'\n\n"
                    "**Example**:\n"
                    "```json\n"
                    "{\n"
                    '  "trace_id": "conv_session_001",  // Use this\n'
                    '  // "task_id": "task_001"        // Remove this\n'
                    "}\n"
                    "```\n\n"
                    "**Quick Fix**: Replace 'task_id' with 'trace_id' for tracking purposes.",
                }

            # Validate required numeric fields with enhanced type conversion
            for field in ["input_tokens", "output_tokens", "duration_ms"]:
                if field in arguments:
                    value = arguments[field]
                    original_value = value

                    # Try to convert to integer if it's a string
                    if isinstance(value, str):
                        try:
                            value = int(value)
                            # Update the arguments with the converted value
                            arguments[field] = value
                        except ValueError:
                            errors.append(
                                f"• {field}: Cannot convert '{original_value}' to integer"
                            )
                            continue
                    elif not isinstance(value, int):
                        errors.append(f"• {field}: Expected integer, got {type(value).__name__}")
                        continue

                    # Check for negative values
                    if value < 0:
                        errors.append(f"• {field}: Must be positive, got {value}")
                        continue

                    # Security: Prevent extremely large values that could cause issues
                    if value > 10_000_000:  # 10M tokens/ms seems reasonable upper bound
                        errors.append(
                            f"• {field}: Value too large ({value}), maximum is 10,000,000"
                        )
                        continue

            # Validate string fields
            for field in ["model", "provider"]:
                if field in arguments:
                    value = arguments[field]
                    if not isinstance(value, str):
                        errors.append(f"• {field}: Expected string, got {type(value).__name__}")
                        continue
                    if not value.strip():
                        errors.append(f"• {field}: Cannot be empty")
                        continue
                    # Security: Prevent injection attempts
                    if len(value) > 200:
                        errors.append(f"• {field}: Too long (max 200 characters)")
                        continue
                    if any(char in value for char in ["<", ">", '"', "'", "&"]):
                        errors.append(f"• {field}: Contains invalid characters")
                        continue

            # Validate operation_type field (critical for API compatibility)
            if "operation_type" in arguments and arguments["operation_type"] is not None:
                value = arguments["operation_type"]
                if not isinstance(value, str):
                    errors.append(f"• operation_type: Expected string, got {type(value).__name__}")
                elif not value.strip():
                    errors.append("• operation_type: Cannot be empty")
                elif value not in ["CHAT", "COMPLETION", "EMBEDDING", "FINE_TUNING", "MODERATION"]:
                    errors.append(
                        f"• operation_type: Invalid value '{value}', must be one of: CHAT, COMPLETION, EMBEDDING, FINE_TUNING, MODERATION"
                    )

            # Validate boolean fields
            if "is_streamed" in arguments and arguments["is_streamed"] is not None:
                value = arguments["is_streamed"]
                if isinstance(value, str):
                    # Try to convert string to boolean
                    if value.lower() in ["true", "1", "yes"]:
                        arguments["is_streamed"] = True
                    elif value.lower() in ["false", "0", "no"]:
                        arguments["is_streamed"] = False
                    else:
                        errors.append(f"• is_streamed: Cannot convert '{value}' to boolean")
                elif not isinstance(value, bool):
                    errors.append(f"• is_streamed: Expected boolean, got {type(value).__name__}")

            # Validate optional string fields with proper length and character validation
            optional_string_fields = [
                "organization_id",
                "task_type",
                "agent",
                "stop_reason",
                "trace_id",
                "product_id",
                "subscription_id",
                "error_reason",
            ]
            for field in optional_string_fields:
                if field in arguments and arguments[field] is not None:
                    value = arguments[field]
                    if not isinstance(value, str):
                        errors.append(f"• {field}: Expected string, got {type(value).__name__}")
                        continue
                    if not value.strip():
                        errors.append(f"• {field}: Cannot be empty")
                        continue
                    # Security: Prevent injection and limit length
                    if len(value) > 500:
                        errors.append(f"• {field}: Too long (max 500 characters), got {len(value)}")
                        continue
                    if any(char in value for char in ["<", ">", '"', "'", "&"]):
                        errors.append(f"• {field}: Contains invalid characters (<, >, \", ', &)")
                        continue

            # Validate response_quality_score (critical missing validation!)
            if (
                "response_quality_score" in arguments
                and arguments["response_quality_score"] is not None
            ):
                value = arguments["response_quality_score"]
                try:
                    # Convert to float if it's a string
                    if isinstance(value, str):
                        value = float(value)
                        arguments["response_quality_score"] = value
                    elif not isinstance(value, (int, float)):
                        errors.append(
                            f"• response_quality_score: Expected number, got {type(value).__name__}"
                        )
                    else:
                        # Validate range 0.0 to 1.0
                        if value < 0.0 or value > 1.0:
                            errors.append(
                                f"• response_quality_score: Must be between 0.0 and 1.0, got {value}"
                            )

                except (ValueError, TypeError):
                    errors.append(f"• response_quality_score: Cannot convert '{value}' to number")

            # Validate timestamp fields (critical missing validation!)
            timestamp_fields = ["request_time", "response_time", "completion_start_time"]
            for field in timestamp_fields:
                if field in arguments and arguments[field] is not None:
                    value = arguments[field]
                    if not isinstance(value, str):
                        errors.append(
                            f"• {field}: Expected ISO UTC string, got {type(value).__name__}"
                        )
                        continue

                    # Check for basic ISO format with Z suffix
                    if not value.endswith("Z"):
                        errors.append(
                            f"• {field}: Must end with 'Z' for UTC timezone, got '{value}'"
                        )
                        continue

                    try:
                        # Try to parse the timestamp
                        parse_str = value.replace("Z", "+00:00")
                        datetime.fromisoformat(parse_str)
                    except ValueError:
                        errors.append(
                            f"• {field}: Invalid ISO UTC format, expected 'YYYY-MM-DDTHH:MM:SS.sssZ', got '{value}'"
                        )
                        continue

            # Validate time_to_first_token
            if "time_to_first_token" in arguments and arguments["time_to_first_token"] is not None:
                value = arguments["time_to_first_token"]
                try:
                    if isinstance(value, str):
                        value = int(value)
                        arguments["time_to_first_token"] = value
                    elif not isinstance(value, int):
                        errors.append(
                            f"• time_to_first_token: Expected integer, got {type(value).__name__}"
                        )
                    else:
                        if value < 0:
                            errors.append(f"• time_to_first_token: Must be positive, got {value}")
                        elif value > 60000:  # 60 seconds seems like a reasonable upper bound
                            errors.append(
                                f"• time_to_first_token: Too large ({value}ms), maximum is 60,000ms"
                            )

                except (ValueError, TypeError):
                    errors.append(f"• time_to_first_token: Cannot convert '{value}' to integer")

            # Progressive validation for field combinations (async)
            combination_warnings = await self._validate_field_combinations_async(arguments)

            if errors:
                # Create comprehensive error message with field-by-field guidance
                error_count = len(errors)
                error_summary = (
                    f"🚨 **{error_count} Validation Error{'s' if error_count > 1 else ''} Found**"
                )

                # Group errors by category for better organization
                field_errors = []
                format_errors = []
                range_errors = []

                for error in errors:
                    if "Expected" in error or "got" in error:
                        format_errors.append(error)
                    elif "Must be" in error or "between" in error or "positive" in error:
                        range_errors.append(error)
                    else:
                        field_errors.append(error)

                detailed_message = f"{error_summary}\n\n"

                if format_errors:
                    detailed_message += (
                        "**🔧 Format Issues:**\n" + "\n".join(format_errors) + "\n\n"
                    )

                if range_errors:
                    detailed_message += (
                        "**📊 Value Range Issues:**\n" + "\n".join(range_errors) + "\n\n"
                    )

                if field_errors:
                    detailed_message += "**⚠️ Field Issues:**\n" + "\n".join(field_errors) + "\n\n"

                # Add helpful guidance based on error types
                detailed_message += "**💡 Quick Fixes:**\n"
                if any("response_quality_score" in error for error in errors):
                    detailed_message += "• response_quality_score: Use values between 0.0 (poor) and 1.0 (excellent)\n"
                if any("timestamp" in error or "time" in error for error in errors):
                    detailed_message += (
                        "• Timestamps: Use ISO UTC format like '2025-06-16T15:30:45.123Z'\n"
                    )
                if any("boolean" in error for error in errors):
                    detailed_message += "• Booleans: Use true/false, 'true'/'false', or 1/0\n"
                if any("string" in error for error in errors):
                    detailed_message += "• Strings: Ensure non-empty text without special characters (<, >, \", ', &)\n"
                if any("integer" in error for error in errors):
                    detailed_message += "• Numbers: Use positive integers for tokens and duration\n"

                detailed_message += "\n**📚 Get Help:**\n"
                detailed_message += "• Use get_examples() to see working examples\n"
                detailed_message += "• Use get_capabilities() to see all field requirements\n"
                detailed_message += (
                    "• Use parse_natural_language(text='subscriber migration') for migration help\n"
                )
                detailed_message += (
                    "• Check field compatibility with validate() before submit_ai_transaction()"
                )

                return {"valid": False, "message": detailed_message}

            # Return success with progressive guidance
            success_message = "All inputs are valid"
            if combination_warnings:
                success_message += "\n\n**🔍 Progressive Enhancement Suggestions:**\n" + "\n".join(
                    combination_warnings
                )
                success_message += "\n\n**Note:** These are optimization suggestions, not errors. Your transaction will work as-is."

            return {"valid": True, "message": success_message}

        except Exception as e:
            logger.error(f"Error in detailed validation: {e}")
            return {"valid": False, "message": f"Validation error: {str(e)}"}

    def _sanitize_for_logging(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize data for safe logging by removing sensitive information."""
        import copy

        sanitized = copy.deepcopy(data)

        # Remove or mask sensitive fields
        sensitive_fields = [
            "subscriberCredential",
            "credential_value",
            "api_key",
            "subscriberCredentialName",
            "credential_name",
        ]

        for field in sensitive_fields:
            if field in sanitized:
                if sanitized[field]:
                    # Mask the value but keep some info for debugging
                    sanitized[field] = (
                        f"***{str(sanitized[field])[-4:]}"
                        if len(str(sanitized[field])) > 4
                        else "***"
                    )

        # Handle nested subscriber credential object
        if "subscriber" in sanitized and isinstance(sanitized["subscriber"], dict):
            if "credential" in sanitized["subscriber"] and isinstance(
                sanitized["subscriber"]["credential"], dict
            ):
                if "value" in sanitized["subscriber"]["credential"]:
                    value = sanitized["subscriber"]["credential"]["value"]
                    if value:
                        sanitized["subscriber"]["credential"]["value"] = (
                            f"***{str(value)[-4:]}" if len(str(value)) > 4 else "***"
                        )

        return sanitized

    def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance statistics for monitoring."""
        stats = {}

        for operation, times in self._operation_times.items():
            if times:
                stats[operation] = {
                    "count": len(times),
                    "avg_ms": sum(times) / len(times),
                    "min_ms": min(times),
                    "max_ms": max(times),
                    "last_ms": times[-1] if times else 0,
                }
            else:
                stats[operation] = {"count": 0, "avg_ms": 0, "min_ms": 0, "max_ms": 0, "last_ms": 0}

        # Add cache statistics
        stats["validation_cache"] = {
            "size": len(self._validation_cache),
            "max_size": self._cache_max_size,
            "hit_rate": self._calculate_cache_hit_rate(),
        }

        return stats

    def _calculate_cache_hit_rate(self) -> float:
        """Calculate cache hit rate for performance monitoring."""
        # This is a simplified calculation - in production you'd track hits/misses
        if len(self._validation_cache) > 0:
            return min(100.0, (len(self._validation_cache) / self._cache_max_size) * 100)
        return 0.0

    # Performance monitoring decorator removed - infrastructure monitoring handled externally
    async def submit_transaction(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Submit AI transaction to Revenium metering API."""
        # UCM-only validation - let the API handle required field validation
        # No hardcoded required fields - API will validate based on UCM capabilities
        logger.info("Transaction submission validation delegated to API based on UCM capabilities")

        # Security validation: Sanitize and validate inputs (async optimized)
        validation_result = await self._validate_transaction_inputs_async(arguments)
        if not validation_result["valid"]:
            raise create_structured_validation_error(
                message=f"⚠️ CRITICAL: Transaction validation failed - {validation_result['message']}",
                field="transaction_data",
                value=arguments,
                suggestions=[
                    "⚠️ CRITICAL: Always verify model/provider combinations using AI models tools before sending transactions",
                    "Use validate_model_provider() to check if your model/provider combination is supported",
                    "Use get_capabilities() to see all required and optional fields",
                    "Ensure all required fields (model, provider, input_tokens, output_tokens, duration_ms) are provided",
                    "Check that token counts and duration are positive integers",
                ],
                examples={
                    "valid_transaction": {
                        "model": "gpt-4",
                        "provider": "OPENAI",
                        "input_tokens": 1500,
                        "output_tokens": 800,
                        "duration_ms": 2500,
                    },
                    "validation_workflow": [
                        "list_ai_models()",
                        "validate_model_provider(model='gpt-4', provider='OPENAI')",
                        "submit_ai_transaction(model='gpt-4', provider='OPENAI', input_tokens=1500, output_tokens=800, duration_ms=2500)",
                    ],
                },
            )

        # Generate transaction ID if not provided; reject malformed user-supplied
        # ids before the payload reaches the backend, which silently drops them.
        user_supplied_id = arguments.get("transaction_id")
        if user_supplied_id:
            self._validate_transaction_id_format(user_supplied_id)
        transaction_id = user_supplied_id or self._generate_transaction_id()

        # Build payload with required fields matching the API format
        now_time = self._iso_utc()

        # Process timestamp fields with validation and auto-population
        request_time = self._process_timestamp_field(arguments, "request_time", now_time)
        response_time = self._process_timestamp_field(arguments, "response_time", now_time)
        completion_start_time = self._process_timestamp_field(
            arguments, "completion_start_time", now_time
        )

        # Handle time_to_first_token with smart defaults and validation
        time_to_first_token = arguments.get("time_to_first_token")
        if time_to_first_token is not None:
            try:
                time_to_first_token = int(time_to_first_token)
                if time_to_first_token < 0:
                    raise create_structured_validation_error(
                        message="🕒 Invalid time_to_first_token: Must be a positive integer",
                        field="time_to_first_token",
                        value=time_to_first_token,
                        suggestions=[
                            "Provide a positive integer value in milliseconds",
                            "Typical values range from 50ms to 5000ms",
                            "Or omit the field to auto-calculate from duration_ms",
                            "Auto-calculation uses 10% of total duration as default",
                        ],
                        examples={
                            "valid_values": [100, 500, 1000, 2500],
                            "auto_calculation": f"Auto-calculated: {int(arguments['duration_ms']) // 10}ms (10% of {arguments['duration_ms']}ms)",
                            "usage": "time_to_first_token=500  # 500 milliseconds",
                        },
                    )
                logger.info(f"Using provided time_to_first_token: {time_to_first_token}ms")
            except (ValueError, TypeError):
                raise create_structured_validation_error(
                    message=f"🕒 Invalid time_to_first_token format: Cannot convert '{time_to_first_token}' to integer",
                    field="time_to_first_token",
                    value=time_to_first_token,
                    suggestions=[
                        "Provide an integer value in milliseconds",
                        "Remove quotes if you provided a string number",
                        "Or omit the field to auto-calculate from duration_ms",
                        "Auto-calculation uses 10% of total duration as default",
                    ],
                    examples={
                        "valid_format": 500,  # Integer, not string
                        "invalid_format": "500",  # String
                        "auto_calculation": f"Auto-calculated: {int(arguments['duration_ms']) // 10}ms (10% of {arguments['duration_ms']}ms)",
                    },
                )
        else:
            # Auto-calculate as 10% of total duration (reasonable default for streaming)
            time_to_first_token = int(arguments["duration_ms"]) // 10
            logger.debug(f"Auto-calculated time_to_first_token: {time_to_first_token}ms")

        # Build payload matching EXACT Revenium API requirements
        payload = {
            "transactionId": transaction_id,
            "model": arguments["model"],
            "provider": arguments["provider"],
            "inputTokenCount": int(arguments["input_tokens"]),
            "outputTokenCount": int(arguments["output_tokens"]),
            "totalTokenCount": int(arguments["input_tokens"]) + int(arguments["output_tokens"]),
            "requestDuration": int(arguments["duration_ms"]),
            "costType": "AI",
            "stopReason": arguments.get("stop_reason", "END"),
            "isStreamed": arguments.get("is_streamed", False),
            "operationType": arguments.get("operation_type", "CHAT"),
            "reasoningTokenCount": int(arguments.get("reasoning_tokens", 0)),
            "cacheCreationTokenCount": int(arguments.get("cache_creation_tokens", 0)),
            "cacheReadTokenCount": int(arguments.get("cache_read_tokens", 0)),
            "timeToFirstToken": time_to_first_token,
            "requestTime": request_time,
            "responseTime": response_time,
            "completionStartTime": completion_start_time,
        }

        # Add optional fields if provided (matching API format)
        optional_fields = {
            "organizationId": arguments.get("organization_id"),
            "productId": arguments.get("product_id"),
            "taskType": arguments.get("task_type"),
            "agent": arguments.get("agent"),
            "errorReason": arguments.get("error_reason"),
            "traceId": arguments.get("trace_id"),
            "subscriptionId": arguments.get("subscription_id"),
            "responseQualityScore": arguments.get("response_quality_score"),
        }

        # Add non-None optional fields
        for key, value in optional_fields.items():
            if value is not None:
                payload[key] = value

        # Extract and add trace fields (10 tracing fields for distributed tracing)
        # These are extracted from arguments with env var fallback
        # Note: trace fields from usage_metadata CAN override default operationType
        # as per the distributed tracing design (user-provided values take precedence)
        trace_fields = extract_trace_fields(arguments)
        for key, value in trace_fields.items():
            payload[key] = value

        # Handle new subscriber object structure
        if "subscriber" in arguments and arguments["subscriber"] is not None:
            subscriber = arguments["subscriber"]
            subscriber_payload = {}

            # Add subscriber.id if provided
            if "id" in subscriber and subscriber["id"] is not None:
                subscriber_payload["id"] = subscriber["id"]

            # Add subscriber.email if provided
            if "email" in subscriber and subscriber["email"] is not None:
                subscriber_payload["email"] = subscriber["email"]

            # Add subscriber.credential object if provided
            if "credential" in subscriber and subscriber["credential"] is not None:
                credential = subscriber["credential"]
                credential_payload = {}

                if "name" in credential and credential["name"] is not None:
                    credential_payload["name"] = credential["name"]

                if "value" in credential and credential["value"] is not None:
                    credential_payload["value"] = credential["value"]

                if credential_payload:
                    subscriber_payload["credential"] = credential_payload

            # Add subscriber object to payload if it has any fields
            if subscriber_payload:
                payload["subscriber"] = subscriber_payload

        # Submit transaction to metering API with caching
        endpoint = "/meter/v2/ai/completions"

        # Debug: Log the exact payload being sent (sanitized for security)
        sanitized_payload = self._sanitize_for_logging(payload)
        logger.info(f"Submitting transaction to {endpoint}")
        logger.info(f"Payload structure: {json.dumps(sanitized_payload, indent=2, default=str)}")

        # Check cache for identical submissions (rare but possible for retries)
        cache_key = f"submit_{hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]}"
        cached_response = await response_cache.get_cached_response("api", cache_key)

        if cached_response is not None:
            logger.debug("Using cached API response for transaction submission")
            response = cached_response
        else:
            try:
                response = await client.post(endpoint, data=payload)
                logger.info(f"📡 API Response status: {response.get('status', 'unknown')}")
                logger.debug(f"📡 Full API Response: {response}")
                # Cache successful responses for 5 minutes (for retry scenarios)
                if response:
                    await response_cache.set_cached_response(
                        "api", cache_key, response, ttl_seconds=300
                    )
            except Exception as api_error:
                logger.error(f"❌ API submission failed: {api_error}")
                logger.error(f"📦 Failed payload: {sanitized_payload}")
                raise

        # Store transaction for verification
        self.transaction_store[transaction_id] = {
            "payload": payload,
            "timestamp": datetime.now(timezone.utc),
            "verified": False,
            "submitted": True,
        }

        return {
            "transaction_id": transaction_id,
            "status": "submitted",
            "model": arguments["model"],
            "provider": arguments["provider"],
            "tokens": f"{arguments['input_tokens']} input + {arguments['output_tokens']} output",
            "duration_ms": arguments["duration_ms"],
        }

    async def get_transaction_status(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get status of a specific transaction."""
        transaction_id = arguments.get("transaction_id")

        if not transaction_id:
            raise create_structured_missing_parameter_error(
                parameter_name="transaction_id",
                action="get_transaction_status",
                examples={
                    "usage": "get_transaction_status(transaction_id='<transaction_id>')",
                    "valid_format": "Transaction ID from submit_ai_transaction response",
                    "example_values": ["tx_abc123def456", "tx_9a72259e8eba", "tx_c6e0f783c0c9"],
                },
            )

        if transaction_id in self.transaction_store:
            stored_data = self.transaction_store[transaction_id]
            return {
                "transaction_id": transaction_id,
                "found": True,
                "submitted_at": stored_data["timestamp"].isoformat(),
                "verified": stored_data.get("verified", False),
                "model": stored_data["payload"].get("model", "Unknown"),
                "provider": stored_data["payload"].get("provider", "Unknown"),
            }
        else:
            return {
                "transaction_id": transaction_id,
                "found": False,
                "message": "Transaction not found in this session",
            }

    def _validate_lookup_parameters(self, transaction_ids: List[str]) -> None:
        """Validate lookup_transactions parameters.

        Validates that transaction_ids parameter is provided and not empty.
        Uses structured error messages with helpful examples for batch usage.

        Args:
            transaction_ids: List of transaction IDs to validate

        Raises:
            ToolError: If transaction_ids is empty or invalid
        """
        # CRITICAL FIX: Explicitly check for empty arrays to prevent 30-second waits
        if not transaction_ids or len(transaction_ids) == 0:
            raise create_structured_missing_parameter_error(
                parameter_name="transaction_ids",
                action="lookup_transactions",
                examples={
                    "usage": "lookup_transactions(transaction_ids=['tx_abc123'])",
                    "batch_usage": "lookup_transactions(transaction_ids=['tx_abc123', 'tx_def456'])",
                    "with_retries": "lookup_transactions(transaction_ids=['tx_abc123'], max_retries=5)",
                    "valid_format": "Transaction IDs from submit_ai_transaction response",
                    "example_values": ["tx_abc123def456", "tx_9a72259e8eba", "tx_c6e0f783c0c9"],
                    "description": "Unified transaction lookup with automatic optimization",
                },
            )

    def _check_session_store(
        self, transaction_ids: Optional[List[str]]
    ) -> Tuple[Dict[str, Any], List[str]]:
        """Check local session store for transaction data.

        Searches the local session store for transaction data and returns
        found transactions along with remaining IDs that need API lookup.

        Args:
            transaction_ids: List of transaction IDs to check, or None for all unverified

        Returns:
            Tuple of (found_transactions_dict, remaining_ids_for_api_search)
        """
        if transaction_ids:
            # Extract exact pattern from lines 1442-1443
            found_in_session = {
                tid: self.transaction_store.get(tid)
                for tid in transaction_ids
                if tid in self.transaction_store
            }
            # Calculate remaining IDs that need API search
            remaining_ids = [tid for tid in transaction_ids if tid not in self.transaction_store]
        else:
            # Extract exact pattern from lines 1444-1445
            found_in_session = {
                tid: data
                for tid, data in self.transaction_store.items()
                if not data.get("verified", False)
            }
            remaining_ids = []

        return found_in_session, remaining_ids

    def _process_batch_result(
        self, result: Any, transaction_id: str, operation_name: str
    ) -> Dict[str, Any]:
        """Process individual batch result using extracted patterns."""
        if isinstance(result, Exception):
            # Extract exception handling pattern from lines 1543-1550
            logger.error(
                f"❌ {operation_name.capitalize()} task failed for {transaction_id}: {result}"
            )
            return {
                "transaction_id": transaction_id,
                "found": False,
                "error": str(result),
                "source": "error",
            }
        elif isinstance(result, dict):
            # Extract successful result handling
            return result
        else:
            # Extract unexpected result handling from lines 1573-1580
            logger.error(f"❌ Unexpected result type for {transaction_id}: {type(result)}")
            return {
                "transaction_id": transaction_id,
                "found": False,
                "error": f"Unexpected result type: {type(result)}",
                "source": "error",
            }

    async def _handle_retry_attempt(
        self,
        operation_func: Callable[[], Awaitable[Tuple[Any, Dict[str, Any]]]],
        transaction_id: str,
        attempt: int,
        max_retries: int,
        operation_name: str,
    ) -> Tuple[bool, Any, Dict[str, Any], Optional[Exception]]:
        """Handle single retry attempt using extracted patterns."""
        try:
            # Extract logging pattern from line 1631
            logger.info(
                f"🔍 Executing {operation_name} for {transaction_id} (attempt {attempt + 1}/{max_retries})"
            )

            # Execute operation function
            result, metadata = await operation_func()

            if result:
                # Extract success logging pattern from line 1643
                logger.info(f"✅ {operation_name.capitalize()} successful for {transaction_id}")
                return True, result, metadata, None

            return False, None, {}, None

        except Exception as e:
            # Extract exception handling pattern from lines 1651-1658
            logger.warning(
                f"⚠️ Error in {operation_name} for {transaction_id} (attempt {attempt + 1}): {e}"
            )
            return False, None, {}, e

    async def _execute_with_retry(
        self,
        operation_func: Callable[[], Awaitable[Tuple[Any, Dict[str, Any]]]],
        transaction_id: str,
        max_retries: int,
        retry_interval: int,
        operation_name: str = "operation",
    ) -> Tuple[bool, Any, Dict[str, Any], Optional[Exception]]:
        """Execute operation with retry logic.

        Executes the provided operation with configurable retry attempts,
        including proper timing, logging, and error handling.
        """
        last_error = None

        # Extract retry loop pattern from lines 1629-1658
        for attempt in range(max_retries):
            success, result, metadata, error = await self._handle_retry_attempt(
                operation_func, transaction_id, attempt, max_retries, operation_name
            )

            if success:
                return True, result, metadata, None

            if error:
                last_error = error

            # Extract retry delay logic from lines 1647-1649 and 1656-1658
            if attempt < max_retries - 1:
                logger.info(
                    f"⏳ {operation_name.capitalize()} failed for {transaction_id}, retrying in {retry_interval}s..."
                )
                await asyncio.sleep(retry_interval)

        return False, None, {}, last_error

    def _build_result_entry(
        self,
        transaction_id: str,
        found: bool,
        source: str,
        transaction_data: Optional[Dict[str, Any]] = None,
        search_metadata: Optional[Dict[str, Any]] = None,
        attempts: int = 1,
        message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build individual lookup result entry.

        Creates a standardized result dictionary for a single transaction lookup
        with consistent structure and metadata.

        Args:
            transaction_id: Transaction ID that was searched
            found: Whether transaction was found
            source: "session" or "api" - where transaction was found
            transaction_data: Complete transaction data when found
            search_metadata: Search statistics and details
            attempts: Number of retry attempts made
            message: Error message when not found

        Returns:
            Dict with result entry following proven pattern
        """
        # Extract base structure from lines 2039-2042
        result = {
            "transaction_id": transaction_id,
            "found": found,
            "source": source,
            "attempts": attempts,
        }

        # Extract conditional fields from transaction lookup pattern
        if found and transaction_data:
            result["transaction_data"] = transaction_data

        if search_metadata:
            result["search_metadata"] = search_metadata

        # Extract error message pattern from lines 2048-2050
        if not found and message:
            result["message"] = message

        return result

    def _build_lookup_response(
        self, results: List[Dict[str, Any]], configuration: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build unified lookup response.

        Creates a comprehensive response with summary statistics and detailed
        results for all requested transactions.

        Args:
            results: List of result dictionaries for each transaction
            configuration: Request parameters used

        Returns:
            Dict with unified response format combining both tools' strengths
        """
        # Extract summary calculation pattern from transaction lookup logic
        total_requested = len(results)
        found_count = sum(1 for r in results if r.get("found", False))
        missing_count = total_requested - found_count

        # Calculate source breakdown (new unified feature)
        session_count = sum(1 for r in results if r.get("source") == "session" and r.get("found"))
        api_count = sum(1 for r in results if r.get("source") == "api" and r.get("found"))

        # Extract proven response structure from transaction lookup pattern
        return {
            "results": results,
            "summary": {
                "total_requested": total_requested,
                "found_count": found_count,
                "missing_count": missing_count,
                "sources": {"session": session_count, "api": api_count},
            },
            "configuration": configuration,
        }

    def _normalize_return_data_parameter(self, arguments: Dict[str, Any]) -> str:
        """Convert legacy boolean or new string values to normalized string enum.

        Supports backward compatibility for boolean values while enabling new string enum options.

        Args:
            arguments: Raw arguments dictionary

        Returns:
            Normalized string: "no", "summary", or "full"
        """
        value = arguments.get("return_transaction_data", "no")

        # Handle legacy boolean values for backward compatibility
        if isinstance(value, bool):
            return "summary" if value else "no"

        # Handle string values (case-insensitive)
        if isinstance(value, str):
            value = value.lower().strip()
            if value in ["no", "false", "0", "none"]:
                return "no"
            elif value in ["summary", "yes", "true", "1", "basic"]:
                return "summary"
            elif value in ["full", "detailed", "verbose", "complete", "all"]:
                return "full"

        # Default fallback for invalid values
        return "no"

    def _extract_lookup_parameters(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Extract and validate lookup_transactions parameters."""
        params = {
            "transaction_ids": arguments.get("transaction_ids", []),
            "check_session_first": True,  # Always check session first as internal optimization
            "wait_seconds": arguments.get("wait_seconds", 30),
            "max_retries": arguments.get("max_retries", 3),
            "retry_interval": arguments.get("retry_interval", 15),
            "search_page_range": arguments.get("search_page_range", 50),
            "page_size": arguments.get("page_size", 1000),
            "early_termination": arguments.get("early_termination", True),
            "return_transaction_data": self._normalize_return_data_parameter(arguments),
            "filters": _extract_completions_filters(arguments),
        }

        # Validate parameters using extracted validation logic
        self._validate_lookup_parameters(params["transaction_ids"])

        return params

    def _build_configuration_object(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Build configuration object for response transparency."""
        return {
            "wait_seconds": params["wait_seconds"],
            "max_retries": params["max_retries"],
            "retry_interval": params["retry_interval"],
            "search_page_range": params["search_page_range"],
            "page_size": params["page_size"],
            "early_termination": params["early_termination"],
        }



    async def _process_session_results(
        self, transaction_ids: List[str]
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """Process session store results and return formatted entries.

        Always checks session store first as internal optimization.
        """
        results = []

        # Always check session store first (internal optimization)
        found_in_session, remaining_ids = self._check_session_store(transaction_ids)

        # Process session store results
        for tid, transaction_data in found_in_session.items():
            result_entry = self._build_result_entry(
                transaction_id=tid,
                found=True,
                source="session",
                transaction_data=transaction_data,
                attempts=1,
            )
            results.append(result_entry)

        return results, remaining_ids

    def _build_api_result_entry(
        self,
        tid: str,
        success: bool,
        transaction_data: Any,
        search_metadata: Dict[str, Any],
        max_retries: int,
    ) -> Dict[str, Any]:
        """Build result entry for API search results."""
        if success and transaction_data:
            return self._build_result_entry(
                transaction_id=tid,
                found=True,
                source="api",
                transaction_data=transaction_data,
                search_metadata=search_metadata,
                attempts=1,
            )
        else:
            # Build not found entry with helpful message
            message = f"Transaction {tid} not found"
            if search_metadata and "transactions_examined" in search_metadata:
                message = f"Transaction {tid} not found in {search_metadata['transactions_examined']:,} transactions across {search_metadata.get('pages_searched', 0)} pages"

            return self._build_result_entry(
                transaction_id=tid,
                found=False,
                source="api",
                search_metadata=search_metadata,
                attempts=max_retries,
                message=message,
            )

    async def _process_api_results(
        self, client: ReveniumClient, remaining_ids: List[str], params: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Process API search results for remaining transaction IDs."""
        results = []

        if not remaining_ids:
            return results

        # Process each remaining transaction with retry logic
        for tid in remaining_ids:
            # Create operation function for retry logic
            async def search_operation():
                return await self._search_transaction_pages(
                    client,
                    tid,
                    params["search_page_range"],
                    params["page_size"],
                    params["early_termination"],
                    filters=params.get("filters"),
                )

            success, transaction_data, search_metadata, error = await self._execute_with_retry(
                search_operation, tid, params["max_retries"], params["retry_interval"], "lookup"
            )

            result_entry = self._build_api_result_entry(
                tid, success, transaction_data, search_metadata, params["max_retries"]
            )
            results.append(result_entry)

        return results

    async def lookup_transactions(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Unified transaction lookup with automatic optimization.

        Efficiently finds transactions using internal session cache and comprehensive API search.
        """
        # Extract and validate parameters
        params = self._extract_lookup_parameters(arguments)

        # Build configuration for response transparency
        configuration = self._build_configuration_object(params)

        # Phase 1: Process session store results (always check session first)
        session_results, remaining_ids = await self._process_session_results(
            params["transaction_ids"]
        )

        # Phase 2: Process API search results
        api_results = await self._process_api_results(client, remaining_ids, params)

        # Combine all results
        all_results = session_results + api_results

        # Build final unified response using extracted response builder
        return self._build_lookup_response(all_results, configuration)

    async def _search_transaction_pages(
        self,
        client: ReveniumClient,
        transaction_id: str,
        search_page_range: Union[int, Tuple[int, int]] = 50,
        page_size: int = 1000,
        early_termination: bool = True,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        """Search across multiple pages for a specific transaction with comprehensive auto-pagination.

        This method implements efficient transaction search with maximum API efficiency,
        searching up to 5,000 transactions by default using 1,000 transactions per API call.
        When filters are provided (especially startDate/endDate or transactionId), the API
        narrows results server-side, dramatically reducing pages needed.

        Args:
            client: Revenium API client
            transaction_id: Transaction ID to search for
            search_page_range: Pages to search - int for 0 to N-1, tuple for (start, end) range
            page_size: Transactions per API call (default: 1000 - maximum supported)
            early_termination: Stop searching when transaction is found (default: True)
            filters: Optional dict of camelCase API filter params (e.g. startDate, provider).
                     Passing transactionId here enables direct API lookup instead of page scanning.

        Returns:
            Tuple of (transaction_data, search_metadata) where:
            - transaction_data: Dict with transaction info if found, None if not found
            - search_metadata: Dict with search statistics and results
        """
        endpoint = get_endpoint_path("completions")

        # Short-circuit: if transactionId or traceId is in filters, the API can
        # resolve the lookup directly — no need to scan multiple pages.
        if filters and ("transactionId" in filters or "traceId" in filters):
            search_page_range = 1  # only page 0

        # Parse search range
        if isinstance(search_page_range, int):
            start_page, end_page = 0, search_page_range - 1
        else:
            start_page, end_page = search_page_range

        total_pages_searched = 0
        total_transactions_examined = 0
        transaction_found = None

        logger.info(f"🔍 Starting comprehensive transaction search for {transaction_id}")
        logger.info(
            f"📊 Search scope: pages {start_page}-{end_page} ({end_page - start_page + 1} pages), {page_size} transactions per page"
        )
        logger.info(
            f"🎯 Maximum search capacity: {(end_page - start_page + 1) * page_size:,} transactions"
        )

        for page in range(start_page, end_page + 1):
            try:
                params = {
                    "teamId": client.team_id,
                    "page": page,
                    "size": page_size,
                    "sort": "timestamp,desc",
                }
                # Apply any caller-supplied filters (date range, provider, model, etc.)
                if filters:
                    params.update(filters)
                # Always scope to the specific transaction — lets the API do the filtering
                # instead of scanning every record on the page.
                params["transactionId"] = transaction_id

                logger.debug(f"🔍 Searching page {page} (size: {page_size})")
                response = await client.get(endpoint, params=params)

                # Handle both possible response structures
                transactions_list = []
                if (
                    "_embedded" in response
                    and "aICompletionMetricResourceList" in response["_embedded"]
                ):
                    transactions_list = response["_embedded"]["aICompletionMetricResourceList"]
                elif "content" in response:
                    transactions_list = response["content"]

                # If no transactions on this page, we've reached the end
                if not transactions_list:
                    logger.info(f"📄 Reached end of data at page {page}")
                    break

                page_transaction_count = len(transactions_list)
                total_transactions_examined += page_transaction_count
                total_pages_searched += 1

                # Search for the target transaction in this page with universal ID format support
                for transaction in transactions_list:
                    stored_transaction_id = transaction.get("transactionId")
                    if self._transaction_ids_match(stored_transaction_id, transaction_id):
                        transaction_found = transaction
                        logger.info(
                            f"✅ Transaction {transaction_id} found on page {page} (stored as: {stored_transaction_id})"
                        )

                        if early_termination:
                            logger.info("🎯 Early termination enabled - stopping search")
                            break

                # If found and early termination enabled, stop searching
                if transaction_found and early_termination:
                    break

                # Log progress for longer searches
                if page % 10 == 0 and page > 0:
                    logger.info(
                        f"📊 Search progress: {total_pages_searched} pages, {total_transactions_examined:,} transactions examined"
                    )

                # Check if we've reached the last page according to API
                page_info = response.get("page", {})
                if page >= page_info.get("totalPages", 1) - 1:
                    logger.info(
                        f"📄 Reached API's last page ({page_info.get('totalPages', 1)} total pages)"
                    )
                    break

            except Exception as e:
                logger.warning(f"❌ Failed to search page {page}: {e}")
                break

        # Compile search metadata
        search_metadata = {
            "pages_searched": total_pages_searched,
            "transactions_examined": total_transactions_examined,
            "search_range": f"pages {start_page}-{end_page}",
            "page_size": page_size,
            "early_termination": early_termination,
            "found": transaction_found is not None,
        }

        logger.info(
            f"🏁 Search complete: {total_pages_searched} pages, {total_transactions_examined:,} transactions examined"
        )

        return transaction_found, search_metadata


class MeteringValidator:
    """Internal manager for metering validation."""

    def __init__(self, transaction_manager=None):
        """Initialize metering validator.

        Args:
            transaction_manager: Shared transaction manager instance for consistent validation
        """
        self.transaction_manager = transaction_manager

    async def validate_transaction(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Validate transaction data."""
        # Use the shared transaction manager for consistent validation
        if not self.transaction_manager:
            self.transaction_manager = MeteringTransactionManager()

        try:
            validation_result = await self.transaction_manager._validate_transaction_inputs_async(
                arguments
            )

            if validation_result["valid"]:
                return {
                    "valid": True,
                    "errors": [],
                    "warnings": [],
                    "message": "All transaction data is valid and ready for submission.",
                }
            else:
                return {
                    "valid": False,
                    "errors": [validation_result["message"]],
                    "warnings": [],
                    "message": validation_result["message"],
                }
        except Exception as e:
            logger.error(f"Error in transaction validation: {e}")
            return {
                "valid": False,
                "errors": [str(e)],
                "warnings": [],
                "message": f"Validation error: {str(e)}",
            }


class MeteringManagement(ToolBase):
    """Consolidated AI metering management tool with comprehensive capabilities."""

    tool_name = "manage_metering"
    tool_description = (
        "Submit AI transaction metering metadata and lookup existing AI transactions metered by Revenium. "
        "Receive guidance for writing new integrations to Revenium's AI metering API using python and typescript. "
        "Key actions: submit_ai_transaction, lookup_transactions (requires transaction IDs), lookup_recent_transactions (browse without IDs), "
        "get_integration_guide, list_ai_models, validate. Supports Python and JavaScript integration examples. "
        "Use get_capabilities() for full guidance."
    )
    business_category = "Metering and Analytics Tools"
    tool_type = ToolType.UTILITY
    tool_version = "2.0.0"

    def __init__(self, ucm_helper=None):
        """Initialize metering management tool.

        Args:
            ucm_helper: UCM integration helper for capability management
        """
        super().__init__(ucm_helper)
        self.formatter = UnifiedResponseFormatter("manage_metering")
        self.transaction_manager = MeteringTransactionManager()
        self.validator = MeteringValidator(self.transaction_manager)  # Share transaction manager

    def _normalize_return_data_parameter(self, arguments: Dict[str, Any]) -> str:
        """Convert legacy boolean or new string values to normalized string enum.

        Supports backward compatibility for boolean values while enabling new string enum options.

        Args:
            arguments: Raw arguments dictionary

        Returns:
            Normalized string: "no", "summary", or "full"
        """
        value = arguments.get("return_transaction_data", "no")

        # Handle legacy boolean values for backward compatibility
        if isinstance(value, bool):
            return "summary" if value else "no"

        # Handle string values (case-insensitive)
        if isinstance(value, str):
            value = value.lower().strip()
            if value in ["no", "false", "0", "none"]:
                return "no"
            elif value in ["summary", "yes", "true", "1", "basic"]:
                return "summary"
            elif value in ["full", "detailed", "verbose", "complete", "all"]:
                return "full"

        # Default fallback for invalid values
        return "no"

    async def handle_action(
        self, action: str, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle metering management actions with response caching."""
        try:
            # Clear request-scoped caches for fresh request
            response_cache.clear_request_cache()
            self.transaction_manager.clear_request_cache()

            client = await self.get_client()

            # Route to appropriate handler
            if action == "submit_ai_transaction":
                # Handle dry_run mode for transaction submission
                dry_run = arguments.get("dry_run", False)
                if dry_run:
                    # Validate transaction data without submitting
                    validation_result = await self.validator.validate_transaction(arguments)
                    if validation_result["valid"]:
                        # Build comprehensive dry-run output including optional fields
                        dry_run_text = "🧪 **DRY RUN MODE - Transaction Validation**\n\n"
                        dry_run_text += (
                            "✅ **Validation Successful**: Transaction data is valid and ready for submission\n\n"
                        )
                        dry_run_text += "**Would Submit:**\n"
                        dry_run_text += f"- **Model:** {arguments.get('model', 'N/A')}\n"
                        dry_run_text += f"- **Provider:** {arguments.get('provider', 'N/A')}\n"
                        dry_run_text += (
                            f"- **Input Tokens:** {arguments.get('input_tokens', 'N/A')}\n"
                        )
                        dry_run_text += (
                            f"- **Output Tokens:** {arguments.get('output_tokens', 'N/A')}\n"
                        )
                        dry_run_text += f"- **Duration:** {arguments.get('duration_ms', 'N/A')}ms\n"

                        # Add optional fields if provided
                        optional_fields_display = [
                            ("subscription_id", "Subscription ID"),
                            ("response_quality_score", "Response Quality Score"),
                            ("organization_id", "Organization ID"),
                            ("product_id", "Product ID"),
                            ("task_type", "Task Type"),
                            ("agent", "Agent"),
                            ("trace_id", "Trace ID"),
                            ("error_reason", "Error Reason"),
                        ]

                        for field_key, field_label in optional_fields_display:
                            if field_key in arguments and arguments[field_key] is not None:
                                dry_run_text += f"- **{field_label}:** {arguments[field_key]}\n"

                        # Add subscriber information if provided
                        if "subscriber" in arguments and arguments["subscriber"] is not None:
                            subscriber = arguments["subscriber"]
                            dry_run_text += "- **Subscriber:**\n"
                            if "id" in subscriber and subscriber["id"]:
                                dry_run_text += f"  - ID: {subscriber['id']}\n"
                            if "email" in subscriber and subscriber["email"]:
                                dry_run_text += f"  - Email: {subscriber['email']}\n"
                            if "credential" in subscriber and subscriber["credential"]:
                                credential = subscriber["credential"]
                                if "name" in credential and credential["name"]:
                                    dry_run_text += f"  - Credential Name: {credential['name']}\n"

                        dry_run_text += "\n**Dry Run:** True (no actual submission performed)"

                        return [TextContent(type="text", text=dry_run_text)]
                    else:
                        errors_text = "\n".join(
                            [f"• {error}" for error in validation_result["errors"]]
                        )
                        return [
                            TextContent(
                                type="text",
                                text="🧪 **DRY RUN MODE - Validation Failed**\n\n"
                                f"❌ **Errors Found:**\n{errors_text}\n\n"
                                "**Dry Run:** True (fix errors before actual submission)",
                            )
                        ]

                result = await self.transaction_manager.submit_transaction(client, arguments)
                return [
                    TextContent(
                        type="text",
                        text="✅ **Transaction Submitted Successfully**\n\n"
                        f"**Transaction ID:** `{result['transaction_id']}`\n"
                        f"**Model:** {result['model']}\n"
                        f"**Provider:** {result['provider']}\n"
                        f"**Tokens:** {result['tokens']}\n"
                        f"**Duration:** {result['duration_ms']}ms\n\n"
                        f"**Status:** {result['status']}",
                    )
                ]

            elif action == "get_transaction_status":
                result = await self.transaction_manager.get_transaction_status(arguments)
                if result["found"]:
                    return [
                        TextContent(
                            type="text",
                            text="**Transaction Status**\n\n"
                            f"**Transaction ID:** `{result['transaction_id']}`\n"
                            "**Found:** Yes\n"
                            f"**Submitted At:** {result['submitted_at']}\n"
                            f"**Verified:** {'Yes' if result['verified'] else 'No'}\n"
                            f"**Model:** {result['model']}\n"
                            f"**Provider:** {result['provider']}",
                        )
                    ]
                else:
                    return [
                        TextContent(
                            type="text",
                            text="**Transaction Not Found**\n\n"
                            f"**Transaction ID:** `{result['transaction_id']}`\n"
                            f"**Found:** No\n\n{result['message']}",
                        )
                    ]

            elif action == "validate":
                result = await self.validator.validate_transaction(arguments)
                if result["valid"]:
                    # Enhanced validation response with progressive guidance
                    response_text = "✅ **Validation Successful**\n\n"
                    response_text += result["message"]
                    return [TextContent(type="text", text=response_text)]
                else:
                    return [
                        TextContent(
                            type="text", text=f"❌ **Validation Failed**\n\n{result['message']}"
                        )
                    ]
            elif action == "lookup_transactions":
                result = await self.transaction_manager.lookup_transactions(client, arguments)

                # Format unified response for display
                response_text = "**Transaction Lookup Results**\n\n"
                response_text += (
                    f"**Summary**: {result['summary']['found_count']}/{result['summary']['total_requested']} "
                    f"transactions found\n"
                )
                response_text += (
                    f"**Sources**: {result['summary']['sources']['session']} session, "
                    f"{result['summary']['sources']['api']} API\n\n"
                )

                # Extract and normalize return_transaction_data parameter
                return_transaction_data = self._normalize_return_data_parameter(arguments)

                # Display individual results
                for i, transaction_result in enumerate(result["results"], 1):
                    response_text += (
                        f"**{i}. Transaction {transaction_result['transaction_id']}**\n"
                    )
                    if transaction_result["found"]:
                        response_text += f"✅ **Found** (source: {transaction_result['source']})\n"

                        # Show transaction data based on consolidated parameter
                        if return_transaction_data in ["summary", "full"] and "transaction_data" in transaction_result:
                            data = transaction_result["transaction_data"]

                            # Use shared method for core fields display
                            response_text += self._format_transaction_summary(data, include_timestamp=False)

                            # Show additional fields only in full mode
                            if return_transaction_data == "full":
                                response_text += self._format_full_transaction_details(data)
                    else:
                        response_text += (
                            f"❌ **Not Found** (searched via {transaction_result['source']})\n"
                        )
                        if "message" in transaction_result:
                            response_text += f"- {transaction_result['message']}\n"
                    response_text += "\n"

                return [TextContent(type="text", text=response_text)]
            elif action == "lookup_recent_transactions":
                result = await self._handle_lookup_recent_transactions(client, arguments)
                return [TextContent(type="text", text=result)]
            elif action == "get_capabilities":
                return await self._handle_get_capabilities()
            elif action == "get_examples":
                return await self._handle_get_examples(arguments)
            elif action == "get_agent_summary":
                return await self._handle_get_agent_summary()
            elif action == "parse_natural_language":
                return await self._handle_parse_natural_language(arguments)
            # AI Models Discovery Actions
            elif action == "list_ai_models":
                return await self._handle_list_ai_models(arguments)
            elif action == "search_ai_models":
                return await self._handle_search_ai_models(arguments)
            elif action == "get_supported_providers":
                return await self._handle_get_supported_providers(arguments)
            elif action == "validate_model_provider":
                return await self._handle_validate_model_provider(arguments)
            elif action == "estimate_transaction_cost":
                return await self._handle_estimate_transaction_cost(arguments)
            # Integration Support Actions
            elif action == "get_api_endpoints":
                return await self._handle_get_api_endpoints()
            elif action == "get_authentication_details":
                return await self._handle_get_authentication_details()
            elif action == "get_response_formats":
                return await self._handle_get_response_formats()
            elif action == "get_integration_config":
                return await self._handle_get_integration_config(arguments)
            elif action == "get_rate_limits":
                return await self._handle_get_rate_limits()
            elif action == "get_integration_guide":
                return await self._handle_get_integration_guide(arguments)
            # Tiered Capability Actions (Progressive Discovery)
            elif action == "get_submission_capabilities":
                return await self._handle_get_submission_capabilities()
            elif action == "get_lookup_capabilities":
                return await self._handle_get_lookup_capabilities()
            elif action == "get_integration_capabilities":
                return await self._handle_get_integration_capabilities()
            elif action == "get_validation_capabilities":
                return await self._handle_get_validation_capabilities()
            elif action == "get_field_documentation":
                return await self._handle_get_field_documentation()
            elif action == "get_business_rules":
                return await self._handle_get_business_rules()
            else:
                # Use structured error for unknown action
                raise ToolError(
                    message=f"Unknown action '{action}' is not supported",
                    error_code=ErrorCodes.ACTION_NOT_SUPPORTED,
                    field="action",
                    value=action,
                    suggestions=[
                        "⚠️ CRITICAL: Always verify model/provider combinations using AI models tools before sending transactions",
                        "Use get_capabilities() to see all available actions and validation requirements",
                        "Check the action name for typos",
                        "Use get_examples() to see working examples",
                        "For AI metering, start with validate() to test your transaction data",
                    ],
                    examples={
                        "transaction_actions": [
                            "submit_ai_transaction",
                            "lookup_transactions",
                            "get_transaction_status",
                        ],
                        "validation_actions": ["validate", "validate_model_provider"],
                        "discovery_actions": [
                            "get_capabilities",
                            "get_examples",
                            "get_agent_summary",
                        ],
                        "ai_models_actions": [
                            "list_ai_models",
                            "search_ai_models",
                            "get_supported_providers",
                        ],
                        "cost_actions": ["estimate_transaction_cost"],
                        "example_workflow": {
                            "step_1": "search_ai_models(query='gpt')",
                            "step_2": "validate_model_provider(model='gpt-4o', provider='openai')",
                            "step_3": "submit_ai_transaction(model='gpt-4o', provider='openai', input_tokens=1500, output_tokens=800, duration_ms=2500)",
                            "step_4": "lookup_transactions(transaction_ids=['tx_abc123'])",
                        },
                    },
                )

        except Exception as e:
            logger.error(f"Error in metering management: {e}")
            # Re-raise Exception to be handled by standardized_tool_execution
            raise e

    async def _handle_lookup_recent_transactions(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> str:
        """Handle lookup_recent_transactions action with pagination support.

        Args:
            client: Revenium API client
            arguments: Action arguments containing pagination parameters

        Returns:
            Formatted response text with transaction data and pagination info
        """
        # Extract and validate parameters
        page = arguments.get("page", 0)
        page_size = arguments.get("recent_page_size") if "recent_page_size" in arguments else arguments.get("page_size", 20)
        # Set default to "summary" for recent transactions lookup
        if "return_transaction_data" not in arguments:
            arguments = arguments.copy()
            arguments["return_transaction_data"] = "summary"
        return_transaction_data = self._normalize_return_data_parameter(arguments)

        # Validate parameters
        if not isinstance(page, int) or page < 0:
            raise create_structured_validation_error(
                message=f"Invalid page parameter: {page}. Must be a non-negative integer.",
                field="page",
                value=page,
                suggestions=[
                    "Use page=0 for the first page",
                    "Use page=1 for the second page, etc.",
                    "Page numbers are 0-based (start from 0)"
                ],
                examples={
                    "first_page": "lookup_recent_transactions(page=0)",
                    "second_page": "lookup_recent_transactions(page=1)",
                    "valid_values": [0, 1, 2, 3, 4]
                }
            )

        if not isinstance(page_size, int) or page_size < 1 or page_size > 100:
            raise create_structured_validation_error(
                message=f"Invalid recent_page_size parameter: {page_size}. Must be an integer between 1 and 100.",
                field="recent_page_size",
                value=page_size,
                suggestions=[
                    "Use recent_page_size=20 for default pagination",
                    "Use recent_page_size=10 for smaller pages",
                    "Maximum recent_page_size is 100"
                ],
                examples={
                    "default": "lookup_recent_transactions(recent_page_size=20)",
                    "small_pages": "lookup_recent_transactions(recent_page_size=10)",
                    "valid_range": "1-100"
                }
            )

        # Extract completions API filter params from arguments
        filters = _extract_completions_filters(arguments)

        # Fetch recent transactions with pagination
        transactions, pagination_info = await self._fetch_recent_transactions_paginated(
            client, page, page_size, filters=filters
        )

        # Format response
        response_text = "**Recent Transactions**\n\n"
        response_text += f"**Page**: {pagination_info['page']} (size: {pagination_info['page_size']})\n"
        response_text += f"**Found**: {pagination_info['total_found']} transactions\n"
        if pagination_info.get('has_more'):
            response_text += f"**More Available**: Use page={pagination_info['page'] + 1} for next page\n"
        response_text += "\n"

        # Display transaction data based on detail level
        if not transactions:
            response_text += "No transactions found for the specified page.\n"
        else:
            for i, transaction in enumerate(transactions, 1):
                response_text += f"**{i}. Transaction {transaction.get('transactionId', 'N/A')}**\n"

                if return_transaction_data in ["summary", "full"]:
                    # Use shared method for core fields display (includes timestamp for recent transactions)
                    response_text += self._format_transaction_summary(transaction, include_timestamp=True)

                    if return_transaction_data == "full":
                        response_text += self._format_full_transaction_details(transaction)
                elif return_transaction_data == "no":
                    response_text += "- **Status**: Found\n"

                response_text += "\n"

        return response_text

    async def _fetch_recent_transactions_paginated(
        self,
        client: ReveniumClient,
        page: int = 0,
        page_size: int = 20,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Fetch recent transactions with pagination support.

        Args:
            client: Revenium API client
            page: Page number (0-based)
            page_size: Number of transactions per page (max 100)
            filters: Optional camelCase API filter params (startDate, endDate, provider, etc.)

        Returns:
            Tuple of (transactions_list, pagination_metadata)
        """
        endpoint = get_endpoint_path("completions")
        params = {
            "teamId": client.team_id,
            "page": page,
            "size": page_size,
            "sort": "timestamp,desc",
        }
        if filters:
            params.update(filters)

        logger.info(f"🔍 Fetching recent transactions: page {page}, size {page_size}")
        response = await client.get(endpoint, params=params)

        # Handle both possible response structures
        transactions = []
        if (
            "_embedded" in response
            and "aICompletionMetricResourceList" in response["_embedded"]
        ):
            # New API structure with _embedded
            transactions = response["_embedded"]["aICompletionMetricResourceList"]
        elif "content" in response:
            # Legacy API structure with content
            transactions = response["content"]

        # Extract pagination info from response
        pagination_info = {
            "page": page,
            "page_size": page_size,
            "total_found": len(transactions),
            "has_more": len(transactions) == page_size,  # Assume more if we got a full page
        }

        # Add additional pagination metadata if available in response
        if "page" in response:
            page_data = response["page"]
            pagination_info.update({
                "total_elements": page_data.get("totalElements"),
                "total_pages": page_data.get("totalPages"),
                "has_more": not page_data.get("last", True),
            })

        logger.info(f"📊 Retrieved {len(transactions)} transactions for page {page}")
        return transactions, pagination_info

    def _format_full_transaction_details(self, data: Dict[str, Any]) -> str:
        """Format comprehensive transaction details for full detail mode.

        Orchestrates all field sections while maintaining single responsibility.
        Each section is handled by a dedicated helper method.

        Args:
            data: Transaction data dictionary from API response

        Returns:
            Formatted string with comprehensive transaction details
        """
        details = ""

        # Add each section using dedicated helper methods
        details += self._format_cost_breakdown(data)
        details += self._format_performance_metrics(data)
        details += self._format_attribution_details(data)
        details += self._format_session_tracking(data)
        details += self._format_quality_streaming(data)
        details += self._format_timestamps(data)

        return details

    def _format_cost_breakdown(self, data: Dict[str, Any]) -> str:
        """Format cost breakdown section with rate calculations."""
        cost_fields = ['inputTokenCost', 'outputTokenCost', 'totalCost']
        if not any(data.get(field) for field in cost_fields):
            return ""

        details = "- **Cost Breakdown**:\n"

        if data.get('inputTokenCost'):
            input_tokens = data.get('inputTokenCount', 0)
            input_cost = data.get('inputTokenCost')
            rate = input_cost / input_tokens if input_tokens > 0 else 0
            details += f"  - **Input Cost**: ${input_cost:.6f} ({input_tokens} tokens × ${rate:.8f}/token)\n"

        if data.get('outputTokenCost'):
            output_tokens = data.get('outputTokenCount', 0)
            output_cost = data.get('outputTokenCost')
            rate = output_cost / output_tokens if output_tokens > 0 else 0
            details += f"  - **Output Cost**: ${output_cost:.6f} ({output_tokens} tokens × ${rate:.8f}/token)\n"

        if data.get('totalCost'):
            details += f"  - **Total Cost**: ${data.get('totalCost'):.6f}\n"

        return details

    def _format_performance_metrics(self, data: Dict[str, Any]) -> str:
        """Format performance metrics section with proper units."""
        perf_fields = ['requestDuration', 'timeToFirstToken', 'tokensPerMinute']
        if not any(data.get(field) for field in perf_fields):
            return ""

        details = "- **Performance Metrics**:\n"

        if data.get('requestDuration'):
            details += f"  - **Duration**: {data.get('requestDuration')}ms\n"

        if data.get('timeToFirstToken'):
            details += f"  - **Time to First Token**: {data.get('timeToFirstToken')}ms\n"

        if data.get('tokensPerMinute'):
            details += f"  - **Tokens per Minute**: {data.get('tokensPerMinute')}\n"

        return details

    def _format_attribution_details(self, data: Dict[str, Any]) -> str:
        """Format attribution section with nested object safety and subscriber information."""
        # Check for both traditional attribution fields and subscriber fields
        attr_fields = ['taskType', 'agent', 'organization', 'product', 'subscriptionId']
        subscriber_fields = ['subscriberEmail', 'subscriberId', 'subscriberCredential', 'subscriber']

        if not any(data.get(field) for field in attr_fields + subscriber_fields):
            return ""

        details = "- **Attribution**:\n"

        if data.get('taskType'):
            details += f"  - **Task Type**: {data.get('taskType')}\n"

        if data.get('agent'):
            details += f"  - **Agent**: {data.get('agent')}\n"

        if data.get('organization'):
            org = data['organization']
            if isinstance(org, dict):
                org_display = f"{org.get('label', org.get('name', 'N/A'))} ({org.get('name', 'N/A')}, {org.get('id', 'N/A')})"
            else:
                org_display = str(org)
            details += f"  - **Organization**: {org_display}\n"

        if data.get('product'):
            prod = data['product']
            if isinstance(prod, dict):
                prod_display = f"{prod.get('label', prod.get('name', 'N/A'))} ({prod.get('name', 'N/A')}, {prod.get('id', 'N/A')})"
            else:
                prod_display = str(prod)
            details += f"  - **Product**: {prod_display}\n"

        if data.get('subscriptionId'):
            details += f"  - **Subscription**: {data.get('subscriptionId')}\n"

        # Add subscriber information to attribution section
        subscriber_added = False

        # Check for flat field format (actual API response structure)
        subscriber_email = data.get('subscriberEmail')
        subscriber_id = data.get('subscriberId')
        subscriber_credential = data.get('subscriberCredential')

        if subscriber_email:
            details += f"  - **Subscriber Email**: {subscriber_email}\n"
            subscriber_added = True

        if subscriber_id:
            details += f"  - **Subscriber ID**: {subscriber_id}\n"
            subscriber_added = True

        if subscriber_credential:
            if isinstance(subscriber_credential, dict):
                cred_name = subscriber_credential.get('label', subscriber_credential.get('name', 'N/A'))
            else:
                cred_name = subscriber_credential
            details += f"  - **Subscriber Credential Name**: {cred_name}\n"
            subscriber_added = True

        # Check for nested object format (documentation examples) if flat fields not found
        if not subscriber_added:
            nested_subscriber = data.get('subscriber')
            if nested_subscriber and isinstance(nested_subscriber, dict):
                if nested_subscriber.get('email'):
                    details += f"  - **Subscriber Email**: {nested_subscriber.get('email')}\n"

                if nested_subscriber.get('id'):
                    details += f"  - **Subscriber ID**: {nested_subscriber.get('id')}\n"

                if nested_subscriber.get('credential'):
                    cred = nested_subscriber['credential']
                    if isinstance(cred, dict):
                        cred_name = cred.get('name', 'N/A')
                        details += f"  - **Subscriber Credential Name**: {cred_name}\n"

        return details

    def _format_session_tracking(self, data: Dict[str, Any]) -> str:
        """Format session tracking section."""
        session_fields = ['traceId', 'operationType']
        if not any(data.get(field) for field in session_fields):
            return ""

        details = "- **Session Tracking**:\n"

        if data.get('traceId'):
            details += f"  - **Trace ID**: {data.get('traceId')}\n"

        if data.get('operationType'):
            details += f"  - **Operation Type**: {data.get('operationType')}\n"

        return details

    def _format_quality_streaming(self, data: Dict[str, Any]) -> str:
        """Format quality and streaming section with proper boolean formatting."""
        quality_fields = ['responseQualityScore', 'isStreamed', 'stopReason']
        if not any(data.get(field) is not None for field in quality_fields):
            return ""

        details = "- **Quality & Streaming**:\n"

        if data.get('responseQualityScore') is not None:
            details += f"  - **Quality Score**: {data.get('responseQualityScore')}\n"

        if data.get('isStreamed') is not None:
            details += f"  - **Streamed Response**: {str(data.get('isStreamed')).lower()}\n"

        if data.get('stopReason'):
            details += f"  - **Stop Reason**: {data.get('stopReason')}\n"

        return details

    def _format_timestamps(self, data: Dict[str, Any]) -> str:
        """Format timestamps section."""
        timestamp_fields = ['requestTime', 'responseTime', 'completionStartTime']
        if not any(data.get(field) for field in timestamp_fields):
            return ""

        details = "- **Timestamps**:\n"

        if data.get('requestTime'):
            details += f"  - **Request Time**: {data.get('requestTime')}\n"

        if data.get('responseTime'):
            details += f"  - **Response Time**: {data.get('responseTime')}\n"

        if data.get('completionStartTime'):
            details += f"  - **Completion Start**: {data.get('completionStartTime')}\n"

        return details

    def _format_subscriber_details(self, data: Dict[str, Any]) -> str:
        """Format subscriber details section with credential obfuscation.

        Handles both nested subscriber object and flat field formats from API.
        """
        details = ""

        # Check for flat field format (actual API response structure)
        subscriber_email = data.get('subscriberEmail')
        subscriber_id = data.get('subscriberId')
        subscriber_credential = data.get('subscriberCredential')

        # Check for nested object format (documentation examples)
        nested_subscriber = data.get('subscriber')

        # Use flat fields if available, otherwise try nested format
        if subscriber_email or subscriber_id or subscriber_credential:
            details = "- **Subscriber Attribution**:\n"

            if subscriber_email:
                details += f"  - **Email**: {subscriber_email}\n"

            if subscriber_id:
                details += f"  - **ID**: {subscriber_id}\n"

            if subscriber_credential:
                if isinstance(subscriber_credential, dict):
                    cred_name = subscriber_credential.get('label', subscriber_credential.get('name', 'N/A'))
                    # Security: Do NOT include credential value
                    details += f"  - **Credential Name**: {cred_name}\n"
                else:
                    details += f"  - **Credential Name**: {subscriber_credential}\n"

        elif nested_subscriber and isinstance(nested_subscriber, dict):
            details = "- **Subscriber Attribution**:\n"

            if nested_subscriber.get('email'):
                details += f"  - **Email**: {nested_subscriber.get('email')}\n"

            if nested_subscriber.get('id'):
                details += f"  - **ID**: {nested_subscriber.get('id')}\n"

            if nested_subscriber.get('credential'):
                cred = nested_subscriber['credential']
                if isinstance(cred, dict):
                    cred_name = cred.get('name', 'N/A')
                    # Security: Do NOT include credential value
                    details += f"  - **Credential Name**: {cred_name}\n"

        return details

    def _format_transaction_summary(self, transaction_data: Dict[str, Any], include_timestamp: bool = False) -> str:
        """Format core transaction fields for summary display.

        Extracts common summary formatting logic to eliminate code duplication
        between lookup_transactions and lookup_recent_transactions.

        Args:
            transaction_data: Transaction data dictionary from API response
            include_timestamp: Whether to include request time field

        Returns:
            Formatted string with core transaction fields
        """
        summary = ""
        summary += f"- **Model**: {transaction_data.get('model', 'N/A')}\n"
        summary += f"- **Provider**: {transaction_data.get('provider', 'N/A')}\n"
        summary += f"- **Input Tokens**: {transaction_data.get('inputTokenCount', 'N/A')}\n"
        summary += f"- **Output Tokens**: {transaction_data.get('outputTokenCount', 'N/A')}\n"

        if include_timestamp:
            summary += f"- **Request Time**: {transaction_data.get('requestTime', 'N/A')}\n"

        return summary

    async def _handle_get_capabilities(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Enhanced capabilities with UCM integration and preserved semantic guidance."""
        # Get UCM capabilities if available for API-verified data (with caching)
        ucm_capabilities = None
        if self.ucm_helper:
            try:
                logger.info("Metering Management: UCM helper available, fetching capabilities...")

                # Check cache for UCM capabilities
                ucm_cache_key = "ucm_metering_capabilities"
                cached_ucm = await response_cache.get_cached_response("ucm", ucm_cache_key)

                if cached_ucm is not None:
                    logger.debug("Using cached UCM capabilities")
                    ucm_capabilities = cached_ucm
                else:
                    ucm_capabilities = await self.ucm_helper.ucm.get_capabilities("metering")
                    # Cache UCM capabilities for 15 minutes
                    if ucm_capabilities:
                        await response_cache.set_cached_response(
                            "ucm", ucm_cache_key, ucm_capabilities, ttl_seconds=900
                        )

                logger.info(
                    f"Metering Management: Got UCM capabilities with "
                    f"{len(ucm_capabilities.get('providers', []))} providers"
                )
            except ToolError:
                # Re-raise ToolError exceptions without modification
                # This preserves helpful error messages with specific suggestions
                raise
            except Exception as e:
                logger.warning(f"Failed to get UCM metering capabilities, using static data: {e}")
        else:
            logger.info(
                "⚠️ Metering Management: No UCM helper available, using static capabilities"
            )

        # Build enhanced capabilities with UCM data and migration guidance
        capabilities_text = await self._build_enhanced_capabilities_text(ucm_capabilities)

        # Note: Migration guidance removed as legacy fields are no longer supported in MCP interface
        migration_guidance = ""

        return [TextContent(type="text", text=capabilities_text + migration_guidance)]

    async def _handle_analyze_recent_transactions(
        self, client: ReveniumClient, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Analyze recent transactions from Revenium reporting API to identify field mapping issues."""
        try:
            # Get parameters with validation
            limit = arguments.get("limit", 20)

            # ✅ PAGINATION VALIDATION: Enforce API limits with helpful guidance
            if limit > 100:
                logger.warning(
                    f"Requested limit {limit} exceeds maximum of 100, automatically capping to 100"
                )
                limit = 100

            # include_test_transactions = arguments.get("include_test_transactions", True)  # Reserved for future use

            # Delegate to the shared paginated fetch helper to avoid duplicating
            # request construction, filter application, and response-structure parsing.
            endpoint = get_endpoint_path("completions")  # Retained for report output below
            filters = _extract_completions_filters(arguments)
            transactions, _ = await self._fetch_recent_transactions_paginated(
                client, page=0, page_size=limit, filters=filters or None
            )
            total_found = len(transactions)

            if total_found == 0:
                return [
                    TextContent(
                        type="text",
                        text="📊 **No Recent Transactions**\n\nNo transactions found in the reporting API. Submit some test transactions first using `submit_ai_transaction()`.",
                    )
                ]

            # Analyze field mapping for each transaction
            field_analysis = {
                "total_transactions": total_found,
                "field_presence": {},
                "field_samples": {},
                "missing_fields": [],
                "unexpected_fields": [],
                "subscriber_analysis": {
                    "total_with_subscriber": 0,
                    "email_present": 0,
                    "id_present": 0,
                    "credential_present": 0,
                    "credential_name_present": 0,
                    "credential_value_present": 0,
                },
            }

            # Expected fields based on our implementation
            expected_fields = [
                "transactionId",
                "model",
                "provider",
                "inputTokenCount",
                "outputTokenCount",
                "durationMs",
                "organizationId",
                "taskType",
                "agent",
                "traceId",
                "taskId",
                "productId",
                "subscriptionId",
                "responseQualityScore",
                "isStreamed",
                "stopReason",
                "requestTime",
                "responseTime",
                "completionStartTime",
                "timeToFirstToken",
                "subscriber",
            ]

            # Analyze each transaction
            for i, tx in enumerate(transactions):
                # Track field presence
                for field in expected_fields:
                    if field not in field_analysis["field_presence"]:
                        field_analysis["field_presence"][field] = 0

                    if field in tx and tx[field] is not None:
                        field_analysis["field_presence"][field] += 1

                        # Store sample values (first 3 transactions)
                        if i < 3:
                            if field not in field_analysis["field_samples"]:
                                field_analysis["field_samples"][field] = []
                            field_analysis["field_samples"][field].append(str(tx[field])[:100])

                # Analyze subscriber object specifically
                if "subscriber" in tx and tx["subscriber"] is not None:
                    field_analysis["subscriber_analysis"]["total_with_subscriber"] += 1
                    subscriber = tx["subscriber"]

                    if isinstance(subscriber, dict):
                        if "email" in subscriber and subscriber["email"]:
                            field_analysis["subscriber_analysis"]["email_present"] += 1
                        if "id" in subscriber and subscriber["id"]:
                            field_analysis["subscriber_analysis"]["id_present"] += 1
                        if "credential" in subscriber and subscriber["credential"]:
                            field_analysis["subscriber_analysis"]["credential_present"] += 1
                            credential = subscriber["credential"]
                            if isinstance(credential, dict):
                                if "name" in credential and credential["name"]:
                                    field_analysis["subscriber_analysis"][
                                        "credential_name_present"
                                    ] += 1
                                if "value" in credential and credential["value"]:
                                    field_analysis["subscriber_analysis"][
                                        "credential_value_present"
                                    ] += 1

                # Check for unexpected fields
                for field in tx.keys():
                    if (
                        field not in expected_fields
                        and field not in field_analysis["unexpected_fields"]
                    ):
                        field_analysis["unexpected_fields"].append(field)

            # Identify missing fields
            for field in expected_fields:
                if field_analysis["field_presence"].get(field, 0) == 0:
                    field_analysis["missing_fields"].append(field)

            # Build comprehensive analysis report
            report = "# **Recent Transactions Field Analysis**\n\n"
            report += f"**Analysis Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
            report += f"**Transactions Analyzed:** {total_found}\n"
            report += f"**API Endpoint:** `{endpoint}`\n\n"

            # Field presence summary
            report += "## **Field Presence Summary**\n\n"
            report += "| **Field** | **Present** | **Missing** | **Percentage** |\n"
            report += "|-----------|-------------|-------------|----------------|\n"

            for field in expected_fields:
                present = field_analysis["field_presence"].get(field, 0)
                missing = total_found - present
                percentage = (present / total_found * 100) if total_found > 0 else 0
                status_icon = "✅" if percentage > 80 else "⚠️" if percentage > 0 else "❌"
                report += (
                    f"| {status_icon} `{field}` | {present} | {missing} | {percentage:.1f}% |\n"
                )

            # Subscriber analysis
            sub_analysis = field_analysis["subscriber_analysis"]
            report += "\n## **👤 Subscriber Object Analysis**\n\n"
            report += f"- **Total transactions with subscriber object:** {sub_analysis['total_with_subscriber']}/{total_found}\n"
            report += f"- **Subscriber.email present:** {sub_analysis['email_present']}/{sub_analysis['total_with_subscriber']} ({(sub_analysis['email_present']/max(sub_analysis['total_with_subscriber'], 1)*100):.1f}%)\n"
            report += f"- **Subscriber.id present:** {sub_analysis['id_present']}/{sub_analysis['total_with_subscriber']} ({(sub_analysis['id_present']/max(sub_analysis['total_with_subscriber'], 1)*100):.1f}%)\n"
            report += f"- **Subscriber.credential present:** {sub_analysis['credential_present']}/{sub_analysis['total_with_subscriber']} ({(sub_analysis['credential_present']/max(sub_analysis['total_with_subscriber'], 1)*100):.1f}%)\n"
            report += f"- **Credential.name present:** {sub_analysis['credential_name_present']}/{sub_analysis['credential_present']} ({(sub_analysis['credential_name_present']/max(sub_analysis['credential_present'], 1)*100):.1f}%)\n"
            report += f"- **Credential.value present:** {sub_analysis['credential_value_present']}/{sub_analysis['credential_present']} ({(sub_analysis['credential_value_present']/max(sub_analysis['credential_present'], 1)*100):.1f}%)\n"

            # Missing fields
            if field_analysis["missing_fields"]:
                report += "\n## **❌ Completely Missing Fields**\n\n"
                for field in field_analysis["missing_fields"]:
                    report += f"- `{field}`: Not found in any transaction\n"

            # Unexpected fields
            if field_analysis["unexpected_fields"]:
                report += "\n## **🔍 Unexpected Fields Found**\n\n"
                for field in field_analysis["unexpected_fields"]:
                    report += f"- `{field}`: Found in API response but not expected\n"

            # Sample data
            if field_analysis["field_samples"]:
                report += "\n## **📝 Sample Field Values**\n\n"
                for field, samples in field_analysis["field_samples"].items():
                    if samples:
                        report += f"**{field}:**\n"
                        for i, sample in enumerate(samples[:3]):
                            report += f"  {i+1}. `{sample}`\n"
                        report += "\n"

            # Recommendations
            report += "\n## **Recommendations**\n\n"

            if sub_analysis["email_present"] == 0 and sub_analysis["total_with_subscriber"] > 0:
                report += (
                    "⚠️ CRITICAL: Subscriber email field is not being stored in any transactions!\n"
                )
                report += "- Check backend processing of subscriber.email field\n"
                report += "- Verify API endpoint expects nested subscriber structure\n"
                report += "- Review database schema for subscriber email storage\n\n"

            if (
                sub_analysis["credential_present"] == 0
                and sub_analysis["total_with_subscriber"] > 0
            ):
                report += "⚠️ **WARNING**: Subscriber credential object is not being stored\n"
                report += "- Verify backend handles nested credential structure\n"
                report += "- Check if credential data is being filtered for security\n\n"

            missing_critical = [
                f
                for f in ["model", "provider", "inputTokenCount", "outputTokenCount"]
                if f in field_analysis["missing_fields"]
            ]
            if missing_critical:
                report += f"⚠️ CRITICAL: Core fields missing: {', '.join(missing_critical)}\n"
                report += "- These are required fields for billing calculations\n"
                report += "- Check API endpoint and field mapping\n\n"

            report += "**Next Steps:**\n"
            report += "1. Focus on subscriber.email field mapping issue\n"
            report += "2. Verify backend API endpoint structure\n"
            report += "3. Check database schema for nested object support\n"
            report += "4. Review API logs for payload structure\n"

            return [TextContent(type="text", text=report)]

        except Exception as e:
            logger.error(f"Error analyzing recent transactions: {e}")
            return [
                TextContent(
                    type="text",
                    text=f"❌ **Analysis Failed**\n\nError querying recent transactions: {str(e)}\n\nThis could indicate:\n• API connectivity issues\n• Permission problems\n• Different endpoint structure\n• Authentication errors",
                )
            ]

    async def _build_enhanced_capabilities_text(
        self, ucm_capabilities: Optional[Dict[str, Any]]
    ) -> str:
        """Build concise capabilities overview with navigation to detailed help."""
        return await self._build_concise_capabilities_overview(ucm_capabilities)

    async def _build_concise_capabilities_overview(
        self, ucm_capabilities: Optional[Dict[str, Any]]
    ) -> str:
        """Build concise capabilities overview with navigation to detailed help.

        Extracts core content from existing response while targeting <1,500 tokens.
        Preserves essential text and provides navigation to detailed capabilities.
        """
        text = """# **AI Metering Management Capabilities**

## **AI METERING OVERVIEW**

### **What AI Metering Is**
- **Usage tracking** for AI model consumption (tokens, requests, costs)
- **Billing foundation** that connects AI usage to customer charges
- **Attribution system** for enterprise usage tracking and cost allocation

### **Key Concepts**
- **Transactions** represent individual AI API calls with usage data
- **Verification** ensures submitted data appears in reporting systems
- **Attribution** connects usage to customers, products, and billing
- **Validation** prevents data quality issues and billing errors

## **Quick Start Commands**

### **Submit AI Usage**
```bash
submit_ai_transaction(model="<model>", provider="<provider>", input_tokens=1500, output_tokens=800, duration_ms=2500)
validate(model="<model>", provider="<provider>", input_tokens=3000, output_tokens=1200, duration_ms=5000)
```

### **Lookup & Track**
```bash
lookup_transactions(transaction_ids=["tx_abc123"])             # Find specific transactions by ID
lookup_recent_transactions()                                   # Browse recent transactions (no IDs needed)
lookup_recent_transactions(page=1, page_size=10)              # Get specific page of recent transactions
get_transaction_status(transaction_id="tx_abc123")             # Check local transaction status
```
## **Detailed Capabilities**

For guidance on specific workflows, use these focused capability actions:

### **Submission & Validation**
- **`get_submission_capabilities`** - Complete field specifications, validation rules, and submission examples
- **`get_validation_capabilities`** - Business rules, critical warnings, and field validation requirements

### **Transaction Management**
- **`get_lookup_capabilities`** - Transaction lookup methods, detail control, and pagination optimization
- **`get_field_documentation`** - Complete field specifications and compatibility matrix

### **Integration Support**
- **`get_integration_capabilities`** - API integration guide with code examples for Python and JavaScript
- **`get_business_rules`** - Detailed validation requirements and critical warnings

### **Quick Navigation Examples**
```bash
# For transaction submission guidance
get_submission_capabilities()

# For transaction lookup overview
get_lookup_capabilities()

# For assistance integrating directly to Revenium's API
get_integration_capabilities()

# For complete field documentation
get_field_documentation()
```"""

        # Add UCM-enhanced providers if available (condensed)
        if ucm_capabilities and "providers" in ucm_capabilities:
            text += "\n\n## **Supported Providers**\n"
            providers = ucm_capabilities["providers"][:5]  # Show first 5 providers
            for provider in providers:
                text += f"- **{provider}**\n"
            if len(ucm_capabilities["providers"]) > 5:
                text += f"- ... and {len(ucm_capabilities['providers']) - 5} more\n"
        else:
            # Provide actionable guidance for users
            text += "\n\n## **Supported Providers**\n"
            text += "View available AI providers and their supported models:\n\n"
            text += "**Commands:**\n"
            text += '- List all providers: `manage_metering(action="get_supported_providers")`\n'
            text += '- Search by provider: `manage_metering(action="search_ai_models", query="anthropic")`\n'

        # Add UCM-enhanced models if available (condensed)
        if ucm_capabilities and "models" in ucm_capabilities:
            text += "\n\n## **Supported Models**\n"
            models = ucm_capabilities["models"]
            provider_count = 0
            for provider, model_list in models.items():
                if provider_count >= 2:  # Show only first 2 providers
                    break
                text += f"### {provider}\n"
                for model in model_list[:3]:  # Show first 3 models per provider
                    text += f"- **{model}**\n"
                if len(model_list) > 3:
                    text += f"- ... and {len(model_list) - 3} more\n"
                provider_count += 1
            if len(models) > 2:
                text += f"- ... and {len(models) - 2} more providers\n"
        else:
            # Provide actionable guidance for users
            text += "\n\n## **Supported Models**\n"
            text += "View available AI models and their pricing information:\n\n"
            text += "**Commands:**\n"
            text += '- List all models: `manage_metering(action="list_ai_models")`\n'

        text += "\n\n## **Next Steps**\n"
        text += "1. Use `submit_ai_transaction(...)` to track AI usage\n"
        text += "2. Use `lookup_transactions()` to find specific transactions by ID\n"
        text += "3. Use `lookup_recent_transactions()` to browse recent transactions without IDs\n"
        text += "4. Use detailed capability actions above for specific guidance\n"
        text += "5. Review examples with `get_examples()`"

        return text

    async def _build_submission_capabilities_content(
        self, ucm_capabilities: Optional[Dict[str, Any]]
    ) -> str:
        """Build AI submission capabilities content

        Extracts and organizes content for submission capabilities:
        Required/Optional Fields, Field Compatibility Matrix, Subscriber Object Structure,
        basic submission examples, validation rules.
        """
        text = """# **AI Transaction Submission Capabilities**

## **Required Fields**
- `model` (required) - AI model identifier
- `provider` (required) - AI provider name
- `input_tokens` (required) - Number of input tokens
- `output_tokens` (required) - Number of output tokens
- `duration_ms` (required) - Request duration in milliseconds

## **Optional Fields**
- `organization_id` (optional) - Customer organization identifier
- `task_type` (optional) - Type of AI operation
- `agent` (optional) - AI agent identifier
- `trace_id` (optional) - Session/conversation tracking ID
- `product_id` (optional) - Product using the AI service
- `subscription_id` (optional) - Subscription reference
- `response_quality_score` (optional) - Quality score 0.0-1.0
- `stop_reason` (optional) - Completion stop reason
- `error_reason` (optional) - Error description if request failed
- `is_streamed` (optional) - Whether response was streamed
- `subscriber` (object) - Subscriber information with nested structure

### **Field Validation Rules**

#### **Required Fields**
- `model`: Non-empty string, must be validated model/provider pair using validate_model_provider() action
- `provider`: Same validation as `model`
- `input_tokens`
- `output_tokens`
- `duration_ms`

#### **Optional String Fields**
- `organization_id`, `task_type`, `agent`, `stop_reason`, `trace_id`, `product_id`, `subscription_id`, `error_reason`:
  - Type: String
  - Length: 1-500 characters
  - Invalid chars: `<`, `>`, `"`, `'`, `&`
- `response_quality_score`: Float between 0.0 and 1.0 (inclusive)
- `is_streamed`: Boolean (true/false, accepts string conversion)
- `time_to_first_token`: Positive integer in milliseconds (≤ 60,000ms)

#### **Timestamp Fields**
- `request_time`, `response_time`, `completion_start_time`:
  - Format: ISO UTC with milliseconds
  - Example: `"2025-06-16T15:30:45.123Z"`
  - Must end with 'Z' for UTC timezone
  - Auto-fallback: Invalid formats use current system time
```

## **Quick Start Submission Examples**

### **Submit AI Usage**
```bash
submit_ai_transaction(model="<model>", provider="<provider>", input_tokens=1500, output_tokens=800, duration_ms=2500)
validate(model="<model>", provider="<provider>", input_tokens=3000, output_tokens=1200, duration_ms=5000)
```

### **Complete Example**
```json
{
  "model": "gpt-4o", "provider": "openai",
  "input_tokens": 3247, "output_tokens": 1856, "duration_ms": 4250,
  "organization_id": "stratton-oakmont-financial",
  "task_type": "portfolio_risk_analysis",
  "agent": "QuantAnalyst_AI_v2.1",
  "subscriber": {
    "id": "sub_so_trading_001",
    "email": "trading.desk@strattonoakmont.com",
    "credential": {"name": "api_key_trading_platform"}
  },
  "product_id": "trading_platform_v2",
  "subscription_id": "sub_enterprise_trading",
  "response_quality_score": 0.94
}
```

## **Next Steps**
1. Use `submit_ai_transaction(...)` to track AI usage
2. Validate fields using `validate()` before submission
3. Add customer attribution fields for enriched analytics or usage-based billing
4. Review examples with `get_examples()`"""

        return text

    async def _build_lookup_capabilities_content(
        self, ucm_capabilities: Optional[Dict[str, Any]]
    ) -> str:
        """Build lookup capabilities content with preserved text from original implementation.

        Extracts and organizes content for lookup capabilities:
        Transaction Lookup with Detail Control, Enhanced Auto-Pagination Guidelines,
        performance characteristics, lookup examples and best practices.
        """
        text = """# **Metering Transaction Lookup Capabilities**

## **Lookup & Track**
```bash
lookup_transactions(transaction_ids=["tx_abc123"])             # Find specific transactions by ID
lookup_transactions(transaction_ids=["tx_abc123", "tx_def456"]) # Batch lookup by IDs
lookup_recent_transactions()                                   # Browse recent transactions (no IDs needed)
lookup_recent_transactions(page=1, page_size=10)              # Get specific page of recent transactions
get_transaction_status(transaction_id="tx_abc123")             # Check local transaction status
get_agent_summary()                                            # Get tool overview
```

## **Transaction Lookup with Detail Control**
Summary: return_transaction_data accepts values of no, summary, or full and returns
increasingly verbose responses for the respective choices.

```json
{
  "action": "lookup_transactions",
  "transaction_ids": ["tx_abc123"],
  "return_transaction_data": "no"
}
```
*This example returns only verification status (✅ Found/❌ Not Found)*

## **Pagination**

- **Revenium API supports up to 1,000 transactions per request**
- **Auto-pagination searches up to 5,000 transactions by default**

### **Unified Lookup Best Practices**
```bash
# OPTIMAL: Single transaction lookup
lookup_transactions(transaction_ids=["tx_abc123"])       # Automatically optimized

# BATCH: Multiple transaction lookup
lookup_transactions(transaction_ids=["tx_abc", "tx_de"]) # Efficient batch processing

# CUSTOM: Lookup with custom settings
lookup_transactions(transaction_ids=["tx_abc123"], max_retries=5)
```
## **Search Options**
- `search_page_range` (integer or array) - Pages to search for lookup_transactions:
  - Integer: Search pages 0 to N-1 (e.g., 5 = first 5 pages)
  - Array: Search specific range [start, end] (e.g., [10, 20] = pages 10-20)
  - Default: 5 pages (5,000 transactions)
- `page_size` (integer) - Transactions per API call (1-1000):
- `early_termination` (boolean) - Stop searching when target transaction found:
  - true: Stop immediately when transaction found (faster)
  - false: Search all specified pages (complete coverage)
  - Default: true (for lookup_transactions)
- `return_transaction_data` (string|boolean) - Transaction data detail level:
  - "no": Show only verification status (✅ Found/❌ Not Found) - default
  - "summary": Show core fields (Model, Provider, Input/Output Tokens)
  - "full": Show comprehensive details including metadata, costs, attribution
  - Legacy boolean support: true="summary", false="no"
- `wait_seconds` (integer) - Wait time for transaction verification (0-300):
  - Default: 30 seconds

### **Quick Recent Transaction Lookup**
```json
{
  "action": "lookup_transactions",
  "transaction_ids": ["tx_abc123def456"],
  "page_size": 100,
  "search_page_range": 5
}
```
### **Deep Historical Transaction Search**
```json
{
  "action": "lookup_transactions",
  "transaction_ids": ["tx_abc123def456"],
  "page_size": 1000,
  "search_page_range": [20, 50],
  "early_termination": true
}
```
*Searches pages 20-50 (31,000 transactions) for historical lookup with early termination*

## **Recent Transactions Lookup (No IDs Required)**
Browse recent transactions without needing specific transaction IDs. Perfect for discovery and monitoring.

### **Basic Recent Transaction Lookup**
```json
{
  "action": "lookup_recent_transactions"
}
```
*Gets the first 20 recent transactions with summary details*

### **Paginated Recent Transaction Lookup**
```json
{
  "action": "lookup_recent_transactions",
  "page": 1,
  "page_size": 10
}
```
*Gets the second page with 10 transactions per page*

### **Detailed Recent Transaction Lookup**
```json
{
  "action": "lookup_recent_transactions",
  "page_size": 5,
  "return_transaction_data": "full"
}
```
*Gets 5 recent transactions with comprehensive details*

### **Parameters for Recent Transactions**
- `page` (optional): Page number (0-based, default: 0)
- `page_size` (optional): Transactions per page (1-50, default: 20)
- `return_transaction_data` (optional): Detail level - "no", "summary", "full" (default: "summary")

## **Next Steps**
1. Use `lookup_transactions()` to find and verify transactions
2. Optimize search parameters based on transaction age and volume
3. Use `return_transaction_data` parameter to control detail level ("no", "summary", "full")
4. Monitor performance characteristics for large-scale lookups"""

        return text

    async def _build_integration_capabilities_content(
        self, ucm_capabilities: Optional[Dict[str, Any]]
    ) -> str:
        """Build integration capabilities content with preserved text from original implementation.

        Extracts and organizes content for integration capabilities:
        Integration Support section, technical implementation actions, supported languages,
        integration features, quick start guidance.
        """
        text = """# **API Integration Capabilities**

## **Integration Support**

### **Technical Implementation Actions**
Complete technical details for building API integrations with Revenium's AI metering API:

- **`get_api_endpoints`** - API endpoint URLs, HTTP methods, and request formats
- **`get_authentication_details`** - Authentication headers, environment variables, and security practices
- **`get_response_formats`** - Success/error response schemas and status codes
- **`get_integration_config`** - Environment setup guidance and configuration examples
- **`get_rate_limits`** - Rate limiting information and retry strategies
- **`get_integration_guide`** - Step-by-step integration guidance with working code examples

### **Supported Languages**
- **Python** (primary)
- **JavaScript**

### **Integration Features**
- **Production-ready code templates** that work without modification

**💡 Quick Start**: Use `get_integration_guide(language="python")` for complete implementation guidance

## **Environment Setup**

### **Authentication Configuration**
```bash
# Create .env file with required variables
cat > .env << EOF
REVENIUM_API_KEY="your_api_key_here"
REVENIUM_BASE_URL="https://api.revenium.ai"  # Optional, defaults to production
EOF
```

### **Python Integration Example**
```python
import asyncio
import aiohttp
import os
from typing import Dict, Any

from ..constants import DEFAULT_BASE_URL

class ReveniumMeteringClient:
    def __init__(self):
        self.api_key = os.getenv("REVENIUM_API_KEY")
        self.base_url = os.getenv("REVENIUM_BASE_URL", DEFAULT_BASE_URL)

    async def submit_transaction(self, transaction_data: Dict[str, Any]) -> Dict[str, Any]:
        # api.revenium.ai uses x-api-key; Bearer is for app.revenium.ai/api/v2
        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/meter/v2/ai/completions",
                json=transaction_data,
                headers=headers
            ) as response:
                return await response.json()

# Usage example
async def main():
    client = ReveniumMeteringClient()

    transaction = {
        "model": "gpt-4o",
        "provider": "openai",
        "inputTokenCount": 1500,
        "outputTokenCount": 800,
        "requestDuration": 2500,
        "requestTime": "2024-01-01T00:00:00Z",
        "completionStartTime": "2024-01-01T00:00:01Z",
        "responseTime": "2024-01-01T00:00:02Z",
        "stopReason": "stop",
        "organizationId": "your-org-id",
        "taskType": "text_generation"
    }

    result = await client.submit_transaction(transaction)
    print(f"Transaction submitted: {result}")

if __name__ == "__main__":
    asyncio.run(main())
```

### **JavaScript Integration Example**
```javascript
const axios = require('axios');

class ReveniumMeteringClient {
    constructor() {
        this.apiKey = process.env.REVENIUM_API_KEY;
        this.baseUrl = process.env.REVENIUM_BASE_URL || 'https://api.revenium.ai';
    }

    async submitTransaction(transactionData) {
        // api.revenium.ai uses x-api-key; Bearer is for app.revenium.ai/api/v2
        const headers = {
            'x-api-key': this.apiKey,
            'Content-Type': 'application/json'
        };

        try {
            const response = await axios.post(
                `${this.baseUrl}/meter/v2/ai/completions`,
                transactionData,
                { headers }
            );
            return response.data;
        } catch (error) {
            console.error('Transaction submission failed:', error.response?.data || error.message);
            throw error;
        }
    }
}

// Usage example
async function main() {
    const client = new ReveniumMeteringClient();

    const transaction = {
        model: 'gpt-4o',
        provider: 'openai',
        inputTokenCount: 1500,
        outputTokenCount: 800,
        requestDuration: 2500,
        requestTime: '2024-01-01T00:00:00Z',
        completionStartTime: '2024-01-01T00:00:01Z',
        responseTime: '2024-01-01T00:00:02Z',
        stopReason: 'stop',
        organizationId: 'your-org-id',
        taskType: 'text_generation'
    };

    try {
        const result = await client.submitTransaction(transaction);
        console.log('Transaction submitted:', result);
    } catch (error) {
        console.error('Failed to submit transaction:', error);
    }
}

main();
```

## **Next Steps**
1. Use `get_integration_guide(language="python")` for complete implementation
2. Set up environment variables for authentication
3. Implement error handling and retry logic
4. Test integration with `validate()` action"""

        return text

    async def _build_validation_capabilities_content(
        self, ucm_capabilities: Optional[Dict[str, Any]]
    ) -> str:
        """Build validation capabilities content with preserved text from original implementation.

        Extracts and organizes content for validation capabilities (600-800 tokens):
        CRITICAL VALIDATION REQUIREMENTS, Business Rules section, Model/Provider validation,
        field validation rules.
        """
        text = """# **Field Validation & Data Format Requirements**

## **Field Validation Rules**

### **Required Fields**
- `model`: String, AI model identifier (max 200 chars)
- `provider`: String, AI provider name (max 200 chars)
- `input_tokens`: Integer (> 0, ≤ 10,000,000)
- `output_tokens`: Integer (> 0, ≤ 10,000,000)
- `duration_ms`: Integer (> 0, ≤ 10,000,000)

### **Optional Fields**
- **String fields**: `organization_id`, `task_type`, `agent`, `trace_id`, `product_id`, `subscription_id`, `stop_reason`
  - Length: 1-500 chars, no `<>\"'&`
- **Numeric fields**: `response_quality_score` (float 0.0-1.0), `time_to_first_token` (integer ≤ 60,000ms)
- **Boolean fields**: `is_streamed` (true/false, string conversion supported)

### **Timestamp Format**
- Format: ISO UTC with milliseconds `"2025-06-16T15:30:45.123Z"`
- Fields: `request_time`, `response_time`, `completion_start_time`
- Auto-populated if not provided

### **Subscriber Object**
```json
"subscriber": {
  "id": "string (optional)",
  "email": "string (optional)",
  "credential": {"name": "string", "value": "string (max 500 chars)"}
}
```

## **Validation Commands**

### **Pre-Submission**
```bash
# Validate complete transaction
validate(model="gpt-4o", provider="openai", input_tokens=3000, output_tokens=1200, duration_ms=5000)

# Validate model/provider combination
validate_model_provider(model="gpt-4o", provider="openai")
```

### **Discovery**
```bash
search_ai_models(query="gpt")          # Search models
get_supported_providers()              # List providers
list_ai_models()                       # List all models
```

## **Common Validation Errors**

### **Field Errors**
- **Token Counts**: Must be positive integers > 0
- **Duration**: Must be positive integer milliseconds > 0
- **String Format**: Remove `<>\"'&` characters
- **Timestamp**: Use ISO UTC format with 'Z'
- **Type Mismatch**: Ensure correct data types
- **Range**: Check limits (tokens ≤ 10M, quality ≤ 1.0)

## **Best Practices**
1. Use `validate()` before submission
2. Implement client-side validation
3. Handle errors gracefully with retry logic
4. Monitor error patterns for quality improvements

**Note**: For critical model/provider business rules, see `get_business_rules`"""

        return text

    async def _build_field_documentation_content(
        self, ucm_capabilities: Optional[Dict[str, Any]]
    ) -> str:
        """Build field documentation content with preserved text from original implementation.

        Extracts and organizes content for field documentation (1,000-1,200 tokens):
        Complete field specifications, timestamp fields documentation, pagination control fields,
        detailed field compatibility matrix.
        """
        text = """# **Complete Field Documentation**

## **Required Fields**
- `model` (string) - AI model identifier (max 200 chars)
- `provider` (string) - AI provider name (max 200 chars)
- `input_tokens` (integer) - Input tokens (> 0, ≤ 10,000,000)
- `output_tokens` (integer) - Output tokens (> 0, ≤ 10,000,000)
- `duration_ms` (integer) - Duration in milliseconds (> 0, ≤ 10,000,000)

## **Optional Fields**
- `organization_id`, `task_type`, `agent`, `trace_id`, `product_id`, `subscription_id`, `stop_reason`, `error_reason` (string, 1-500 chars, no `< > " ' &`)
- `response_quality_score` (float, 0.0-1.0)
- `is_streamed` (boolean)
- `time_to_first_token` (integer, ≤ 60,000ms)

## **Subscriber Object**
```json
"subscriber": {
  "id": "string (optional)",
  "email": "string (optional)",
  "credential": {"name": "string", "value": "string (max 500 chars)"}
}
```

## **Timestamp Fields**
- `request_time`, `response_time`, `completion_start_time` (string)
- Format: `"2025-06-16T15:30:45.123Z"` (ISO UTC with 'Z')
- Auto-populated if not provided

## **Pagination Control**
- `search_page_range` (integer/array) - Pages to search (default: 5)
- `page_size` (integer) - Transactions per call (1-1000, default: 1000)
- `early_termination` (boolean) - Stop when found (default: true)
- `return_transaction_data` (string|boolean) - Detail level: "no" (default), "summary", "full"
- `wait_seconds` (integer) - Wait time (0-300, default: 30)

## **Field Groups**
- **Basic**: `model`, `provider`, `input_tokens`, `output_tokens`, `duration_ms`
- **Attribution**: + `organization_id`, `task_type`, `agent`
- **Quality**: + `response_quality_score`, `is_streamed`, `stop_reason`, `error_reason`
- **Session**: + `trace_id`
- **Billing**: + `product_id`, `subscription_id`, `subscriber`
- **Timestamps**: + `request_time`, `response_time`, `completion_start_time`

## **Validation**
- String fields: 1-500 chars, no `<>\"'&`
- Tokens/duration: Positive integers
- Quality score: 0.0-1.0 float
- Timestamps: ISO UTC with 'Z'

Use `validate()` before submission."""

        return text

    async def _build_business_rules_content(
        self, ucm_capabilities: Optional[Dict[str, Any]]
    ) -> str:
        """Build business rules content with preserved text from original implementation.

        Extracts and organizes content for business rules (800-1,000 tokens):
        Business rules, critical warnings, validation requirements,
        model/provider compatibility requirements.
        """
        text = """# **Business Rules & Critical Requirements**

## **CRITICAL AI MODEL VALIDATION PROCESS**

### **Model/Provider Validation**
- **CRITICAL**: Model and provider MUST match supported combinations from AI models endpoint
- **CONSEQUENCE**: Unsupported combinations result in inaccurate cost calculations in Revenium
- **REQUIREMENT**: Always verify model/provider support before sending transactions

### **Verification Process**
1. Search models: `search_ai_models(query="gpt")` or `search_ai_models(query="anthropic")`
2. List providers: `get_supported_providers()`
3. Validate: `validate_model_provider(model="gpt-4o", provider="openai")`
4. Submit: `submit_ai_transaction(model="gpt-4o", provider="openai", ...)`

## **Business Rules**
- Follow AI Model Validation Process above
- All token counts must be positive integers
- Duration must be in milliseconds (positive integer)
- Attribution fields enable customer billing and cost allocation
- Transaction verification ensures data integrity

## **Field Validation**
- **Required**: `model`, `provider`, `input_tokens`, `output_tokens`, `duration_ms`
- **String fields**: 1-500 chars, no `<>\"'&`
- **Token counts**: Positive integers (> 0, ≤ 10,000,000)
- **Duration**: Positive integer milliseconds (> 0, ≤ 10,000,000)
- **Quality score**: Float 0.0-1.0
- **Timestamps**: ISO UTC with 'Z' (e.g., "2025-06-16T15:30:45.123Z")
- **Booleans**: true/false (string conversion supported)

## **Next Steps**
1. Use `validate_model_provider()` to verify combinations
2. Use `validate()` to check transaction data before submission
3. Implement validation in your application
4. Monitor validation errors and adjust accordingly"""

        return text

    # AI Models Discovery Action Handlers
    async def _handle_list_ai_models(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle list AI models action."""
        try:
            # BACK-1313: coerce page/size before they reach arithmetic; raises
            # structured ToolError on bad input instead of letting a Python
            # TypeError leak through (audit finding C.4).
            arguments = validate_pagination_params(arguments, action="list_ai_models")
            client = ReveniumClient()
            page = arguments.get("page", 0)
            size = arguments.get("size", 20)

            # Get AI models from API
            response = await client.get_ai_models(page=page, size=size)

            if "_embedded" in response and "aIModelResourceList" in response["_embedded"]:
                models = response["_embedded"]["aIModelResourceList"]
                page_info = response.get("page", {})
                total_models = page_info.get("totalElements", len(models))

                # Group models by provider
                providers = {}
                for model in models:
                    provider = model.get("provider", "Unknown")
                    if provider not in providers:
                        providers[provider] = []
                    providers[provider].append(model)

                # Build response text
                text = f"# **AI Models List** (Page {page + 1})\n\n"
                text += f"**Total Models Found**: {total_models}\n"
                text += f"**Providers**: {len(providers)}\n\n"

                for provider, provider_models in providers.items():
                    text += f"## **{provider}** ({len(provider_models)} models)\n"
                    for model in provider_models[:5]:  # Show first 5 models per provider
                        name = model.get("name", "Unknown")
                        input_cost = model.get("inputCostPerToken", "N/A")
                        output_cost = model.get("outputCostPerToken", "N/A")
                        text += f"- **{name}** (Input: ${input_cost}/token, Output: ${output_cost}/token)\n"
                    if len(provider_models) > 5:
                        text += f"- ... and {len(provider_models) - 5} more models\n"
                    text += "\n"

                text += '**💡 Tip**: Use `search_ai_models(query="<provider>")` to find specific models\n'
                text += '**💡 Tip**: Use `get_ai_model(model_id="<id>")` for detailed model information'

                return [TextContent(type="text", text=text)]
            else:
                return [
                    TextContent(
                        type="text",
                        text="❌ **No AI models found**\n\nThe API response did not contain any models.",
                    )
                ]

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Error listing AI models: {e}")
            from ..common.error_handling import format_error_response

            return format_error_response(e, "listing AI models")

    async def _handle_search_ai_models(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle search AI models action using list and filter approach."""
        try:
            # BACK-1313: coerce page/size at the action boundary (audit C.4).
            arguments = validate_pagination_params(arguments, action="search_ai_models")
            query = arguments.get("query")
            if not query:
                raise create_structured_missing_parameter_error(
                    parameter_name="query",
                    action="search_ai_models",
                    examples={
                        "usage": 'search_ai_models(query="<search_term>")',
                        "examples": [
                            'search_ai_models(query="gpt")',
                            'search_ai_models(query="anthropic")',
                        ],
                        "provider_searches": [
                            'search_ai_models(query="openai")',
                            'search_ai_models(query="anthropic")',
                        ],
                        "model_searches": [
                            'search_ai_models(query="gpt-4")',
                            'search_ai_models(query="claude")',
                        ],
                    },
                )

            client = ReveniumClient()
            page = arguments.get("page", 0)
            size = arguments.get("size", 20)

            response = await client.search_ai_models(query=query, page=page, size=size)

            if "_embedded" in response and "aIModelResourceList" in response["_embedded"]:
                models = response["_embedded"]["aIModelResourceList"]
                page_info = response.get("page", {})
                total_elements = page_info.get("totalElements", len(models))
                total_pages = page_info.get("totalPages", 1)

                if not models:
                    return [
                        TextContent(
                            type="text",
                            text=f'No models found for query: "{query}"\n\n'
                            "**Suggestions**:\n"
                            "- Try a broader search term\n"
                            '- Search by provider name (e.g., "openai", "anthropic")\n'
                            "- Use `list_ai_models()` to see all available models",
                        )
                    ]

                text = "# **AI Models Search Results**\n\n"
                text += f'**Query**: "{query}"\n'
                text += f"**Results Found**: {total_elements} total ({len(models)} on page {page + 1} of {total_pages})\n\n"

                for model in models:
                    name = model.get("name", "Unknown")
                    provider = model.get("provider", "Unknown")
                    model_id = model.get("id", "Unknown")
                    input_cost = model.get("inputCostPerToken", "N/A")
                    output_cost = model.get("outputCostPerToken", "N/A")

                    text += f"## **{name}** ({provider})\n"
                    text += f"- **ID**: {model_id}\n"
                    text += f"- **Input Cost**: ${input_cost}/token\n"
                    text += f"- **Output Cost**: ${output_cost}/token\n"

                    features = []
                    if model.get("supportFunctionCalling"):
                        features.append("Function Calling")
                    if model.get("supportsVision"):
                        features.append("Vision")
                    if model.get("supportsPromptCaching"):
                        features.append("Prompt Caching")

                    if features:
                        text += f"- **Features**: {', '.join(features)}\n"
                    text += "\n"

                text += (
                    '**Tip**: Use `get_ai_model(model_id="<id>")` for complete model details'
                )

                return [TextContent(type="text", text=text)]
            else:
                return [
                    TextContent(
                        type="text",
                        text=f'No results found for query: "{query}"',
                    )
                ]

        except Exception as e:
            logger.error(f"Error searching AI models: {e}")
            from ..common.error_handling import format_error_response

            return format_error_response(e, "searching AI models")

    async def _handle_get_supported_providers(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get supported providers action."""
        try:
            # arguments parameter is required by interface but not used in this method
            _ = arguments  # Acknowledge the parameter to avoid linter warnings
            client = ReveniumClient()

            # Get all models to extract unique providers
            response = await client.get_ai_models(
                page=0, size=1000
            )  # Get large page to capture all providers

            if "_embedded" in response and "aIModelResourceList" in response["_embedded"]:
                models = response["_embedded"]["aIModelResourceList"]

                # Extract unique providers with model counts
                provider_stats = {}
                for model in models:
                    provider = model.get("provider", "Unknown")
                    if provider not in provider_stats:
                        provider_stats[provider] = {"count": 0, "models": [], "features": set()}
                    provider_stats[provider]["count"] += 1
                    provider_stats[provider]["models"].append(model.get("name", "Unknown"))

                    # Track features
                    if model.get("supportFunctionCalling"):
                        provider_stats[provider]["features"].add("Function Calling")
                    if model.get("supportsVision"):
                        provider_stats[provider]["features"].add("Vision")
                    if model.get("supportsPromptCaching"):
                        provider_stats[provider]["features"].add("Prompt Caching")

                # Build response
                text = "# 🏢 **Supported AI Providers**\n\n"
                text += f"**Total Providers**: {len(provider_stats)}\n"
                text += f"**Total Models**: {len(models)}\n\n"

                for provider, stats in sorted(provider_stats.items()):
                    text += f"## **{provider}**\n"
                    text += f"- **Models Available**: {stats['count']}\n"

                    # Show sample models
                    sample_models = stats["models"][:3]
                    text += f"- **Sample Models**: {', '.join(sample_models)}"
                    if len(stats["models"]) > 3:
                        text += f" (and {len(stats['models']) - 3} more)"
                    text += "\n"

                    # Show features
                    if stats["features"]:
                        text += f"- **Features**: {', '.join(sorted(stats['features']))}\n"
                    text += "\n"

                text += '**💡 Tip**: Use `search_ai_models(query="<provider>")` to see all models from a specific provider\n'
                text += '**💡 Tip**: Use `validate_model_provider(model="<model>", provider="<provider>")` to check compatibility'

                return [TextContent(type="text", text=text)]
            else:
                return [
                    TextContent(
                        type="text",
                        text="❌ **No providers found**\n\nThe API response did not contain any models.",
                    )
                ]

        except Exception as e:
            logger.error(f"Error getting supported providers: {e}")
            from ..common.error_handling import format_error_response

            return format_error_response(e, "getting supported providers")

    async def _handle_validate_model_provider(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle validate model provider action."""
        try:
            model = arguments.get("model")
            provider = arguments.get("provider")

            if not model or not provider:
                missing_params = []
                if not model:
                    missing_params.append("model")
                if not provider:
                    missing_params.append("provider")

                raise ToolError(
                    message=f"Missing required parameters: {', '.join(missing_params)}",
                    error_code=ErrorCodes.MISSING_PARAMETER,
                    field="parameters",
                    value={"model": model, "provider": provider},
                    suggestions=[
                        "Provide both model and provider parameters",
                        "Use search_ai_models() to find valid model names",
                        "Use get_supported_providers() to see available providers",
                        "Model and provider must match supported combinations",
                    ],
                    examples={
                        "usage": 'validate_model_provider(model="<model>", provider="<provider>")',
                        "openai_example": 'validate_model_provider(model="gpt-4o", provider="openai")',
                        "anthropic_example": 'validate_model_provider(model="claude-3-sonnet-20240229", provider="anthropic")',
                        "microsoft_example": 'validate_model_provider(model="gpt-4o", provider="microsoft")',
                    },
                )

            client = ReveniumClient()

            response = await client.search_ai_models(query=model, page=0, size=100)

            if "_embedded" in response and "aIModelResourceList" in response["_embedded"]:
                models = response["_embedded"]["aIModelResourceList"]

                exact_match = None
                partial_matches = []

                for api_model in models:
                    api_model_name = api_model.get("name", "").lower()
                    api_provider = api_model.get("provider", "").lower()

                    if api_model_name == model.lower() and api_provider == provider.lower():
                        exact_match = api_model
                        break
                    elif api_model_name == model.lower() or api_provider == provider.lower():
                        partial_matches.append(api_model)

                if exact_match:
                    text = "✅ **Valid Model/Provider Combination**\n\n"
                    text += f"**Model**: {exact_match.get('name')}\n"
                    text += f"**Provider**: {exact_match.get('provider')}\n"
                    text += f"**Model ID**: {exact_match.get('id')}\n\n"
                    text += "**Cost Information**:\n"
                    text += f"- Input: ${exact_match.get('inputCostPerToken', 'N/A')}/token\n"
                    text += f"- Output: ${exact_match.get('outputCostPerToken', 'N/A')}/token\n\n"
                    text += "**✅ Ready for metering transactions**"

                    return [TextContent(type="text", text=text)]

                elif partial_matches:
                    text = "❌ **Invalid Model/Provider Combination**\n\n"
                    text += f"**Requested**: {model} ({provider})\n\n"
                    text += "**Did you mean one of these?**\n"

                    for match in partial_matches[:5]:
                        text += f"- **{match.get('name')}** ({match.get('provider')})\n"

                    text += f'\n**💡 Tip**: Use `search_ai_models(query="{model}")` to see all matching models'

                    return [TextContent(type="text", text=text)]

                else:
                    text = "❌ **Model/Provider Not Found**\n\n"
                    text += f"**Requested**: {model} ({provider})\n\n"
                    text += "**Suggestions**:\n"
                    text += "- Use `list_ai_models()` to see all available models\n"
                    text += "- Use `get_supported_providers()` to see all providers\n"
                    text += "- Check spelling and try again"

                    return [TextContent(type="text", text=text)]

            else:
                return [
                    TextContent(
                        type="text",
                        text="❌ **Validation failed**\n\nUnable to retrieve models from API for validation.",
                    )
                ]

        except Exception as e:
            logger.error(f"Error validating model/provider: {e}")
            from ..common.error_handling import format_error_response

            return format_error_response(e, "validating model/provider")

    async def _handle_estimate_transaction_cost(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle estimate transaction cost action."""
        try:
            model = arguments.get("model")
            provider = arguments.get("provider")
            input_tokens = arguments.get("input_tokens", 0)
            output_tokens = arguments.get("output_tokens", 0)

            if not model or not provider:
                missing_params = []
                if not model:
                    missing_params.append("model")
                if not provider:
                    missing_params.append("provider")

                raise create_structured_missing_parameter_error(
                    parameter_name=", ".join(missing_params),
                    action="estimate_transaction_cost",
                    examples={
                        "usage": 'estimate_transaction_cost(model="<model>", provider="<provider>", input_tokens=1000, output_tokens=500)',
                        "openai_example": 'estimate_transaction_cost(model="gpt-4o", provider="OPENAI", input_tokens=1500, output_tokens=800)',
                        "anthropic_example": 'estimate_transaction_cost(model="claude-3-sonnet-20240229", provider="ANTHROPIC", input_tokens=2000, output_tokens=1200)',
                    },
                )

            try:
                input_tokens = int(input_tokens)
                output_tokens = int(output_tokens)
            except (ValueError, TypeError):
                raise create_structured_validation_error(
                    message="Token counts must be valid integers",
                    field="token_counts",
                    value={
                        "input_tokens": arguments.get("input_tokens"),
                        "output_tokens": arguments.get("output_tokens"),
                    },
                    suggestions=[
                        "Provide positive integer values for input_tokens and output_tokens",
                        "Token counts must be greater than 0",
                        "Use numeric values without quotes or decimal points",
                    ],
                    examples={
                        "valid_usage": 'estimate_transaction_cost(model="gpt-4o", provider="OPENAI", input_tokens=1500, output_tokens=800)',
                        "valid_tokens": {"input_tokens": 1500, "output_tokens": 800},
                        "invalid_tokens": {"input_tokens": "1500", "output_tokens": "800.5"},
                    },
                )

            client = ReveniumClient()

            response = await client.search_ai_models(query=model, page=0, size=100)

            if "_embedded" in response and "aIModelResourceList" in response["_embedded"]:
                models = response["_embedded"]["aIModelResourceList"]

                target_model = None
                for api_model in models:
                    if (
                        api_model.get("name", "").lower() == model.lower()
                        and api_model.get("provider", "").lower() == provider.lower()
                    ):
                        target_model = api_model
                        break

                if target_model:
                    input_cost_per_token = float(target_model.get("inputCostPerToken", 0))
                    output_cost_per_token = float(target_model.get("outputCostPerToken", 0))

                    input_cost = input_tokens * input_cost_per_token
                    output_cost = output_tokens * output_cost_per_token
                    total_cost = input_cost + output_cost

                    text = "# 💰 **Transaction Cost Estimate**\n\n"
                    text += f"**Model**: {target_model.get('name')} ({target_model.get('provider')})\n\n"
                    text += "### **Token Usage**\n"
                    text += f"- **Input Tokens**: {input_tokens:,}\n"
                    text += f"- **Output Tokens**: {output_tokens:,}\n"
                    text += f"- **Total Tokens**: {input_tokens + output_tokens:,}\n\n"
                    text += "### **Cost Breakdown**\n"
                    text += f"- **Input Cost**: {input_tokens:,} × ${input_cost_per_token} = **${input_cost:.6f}**\n"
                    text += f"- **Output Cost**: {output_tokens:,} × ${output_cost_per_token} = **${output_cost:.6f}**\n"
                    text += f"- **Total Cost**: **${total_cost:.6f}**\n\n"

                    # Add cost per 1K tokens for reference
                    if input_tokens > 0:
                        cost_per_1k_input = 1000 * input_cost_per_token
                        text += "### **Reference Rates**\n"
                        text += f"- **Input**: ${cost_per_1k_input:.4f} per 1K tokens\n"
                        text += (
                            f"- **Output**: ${1000 * output_cost_per_token:.4f} per 1K tokens\n\n"
                        )

                    text += "**💡 Ready to submit**: Use `submit_ai_transaction()` with these parameters"

                    return [TextContent(type="text", text=text)]

                else:
                    return [
                        TextContent(
                            type="text",
                            text=f"❌ **Model not found**: {model} ({provider})\n\n"
                            "**Tip**: Use `validate_model_provider()` to check if the model/provider combination exists",
                        )
                    ]

            else:
                return [
                    TextContent(
                        type="text",
                        text="❌ **Cost estimation failed**\n\nUnable to retrieve model pricing from API.",
                    )
                ]

        except Exception as e:
            logger.error(f"Error estimating transaction cost: {e}")
            from ..common.error_handling import format_error_response

            return format_error_response(e, "estimating transaction cost")

    async def _handle_get_examples(
        self, arguments: Optional[Dict[str, Any]] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get examples action with comprehensive financial services examples and integration code templates."""
        if arguments is None:
            arguments = {}

        example_type = arguments.get("example_type", "default")
        language = arguments.get("language", "python")

        # Handle integration code examples
        if example_type == "integration_code":
            return await self._handle_integration_code_examples(language)

        # Default examples (existing functionality)
        return [
            TextContent(
                type="text",
                text="# **AI Metering Examples**\n\n"
                "## **Financial Services Use Cases (Realistic Examples)**\n\n"
                "### **1. Portfolio Risk Analysis - Basic Transaction**\n"
                "```json\n"
                "{\n"
                '  "action": "submit_ai_transaction",\n'
                '  "model": "gpt-4o",\n'
                '  "provider": "openai",\n'
                '  "input_tokens": 3247,\n'
                '  "output_tokens": 1856,\n'
                '  "duration_ms": 4250,\n'
                '  "organization_id": "stratton-oakmont-financial",\n'
                '  "task_type": "portfolio_risk_analysis",\n'
                '  "agent": "QuantAnalyst_AI_v2.1",\n'
                '  "response_quality_score": 0.94\n'
                "}\n"
                "```\n\n"
                "### **2. Market Sentiment Analysis - With Subscriber Attribution**\n"
                "```json\n"
                "{\n"
                '  "action": "submit_ai_transaction",\n'
                '  "model": "gpt-4o",\n'
                '  "provider": "openai",\n'
                '  "input_tokens": 4125,\n'
                '  "output_tokens": 2340,\n'
                '  "duration_ms": 5800,\n'
                '  "organization_id": "stratton-oakmont-financial",\n'
                '  "task_type": "market_sentiment_analysis",\n'
                '  "agent": "MarketIntel_AI_v3.2",\n'
                '  "subscriber": {\n'
                '    "id": "sub_so_trading_001",\n'
                '    "email": "trading.desk@strattonoakmont.com",\n'
                '    "credential": {\n'
                '      "name": "api_key_trading_platform"\n'
                "    }\n"
                "  },\n"
                '  "trace_id": "conv_market_analysis_20250616",\n'
                '  "response_quality_score": 0.91\n'
                "}\n"
                "```\n\n"
                "### **3. Algorithmic Trading Strategy - Comprehensive Enterprise Transaction**\n"
                "```json\n"
                "{\n"
                '  "action": "submit_ai_transaction",\n'
                '  "model": "gpt-4o",\n'
                '  "provider": "openai",\n'
                '  "input_tokens": 5680,\n'
                '  "output_tokens": 3120,\n'
                '  "duration_ms": 7200,\n'
                '  "organization_id": "stratton-oakmont-financial",\n'
                '  "task_type": "algorithmic_trading_strategy",\n'
                '  "agent": "AlgoTrader_AI_v4.1",\n'
                '  "subscriber": {\n'
                '    "id": "sub_so_quant_team",\n'
                '    "email": "quant.team@strattonoakmont.com",\n'
                '    "credential": {\n'
                '      "name": "algo_trading_api_key"\n'
                "    }\n"
                "  },\n"
                '  "product_id": "trading_platform_v2",\n'
                '  "subscription_id": "sub_enterprise_trading",\n'
                '  "trace_id": "conv_financial_analysis",\n'
                '  "response_quality_score": 0.96,\n'
                '  "is_streamed": false,\n'
                '  "stop_reason": "END"\n'
                "}\n"
                "```\n\n"
                "## **Quick Start Examples (Basic Usage)**\n\n"
                "### **1. Simple OpenAI GPT-4 Transaction**\n"
                "```json\n"
                "{\n"
                '  "action": "submit_ai_transaction",\n'
                '  "model": "gpt-4o",\n'
                '  "provider": "openai",\n'
                '  "input_tokens": 1500,\n'
                '  "output_tokens": 800,\n'
                '  "duration_ms": 2500\n'
                "}\n"
                "```\n\n"
                "### **2. Anthropic Claude Transaction**\n"
                "```json\n"
                "{\n"
                '  "action": "submit_ai_transaction",\n'
                '  "model": "claude-3-5-sonnet-20241022",\n'
                '  "provider": "anthropic",\n'
                '  "input_tokens": 2000,\n'
                '  "output_tokens": 1200,\n'
                '  "duration_ms": 3500\n'
                "}\n"
                "```\n\n"
                "### **3. Google Gemini Transaction**\n"
                "```json\n"
                "{\n"
                '  "action": "submit_ai_transaction",\n'
                '  "model": "gemini-1.5-pro",\n'
                '  "provider": "google",\n'
                '  "input_tokens": 1000,\n'
                '  "output_tokens": 600,\n'
                '  "duration_ms": 1800\n'
                "}\n"
                "```\n\n"
                "## **Field Combination Examples (Tested & Working)**\n\n"
                "### **Basic + Organization Attribution**\n"
                "```json\n"
                "{\n"
                '  "action": "submit_ai_transaction",\n'
                '  "model": "gpt-4o",\n'
                '  "provider": "openai",\n'
                '  "input_tokens": 1500,\n'
                '  "output_tokens": 800,\n'
                '  "duration_ms": 2500,\n'
                '  "organization_id": "acme-corp",\n'
                '  "task_type": "customer_support",\n'
                '  "agent": "SupportBot_v2.1"\n'
                "}\n"
                "```\n\n"
                "### **Quality Tracking + Streaming Metadata**\n"
                "```json\n"
                "{\n"
                '  "action": "submit_ai_transaction",\n'
                '  "model": "gpt-4o",\n'
                '  "provider": "openai",\n'
                '  "input_tokens": 2500,\n'
                '  "output_tokens": 1200,\n'
                '  "duration_ms": 4000,\n'
                '  "response_quality_score": 0.92,\n'
                '  "is_streamed": true,\n'
                '  "stop_reason": "END",\n'
                '  "trace_id": "conv_quality_test_001"\n'
                "}\n"
                "```\n\n"
                "### **Full Enterprise Attribution (All Compatible Fields)**\n"
                "```json\n"
                "{\n"
                '  "action": "submit_ai_transaction",\n'
                '  "model": "gpt-4o",\n'
                '  "provider": "openai",\n'
                '  "input_tokens": 3500,\n'
                '  "output_tokens": 2000,\n'
                '  "duration_ms": 6000,\n'
                '  "organization_id": "enterprise-client",\n'
                '  "task_type": "data_analysis",\n'
                '  "agent": "DataAnalyst_AI_v3.0",\n'
                '  "product_id": "analytics_platform",\n'
                '  "subscription_id": "sub_enterprise_pro",\n'
                '  "trace_id": "conv_enterprise_session",\n'
                '  "response_quality_score": 0.95,\n'
                '  "is_streamed": false,\n'
                '  "stop_reason": "END"\n'
                "}\n"
                "```\n\n"
                "## **Subscriber Object Examples**\n"
                "```json\n"
                "// Minimal subscriber with just ID\n"
                '"subscriber": {\n'
                '  "id": "sub_12345"\n'
                "}\n\n"
                "// Subscriber with email only\n"
                '"subscriber": {\n'
                '  "email": "user@company.com"\n'
                "}\n\n"
                "// Full subscriber with credential\n"
                '"subscriber": {\n'
                '  "id": "sub_12345",\n'
                '  "email": "user@company.com",\n'
                '  "credential": {\n'
                '    "name": "api_token",\n'
                '    "value": "token_xyz789"\n'
                "  }\n"
                "}\n"
                "```\n\n"
                "## **Transaction Verification Examples**\n\n"
                "### **Standard Transaction Lookup (Recommended)**\n"
                "```json\n"
                "{\n"
                '  "action": "lookup_transactions",\n'
                '  "transaction_ids": ["tx_abc123"]\n'
                "}\n"
                "```\n\n"
                "### **Batch Transaction Lookup**\n"
                "```json\n"
                "{\n"
                '  "action": "lookup_transactions",\n'
                '  "transaction_ids": ["tx_abc123", "tx_def456"]\n'
                "}\n"
                "```\n\n"
                "### **Comprehensive Lookup (With Retries)**\n"
                "```json\n"
                "{\n"
                '  "action": "lookup_transactions",\n'
                '  "transaction_ids": ["tx_abc123"],\n'
                '  "max_retries": 5,\n'
                '  "retry_interval": 20\n'
                "}\n"
                "```\n\n"
                "### **Batch Lookup with Custom Settings**\n"
                "```json\n"
                "{\n"
                '  "action": "lookup_transactions",\n'
                '  "transaction_ids": ["tx_abc123", "tx_def456"],\n'
                '  "search_page_range": 10\n'
                "}\n"
                "```\n\n"
                "### **Lookup with Custom Settings**\n"
                "```json\n"
                "{\n"
                '  "action": "lookup_transactions",\n'
                '  "transaction_ids": ["tx_abc123"],\n'
                '  "max_retries": 5,\n'
                '  "early_termination": true\n'
                "}\n"
                "```\n\n"
                "### **Performance Optimized Lookup**\n"
                "```json\n"
                "{\n"
                '  "action": "lookup_transactions",\n'
                '  "transaction_ids": ["tx_abc123"],\n'
                '  "page_size": 100,\n'
                '  "search_page_range": 2\n'
                "}\n"
                "```\n"
                "*Searches only first 200 transactions (2 pages × 100) for fast lookup*\n\n"
                "### **Comprehensive Historical Lookup**\n"
                "```json\n"
                "{\n"
                '  "action": "lookup_transactions",\n'
                '  "transaction_ids": ["tx_abc123"],\n'
                '  "page_size": 1000,\n'
                '  "search_page_range": 50,\n'
                '  "max_retries": 5\n'
                "}\n"
                "```\n"
                "*Searches up to 50,000 transactions (50 pages × 1,000) for comprehensive lookup*\n\n"
                "**🚀 Performance Notes:**\n"
                "- **Auto-pagination**: Searches up to 50,000 recent transactions by default\n"
                "- **Maximum efficiency**: 1,000 transactions per API call (maximum supported)\n"
                "- **Smart search**: Early termination when transactions found\n"
                "- **Historical coverage**: Comprehensive search across transaction history\n\n"
                "## **Pagination Performance Guide**\n\n"
                "### **Quick Searches (Recent Transactions)**\n"
                "**Use Case**: Looking for transactions from last few minutes/hours\n"
                "**Parameters**: `page_size: 50-100`, `search_page_range: 2-5`\n"
                "**Example**: `page_size: 100, search_page_range: 3` = 300 transactions\n"
                "**Performance**: Fast response, minimal API calls\n\n"
                "### **Standard Searches (Recent Days)**\n"
                "**Use Case**: Looking for transactions from last few days\n"
                "**Parameters**: `page_size: 500`, `search_page_range: 10`\n"
                "**Example**: `page_size: 500, search_page_range: 10` = 5,000 transactions\n"
                "**Performance**: Balanced speed and coverage\n\n"
                "### **Comprehensive Searches (Historical)**\n"
                "**Use Case**: Deep historical lookup or large-scale verification\n"
                "**Parameters**: `page_size: 1000`, `search_page_range: 50`\n"
                "**Example**: `page_size: 1000, search_page_range: 50` = 50,000 transactions\n"
                "**Performance**: Maximum coverage, optimal API efficiency\n\n"
                "## **Transaction Lookup and Status**\n\n"
                "### **Single Transaction Lookup (Recommended)**\n"
                "```json\n"
                "{\n"
                '  "action": "lookup_transactions",\n'
                '  "transaction_ids": ["tx_abc123def456"]\n'
                "}\n"
                "```\n\n"
                "### **Quick Recent Transaction Lookup (Performance Optimized)**\n"
                "```json\n"
                "{\n"
                '  "action": "lookup_transactions",\n'
                '  "transaction_ids": ["tx_abc123def456"],\n'
                '  "page_size": 100,\n'
                '  "search_page_range": 5\n'
                "}\n"
                "```\n"
                "*Searches first 500 transactions (5 pages × 100) for fast recent lookup*\n\n"
                "### **Deep Historical Transaction Search**\n"
                "```json\n"
                "{\n"
                '  "action": "lookup_transactions",\n'
                '  "transaction_ids": ["tx_abc123def456"],\n'
                '  "page_size": 1000,\n'
                '  "search_page_range": [20, 50],\n'
                '  "early_termination": true\n'
                "}\n"
                "```\n"
                "*Searches pages 20-50 (31,000 transactions) for historical lookup with early termination*\n\n"
                "### **Check Local Transaction Status**\n"
                "```json\n"
                "{\n"
                '  "action": "get_transaction_status",\n'
                '  "transaction_id": "tx_abc123def456"\n'
                "}\n"
                "```\n\n"
                "## **AI Models Discovery**\n\n"
                "### **List Available Models**\n"
                "```json\n"
                "{\n"
                '  "action": "list_ai_models",\n'
                '  "page": 0,\n'
                '  "size": 20\n'
                "}\n"
                "```\n\n"
                "### **Search for Specific Models**\n"
                "```json\n"
                "{\n"
                '  "action": "search_ai_models",\n'
                '  "query": "gpt"\n'
                "}\n"
                "```\n\n"
                "### **Validate Model/Provider Combination**\n"
                "```json\n"
                "{\n"
                '  "action": "validate_model_provider",\n'
                '  "model": "gpt-4",\n'
                '  "provider": "OPENAI"\n'
                "}\n"
                "```\n\n"
                "### **Estimate Transaction Cost**\n"
                "```json\n"
                "{\n"
                '  "action": "estimate_transaction_cost",\n'
                '  "model": "gpt-4",\n'
                '  "provider": "OPENAI",\n'
                '  "input_tokens": 1500,\n'
                '  "output_tokens": 800\n'
                "}\n"
                "```\n\n"
                "## **🕒 Timestamp Usage Examples**\n\n"
                "### **Auto-Populated Timestamps (Recommended)**\n"
                "```json\n"
                "{\n"
                '  "action": "submit_ai_transaction",\n'
                '  "model": "gpt-4",\n'
                '  "provider": "OPENAI",\n'
                '  "input_tokens": 1500,\n'
                '  "output_tokens": 800,\n'
                '  "duration_ms": 2500\n'
                "  // Timestamps auto-generated: request_time, response_time, completion_start_time\n"
                "  // time_to_first_token auto-calculated from duration_ms\n"
                "}\n"
                "```\n\n"
                "### **Explicit Timestamp Control (External Integration)**\n"
                "```json\n"
                "{\n"
                '  "action": "submit_ai_transaction",\n'
                '  "model": "claude-3-sonnet-20240229",\n'
                '  "provider": "ANTHROPIC",\n'
                '  "input_tokens": 2000,\n'
                '  "output_tokens": 1200,\n'
                '  "duration_ms": 3500,\n'
                '  "request_time": "2025-03-02T15:30:45.123Z",\n'
                '  "response_time": "2025-03-02T15:30:48.623Z",\n'
                '  "completion_start_time": "2025-03-02T15:30:45.623Z",\n'
                '  "time_to_first_token": 500\n'
                "}\n"
                "```\n\n"
                "### **Mixed Approach (Some Explicit, Some Auto)**\n"
                "```json\n"
                "{\n"
                '  "action": "submit_ai_transaction",\n'
                '  "model": "gemini-pro",\n'
                '  "provider": "GOOGLE",\n'
                '  "input_tokens": 1000,\n'
                '  "output_tokens": 600,\n'
                '  "duration_ms": 1800,\n'
                '  "request_time": "2025-03-02T15:30:45.123Z"\n'
                "  // response_time and completion_start_time will be auto-populated\n"
                "  // time_to_first_token will be auto-calculated (180ms)\n"
                "}\n"
                "```\n\n"
                "## **Usage Tips**\n\n"
                "1. **Always validate model/provider combinations** using `validate_model_provider()` before submitting transactions\n"
                "2. **Use the subscriber object format** - the old separate fields are no longer supported\n"
                "3. **Include attribution metadata** for enterprise usage tracking\n"
                "4. **Lookup transactions** using `lookup_transactions()` to find and verify transactions\n"
                "5. **Use AI models discovery** to find supported models and get cost estimates\n"
                "6. **Timestamp auto-population** - Don't provide timestamps for real-time usage (recommended)\n"
                "7. **Explicit timestamps** - Only provide when integrating external systems or importing historical data\n"
                "8. **Timestamp format** - Must be ISO UTC with milliseconds ending in 'Z' (e.g., \"2025-03-02T15:30:45.123Z\")\n\n"
                "## **Complete Financial Services Workflow**\n\n"
                "```bash\n"
                "# 1. Discover available models for financial analysis\n"
                'search_ai_models(query="gpt-4")\n'
                "# Returns: List of GPT-4 models with providers and costs\n\n"
                "# 2. Validate model/provider combination\n"
                'validate_model_provider(model="gpt-4o", provider="openai")\n'
                '# Returns: {"valid": true, "cost_info": {"input_cost": 0.0000025, "output_cost": 0.00001}}\n\n'
                "# 3. Submit financial analysis transaction\n"
                "submit_ai_transaction(\n"
                '  model="gpt-4o", \n'
                '  provider="openai", \n'
                "  input_tokens=4125, \n"
                "  output_tokens=2340, \n"
                "  duration_ms=5800,\n"
                '  organization_id="stratton-oakmont-financial",\n'
                '  task_type="market_sentiment_analysis",\n'
                '  agent="MarketIntel_AI_v3.2",\n'
                '  subscriber={"id": "sub_so_trading_001", "email": "trading.desk@strattonoakmont.com"}\n'
                ")\n"
                '# Returns: {"transaction_id": "tx_9162844a6068", "status": "submitted"}\n\n'
                "# 4. Lookup and verify transaction (unified approach)\n"
                'lookup_transactions(transaction_ids=["tx_9162844a6068"])\n'
                '# Returns: {"results": [{"transaction_id": "tx_9162844a6068", "found": true, "source": "api"}], "summary": {"found_count": 1}}\n\n'
                "# 6. Check local transaction status (optional)\n"
                'get_transaction_status(transaction_id="tx_9162844a6068")\n'
                '# Returns: {"found": true, "verified": true, "model": "gpt-4o", "provider": "openai"}\n'
                "```\n\n"
                "## **Field Compatibility Guidelines**\n\n"
                "### **Safe Field Combinations (Tested)**\n"
                "- **Basic Required**: model, provider, input_tokens, output_tokens, duration_ms\n"
                "- **Organization Attribution**: + organization_id, task_type, agent\n"
                "- **Quality Tracking**: + response_quality_score, is_streamed, stop_reason\n"
                "- **Session Tracking**: + trace_id\n"
                "- **Billing Attribution**: + product_id, subscription_id, subscriber\n"
                "- **Timestamp Control**: + request_time, response_time, completion_start_time, time_to_first_token\n\n"
                "### **⚠️ Validation Rules**\n"
                "- **response_quality_score**: Must be 0.0-1.0\n"
                "- **is_streamed**: Boolean (true/false)\n"
                "- **Timestamps**: ISO UTC format ending in 'Z' (e.g., \"2025-06-16T15:30:45.123Z\")\n"
                "- **String fields**: Non-empty, max 500 characters, no special characters (<, >, \", ', &)\n"
                "- **Token counts**: Positive integers\n"
                "- **Duration**: Positive integer in milliseconds\n\n"
                "### **Integration Guide Examples**\n"
                "```bash\n"
                "# Get comprehensive implementation guidance\n"
                'get_integration_guide(language="python")     # Python integration with working code\n'
                'get_integration_guide(language="javascript") # JavaScript/Node.js with official packages\n'
                "```\n\n"
                "### **Troubleshooting Tips**\n"
                "- **Validation errors**: Use validate() action to test before submit_ai_transaction()\n"
                "- **Missing transactions**: Increase wait_seconds (try 60-90s) and max_retries (3-5)\n"
                "- **Field conflicts**: Check field compatibility matrix above\n"
                "- **Subscriber format**: Use new object structure, not individual fields\n"
                "- **Model/provider**: Always validate combination with validate_model_provider() first",
            )
        ]

    async def _handle_integration_code_examples(
        self, language: str
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle integration code examples for different programming languages."""
        if language.lower() == "python":
            return await self._get_python_integration_examples()
        elif language.lower() == "javascript":
            return await self._get_javascript_integration_examples()
        else:
            # Default to Python with language note
            return await self._get_python_integration_examples()

    async def _get_python_integration_examples(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Get Python integration code examples."""
        return [
            TextContent(
                type="text",
                text="# 🐍 **Python Integration Code Examples**\n\n"
                "## **Complete Production-Ready Client**\n\n"
                "### **Basic Async Client with aiohttp**\n"
                "```python\n"
                "import os\n"
                "import asyncio\n"
                "import aiohttp\n"
                "import json\n"
                "from typing import Dict, Any, Optional, List\n"
                "from datetime import datetime\n"
                "import logging\n\n"
                "class ReveniumMeteringClient:\n"
                '    """Production-ready Revenium metering client with error handling."""\n'
                "    \n"
                "    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):\n"
                "        self.api_key = api_key or os.getenv('REVENIUM_API_KEY')\n"
                "        self.base_url = base_url or os.getenv('REVENIUM_BASE_URL', 'https://api.revenium.ai')\n"
                "        self.timeout = int(os.getenv('REVENIUM_TIMEOUT', '30'))\n"
                "        \n"
                "        if not self.api_key:\n"
                "            raise ValueError('REVENIUM_API_KEY environment variable or api_key parameter required')\n"
                "        \n"
                "        self.headers = {\n"
                "            'Authorization': f'Bearer {self.api_key}',\n"
                "            'x-api-key': self.api_key,\n"
                "            'Content-Type': 'application/json',\n"
                "            'User-Agent': 'ReveniumPythonClient/1.0.0'\n"
                "        }\n"
                "        \n"
                "        # Setup logging\n"
                "        self.logger = logging.getLogger(__name__)\n"
                "    \n"
                "    async def submit_transaction(self, transaction_data: Dict[str, Any]) -> Dict[str, Any]:\n"
                '        """Submit AI transaction with comprehensive error handling."""\n'
                "        url = f'{self.base_url}/meter/v2/ai/completions'\n"
                "        \n"
                "        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:\n"
                "            try:\n"
                "                async with session.post(url, json=transaction_data, headers=self.headers) as response:\n"
                "                    response_data = await response.json()\n"
                "                    \n"
                "                    if response.status == 201:\n"
                "                        self.logger.info(f'Transaction submitted: {response_data.get(\"transaction_id\")}')\n"
                "                        return response_data\n"
                "                    elif response.status == 400:\n"
                "                        raise ValidationError(f'Validation failed: {response_data.get(\"message\")}')\n"
                "                    elif response.status == 401:\n"
                "                        raise AuthenticationError('Invalid API key')\n"
                "                    elif response.status == 429:\n"
                "                        retry_after = int(response.headers.get('Retry-After', 60))\n"
                "                        raise RateLimitError(f'Rate limited. Retry after {retry_after} seconds')\n"
                "                    else:\n"
                "                        raise APIError(f'API Error {response.status}: {response_data}')\n"
                "                        \n"
                "            except aiohttp.ClientError as e:\n"
                "                raise ConnectionError(f'Network error: {e}')\n"
                "    \n"
                "    async def lookup_transactions(self, transaction_ids: List[str]) -> Dict[str, Any]:\n"
                '        """Unified transaction lookup with automatic optimization."""\n'
                "        url = f'{self.base_url}/profitstream/v2/api/sources/metrics/ai/completions'\n"
                "        params = {}\n"
                "        \n"
                "        if transaction_ids:\n"
                "            params['transaction_ids'] = ','.join(transaction_ids)\n"
                "        if since:\n"
                "            params['since'] = since\n"
                "        \n"
                "        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:\n"
                "            async with session.get(url, params=params, headers=self.headers) as response:\n"
                "                if response.status == 200:\n"
                "                    return await response.json()\n"
                "                else:\n"
                "                    error_data = await response.json()\n"
                "                    raise APIError(f'Verification failed {response.status}: {error_data}')\n\n"
                "# Custom exceptions\n"
                "class ReveniumError(Exception):\n"
                '    """Base exception for Revenium client errors."""\n'
                "    pass\n\n"
                "class ValidationError(ReveniumError):\n"
                '    """Raised when request validation fails."""\n'
                "    pass\n\n"
                "class AuthenticationError(ReveniumError):\n"
                '    """Raised when authentication fails."""\n'
                "    pass\n\n"
                "class RateLimitError(ReveniumError):\n"
                '    """Raised when rate limit is exceeded."""\n'
                "    pass\n\n"
                "class APIError(ReveniumError):\n"
                '    """Raised for general API errors."""\n'
                "    pass\n"
                "```\n\n"
                "## **Usage Examples**\n\n"
                "### **Basic Usage**\n"
                "```python\n"
                "import asyncio\n"
                "from revenium_client import ReveniumMeteringClient\n\n"
                "async def main():\n"
                "    # Initialize client\n"
                "    client = ReveniumMeteringClient()\n"
                "    \n"
                "    # Submit transaction\n"
                "    transaction = {\n"
                "        'model': 'gpt-4o',\n"
                "        'provider': 'openai',\n"
                "        'inputTokenCount': 1500,\n"
                "        'outputTokenCount': 800,\n"
                "        'requestDuration': 2500,\n"
                "        'requestTime': '2024-01-01T00:00:00Z',\n"
                "        'completionStartTime': '2024-01-01T00:00:01Z',\n"
                "        'responseTime': '2024-01-01T00:00:02Z',\n"
                "        'stopReason': 'stop',\n"
                "        'organizationId': 'my-org',\n"
                "        'taskType': 'text_generation'\n"
                "    }\n"
                "    \n"
                "    try:\n"
                "        result = await client.submit_transaction(transaction)\n"
                "        print(f'Success: {result[\"transaction_id\"]}')\n"
                "        \n"
                "        # Lookup transaction\n"
                "        lookup_result = await client.lookup_transactions([result['transaction_id']])\n"
                "        print(f'Lookup result: {lookup_result}')\n"
                "        \n"
                "    except ValidationError as e:\n"
                "        print(f'Validation error: {e}')\n"
                "    except RateLimitError as e:\n"
                "        print(f'Rate limited: {e}')\n"
                "        # Implement retry logic here\n"
                "    except Exception as e:\n"
                "        print(f'Error: {e}')\n\n"
                "if __name__ == '__main__':\n"
                "    asyncio.run(main())\n"
                "```\n\n"
                "### **Production Usage with Retry Logic**\n"
                "```python\n"
                "import asyncio\n"
                "import random\n"
                "from typing import Dict, Any\n\n"
                "async def submit_with_retry(client: ReveniumMeteringClient, \n"
                "                           transaction: Dict[str, Any], \n"
                "                           max_retries: int = 3) -> Dict[str, Any]:\n"
                '    """Submit transaction with exponential backoff retry."""\n'
                "    for attempt in range(max_retries):\n"
                "        try:\n"
                "            return await client.submit_transaction(transaction)\n"
                "        except RateLimitError as e:\n"
                "            if attempt == max_retries - 1:\n"
                "                raise\n"
                "            # Exponential backoff with jitter\n"
                "            delay = (2 ** attempt) + random.uniform(0, 1)\n"
                "            await asyncio.sleep(min(delay, 60))\n"
                "        except (ValidationError, AuthenticationError):\n"
                "            # Don't retry validation or auth errors\n"
                "            raise\n"
                "        except Exception as e:\n"
                "            if attempt == max_retries - 1:\n"
                "                raise\n"
                "            await asyncio.sleep(2 ** attempt)\n\n"
                "async def batch_submit_transactions(client: ReveniumMeteringClient,\n"
                "                                  transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:\n"
                '    """Submit multiple transactions concurrently."""\n'
                "    semaphore = asyncio.Semaphore(10)  # Limit concurrent requests\n"
                "    \n"
                "    async def submit_one(transaction):\n"
                "        async with semaphore:\n"
                "            return await submit_with_retry(client, transaction)\n"
                "    \n"
                "    tasks = [submit_one(tx) for tx in transactions]\n"
                "    return await asyncio.gather(*tasks, return_exceptions=True)\n"
                "```\n\n"
                "### **Environment Setup**\n"
                "```bash\n"
                "# .env file\n"
                "REVENIUM_API_KEY=rev_your_api_key_here\n"
                "REVENIUM_BASE_URL=https://api.revenium.ai\n"
                "REVENIUM_TIMEOUT=30\n"
                "```\n\n"
                "```bash\n"
                "# Install dependencies\n"
                "pip install aiohttp python-dotenv\n"
                "```\n\n"
                "**💡 Next Steps**: Use `get_authentication_details()` for complete setup guidance\n",
            )
        ]

    async def _get_javascript_integration_examples(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Get JavaScript integration code examples."""
        return [
            TextContent(
                type="text",
                text="# **JavaScript/Node.js Integration Examples**\n\n"
                "## **Complete Production-Ready Client**\n\n"
                "### **Modern ES6+ Client with fetch**\n"
                "```javascript\n"
                "const fetch = require('node-fetch'); // npm install node-fetch\n"
                "const { performance } = require('perf_hooks');\n\n"
                "class ReveniumMeteringClient {\n"
                "    constructor(apiKey = null, baseUrl = null) {\n"
                "        this.apiKey = apiKey || process.env.REVENIUM_API_KEY;\n"
                "        this.baseUrl = baseUrl || process.env.REVENIUM_BASE_URL || 'https://api.revenium.ai';\n"
                "        this.timeout = parseInt(process.env.REVENIUM_TIMEOUT || '30000');\n"
                "        \n"
                "        if (!this.apiKey) {\n"
                "            throw new Error('REVENIUM_API_KEY environment variable or apiKey parameter required');\n"
                "        }\n"
                "        \n"
                "        this.headers = {\n"
                "            'Authorization': `Bearer ${this.apiKey}`,\n"
                "            'x-api-key': this.apiKey,\n"
                "            'Content-Type': 'application/json',\n"
                "            'User-Agent': 'ReveniumNodeClient/1.0.0'\n"
                "        };\n"
                "    }\n"
                "    \n"
                "    async submitTransaction(transactionData) {\n"
                "        const url = `${this.baseUrl}/meter/v2/ai/completions`;\n"
                "        \n"
                "        try {\n"
                "            const controller = new AbortController();\n"
                "            const timeoutId = setTimeout(() => controller.abort(), this.timeout);\n"
                "            \n"
                "            const response = await fetch(url, {\n"
                "                method: 'POST',\n"
                "                headers: this.headers,\n"
                "                body: JSON.stringify(transactionData),\n"
                "                signal: controller.signal\n"
                "            });\n"
                "            \n"
                "            clearTimeout(timeoutId);\n"
                "            const responseData = await response.json();\n"
                "            \n"
                "            if (response.status === 201) {\n"
                "                console.log(`Transaction submitted: ${responseData.transaction_id}`);\n"
                "                return responseData;\n"
                "            } else if (response.status === 400) {\n"
                "                throw new ValidationError(`Validation failed: ${responseData.message}`);\n"
                "            } else if (response.status === 401) {\n"
                "                throw new AuthenticationError('Invalid API key');\n"
                "            } else if (response.status === 429) {\n"
                "                const retryAfter = parseInt(response.headers.get('Retry-After') || '60');\n"
                "                throw new RateLimitError(`Rate limited. Retry after ${retryAfter} seconds`);\n"
                "            } else {\n"
                "                throw new APIError(`API Error ${response.status}: ${JSON.stringify(responseData)}`);\n"
                "            }\n"
                "            \n"
                "        } catch (error) {\n"
                "            if (error.name === 'AbortError') {\n"
                "                throw new Error(`Request timeout after ${this.timeout}ms`);\n"
                "            }\n"
                "            throw error;\n"
                "        }\n"
                "    }\n"
                "    \n"
                "    async verifyTransactions(transactionIds = null, since = null) {\n"
                "        const url = new URL(`${this.baseUrl}/profitstream/v2/api/sources/metrics/ai/completions`);\n"
                "        \n"
                "        if (transactionIds) {\n"
                "            url.searchParams.append('transaction_ids', transactionIds.join(','));\n"
                "        }\n"
                "        if (since) {\n"
                "            url.searchParams.append('since', since);\n"
                "        }\n"
                "        \n"
                "        const response = await fetch(url.toString(), {\n"
                "            method: 'GET',\n"
                "            headers: this.headers\n"
                "        });\n"
                "        \n"
                "        if (response.status === 200) {\n"
                "            return await response.json();\n"
                "        } else {\n"
                "            const errorData = await response.json();\n"
                "            throw new APIError(`Verification failed ${response.status}: ${JSON.stringify(errorData)}`);\n"
                "        }\n"
                "    }\n"
                "}\n\n"
                "// Custom error classes\n"
                "class ReveniumError extends Error {\n"
                "    constructor(message) {\n"
                "        super(message);\n"
                "        this.name = this.constructor.name;\n"
                "    }\n"
                "}\n\n"
                "class ValidationError extends ReveniumError {}\n"
                "class AuthenticationError extends ReveniumError {}\n"
                "class RateLimitError extends ReveniumError {}\n"
                "class APIError extends ReveniumError {}\n\n"
                "module.exports = {\n"
                "    ReveniumMeteringClient,\n"
                "    ValidationError,\n"
                "    AuthenticationError,\n"
                "    RateLimitError,\n"
                "    APIError\n"
                "};\n"
                "```\n\n"
                "## **Usage Examples**\n\n"
                "### **Basic Usage**\n"
                "```javascript\n"
                "const { ReveniumMeteringClient } = require('./revenium-client');\n\n"
                "async function main() {\n"
                "    try {\n"
                "        // Initialize client\n"
                "        const client = new ReveniumMeteringClient();\n"
                "        \n"
                "        // Submit transaction\n"
                "        const transaction = {\n"
                "            model: 'gpt-4o',\n"
                "            provider: 'openai',\n"
                "            inputTokenCount: 1500,\n"
                "            outputTokenCount: 800,\n"
                "            requestDuration: 2500,\n"
                "            requestTime: '2024-01-01T00:00:00Z',\n"
                "            completionStartTime: '2024-01-01T00:00:01Z',\n"
                "            responseTime: '2024-01-01T00:00:02Z',\n"
                "            stopReason: 'stop',\n"
                "            organizationId: 'my-org',\n"
                "            taskType: 'text_generation'\n"
                "        };\n"
                "        \n"
                "        const result = await client.submitTransaction(transaction);\n"
                "        console.log(`Success: ${result.transaction_id}`);\n"
                "        \n"
                "        // Verify transaction\n"
                "        const verification = await client.verifyTransactions([result.transaction_id]);\n"
                "        console.log('Verified:', verification);\n"
                "        \n"
                "    } catch (error) {\n"
                "        if (error instanceof ValidationError) {\n"
                "            console.error('Validation error:', error.message);\n"
                "        } else if (error instanceof RateLimitError) {\n"
                "            console.error('Rate limited:', error.message);\n"
                "        } else {\n"
                "            console.error('Error:', error.message);\n"
                "        }\n"
                "    }\n"
                "}\n\n"
                "main().catch(console.error);\n"
                "```\n\n"
                "### **Environment Setup**\n"
                "```bash\n"
                "# .env file\n"
                "REVENIUM_API_KEY=rev_your_api_key_here\n"
                "REVENIUM_BASE_URL=https://api.revenium.ai\n"
                "REVENIUM_TIMEOUT=30000\n"
                "```\n\n"
                "```bash\n"
                "# Install dependencies\n"
                "npm install node-fetch dotenv\n"
                "```\n\n"
                "**Next Steps**: Use `get_rate_limits()` for retry strategies\n",
            )
        ]

    async def _get_java_integration_examples(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Get Java integration code examples."""
        return [
            TextContent(
                type="text",
                text="# **Java Integration Examples**\n\n"
                "## **Complete Production-Ready Client**\n\n"
                "### **Modern Java Client with HttpClient**\n"
                "```java\n"
                "import java.net.http.HttpClient;\n"
                "import java.net.http.HttpRequest;\n"
                "import java.net.http.HttpResponse;\n"
                "import java.net.URI;\n"
                "import java.time.Duration;\n"
                "import java.util.Map;\n"
                "import java.util.List;\n"
                "import java.util.Optional;\n"
                "import com.fasterxml.jackson.databind.ObjectMapper;\n"
                "import com.fasterxml.jackson.core.type.TypeReference;\n\n"
                "public class ReveniumMeteringClient {\n"
                "    private final String apiKey;\n"
                "    private final String baseUrl;\n"
                "    private final HttpClient httpClient;\n"
                "    private final ObjectMapper objectMapper;\n"
                "    private final Duration timeout;\n"
                "    \n"
                "    public ReveniumMeteringClient(String apiKey, String baseUrl) {\n"
                "        this.apiKey = Optional.ofNullable(apiKey)\n"
                '            .orElse(System.getenv("REVENIUM_API_KEY"));\n'
                "        this.baseUrl = Optional.ofNullable(baseUrl)\n"
                '            .orElse(Optional.ofNullable(System.getenv("REVENIUM_BASE_URL"))\n'
                '                .orElse("https://api.revenium.ai"));\n'
                "        this.timeout = Duration.ofSeconds(\n"
                '            Integer.parseInt(Optional.ofNullable(System.getenv("REVENIUM_TIMEOUT"))\n'
                '                .orElse("30")));\n'
                "        \n"
                "        if (this.apiKey == null || this.apiKey.isEmpty()) {\n"
                "            throw new IllegalArgumentException(\n"
                '                "REVENIUM_API_KEY environment variable or apiKey parameter required");\n'
                "        }\n"
                "        \n"
                "        this.httpClient = HttpClient.newBuilder()\n"
                "            .connectTimeout(timeout)\n"
                "            .build();\n"
                "        this.objectMapper = new ObjectMapper();\n"
                "    }\n"
                "    \n"
                "    public Map<String, Object> submitTransaction(Map<String, Object> transactionData) \n"
                "            throws ReveniumException {\n"
                "        try {\n"
                "            String jsonBody = objectMapper.writeValueAsString(transactionData);\n"
                "            \n"
                "            HttpRequest request = HttpRequest.newBuilder()\n"
                '                .uri(URI.create(baseUrl + "/meter/v2/ai/completions"))\n'
                "                .timeout(timeout)\n"
                '                .header("Authorization", "Bearer " + apiKey)\n'
                '                .header("x-api-key", apiKey)\n'
                '                .header("Content-Type", "application/json")\n'
                '                .header("User-Agent", "ReveniumJavaClient/1.0.0")\n'
                "                .POST(HttpRequest.BodyPublishers.ofString(jsonBody))\n"
                "                .build();\n"
                "            \n"
                "            HttpResponse<String> response = httpClient.send(request, \n"
                "                HttpResponse.BodyHandlers.ofString());\n"
                "            \n"
                "            Map<String, Object> responseData = objectMapper.readValue(\n"
                "                response.body(), new TypeReference<Map<String, Object>>() {});\n"
                "            \n"
                "            switch (response.statusCode()) {\n"
                "                case 201:\n"
                '                    System.out.println("Transaction submitted: " + \n'
                '                        responseData.get("transaction_id"));\n'
                "                    return responseData;\n"
                "                case 400:\n"
                '                    throw new ValidationException("Validation failed: " + \n'
                '                        responseData.get("message"));\n'
                "                case 401:\n"
                '                    throw new AuthenticationException("Invalid API key");\n'
                "                case 429:\n"
                '                    String retryAfter = response.headers().firstValue("Retry-After")\n'
                '                        .orElse("60");\n'
                '                    throw new RateLimitException("Rate limited. Retry after " + \n'
                '                        retryAfter + " seconds");\n'
                "                default:\n"
                '                    throw new APIException("API Error " + response.statusCode() + \n'
                '                        ": " + response.body());\n'
                "            }\n"
                "            \n"
                "        } catch (Exception e) {\n"
                "            if (e instanceof ReveniumException) {\n"
                "                throw e;\n"
                "            }\n"
                '            throw new ReveniumException("Request failed: " + e.getMessage(), e);\n'
                "        }\n"
                "    }\n"
                "}\n\n"
                "// Custom exception classes\n"
                "public class ReveniumException extends Exception {\n"
                "    public ReveniumException(String message) {\n"
                "        super(message);\n"
                "    }\n"
                "    \n"
                "    public ReveniumException(String message, Throwable cause) {\n"
                "        super(message, cause);\n"
                "    }\n"
                "}\n\n"
                "public class ValidationException extends ReveniumException {\n"
                "    public ValidationException(String message) {\n"
                "        super(message);\n"
                "    }\n"
                "}\n\n"
                "public class AuthenticationException extends ReveniumException {\n"
                "    public AuthenticationException(String message) {\n"
                "        super(message);\n"
                "    }\n"
                "}\n\n"
                "public class RateLimitException extends ReveniumException {\n"
                "    public RateLimitException(String message) {\n"
                "        super(message);\n"
                "    }\n"
                "}\n\n"
                "public class APIException extends ReveniumException {\n"
                "    public APIException(String message) {\n"
                "        super(message);\n"
                "    }\n"
                "}\n"
                "```\n\n",
            )
        ]

    async def _handle_get_agent_summary(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get agent summary action with structured overview and clear call-to-action."""
        return [
            TextContent(
                type="text",
                text="# **AI Transaction Metering Management**\n\n"
                "The manage_metering tool allows you to submit AI transactions to Revenium for metering, look up previously submitted AI transactions, validate transaction data before submission, and access comprehensive documentation for AI usage tracking and billing.\n\n"
                "## **Capabilities Overview**\n\n"
                "### **Core Operations**\n"
                "• **Transaction Submission**: Submit AI usage data with comprehensive metadata for billing and attribution\n"
                "• **Transaction Lookup**: Find and verify previously submitted transactions with flexible search options\n"
                "• **Data Validation**: Validate transaction data and model/provider combinations before submission\n\n"
                "### **Discovery & Integration**\n"
                "• **AI Models Discovery**: Search and validate supported AI models and providers\n"
                "• **API Integration**: Get technical implementation guidance with code examples\n"
                "• **Field Documentation**: Access complete field specifications and validation rules\n\n"
                "### **Business & Compliance**\n"
                "• **Business Rules**: Understand critical validation requirements and compliance rules\n"
                "• **Enterprise Attribution**: Track usage by organization, product, and subscriber\n"
                "• **Quality Monitoring**: Monitor AI performance with quality scores and metrics\n\n"
                "## **Quick Start**\n"
                "```bash\n"
                "# 1. Validate model/provider combination\n"
                'validate_model_provider(model="gpt-4o", provider="openai")\n\n'
                "# 2. Submit AI transaction\n"
                'submit_ai_transaction(model="gpt-4o", provider="openai", input_tokens=1500, output_tokens=800, duration_ms=2500)\n\n'
                "# 3. Lookup transaction\n"
                'lookup_transactions(transaction_ids=["tx_abc123"])\n'
                "```\n\n"
                "## **Detailed Capabilities**\n"
                "For comprehensive guidance on specific workflows, use these focused capability actions:\n\n"
                "• **`get_submission_capabilities`** - Complete field specifications and submission examples\n"
                "• **`get_lookup_capabilities`** - Transaction lookup methods and optimization\n"
                "• **`get_integration_capabilities`** - API integration guide with code examples\n"
                "• **`get_validation_capabilities`** - Field validation rules and data format requirements\n"
                "• **`get_field_documentation`** - Complete field specifications and compatibility matrix\n"
                "• **`get_business_rules`** - Critical validation requirements and business logic\n\n"
                "**For more information on any of these capabilities, use the actions above.**"
            )
        ]

    async def _handle_parse_natural_language(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle natural language parsing for subscriber migration guidance and timestamp usage."""
        text = arguments.get("text", "").lower()
        description = arguments.get("description", "").lower()
        query = f"{text} {description}".strip()

        # Check for timestamp-related queries
        timestamp_indicators = [
            "timestamp",
            "time",
            "request_time",
            "response_time",
            "completion_start_time",
            "time_to_first_token",
            "auto populate",
            "auto-populate",
            "explicit time",
            "iso utc",
            "timestamp format",
            "external system",
            "integration testing",
            "historical data",
            "when to provide time",
            "timestamp validation",
        ]

        # Check for old subscriber format mentions in natural language
        old_format_indicators = [
            "subscriber_email",
            "subscriber_id",
            "subscriber_credential",
            "subscriber email",
            "subscriber id",
            "subscriber credential",
            "separate subscriber fields",
            "individual subscriber",
            "old subscriber format",
            "subscriber fields",
        ]

        detected_timestamp_query = any(indicator in query for indicator in timestamp_indicators)
        detected_old_format = any(indicator in query for indicator in old_format_indicators)

        if detected_timestamp_query:
            return [
                TextContent(
                    type="text",
                    text="**TIMESTAMP FIELD GUIDANCE**\n\n"
                    "I detected you're asking about timestamp handling in AI metering transactions!\n\n"
                    "## **Two Usage Patterns**\n\n"
                    "### **Auto-Population (Recommended)**\n"
                    "**When to use**: Real-time AI usage tracking, most common scenarios\n"
                    "**How**: Don't provide any timestamp fields - system auto-generates them\n"
                    "```json\n"
                    "{\n"
                    '  "action": "submit_ai_transaction",\n'
                    '  "model": "gpt-4",\n'
                    '  "provider": "OPENAI",\n'
                    '  "input_tokens": 1500,\n'
                    '  "output_tokens": 800,\n'
                    '  "duration_ms": 2500\n'
                    "  // All timestamps auto-generated with current UTC time\n"
                    "}\n"
                    "```\n\n"
                    "### **Explicit Control (External Integration)**\n"
                    "**When to use**: External system integration, historical data import, testing\n"
                    "**How**: Provide timestamp fields in ISO UTC format\n"
                    "```json\n"
                    "{\n"
                    '  "action": "submit_ai_transaction",\n'
                    '  "model": "claude-3-sonnet-20240229",\n'
                    '  "provider": "ANTHROPIC",\n'
                    '  "input_tokens": 2000,\n'
                    '  "output_tokens": 1200,\n'
                    '  "duration_ms": 3500,\n'
                    '  "request_time": "2025-03-02T15:30:45.123Z",\n'
                    '  "response_time": "2025-03-02T15:30:48.623Z",\n'
                    '  "completion_start_time": "2025-03-02T15:30:45.623Z",\n'
                    '  "time_to_first_token": 500\n'
                    "}\n"
                    "```\n\n"
                    "## **Available Timestamp Fields**\n"
                    "- `request_time` - When AI request was made (auto-populated if not provided)\n"
                    "- `response_time` - When AI response was generated (auto-populated if not provided)\n"
                    "- `completion_start_time` - Streaming start time (auto-populated if not provided)\n"
                    "- `time_to_first_token` - Time to first token in ms (auto-calculated if not provided)\n\n"
                    "## **⚠️ Format Requirements**\n"
                    "- **Format**: ISO UTC with milliseconds\n"
                    '- **Example**: `"2025-03-02T15:30:45.123Z"`\n'
                    "- **Must end with 'Z'** for UTC timezone\n"
                    "- **Invalid formats** automatically fall back to auto-generation\n\n"
                    "## **Smart Validation**\n"
                    "- System validates provided timestamps\n"
                    "- Invalid formats trigger auto-population fallback\n"
                    "- Mix explicit and auto-populated fields as needed\n"
                    "- Logs show which timestamps were provided vs auto-generated\n\n"
                    "**Use `get_examples()` to see complete timestamp usage patterns!**",
                )
            ]
        elif detected_old_format:
            return [
                TextContent(
                    type="text",
                    text="⚠️ **SUBSCRIBER FORMAT MIGRATION REQUIRED** ⚠️\n\n"
                    "I detected you're asking about the old subscriber format. "
                    "The subscriber data structure has been updated!\n\n"
                    "**❌ Old format (no longer supported)**:\n"
                    "```json\n"
                    "{\n"
                    '  "subscriber_email": "user@company.com",\n'
                    '  "subscriber_id": "sub_12345",\n'
                    '  "subscriber_credential_name": "api_key",\n'
                    '  "subscriber_credential": "***YOUR_API_KEY***"\n'
                    "}\n"
                    "```\n\n"
                    "**✅ New format (required)**:\n"
                    "```json\n"
                    "{\n"
                    '  "subscriber": {\n'
                    '    "id": "sub_12345",\n'
                    '    "email": "user@company.com",\n'
                    '    "credential": {\n'
                    '      "name": "api_key",\n'
                    '      "value": "***YOUR_API_KEY***"\n'
                    "    }\n"
                    "  }\n"
                    "}\n"
                    "```\n\n"
                    "**Key Changes**:\n"
                    "• All subscriber data is now nested under a single `subscriber` object\n"
                    "• Credential information is nested under `subscriber.credential`\n"
                    "• All fields are optional within the subscriber object\n"
                    "• You can include just `id`, just `email`, or both with optional credential\n\n"
                    "**Migration Examples**:\n"
                    "```json\n"
                    "// Minimal - just ID\n"
                    '"subscriber": { "id": "sub_12345" }\n\n'
                    "// Email only\n"
                    '"subscriber": { "email": "user@company.com" }\n\n'
                    "// Full with credential\n"
                    '"subscriber": {\n'
                    '  "id": "sub_12345",\n'
                    '  "email": "user@company.com",\n'
                    '  "credential": {\n'
                    '    "name": "api_token",\n'
                    '    "value": "token_xyz"\n'
                    "  }\n"
                    "}\n"
                    "```\n\n"
                    "Use `get_examples()` to see complete transaction examples with the new format!",
                )
            ]
        else:
            return [
                TextContent(
                    type="text",
                    text="**Natural Language Processing**\n\n"
                    "I can help you understand the AI metering API structure, migration guidance, and timestamp handling.\n\n"
                    "**What I can help with**:\n"
                    "• Subscriber format migration (old → new structure)\n"
                    "• Timestamp field usage and validation\n"
                    "• Transaction parameter guidance\n"
                    "• API structure explanations\n"
                    "• Example generation\n\n"
                    "**Try asking about**:\n"
                    '• "How do I migrate subscriber_email to new format?"\n'
                    '• "What\'s the new subscriber structure?"\n'
                    '• "How do timestamps work in AI metering?"\n'
                    '• "When should I provide explicit timestamps?"\n'
                    '• "What\'s the timestamp format requirement?"\n'
                    '• "Show me transaction examples"\n'
                    '• "How do I submit AI transactions?"\n\n'
                    "Or use `get_examples()` and `get_capabilities()` for comprehensive documentation!",
                )
            ]

    # Metadata Provider Implementation
    async def _get_tool_capabilities(self) -> List[ToolCapability]:
        """Get metering tool capabilities."""
        return [
            ToolCapability(
                name="AI Transaction Submission",
                description="Submit AI transaction data to Revenium metering API",
                parameters={
                    "model": "str (required) - AI model used",
                    "provider": "str (required) - AI provider",
                    "input_tokens": "int (required) - Input token count",
                    "output_tokens": "int (required) - Output token count",
                    "duration_ms": "int (required) - Request duration",
                },
                examples=[
                    "submit_ai_transaction(model='<model>', provider='<provider>', input_tokens=1500, output_tokens=800, duration_ms=2500)",
                    "submit_ai_transaction(model='<model>', provider='<provider>', input_tokens=3000, output_tokens=1200, duration_ms=5000, organization_id='acme-corp')",
                ],
            ),
            ToolCapability(
                name="Transaction Lookup by ID",
                description="Find specific transactions by their IDs. Requires transaction IDs and searches efficiently using session cache and API search.",
                parameters={
                    "transaction_ids": "list (required) - Transaction IDs to lookup",
                    "max_retries": "int (optional) - Maximum retry attempts (default: 3)",
                    "retry_interval": "int (optional) - Seconds between retries (default: 15)",
                    "search_page_range": "int|array (optional) - Pages to search (default: 50)",
                    "page_size": "int (optional) - Transactions per page (default: 1000)",
                    "early_termination": "bool (optional) - Stop when found (default: true)",
                },
                examples=[
                    "lookup_transactions(transaction_ids=['tx_abc123'])  # Single transaction lookup",
                    "lookup_transactions(transaction_ids=['tx_abc123', 'tx_def456'])  # Batch lookup",
                    "lookup_transactions(transaction_ids=['tx_abc123'], max_retries=5)  # With custom retries",
                ],
            ),
            ToolCapability(
                name="Browse Recent Transactions",
                description="Browse recent transactions with pagination. No transaction IDs required - perfect for discovery and monitoring.",
                parameters={
                    "page": "int (optional) - Page number for pagination (0-based, default: 0)",
                    "page_size": "int (optional) - Number of transactions per page (1-50, default: 20)",
                    "return_transaction_data": "str (optional) - Detail level: 'no', 'summary', 'full' (default: 'summary')",
                },
                examples=[
                    "lookup_recent_transactions()  # Get first 20 recent transactions",
                    "lookup_recent_transactions(page=1, page_size=10)  # Get next 10 transactions",
                    "lookup_recent_transactions(return_transaction_data='full')  # Get detailed transaction data",
                ],
            ),
            ToolCapability(
                name="Status Tracking",
                description="Check status of individual transactions (local session data only)",
                parameters={"transaction_id": "str (required) - Transaction ID to check"},
                examples=["get_transaction_status(transaction_id='tx_abc123def456')"],
            ),
        ]

    async def _get_supported_actions(self) -> List[str]:
        """Get supported actions."""
        return [
            "submit_ai_transaction",
            "lookup_transactions",
            "lookup_recent_transactions",
            "get_transaction_status",
            "validate",
            "get_capabilities",
            "get_examples",
            "get_agent_summary",
            "parse_natural_language",
            # AI Models Discovery Actions
            "list_ai_models",
            "search_ai_models",
            "get_supported_providers",
            "validate_model_provider",
            "estimate_transaction_cost",
            # Integration Support Actions
            "get_api_endpoints",
            "get_authentication_details",
            "get_response_formats",
            "get_integration_config",
            "get_rate_limits",
            "get_integration_guide",
            # Tiered Capability Actions (Progressive Discovery)
            "get_submission_capabilities",
            "get_lookup_capabilities",
            "get_integration_capabilities",
            "get_validation_capabilities",
            "get_field_documentation",
            "get_business_rules",
        ]

    async def _get_input_schema(self) -> Dict[str, Any]:
        """Single source of truth for manage_metering schema."""
        schema = {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": await self._get_supported_actions(),
                    "description": "Action to perform - submit_ai_transaction for basic usage, get_capabilities for full guidance",
                },
                # Core Transaction Fields (required for submit_ai_transaction)
                "model": {
                    "type": "string",
                    "description": "AI model name (e.g., 'gpt-4o', 'claude-3-5-sonnet-20241022') - required for submit_ai_transaction. Also used as a search filter for lookup_recent_transactions and analyze_recent_transactions.",
                },
                "provider": {
                    "type": "string",
                    "description": "AI provider (e.g., 'openai', 'anthropic') - required for submit_ai_transaction. Also used as a search filter for lookup_recent_transactions and analyze_recent_transactions.",
                },
                "input_tokens": {
                    "type": "integer",
                    "description": "Number of input tokens - required for submit_ai_transaction",
                },
                "output_tokens": {
                    "type": "integer",
                    "description": "Number of output tokens - required for submit_ai_transaction",
                },
                "duration_ms": {
                    "type": "integer",
                    "description": "Request duration in milliseconds - required for submit_ai_transaction",
                },
                # Enterprise Attribution Fields (optional)
                "organization_id": {
                    "type": "string",
                    "description": "Customer organization identifier for enterprise billing attribution",
                },
                "subscriber": {
                    "type": "object",
                    "description": "Subscriber object with id, email, and optional credential for billing attribution",
                },
                "trace_id": {
                    "type": "string",
                    "description": "Unique identifier for conversation/session tracking. Also used as a search filter for lookup_recent_transactions (finds all spans in a trace).",
                },
                "task_type": {
                    "type": "string",
                    "description": "Classification of AI operation for reporting and analytics. Also used as a search filter for lookup_recent_transactions.",
                },
                # Pagination and Search Control Parameters
                "search_page_range": {
                    "type": ["integer", "array"],
                    "description": "Pages to search for lookup_transactions. Integer for 0 to N-1 pages (e.g., 5 = first 5 pages), or [start, end] array for specific range (e.g., [10, 20]). Default: 5 pages (5,000 transactions)",
                },
                "page_size": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1000,
                    "description": "Transactions per API call for pagination. Use smaller values (50-100) for quick recent searches, larger values (500-1000) for comprehensive historical searches. Default: 1000 (maximum efficiency)",
                },
                "early_termination": {
                    "type": "boolean",
                    "description": "Stop searching when target transaction is found (for lookup_transactions). Default: true for efficiency",
                },
                # Verification Control Parameters
                "return_transaction_data": {
                    "oneOf": [
                        {"type": "boolean", "description": "Legacy: true=summary, false=no"},
                        {"type": "string", "enum": ["no", "summary", "full"]}
                    ],
                    "default": "no",
                    "description": "Transaction data detail level: 'no' (status only), 'summary' (core fields), 'full' (all metadata). Legacy boolean values supported for backward compatibility.",
                },
                "wait_seconds": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 300,
                    "description": "Wait time for transaction verification. Default: 30 seconds",
                },
                # Integration Guide Parameters
                "language": {
                    "type": "string",
                    "description": "Programming language for integration guide (e.g., 'python', 'javascript', 'java') - used with get_integration_guide",
                },
                "use_case": {
                    "type": "string",
                    "description": "Use case for integration guide (e.g., 'ai_transaction_submission') - used with get_integration_guide",
                },
                "example_type": {
                    "type": "string",
                    "description": "Type of examples to retrieve (e.g., 'integration_code', 'default') - used with get_examples",
                },
                "text": {
                    "type": "string",
                    "description": "Natural language query for guidance - used with parse_natural_language",
                },
                "description": {
                    "type": "string",
                    "description": "Additional description for natural language queries - used with parse_natural_language",
                },
                # Unified Transaction Lookup Parameters (lookup_transactions)
                "transaction_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Array of transaction IDs to lookup - required for lookup_transactions",
                },
                "max_retries": {
                    "type": "integer",
                    "description": "Maximum retry attempts for failed lookups (default: 3) - used with lookup_transactions",
                },
                "retry_interval": {
                    "type": "integer",
                    "description": "Seconds between retry attempts (default: 15) - used with lookup_transactions",
                },
                # Recent Transactions Lookup Parameters (lookup_recent_transactions)
                "page": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Page number for pagination (0-based, default: 0) - used with lookup_recent_transactions",
                },
                "recent_page_size": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Number of transactions per page (1-100, default: 20) - used with lookup_recent_transactions",
                },
                # Search Filters for lookup_recent_transactions and analyze_recent_transactions.
                # All filters are sent directly to the completions API; only non-None values are included.
                # Date range (biggest performance win — narrows result set server-side)
                "start_date": {
                    "type": "string",
                    "description": "Filter transactions on or after this ISO 8601 timestamp (e.g. '2026-03-10T00:00:00-06:00'). Used with lookup_recent_transactions and analyze_recent_transactions.",
                },
                "end_date": {
                    "type": "string",
                    "description": "Filter transactions on or before this ISO 8601 timestamp. Used with lookup_recent_transactions and analyze_recent_transactions.",
                },
                # Cost / performance ranges
                "total_cost_min": {
                    "type": "number",
                    "description": "Minimum total transaction cost (inclusive). e.g. 0.5 for ≥$0.50.",
                },
                "total_cost_max": {
                    "type": "number",
                    "description": "Maximum total transaction cost (inclusive).",
                },
                "request_duration_min": {
                    "type": "number",
                    "description": "Minimum request duration in milliseconds (inclusive).",
                },
                "request_duration_max": {
                    "type": "number",
                    "description": "Maximum request duration in milliseconds (inclusive).",
                },
                # Entity filters
                "organization_name": {
                    "type": "string",
                    "description": "Filter by customer organization name.",
                },
                "subscriber_id": {
                    "type": "string",
                    "description": "Filter by subscriber ID.",
                },
                "subscriber_email": {
                    "type": "string",
                    "description": "Filter by subscriber email address.",
                },
                "subscription_id": {
                    "type": "string",
                    "description": "Filter by subscription ID.",
                },
                "product_id": {
                    "type": "string",
                    "description": "Filter by product ID.",
                },
                "credential_name": {
                    "type": "string",
                    "description": "Filter by credential name.",
                },
                # Model / provider (see also "provider" above — dual-use for submission and filtering)
                "model_source": {
                    "type": "string",
                    "description": "Filter by model source.",
                },
                # Token count ranges
                "input_token_count_min": {
                    "type": "integer",
                    "description": "Minimum input token count (inclusive).",
                },
                "input_token_count_max": {
                    "type": "integer",
                    "description": "Maximum input token count (inclusive).",
                },
                "output_token_count_min": {
                    "type": "integer",
                    "description": "Minimum output token count (inclusive).",
                },
                "output_token_count_max": {
                    "type": "integer",
                    "description": "Maximum output token count (inclusive).",
                },
                "reasoning_token_count_min": {
                    "type": "integer",
                    "description": "Minimum reasoning token count (inclusive).",
                },
                "reasoning_token_count_max": {
                    "type": "integer",
                    "description": "Maximum reasoning token count (inclusive).",
                },
                "cached_token_count_min": {
                    "type": "integer",
                    "description": "Minimum cached token count (inclusive).",
                },
                "cached_token_count_max": {
                    "type": "integer",
                    "description": "Maximum cached token count (inclusive).",
                },
                "total_token_count_min": {
                    "type": "integer",
                    "description": "Minimum total token count across all token types (inclusive).",
                },
                "total_token_count_max": {
                    "type": "integer",
                    "description": "Maximum total token count across all token types (inclusive).",
                },
                # Token cost ranges
                "input_token_cost_min": {
                    "type": "number",
                    "description": "Minimum input token cost (inclusive).",
                },
                "input_token_cost_max": {
                    "type": "number",
                    "description": "Maximum input token cost (inclusive).",
                },
                "output_token_cost_min": {
                    "type": "number",
                    "description": "Minimum output token cost (inclusive).",
                },
                "output_token_cost_max": {
                    "type": "number",
                    "description": "Maximum output token cost (inclusive).",
                },
                # Streaming performance
                "time_to_first_token_min": {
                    "type": "number",
                    "description": "Minimum time-to-first-token in milliseconds (inclusive).",
                },
                "time_to_first_token_max": {
                    "type": "number",
                    "description": "Maximum time-to-first-token in milliseconds (inclusive).",
                },
                "mediation_latency_min": {
                    "type": "number",
                    "description": "Minimum mediation latency in milliseconds (inclusive).",
                },
                "mediation_latency_max": {
                    "type": "number",
                    "description": "Maximum mediation latency in milliseconds (inclusive).",
                },
                # Quality / config ranges
                "temperature_min": {
                    "type": "number",
                    "description": "Minimum temperature value (inclusive).",
                },
                "temperature_max": {
                    "type": "number",
                    "description": "Maximum temperature value (inclusive).",
                },
                "response_quality_score_min": {
                    "type": "number",
                    "description": "Minimum response quality score (inclusive).",
                },
                "response_quality_score_max": {
                    "type": "number",
                    "description": "Maximum response quality score (inclusive).",
                },
                # Quality / operational text filters (also used for submission)
                "stop_reason": {
                    "type": "string",
                    "description": "Stop reason value (e.g. 'END', 'stop'). Used as filter for lookup_recent_transactions and as a submission field.",
                },
                "operation_type": {
                    "type": "string",
                    "description": "Operation type (e.g. 'CHAT', 'COMPLETION'). Used as filter for lookup_recent_transactions and as a submission field.",
                },
                "agent": {
                    "type": "string",
                    "description": "Agent name/identifier. Used as filter for lookup_recent_transactions and as a submission field.",
                },
                "system_fingerprint": {
                    "type": "string",
                    "description": "System fingerprint value. Used as filter for lookup_recent_transactions and as a submission field.",
                },
                # Operational filters
                "error_reason": {
                    "type": "string",
                    "description": "Filter by error reason string to find failed transactions.",
                },
                # Distributed Tracing Fields (optional, for observability)
                "environment": {
                    "type": "string",
                    "description": "Deployment environment (e.g., 'production', 'staging', 'development'). Falls back to REVENIUM_ENVIRONMENT, ENVIRONMENT, or DEPLOYMENT_ENV env vars. Also used as a search filter for lookup_recent_transactions.",
                },
                "region": {
                    "type": "string",
                    "description": "Cloud region or data center (e.g., 'us-east-1', 'eu-west-1'). Falls back to REVENIUM_REGION, AWS_REGION, AZURE_REGION, or GCP_REGION env vars.",
                },
                "credential_alias": {
                    "type": "string",
                    "description": "Human-readable credential name (e.g., 'prod-api-key'). Falls back to REVENIUM_CREDENTIAL_ALIAS env var.",
                },
                "trace_type": {
                    "type": "string",
                    "description": "Categorical identifier for grouping similar workflows (e.g., 'customer-support', 'document-analysis'). Max 128 chars, alphanumeric/hyphens/underscores only. Also used as a search filter for lookup_recent_transactions.",
                },
                "trace_name": {
                    "type": "string",
                    "description": "Human-readable label for trace instances (e.g., 'Support Chat Session'). Max 256 chars, auto-truncates if longer. Also used as a search filter for lookup_recent_transactions.",
                },
                "parent_transaction_id": {
                    "type": "string",
                    "description": "Parent transaction reference for distributed tracing. Also accepts 'parentSpanId' or 'parentTransactionId'.",
                },
                "transaction_name": {
                    "type": "string",
                    "description": "Human-friendly operation name (e.g., 'Generate Response'). Also accepts 'transactionName'.",
                },
                "operation_subtype": {
                    "type": "string",
                    "description": "Additional operation context (e.g., 'function_call', 'web_search', 'sql_query').",
                },
                "retry_number": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Retry attempt number (0 = first attempt, 1 = first retry, etc.).",
                },
                "usage_metadata": {
                    "type": "object",
                    "description": "Nested object containing trace fields. All trace fields can be passed here as an alternative to top-level arguments.",
                },

                # Note: Full field list available in get_capabilities() and get_examples()
                # Note: All timestamp, quality, verification, and discovery fields supported
                # Note: System handles validation and field compatibility transparently
            },
            "required": [
                "action"
            ],  # User-centric - only action required, other fields depend on action
            "additionalProperties": True,  # Allow all supported fields for maximum flexibility
        }
        return schema

    async def _get_tool_dependencies(self) -> List[ToolDependency]:
        """Get tool dependencies."""
        return [
            ToolDependency(
                tool_name="manage_customers",
                dependency_type=DependencyType.ENHANCES,
                description="Metering can be attributed to customer organizations and subscribers",
                conditional=True,
            ),
            ToolDependency(
                tool_name="manage_products",
                dependency_type=DependencyType.ENHANCES,
                description="Transactions can be associated with specific products",
                conditional=True,
            ),
        ]

    # Integration Support Action Handlers
    async def _handle_get_api_endpoints(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get API endpoints action - provides complete API endpoint information."""
        return [
            TextContent(
                type="text",
                text="# **Revenium API Endpoints**\n\n"
                "## **API Configuration**\n\n"
                "### **Production Environment**\n"
                "- **Base URL**: `https://api.revenium.ai`\n"
                "- **Timeout**: 30 seconds (configurable via REVENIUM_TIMEOUT)\n"
                "- **SSL/TLS**: Required (HTTPS only)\n"
                "- **Content-Type**: `application/json`\n\n"
                "### **Custom Configuration**\n"
                "- **Base URL**: Configurable via `REVENIUM_BASE_URL` environment variable\n"
                "- **Default**: `https://api.revenium.ai`\n"
                "- **Use Case**: Custom deployments or specific routing requirements\n\n"
                "## **AI Metering Endpoints**\n\n"
                "### **1. Submit AI Transaction**\n"
                "```http\n"
                "POST {base_url}/meter/v2/ai/completions\n"
                "Content-Type: application/json\n"
                "Authorization: Bearer {REVENIUM_API_KEY}\n"
                "x-api-key: {REVENIUM_API_KEY}\n"
                "```\n\n"
                "**Purpose**: Submit AI usage transaction for metering and billing\n"
                "**Request Body**: JSON with transaction data (see get_examples for schemas)\n"
                "**Response**: 201 Created with transaction_id\n"
                "**Timeout**: 30 seconds\n"
                "**Rate Limit**: 1,000 requests/minute\n\n"
                "### **2. Verify Transactions**\n"
                "```http\n"
                # completions new_path is TBD in endpoint_registry; currently routes to legacy path
                "GET {base_url}/profitstream/v2/api/sources/metrics/ai/completions\n"
                "Authorization: Bearer {REVENIUM_API_KEY}\n"
                "x-api-key: {REVENIUM_API_KEY}\n"
                "```\n\n"
                "**Purpose**: Verify transaction processing status\n"
                "**Query Parameters**:\n"
                "- `transaction_ids` (optional): Comma-separated list of transaction IDs\n"
                "- `since` (optional): ISO timestamp to check transactions since\n"
                "- `limit` (optional): Maximum 1,000 transactions per request (auto-pagination available)\n"
                "**Response**: 200 OK with verification results\n"
                "**Timeout**: 30 seconds\n"
                "**Rate Limit**: 100 requests/minute\n\n"
                "### **3. Get Transaction Status**\n"
                "```http\n"
                # completions new_path is TBD in endpoint_registry; currently routes to legacy path
                "GET {base_url}/profitstream/v2/api/sources/metrics/ai/completions/{transaction_id}\n"
                "Authorization: Bearer {REVENIUM_API_KEY}\n"
                "x-api-key: {REVENIUM_API_KEY}\n"
                "```\n\n"
                "**Purpose**: Get detailed status of specific transaction\n"
                "**Path Parameters**: `transaction_id` - Transaction identifier\n"
                "**Response**: 200 OK with transaction details\n"
                "**Timeout**: 30 seconds\n"
                "**Rate Limit**: 100 requests/minute\n\n"
                "## **AI Models Discovery Endpoints**\n\n"
                "### **4. List AI Models**\n"
                "```http\n"
                "GET {base_url}/v1/ai-models?page=0&size=20\n"
                "Authorization: Bearer {REVENIUM_API_KEY}\n"
                "x-api-key: {REVENIUM_API_KEY}\n"
                "```\n\n"
                "**Purpose**: Get paginated list of supported AI models\n"
                "**Query Parameters**:\n"
                "- `page` (optional): Page number (default: 0)\n"
                "- `size` (optional): Page size (default: 20, max: 50)\n"
                "**Response**: 200 OK with model list\n\n"
                "### **5. Search AI Models**\n"
                "```http\n"
                "GET {base_url}/v1/ai-models/search?query={search_term}&page=0&size=20\n"
                "Authorization: Bearer {REVENIUM_API_KEY}\n"
                "x-api-key: {REVENIUM_API_KEY}\n"
                "```\n\n"
                "**Purpose**: Search for AI models by name or provider\n"
                "**Query Parameters**:\n"
                "- `query` (required): Search term (model name, provider, etc.)\n"
                "- `page` (optional): Page number (default: 0)\n"
                "- `size` (optional): Page size (default: 20, max: 50)\n"
                "**Response**: 200 OK with matching models\n\n"
                "## **Request Headers (All Endpoints)**\n\n"
                "### **Required Headers**\n"
                "```http\n"
                "Authorization: Bearer {REVENIUM_API_KEY}\n"
                "Content-Type: application/json\n"
                "x-api-key: {REVENIUM_API_KEY}\n"
                "```\n\n"
                "### **Optional Headers**\n"
                "```http\n"
                "User-Agent: YourApp/1.0.0\n"
                "X-Request-ID: unique-request-identifier\n"
                "Accept: application/json\n"
                "```\n\n"
                "## **Environment Configuration**\n\n"
                "### **Environment Variables**\n"
                "```bash\n"
                "# Add to .env file:\n"
                "# Required\n"
                "REVENIUM_API_KEY=rev_your_api_key_here\n\n"
                "# Optional\n"
                "REVENIUM_BASE_URL=https://api.revenium.ai\n"
                "REVENIUM_TIMEOUT=30\n"
                "```\n\n"
                "### **URL Construction Examples**\n"
                "```python\n"
                "import os\n\n"
                "base_url = os.getenv('REVENIUM_BASE_URL', 'https://api.revenium.ai')\n"
                "submit_url = f'{base_url}/meter/v2/ai/completions'\n"
                "verify_url = f'{base_url}/profitstream/v2/api/sources/metrics/ai/completions'\n"
                "models_url = f'{base_url}/v1/ai-models'\n"
                "```\n\n"
                "## **Connection Best Practices**\n\n"
                "### **HTTP Client Configuration**\n"
                "- **Connection Pooling**: Use persistent connections for better performance\n"
                "- **Timeout Settings**: Set both connection and read timeouts\n"
                "- **Retry Logic**: Implement exponential backoff for transient failures\n"
                "- **SSL Verification**: Always verify SSL certificates in production\n\n"
                "### **Error Handling**\n"
                "- **4xx Errors**: Client errors (authentication, validation)\n"
                "- **5xx Errors**: Server errors (retry with exponential backoff)\n"
                "- **Network Errors**: Connection timeouts, DNS failures\n"
                "- **Rate Limiting**: 429 status code with Retry-After header\n\n"
                "**Next Steps**: Use `get_authentication_details()` for complete auth setup\n\n"
                "**Note**: Endpoint specifications are current as of tool version. "
                "Always verify against the latest API documentation for production deployments.",
            )
        ]

    async def _handle_get_authentication_details(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get authentication details action - provides complete authentication specifications."""
        return [
            TextContent(
                type="text",
                text="# **Revenium API Authentication**\n\n"
                "## **Authentication Method**\n\n"
                "**Type**: Bearer Token Authentication with API Key\n"
                "**Security**: HTTPS required for all requests\n"
                "**Key Format**: `rev_` prefix followed by 32 alphanumeric characters\n\n"
                "## **Required HTTP Headers**\n\n"
                "### **Primary Authentication Headers**\n"
                "```http\n"
                "Authorization: Bearer {REVENIUM_API_KEY}\n"
                "x-api-key: {REVENIUM_API_KEY}\n"
                "Content-Type: application/json\n"
                "```\n\n"
                "### **Complete Header Example**\n"
                "```http\n"
                "POST /meter/v2/ai/completions HTTP/1.1\n"
                "Host: api.revenium.ai\n"
                "Authorization: Bearer rev_abc123def456ghi789jkl012mno345pq\n"
                "x-api-key: rev_abc123def456ghi789jkl012mno345pq\n"
                "Content-Type: application/json\n"
                "User-Agent: MyApp/1.0.0\n"
                "Accept: application/json\n"
                "```\n\n"
                "## **Environment Variables**\n\n"
                "### **Required Configuration**\n"
                "```bash\n"
                "# Primary API key (REQUIRED)\n"
                "REVENIUM_API_KEY=rev_your_32_character_api_key_here\n"
                "```\n\n"
                "**API Key Details**:\n"
                "- **Format**: `rev_[a-zA-Z0-9]{32}`\n"
                "- **Example**: `rev_abc123def456ghi789jkl012mno345pq`\n"
                "- **Length**: 36 characters total (rev_ + 32 chars)\n"
                "- **Case Sensitive**: Yes\n"
                "- **Where to Find**: Revenium Dashboard → Settings → API Keys\n\n"
                "### **Optional Configuration**\n"
                "```bash\n"
                "# Custom API base URL (OPTIONAL)\n"
                "REVENIUM_BASE_URL=https://api.revenium.ai\n\n"
                "# Request timeout in seconds (OPTIONAL)\n"
                "REVENIUM_TIMEOUT=30\n\n"
                "# Team and Owner IDs for advanced features (OPTIONAL)\n"
                "REVENIUM_TEAM_ID=your_team_id\n"
                "REVENIUM_OWNER_ID=your_owner_id\n"
                "```\n\n"
                "## **Authentication Implementation Examples**\n\n"
                "### **Python with aiohttp**\n"
                "```python\n"
                "import os\n"
                "import aiohttp\n\n"
                "api_key = os.getenv('REVENIUM_API_KEY')\n"
                "if not api_key:\n"
                "    raise ValueError('REVENIUM_API_KEY environment variable required')\n\n"
                "headers = {\n"
                "    'Authorization': f'Bearer {api_key}',\n"
                "    'x-api-key': api_key,\n"
                "    'Content-Type': 'application/json'\n"
                "}\n\n"
                "async with aiohttp.ClientSession(headers=headers) as session:\n"
                "    async with session.post(url, json=data) as response:\n"
                "        result = await response.json()\n"
                "```\n\n"
                "### **Python with requests**\n"
                "```python\n"
                "import os\n"
                "import requests\n\n"
                "api_key = os.getenv('REVENIUM_API_KEY')\n"
                "headers = {\n"
                "    'Authorization': f'Bearer {api_key}',\n"
                "    'x-api-key': api_key,\n"
                "    'Content-Type': 'application/json'\n"
                "}\n\n"
                "response = requests.post(url, json=data, headers=headers)\n"
                "result = response.json()\n"
                "```\n\n"
                "### **JavaScript/Node.js**\n"
                "```javascript\n"
                "const apiKey = process.env.REVENIUM_API_KEY;\n"
                "if (!apiKey) {\n"
                "    throw new Error('REVENIUM_API_KEY environment variable required');\n"
                "}\n\n"
                "const headers = {\n"
                "    'Authorization': `Bearer ${apiKey}`,\n"
                "    'x-api-key': apiKey,\n"
                "    'Content-Type': 'application/json'\n"
                "};\n\n"
                "const response = await fetch(url, {\n"
                "    method: 'POST',\n"
                "    headers: headers,\n"
                "    body: JSON.stringify(data)\n"
                "});\n"
                "```\n\n"
                "## **Authentication Error Responses**\n\n"
                "### **401 Unauthorized - Invalid API Key**\n"
                "```json\n"
                "{\n"
                '  "error": "unauthorized",\n'
                '  "message": "Invalid or missing API key",\n'
                '  "timestamp": "2025-06-22T15:30:45.123Z"\n'
                "}\n"
                "```\n\n"
                "**Common Causes**:\n"
                "- Missing `Authorization` header\n"
                "- Missing `x-api-key` header\n"
                "- Invalid API key format\n"
                "- Expired or revoked API key\n\n"
                "### **403 Forbidden - Insufficient Permissions**\n"
                "```json\n"
                "{\n"
                '  "error": "forbidden",\n'
                '  "message": "API key lacks required permissions for this operation",\n'
                '  "required_permissions": ["metering:write"],\n'
                '  "timestamp": "2025-06-22T15:30:45.123Z"\n'
                "}\n"
                "```\n\n"
                "**Common Causes**:\n"
                "- API key doesn't have metering permissions\n"
                "- API key restricted to specific operations\n"
                "- Team/organization access restrictions\n\n"
                "### **429 Rate Limited**\n"
                "```json\n"
                "{\n"
                '  "error": "rate_limit_exceeded",\n'
                '  "message": "Too many requests. Please retry after 60 seconds.",\n'
                '  "retry_after": 60,\n'
                '  "limit": 1000,\n'
                '  "remaining": 0,\n'
                '  "reset_time": "2025-06-22T15:31:45.123Z"\n'
                "}\n"
                "```\n\n"
                "## **API Key Management**\n\n"
                "### **Obtaining API Keys**\n"
                "1. **Login** to Revenium Dashboard\n"
                "2. **Navigate** to Settings → API Keys\n"
                "3. **Create** new API key with appropriate permissions\n"
                "4. **Copy** the key immediately (shown only once)\n"
                "5. **Store** securely in environment variables\n\n"
                "### **API Key Permissions**\n"
                "Required permissions for metering operations:\n"
                "- **`metering:read`** - View transaction data\n"
                "- **`metering:write`** - Submit transactions\n"
                "- **`models:read`** - Access AI models data\n\n"
                "### **API Key Security**\n"
                "- **Scope**: Limit permissions to minimum required\n"
                "- **Environment**: Use different keys for dev/staging/prod\n"
                "- **Rotation**: Rotate keys every 90 days\n"
                "- **Monitoring**: Monitor usage for anomalies\n"
                "- **Revocation**: Immediately revoke compromised keys\n\n"
                "## **Security Best Practices**\n\n"
                "### **✅ DO**\n"
                "- Store API keys in environment variables\n"
                "- Use secure key management systems (AWS Secrets Manager, etc.)\n"
                "- Implement proper error handling for auth failures\n"
                "- Monitor API key usage and set up alerts\n"
                "- Use HTTPS for all requests\n"
                "- Validate SSL certificates\n"
                "- Implement request timeouts\n"
                "- Log authentication events (without exposing keys)\n\n"
                "### **❌ DON'T**\n"
                "- Hardcode API keys in source code\n"
                "- Commit API keys to version control\n"
                "- Share API keys via email or chat\n"
                "- Use production keys in development\n"
                "- Ignore authentication errors\n"
                "- Skip SSL certificate validation\n"
                "- Log API keys in plain text\n\n"
                "## **Troubleshooting Authentication**\n\n"
                "### **Common Issues**\n"
                '1. **"Invalid API key" errors**\n'
                "   - Verify key format (starts with 'rev_')\n"
                "   - Check for extra spaces or newlines\n"
                "   - Confirm key is active in dashboard\n\n"
                '2. **"Forbidden" errors**\n'
                "   - Check API key permissions\n"
                "   - Verify team/organization access\n"
                "   - Contact admin for permission updates\n\n"
                '3. **"Rate limited" errors**\n'
                "   - Implement exponential backoff\n"
                "   - Check rate limit headers\n"
                "   - Consider request batching\n\n"
                "### **Testing Authentication**\n"
                "```bash\n"
                "# Test API key with curl\n"
                'curl -H "Authorization: Bearer $REVENIUM_API_KEY" \\\n'
                '     -H "x-api-key: $REVENIUM_API_KEY" \\\n'
                '     -H "Content-Type: application/json" \\\n'
                "     https://api.revenium.ai/v1/ai-models?page=0&size=1\n"
                "```\n\n"
                "**Next Steps**: Use `get_response_formats()` to understand API responses\n\n"
                "**Note**: Authentication requirements are current as of tool version. "
                "Always verify against the latest API documentation for production use.",
            )
        ]

    async def _handle_get_response_formats(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get response formats action - documents complete API response formats."""
        return [
            TextContent(
                type="text",
                text="# **Revenium API Response Formats**\n\n"
                "## **Success Response Formats**\n\n"
                "### **201 Created - Transaction Submitted Successfully**\n"
                "**Endpoint**: `POST /meter/v2/ai/completions`\n\n"
                "```json\n"
                "{\n"
                '  "transaction_id": "tx_9162844a6068f2b1",\n'
                '  "status": "submitted",\n'
                '  "timestamp": "2025-06-22T15:30:45.123Z",\n'
                '  "estimated_cost": 0.0125,\n'
                '  "processing_time_ms": 245\n'
                "}\n"
                "```\n\n"
                "**Field Descriptions**:\n"
                "- `transaction_id`: Unique identifier (format: tx_[16 hex chars])\n"
                "- `status`: Processing status (submitted|processing|completed|failed)\n"
                "- `timestamp`: ISO 8601 UTC timestamp with milliseconds\n"
                "- `estimated_cost`: Estimated cost in USD (optional)\n"
                "- `processing_time_ms`: Server processing time in milliseconds\n\n"
                "### **200 OK - Transaction Verification**\n"
                # completions new_path is TBD; currently routes to legacy path regardless of REVENIUM_USE_NEW_ANALYTICS_API flag
                "**Endpoint**: `GET /profitstream/v2/api/sources/metrics/ai/completions`\n\n"
                "```json\n"
                "{\n"
                '  "verified_transactions": [\n'
                "    {\n"
                '      "transaction_id": "tx_9162844a6068f2b1",\n'
                '      "status": "processed",\n'
                '      "submitted_at": "2025-06-22T15:30:45.123Z",\n'
                '      "processed_at": "2025-06-22T15:31:00.456Z",\n'
                '      "final_cost": 0.0127,\n'
                '      "billing_status": "billed"\n'
                "    }\n"
                "  ],\n"
                '  "total_verified": 1,\n'
                '  "total_requested": 1,\n'
                '  "verification_timestamp": "2025-06-22T15:32:15.789Z"\n'
                "}\n"
                "```\n\n"
                "**Field Descriptions**:\n"
                "- `verified_transactions`: Array of verified transaction objects\n"
                "- `status`: Current processing status\n"
                "- `submitted_at`: Original submission timestamp\n"
                "- `processed_at`: Processing completion timestamp\n"
                "- `final_cost`: Actual calculated cost (may differ from estimate)\n"
                "- `billing_status`: Billing processing status\n\n"
                "### **200 OK - AI Models List**\n"
                "**Endpoint**: `GET /v1/ai-models`\n\n"
                "```json\n"
                "{\n"
                '  "_embedded": {\n'
                '    "aIModelResourceList": [\n'
                "      {\n"
                '        "id": "model_123",\n'
                '        "name": "gpt-4o",\n'
                '        "provider": "openai",\n'
                '        "inputCostPerToken": 0.000005,\n'
                '        "outputCostPerToken": 0.000015,\n'
                '        "supportFunctionCalling": true,\n'
                '        "supportsVision": true,\n'
                '        "supportsPromptCaching": false,\n'
                '        "maxTokens": 128000,\n'
                '        "contextWindow": 128000\n'
                "      }\n"
                "    ]\n"
                "  },\n"
                '  "page": {\n'
                '    "size": 20,\n'
                '    "totalElements": 156,\n'
                '    "totalPages": 8,\n'
                '    "number": 0\n'
                "  }\n"
                "}\n"
                "```\n\n"
                "## **Error Response Formats**\n\n"
                "### **400 Bad Request - Validation Errors**\n"
                "```json\n"
                "{\n"
                '  "error": "validation_failed",\n'
                '  "message": "Request validation failed",\n'
                '  "timestamp": "2025-06-22T15:30:45.123Z",\n'
                '  "path": "/meter/v2/ai/completions",\n'
                '  "details": {\n'
                '    "field_errors": [\n'
                "      {\n"
                '        "field": "input_tokens",\n'
                '        "error": "Must be a positive integer",\n'
                '        "value": -100,\n'
                '        "constraint": "min=1, max=10000000"\n'
                "      },\n"
                "      {\n"
                '        "field": "model",\n'
                '        "error": "Model not found or unsupported",\n'
                '        "value": "invalid-model",\n'
                '        "suggestion": "Use list_ai_models() to see supported models"\n'
                "      }\n"
                "    ],\n"
                '    "validation_summary": {\n'
                '      "total_errors": 2,\n'
                '      "critical_errors": 1,\n'
                '      "warnings": 0\n'
                "    }\n"
                "  }\n"
                "}\n"
                "```\n\n"
                "**Common Validation Errors**:\n"
                "- Invalid token counts (negative, zero, or too large)\n"
                "- Unsupported model/provider combinations\n"
                "- Invalid field formats (timestamps, emails, etc.)\n"
                "- Missing required fields\n"
                "- Field length violations\n\n"
                "### **401 Unauthorized - Authentication Failed**\n"
                "```json\n"
                "{\n"
                '  "error": "unauthorized",\n'
                '  "message": "Authentication failed",\n'
                '  "timestamp": "2025-06-22T15:30:45.123Z",\n'
                '  "details": {\n'
                '    "reason": "invalid_api_key",\n'
                '    "provided_key_format": "rev_***...***",\n'
                '    "suggestions": [\n'
                "      \"Verify API key format (should start with 'rev_')\",\n"
                '      "Check for extra spaces or newlines",\n'
                '      "Ensure key is active in dashboard"\n'
                "    ]\n"
                "  }\n"
                "}\n"
                "```\n\n"
                "### **403 Forbidden - Insufficient Permissions**\n"
                "```json\n"
                "{\n"
                '  "error": "forbidden",\n'
                '  "message": "Insufficient permissions for this operation",\n'
                '  "timestamp": "2025-06-22T15:30:45.123Z",\n'
                '  "details": {\n'
                '    "required_permissions": ["metering:write"],\n'
                '    "current_permissions": ["metering:read"],\n'
                '    "api_key_id": "key_***...***",\n'
                '    "suggestions": [\n'
                '      "Contact administrator to update API key permissions",\n'
                '      "Use a different API key with write permissions",\n'
                '      "Check team/organization access settings"\n'
                "    ]\n"
                "  }\n"
                "}\n"
                "```\n\n"
                "### **404 Not Found - Resource Not Found**\n"
                "```json\n"
                "{\n"
                '  "error": "not_found",\n'
                '  "message": "Requested resource not found",\n'
                '  "timestamp": "2025-06-22T15:30:45.123Z",\n'
                '  "details": {\n'
                '    "resource_type": "transaction",\n'
                '    "resource_id": "tx_nonexistent123",\n'
                '    "suggestions": [\n'
                '      "Verify transaction ID format",\n'
                '      "Check if transaction was submitted successfully",\n'
                '      "Use lookup_transactions() to search for transaction by ID",\n'
                '      "Use lookup_recent_transactions() if you want a list of all recent transactions"\n'
                "    ]\n"
                "  }\n"
                "}\n"
                "```\n\n"
                "### **429 Too Many Requests - Rate Limited**\n"
                "```json\n"
                "{\n"
                '  "error": "rate_limit_exceeded",\n'
                '  "message": "Rate limit exceeded. Please retry after specified delay.",\n'
                '  "timestamp": "2025-06-22T15:30:45.123Z",\n'
                '  "details": {\n'
                '    "limit": 1000,\n'
                '    "remaining": 0,\n'
                '    "reset_time": "2025-06-22T15:31:45.123Z",\n'
                '    "retry_after": 60,\n'
                '    "window": "1 minute",\n'
                '    "suggestions": [\n'
                '      "Implement exponential backoff retry logic",\n'
                '      "Consider request batching to reduce call frequency",\n'
                '      "Monitor rate limit headers in responses"\n'
                "    ]\n"
                "  }\n"
                "}\n"
                "```\n\n"
                "### **500 Internal Server Error - Server Issues**\n"
                "```json\n"
                "{\n"
                '  "error": "internal_server_error",\n'
                '  "message": "An unexpected server error occurred",\n'
                '  "timestamp": "2025-06-22T15:30:45.123Z",\n'
                '  "details": {\n'
                '    "request_id": "req_abc123def456ghi789",\n'
                '    "error_code": "DB_CONNECTION_TIMEOUT",\n'
                '    "suggestions": [\n'
                '      "Retry the request after a brief delay",\n'
                '      "Implement exponential backoff for server errors",\n'
                '      "Contact support if error persists with request_id"\n'
                "    ]\n"
                "  }\n"
                "}\n"
                "```\n\n"
                "## **Response Headers**\n\n"
                "### **Standard Headers (All Responses)**\n"
                "```http\n"
                "Content-Type: application/json; charset=utf-8\n"
                "X-Request-ID: req_abc123def456ghi789\n"
                "X-Response-Time: 245ms\n"
                "Date: Fri, 22 Jun 2025 15:30:45 GMT\n"
                "```\n\n"
                "### **Rate Limiting Headers**\n"
                "```http\n"
                "X-RateLimit-Limit: 1000\n"
                "X-RateLimit-Remaining: 999\n"
                "X-RateLimit-Reset: 1719067845\n"
                "X-RateLimit-Window: 60\n"
                "```\n\n"
                "**Header Descriptions**:\n"
                "- `X-RateLimit-Limit`: Maximum requests per time window\n"
                "- `X-RateLimit-Remaining`: Requests remaining in current window\n"
                "- `X-RateLimit-Reset`: Unix timestamp when limit resets\n"
                "- `X-RateLimit-Window`: Time window in seconds\n\n"
                "### **Error-Specific Headers**\n"
                "```http\n"
                "# For 429 Rate Limited responses\n"
                "Retry-After: 60\n\n"
                "# For 503 Service Unavailable responses\n"
                "Retry-After: 300\n\n"
                "# For authentication errors\n"
                'WWW-Authenticate: Bearer realm="Revenium API"\n'
                "```\n\n"
                "## **Response Processing Guidelines**\n\n"
                "### **Success Response Handling**\n"
                "```python\n"
                "async def handle_success_response(response):\n"
                "    if response.status == 201:\n"
                "        data = await response.json()\n"
                "        transaction_id = data['transaction_id']\n"
                "        print(f'Transaction submitted: {transaction_id}')\n"
                "        return data\n"
                "    elif response.status == 200:\n"
                "        data = await response.json()\n"
                "        return data\n"
                "```\n\n"
                "### **Error Response Handling**\n"
                "```python\n"
                "async def handle_error_response(response):\n"
                "    error_data = await response.json()\n"
                "    error_type = error_data.get('error')\n"
                "    message = error_data.get('message')\n"
                "    \n"
                "    if response.status == 400:\n"
                "        # Handle validation errors\n"
                "        field_errors = error_data.get('details', {}).get('field_errors', [])\n"
                "        for field_error in field_errors:\n"
                "            print(f\"Field {field_error['field']}: {field_error['error']}\")\n"
                "    elif response.status == 429:\n"
                "        # Handle rate limiting\n"
                "        retry_after = error_data.get('details', {}).get('retry_after', 60)\n"
                "        await asyncio.sleep(retry_after)\n"
                "    elif response.status >= 500:\n"
                "        # Handle server errors with exponential backoff\n"
                "        request_id = error_data.get('details', {}).get('request_id')\n"
                '        print(f"Server error (request_id: {request_id}): {message}")\n'
                "```\n\n"
                "### **Response Validation**\n"
                "```python\n"
                "def validate_response_format(data, expected_fields):\n"
                '    """Validate response contains expected fields."""\n'
                "    missing_fields = []\n"
                "    for field in expected_fields:\n"
                "        if field not in data:\n"
                "            missing_fields.append(field)\n"
                "    \n"
                "    if missing_fields:\n"
                '        raise ValueError(f"Missing expected fields: {missing_fields}")\n'
                "    \n"
                "    return True\n"
                "```\n\n"
                "## **Content-Type Handling**\n\n"
                "### **Request Content-Type**\n"
                "- **Required**: `application/json` for all POST/PUT requests\n"
                "- **Character Encoding**: UTF-8 (default)\n"
                "- **JSON Format**: Valid JSON with proper escaping\n\n"
                "### **Response Content-Type**\n"
                "- **Standard**: `application/json; charset=utf-8`\n"
                "- **Error Responses**: Always JSON format\n"
                "- **Empty Responses**: May have `application/json` with empty body\n\n"
                "**Next Steps**: Use `get_rate_limits()` for rate limiting details\n\n"
                "**Note**: Response formats are current as of tool version. "
                "Always validate against the latest API documentation for production use.",
            )
        ]

    async def _handle_get_integration_config(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get integration config action - provides environment setup guidance."""
        language = arguments.get("language", "python")
        return [
            TextContent(
                type="text",
                text="# **Integration Configuration**\n\n"
                "## **Environment Setup**\n\n"
                "### **Required Environment Variables**\n\n"
                "**REVENIUM_API_KEY**\n"
                "- Description: Your Revenium API key for authentication\n"
                "- Format: `rev_[a-zA-Z0-9]{32}`\n"
                "- Example: `rev_abc123def456ghi789jkl012mno345pq`\n"
                "- Where to find: Revenium Dashboard > Settings > API Keys\n\n"
                "### **Optional Environment Variables**\n\n"
                "**REVENIUM_BASE_URL**\n"
                "- Description: Custom API base URL\n"
                "- Default: `https://api.revenium.ai`\n"
                "- Use cases: Testing, On-premise deployments\n\n"
                "**REVENIUM_TIMEOUT**\n"
                "- Description: Request timeout in seconds\n"
                "- Default: 30\n"
                "- Type: Integer\n\n"
                f"## **{language.title()} Configuration**\n\n"
                "### **.env File**\n"
                "```bash\n"
                "# Revenium API Configuration\n"
                "REVENIUM_API_KEY=rev_your_key_here\n"
                "REVENIUM_BASE_URL=https://api.revenium.ai\n"
                "REVENIUM_TIMEOUT=30\n"
                "```\n\n"
                "### **Code Example**\n"
                "```python\n"
                "import os\n"
                "from typing import Optional\n\n"
                "# Load configuration from environment\n"
                "api_key = os.getenv('REVENIUM_API_KEY')\n"
                "base_url = os.getenv('REVENIUM_BASE_URL', 'https://api.revenium.ai')\n"
                "timeout = int(os.getenv('REVENIUM_TIMEOUT', '30'))\n\n"
                "if not api_key:\n"
                "    raise ValueError('REVENIUM_API_KEY environment variable is required')\n\n"
                "# HTTP headers for API requests\n"
                "headers = {\n"
                "    'Authorization': f'Bearer {api_key}',\n"
                "    'Content-Type': 'application/json',\n"
                "    'x-api-key': api_key\n"
                "}\n"
                "```\n\n"
                "## **Security Best Practices**\n\n"
                "1. **Never hardcode API keys** in source code\n"
                "2. **Use environment variables** or secure key management systems\n"
                "3. **Rotate API keys regularly** (recommended: every 90 days)\n"
                "4. **Use different keys** for different environments (dev/staging/prod)\n"
                "5. **Monitor API key usage** for suspicious activity\n"
                "6. **Restrict API key permissions** to minimum required scope\n\n"
                "## **Troubleshooting**\n\n"
                "### **Common Issues**\n"
                "- **401 Unauthorized**: Check API key format and validity\n"
                "- **403 Forbidden**: Verify API key has required permissions\n"
                "- **Connection Timeout**: Check network connectivity and timeout settings\n"
                "- **SSL Errors**: Ensure proper SSL/TLS configuration\n\n"
                "### **Debugging Tips**\n"
                "- Enable request logging to see full HTTP requests/responses\n"
                "- Verify environment variables are loaded correctly\n"
                "- Test with a simple API call first (e.g., get capabilities)\n"
                "- Check API key permissions in Revenium Dashboard\n\n"
                "**Note**: Configuration requirements may change. Always refer to "
                "the latest documentation for current setup instructions.",
            )
        ]

    async def _handle_get_rate_limits(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get rate limits action - provides API rate limiting information."""
        return [
            TextContent(
                type="text",
                text="# **API Rate Limits**\n\n"
                "## **Rate Limit Overview**\n\n"
                "Revenium API implements rate limiting to ensure fair usage and system stability.\n\n"
                "### **Transaction Submission Limits**\n"
                "- **Requests per minute**: 1,000\n"
                "- **Requests per hour**: 50,000\n"
                "- **Burst limit**: 100 requests in 10 seconds\n"
                "- **Concurrent requests**: 10\n\n"
                "### **Verification Limits**\n"
                "- **Requests per minute**: 100\n"
                "- **Requests per hour**: 5,000\n\n"
                "## **Rate Limit Headers**\n\n"
                "API responses include rate limit information:\n\n"
                "```http\n"
                "X-RateLimit-Limit: 1000\n"
                "X-RateLimit-Remaining: 999\n"
                "X-RateLimit-Reset: 1640995200\n"
                "```\n\n"
                "- **X-RateLimit-Limit**: Maximum requests allowed per time window\n"
                "- **X-RateLimit-Remaining**: Requests remaining in current window\n"
                "- **X-RateLimit-Reset**: Unix timestamp when limit resets\n\n"
                "## **Rate Limit Exceeded Response**\n\n"
                "When rate limit is exceeded, you'll receive:\n\n"
                "```http\n"
                "HTTP/1.1 429 Too Many Requests\n"
                "Content-Type: application/json\n"
                "Retry-After: 60\n\n"
                "{\n"
                '  "error": "rate_limit_exceeded",\n'
                '  "message": "Rate limit exceeded. Please retry after 60 seconds.",\n'
                '  "retry_after": 60\n'
                "}\n"
                "```\n\n"
                "## **Retry Strategies**\n\n"
                "### **Exponential Backoff**\n"
                "```python\n"
                "import time\n"
                "import random\n\n"
                "def exponential_backoff_retry(func, max_retries=5):\n"
                "    for attempt in range(max_retries):\n"
                "        try:\n"
                "            return func()\n"
                "        except RateLimitError as e:\n"
                "            if attempt == max_retries - 1:\n"
                "                raise\n"
                "            \n"
                "            # Exponential backoff with jitter\n"
                "            delay = (2 ** attempt) + random.uniform(0, 1)\n"
                "            time.sleep(min(delay, 60))  # Cap at 60 seconds\n"
                "```\n\n"
                "### **Rate Limit Specific Handling**\n"
                "```python\n"
                "def handle_rate_limit(response):\n"
                "    if response.status_code == 429:\n"
                "        retry_after = int(response.headers.get('Retry-After', 60))\n"
                "        print(f'Rate limited. Waiting {retry_after} seconds...')\n"
                "        time.sleep(retry_after)\n"
                "        return True  # Retry the request\n"
                "    return False\n"
                "```\n\n"
                "## **Best Practices**\n\n"
                "1. **Monitor rate limit headers** in every response\n"
                "2. **Implement exponential backoff** for 429 responses\n"
                "3. **Use batch operations** when possible to reduce request count\n"
                "4. **Implement circuit breaker pattern** for sustained errors\n"
                "5. **Cache responses** when appropriate to reduce API calls\n"
                "6. **Distribute load** across multiple time windows\n"
                "7. **Use connection pooling** to reduce connection overhead\n\n"
                "## **Rate Limit Optimization**\n\n"
                "### **Batch Processing**\n"
                "- Submit multiple transactions in a single request when supported\n"
                "- Group verification requests by time ranges\n\n"
                "### **Intelligent Scheduling**\n"
                "- Spread requests evenly across time windows\n"
                "- Avoid burst patterns that quickly exhaust limits\n\n"
                "### **Caching Strategy**\n"
                "- Cache static data (model lists, provider information)\n"
                "- Use conditional requests with ETags when available\n\n"
                "**Note**: Rate limits may be adjusted based on usage patterns and "
                "system capacity. Monitor the API documentation for updates.",
            )
        ]

    async def _handle_get_integration_guide(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get integration guide action - provides comprehensive integration guidance."""
        language = arguments.get("language", "python")
        use_case = arguments.get("use_case", "ai_transaction_submission")

        # Validate supported languages
        if language.lower() == "java":
            from ..common.error_handling import (
                create_structured_validation_error,
                format_structured_error,
            )

            error = create_structured_validation_error(
                message="Java integration guide is not supported",
                field="language",
                value=language,
                suggestions=[
                    "Use language='python' for comprehensive Python integration guidance",
                    "Use language='javascript' for Node.js integration guidance with official package references",
                    "Supported languages are: python, javascript",
                ],
                examples={
                    "python_guide": "get_integration_guide(language='python')",
                    "javascript_guide": "get_integration_guide(language='javascript')",
                    "supported_languages": ["python", "javascript"],
                },
            )
            return [TextContent(type="text", text=format_structured_error(error))]

        # Route to language-specific implementations
        if language.lower() == "javascript":
            return await self._get_javascript_integration_guide(use_case)
        else:
            # Default to Python (includes "python" and any other values)
            return await self._get_python_integration_guide(use_case)

    async def _get_python_integration_guide(
        self, use_case: str
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Get Python-specific integration guide."""
        return [
            TextContent(
                type="text",
                text="# **Complete Integration Guide**\n\n"
                f"## **Python Integration for {use_case.replace('_', ' ').title()}**\n\n"
                "### **Prerequisites**\n\n"
                "1. **Revenium API Key** - Get from Dashboard > Settings > API Keys\n"
                "2. **Python 3.8+** - Required for async/await support\n"
                "3. **HTTP Client Library** - `aiohttp` recommended for async operations\n\n"
                "```bash\n"
                "pip install aiohttp python-dotenv\n"
                "```\n\n"
                "### **Step 1: Environment Setup**\n\n"
                "Create `.env` file:\n"
                "```bash\n"
                "REVENIUM_API_KEY=rev_your_key_here\n"
                "REVENIUM_BASE_URL=https://api.revenium.ai\n"
                "```\n\n"
                "### **Step 2: Basic Client Implementation**\n\n"
                "```python\n"
                "import os\n"
                "import aiohttp\n"
                "import asyncio\n"
                "from typing import Dict, Any, Optional\n"
                "from dotenv import load_dotenv\n\n"
                "load_dotenv()\n\n"
                "class ReveniumMeteringClient:\n"
                "    def __init__(self):\n"
                "        self.api_key = os.getenv('REVENIUM_API_KEY')\n"
                "        self.base_url = os.getenv('REVENIUM_BASE_URL', 'https://api.revenium.ai')\n"
                "        \n"
                "        if not self.api_key:\n"
                "            raise ValueError('REVENIUM_API_KEY environment variable required')\n"
                "        \n"
                "        self.headers = {\n"
                "            'Authorization': f'Bearer {self.api_key}',\n"
                "            'Content-Type': 'application/json',\n"
                "            'x-api-key': self.api_key\n"
                "        }\n\n"
                "    async def submit_transaction(self, transaction_data: Dict[str, Any]) -> Dict[str, Any]:\n"
                '        """Submit AI transaction for metering."""\n'
                "        url = f'{self.base_url}/meter/v2/ai/completions'\n"
                "        \n"
                "        async with aiohttp.ClientSession() as session:\n"
                "            async with session.post(url, json=transaction_data, headers=self.headers) as response:\n"
                "                if response.status == 201:\n"
                "                    return await response.json()\n"
                "                elif response.status == 429:\n"
                "                    retry_after = int(response.headers.get('Retry-After', 60))\n"
                "                    raise RateLimitError(f'Rate limited. Retry after {retry_after} seconds')\n"
                "                else:\n"
                "                    error_data = await response.json()\n"
                "                    raise APIError(f'API Error {response.status}: {error_data}')\n"
                "```\n\n"
                "### **Step 3: Error Handling**\n\n"
                "```python\n"
                "class APIError(Exception):\n"
                "    pass\n\n"
                "class RateLimitError(APIError):\n"
                "    pass\n\n"
                "async def submit_with_retry(client, transaction_data, max_retries=3):\n"
                '    """Submit transaction with automatic retry logic."""\n'
                "    for attempt in range(max_retries):\n"
                "        try:\n"
                "            return await client.submit_transaction(transaction_data)\n"
                "        except RateLimitError as e:\n"
                "            if attempt == max_retries - 1:\n"
                "                raise\n"
                "            await asyncio.sleep(2 ** attempt)  # Exponential backoff\n"
                "        except APIError as e:\n"
                "            print(f'API Error on attempt {attempt + 1}: {e}')\n"
                "            if attempt == max_retries - 1:\n"
                "                raise\n"
                "```\n\n"
                "### **Step 4: Complete Example**\n\n"
                "```python\n"
                "async def main():\n"
                "    client = ReveniumMeteringClient()\n"
                "    \n"
                "    # Example transaction data\n"
                "    transaction = {\n"
                "        'model': 'gpt-4o',\n"
                "        'provider': 'openai',\n"
                "        'inputTokenCount': 1500,\n"
                "        'outputTokenCount': 800,\n"
                "        'requestDuration': 2500,\n"
                "        'requestTime': '2024-01-01T00:00:00Z',\n"
                "        'completionStartTime': '2024-01-01T00:00:01Z',\n"
                "        'responseTime': '2024-01-01T00:00:02Z',\n"
                "        'stopReason': 'stop',\n"
                "        'organizationId': 'my-org',\n"
                "        'taskType': 'text_generation'\n"
                "    }\n"
                "    \n"
                "    try:\n"
                "        result = await submit_with_retry(client, transaction)\n"
                "        print(f'Transaction submitted: {result[\"transaction_id\"]}')\n"
                "    except Exception as e:\n"
                "        print(f'Failed to submit transaction: {e}')\n\n"
                "if __name__ == '__main__':\n"
                "    asyncio.run(main())\n"
                "```\n\n"
                "### **Step 5: Testing and Validation**\n\n"
                "1. **Test with staging environment** first\n"
                "2. **Verify transactions appear** in Revenium Dashboard\n"
                "3. **Test error handling** with invalid data\n"
                "4. **Monitor rate limits** during high-volume testing\n"
                "5. **Validate cost calculations** match expected values\n\n"
                "### **Production Considerations**\n\n"
                "1. **Connection Pooling**: Use persistent HTTP connections\n"
                "2. **Logging**: Implement comprehensive request/response logging\n"
                "3. **Monitoring**: Track API response times and error rates\n"
                "4. **Circuit Breaker**: Implement circuit breaker for API failures\n"
                "5. **Graceful Degradation**: Handle API unavailability gracefully\n\n"
                "### **Additional Resources**\n\n"
                "- **API Documentation**: Latest endpoint specifications\n"
                "- **Model Validation**: Use AI models tools to verify compatibility\n"
                "- **Dashboard**: Monitor transactions and costs in real-time\n"
                "- **Support**: Contact support for integration assistance\n\n"
                "**Note**: This guide provides a foundation for integration. "
                "Customize based on your specific requirements and architecture.",
            )
        ]

    async def _get_javascript_integration_guide(
        self, use_case: str
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Get JavaScript/Node.js-specific integration guide with official package references."""
        return [
            TextContent(
                type="text",
                text="# **Complete Integration Guide**\n\n"
                f"## **JavaScript/Node.js Integration for {use_case.replace('_', ' ').title()}**\n\n"
                "### **🚀 Official Revenium Node.js Packages (Recommended)**\n\n"
                "**For production use, see Revenium's official Node.js packages:**\n"
                "📦 **https://app.revenium.ai** - Review the get connected section\n\n"
                "The official packages provide:\n"
                "- ✅ **Production-ready implementations** with full TypeScript support\n"
                "- ✅ **Comprehensive up-to-date examples** maintained by the Revenium team\n"
                "- ✅ **Latest API compatibility** and automatic updates\n"
                "**⚠️ Important**: Always obtain the latest examples and implementation guidance from the official npm packages above, as they are continuously updated with the most current API specifications and best practices.\n\n"
                "### **Basic Integration Overview**\n\n"
                "For basic integration concepts, the general approach involves:\n\n"
                "1. **Install official Revenium package** from npm\n"
                "2. **Configure API credentials** using environment variables\n"
                "3. **Add small code snippet to wrap normal AI calls with Revenium metering**\n"
                "### **Environment Setup**\n\n"
                "```bash\n"
                "# Environment variables (standard across all implementations)\n"
                "REVENIUM_API_KEY=rev_your_key_here\n"
                "REVENIUM_BASE_URL=https://api.revenium.ai\n"
                "```\n\n"
                "### **Next Steps**\n\n"
                "1. **Visit Revenium**: https://app.revenium.ai and review the get connected section\n"
                "2. **Review the latest documentation** and examples provided there\n"
                "3. **Install the appropriate package** for your Node.js version\n"
                "4. **Follow the official integration examples** for your specific use case\n\n"
                "### **Support Resources**\n\n"
                "- **Get Connected**: https://app.revenium.ai\n"
                "- **API Documentation**: Latest endpoint specifications\n"
                "- **Dashboard**: Monitor transactions and costs in real-time\n"
                "- **Support**: Contact support for integration assistance\n\n"
                "**Note**: This MCP tool provides Python-focused integration guidance. "
                "For JavaScript/Node.js, always refer to the official npm packages for the most current and comprehensive implementation examples.",
            )
        ]

    # Tiered Capability Action Handlers (Progressive Discovery)
    async def _handle_get_submission_capabilities(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get submission capabilities action - provides complete field specifications, validation rules, and submission examples."""
        # Get UCM capabilities if available (following established pattern)
        ucm_capabilities = None
        if self.ucm_helper:
            try:
                ucm_capabilities = await self.ucm_helper.ucm.get_capabilities("metering")
            except Exception:
                # Use static content if UCM unavailable
                pass

        content = await self._build_submission_capabilities_content(ucm_capabilities)
        return [TextContent(type="text", text=content)]

    async def _handle_get_lookup_capabilities(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get lookup capabilities action - provides transaction lookup methods, detail control, and pagination optimization."""
        # Get UCM capabilities if available (following established pattern)
        ucm_capabilities = None
        if self.ucm_helper:
            try:
                ucm_capabilities = await self.ucm_helper.ucm.get_capabilities("metering")
            except Exception:
                # Use static content if UCM unavailable
                pass

        content = await self._build_lookup_capabilities_content(ucm_capabilities)
        return [TextContent(type="text", text=content)]

    async def _handle_get_integration_capabilities(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get integration capabilities action - provides API integration guide with code examples for Python and JavaScript."""
        # Get UCM capabilities if available (following established pattern)
        ucm_capabilities = None
        if self.ucm_helper:
            try:
                ucm_capabilities = await self.ucm_helper.ucm.get_capabilities("metering")
            except Exception:
                # Use static content if UCM unavailable
                pass

        content = await self._build_integration_capabilities_content(ucm_capabilities)
        return [TextContent(type="text", text=content)]

    async def _handle_get_validation_capabilities(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get validation capabilities action - provides business rules, critical warnings, and field validation requirements."""
        # Get UCM capabilities if available (following established pattern)
        ucm_capabilities = None
        if self.ucm_helper:
            try:
                ucm_capabilities = await self.ucm_helper.ucm.get_capabilities("metering")
            except Exception:
                # Use static content if UCM unavailable
                pass

        content = await self._build_validation_capabilities_content(ucm_capabilities)
        return [TextContent(type="text", text=content)]

    async def _handle_get_field_documentation(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get field documentation action - provides complete field specifications and compatibility matrix."""
        # Get UCM capabilities if available (following established pattern)
        ucm_capabilities = None
        if self.ucm_helper:
            try:
                ucm_capabilities = await self.ucm_helper.ucm.get_capabilities("metering")
            except Exception:
                # Use static content if UCM unavailable
                pass

        content = await self._build_field_documentation_content(ucm_capabilities)
        return [TextContent(type="text", text=content)]

    async def _handle_get_business_rules(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle get business rules action - provides detailed validation requirements and critical warnings."""
        # Get UCM capabilities if available (following established pattern)
        ucm_capabilities = None
        if self.ucm_helper:
            try:
                ucm_capabilities = await self.ucm_helper.ucm.get_capabilities("metering")
            except Exception:
                # Use static content if UCM unavailable
                pass

        content = await self._build_business_rules_content(ucm_capabilities)
        return [TextContent(type="text", text=content)]


# Create consolidated instance for backward compatibility
# Note: UCM-enhanced instances are created in introspection registration
# Module-level instantiation removed to prevent UCM warnings during import
# metering_management = MeteringManagement(ucm_helper=None)
