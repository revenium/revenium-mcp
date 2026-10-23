"""Unit tests for AlertSemanticProcessor in alerts/semantic_processor.py.

Tests natural language parsing for alert creation: metric extraction,
threshold/operator parsing, time period resolution, alert type detection,
filter extraction, and name generation.
"""

import os
import pytest
from unittest.mock import patch

from src.revenium_mcp_server.alerts.semantic_processor import (
    AlertSemanticProcessor,
    threshold_in_text,
)
from tests.unit.test_hosted_alert_notification_email import (
    StubbedAlerts,
    _text,
    no_server_identity,  # noqa: F401
)


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


    @pytest.mark.parametrize(
        "text, expected",
        [
            ("Add a second alert when token rate exceeds 900000", "TOKENS_PER_MINUTE"),
            ("Create a second alert when request rate exceeds 50", "REQUESTS_PER_MINUTE"),
            ("when token rate exceeds 900000 add a second alert", "TOKENS_PER_MINUTE"),
            (
                "set up a second token rate alert at 5000 tokens per minute",
                "TOKENS_PER_MINUTE",
            ),
        ],
    )
    def test_an_ordinal_a_second_is_not_a_per_second_unit(self, processor, text, expected):
        """BACK-4800: "a second alert" counts alerts; it is not a rate unit."""
        assert processor._extract_metric(text) == expected

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("Alert when tokens per second exceed 50", "TOKENS_PER_SECOND"),
            ("token rate exceeds 50 per second", "TOKENS_PER_SECOND"),
            ("token rate exceeds 50 each second", "TOKENS_PER_SECOND"),
            ("token rate exceeds 50 every second", "TOKENS_PER_SECOND"),
            ("token rate exceeds 50/s", "TOKENS_PER_SECOND"),
            ("token rate exceeds 1000 tokens a second", "TOKENS_PER_SECOND"),
            ("token rate exceeds 1k tokens a second", "TOKENS_PER_SECOND"),
            ("token rate exceeds 1,000 tokens in a second", "TOKENS_PER_SECOND"),
            ("token rate exceeds 2.5 thousand tokens a second", "TOKENS_PER_SECOND"),
            ("token rate over 500 a second for 10 minutes", "TOKENS_PER_SECOND"),
            ("request rate exceeds 50 requests/second", "REQUESTS_PER_SECOND"),
            ("request rate above 20 per sec", "REQUESTS_PER_SECOND"),
            ("Alert when token rate exceeds 100 a second continuously", "TOKENS_PER_SECOND"),
            ("token rate exceeds 1000 tokens a second at peak", "TOKENS_PER_SECOND"),
            ("request rate exceeds 50 requests a second from any key", "REQUESTS_PER_SECOND"),
            ("token rate exceeds 1000 tokens a second to the API", "TOKENS_PER_SECOND"),
            ("token rate exceeds 1000 tokens a second per model", "TOKENS_PER_SECOND"),
            ("token rate exceeds 100 a second for an alert", "TOKENS_PER_SECOND"),
            ("token rate exceeds 800 a second please alert me", "TOKENS_PER_SECOND"),
            ("token rate exceeds 800 a second triggers alert", "TOKENS_PER_SECOND"),
            ("token rate exceeds 800 a second overall rate limit", "TOKENS_PER_SECOND"),
        ],
    )
    def test_real_per_second_phrasing_still_reads_per_second(self, processor, text, expected):
        """BACK-4800: a rate stated per second stays per second, so it is refused, not sent 60x low."""
        assert processor._extract_metric(text) == expected


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

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("alert when gpt-4 monthly total cost goes past 500", 500.0),
            ("alert when total cost for gpt-4 exceeds 500", 500.0),
            ("alert when claude-3.5 total cost exceeds 200", 200.0),
            ("team-3 alert when total cost exceeds $50 per hour", 50.0),
        ],
    )
    def test_a_number_inside_a_name_is_not_the_threshold(self, processor, text, expected):
        """BACK-4800: the 4 of gpt-4 or the 3 of team-3 is part of a name, not the threshold."""
        _, value, _ = processor._extract_threshold(text)
        assert value == expected

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("Alert when total cost budget 500 over 24 hours", 500.0),
            ("daily budget 500 over 24 hours", 500.0),
            ("weekly spending budget 2000 over 7 days", 2000.0),
            ("Alert when total cost budget 500 over 15m", 500.0),
            ("daily budget 500 over 30m", 500.0),
        ],
    )
    def test_a_window_is_not_the_threshold(self, processor, text, expected):
        """BACK-4800: the 24 of "over 24 hours" is the window, not the money."""
        _, value, _ = processor._extract_threshold(text)
        assert value == expected

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("alert when total cost exceeds 10k", 10_000.0),
            ("alert when total cost exceeds 1.5 million", 1_500_000.0),
            ("alert when total cost exceeds 2 thousand", 2_000.0),
        ],
    )
    def test_a_multiplier_after_the_number_is_applied(self, processor, text, expected):
        """BACK-4800: "exceeds 10k" is ten thousand, not ten."""
        _, value, _ = processor._extract_threshold(text)
        assert value == expected

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("alert when total cost exceeds 5m", 5.0),
            ("alert when total cost exceeds 5 kb", 5.0),
            ("monthly budget 2000 for 5 models", 2000.0),
            ("daily budget 300 across 5 models", 300.0),
            ("budget 2000 across 3 keys", 2000.0),
            ("budget 2000 for 4 bots", 2000.0),
        ],
    )
    def test_a_unit_suffix_is_not_a_multiplier(self, processor, text, expected):
        """BACK-4800: a bare m or kb, or a word like models or bots, after a number is not a multiplier."""
        _, value, _ = processor._extract_threshold(text)
        assert value == expected


