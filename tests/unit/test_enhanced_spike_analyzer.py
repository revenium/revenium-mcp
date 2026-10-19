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

import asyncio
import gc
import warnings
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from unittest.mock import MagicMock

from src.revenium_mcp_server.analytics.enhanced_spike_analyzer import (
    EnhancedSpikeAnalyzer,
    TemporalAnomaly,
    TemporalCollection,
)
from src.revenium_mcp_server.analytics.statistical_anomaly_detector import (
    ACTIVATION,
    NEW_ENTITY,
    StatisticalAnomalyDetector,
)
from src.revenium_mcp_server.client import ReveniumAPIError
from src.revenium_mcp_server.constants import ANALYTICS_MAX_PAGE_SIZE


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
        assert "OPENAI" in matrix
        assert len(matrix["OPENAI"]) == 2
        assert matrix["OPENAI"][0] == (1705276800000, 100.0)
        assert matrix["OPENAI"][1] == (1705363200000, 200.0)

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
        assert "GPT-4" in matrix
        assert len(matrix["GPT-4"]) == 1
        assert matrix["GPT-4"][0][1] == 500.0

    def test_mixed_case_time_series_aggregate_as_one(self):
        data = {
            "providers": [
                {
                    "startTimestamp": 1000,
                    "groups": [
                        {"groupName": "OPENAI", "metrics": [{"metricResult": 100}]},
                        {"groupName": "openai", "metrics": [{"metricResult": 50}]},
                        {"groupName": "OpenAI", "metrics": [{"metricResult": 25}]},
                    ],
                }
            ]
        }
        matrix = self.analyzer._build_entity_time_matrix(data)
        assert len(matrix) == 1
        assert "OPENAI" in matrix
        costs = [c for _, c in matrix["OPENAI"]]
        assert sum(costs) == 175.0

    def test_mixed_case_single_period_aggregate_as_one(self):
        data = {
            "providers": {
                "startTimestamp": "2024-01-15T00:00:00Z",
                "groups": [
                    {"groupName": "OPENAI", "metrics": [{"metricResult": 100}]},
                    {"groupName": "openai", "metrics": [{"metricResult": 50}]},
                ],
            }
        }
        matrix = self.analyzer._build_entity_time_matrix(data)
        assert len(matrix) == 1
        assert "OPENAI" in matrix
        assert len(matrix["OPENAI"]) == 2
        costs = [c for _, c in matrix["OPENAI"]]
        assert sum(costs) == 150.0

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


