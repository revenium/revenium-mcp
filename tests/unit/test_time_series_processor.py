"""Unit tests for TimeSeriesProcessor.

Tests behavioral correctness of time series aggregation, trend analysis,
period comparison, anomaly detection, data smoothing, and helper computations.
"""

import pytest
import statistics
from datetime import datetime, timedelta, timezone

from src.revenium_mcp_server.analytics.time_series_processor import (
    TimeSeriesProcessor,
    TimeSeriesPoint,
    TrendDirection,
    AggregationType,
)


def _make_points(values, start=None, interval_hours=1):
    """Create a list of TimeSeriesPoint from values."""
    start = start or datetime(2025, 1, 1, tzinfo=timezone.utc)
    return [
        TimeSeriesPoint(
            timestamp=start + timedelta(hours=i * interval_hours),
            value=v,
        )
        for i, v in enumerate(values)
    ]


class TestAggregateValues:
    """Tests for _aggregate_values: core aggregation logic."""

    def test_sum(self):
        proc = TimeSeriesProcessor()
        assert proc._aggregate_values([1, 2, 3], AggregationType.SUM) == 6

    def test_mean(self):
        proc = TimeSeriesProcessor()
        assert proc._aggregate_values([2, 4, 6], AggregationType.MEAN) == 4.0

    def test_median(self):
        proc = TimeSeriesProcessor()
        assert proc._aggregate_values([1, 2, 100], AggregationType.MEDIAN) == 2

    def test_min(self):
        proc = TimeSeriesProcessor()
        assert proc._aggregate_values([3, 1, 2], AggregationType.MIN) == 1

    def test_max(self):
        proc = TimeSeriesProcessor()
        assert proc._aggregate_values([3, 1, 2], AggregationType.MAX) == 3

    def test_count(self):
        proc = TimeSeriesProcessor()
        assert proc._aggregate_values([10, 20, 30], AggregationType.COUNT) == 3.0

    def test_empty_list_returns_zero(self):
        proc = TimeSeriesProcessor()
        assert proc._aggregate_values([], AggregationType.SUM) == 0.0


class TestCalculateSlope:
    """Tests for _calculate_slope: linear regression slope."""

    def test_increasing_values_positive_slope(self):
        proc = TimeSeriesProcessor()
        slope = proc._calculate_slope([1, 2, 3, 4, 5])
        assert slope > 0

    def test_decreasing_values_negative_slope(self):
        proc = TimeSeriesProcessor()
        slope = proc._calculate_slope([5, 4, 3, 2, 1])
        assert slope < 0

    def test_constant_values_zero_slope(self):
        proc = TimeSeriesProcessor()
        slope = proc._calculate_slope([3, 3, 3, 3])
        assert slope == 0.0

    def test_single_value_returns_zero(self):
        proc = TimeSeriesProcessor()
        slope = proc._calculate_slope([5])
        assert slope == 0.0


class TestDetermineTrendDirection:
    """Tests for _determine_trend_direction."""

    def test_increasing_trend(self):
        proc = TimeSeriesProcessor()
        # Low volatility values (close together), positive slope
        direction = proc._determine_trend_direction(0.5, [100, 101, 102, 103, 104])
        assert direction == TrendDirection.INCREASING

    def test_decreasing_trend(self):
        proc = TimeSeriesProcessor()
        direction = proc._determine_trend_direction(-0.5, [104, 103, 102, 101, 100])
        assert direction == TrendDirection.DECREASING

    def test_stable_trend(self):
        proc = TimeSeriesProcessor()
        direction = proc._determine_trend_direction(0.001, [10, 10, 10, 10])
        assert direction == TrendDirection.STABLE

    def test_volatile_trend(self):
        proc = TimeSeriesProcessor()
        # High coefficient of variation (volatility > 0.5)
        direction = proc._determine_trend_direction(0.5, [1, 100, 1, 100])
        assert direction == TrendDirection.VOLATILE


class TestCalculateVolatility:
    """Tests for _calculate_volatility."""

    def test_zero_volatility_for_constant(self):
        proc = TimeSeriesProcessor()
        assert proc._calculate_volatility([5, 5, 5, 5]) == 0.0

    def test_positive_volatility_for_varying(self):
        proc = TimeSeriesProcessor()
        vol = proc._calculate_volatility([1, 10, 1, 10])
        assert vol > 0

    def test_single_value_returns_zero(self):
        proc = TimeSeriesProcessor()
        assert proc._calculate_volatility([5]) == 0.0

    def test_zero_mean_returns_zero(self):
        proc = TimeSeriesProcessor()
        assert proc._calculate_volatility([0, 0, 0]) == 0.0


