"""Unit tests for AlertSemanticProcessor in alerts/semantic_processor.py.

Tests natural language parsing for alert creation: metric extraction,
threshold/operator parsing, time period resolution, alert type detection,
filter extraction, and name generation.
"""

import os
import pytest
from unittest.mock import patch

from src.revenium_mcp_server.alerts.semantic_processor import AlertSemanticProcessor


@pytest.fixture
def processor():
    return AlertSemanticProcessor()


# ---------------------------------------------------------------------------
# _extract_metric: maps natural language to API metric codes
# ---------------------------------------------------------------------------


class TestExtractMetric:
    def test_total_cost(self, processor):
        assert processor._extract_metric("alert when total cost exceeds $100") == "TOTAL_COST"

    def test_spending_synonym(self, processor):
        assert processor._extract_metric("monitor spending") == "TOTAL_COST"

    def test_error_rate(self, processor):
        assert processor._extract_metric("notify when error rate is high") == "ERROR_RATE"

    def test_token_count(self, processor):
        assert processor._extract_metric("track token count") == "TOKEN_COUNT"

    def test_input_tokens(self, processor):
        assert processor._extract_metric("monitor input tokens") == "INPUT_TOKEN_COUNT"

    def test_output_tokens(self, processor):
        assert processor._extract_metric("check output tokens") == "OUTPUT_TOKEN_COUNT"

    def test_cost_per_transaction(self, processor):
        assert processor._extract_metric("cost per transaction too high") == "COST_PER_TRANSACTION"

    def test_requests_per_second(self, processor):
        assert processor._extract_metric("api calls per second") == "REQUESTS_PER_SECOND"

    def test_no_metric_found(self, processor):
        assert processor._extract_metric("please do something") is None

    def test_longer_phrase_matched_first(self, processor):
        """'cost per transaction' should match before 'cost'."""
        result = processor._extract_metric("cost per transaction exceeds 50")
        assert result == "COST_PER_TRANSACTION"


# ---------------------------------------------------------------------------
# _extract_threshold: extracts operator, value, and percentage flag
# ---------------------------------------------------------------------------


class TestExtractThreshold:
    def test_dollar_amount(self, processor):
        op, val, is_pct = processor._extract_threshold("cost exceeds $500")
        assert op == ">"
        assert val == 500.0
        assert is_pct is False

    def test_percentage(self, processor):
        op, val, is_pct = processor._extract_threshold("error rate above 5%")
        assert op == ">"
        assert val == 5.0
        assert is_pct is True

    def test_less_than(self, processor):
        op, val, is_pct = processor._extract_threshold("below 100 requests")
        assert op == "<"
        assert val == 100.0

    def test_at_least(self, processor):
        op, val, is_pct = processor._extract_threshold("at least 50 tokens")
        assert op == ">="
        assert val == 50.0

    def test_at_most(self, processor):
        op, val, is_pct = processor._extract_threshold("at most 200")
        assert op == "<="
        assert val == 200.0

    def test_comma_separated_number(self, processor):
        op, val, is_pct = processor._extract_threshold("over 1,000,000 tokens")
        assert val == 1000000.0

    def test_no_threshold_found(self, processor):
        op, val, is_pct = processor._extract_threshold("just monitor things")
        assert op is None
        assert val is None
        assert is_pct is False

    def test_million_multiplier_standalone(self, processor):
        """Standalone '1.5 million' pattern applies the multiplier."""
        op, val, is_pct = processor._extract_threshold("1.5 million tokens used")
        assert val == 1500000.0

    def test_thousand_multiplier_standalone(self, processor):
        """Standalone '10 thousand' pattern applies the multiplier."""
        op, val, is_pct = processor._extract_threshold("10 thousand calls made")
        assert val == 10000.0

    def test_percent_keyword(self, processor):
        _, _, is_pct = processor._extract_threshold("above 5 percent error rate")
        assert is_pct is True


# ---------------------------------------------------------------------------
# _extract_time_period: maps natural language to time intervals/periods
# ---------------------------------------------------------------------------


class TestExtractTimePeriod:
    def test_five_minutes(self, processor):
        assert processor._extract_time_period("check every 5 minutes") == "5m"

    def test_hourly(self, processor):
        assert processor._extract_time_period("hourly check") == "1h"

    def test_daily(self, processor):
        assert processor._extract_time_period("daily monitoring") in ["daily"]

    def test_monthly(self, processor):
        assert processor._extract_time_period("monthly budget") == "monthly"

    def test_quarterly(self, processor):
        assert processor._extract_time_period("quarterly review") == "quarterly"

    def test_no_period(self, processor):
        assert processor._extract_time_period("alert me") is None

    def test_per_month(self, processor):
        assert processor._extract_time_period("cost per month") == "monthly"

    def test_every_week(self, processor):
        assert processor._extract_time_period("check every week") == "weekly"


