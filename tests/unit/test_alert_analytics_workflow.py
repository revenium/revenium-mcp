"""Unit tests for AlertAnalyticsWorkflowProcessor.

Tests behavioral correctness of pure computation methods: analysis window
calculation, period determination, alert classification, timestamp parsing,
confidence scoring, timeline pattern analysis, format output, and
contributing factor identification.
"""

import pytest
from datetime import datetime, timedelta, timezone

from src.revenium_mcp_server.analytics.alert_analytics_workflow_processor import (
    AlertAnalyticsWorkflowProcessor,
    AlertContext,
    RootCauseAnalysis,
)


def _make_alert_context(**overrides):
    """Build a default AlertContext for testing, with optional overrides."""
    defaults = {
        "alert_id": "alert-001",
        "anomaly_id": "anom-001",
        "anomaly_name": "Test Alert",
        "trigger_timestamp": datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        "severity": "medium",
        "status": "active",
        "affected_metrics": {"TOTAL_COST": 150.0},
        "threshold_violations": [{"metric": "TOTAL_COST", "threshold": 100.0}],
        "team_id": "team-1",
        "metadata": None,
    }
    defaults.update(overrides)
    return AlertContext(**defaults)


class TestCalculateAnalysisWindow:
    """Tests for _calculate_analysis_window: time window computation."""

    def test_returns_correct_duration(self):
        proc = AlertAnalyticsWorkflowProcessor()
        trigger = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        window = proc._calculate_analysis_window(trigger, 24)
        assert window["duration_hours"] == 24
        assert window["start_time"] == trigger - timedelta(hours=24)
        assert window["end_time"] == trigger

    def test_different_window_sizes(self):
        proc = AlertAnalyticsWorkflowProcessor()
        trigger = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        for hours in [1, 8, 24, 168, 720, 8760]:
            window = proc._calculate_analysis_window(trigger, hours)
            assert window["duration_hours"] == hours
            assert "period" in window


class TestDeterminePeriodFromHours:
    """Tests for _determine_period_from_hours: API period mapping."""

    @pytest.mark.parametrize(
        "hours,expected_period",
        [
            (1, "HOUR"),
            (4, "EIGHT_HOURS"),
            (8, "EIGHT_HOURS"),
            (12, "TWENTY_FOUR_HOURS"),
            (24, "TWENTY_FOUR_HOURS"),
            (48, "SEVEN_DAYS"),
            (168, "SEVEN_DAYS"),
            (360, "THIRTY_DAYS"),
            (720, "THIRTY_DAYS"),
            (1000, "TWELVE_MONTHS"),
        ],
    )
    def test_maps_hours_to_correct_period(self, hours, expected_period):
        proc = AlertAnalyticsWorkflowProcessor()
        assert proc._determine_period_from_hours(hours) == expected_period


class TestIsCostRelatedAlert:
    """Tests for _is_cost_related_alert: cost classification logic."""

    def test_cost_metric_detected(self):
        proc = AlertAnalyticsWorkflowProcessor()
        ctx = _make_alert_context(affected_metrics={"TOTAL_COST": 100.0})
        assert proc._is_cost_related_alert(ctx) is True

    def test_spending_metric_detected(self):
        proc = AlertAnalyticsWorkflowProcessor()
        ctx = _make_alert_context(affected_metrics={"daily_spending": 50.0})
        assert proc._is_cost_related_alert(ctx) is True

    def test_non_cost_metric_not_detected(self):
        proc = AlertAnalyticsWorkflowProcessor()
        ctx = _make_alert_context(
            affected_metrics={"REQUEST_COUNT": 5000},
            anomaly_name="High Traffic Alert",
        )
        assert proc._is_cost_related_alert(ctx) is False

    def test_cost_in_anomaly_name(self):
        proc = AlertAnalyticsWorkflowProcessor()
        ctx = _make_alert_context(
            affected_metrics={"METRIC_A": 10},
            anomaly_name="Cost Spike Anomaly",
        )
        assert proc._is_cost_related_alert(ctx) is True

    def test_none_anomaly_name(self):
        proc = AlertAnalyticsWorkflowProcessor()
        ctx = _make_alert_context(
            affected_metrics={"REQUEST_COUNT": 100},
            anomaly_name=None,
        )
        assert proc._is_cost_related_alert(ctx) is False