class TestBucketStarts:
    """Counting a dimension's buckets without building its cost series."""

    def test_matches_the_detection_series_starts(self):
        analyzer = _make_analyzer()
        group = {"groupName": "A", "metrics": [{"metricResult": 1}]}
        data = {
            "agents": [
                {"startTimestamp": "2024-01-16T00:00:00Z", "groups": [group]},
                {"startTimestamp": "2024-01-15T00:00:00Z", "groups": []},
                {"startTimestamp": "2024-01-16T00:00:00Z", "groups": [group]},
                {"groups": []},
            ]
        }

        starts = analyzer._bucket_starts(data, "agents")

        assert starts == analyzer._build_detection_series(data, "agents")[0]
        assert len(starts) == 2
        assert starts[0] < starts[1]


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
        assert "Weekend anomaly" in result

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
        assert "$1,000.00" in result
        assert "2.5 standard deviations" in result

    def test_today_no_preposition(self):
        anomaly = MagicMock(value=500.0, z_score=3.0)
        result = self.analyzer._generate_context("X", 0, anomaly, "TWENTY_FOUR_HOURS")
        assert "costs today" in result

    def test_hour_uses_during(self):
        anomaly = MagicMock(value=100.0, z_score=1.5)
        result = self.analyzer._generate_context("X", 2, anomaly, "HOUR")
        assert "during" in result

    def _context_of(self, values):
        found = StatisticalAnomalyDetector().detect_entity_temporal_anomalies(
            "X", values, "normal", 10.0
        )
        assert [index for index, _ in found] == [9]
        return self.analyzer._generate_context_from_timestamp(
            "X", "2026-10-14T00:00:00.000Z", found[0][1]
        )

    def test_a_cost_below_the_average_is_described_as_below(self):
        text = self._context_of([100.0] * 9 + [10.0])
        assert "2.8 standard deviations below the average" in text
        assert "above" not in text

    def test_a_spike_is_still_described_as_above(self):
        text = self._context_of([10.0] * 9 + [100.0])
        assert "2.8 standard deviations above the average" in text


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

    @pytest.mark.parametrize(
        "entity_name, label, value, range_max, expected",
        [
            ("CODEXCLI", "Wednesday", 86.31, 45.11, 3.8),
            ("AMAZON", "Thursday", 51.23, 20.38, 5.0),
        ],
    )
    def test_cost_multiplier_is_the_spike_cost_divided_by_normal(
        self, entity_name, label, value, range_max, expected
    ):
        anomalies = [self._make_anomaly(entity_name, "provider", label, value, 0.0, range_max)]
        period = self.analyzer._generate_time_period_summary(anomalies, "SEVEN_DAYS")[label]
        assert period["cost_multiplier"] == expected
        assert f"with {expected}x normal cost levels" in period["anomaly_explanation"]
        assert period["total_anomalous_cost"] == round(value - range_max / 2, 2)

    def test_cost_multiplier_of_a_period_adds_every_spike_and_every_normal(self):
        anomalies = [
            self._make_anomaly("OpenAI", "provider", "Monday", 300.0, 0.0, 200.0),
            self._make_anomaly("Anthropic", "provider", "Monday", 100.0, 0.0, 100.0),
        ]
        period = self.analyzer._generate_time_period_summary(anomalies, "SEVEN_DAYS")["Monday"]
        assert period["cost_multiplier"] == 2.7


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

    def test_percent_column_compares_the_spike_with_the_same_normal_as_the_multiplier(self):
        anomaly = TemporalAnomaly(
            entity_name="OpenAI", entity_type="provider",
            time_group="2026-10-14T00:00:00Z", time_group_label="Wednesday",
            anomaly_value=86.31, normal_range_min=0.0, normal_range_max=45.11,
            z_score=2.5, severity_score=23.5, anomaly_type="entity_temporal",
            context="test", percentage_above_normal=376.6,
        )
        result = self.analyzer._format_temporal_results(
            [anomaly], "SEVEN_DAYS", "normal", ["providers"]
        )
        assert result["temporal_anomalies"][0]["percentage_above_normal"] == 282.7

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
        new_entity.introduction_type = NEW_ENTITY
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
        entity1.introduction_type = NEW_ENTITY
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
        entity2.introduction_type = NEW_ENTITY
        entity2.context = "New key"

        result = self.analyzer._format_new_entity_results([entity1, entity2])
        assert result["new_entities_detected"] == 2
        assert result["new_entities_total_cost_impact"] == 150.0
        assert "agent" in result["new_entities_by_type"]
        assert "api_key" in result["new_entities_by_type"]

    @staticmethod
    def _entity(name, entity_type, cost, introduction_type):
        entity = MagicMock()
        entity.entity_name = name
        entity.entity_type = entity_type
        entity.total_cost_impact = cost
        entity.introduction_type = introduction_type
        return entity

    def test_summary_counts_new_and_activated_apart(self):
        """An entity that resumed after idle baseline buckets is not counted as new (BACK-4813)."""
        result = self.analyzer._format_new_entity_results(
            [
                self._entity("fresh-bot", "agent", 30.0, NEW_ENTITY),
                self._entity("daytime-bot", "agent", 1106.0, ACTIVATION),
            ]
        )

        summary = result["new_entity_summary"]
        assert summary.startswith("Detected 1 new and 1 activated cost sources")
        assert "$1,136.00" in summary
        assert "2 new" not in summary
        assert result["new_entities_detected"] == 2
        assert result["new_entities_new_count"] == 1
        assert result["new_entities_activated_count"] == 1
        agents = result["new_entities_by_type"]["agent"]["summary"]
        assert agents.startswith("1 new and 1 activated agents")
        assert "2 new" not in agents

    def test_summary_leaves_out_a_count_of_zero(self):
        result = self.analyzer._format_new_entity_results(
            [self._entity("daytime-bot", "agent", 10.0, ACTIVATION)]
        )

        assert result["new_entity_summary"].startswith("Detected 1 activated cost source with")
        assert result["new_entities_by_type"]["agent"]["summary"].startswith(
            "1 activated agent,"
        )


