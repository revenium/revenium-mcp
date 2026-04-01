"""Tests for schema_discovery.py — schema discovery engine capabilities and validation."""

import pytest

from src.revenium_mcp_server.schema_discovery import SchemaDiscoveryEngine


@pytest.fixture
def engine():
    return SchemaDiscoveryEngine()


class TestGetCapabilities:
    def test_anomalies_capabilities(self, engine):
        caps = engine.get_capabilities("anomalies")
        assert "metrics" in caps
        assert "operators" in caps
        assert "time_periods" in caps

    def test_alerts_capabilities(self, engine):
        caps = engine.get_capabilities("alerts")
        assert isinstance(caps, dict)
        assert len(caps) > 0

    def test_unknown_resource_returns_error(self, engine):
        result = engine.get_capabilities("unknown_type")
        assert "error" in result
        assert "available_types" in result


class TestGetExamples:
    def test_anomalies_examples(self, engine):
        result = engine.get_examples("anomalies")
        assert "examples" in result
        assert len(result["examples"]) > 0

    def test_unknown_type_returns_error(self, engine):
        result = engine.get_examples("nonexistent")
        assert "error" in result

    def test_filter_by_example_type(self, engine):
        # Get all examples first to find a valid type
        all_examples = engine.get_examples("anomalies")
        if all_examples.get("examples"):
            example_type = all_examples["examples"][0].get("type")
            if example_type:
                filtered = engine.get_examples("anomalies", example_type=example_type)
                assert all(
                    ex.get("type") == example_type
                    for ex in filtered.get("examples", [])
                )


class TestValidateConfiguration:
    def test_valid_anomaly_config(self, engine):
        # Get required fields from validation rules
        rules = engine.validation_rules.get("anomalies", {})
        required = rules.get("required", [])

        # Build minimal valid config
        config = {field: f"test_{field}" for field in required}
        config["detection_rules"] = [
            {
                "rule_type": "THRESHOLD",
                "metric": engine.capabilities["anomalies"]["metrics"]["all"][0],
                "operator": engine.capabilities["anomalies"]["operators"]["all"][0],
                "value": 100,
            }
        ]
        result = engine.validate_configuration("anomalies", config)
        assert result["valid"] is True

    def test_missing_required_field(self, engine):
        result = engine.validate_configuration("anomalies", {})
        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_invalid_rule_type(self, engine):
        rules = engine.validation_rules.get("anomalies", {})
        required = rules.get("required", [])
        config = {field: f"test_{field}" for field in required}
        config["detection_rules"] = [
            {
                "rule_type": "INVALID_TYPE",
                "metric": "TOTAL_COST",
                "operator": "GREATER_THAN",
                "value": 100,
            }
        ]
        result = engine.validate_configuration("anomalies", config)
        assert result["valid"] is False
        assert any("rule_type" in str(e) for e in result["errors"])

    def test_invalid_metric(self, engine):
        rules = engine.validation_rules.get("anomalies", {})
        required = rules.get("required", [])
        config = {field: f"test_{field}" for field in required}
        config["detection_rules"] = [
            {
                "rule_type": "THRESHOLD",
                "metric": "FAKE_METRIC",
                "operator": "GREATER_THAN",
                "value": 100,
            }
        ]
        result = engine.validate_configuration("anomalies", config)
        assert result["valid"] is False

    def test_invalid_operator(self, engine):
        rules = engine.validation_rules.get("anomalies", {})
        required = rules.get("required", [])
        config = {field: f"test_{field}" for field in required}
        config["detection_rules"] = [
            {
                "rule_type": "THRESHOLD",
                "metric": engine.capabilities["anomalies"]["metrics"]["all"][0],
                "operator": "INVALID_OP",
                "value": 100,
            }
        ]
        result = engine.validate_configuration("anomalies", config)
        assert result["valid"] is False

    def test_missing_detection_rule_fields(self, engine):
        rules = engine.validation_rules.get("anomalies", {})
        required = rules.get("required", [])
        config = {field: f"test_{field}" for field in required}
        config["detection_rules"] = [{}]  # Empty rule
        result = engine.validate_configuration("anomalies", config)
        assert result["valid"] is False
        assert len(result["errors"]) >= 4  # 4 required fields missing

    def test_unknown_resource_type(self, engine):
        result = engine.validate_configuration("unknown", {})
        assert result["valid"] is False
        assert "error" in result


class TestGetAgentFriendlySummary:
    def test_anomalies_summary(self, engine):
        summary = engine.get_agent_friendly_summary("anomalies")
        assert summary["resource_type"] == "anomalies"
        assert "quick_reference" in summary
        assert "common_patterns" in summary
        assert "natural_language_examples" in summary

    def test_unknown_type(self, engine):
        result = engine.get_agent_friendly_summary("unknown")
        assert "error" in result

    def test_common_patterns_have_categories(self, engine):
        summary = engine.get_agent_friendly_summary("anomalies")
        patterns = summary["common_patterns"]
        assert "cost_monitoring" in patterns
        assert "performance_monitoring" in patterns
        assert "usage_monitoring" in patterns
        assert "cumulative_usage_monitoring" in patterns


class TestInternalHelpers:
    def test_get_valid_values_for_known_field(self, engine):
        values = engine._get_valid_values_for_field("rule_type")
        assert "THRESHOLD" in values

    def test_get_valid_values_for_unknown_field(self, engine):
        assert engine._get_valid_values_for_field("nonexistent") == []