class TestExtractCostThreshold:
    """Tests for _extract_cost_threshold: threshold extraction from alert context."""

    def test_extracts_from_threshold_violations(self):
        proc = AlertAnalyticsWorkflowProcessor()
        ctx = _make_alert_context(
            threshold_violations=[{"metric": "cost", "threshold": 250.0}]
        )
        assert proc._extract_cost_threshold(ctx) == 250.0

    def test_returns_default_when_no_violations(self):
        proc = AlertAnalyticsWorkflowProcessor()
        ctx = _make_alert_context(
            threshold_violations=[],
            affected_metrics={"REQUEST_COUNT": 100},
        )
        assert proc._extract_cost_threshold(ctx) == 100.0

    def test_extracts_from_affected_metrics_threshold_key(self):
        proc = AlertAnalyticsWorkflowProcessor()
        ctx = _make_alert_context(
            threshold_violations=[{"metric": "cost"}],  # no "threshold" key
            affected_metrics={"cost_threshold": 300.0},
        )
        assert proc._extract_cost_threshold(ctx) == 300.0

    def test_handles_invalid_metric_value(self):
        proc = AlertAnalyticsWorkflowProcessor()
        ctx = _make_alert_context(
            threshold_violations=[{"metric": "cost"}],
            affected_metrics={"cost_threshold": "not_a_number"},
        )
        # Should fall through to default
        assert proc._extract_cost_threshold(ctx) == 100.0


class TestParseTimestamp:
    """Tests for _parse_timestamp: timestamp parsing from various formats."""

    def test_passthrough_datetime(self):
        proc = AlertAnalyticsWorkflowProcessor()
        dt = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
        assert proc._parse_timestamp(dt) == dt

    def test_iso_format_string(self):
        proc = AlertAnalyticsWorkflowProcessor()
        result = proc._parse_timestamp("2025-06-01T12:00:00Z")
        assert isinstance(result, datetime)
        assert result.year == 2025

    def test_common_format_string(self):
        proc = AlertAnalyticsWorkflowProcessor()
        result = proc._parse_timestamp("2025-06-01 12:00:00")
        assert isinstance(result, datetime)
        assert result.year == 2025

    def test_invalid_returns_current_time(self):
        proc = AlertAnalyticsWorkflowProcessor()
        result = proc._parse_timestamp(12345)
        assert isinstance(result, datetime)
        # Fallback must be timezone-aware (UTC)
        assert result.utcoffset().total_seconds() == 0

    def test_unparseable_string_returns_current_time(self):
        proc = AlertAnalyticsWorkflowProcessor()
        result = proc._parse_timestamp("not-a-date")
        assert isinstance(result, datetime)
        # Fallback must be timezone-aware (UTC)
        assert result.utcoffset().total_seconds() == 0


class TestIsTransactionRelatedAlert:
    """Tests for _is_transaction_related_alert."""

    def test_transaction_metric_detected(self):
        proc = AlertAnalyticsWorkflowProcessor()
        ctx = _make_alert_context(affected_metrics={"transaction_count": 1000})
        assert proc._is_transaction_related_alert(ctx) is True

    def test_latency_metric_detected(self):
        proc = AlertAnalyticsWorkflowProcessor()
        ctx = _make_alert_context(affected_metrics={"response_time_p99": 500})
        assert proc._is_transaction_related_alert(ctx) is True

    def test_agent_in_anomaly_name(self):
        proc = AlertAnalyticsWorkflowProcessor()
        ctx = _make_alert_context(
            affected_metrics={"METRIC_A": 10},
            anomaly_name="Agent Performance Degradation",
        )
        assert proc._is_transaction_related_alert(ctx) is True

    def test_non_transaction_metric(self):
        proc = AlertAnalyticsWorkflowProcessor()
        ctx = _make_alert_context(
            affected_metrics={"TOTAL_COST": 100},
            anomaly_name="Cost Alert",
        )
        assert proc._is_transaction_related_alert(ctx) is False