# ---------------------------------------------------------------------------
# _extract_alert_type: determines THRESHOLD vs CUMULATIVE_USAGE
# ---------------------------------------------------------------------------


class TestExtractAlertType:
    def test_budget_is_cumulative(self, processor):
        assert processor._extract_alert_type("set a monthly budget alert") == "CUMULATIVE_USAGE"

    def test_spending_limit_is_cumulative(self, processor):
        assert processor._extract_alert_type("spending limit of $5000") == "CUMULATIVE_USAGE"

    def test_quarterly_is_cumulative(self, processor):
        assert processor._extract_alert_type("quarterly cost tracking") == "CUMULATIVE_USAGE"

    def test_monthly_keyword_is_cumulative(self, processor):
        assert processor._extract_alert_type("monthly cost threshold") == "CUMULATIVE_USAGE"

    def test_quota_is_cumulative(self, processor):
        assert processor._extract_alert_type("usage quota alert") == "CUMULATIVE_USAGE"

    def test_default_is_threshold(self, processor):
        """Without cumulative indicators, default to THRESHOLD."""
        assert processor._extract_alert_type("alert when value spikes") == "THRESHOLD"

    def test_real_time_monitoring(self, processor):
        assert processor._extract_alert_type("real-time performance alert") == "THRESHOLD"

    def test_budget_pattern_regex(self, processor):
        result = processor._extract_alert_type("alert when cost goes over $500 per month")
        assert result == "CUMULATIVE_USAGE"


# ---------------------------------------------------------------------------
# _extract_filters: regex-based filter extraction from natural language
# ---------------------------------------------------------------------------


class TestExtractFilters:
    def test_customer_filter(self, processor):
        filters = processor._extract_filters("customer named Acme Corp alert")
        assert len(filters) >= 1
        assert any(f["dimension"] == "ORGANIZATION" for f in filters)

    def test_model_filter_gpt(self, processor):
        filters = processor._extract_filters("for gpt-4o usage")
        model_filters = [f for f in filters if f["dimension"] == "MODEL"]
        assert len(model_filters) >= 1
        assert model_filters[0]["value"] == "gpt-4o"

    def test_provider_filter(self, processor):
        filters = processor._extract_filters("using openai provider")
        provider_filters = [f for f in filters if f["dimension"] == "PROVIDER"]
        assert len(provider_filters) >= 1
        assert provider_filters[0]["value"] == "openai"

    def test_email_subscriber_filter(self, processor):
        filters = processor._extract_filters("subscriber user@example.com")
        subscriber_filters = [f for f in filters if f["dimension"] == "SUBSCRIBER"]
        assert len(subscriber_filters) >= 1
        assert subscriber_filters[0]["value"] == "user@example.com"

    def test_product_exclusion(self, processor):
        """Exclusion pattern should produce at least one IS_NOT filter."""
        filters = processor._extract_filters("exclude product internal-tools")
        product_filters = [f for f in filters if f["dimension"] == "PRODUCT"]
        assert len(product_filters) >= 1
        exclusion_filters = [f for f in product_filters if f["operator"] == "IS_NOT"]
        assert len(exclusion_filters) >= 1

    def test_no_duplicate_filters(self, processor):
        """Same filter extracted twice should be deduplicated."""
        filters = processor._extract_filters("for openai using openai")
        provider_filters = [f for f in filters if f["dimension"] == "PROVIDER"]
        assert len(provider_filters) == 1

    def test_no_filters(self, processor):
        filters = processor._extract_filters("simple alert")
        assert len(filters) == 0


# ---------------------------------------------------------------------------
# _generate_alert_name: creates descriptive name from parsed data
# ---------------------------------------------------------------------------


