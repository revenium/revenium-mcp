"""Unit tests for EnhancedSpikeAnalyzer.

Tests the behavioral correctness of:
- Entity-time matrix building from various API response formats
- Group cost calculation from metrics
- Time group label generation from timestamps and indices
- Timestamp conversion to ISO format
- Context generation for anomalies
- Entity type determination from dimension mapping
- Pattern detection (single, weekend, consecutive, multiple)
- Time period summary generation with deduplication
- Entity summary generation with anomalous cost calculation
- Recommendations generation based on anomaly patterns
- Temporal result formatting
- New entity result formatting
"""

import pytest
from unittest.mock import MagicMock

from src.revenium_mcp_server.analytics.enhanced_spike_analyzer import (
    EnhancedSpikeAnalyzer,
    TemporalAnomaly,
)


def _make_analyzer():
    """Create an analyzer with a mock client."""
    client = MagicMock()
    return EnhancedSpikeAnalyzer(client)


# ─────────────────────────────────────────────────────────────────────────────
# Initialization and supported periods
# ─────────────────────────────────────────────────────────────────────────────


class TestEnhancedSpikeAnalyzerInit:
    """Verify analyzer initializes correctly."""

    def test_supported_periods(self):
        analyzer = _make_analyzer()
        assert "SEVEN_DAYS" in analyzer.supported_periods
        assert "THIRTY_DAYS" in analyzer.supported_periods
        assert "INVALID" not in analyzer.supported_periods


# ─────────────────────────────────────────────────────────────────────────────
# _calculate_group_cost
# ─────────────────────────────────────────────────────────────────────────────


class TestCalculateGroupCost:
    """Tests for group cost aggregation from metrics."""

    def setup_method(self):
        self.analyzer = _make_analyzer()

    def test_sums_metric_results(self):
        metrics = [
            {"metricResult": 100.0},
            {"metricResult": 50.5},
        ]
        result = self.analyzer._calculate_group_cost(metrics)
        assert result == pytest.approx(150.5)

    def test_empty_metrics_returns_zero(self):
        assert self.analyzer._calculate_group_cost([]) == 0.0

    def test_non_dict_metrics_skipped(self):
        metrics = [{"metricResult": 10}, "bad", None]
        result = self.analyzer._calculate_group_cost(metrics)
        assert result == 10.0

    def test_missing_metric_result_defaults_to_zero(self):
        metrics = [{"otherField": 999}]
        result = self.analyzer._calculate_group_cost(metrics)
        assert result == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# _build_entity_time_matrix
# ─────────────────────────────────────────────────────────────────────────────


class TestBuildEntityTimeMatrix:
    """Tests for entity-time matrix building from API data."""

    def setup_method(self):
        self.analyzer = _make_analyzer()

    def test_time_series_format(self):
        """List of time entries with groups produces entity-time tuples."""
        data = {
            "providers": [
                {
                    "startTimestamp": 1705276800000,
                    "groups": [
                        {"groupName": "OpenAI", "metrics": [{"metricResult": 100}]},
                    ],
                },
                {
                    "startTimestamp": 1705363200000,
                    "groups": [
                        {"groupName": "OpenAI", "metrics": [{"metricResult": 200}]},
                    ],
                },
            ]
        }
        matrix = self.analyzer._build_entity_time_matrix(data)
        assert "OpenAI" in matrix
        assert len(matrix["OpenAI"]) == 2
        # Each entry is (timestamp, cost)
        assert matrix["OpenAI"][0] == (1705276800000, 100.0)
        assert matrix["OpenAI"][1] == (1705363200000, 200.0)

    def test_single_period_format(self):
        """Dict with groups (single period) produces single-item time series."""
        data = {
            "models": {
                "startTimestamp": "2024-01-15T00:00:00Z",
                "groups": [
                    {"groupName": "gpt-4", "metrics": [{"metricResult": 500}]},
                ],
            }
        }
        matrix = self.analyzer._build_entity_time_matrix(data)
        assert "gpt-4" in matrix
        assert len(matrix["gpt-4"]) == 1
        assert matrix["gpt-4"][0][1] == 500.0

    def test_empty_data_produces_empty_matrix(self):
        matrix = self.analyzer._build_entity_time_matrix({})
        assert len(matrix) == 0

    def test_non_list_non_dict_data_skipped(self):
        data = {"providers": "invalid"}
        matrix = self.analyzer._build_entity_time_matrix(data)
        assert len(matrix) == 0

    def test_tracks_entity_dimension_map(self):
        data = {
            "providers": [
                {"startTimestamp": 1000, "groups": [{"groupName": "X", "metrics": [{"metricResult": 10}]}]}
            ]
        }
        self.analyzer._build_entity_time_matrix(data)
        assert self.analyzer.entity_dimension_map["X"] == "providers"


