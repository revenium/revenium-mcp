"""Unit tests for MeteringManagement response formatter methods.

Covers:
- _format_transaction_summary
- _format_full_transaction_details
- _format_cost_breakdown
- _format_performance_metrics
- _format_attribution_details
- _format_session_tracking
- _format_quality_streaming
- _format_timestamps
- _format_subscriber_details
"""


from src.revenium_mcp_server.tools_decomposed.metering_management import (
    MeteringManagement,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def make_mm() -> MeteringManagement:
    return MeteringManagement(ucm_helper=None)


FULL_TRANSACTION = {
    "model": "gpt-4",
    "provider": "OPENAI",
    "inputTokenCount": 1500,
    "outputTokenCount": 800,
    "inputTokenCost": 0.045,
    "outputTokenCost": 0.048,
    "totalCost": 0.093,
    "requestDuration": 2500,
    "timeToFirstToken": 350,
    "tokensPerMinute": 920,
    "taskType": "code_generation",
    "agent": "copilot-v2",
    "organization": {"label": "Acme Corp", "name": "acme", "id": "org_1"},
    "product": {"label": "API Gateway", "name": "api-gw", "id": "prod_1"},
    "subscriptionId": "sub_42",
    "subscriberEmail": "dev@acme.com",
    "subscriberId": "usr_99",
    "subscriberCredential": {"label": "Main Key", "name": "main-key"},
    "traceId": "trace_abc123",
    "operationType": "completion",
    "responseQualityScore": 0.95,
    "isStreamed": True,
    "stopReason": "end_turn",
    "requestTime": "2024-06-15T12:00:00.000Z",
    "responseTime": "2024-06-15T12:00:02.500Z",
    "completionStartTime": "2024-06-15T12:00:00.350Z",
}


# ===========================================================================
# _format_transaction_summary
# ===========================================================================


class TestFormatTransactionSummary:
    """Verify core summary formatting."""

    def setup_method(self):
        self.mm = make_mm()

    def test_includes_model(self):
        result = self.mm._format_transaction_summary(FULL_TRANSACTION)
        assert "**Model**: gpt-4" in result

    def test_includes_provider(self):
        result = self.mm._format_transaction_summary(FULL_TRANSACTION)
        assert "**Provider**: OPENAI" in result

    def test_includes_input_tokens(self):
        result = self.mm._format_transaction_summary(FULL_TRANSACTION)
        assert "**Input Tokens**: 1500" in result

    def test_includes_output_tokens(self):
        result = self.mm._format_transaction_summary(FULL_TRANSACTION)
        assert "**Output Tokens**: 800" in result

    def test_timestamp_excluded_by_default(self):
        result = self.mm._format_transaction_summary(FULL_TRANSACTION)
        assert "Request Time" not in result

    def test_timestamp_included_when_requested(self):
        result = self.mm._format_transaction_summary(FULL_TRANSACTION, include_timestamp=True)
        assert "**Request Time**: 2024-06-15T12:00:00.000Z" in result

    def test_missing_fields_show_na(self):
        result = self.mm._format_transaction_summary({})
        assert "N/A" in result

    def test_partial_data(self):
        result = self.mm._format_transaction_summary({"model": "claude-3"})
        assert "**Model**: claude-3" in result
        assert "**Provider**: N/A" in result


# ===========================================================================
# _format_cost_breakdown
# ===========================================================================


class TestFormatCostBreakdown:
    """Verify cost formatting with rate calculations."""

    def setup_method(self):
        self.mm = make_mm()

    def test_empty_data_returns_empty(self):
        result = self.mm._format_cost_breakdown({})
        assert result == ""

    def test_no_cost_fields_returns_empty(self):
        result = self.mm._format_cost_breakdown({"model": "gpt-4"})
        assert result == ""

    def test_full_cost_breakdown(self):
        result = self.mm._format_cost_breakdown(FULL_TRANSACTION)
        assert "Cost Breakdown" in result
        assert "Input Cost" in result
        assert "Output Cost" in result
        assert "Total Cost" in result

    def test_input_cost_rate_calculation(self):
        data = {"inputTokenCost": 0.03, "inputTokenCount": 1000}
        result = self.mm._format_cost_breakdown(data)
        assert "$0.030000" in result
        assert "1000 tokens" in result

    def test_zero_input_tokens_no_division_error(self):
        data = {"inputTokenCost": 0.01, "inputTokenCount": 0}
        result = self.mm._format_cost_breakdown(data)
        assert "Input Cost" in result

    def test_zero_output_tokens_no_division_error(self):
        data = {"outputTokenCost": 0.02, "outputTokenCount": 0}
        result = self.mm._format_cost_breakdown(data)
        assert "Output Cost" in result

    def test_total_cost_only(self):
        data = {"totalCost": 0.5}
        result = self.mm._format_cost_breakdown(data)
        assert "Total Cost" in result
        assert "$0.500000" in result
        assert "Input Cost" not in result


# ===========================================================================
# _format_performance_metrics
# ===========================================================================


class TestFormatPerformanceMetrics:
    """Verify performance metrics formatting."""

    def setup_method(self):
        self.mm = make_mm()

    def test_empty_data_returns_empty(self):
        assert self.mm._format_performance_metrics({}) == ""

    def test_all_metrics_present(self):
        result = self.mm._format_performance_metrics(FULL_TRANSACTION)
        assert "Performance Metrics" in result
        assert "**Duration**: 2500ms" in result
        assert "**Time to First Token**: 350ms" in result
        assert "**Tokens per Minute**: 920" in result

    def test_duration_only(self):
        result = self.mm._format_performance_metrics({"requestDuration": 1000})
        assert "**Duration**: 1000ms" in result
        assert "Time to First Token" not in result

    def test_no_perf_fields_returns_empty(self):
        result = self.mm._format_performance_metrics({"model": "gpt-4"})
        assert result == ""


# ===========================================================================
# _format_attribution_details
# ===========================================================================


class TestFormatAttributionDetails:
    """Verify attribution formatting with nested objects."""

    def setup_method(self):
        self.mm = make_mm()

    def test_empty_data_returns_empty(self):
        assert self.mm._format_attribution_details({}) == ""

    def test_task_type_included(self):
        result = self.mm._format_attribution_details({"taskType": "chat"})
        assert "**Task Type**: chat" in result

    def test_agent_included(self):
        result = self.mm._format_attribution_details({"agent": "my-agent"})
        assert "**Agent**: my-agent" in result

    def test_organization_dict_formatted(self):
        data = {"organization": {"label": "Acme", "name": "acme", "id": "org_1"}}
        result = self.mm._format_attribution_details(data)
        assert "Acme" in result
        assert "org_1" in result

    def test_organization_string_formatted(self):
        data = {"organization": "Simple Org"}
        result = self.mm._format_attribution_details(data)
        assert "Simple Org" in result

    def test_product_dict_formatted(self):
        data = {"product": {"label": "Widget", "name": "widget", "id": "p_1"}}
        result = self.mm._format_attribution_details(data)
        assert "Widget" in result

    def test_product_string_formatted(self):
        data = {"product": "My Product"}
        result = self.mm._format_attribution_details(data)
        assert "My Product" in result

    def test_subscription_id_included(self):
        data = {"subscriptionId": "sub_99"}
        result = self.mm._format_attribution_details(data)
        assert "**Subscription**: sub_99" in result

    def test_flat_subscriber_email(self):
        data = {"subscriberEmail": "user@example.com"}
        result = self.mm._format_attribution_details(data)
        assert "**Subscriber Email**: user@example.com" in result

    def test_flat_subscriber_id(self):
        data = {"subscriberId": "usr_42"}
        result = self.mm._format_attribution_details(data)
        assert "**Subscriber ID**: usr_42" in result

    def test_flat_subscriber_credential_dict(self):
        data = {"subscriberCredential": {"label": "Key Name", "name": "key-name"}}
        result = self.mm._format_attribution_details(data)
        assert "**Subscriber Credential Name**: Key Name" in result

    def test_flat_subscriber_credential_string(self):
        data = {"subscriberCredential": "my-key"}
        result = self.mm._format_attribution_details(data)
        assert "**Subscriber Credential Name**: my-key" in result

    def test_flat_subscriber_credential_null_no_line(self):
        """Preview docs retype subscriberCredential as nullable; a null value
        must skip the credential line, not render 'None'."""
        data = {"subscriberEmail": "a@b.com", "subscriberCredential": None}
        result = self.mm._format_attribution_details(data)
        assert "**Subscriber Email**: a@b.com" in result
        assert "Subscriber Credential Name" not in result

    def test_flat_subscriber_credential_resource_metadata_label(self):
        """Live dev payloads return the ResourceMetadata shape; label wins."""
        data = {
            "subscriberCredential": {
                "id": "3BygmAQ",
                "label": "UNCLASSIFIED",
                "resourceType": "credential",
            }
        }
        result = self.mm._format_attribution_details(data)
        assert "**Subscriber Credential Name**: UNCLASSIFIED" in result
        assert "3BygmAQ" not in result

    def test_nested_subscriber_fallback(self):
        data = {
            "subscriber": {
                "email": "nested@example.com",
                "id": "usr_nested",
                "credential": {"name": "nested-key"},
            }
        }
        result = self.mm._format_attribution_details(data)
        assert "nested@example.com" in result
        assert "usr_nested" in result
        assert "nested-key" in result

    def test_flat_fields_take_precedence_over_nested(self):
        data = {
            "subscriberEmail": "flat@example.com",
            "subscriber": {"email": "nested@example.com"},
        }
        result = self.mm._format_attribution_details(data)
        assert "flat@example.com" in result
        # Nested should NOT appear when flat fields are present
        assert result.count("nested@example.com") == 0

    def test_no_attribution_fields_returns_empty(self):
        result = self.mm._format_attribution_details({"model": "gpt-4"})
        assert result == ""


# ===========================================================================
# _format_session_tracking
# ===========================================================================


class TestFormatSessionTracking:
    """Verify session tracking formatting."""

    def setup_method(self):
        self.mm = make_mm()

    def test_empty_data_returns_empty(self):
        assert self.mm._format_session_tracking({}) == ""

    def test_trace_id(self):
        result = self.mm._format_session_tracking({"traceId": "t_123"})
        assert "**Trace ID**: t_123" in result

    def test_operation_type(self):
        result = self.mm._format_session_tracking({"operationType": "completion"})
        assert "**Operation Type**: completion" in result

    def test_both_fields(self):
        data = {"traceId": "t_1", "operationType": "chat"}
        result = self.mm._format_session_tracking(data)
        assert "Session Tracking" in result
        assert "t_1" in result
        assert "chat" in result

    def test_no_session_fields_returns_empty(self):
        assert self.mm._format_session_tracking({"model": "gpt-4"}) == ""


# ===========================================================================
# _format_quality_streaming
# ===========================================================================


class TestFormatQualityStreaming:
    """Verify quality and streaming formatting."""

    def setup_method(self):
        self.mm = make_mm()

    def test_empty_data_returns_empty(self):
        assert self.mm._format_quality_streaming({}) == ""

    def test_quality_score(self):
        result = self.mm._format_quality_streaming({"responseQualityScore": 0.95})
        assert "**Quality Score**: 0.95" in result

    def test_streamed_true(self):
        result = self.mm._format_quality_streaming({"isStreamed": True})
        assert "**Streamed Response**: true" in result

    def test_streamed_false(self):
        result = self.mm._format_quality_streaming({"isStreamed": False})
        assert "**Streamed Response**: false" in result

    def test_stop_reason(self):
        result = self.mm._format_quality_streaming({"stopReason": "max_tokens"})
        assert "**Stop Reason**: max_tokens" in result

    def test_no_quality_fields_returns_empty(self):
        assert self.mm._format_quality_streaming({"model": "gpt-4"}) == ""

    def test_quality_score_zero_is_shown(self):
        # responseQualityScore of 0 is not None, so should be shown
        result = self.mm._format_quality_streaming({"responseQualityScore": 0})
        assert "**Quality Score**: 0" in result

    def test_is_streamed_false_is_shown(self):
        # isStreamed=False is not None, should be shown
        result = self.mm._format_quality_streaming({"isStreamed": False})
        assert "Streamed Response" in result


# ===========================================================================
# _format_timestamps
# ===========================================================================


class TestFormatTimestamps:
    """Verify timestamps formatting."""

    def setup_method(self):
        self.mm = make_mm()

    def test_empty_data_returns_empty(self):
        assert self.mm._format_timestamps({}) == ""

    def test_request_time(self):
        result = self.mm._format_timestamps({"requestTime": "2024-06-15T12:00:00Z"})
        assert "**Request Time**: 2024-06-15T12:00:00Z" in result

    def test_response_time(self):
        result = self.mm._format_timestamps({"responseTime": "2024-06-15T12:00:02Z"})
        assert "**Response Time**: 2024-06-15T12:00:02Z" in result

    def test_completion_start_time(self):
        result = self.mm._format_timestamps({"completionStartTime": "2024-06-15T12:00:00.350Z"})
        assert "**Completion Start**: 2024-06-15T12:00:00.350Z" in result

    def test_all_timestamps(self):
        data = {
            "requestTime": "t1",
            "responseTime": "t2",
            "completionStartTime": "t3",
        }
        result = self.mm._format_timestamps(data)
        assert "Timestamps" in result
        assert "t1" in result
        assert "t2" in result
        assert "t3" in result

    def test_no_timestamp_fields_returns_empty(self):
        assert self.mm._format_timestamps({"model": "gpt-4"}) == ""


# ===========================================================================
# _format_subscriber_details
# ===========================================================================


class TestFormatSubscriberDetails:
    """Verify subscriber details formatting with credential obfuscation."""

    def setup_method(self):
        self.mm = make_mm()

    def test_empty_data_returns_empty(self):
        assert self.mm._format_subscriber_details({}) == ""

    def test_flat_email(self):
        result = self.mm._format_subscriber_details({"subscriberEmail": "a@b.com"})
        assert "**Email**: a@b.com" in result

    def test_flat_id(self):
        result = self.mm._format_subscriber_details({"subscriberId": "usr_1"})
        assert "**ID**: usr_1" in result

    def test_flat_credential_string(self):
        result = self.mm._format_subscriber_details({"subscriberCredential": "key-name"})
        assert "**Credential Name**: key-name" in result

    def test_flat_credential_dict(self):
        data = {"subscriberCredential": {"label": "My Key", "name": "my-key"}}
        result = self.mm._format_subscriber_details(data)
        assert "**Credential Name**: My Key" in result

    def test_flat_credential_dict_fallback_to_name(self):
        data = {"subscriberCredential": {"name": "fallback-name"}}
        result = self.mm._format_subscriber_details(data)
        assert "**Credential Name**: fallback-name" in result

    def test_null_credential_renders_no_credential_line(self):
        """Preview docs retype subscriberCredential as nullable; a null value
        must skip the credential line, not render 'None'."""
        data = {"subscriberEmail": "a@b.com", "subscriberCredential": None}
        result = self.mm._format_subscriber_details(data)
        assert "**Email**: a@b.com" in result
        assert "Credential Name" not in result

    def test_null_credential_alone_returns_empty(self):
        assert self.mm._format_subscriber_details({"subscriberCredential": None}) == ""

    def test_credential_resource_metadata_shape_renders_label(self):
        """Live dev payloads return the ResourceMetadata shape; label wins."""
        data = {
            "subscriberCredential": {
                "id": "3BygmAQ",
                "label": "UNCLASSIFIED",
                "resourceType": "credential",
                "created": "2026-07-01T00:00:00Z",
                "updated": "2026-07-01T00:00:00Z",
            }
        }
        result = self.mm._format_subscriber_details(data)
        assert "**Credential Name**: UNCLASSIFIED" in result
        assert "3BygmAQ" not in result

    def test_nested_subscriber_format(self):
        data = {
            "subscriber": {
                "email": "nested@example.com",
                "id": "usr_nested",
                "credential": {"name": "cred-name"},
            }
        }
        result = self.mm._format_subscriber_details(data)
        assert "**Email**: nested@example.com" in result
        assert "**ID**: usr_nested" in result
        assert "**Credential Name**: cred-name" in result

    def test_flat_takes_precedence_over_nested(self):
        data = {
            "subscriberEmail": "flat@example.com",
            "subscriber": {"email": "nested@example.com"},
        }
        result = self.mm._format_subscriber_details(data)
        assert "flat@example.com" in result
        assert "nested@example.com" not in result

    def test_subscriber_attribution_header(self):
        result = self.mm._format_subscriber_details({"subscriberEmail": "a@b.com"})
        assert "Subscriber Attribution" in result

    def test_nested_subscriber_attribution_header(self):
        data = {"subscriber": {"email": "a@b.com"}}
        result = self.mm._format_subscriber_details(data)
        assert "Subscriber Attribution" in result

    def test_subscriber_not_dict_returns_empty(self):
        data = {"subscriber": "just_a_string"}
        result = self.mm._format_subscriber_details(data)
        assert result == ""

    def test_no_subscriber_fields_returns_empty(self):
        result = self.mm._format_subscriber_details({"model": "gpt-4"})
        assert result == ""


# ===========================================================================
# _format_full_transaction_details
# ===========================================================================


class TestFormatFullTransactionDetails:
    """Verify full details orchestration."""

    def setup_method(self):
        self.mm = make_mm()

    def test_full_data_includes_all_sections(self):
        result = self.mm._format_full_transaction_details(FULL_TRANSACTION)
        assert "Cost Breakdown" in result
        assert "Performance Metrics" in result
        assert "Attribution" in result
        assert "Session Tracking" in result
        assert "Quality & Streaming" in result
        assert "Timestamps" in result

    def test_empty_data_returns_empty(self):
        result = self.mm._format_full_transaction_details({})
        assert result == ""

    def test_partial_data_only_relevant_sections(self):
        data = {"requestDuration": 1000, "traceId": "t_1"}
        result = self.mm._format_full_transaction_details(data)
        assert "Performance Metrics" in result
        assert "Session Tracking" in result
        assert "Cost Breakdown" not in result
        assert "Quality & Streaming" not in result