# ---------------------------------------------------------------------------
# threshold_in_text: a budget, limit or cap word decides; otherwise ask
# ---------------------------------------------------------------------------

UNDECIDED_TEXT = "alert when project 7 spend hits 300"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("alert me when the phase 2 budget of 500 is hit", 500.0),
        ("team 3 budget 500", 500.0),
        ("phase 2 limit 250", 250.0),
        ("project 4 cap of 75", 75.0),
        ("spend for phase 2 capped at 40", 40.0),
        ("the phase 2 limit is 90", 90.0),
        ("phase 2 budget of 10k", 10_000.0),
        ("team 3 limit of 1.5 million", 1_500_000.0),
    ],
)
def test_a_budget_limit_or_cap_word_decides_the_threshold(text, expected):
    """BACK-4839: the number after budget, limit or cap wins over a number in a name."""
    found = threshold_in_text(text)
    assert found is not None
    assert found.value == expected
    assert found.ambiguous_between == ()


@pytest.mark.parametrize(
    "text, expected",
    [
        ("phase 2 budget of $500", 500.0),
        ("team 3 alert when error rate is 5%", 5.0),
        ("team 3 alert when total cost exceeds 500", 500.0),
        ("team 3 alert at 10k tokens", 10_000.0),
        ("alert when total cost is 500", 500.0),
        ("alert when error rate hits 5 percent for team 2", 5.0),
        ("error rate 5 pct for team 2", 5.0),
        ("alert when error rate hits 5 % for team 2", 5.0),
    ],
)
def test_a_money_percent_comparison_count_or_single_number_still_decides(text, expected):
    """BACK-4839: sentences that a money, percent, comparison or count word settles are unchanged."""
    found = threshold_in_text(text)
    assert found is not None
    assert found.value == expected
    assert found.ambiguous_between == ()


@pytest.mark.parametrize(
    "text, is_percentage",
    [
        ("alert when error rate hits 5 percent for team 2", True),
        ("error rate 5 pct for team 2", True),
        ("team 3 alert when error rate is 5%", True),
        ("alert when error rate hits 5 % for team 2", True),
        ("phase 2 budget of 500", False),
        ("phase 2 budget of $500", False),
    ],
)
def test_the_percent_meaning_travels_with_the_number(text, is_percentage):
    """BACK-4839: a percent sign or word after the digits marks the threshold as a percentage."""
    found = threshold_in_text(text)
    assert found is not None
    assert found.is_percentage is is_percentage


def test_the_semantic_parser_reads_pct_as_a_percentage(processor):
    """BACK-4839: the semantic parser agrees with threshold_in_text on "5 pct"."""
    _, value, is_percentage = processor._extract_threshold("error rate 5 pct for team 2")
    assert value == 5.0
    assert is_percentage is True