# ─────────────────────────────────────────────────────────────────────────────
# _convert_timestamp_to_iso
# ─────────────────────────────────────────────────────────────────────────────


class TestConvertTimestampToIso:
    """Tests for timestamp conversion to ISO format."""

    def setup_method(self):
        self.analyzer = _make_analyzer()

    def test_unix_millis_converted(self):
        result = self.analyzer._convert_timestamp_to_iso(1705276800000)
        assert "2024" in result
        assert result.endswith("Z")

    def test_string_returned_as_is(self):
        result = self.analyzer._convert_timestamp_to_iso("2024-01-15T00:00:00Z")
        assert result == "2024-01-15T00:00:00Z"

    def test_unknown_type_stringified(self):
        result = self.analyzer._convert_timestamp_to_iso(None)
        assert result == "None"


# ─────────────────────────────────────────────────────────────────────────────
# _get_time_group_label_from_timestamp
# ─────────────────────────────────────────────────────────────────────────────


class TestGetTimeGroupLabelFromTimestamp:
    """Tests for time group label generation from timestamps."""

    def setup_method(self):
        self.analyzer = _make_analyzer()

    def test_unix_millis_returns_day_name(self):
        # 1705276800000 = 2024-01-15 (Monday)
        result = self.analyzer._get_time_group_label_from_timestamp(1705276800000)
        assert result in ["Monday", "Sunday", "Tuesday"]  # TZ-dependent

    def test_iso_string_returns_day_name(self):
        result = self.analyzer._get_time_group_label_from_timestamp("2024-01-15T00:00:00Z")
        assert result == "Monday"

    def test_unknown_type_returns_unknown(self):
        result = self.analyzer._get_time_group_label_from_timestamp(None)
        assert result == "Unknown"


# ─────────────────────────────────────────────────────────────────────────────
# _get_entity_type
# ─────────────────────────────────────────────────────────────────────────────


class TestGetEntityType:
    """Tests for entity type determination from dimension mapping."""

    def setup_method(self):
        self.analyzer = _make_analyzer()
        self.analyzer.entity_dimension_map = {
            "OpenAI": "providers",
            "gpt-4": "models",
            "agent-1": "agents",
            "key-123": "api_keys",
            "Acme": "customers",
        }

    def test_provider_type(self):
        assert self.analyzer._get_entity_type("OpenAI") == "provider"

    def test_model_type(self):
        assert self.analyzer._get_entity_type("gpt-4") == "model"

    def test_agent_type(self):
        assert self.analyzer._get_entity_type("agent-1") == "agent"

    def test_api_key_type(self):
        assert self.analyzer._get_entity_type("key-123") == "api_key"

    def test_customer_type(self):
        assert self.analyzer._get_entity_type("Acme") == "customer"

    def test_unknown_entity_defaults_to_provider(self):
        assert self.analyzer._get_entity_type("unknown-entity") == "provider"


# ─────────────────────────────────────────────────────────────────────────────
# _get_time_group_label (index-based, deprecated path)
# ─────────────────────────────────────────────────────────────────────────────


