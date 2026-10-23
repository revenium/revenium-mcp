"""BACK-4851: scientific notation, rate words, token-alert names and camelCase detection-rule flags."""

import pytest

from src.revenium_mcp_server.alerts.anomaly_manager import AnomalyManager
from src.revenium_mcp_server.alerts.semantic_processor import (
    AlertSemanticProcessor,
    threshold_in_text,
)
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.validators import InputValidator, detection_rule_metrics


@pytest.fixture
def processor():
    return AlertSemanticProcessor()


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("alert when tokens above 1e6", 1_000_000.0),
        ("alert when token count exceeds 2.5E3", 2_500.0),
        ("alert when total cost exceeds $1e3", 1_000.0),
        ("alert when cost is over 5e-1 dollars", 0.5),
    ],
)
def test_scientific_notation_reads_as_its_value(text, value):
    found = threshold_in_text(text)

    assert found is not None
    assert found.value == value


@pytest.mark.parametrize("text", ["alert when api calls exceed 500", "alert when requests exceed 500"])
def test_a_count_of_calls_maps_to_a_metric_the_platform_accepts(processor, text):
    parsed = processor.parse_alert_request(text)
    api_data = InputValidator.convert_to_api_format(parsed)

    assert parsed["metric"] == "REQUESTS_PER_MINUTE"
    assert api_data["metricType"] == "REQUESTS_PER_MINUTE"


@pytest.mark.parametrize(
    "text",
    ["alert when tokens per second exceed 50", "alert when api calls per second exceed 50"],
)
def test_a_per_second_rate_is_refused_naming_the_valid_metrics(processor, text):
    parsed = processor.parse_alert_request(text)

    with pytest.raises(ToolError) as refusal:
        InputValidator.convert_to_api_format(parsed)

    assert "Valid metrics: " + ", ".join(detection_rule_metrics()) in refusal.value.message


@pytest.mark.parametrize(
    "metric", ["TOKEN_COUNT", "INPUT_TOKEN_COUNT", "TOKENS_PER_MINUTE", "REQUESTS_PER_MINUTE"]
)
def test_a_generated_name_for_a_count_has_no_dollar_sign(processor, metric):
    name = processor._generate_alert_name({"metric": metric, "operator": ">", "threshold": 5000})

    assert "$" not in name
    assert "Above 5000" in name


@pytest.mark.parametrize(
    ("text", "name_part"),
    [
        ("alert when token count exceeds 5000", "Above 5000"),
        ("alert when total cost exceeds 100", "Above $100"),
        ("alert when error rate exceeds 5%", "Above 5%"),
        ("alert when requests per minute exceed 2.5", "Above 2.5"),
    ],
)
def test_a_name_generated_from_text_prints_a_whole_threshold_without_a_decimal(
    processor, text, name_part
):
    name = processor.parse_alert_request(text)["name"]

    assert name.endswith(name_part)


@pytest.mark.parametrize("metric", ["TOTAL_COST", "COST_PER_TRANSACTION"])
def test_a_generated_name_for_money_keeps_the_dollar_sign(processor, metric):
    name = processor._generate_alert_name({"metric": metric, "operator": ">", "threshold": 100})

    assert "Above $100" in name


def _rules_payload(**flags):
    return {
        "name": "Rule flags",
        "detection_rules": [
            {"rule_type": "THRESHOLD", "metric": "error_rate", "operator": ">", "value": 5, "time_window": "1h"}
        ],
        "notificationAddresses": ["ops@example.com"],
        **flags,
    }


@pytest.mark.parametrize(
    "flags",
    [
        {"is_percentage": True, "trigger_after_persists_duration": "THIRTY_MINUTES"},
        {"isPercentage": True, "triggerAfterPersistsDuration": "THIRTY_MINUTES"},
    ],
    ids=["snake", "camel"],
)
def test_detection_rule_flags_reach_the_platform_in_either_spelling(flags):
    api_data = AnomalyManager().prepare_create(_rules_payload(**flags), "team-1")

    assert api_data["isPercentage"] is True
    assert api_data["triggerAfterPersistsDuration"] == "THIRTY_MINUTES"


def test_detection_rule_flags_default_when_neither_spelling_is_given():
    api_data = AnomalyManager().prepare_create(_rules_payload(), "team-1")

    assert api_data["isPercentage"] is False
    assert api_data["triggerAfterPersistsDuration"] == ""