class TestMoneyInAnomalySentences:
    """Every dollar figure in an anomaly sentence follows the one dollar rule."""

    def setup_method(self):
        self.analyzer = _make_analyzer()

    @staticmethod
    def _new_entity(cost):
        entity = MagicMock()
        entity.entity_name = "agent-1"
        entity.entity_type = "agent"
        entity.total_cost_impact = cost
        entity.introduction_type = NEW_ENTITY
        return entity

    def _anomaly(self, value):
        return MagicMock(value=value, z_score=2.5, percentage_above_normal=50.0)

    def test_a_sub_cent_new_source_keeps_its_fraction_of_a_cent(self):
        result = self.analyzer._format_new_entity_results([self._new_entity(0.004)])
        assert result["new_entity_summary"] == (
            "Detected 1 new cost source with $0.004 in the recent part"
        )
        assert result["new_entities_by_type"]["agent"]["summary"] == (
            "1 new agent, $0.004 in the recent part"
        )

    def test_a_whole_dollar_new_source_keeps_two_decimals_and_commas(self):
        result = self.analyzer._format_new_entity_results([self._new_entity(1234.5)])
        assert "$1,234.50 in the recent part" in result["new_entity_summary"]
        assert "$1,234.50 in the recent part" in result["new_entities_by_type"]["agent"]["summary"]

    def test_a_sub_cent_anomaly_keeps_its_fraction_of_a_cent(self):
        by_index = self.analyzer._generate_context("X", 1, self._anomaly(0.0042), "SEVEN_DAYS")
        by_time = self.analyzer._generate_context_from_timestamp(
            "X", "2026-10-14T00:00:00.000Z", self._anomaly(0.0042)
        )
        assert "($0.0042)" in by_index
        assert "($0.0042)" in by_time

    def test_a_whole_dollar_anomaly_keeps_two_decimals_and_commas(self):
        by_index = self.analyzer._generate_context("X", 1, self._anomaly(1234.5), "SEVEN_DAYS")
        by_time = self.analyzer._generate_context_from_timestamp(
            "X", "2026-10-14T00:00:00.000Z", self._anomaly(1234.5)
        )
        assert "($1,234.50)" in by_index
        assert "($1,234.50)" in by_time


# ─────────────────────────────────────────────────────────────────────────────
# Reading the dimension reports
# ─────────────────────────────────────────────────────────────────────────────

_FIRST_BUCKET = datetime(2026, 10, 9, tzinfo=timezone.utc)
_LEGACY_PROVIDER_PATH = "/profitstream/v2/api/sources/metrics/ai/total-cost-by-provider-over-time"
_SUPPORTED = "providers, models, api_keys, agents, customers, tokens"


def _iso(moment):
    return f"{moment:%Y-%m-%dT%H:%M:%S}.{moment.microsecond // 1000:03d}Z"


def _six_hour_buckets(costs):
    """Six-hour buckets from 2026-10-09T00:00:00.000Z, one codexcli group each."""
    return [
        {
            "startTimestamp": _iso(_FIRST_BUCKET + timedelta(hours=6 * index)),
            "endTimestamp": _iso(
                _FIRST_BUCKET + timedelta(hours=6 * (index + 1)) - timedelta(milliseconds=1)
            ),
            "groups": [{"groupName": "codexcli", "metrics": [{"metricResult": cost}]}],
        }
        for index, cost in enumerate(costs)
    ]