class TestGetTimeGroupLabel:
    """Tests for index-based time group label generation."""

    def setup_method(self):
        self.analyzer = _make_analyzer()

    def test_hour_period(self):
        result = self.analyzer._get_time_group_label(3, "HOUR")
        assert "03:00" in result

    def test_seven_days_period(self):
        result = self.analyzer._get_time_group_label(1, "SEVEN_DAYS")
        assert result == "Monday"

    def test_twenty_four_hours_today(self):
        assert self.analyzer._get_time_group_label(0, "TWENTY_FOUR_HOURS") == "today"

    def test_twenty_four_hours_yesterday(self):
        assert self.analyzer._get_time_group_label(1, "TWENTY_FOUR_HOURS") == "yesterday"

    def test_twelve_months_period(self):
        result = self.analyzer._get_time_group_label(0, "TWELVE_MONTHS")
        assert result == "January"

    def test_thirty_days_week1(self):
        result = self.analyzer._get_time_group_label(2, "THIRTY_DAYS")
        assert "(week 1)" in result

    def test_unknown_period(self):
        result = self.analyzer._get_time_group_label(0, "CUSTOM")
        assert result == "period 1"


# ─────────────────────────────────────────────────────────────────────────────
# _get_time_groups_count
# ─────────────────────────────────────────────────────────────────────────────


class TestGetTimeGroupsCount:
    """Tests for time groups count by period."""

    def setup_method(self):
        self.analyzer = _make_analyzer()

    def test_seven_days(self):
        assert self.analyzer._get_time_groups_count("SEVEN_DAYS") == 7

    def test_thirty_days(self):
        assert self.analyzer._get_time_groups_count("THIRTY_DAYS") == 30

    def test_twelve_months(self):
        assert self.analyzer._get_time_groups_count("TWELVE_MONTHS") == 12

    def test_unknown_period(self):
        assert self.analyzer._get_time_groups_count("CUSTOM") == 1


# ─────────────────────────────────────────────────────────────────────────────
# _detect_absolute_pattern
# ─────────────────────────────────────────────────────────────────────────────


class TestDetectAbsolutePattern:
    """Tests for pattern detection in anomaly time periods."""

    def setup_method(self):
        self.analyzer = _make_analyzer()

    def test_single_period(self):
        result = self.analyzer._detect_absolute_pattern(["Monday 2PM"])
        assert "Single period" in result

    def test_weekend_spike_pattern(self):
        result = self.analyzer._detect_absolute_pattern(["Saturday 2PM", "Sunday 3PM"])
        assert "Weekend spike" in result

    def test_consecutive_day_pattern(self):
        result = self.analyzer._detect_absolute_pattern(["Monday 2PM", "Tuesday 3PM"])
        assert "Consecutive day" in result

    def test_multiple_non_consecutive(self):
        result = self.analyzer._detect_absolute_pattern(["Monday 2PM", "Thursday 3PM"])
        assert "Multiple period" in result


# ─────────────────────────────────────────────────────────────────────────────
# _generate_context (index-based)
# ─────────────────────────────────────────────────────────────────────────────


class TestGenerateContext:
    """Tests for context generation for anomalies."""

    def setup_method(self):
        self.analyzer = _make_analyzer()

    def test_day_name_uses_on_preposition(self):
        anomaly = MagicMock(value=1000.0, z_score=2.5)
        result = self.analyzer._generate_context("OpenAI", 1, anomaly, "SEVEN_DAYS")
        assert "on Monday" in result
        assert "$1000.00" in result
        assert "2.5 standard deviations" in result

    def test_today_no_preposition(self):
        anomaly = MagicMock(value=500.0, z_score=3.0)
        result = self.analyzer._generate_context("X", 0, anomaly, "TWENTY_FOUR_HOURS")
        assert "costs today" in result

    def test_hour_uses_during(self):
        anomaly = MagicMock(value=100.0, z_score=1.5)
        result = self.analyzer._generate_context("X", 2, anomaly, "HOUR")
        assert "during" in result


# ─────────────────────────────────────────────────────────────────────────────
# _generate_recommendations
# ─────────────────────────────────────────────────────────────────────────────