@pytest.mark.parametrize(
    "text",
    [
        "alert when the 95th percentile latency exceeds 500",
        "alert when the percentile cost exceeds 500",
    ],
)
def test_a_percent_away_from_the_threshold_does_not_make_it_a_percentage(processor, text):
    """BACK-4839: only a percent sign or word next to the threshold makes it a percentage."""
    found = threshold_in_text(text)
    _, value, is_percentage = processor._extract_threshold(text)
    assert found is not None
    assert value == found.value
    assert is_percentage is found.is_percentage is False


def test_a_number_inside_a_name_after_budget_is_not_the_threshold():
    """BACK-4839: "budget 2026-Q1" names a budget, so the standing 500 is the threshold."""
    found = threshold_in_text("alert when total cost hits 500 for budget 2026-Q1")
    assert found is not None
    assert found.value == 500.0
    assert found.ambiguous_between == ()


@pytest.mark.parametrize(
    "text, candidates",
    [
        (UNDECIDED_TEXT, (7.0, 300.0)),
        ("alert when spend hits 500 for any of 3 projects", (500.0, 3.0)),
        ("alert when monthly spend hits 1000 by the end of 2026", (1000.0, 2026.0)),
    ],
)
def test_two_numbers_and_no_deciding_word_are_named_as_ambiguous(text, candidates):
    """BACK-4839: with no word to decide, "of" included, every standing number is a candidate."""
    found = threshold_in_text(text)
    assert found is not None
    assert found.ambiguous_between == candidates


@pytest.fixture
def alerts(monkeypatch):
    return StubbedAlerts(monkeypatch)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text", ["alert me when the phase 2 budget of 500 is hit", "team 3 budget 500"]
)
async def test_create_from_text_sends_the_budget_number_as_the_threshold(alerts, text):
    """BACK-4839: the alert the customer asked for is created at 500, not at the name's digit."""
    result = await alerts.call_with(
        {"action": "create_from_text", "text": text, "email": "owner@example.test"}
    )

    assert result.is_error is False, _text(result)
    assert alerts.sent()["threshold"] == 500.0