class TestGenerateAlertName:
    def test_metric_and_threshold(self, processor):
        data = {"metric": "TOTAL_COST", "operator": ">", "threshold": 100}
        name = processor._generate_alert_name(data)
        assert "Total Cost" in name
        assert "Above" in name
        assert "$100" in name

    def test_percentage_threshold(self, processor):
        data = {"metric": "ERROR_RATE", "operator": ">", "threshold": 5, "is_percentage": True}
        name = processor._generate_alert_name(data)
        assert "5%" in name

    def test_with_filters(self, processor):
        data = {
            "metric": "TOTAL_COST",
            "operator": ">",
            "threshold": 100,
            "filters": [{"dimension": "ORGANIZATION", "operator": "CONTAINS", "value": "Acme"}],
        }
        name = processor._generate_alert_name(data)
        assert "Customer Acme" in name

    def test_empty_data(self, processor):
        assert processor._generate_alert_name({}) == "Custom Alert"

    def test_model_filter_in_name(self, processor):
        data = {
            "metric": "TOKEN_COUNT",
            "operator": ">",
            "threshold": 50000,
            "filters": [{"dimension": "MODEL", "operator": "CONTAINS", "value": "gpt-4"}],
        }
        name = processor._generate_alert_name(data)
        assert "Model gpt-4" in name


# ---------------------------------------------------------------------------
# parse_alert_request: end-to-end NLP parsing
# ---------------------------------------------------------------------------


class TestParseAlertRequest:
    def test_simple_cost_alert(self, processor):
        result = processor.parse_alert_request("alert when total cost exceeds $500 daily")
        assert result["metric"] == "TOTAL_COST"
        assert result["operator"] == ">"
        assert result["threshold"] == 500.0
        assert result["alertType"] == "CUMULATIVE_USAGE"
        assert result["name"]  # Should have auto-generated name

    def test_error_rate_alert(self, processor):
        result = processor.parse_alert_request("notify me when error rate goes above 5%")
        assert result["metric"] == "ERROR_RATE"
        assert result["is_percentage"] is True
        assert result["threshold"] == 5.0

    def test_detection_rule_built(self, processor):
        """When metric/operator/threshold all extracted, a detection rule should be built."""
        result = processor.parse_alert_request("alert when total cost exceeds $100")
        assert len(result["detection_rules"]) == 1
        rule = result["detection_rules"][0]
        assert rule["metric"] == "TOTAL_COST"
        assert rule["operator"] == ">"
        assert rule["value"] == 100.0

    def test_no_metric_no_rule(self, processor):
        """Without a metric, no detection rule should be built."""
        result = processor.parse_alert_request("set up an alert please")
        assert len(result["detection_rules"]) == 0

    @patch.dict(os.environ, {"REVENIUM_DEFAULT_EMAIL": "team@company.com"})
    def test_email_from_env(self, processor):
        result = processor.parse_alert_request("alert when spending exceeds $100")
        assert "team@company.com" in result["notification_addresses"]

    @patch.dict(os.environ, {"REVENIUM_DEFAULT_EMAIL": "dummy@email.com"})
    def test_dummy_email_uses_fallback(self, processor):
        result = processor.parse_alert_request("alert when spending exceeds $100")
        assert "admin@example.com" in result["notification_addresses"]


# ---------------------------------------------------------------------------
# validate_and_warn_limitations: validation warnings
# ---------------------------------------------------------------------------


class TestValidateAndWarnLimitations:
    def test_or_logic_warning(self, processor):
        warnings = processor.validate_and_warn_limitations(
            "alert for model A or model B", {"filters": []}
        )
        assert any("OR" in w for w in warnings)

    def test_not_contains_warning(self, processor):
        warnings = processor.validate_and_warn_limitations(
            "not contains value", {"filters": []}
        )
        assert any("not contains" in w.lower() for w in warnings)

    def test_missing_metric_warning(self, processor):
        warnings = processor.validate_and_warn_limitations("set up alert", {})
        assert any("Missing Metric" in w for w in warnings)

    def test_missing_threshold_warning(self, processor):
        warnings = processor.validate_and_warn_limitations(
            "alert", {"metric": "TOTAL_COST"}
        )
        assert any("Missing Threshold" in w for w in warnings)

    def test_relative_change_warning(self, processor):
        warnings = processor.validate_and_warn_limitations(
            "alert when cost increase", {"metric": "TOTAL_COST", "operator": ">", "threshold": 10}
        )
        assert any("Relative change" in w or "relative" in w.lower() for w in warnings)

    def test_no_warnings_for_valid(self, processor):
        parsed = {"metric": "TOTAL_COST", "operator": ">", "threshold": 100}
        warnings = processor.validate_and_warn_limitations("cost above 100", parsed)
        # Should only have the relative change warning for valid data
        error_warnings = [w for w in warnings if "Missing" in w]
        assert len(error_warnings) == 0


# ---------------------------------------------------------------------------
# enhance_with_semantic_search: applies semantic mappings to user input
# ---------------------------------------------------------------------------