class TestGenerateRecommendations:
    """Tests for recommendation generation from anomalies."""

    def setup_method(self):
        self.analyzer = _make_analyzer()
        self.analyzer.entity_dimension_map = {}

    def test_no_api_keys_returns_empty(self):
        recs = self.analyzer._generate_recommendations([], ["providers"])
        assert recs == []

    def test_anonymous_api_key_triggers_recommendation(self):
        anomaly = TemporalAnomaly(
            entity_name="ANONYMOUS", entity_type="api_key",
            time_group="2024-01-15T00:00:00Z", time_group_label="Monday",
            anomaly_value=1000, normal_range_min=100, normal_range_max=300,
            z_score=3.0, severity_score=50.0, anomaly_type="entity_temporal",
            context="test", percentage_above_normal=200.0,
        )
        recs = self.analyzer._generate_recommendations([anomaly], ["api_keys"])
        assert any("credential" in r.lower() or "attribution" in r.lower() for r in recs)

    def test_non_anonymous_api_key_no_recommendation(self):
        anomaly = TemporalAnomaly(
            entity_name="my-key-123", entity_type="api_key",
            time_group="2024-01-15T00:00:00Z", time_group_label="Monday",
            anomaly_value=1000, normal_range_min=100, normal_range_max=300,
            z_score=3.0, severity_score=50.0, anomaly_type="entity_temporal",
            context="test", percentage_above_normal=200.0,
        )
        recs = self.analyzer._generate_recommendations([anomaly], ["api_keys"])
        assert recs == []


# ─────────────────────────────────────────────────────────────────────────────
# _generate_time_period_summary
# ─────────────────────────────────────────────────────────────────────────────