@pytest.mark.asyncio
async def test_create_from_text_asks_which_number_is_the_threshold(alerts):
    """BACK-4839: two equally plausible numbers are refused, named, and nothing is created."""
    result = await alerts.call_with(
        {"action": "create_from_text", "text": UNDECIDED_TEXT, "email": "owner@example.test"}
    )
    text = _text(result)

    assert result.is_error is True, text
    assert "7 or 300" in text
    assert "Which one is the threshold?" in text
    assert "nothing was created" in text
    assert "Put 'over' or '$' right before the number you mean" in text
    assert "'budget of <number>' instead creates a cumulative budget alert" in text
    assert "write its period (daily, weekly or monthly) in the text" in text
    assert "monthly cumulative" not in text
    alerts.platform.create_anomaly.assert_not_called()


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

    def test_relative_change_keyword(self, processor):
        assert processor._extract_alert_type("relative change alert for cost") == "RELATIVE_CHANGE"

    def test_percentage_change_keyword(self, processor):
        assert processor._extract_alert_type("percentage change in spending") == "RELATIVE_CHANGE"

    def test_trending_keyword(self, processor):
        assert processor._extract_alert_type("alert when cost is trending up") == "RELATIVE_CHANGE"

    def test_trend_alert_keyword(self, processor):
        assert processor._extract_alert_type("set up a trend alert") == "RELATIVE_CHANGE"

    def test_increases_by_keyword(self, processor):
        assert processor._extract_alert_type("alert when cost increases by 20%") == "RELATIVE_CHANGE"

    def test_decreases_by_keyword(self, processor):
        assert processor._extract_alert_type("notify when usage decreases by 10%") == "RELATIVE_CHANGE"


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

    def test_relative_change_alert_parsed(self, processor):
        """RELATIVE_CHANGE alerts should be recognized from NLP text."""
        result = processor.parse_alert_request(
            "relative change alert when cost per transaction goes above 25%"
        )
        assert result["alertType"] == "RELATIVE_CHANGE"
        assert result["metric"] == "COST_PER_TRANSACTION"
        assert result["threshold"] == 25.0

    def test_relative_change_increases_by_operator(self, processor):
        """RELATIVE_CHANGE alert with 'increases by' should produce INCREASES_BY operator and detection rule."""
        result = processor.parse_alert_request(
            "alert when error rate increases by 20%"
        )
        assert result["alertType"] == "RELATIVE_CHANGE"
        assert result["threshold"] == 20.0
        assert len(result["detection_rules"]) == 1
        rule = result["detection_rules"][0]
        assert rule["rule_type"] == "RELATIVE_CHANGE"
        assert rule["operator"] == "INCREASES_BY"
        assert rule["value"] == 20.0

    def test_relative_change_decreases_by_operator(self, processor):
        """RELATIVE_CHANGE alert with 'decreases by' should produce DECREASES_BY operator and detection rule."""
        result = processor.parse_alert_request(
            "alert when error rate decreases by 15%"
        )
        assert result["alertType"] == "RELATIVE_CHANGE"
        assert result["threshold"] == 15.0
        assert len(result["detection_rules"]) == 1
        rule = result["detection_rules"][0]
        assert rule["rule_type"] == "RELATIVE_CHANGE"
        assert rule["operator"] == "DECREASES_BY"
        assert rule["value"] == 15.0

    def test_relative_change_increases_by_bare_number(self, processor):
        """RELATIVE_CHANGE 'increases by N' without % should still extract threshold and produce a detection rule."""
        result = processor.parse_alert_request(
            "alert when error rate increases by 20"
        )
        assert result["alertType"] == "RELATIVE_CHANGE"
        assert result["threshold"] == 20.0
        assert len(result["detection_rules"]) == 1
        rule = result["detection_rules"][0]
        assert rule["rule_type"] == "RELATIVE_CHANGE"
        assert rule["operator"] == "INCREASES_BY"
        assert rule["value"] == 20.0

    def test_relative_change_singular_increase_by(self, processor):
        """Singular 'increase by' should classify as RELATIVE_CHANGE, not THRESHOLD."""
        result = processor.parse_alert_request(
            "alert when error rate increase by 20%"
        )
        assert result["alertType"] == "RELATIVE_CHANGE"
        assert len(result["detection_rules"]) == 1
        rule = result["detection_rules"][0]
        assert rule["rule_type"] == "RELATIVE_CHANGE"
        assert rule["operator"] == "INCREASES_BY"

    def test_relative_change_time_interval_clamped_to_daily(self, processor):
        """RELATIVE_CHANGE with a sub-day time interval should clamp to 'daily', not pass '5m' to validator."""
        result = processor.parse_alert_request(
            "alert when error rate increases by 20% every 5 minutes"
        )
        assert result["alertType"] == "RELATIVE_CHANGE"
        assert len(result["detection_rules"]) == 1
        rule = result["detection_rules"][0]
        assert rule["rule_type"] == "RELATIVE_CHANGE"
        assert rule["time_window"] == "daily"

    def test_no_metric_no_rule(self, processor):
        """Without a metric, no detection rule should be built."""
        result = processor.parse_alert_request("set up an alert please")
        assert len(result["detection_rules"]) == 0

    @patch.dict(os.environ, {"REVENIUM_DEFAULT_EMAIL": "team@company.com"})
    def test_email_from_env(self, processor):
        result = processor.parse_alert_request("alert when spending exceeds $100")
        assert "team@company.com" in result["notification_addresses"]

    @patch.dict(os.environ, {"REVENIUM_DEFAULT_EMAIL": "dummy@email.com"})
    def test_dummy_email_never_becomes_a_placeholder_recipient(self, processor):
        with patch(
            "src.revenium_mcp_server.config_store.ConfigurationStore._discovered_value",
            return_value=None,
        ):
            result = processor.parse_alert_request("alert when spending exceeds $100")
        assert result["notification_addresses"] == []


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

    def test_relative_change_no_warning(self, processor):
        """RELATIVE_CHANGE is supported — no warning should be emitted for change-related text."""
        warnings = processor.validate_and_warn_limitations(
            "alert when cost increase", {"metric": "TOTAL_COST", "operator": ">", "threshold": 10}
        )
        assert not any("not supported" in w.lower() or "feature limitation" in w.lower() for w in warnings)

    def test_no_warnings_for_valid(self, processor):
        parsed = {"metric": "TOTAL_COST", "operator": ">", "threshold": 100}
        warnings = processor.validate_and_warn_limitations("cost above 100", parsed)
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