class TestCalculateTrendConfidence:
    """Tests for _calculate_trend_confidence (R-squared)."""

    def test_perfect_linear_trend(self):
        proc = TimeSeriesProcessor()
        confidence = proc._calculate_trend_confidence([1, 2, 3, 4, 5])
        assert confidence == pytest.approx(1.0)

    def test_no_variance_returns_1(self):
        proc = TimeSeriesProcessor()
        confidence = proc._calculate_trend_confidence([5, 5, 5, 5])
        assert confidence == 1.0

    def test_noisy_data_lower_confidence(self):
        proc = TimeSeriesProcessor()
        confidence = proc._calculate_trend_confidence([1, 10, 2, 9, 3])
        assert confidence < 1.0

    def test_single_value_returns_zero(self):
        proc = TimeSeriesProcessor()
        assert proc._calculate_trend_confidence([5]) == 0.0


class TestGenerateTrendSummary:
    """Tests for _generate_trend_summary."""

    def test_stable_summary(self):
        proc = TimeSeriesProcessor()
        summary = proc._generate_trend_summary(TrendDirection.STABLE, 2.0, 0.9)
        assert "Stable" in summary
        assert "high" in summary

    def test_increasing_summary(self):
        proc = TimeSeriesProcessor()
        summary = proc._generate_trend_summary(TrendDirection.INCREASING, 25.0, 0.6)
        assert "Increasing" in summary
        assert "+25.0%" in summary

    def test_decreasing_summary(self):
        proc = TimeSeriesProcessor()
        summary = proc._generate_trend_summary(TrendDirection.DECREASING, -15.0, 0.3)
        assert "Decreasing" in summary
        assert "low" in summary

    def test_volatile_summary(self):
        proc = TimeSeriesProcessor()
        summary = proc._generate_trend_summary(TrendDirection.VOLATILE, 5.0, 0.5)
        assert "Volatile" in summary


class TestAnalyzeTrend:
    """Tests for analyze_trend: end-to-end trend analysis."""

    def test_insufficient_data(self):
        proc = TimeSeriesProcessor()
        result = proc.analyze_trend([_make_points([5])[0]])
        assert result.direction == TrendDirection.STABLE
        assert result.confidence == 0.0
        assert "Insufficient" in result.summary

    def test_increasing_trend_detected(self):
        proc = TimeSeriesProcessor()
        # Use values with low coefficient of variation (mean >> stdev)
        points = _make_points([100, 101, 102, 103, 104, 105, 106, 107, 108, 109])
        result = proc.analyze_trend(points)
        assert result.direction == TrendDirection.INCREASING
        assert result.slope > 0
        assert result.change_percentage > 0

    def test_decreasing_trend_detected(self):
        proc = TimeSeriesProcessor()
        points = _make_points([109, 108, 107, 106, 105, 104, 103, 102, 101, 100])
        result = proc.analyze_trend(points)
        assert result.direction == TrendDirection.DECREASING
        assert result.slope < 0

    def test_zero_start_value_handles_change_percentage(self):
        proc = TimeSeriesProcessor()
        points = _make_points([0, 1, 2, 3])
        result = proc.analyze_trend(points)
        assert result.change_percentage == 0.0  # Division by zero handled


class TestComparePeriods:
    """Tests for compare_periods: period-over-period analysis."""

    def test_increasing_comparison(self):
        proc = TimeSeriesProcessor()
        current = _make_points([10, 20, 30])
        previous = _make_points([5, 10, 15])
        result = proc.compare_periods(current, previous)
        assert result.current_value > result.previous_value
        assert result.absolute_change > 0
        assert result.percentage_change > 0
        assert result.trend_direction == TrendDirection.INCREASING

    def test_stable_comparison(self):
        proc = TimeSeriesProcessor()
        current = _make_points([10, 10, 10])
        previous = _make_points([10, 10, 10])
        result = proc.compare_periods(current, previous)
        assert result.trend_direction == TrendDirection.STABLE
        assert result.significance == "minimal"

    def test_moderate_change_significance(self):
        proc = TimeSeriesProcessor()
        current = _make_points([110])
        previous = _make_points([100])
        result = proc.compare_periods(current, previous)
        assert result.significance == "moderate"

    def test_significant_change(self):
        proc = TimeSeriesProcessor()
        current = _make_points([200])
        previous = _make_points([100])
        result = proc.compare_periods(current, previous)
        assert result.significance == "significant"

    def test_zero_previous_value(self):
        proc = TimeSeriesProcessor()
        current = _make_points([10])
        previous = _make_points([0])
        result = proc.compare_periods(current, previous)
        assert result.percentage_change == float("inf")

    def test_both_zero(self):
        proc = TimeSeriesProcessor()
        current = _make_points([0])
        previous = _make_points([0])
        result = proc.compare_periods(current, previous)
        assert result.percentage_change == 0.0

    def test_mean_aggregation(self):
        proc = TimeSeriesProcessor()
        current = _make_points([10, 20])
        previous = _make_points([5, 15])
        result = proc.compare_periods(current, previous, AggregationType.MEAN)
        assert result.current_value == 15.0
        assert result.previous_value == 10.0