def _failed_after(cause):
    """The client's own wrap of a transport error whose message is empty."""
    try:
        raise cause
    except Exception:
        try:
            raise ReveniumAPIError(f"Request failed: {str(cause)}")
        except ReveniumAPIError as error:
            return error


class FakeReportClient:
    """The legacy route answers every bucket as a list; the analytics route pages them."""

    def __init__(self, buckets, page_size=20, failures=None):
        self.team_id = "team-1"
        self.buckets = buckets
        self.page_size = page_size
        self.failures = failures or {}
        self.calls = []
        self.in_flight = 0
        self.most_in_flight = 0

    async def get(self, path, params=None, **kwargs):
        self.calls.append((path, dict(params or {}), kwargs))
        self.in_flight += 1
        self.most_in_flight = max(self.most_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0)
        finally:
            self.in_flight -= 1
        for fragment, error in self.failures.items():
            if fragment in path:
                raise error
        if not kwargs.get("use_bearer"):
            return list(self.buckets)
        size = self.page_size
        pages = [self.buckets[i:i + size] for i in range(0, len(self.buckets), size)]
        number = (params or {}).get("page", 0)
        envelope = {
            "_embedded": {"items": pages[number]},
            "page": {
                "number": number,
                "size": size,
                "totalPages": len(pages),
                "totalElements": len(self.buckets),
            },
        }
        if kwargs.get("unwrap_hal_embedded", True):
            # The client's default unwrap hands back the _embedded list only
            return pages[number]
        return envelope


class _ReportsByPath(FakeReportClient):
    """The legacy route, answering the report whose path holds a fragment with its own buckets."""

    def __init__(self, buckets_by_fragment):
        super().__init__([])
        self.buckets_by_fragment = buckets_by_fragment

    async def get(self, path, params=None, **kwargs):
        self.calls.append((path, dict(params or {}), kwargs))
        return next(
            list(buckets)
            for fragment, buckets in self.buckets_by_fragment.items()
            if fragment in path
        )