class TestAnalyzeTransactionCorrelation:
    """Tests for _analyze_transaction_correlation."""

    def test_no_correlation_with_empty_data(self):
        proc = AlertAnalyticsWorkflowProcessor()
        ctx = _make_alert_context()
        correlation = proc._analyze_transaction_correlation(
            ctx, {"agent_metrics": {}, "task_metrics": {}}
        )
        assert correlation["agent_correlation"] == "none"
        assert correlation["correlation_confidence"] == 0.0

    def test_agent_correlation_detected(self):
        proc = AlertAnalyticsWorkflowProcessor()
        ctx = _make_alert_context()
        tx_data = {
            "agent_metrics": {"cost_trends": {"direction": "up"}},
            "task_metrics": {},
        }
        correlation = proc._analyze_transaction_correlation(ctx, tx_data)
        assert correlation["agent_correlation"] == "detected"
        assert correlation["correlation_confidence"] > 0.0

    def test_includes_alert_metadata(self):
        proc = AlertAnalyticsWorkflowProcessor()
        ctx = _make_alert_context(severity="critical")
        correlation = proc._analyze_transaction_correlation(ctx, {})
        assert correlation["alert_severity"] == "critical"


class TestAnalyzeTimelinePatterns:
    """Tests for _analyze_timeline_patterns."""

    def test_default_patterns(self):
        proc = AlertAnalyticsWorkflowProcessor()
        trigger = datetime(2025, 6, 1, 14, 30, tzinfo=timezone.utc)
        patterns = proc._analyze_timeline_patterns(None, trigger)
        assert patterns["pre_alert_trend"] == "stable"
        assert patterns["trigger_hour"] == 14
        assert patterns["trigger_day_of_week"] == trigger.weekday()

    def test_increasing_trend_direction(self):
        proc = AlertAnalyticsWorkflowProcessor()
        trigger = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)

        class MockTrends:
            trend_direction = "increasing"

        patterns = proc._analyze_timeline_patterns(MockTrends(), trigger)
        assert patterns["pre_alert_trend"] == "increasing"
        assert patterns["pattern_confidence"] == 0.8


class TestCalculateConfidenceScore:
    """Tests for _calculate_confidence_score."""

    def test_base_confidence_no_data(self):
        proc = AlertAnalyticsWorkflowProcessor()
        score = proc._calculate_confidence_score({}, {}, {}, [])
        assert 0.0 <= score <= 1.0

    def test_higher_confidence_with_more_data(self):
        proc = AlertAnalyticsWorkflowProcessor()
        score_minimal = proc._calculate_confidence_score({}, {}, {}, [])
        score_full = proc._calculate_confidence_score(
            {"type": "cost"},
            {"type": "timeline"},
            {"type": "transaction"},
            [{"confidence": 0.9, "type": "cost_spike"}],
        )
        assert score_full > score_minimal

    def test_transaction_correlation_boost(self):
        proc = AlertAnalyticsWorkflowProcessor()
        tx_no_corr = {"type": "transaction"}
        tx_with_corr = {
            "type": "transaction",
            "correlation_analysis": {"correlation_confidence": 0.8},
        }
        score_no = proc._calculate_confidence_score({}, {}, tx_no_corr, [])
        score_with = proc._calculate_confidence_score({}, {}, tx_with_corr, [])
        assert score_with > score_no

    def test_confidence_never_exceeds_1(self):
        proc = AlertAnalyticsWorkflowProcessor()
        many_factors = [{"confidence": 1.0} for _ in range(10)]
        score = proc._calculate_confidence_score(
            {"type": "cost"},
            {"type": "timeline"},
            {"type": "tx", "correlation_analysis": {"correlation_confidence": 1.0}},
            many_factors,
        )
        assert score <= 1.0