class TestDetectAnomalies:
    """Tests for detect_anomalies: statistical anomaly detection."""

    def test_no_anomalies_in_uniform_data(self):
        proc = TimeSeriesProcessor()
        points = _make_points([10, 10, 10, 10, 10])
        anomalies = proc.detect_anomalies(points)
        assert len(anomalies) == 0

    def test_detects_outlier(self):
        proc = TimeSeriesProcessor()
        points = _make_points([10, 10, 10, 10, 100])
        anomalies = proc.detect_anomalies(points, threshold_std=1.5)
        assert len(anomalies) > 0
        # The outlier (100) should be detected
        anomaly_values = [a[0].value for a in anomalies]
        assert 100 in anomaly_values

    def test_insufficient_data_returns_empty(self):
        proc = TimeSeriesProcessor()
        points = _make_points([10, 20])
        anomalies = proc.detect_anomalies(points)
        assert anomalies == []

    def test_anomaly_score_is_z_score(self):
        proc = TimeSeriesProcessor()
        points = _make_points([10, 10, 10, 10, 50])
        anomalies = proc.detect_anomalies(points, threshold_std=1.0)
        if anomalies:
            _, z_score = anomalies[0]
            assert z_score > 1.0


class TestSmoothData:
    """Tests for smooth_data: moving average smoothing."""

    def test_smoothing_reduces_noise(self):
        proc = TimeSeriesProcessor()
        noisy = _make_points([1, 100, 1, 100, 1])
        smoothed = proc.smooth_data(noisy, window_size=3)
        # Smoothed values should have less variance
        smooth_values = [p.value for p in smoothed]
        assert statistics.stdev(smooth_values) < statistics.stdev([1, 100, 1, 100, 1])

    def test_returns_original_if_fewer_than_window(self):
        proc = TimeSeriesProcessor()
        points = _make_points([10, 20])
        result = proc.smooth_data(points, window_size=5)
        assert len(result) == 2
        assert result[0].value == 10

    def test_metadata_preserved(self):
        proc = TimeSeriesProcessor()
        points = _make_points([10, 20, 30, 40, 50])
        smoothed = proc.smooth_data(points, window_size=3)
        for p in smoothed:
            assert p.metadata is not None
            assert p.metadata["smoothing_applied"] is True
            assert "original_value" in p.metadata

    def test_timestamp_order_preserved(self):
        proc = TimeSeriesProcessor()
        points = _make_points([10, 20, 30, 40, 50])
        smoothed = proc.smooth_data(points, window_size=3)
        for i in range(len(smoothed) - 1):
            assert smoothed[i].timestamp < smoothed[i + 1].timestamp


class TestAggregateTimeSeries:
    """Tests for aggregate_time_series: bucketing and aggregation."""

    def test_empty_data_returns_empty(self):
        proc = TimeSeriesProcessor()
        result = proc.aggregate_time_series([], AggregationType.SUM, timedelta(hours=1))
        assert result == []

    def test_single_bucket_aggregation(self):
        proc = TimeSeriesProcessor()
        points = _make_points([10, 20, 30], interval_hours=0)
        # All points have same timestamp, one bucket
        result = proc.aggregate_time_series(points, AggregationType.SUM, timedelta(hours=1))
        assert len(result) >= 1

    def test_multiple_buckets(self):
        proc = TimeSeriesProcessor()
        points = _make_points([10, 20, 30, 40], interval_hours=1)
        # 4 hours of data, 2-hour buckets
        result = proc.aggregate_time_series(points, AggregationType.SUM, timedelta(hours=2))
        assert len(result) >= 2

    def test_aggregation_metadata_includes_count(self):
        proc = TimeSeriesProcessor()
        points = _make_points([10, 20, 30], interval_hours=1)
        result = proc.aggregate_time_series(points, AggregationType.MEAN, timedelta(hours=4))
        if result:
            assert "point_count" in result[0].metadata


class TestSupportedPeriods:
    """Test that supported periods are initialized correctly."""

    def test_all_periods_present(self):
        proc = TimeSeriesProcessor()
        expected = {"TWELVE_MONTHS", "THIRTY_DAYS", "SEVEN_DAYS", "TWENTY_FOUR_HOURS", "EIGHT_HOURS", "HOUR"}
        assert set(proc.supported_periods.keys()) == expected