class TestDimensionReportPaging:
    """Every page of each dimension report is read, a few reports at a time."""

    @pytest.mark.asyncio
    async def test_new_analytics_route_reads_every_page_of_buckets(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_USE_NEW_ANALYTICS_API", "true")
        costs = [20.0] * 29
        costs[24] = 900.0
        buckets = _six_hour_buckets(costs)
        client = FakeReportClient(buckets, page_size=20)

        result = await EnhancedSpikeAnalyzer(client).analyze_temporal_anomalies("SEVEN_DAYS")

        assert [params.get("page", 0) for _, params, _ in client.calls] == [0, 1]
        assert all(params["size"] == ANALYTICS_MAX_PAGE_SIZE for _, params, _ in client.calls)
        assert all(
            kwargs.get("use_bearer") is True and kwargs.get("unwrap_hal_embedded") is False
            for _, _, kwargs in client.calls
        )
        assert [a["time_group"] for a in result["temporal_anomalies"]] == [
            buckets[24]["startTimestamp"]
        ]
        assert "dimensions_incomplete" not in result

    @pytest.mark.asyncio
    async def test_a_read_stopped_at_the_page_cap_names_the_unexamined_window(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_USE_NEW_ANALYTICS_API", "true")
        buckets = _six_hour_buckets([20.0] * 25)
        client = FakeReportClient(buckets, page_size=1)

        result = await EnhancedSpikeAnalyzer(client).analyze_temporal_anomalies("SEVEN_DAYS")

        pages_read = len(client.calls)
        note = result.get("dimensions_incomplete", {}).get("providers", "")
        assert pages_read < 25
        assert f"{pages_read} of 25 pages" in note
        assert buckets[pages_read - 1]["endTimestamp"] in note

    @pytest.mark.asyncio
    async def test_legacy_route_is_read_once_unpaged(self, monkeypatch):
        monkeypatch.delenv("REVENIUM_USE_NEW_ANALYTICS_API", raising=False)
        client = FakeReportClient(_six_hour_buckets([20.0] * 12))

        await EnhancedSpikeAnalyzer(client).analyze_temporal_anomalies("SEVEN_DAYS")

        assert client.calls == [
            (_LEGACY_PROVIDER_PATH, {"teamId": "team-1", "period": "SEVEN_DAYS"}, {})
        ]

    @pytest.mark.asyncio
    async def test_dimension_reports_are_read_concurrently(self, monkeypatch):
        monkeypatch.delenv("REVENIUM_USE_NEW_ANALYTICS_API", raising=False)
        client = FakeReportClient(_six_hour_buckets([20.0] * 12))

        await EnhancedSpikeAnalyzer(client).analyze_temporal_anomalies(
            "SEVEN_DAYS",
            include_dimensions=["providers", "models", "api_keys", "agents", "customers"],
        )

        assert len(client.calls) == 5
        assert client.most_in_flight == 3

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error, reason",
        [
            (ReveniumAPIError("Gateway timeout", status_code=504), "HTTP 504: Gateway timeout"),
            (
                ReveniumAPIError("HTTP 504: Gateway Timeout", status_code=504),
                "HTTP 504: Gateway Timeout",
            ),
            (RuntimeError("connection reset"), "connection reset"),
            (_failed_after(httpx.ReadTimeout("")), "Request failed: ReadTimeout"),
        ],
    )
    async def test_an_unread_report_carries_its_failure_reason(self, monkeypatch, error, reason):
        monkeypatch.delenv("REVENIUM_USE_NEW_ANALYTICS_API", raising=False)
        client = FakeReportClient(
            _six_hour_buckets([20.0] * 12), failures={"total-cost-by-model": error}
        )

        result = await EnhancedSpikeAnalyzer(client).analyze_temporal_anomalies(
            "SEVEN_DAYS", include_dimensions=["providers", "models"]
        )

        assert result.get("dimensions_not_read", {}).get("models") == reason
        assert "models" not in result["entities_analyzed"]

    @pytest.mark.asyncio
    async def test_time_groups_analyzed_is_the_bucket_count_returned(self, monkeypatch):
        monkeypatch.delenv("REVENIUM_USE_NEW_ANALYTICS_API", raising=False)
        client = FakeReportClient(_six_hour_buckets([20.0] * 14))

        result = await EnhancedSpikeAnalyzer(client).analyze_temporal_anomalies("SEVEN_DAYS")

        assert result["time_groups_analyzed"] == 14
        assert "time_groups_by_dimension" not in result

    @pytest.mark.asyncio
    async def test_dimensions_with_different_bucket_counts_are_counted_apart(
        self, monkeypatch
    ):
        from src.revenium_mcp_server.tools_decomposed.business_analytics_management import (
            BusinessAnalyticsManagement,
        )

        monkeypatch.delenv("REVENIUM_USE_NEW_ANALYTICS_API", raising=False)
        client = _ReportsByPath(
            {
                "total-cost-by-provider": _six_hour_buckets([20.0] * 14),
                "agents-over-time": _six_hour_buckets([20.0] * 7),
            }
        )

        result = await EnhancedSpikeAnalyzer(client).analyze_temporal_anomalies(
            "SEVEN_DAYS", include_dimensions=["providers", "agents"]
        )

        assert result["time_groups_by_dimension"] == {"providers": 14, "agents": 7}
        assert "time_groups_analyzed" not in result
        text = BusinessAnalyticsManagement(ucm_helper=None)._format_anomaly_results_markdown(
            result
        )
        assert "**Time groups analyzed:** providers 14, agents 7" in text


class TestDimensionReadCancellation:
    """A read that is cancelled while waiting for a slot leaves no coroutine behind."""

    @pytest.mark.asyncio
    async def test_cancelling_the_gather_leaves_no_coroutine_never_awaited(self):
        analyzer = EnhancedSpikeAnalyzer(MagicMock())
        started = asyncio.Event()
        created = []

        class BlockingReader:
            def _read_ranked_report(self, request):
                created.append(request)
                return self._block()

            async def _block(self):
                started.set()
                await asyncio.Event().wait()

        reader = BlockingReader()
        semaphore = asyncio.Semaphore(3)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            gathered = asyncio.gather(
                *(analyzer._read_dimension(semaphore, f"d{i}", reader, i) for i in range(6))
            )
            await started.wait()
            gathered.cancel()
            with pytest.raises(asyncio.CancelledError):
                await gathered
            gc.collect()

        assert len(created) == 3
        assert [w for w in caught if "never awaited" in str(w.message)] == []


# ─────────────────────────────────────────────────────────────────────────────
# New-entity detection split
# ─────────────────────────────────────────────────────────────────────────────


class TestNewEntityDetectionSplit:
    """The baseline is a share of the buckets the report returned, whatever their size."""

    @pytest.mark.asyncio
    async def test_new_api_six_hour_buckets_split_by_bucket_share(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_USE_NEW_ANALYTICS_API", "true")
        buckets = _six_hour_buckets([20.0] * 28)
        for bucket in buckets[20:]:
            bucket["groups"].append({"groupName": "newbot", "metrics": [{"metricResult": 15.0}]})
        client = FakeReportClient(buckets, page_size=20)

        result = await EnhancedSpikeAnalyzer(client).analyze_temporal_anomalies(
            "SEVEN_DAYS", detect_new_entities=True
        )

        assert "new_entity_detection" in result
        detection = result["new_entity_detection"]
        assert detection["baseline"]["buckets"] == 8
        assert detection["baseline"]["start"] == "2026-10-09T00:00:00+00:00"
        assert detection["baseline"]["end"] == "2026-10-10T18:00:00+00:00"
        assert detection["recent"]["buckets"] == 20
        entities = result["new_entities_by_type"]["provider"]["entities"]
        assert [entity["entity_name"] for entity in entities] == ["NEWBOT"]
        assert entities[0]["first_active_date"] == "2026-10-14"
        assert entities[0]["periods_active"] == 8

    @staticmethod
    def _daily_agent_buckets(bucket_count):
        """Daily agent buckets from 2026-10-09, steadybot with cost in every one."""
        return [
            {
                "startTimestamp": _iso(_FIRST_BUCKET + timedelta(days=index)),
                "groups": [
                    {"groupName": "steadybot", "metrics": [{"metricResult": 10.0}]}
                ],
            }
            for index in range(bucket_count)
        ]

    @staticmethod
    def _providers_with_newbot():
        buckets = _six_hour_buckets([20.0] * 28)
        newbot = {"groupName": "newbot", "metrics": [{"metricResult": 15.0}]}
        for bucket in buckets[20:]:
            bucket["groups"].append(dict(newbot))
        return buckets

    @staticmethod
    async def _detect(data):
        collection = TemporalCollection(data=data, not_read={}, incomplete={})
        return await _make_analyzer()._detect_new_entities(
            collection, "SEVEN_DAYS", list(data)
        )

    @pytest.mark.asyncio
    async def test_another_dimensions_bucket_grid_leaves_the_first_unchanged(self):
        providers = self._providers_with_newbot()

        alone, alone_outcome = await self._detect({"providers": providers})
        both, both_outcome = await self._detect(
            {"providers": providers, "agents": self._daily_agent_buckets(7)}
        )

        assert [entity.entity_name for entity in alone] == ["NEWBOT"]
        assert [(item.entity_type, item.entity_name) for item in both] == [
            ("provider", "NEWBOT")
        ]
        spans = both_outcome["spans_by_dimension"]
        span_keys = ("whole_window", "baseline", "recent", "buckets_start_at_midnight")
        assert spans["providers"] == {key: alone_outcome[key] for key in span_keys}
        assert spans["agents"]["baseline"]["buckets"] == 2
        assert spans["agents"]["recent"]["buckets"] == 5
        assert "whole_window" not in both_outcome

    @pytest.mark.asyncio
    async def test_a_dimension_with_one_bucket_is_not_compared_but_others_are(self):
        found, outcome = await self._detect(
            {
                "providers": self._providers_with_newbot(),
                "agents": self._daily_agent_buckets(1),
            }
        )

        assert outcome["status"] == "found"
        assert [entity.entity_name for entity in found] == ["NEWBOT"]
        assert outcome["dimensions_not_compared"] == {
            "agents": (
                "the report returned 1 bucket, and at least 2 are needed to compare "
                "a baseline with a recent part"
            )
        }
        assert outcome["recent"]["buckets"] == 20

    @staticmethod
    def _api_key_buckets(late_groups):
        """28 six-hour buckets with codexcli in each, and late_groups from bucket 20 on."""
        buckets = _six_hour_buckets([20.0] * 28)
        for bucket in buckets[20:]:
            bucket["groups"].extend(
                {"groupName": name, "metrics": [{"metricResult": cost}]}
                for name, cost in late_groups.items()
            )
        return buckets

    @staticmethod
    async def _detect_api_keys(buckets):
        result = await EnhancedSpikeAnalyzer(
            FakeReportClient(buckets, page_size=20)
        ).analyze_temporal_anomalies(
            "SEVEN_DAYS", include_dimensions=["api_keys"], detect_new_entities=True
        )
        entities = result.get("new_entities_by_type", {}).get("api_key", {}).get("entities", [])
        return result["new_entity_detection"], [entity["entity_name"] for entity in entities]

    @pytest.mark.asyncio
    async def test_the_analytics_api_key_rollup_is_not_a_new_key_and_the_cap_is_named(
        self, monkeypatch
    ):
        """The analytics route names 20 keys and rolls the rest into one group (BACK-4813)."""
        from src.revenium_mcp_server.tools_decomposed.business_analytics_management import (
            BusinessAnalyticsManagement,
        )

        monkeypatch.setenv("REVENIUM_USE_NEW_ANALYTICS_API", "true")
        buckets = self._api_key_buckets({"Other API keys": 40.0, "newkey": 15.0})

        detection, names = await self._detect_api_keys(buckets)

        assert names == ["NEWKEY"]
        assert "20" in detection["dimensions_capped"]["api_keys"]
        assert "Other API keys" in detection["dimensions_capped"]["api_keys"]
        lines = []
        BusinessAnalyticsManagement._render_detection_window(detection, lines)
        assert any(
            line.startswith("Capped for new-entity detection: api_keys (") for line in lines
        )

    @pytest.mark.asyncio
    async def test_the_cap_is_not_named_when_the_analytics_route_returned_no_rollup(
        self, monkeypatch
    ):
        monkeypatch.setenv("REVENIUM_USE_NEW_ANALYTICS_API", "true")
        buckets = self._api_key_buckets({f"key-{index}": 15.0 for index in range(4)})

        detection, names = await self._detect_api_keys(buckets)

        assert sorted(names) == [f"KEY-{index}" for index in range(4)]
        assert not detection.get("dimensions_capped")

    @pytest.mark.asyncio
    async def test_a_legacy_key_named_other_api_keys_is_still_reported_as_new(
        self, monkeypatch
    ):
        monkeypatch.delenv("REVENIUM_USE_NEW_ANALYTICS_API", raising=False)
        buckets = self._api_key_buckets({"Other API keys": 40.0})

        detection, names = await self._detect_api_keys(buckets)

        assert names == ["OTHER API KEYS"]
        assert not detection.get("dimensions_capped")

    def test_introduction_period_names_two_half_day_buckets_with_times(self):
        starts = [
            datetime(2026, 10, 8, 12, tzinfo=timezone.utc),
            datetime(2026, 10, 9, tzinfo=timezone.utc),
            datetime(2026, 10, 9, 12, tzinfo=timezone.utc),
        ]

        found = StatisticalAnomalyDetector().detect_new_cost_sources(
            {("providers", "NEWBOT"): [0.0, 5.0, 5.0]}, starts, "SEVEN_DAYS"
        )

        assert [entity.introduction_period for entity in found] == [
            "the 2 buckets starting 2026-10-09 00:00 UTC to 2026-10-09 12:00 UTC"
        ]