class TestEnhanceWithSemanticSearch:
    def test_metric_mapping(self, processor):
        input_data = {
            "detection_rules": [{"metric": "total cost", "operator": ">", "value": 100}]
        }
        result = processor.enhance_with_semantic_search(input_data)
        assert result["detection_rules"][0]["metric"] == "TOTAL_COST"

    def test_operator_mapping(self, processor):
        input_data = {
            "detection_rules": [{"metric": "TOTAL_COST", "operator": "above", "value": 100}]
        }
        result = processor.enhance_with_semantic_search(input_data)
        assert result["detection_rules"][0]["operator"] == ">"

    def test_time_window_mapping(self, processor):
        input_data = {
            "detection_rules": [
                {"metric": "TOTAL_COST", "operator": ">", "value": 100, "time_window": "hourly"}
            ]
        }
        result = processor.enhance_with_semantic_search(input_data)
        assert result["detection_rules"][0]["time_window"] == "1h"

    def test_filter_dimension_mapping(self, processor):
        input_data = {
            "filters": [{"dimension": "customer", "operator": "is", "value": "Acme"}]
        }
        result = processor.enhance_with_semantic_search(input_data)
        assert result["filters"][0]["dimension"] == "ORGANIZATION"

    def test_filter_operator_mapping(self, processor):
        input_data = {
            "filters": [{"dimension": "ORGANIZATION", "operator": "is", "value": "Acme"}]
        }
        result = processor.enhance_with_semantic_search(input_data)
        assert result["filters"][0]["operator"] == "EQUALS"

    def test_no_modification_for_unknown(self, processor):
        input_data = {
            "detection_rules": [
                {"metric": "UNKNOWN_METRIC", "operator": "CUSTOM", "value": 42}
            ]
        }
        result = processor.enhance_with_semantic_search(input_data)
        assert result["detection_rules"][0]["metric"] == "UNKNOWN_METRIC"


# ---------------------------------------------------------------------------
# _analyze_conceptual_intent: intent analysis for disambiguation
# ---------------------------------------------------------------------------


class TestAnalyzeConceptualIntent:
    def test_create_alert_intent(self, processor):
        guidance = processor._analyze_conceptual_intent("create an alert for cost")
        assert guidance["intent"] == "create_anomaly"
        assert guidance["confidence"] == "medium"

    def test_list_alerts_intent(self, processor):
        guidance = processor._analyze_conceptual_intent("show me alerts")
        assert guidance["intent"] == "list_alerts"
        assert guidance["confidence"] == "high"

    def test_budget_suggestion(self, processor):
        guidance = processor._analyze_conceptual_intent("set monthly budget limit")
        suggestions_text = " ".join(guidance["suggestions"])
        assert "CUMULATIVE_USAGE" in suggestions_text or "Budget" in suggestions_text

    def test_realtime_suggestion(self, processor):
        guidance = processor._analyze_conceptual_intent("real-time performance monitoring")
        suggestions_text = " ".join(guidance["suggestions"])
        assert "THRESHOLD" in suggestions_text or "Spike" in suggestions_text

    def test_default_intent(self, processor):
        guidance = processor._analyze_conceptual_intent("do something")
        assert guidance["intent"] == "create_anomaly"
        assert guidance["confidence"] == "high"


# ---------------------------------------------------------------------------
# Mapping construction: verify mappings are populated and correct
# ---------------------------------------------------------------------------


class TestMappingConstruction:
    def test_metric_mappings_populated(self, processor):
        assert len(processor.metric_mappings) > 10
        assert processor.metric_mappings["spending"] == "TOTAL_COST"

    def test_operator_mappings_populated(self, processor):
        assert len(processor.operator_mappings) > 5
        assert processor.operator_mappings["above"] == ">"

    def test_time_period_mappings_populated(self, processor):
        assert len(processor.time_period_mappings) > 10
        assert processor.time_period_mappings["monthly"] == "monthly"

    def test_filter_dimension_mappings(self, processor):
        assert processor.filter_dimension_mappings["customer"] == "organization"
        assert processor.filter_dimension_mappings["api key"] == "credential"
        assert processor.filter_dimension_mappings["llm"] == "model"

    def test_alert_type_mappings(self, processor):
        assert processor.alert_type_mappings["budget"] == "CUMULATIVE_USAGE"
        assert processor.alert_type_mappings["threshold"] == "THRESHOLD"
        assert processor.alert_type_mappings["spike"] == "THRESHOLD"