class TestGenerateTimePeriodSummary:
    """Tests for time period summary generation."""

    def setup_method(self):
        self.analyzer = _make_analyzer()

    def _make_anomaly(self, entity_name, entity_type, label, value, range_min, range_max):
        return TemporalAnomaly(
            entity_name=entity_name, entity_type=entity_type,
            time_group="2024-01-15T00:00:00Z", time_group_label=label,
            anomaly_value=value, normal_range_min=range_min, normal_range_max=range_max,
            z_score=3.0, severity_score=50.0, anomaly_type="entity_temporal",
            context="test", percentage_above_normal=200.0,
        )

    def test_single_anomaly_summary(self):
        anomalies = [self._make_anomaly("OpenAI", "provider", "Monday", 500, 100, 200)]
        summary = self.analyzer._generate_time_period_summary(anomalies, "SEVEN_DAYS")
        assert "Monday" in summary
        assert summary["Monday"]["total_anomalies"] == 1
        assert summary["Monday"]["total_anomalous_cost"] > 0

    def test_multi_type_deduplication(self):
        """When multiple entity types are in same period, costs use highest priority type."""
        anomalies = [
            self._make_anomaly("OpenAI", "provider", "Monday", 500, 100, 200),
            self._make_anomaly("gpt-4", "model", "Monday", 400, 80, 160),
        ]
        summary = self.analyzer._generate_time_period_summary(anomalies, "SEVEN_DAYS")
        # Provider has highest priority (1), should be used for cost calculation
        assert summary["Monday"]["primary_entity_type_used"] == "provider"
        assert summary["Monday"]["total_anomalies"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# _generate_entity_summary
# ─────────────────────────────────────────────────────────────────────────────


class TestGenerateEntitySummary:
    """Tests for entity summary generation."""

    def setup_method(self):
        self.analyzer = _make_analyzer()

    def test_entity_summary_structure(self):
        anomalies = [
            TemporalAnomaly(
                entity_name="OpenAI", entity_type="provider",
                time_group="2024-01-15T00:00:00Z", time_group_label="Monday",
                anomaly_value=500, normal_range_min=100, normal_range_max=200,
                z_score=3.0, severity_score=50.0, anomaly_type="entity_temporal",
                context="test", percentage_above_normal=200.0,
            )
        ]
        summary = self.analyzer._generate_entity_summary(anomalies)
        assert "OpenAI" in summary
        assert "anomalous_time_periods" in summary["OpenAI"]
        assert summary["OpenAI"]["anomalous_time_periods"] == ["Monday"]
        assert summary["OpenAI"]["total_anomalous_cost"] > 0


# ─────────────────────────────────────────────────────────────────────────────
# _format_temporal_results
# ─────────────────────────────────────────────────────────────────────────────


class TestFormatTemporalResults:
    """Tests for temporal results formatting."""

    def setup_method(self):
        self.analyzer = _make_analyzer()
        self.analyzer.entity_dimension_map = {"OpenAI": "providers"}

    def test_empty_anomalies_structure(self):
        result = self.analyzer._format_temporal_results(
            [], "SEVEN_DAYS", "normal", ["providers"]
        )
        assert result["total_anomalies_detected"] == 0
        assert result["period_analyzed"] == "SEVEN_DAYS"
        assert result["sensitivity_used"] == "normal"
        assert result["temporal_anomalies"] == []

    def test_anomaly_values_rounded(self):
        anomaly = TemporalAnomaly(
            entity_name="OpenAI", entity_type="provider",
            time_group="2024-01-15T00:00:00Z", time_group_label="Monday",
            anomaly_value=123.456, normal_range_min=50.123, normal_range_max=80.789,
            z_score=2.89, severity_score=45.67, anomaly_type="entity_temporal",
            context="test", percentage_above_normal=123.456,
        )
        result = self.analyzer._format_temporal_results(
            [anomaly], "SEVEN_DAYS", "normal", ["providers"]
        )
        ta = result["temporal_anomalies"][0]
        assert ta["anomaly_value"] == 123.46
        assert ta["z_score"] == 2.9
        assert ta["severity_score"] == 45.7

    def test_new_entities_included_when_present(self):
        # Mock new entity objects
        new_entity = MagicMock()
        new_entity.entity_name = "new-agent"
        new_entity.entity_type = "agent"
        new_entity.total_cost_impact = 100.0
        new_entity.introduction_period = "2024-01"
        new_entity.first_active_date = "2024-01-10"
        new_entity.periods_active = 5
        new_entity.period_type = "day"
        new_entity.average_daily_cost = 20.0
        new_entity.introduction_type = "new"
        new_entity.context = "New agent detected"

        result = self.analyzer._format_temporal_results(
            [], "SEVEN_DAYS", "normal", ["providers"], [new_entity]
        )
        assert result["new_entities_detected"] == 1
        assert result["new_entities_total_cost_impact"] == 100.0

    def test_period_conversion_notice_included(self):
        result = self.analyzer._format_temporal_results(
            [], "SEVEN_DAYS", "normal", ["providers"], [], "Period was adjusted"
        )
        assert result["period_conversion_notice"] == "Period was adjusted"


# ─────────────────────────────────────────────────────────────────────────────
# _format_new_entity_results
# ─────────────────────────────────────────────────────────────────────────────


class TestFormatNewEntityResults:
    """Tests for new entity result formatting."""

    def setup_method(self):
        self.analyzer = _make_analyzer()

    def test_empty_entities_returns_empty(self):
        assert self.analyzer._format_new_entity_results([]) == {}

    def test_groups_by_type(self):
        entity1 = MagicMock()
        entity1.entity_name = "agent-1"
        entity1.entity_type = "agent"
        entity1.total_cost_impact = 50.0
        entity1.introduction_period = "2024-01"
        entity1.first_active_date = "2024-01-05"
        entity1.periods_active = 3
        entity1.period_type = "day"
        entity1.average_daily_cost = 16.67
        entity1.introduction_type = "new"
        entity1.context = "New agent"

        entity2 = MagicMock()
        entity2.entity_name = "key-1"
        entity2.entity_type = "api_key"
        entity2.total_cost_impact = 100.0
        entity2.introduction_period = "2024-01"
        entity2.first_active_date = "2024-01-10"
        entity2.periods_active = 2
        entity2.period_type = "day"
        entity2.average_daily_cost = 50.0
        entity2.introduction_type = "new"
        entity2.context = "New key"

        result = self.analyzer._format_new_entity_results([entity1, entity2])
        assert result["new_entities_detected"] == 2
        assert result["new_entities_total_cost_impact"] == 150.0
        assert "agent" in result["new_entities_by_type"]
        assert "api_key" in result["new_entities_by_type"]