class TestIdentifyContributingFactors:
    """Tests for _identify_contributing_factors (async)."""

    @pytest.mark.asyncio
    async def test_threshold_violations_always_factor(self):
        proc = AlertAnalyticsWorkflowProcessor()
        ctx = _make_alert_context()
        factors = await proc._identify_contributing_factors(ctx, {}, {}, {})
        types = [f["type"] for f in factors]
        assert "threshold_violation" in types

    @pytest.mark.asyncio
    async def test_cost_spike_factor(self):
        proc = AlertAnalyticsWorkflowProcessor()
        ctx = _make_alert_context()
        cost_data = {
            "is_cost_related": True,
            "spike_analysis": {"spike_analysis": {"detected": True}},
        }
        factors = await proc._identify_contributing_factors(ctx, cost_data, {}, {})
        types = [f["type"] for f in factors]
        assert "cost_spike" in types

    @pytest.mark.asyncio
    async def test_trend_escalation_factor(self):
        proc = AlertAnalyticsWorkflowProcessor()
        ctx = _make_alert_context()
        timeline_data = {"timeline_patterns": {"pre_alert_trend": "increasing", "pattern_confidence": 0.8}}
        factors = await proc._identify_contributing_factors(ctx, {}, timeline_data, {})
        types = [f["type"] for f in factors]
        assert "trend_escalation" in types

    @pytest.mark.asyncio
    async def test_transaction_correlation_factor(self):
        proc = AlertAnalyticsWorkflowProcessor()
        ctx = _make_alert_context()
        tx_data = {
            "is_transaction_related": True,
            "correlation_analysis": {"correlation_confidence": 0.7},
        }
        factors = await proc._identify_contributing_factors(ctx, {}, {}, tx_data)
        types = [f["type"] for f in factors]
        assert "transaction_correlation" in types


class TestGenerateRecommendations:
    """Tests for _generate_recommendations."""

    @pytest.mark.asyncio
    async def test_critical_severity_adds_urgent_recs(self):
        proc = AlertAnalyticsWorkflowProcessor()
        ctx = _make_alert_context(severity="critical")
        recs = await proc._generate_recommendations(ctx, [])
        assert any("CRITICAL" in r for r in recs)

    @pytest.mark.asyncio
    async def test_always_includes_general_recs(self):
        proc = AlertAnalyticsWorkflowProcessor()
        ctx = _make_alert_context()
        recs = await proc._generate_recommendations(ctx, [])
        assert any("Document" in r for r in recs)
        assert any("monitoring" in r.lower() for r in recs)

    @pytest.mark.asyncio
    async def test_cost_spike_factor_recs(self):
        proc = AlertAnalyticsWorkflowProcessor()
        ctx = _make_alert_context()
        factors = [{"type": "cost_spike"}]
        recs = await proc._generate_recommendations(ctx, factors)
        assert any("cost" in r.lower() for r in recs)

    @pytest.mark.asyncio
    async def test_threshold_violation_factor_recs(self):
        proc = AlertAnalyticsWorkflowProcessor()
        ctx = _make_alert_context()
        factors = [{"type": "threshold_violation"}]
        recs = await proc._generate_recommendations(ctx, factors)
        assert any("threshold" in r.lower() for r in recs)


class TestFormatRootCauseAnalysis:
    """Tests for format_root_cause_analysis: output formatting."""

    def test_includes_alert_id(self):
        proc = AlertAnalyticsWorkflowProcessor()
        ctx = _make_alert_context()
        analysis = RootCauseAnalysis(
            alert_context=ctx,
            cost_analysis={},
            timeline_analysis={},
            transaction_analysis={},
            contributing_factors=[
                {"type": "threshold_violation", "description": "test", "confidence": 0.9, "impact": "high"}
            ],
            recommendations=["Fix it"],
            confidence_score=0.75,
            analysis_timestamp=datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        )
        formatted = proc.format_root_cause_analysis(analysis)
        assert "alert-001" in formatted
        assert "75.0%" in formatted
        assert "Fix it" in formatted

    def test_includes_contributing_factors(self):
        proc = AlertAnalyticsWorkflowProcessor()
        ctx = _make_alert_context()
        analysis = RootCauseAnalysis(
            alert_context=ctx,
            cost_analysis={},
            timeline_analysis={},
            transaction_analysis={},
            contributing_factors=[
                {"type": "cost_spike", "description": "Cost went up", "confidence": 0.95, "impact": "high"},
                {"type": "metric_anomaly", "description": "Metric abnormal", "confidence": 0.5, "impact": "medium"},
            ],
            recommendations=[],
            confidence_score=0.8,
            analysis_timestamp=datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        )
        formatted = proc.format_root_cause_analysis(analysis)
        assert "Cost Spike" in formatted
        assert "Metric Anomaly" in formatted
