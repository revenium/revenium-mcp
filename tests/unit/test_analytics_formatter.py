"""Unit tests for AnalyticsFormatter in alerts/analytics_formatter.py.

Tests formatting helpers, report generation, insight generation,
and recommendation logic.
"""

import pytest
from datetime import datetime, timedelta, timezone

from src.revenium_mcp_server.alerts.analytics_formatter import AnalyticsFormatter
from src.revenium_mcp_server.alerts.analytics_engine import (
    AlertTrendData,
    AnomalyFrequencyData,
    TimeRange,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def time_range_7d():
    end = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    start = end - timedelta(days=7)
    return TimeRange(start=start, end=end)


@pytest.fixture
def time_range_24h():
    end = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    start = end - timedelta(hours=24)
    return TimeRange(start=start, end=end)


@pytest.fixture
def basic_anomaly_data():
    return AnomalyFrequencyData(
        total_anomalies=20,
        active_anomalies=15,
        inactive_anomalies=5,
        enabled_anomalies=18,
        disabled_anomalies=2,
        anomalies_by_status={"active": 15, "inactive": 5},
        anomalies_by_team={"team-1": 10, "team-2": 7, "team-3": 3},
        detection_rule_types={"threshold": 12, "statistical": 8},
        most_common_metrics=[("TOTAL_COST", 8), ("ERROR_RATE", 6), ("TOKEN_COUNT", 4)],
        creation_trend=[],
    )


@pytest.fixture
def basic_alert_data():
    return AlertTrendData(
        total_alerts=50,
        alerts_by_severity={"critical": 5, "high": 15, "medium": 20, "low": 10},
        alerts_by_status={"resolved": 30, "open": 15, "acknowledged": 5},
        resolution_times=[0.5, 1.0, 2.0, 4.0, 8.0, 12.0, 24.0, 48.0],
        alert_frequency=[],
        top_triggering_anomalies=[],
    )


# ---------------------------------------------------------------------------
# _create_progress_bar / _create_mini_bar: visual bar generation
# ---------------------------------------------------------------------------


class TestProgressBar:
    def test_full_bar(self):
        bar = AnalyticsFormatter._create_progress_bar(100, 10)
        assert bar == "[" + "\u2588" * 10 + "]"

    def test_empty_bar(self):
        bar = AnalyticsFormatter._create_progress_bar(0, 10)
        assert bar == "[" + "\u2591" * 10 + "]"

    def test_half_bar(self):
        bar = AnalyticsFormatter._create_progress_bar(50, 10)
        assert "\u2588" * 5 in bar
        assert "\u2591" * 5 in bar

    def test_mini_bar_zero_max(self):
        bar = AnalyticsFormatter._create_mini_bar(5, 0, 10)
        assert bar == "\u2581" * 10

    def test_mini_bar_proportional(self):
        bar = AnalyticsFormatter._create_mini_bar(5, 10, 10)
        assert "\u2587" * 5 in bar


# ---------------------------------------------------------------------------
# _format_duration: hours to human-readable
# ---------------------------------------------------------------------------


class TestFormatDuration:
    def test_minutes(self):
        assert AnalyticsFormatter._format_duration(0.5) == "30m"

    def test_hours(self):
        assert AnalyticsFormatter._format_duration(3.5) == "3.5h"

    def test_days(self):
        result = AnalyticsFormatter._format_duration(50)
        assert "2d" in result
        assert "2h" in result

    def test_zero(self):
        assert AnalyticsFormatter._format_duration(0) == "0m"


# ---------------------------------------------------------------------------
# _format_time_ago: timedelta to human-readable
# ---------------------------------------------------------------------------


class TestFormatTimeAgo:
    def test_seconds(self):
        assert AnalyticsFormatter._format_time_ago(timedelta(seconds=30)) == "30s"

    def test_minutes(self):
        assert AnalyticsFormatter._format_time_ago(timedelta(minutes=15)) == "15m"

    def test_hours(self):
        assert AnalyticsFormatter._format_time_ago(timedelta(hours=3)) == "3h"

    def test_days(self):
        assert AnalyticsFormatter._format_time_ago(timedelta(days=5)) == "5d"


# ---------------------------------------------------------------------------
# _get_ranking_emoji: returns simple number format
# ---------------------------------------------------------------------------


class TestRankingEmoji:
    def test_first(self):
        assert AnalyticsFormatter._get_ranking_emoji(1) == "1."

    def test_tenth(self):
        assert AnalyticsFormatter._get_ranking_emoji(10) == "10."


# ---------------------------------------------------------------------------
# _analyze_trend_pattern: trend direction analysis
# ---------------------------------------------------------------------------


class TestAnalyzeTrendPattern:
    def test_insufficient_data(self):
        result = AnalyticsFormatter._analyze_trend_pattern([])
        assert "Insufficient data" in result

    def test_single_point(self):
        result = AnalyticsFormatter._analyze_trend_pattern([{"date": "2024-01-01", "count": 5}])
        assert "Insufficient data" in result

    def test_stable_trend(self):
        trend = [{"date": f"2024-01-{i+1:02d}", "count": 5} for i in range(14)]
        result = AnalyticsFormatter._analyze_trend_pattern(trend)
        assert "Stable" in result

    def test_increasing_trend(self):
        # First 7 days low, last 7 high
        trend = [{"date": f"2024-01-{i+1:02d}", "count": 1} for i in range(7)]
        trend += [{"date": f"2024-01-{i+8:02d}", "count": 10} for i in range(7)]
        result = AnalyticsFormatter._analyze_trend_pattern(trend)
        assert "Increasing" in result

    def test_decreasing_trend(self):
        trend = [{"date": f"2024-01-{i+1:02d}", "count": 10} for i in range(7)]
        trend += [{"date": f"2024-01-{i+8:02d}", "count": 1} for i in range(7)]
        result = AnalyticsFormatter._analyze_trend_pattern(trend)
        assert "Decreasing" in result


# ---------------------------------------------------------------------------
# _analyze_resolution_times: resolution stats computation
# ---------------------------------------------------------------------------


class TestAnalyzeResolutionTimes:
    def test_empty_list(self):
        result = AnalyticsFormatter._analyze_resolution_times([])
        assert "No resolution time data" in result[0]

    def test_basic_stats(self):
        result = AnalyticsFormatter._analyze_resolution_times([1.0, 2.0, 3.0, 4.0])
        text = "\n".join(result)
        assert "Fastest" in text
        assert "Slowest" in text
        assert "Average" in text
        assert "Median" in text

    def test_excellent_performance(self):
        result = AnalyticsFormatter._analyze_resolution_times([0.2, 0.5, 0.8])
        text = "\n".join(result)
        assert "Excellent" in text

    def test_poor_performance(self):
        result = AnalyticsFormatter._analyze_resolution_times([25.0, 30.0, 48.0])
        text = "\n".join(result)
        assert "Poor" in text

    def test_percentiles_with_enough_data(self):
        times = [float(i) for i in range(1, 21)]  # 20 data points
        result = AnalyticsFormatter._analyze_resolution_times(times)
        text = "\n".join(result)
        assert "90th Percentile" in text
        assert "95th Percentile" in text


# ---------------------------------------------------------------------------
# _analyze_alert_frequency_pattern: frequency insight generation
# ---------------------------------------------------------------------------


class TestAnalyzeAlertFrequencyPattern:
    def test_empty_data(self):
        result = AnalyticsFormatter._analyze_alert_frequency_pattern([])
        assert "No frequency data" in result[0]

    def test_zero_alerts(self):
        data = [{"timestamp": "2024-01-15T00:00:00", "count": 0}]
        result = AnalyticsFormatter._analyze_alert_frequency_pattern(data)
        assert "No alerts" in result[0]

    def test_peak_activity_identified(self):
        data = [
            {"timestamp": "2024-01-15T10:00:00", "count": 5},
            {"timestamp": "2024-01-15T11:00:00", "count": 15},
            {"timestamp": "2024-01-15T12:00:00", "count": 3},
        ]
        result = AnalyticsFormatter._analyze_alert_frequency_pattern(data)
        text = "\n".join(result)
        assert "Peak Activity" in text

    def test_quiet_periods_detected(self):
        data = [
            {"timestamp": "2024-01-15T10:00:00", "count": 5},
            {"timestamp": "2024-01-15T11:00:00", "count": 0},
            {"timestamp": "2024-01-15T12:00:00", "count": 0},
        ]
        result = AnalyticsFormatter._analyze_alert_frequency_pattern(data)
        text = "\n".join(result)
        assert "Quiet Periods" in text


# ---------------------------------------------------------------------------
# _generate_anomaly_insights: insights from anomaly data
# ---------------------------------------------------------------------------


class TestGenerateAnomalyInsights:
    def test_high_activation_rate(self):
        data = AnomalyFrequencyData(
            total_anomalies=10, active_anomalies=9, inactive_anomalies=1,
            enabled_anomalies=10, disabled_anomalies=0,
            anomalies_by_status={}, anomalies_by_team={"t1": 10},
            detection_rule_types={"threshold": 5, "statistical": 3, "pattern": 2},
            most_common_metrics=[], creation_trend=[],
        )
        insights = AnalyticsFormatter._generate_anomaly_insights(data)
        text = " ".join(insights)
        assert "High activation" in text or "well-configured" in text

    def test_low_activation_rate(self):
        data = AnomalyFrequencyData(
            total_anomalies=10, active_anomalies=3, inactive_anomalies=7,
            enabled_anomalies=10, disabled_anomalies=0,
            anomalies_by_status={}, anomalies_by_team={"t1": 10},
            detection_rule_types={"threshold": 10},
            most_common_metrics=[], creation_trend=[],
        )
        insights = AnalyticsFormatter._generate_anomaly_insights(data)
        text = " ".join(insights)
        assert "Low activation" in text or "inactive" in text

    def test_disabled_anomalies_warning(self):
        data = AnomalyFrequencyData(
            total_anomalies=10, active_anomalies=8, inactive_anomalies=2,
            enabled_anomalies=7, disabled_anomalies=3,
            anomalies_by_status={}, anomalies_by_team={"t1": 10},
            detection_rule_types={"threshold": 10},
            most_common_metrics=[], creation_trend=[],
        )
        insights = AnalyticsFormatter._generate_anomaly_insights(data)
        text = " ".join(insights)
        assert "disabled" in text.lower()


# ---------------------------------------------------------------------------
# _generate_anomaly_recommendations
# ---------------------------------------------------------------------------


class TestGenerateAnomalyRecommendations:
    def test_low_activation_recommendation(self):
        data = AnomalyFrequencyData(
            total_anomalies=10, active_anomalies=5, inactive_anomalies=5,
            enabled_anomalies=10, disabled_anomalies=0,
            anomalies_by_status={}, anomalies_by_team={},
            detection_rule_types={}, most_common_metrics=[("COST", 10)],
            creation_trend=[],
        )
        recs = AnalyticsFormatter._generate_anomaly_recommendations(data)
        text = " ".join(recs)
        assert "activate" in text.lower() or "obsolete" in text.lower()

    def test_missing_statistical_rules(self):
        data = AnomalyFrequencyData(
            total_anomalies=10, active_anomalies=10, inactive_anomalies=0,
            enabled_anomalies=10, disabled_anomalies=0,
            anomalies_by_status={}, anomalies_by_team={},
            detection_rule_types={"threshold": 10},
            most_common_metrics=[("COST", 10)],
            creation_trend=[],
        )
        recs = AnalyticsFormatter._generate_anomaly_recommendations(data)
        text = " ".join(recs)
        assert "statistical" in text.lower()

    def test_no_recent_creation(self):
        data = AnomalyFrequencyData(
            total_anomalies=10, active_anomalies=10, inactive_anomalies=0,
            enabled_anomalies=10, disabled_anomalies=0,
            anomalies_by_status={}, anomalies_by_team={},
            detection_rule_types={"threshold": 5, "statistical": 5},
            most_common_metrics=[("A", 1), ("B", 1), ("C", 1), ("D", 1), ("E", 1)],
            creation_trend=[{"date": f"2024-01-{i+1:02d}", "count": 0} for i in range(7)],
        )
        recs = AnalyticsFormatter._generate_anomaly_recommendations(data)
        text = " ".join(recs)
        assert "recent" in text.lower() or "gap" in text.lower()


# ---------------------------------------------------------------------------
# _generate_alert_insights: insights from alert trend data
# ---------------------------------------------------------------------------


class TestGenerateAlertInsights:
    def test_high_alert_rate(self, time_range_24h):
        data = AlertTrendData(
            total_alerts=500, alerts_by_severity={}, alerts_by_status={},
            resolution_times=[], alert_frequency=[], top_triggering_anomalies=[],
        )
        insights = AnalyticsFormatter._generate_alert_insights(data, time_range_24h)
        text = " ".join(insights)
        assert "high" in text.lower() or "fatigue" in text.lower()

    def test_no_alerts(self, time_range_24h):
        data = AlertTrendData(
            total_alerts=0, alerts_by_severity={}, alerts_by_status={},
            resolution_times=[], alert_frequency=[], top_triggering_anomalies=[],
        )
        insights = AnalyticsFormatter._generate_alert_insights(data, time_range_24h)
        text = " ".join(insights)
        assert "No alerts" in text

    def test_high_critical_percentage(self, time_range_24h):
        data = AlertTrendData(
            total_alerts=10, alerts_by_severity={"critical": 8, "low": 2},
            alerts_by_status={}, resolution_times=[],
            alert_frequency=[], top_triggering_anomalies=[],
        )
        insights = AnalyticsFormatter._generate_alert_insights(data, time_range_24h)
        text = " ".join(insights)
        assert "critical" in text.lower() or "threshold" in text.lower()


# ---------------------------------------------------------------------------
# _generate_alert_recommendations
# ---------------------------------------------------------------------------


class TestGenerateAlertRecommendations:
    def test_high_volume_recommendation(self):
        data = AlertTrendData(
            total_alerts=1500, alerts_by_severity={}, alerts_by_status={},
            resolution_times=[], alert_frequency=[], top_triggering_anomalies=[],
        )
        recs = AnalyticsFormatter._generate_alert_recommendations(data)
        text = " ".join(recs)
        assert "consolidation" in text.lower() or "noise" in text.lower()

    def test_high_resolution_time_recommendation(self):
        data = AlertTrendData(
            total_alerts=10, alerts_by_severity={}, alerts_by_status={},
            resolution_times=[5.0, 6.0, 7.0], alert_frequency=[],
            top_triggering_anomalies=[],
        )
        recs = AnalyticsFormatter._generate_alert_recommendations(data)
        text = " ".join(recs)
        assert "automated" in text.lower() or "resolution" in text.lower()

    def test_top_anomaly_dominance(self):
        data = AlertTrendData(
            total_alerts=100, alerts_by_severity={}, alerts_by_status={},
            resolution_times=[], alert_frequency=[],
            top_triggering_anomalies=[
                {"anomaly_name": "Noisy Alert", "anomaly_id": "a1", "alert_count": 50}
            ],
        )
        recs = AnalyticsFormatter._generate_alert_recommendations(data)
        text = " ".join(recs)
        assert "Noisy Alert" in text


# ---------------------------------------------------------------------------
# format_anomaly_frequency_report: full report generation
# ---------------------------------------------------------------------------


class TestFormatAnomalyFrequencyReport:
    def test_generates_complete_report(self, basic_anomaly_data, time_range_7d):
        report = AnalyticsFormatter.format_anomaly_frequency_report(
            basic_anomaly_data, time_range_7d
        )
        assert "Anomaly Frequency Analysis" in report
        assert "Overview" in report
        assert "Total Anomalies" in report
        assert "20" in report
        assert "Health Insights" in report
        assert "Recommendations" in report

    def test_includes_team_distribution(self, basic_anomaly_data, time_range_7d):
        report = AnalyticsFormatter.format_anomaly_frequency_report(
            basic_anomaly_data, time_range_7d
        )
        assert "team-1" in report

    def test_includes_detection_rules(self, basic_anomaly_data, time_range_7d):
        report = AnalyticsFormatter.format_anomaly_frequency_report(
            basic_anomaly_data, time_range_7d
        )
        assert "threshold" in report.lower()


# ---------------------------------------------------------------------------
# format_alert_trend_report: full report generation
# ---------------------------------------------------------------------------


class TestFormatAlertTrendReport:
    def test_generates_complete_report(self, basic_alert_data, time_range_24h):
        report = AnalyticsFormatter.format_alert_trend_report(
            basic_alert_data, time_range_24h
        )
        assert "Alert Trend Analysis" in report
        assert "Total Alerts" in report
        assert "50" in report
        assert "Resolution Time" in report
        assert "Insights" in report

    def test_includes_anomaly_id_in_title(self, basic_alert_data, time_range_24h):
        report = AnalyticsFormatter.format_alert_trend_report(
            basic_alert_data, time_range_24h, anomaly_id="anom-123"
        )
        assert "anom-123" in report

    def test_severity_distribution(self, basic_alert_data, time_range_24h):
        report = AnalyticsFormatter.format_alert_trend_report(
            basic_alert_data, time_range_24h
        )
        assert "Severity Distribution" in report
        assert "Critical" in report

    def test_status_distribution(self, basic_alert_data, time_range_24h):
        report = AnalyticsFormatter.format_alert_trend_report(
            basic_alert_data, time_range_24h
        )
        assert "Status Distribution" in report


# ---------------------------------------------------------------------------
# format_top_alerting_anomalies_report
# ---------------------------------------------------------------------------


class TestFormatTopAlertingAnomaliesReport:
    def test_empty_anomalies(self, time_range_7d):
        report = AnalyticsFormatter.format_top_alerting_anomalies_report([], time_range_7d)
        assert "No alerting anomalies found" in report

    def test_formats_anomalies(self, time_range_7d):
        anomalies = [
            {
                "anomaly_name": "Cost Spike",
                "anomaly_id": "a1",
                "alert_count": 25,
                "most_common_severity": "high",
            },
            {
                "anomaly_name": "Error Rate",
                "anomaly_id": "a2",
                "alert_count": 10,
                "most_common_severity": "medium",
            },
        ]
        report = AnalyticsFormatter.format_top_alerting_anomalies_report(
            anomalies, time_range_7d
        )
        assert "Cost Spike" in report
        assert "Error Rate" in report
        assert "Summary" in report
        assert "35" in report  # total alerts
