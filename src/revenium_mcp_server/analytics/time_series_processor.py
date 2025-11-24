"""Time series data processing utilities for analytics.

This module provides comprehensive time series processing capabilities including:
- Time series aggregation and resampling
- Trend calculation and analysis
- Period-over-period comparisons
- Seasonal pattern detection
- Data smoothing and filtering
"""

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

from loguru import logger


class TrendDirection(Enum):
    """Trend direction enumeration."""

    INCREASING = "increasing"
    DECREASING = "decreasing"
    STABLE = "stable"
    VOLATILE = "volatile"


class AggregationType(Enum):
    """Time series aggregation types."""

    SUM = "sum"
    MEAN = "mean"
    MEDIAN = "median"
    MIN = "min"
    MAX = "max"
    COUNT = "count"


@dataclass
class TimeSeriesPoint:
    """Individual time series data point."""

    timestamp: datetime
    value: float
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class TrendAnalysis:
    """Trend analysis result."""

    direction: TrendDirection
    slope: float
    confidence: float
    change_percentage: float
    volatility: float
    summary: str


@dataclass
class PeriodComparison:
    """Period-over-period comparison result."""

    current_value: float
    previous_value: float
    absolute_change: float
    percentage_change: float
    trend_direction: TrendDirection
    significance: str  # "significant", "moderate", "minimal"


class TimeSeriesProcessor:
    """Comprehensive time series data processing utilities.

    Provides advanced time series analysis capabilities for business analytics,
    including trend detection, period comparisons, and data aggregation.
    """

    def __init__(self):
        """Initialize the time series processor."""
        # API-verified periods only - aligned with transaction_level_validation.py
        self.supported_periods = {
            "TWELVE_MONTHS": 365,
            "THIRTY_DAYS": 30,  # API-verified equivalent of ONE_MONTH
            "SEVEN_DAYS": 7,
            "TWENTY_FOUR_HOURS": 1,  # API-verified equivalent of ONE_DAY
            "EIGHT_HOURS": 0.33,  # API-verified short-term period
            "HOUR": 0.04,  # API-verified real-time period
        }

    def aggregate_time_series(
        self, data: List[TimeSeriesPoint], aggregation: AggregationType, bucket_size: timedelta
    ) -> List[TimeSeriesPoint]:
        """Aggregate time series data into time buckets.

        Args:
            data: List of time series data points
            aggregation: Type of aggregation to perform
            bucket_size: Size of time buckets for aggregation

        Returns:
            Aggregated time series data
        """
        if not data:
            return []

        logger.info(f"Aggregating {len(data)} data points with {aggregation.value} aggregation")

        # Sort data by timestamp
        sorted_data = sorted(data, key=lambda x: x.timestamp)

        # Create time buckets
        start_time = sorted_data[0].timestamp
        end_time = sorted_data[-1].timestamp

        buckets = {}
        current_bucket_start = start_time

        while current_bucket_start <= end_time:
            bucket_end = current_bucket_start + bucket_size
            bucket_key = current_bucket_start
            buckets[bucket_key] = []

            # Add data points to bucket
            for point in sorted_data:
                if current_bucket_start <= point.timestamp < bucket_end:
                    buckets[bucket_key].append(point)

            current_bucket_start = bucket_end

        # Aggregate each bucket
        aggregated_data = []
        for bucket_start, bucket_points in buckets.items():
            if bucket_points:
                aggregated_value = self._aggregate_values(
                    [p.value for p in bucket_points], aggregation
                )

                aggregated_point = TimeSeriesPoint(
                    timestamp=bucket_start,
                    value=aggregated_value,
                    metadata={
                        "bucket_size": str(bucket_size),
                        "point_count": len(bucket_points),
                        "aggregation": aggregation.value,
                    },
                )
                aggregated_data.append(aggregated_point)

        logger.info(f"Aggregated to {len(aggregated_data)} time buckets")
        return aggregated_data

    def analyze_trend(
        self, data: List[TimeSeriesPoint], confidence_threshold: float = 0.7
    ) -> TrendAnalysis:
        """Analyze trend in time series data.

        Args:
            data: Time series data points
            confidence_threshold: Minimum confidence for trend detection

        Returns:
            Comprehensive trend analysis
        """
        if len(data) < 2:
            return TrendAnalysis(
                direction=TrendDirection.STABLE,
                slope=0.0,
                confidence=0.0,
                change_percentage=0.0,
                volatility=0.0,
                summary="Insufficient data for trend analysis",
            )

        logger.info(f"Analyzing trend for {len(data)} data points")

        # Sort data by timestamp
        sorted_data = sorted(data, key=lambda x: x.timestamp)
        values = [p.value for p in sorted_data]

        # Calculate linear regression slope
        slope = self._calculate_slope(values)

        # Calculate trend direction
        direction = self._determine_trend_direction(slope, values)

        # Calculate confidence based on R-squared
        confidence = self._calculate_trend_confidence(values)

        # Calculate percentage change
        if values[0] != 0:
            change_percentage = ((values[-1] - values[0]) / abs(values[0])) * 100
        else:
            change_percentage = 0.0

        # Calculate volatility (coefficient of variation)
        volatility = self._calculate_volatility(values)

        # Generate summary
        summary = self._generate_trend_summary(direction, change_percentage, confidence)

        return TrendAnalysis(
            direction=direction,
            slope=slope,
            confidence=confidence,
            change_percentage=change_percentage,
            volatility=volatility,
            summary=summary,
        )

    def compare_periods(
        self,
        current_data: List[TimeSeriesPoint],
        previous_data: List[TimeSeriesPoint],
        aggregation: AggregationType = AggregationType.SUM,
    ) -> PeriodComparison:
        """Compare two time periods for period-over-period analysis.

        Args:
            current_data: Current period data
            previous_data: Previous period data for comparison
            aggregation: How to aggregate period data

        Returns:
            Period comparison analysis
        """
        logger.info("Performing period-over-period comparison")

        # Aggregate period values
        current_value = self._aggregate_values([p.value for p in current_data], aggregation)
        previous_value = self._aggregate_values([p.value for p in previous_data], aggregation)

        # Calculate changes
        absolute_change = current_value - previous_value

        if previous_value != 0:
            percentage_change = (absolute_change / abs(previous_value)) * 100
        else:
            percentage_change = 0.0 if current_value == 0 else float("inf")

        # Determine trend direction
        if abs(percentage_change) < 5:  # Less than 5% change
            trend_direction = TrendDirection.STABLE
        elif percentage_change > 0:
            trend_direction = TrendDirection.INCREASING
        else:
            trend_direction = TrendDirection.DECREASING

        # Determine significance
        if abs(percentage_change) < 5:
            significance = "minimal"
        elif abs(percentage_change) < 20:
            significance = "moderate"
        else:
            significance = "significant"

        return PeriodComparison(
            current_value=current_value,
            previous_value=previous_value,
            absolute_change=absolute_change,
            percentage_change=percentage_change,
            trend_direction=trend_direction,
            significance=significance,
        )

    def detect_anomalies(
        self, data: List[TimeSeriesPoint], threshold_std: float = 2.0
    ) -> List[Tuple[TimeSeriesPoint, float]]:
        """Detect anomalies in time series data using statistical methods.

        Args:
            data: Time series data points
            threshold_std: Number of standard deviations for anomaly threshold

        Returns:
            List of anomalous points with their anomaly scores
        """
        if len(data) < 3:
            return []

        logger.info(f"Detecting anomalies in {len(data)} data points")

        values = [p.value for p in data]
        mean_value = statistics.mean(values)
        std_value = statistics.stdev(values) if len(values) > 1 else 0

        anomalies = []
        for point in data:
            if std_value > 0:
                z_score = abs(point.value - mean_value) / std_value
                if z_score > threshold_std:
                    anomalies.append((point, z_score))

        logger.info(f"Detected {len(anomalies)} anomalies")
        return anomalies

    def smooth_data(
        self, data: List[TimeSeriesPoint], window_size: int = 3
    ) -> List[TimeSeriesPoint]:
        """Apply moving average smoothing to time series data.

        Args:
            data: Time series data points
            window_size: Size of moving average window

        Returns:
            Smoothed time series data
        """
        if len(data) < window_size:
            return data

        logger.info(f"Smoothing {len(data)} data points with window size {window_size}")

        sorted_data = sorted(data, key=lambda x: x.timestamp)
        smoothed_data = []

        for i in range(len(sorted_data)):
            # Calculate window bounds
            start_idx = max(0, i - window_size // 2)
            end_idx = min(len(sorted_data), i + window_size // 2 + 1)

            # Calculate moving average
            window_values = [sorted_data[j].value for j in range(start_idx, end_idx)]
            smoothed_value = statistics.mean(window_values)

            smoothed_point = TimeSeriesPoint(
                timestamp=sorted_data[i].timestamp,
                value=smoothed_value,
                metadata={
                    "original_value": sorted_data[i].value,
                    "window_size": window_size,
                    "smoothing_applied": True,
                },
            )
            smoothed_data.append(smoothed_point)

        return smoothed_data

    def _aggregate_values(self, values: List[float], aggregation: AggregationType) -> float:
        """Aggregate a list of values using the specified aggregation type."""
        if not values:
            return 0.0

        if aggregation == AggregationType.SUM:
            return sum(values)
        elif aggregation == AggregationType.MEAN:
            return statistics.mean(values)
        elif aggregation == AggregationType.MEDIAN:
            return statistics.median(values)
        elif aggregation == AggregationType.MIN:
            return min(values)
        elif aggregation == AggregationType.MAX:
            return max(values)
        elif aggregation == AggregationType.COUNT:
            return float(len(values))
        else:
            return sum(values)  # Default to sum

    def _calculate_slope(self, values: List[float]) -> float:
        """Calculate linear regression slope for trend analysis."""
        n = len(values)
        if n < 2:
            return 0.0

        x_values = list(range(n))
        x_mean = statistics.mean(x_values)
        y_mean = statistics.mean(values)

        numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, values))
        denominator = sum((x - x_mean) ** 2 for x in x_values)

        return numerator / denominator if denominator != 0 else 0.0

    def _determine_trend_direction(self, slope: float, values: List[float]) -> TrendDirection:
        """Determine trend direction based on slope and volatility."""
        volatility = self._calculate_volatility(values)

        if volatility > 0.5:  # High volatility
            return TrendDirection.VOLATILE
        elif abs(slope) < 0.01:  # Very small slope
            return TrendDirection.STABLE
        elif slope > 0:
            return TrendDirection.INCREASING
        else:
            return TrendDirection.DECREASING

    def _calculate_trend_confidence(self, values: List[float]) -> float:
        """Calculate confidence in trend analysis using R-squared."""
        if len(values) < 2:
            return 0.0

        # Simple R-squared calculation for linear trend
        n = len(values)
        x_values = list(range(n))

        # Calculate means
        x_mean = statistics.mean(x_values)
        y_mean = statistics.mean(values)

        # Calculate R-squared
        ss_tot = sum((y - y_mean) ** 2 for y in values)
        if ss_tot == 0:
            return 1.0  # Perfect fit if no variance

        # Calculate predicted values using linear regression
        slope = self._calculate_slope(values)
        intercept = y_mean - slope * x_mean

        predicted = [slope * x + intercept for x in x_values]
        ss_res = sum((y - pred) ** 2 for y, pred in zip(values, predicted))

        r_squared = 1 - (ss_res / ss_tot)
        return max(0.0, min(1.0, r_squared))  # Clamp between 0 and 1

    def _calculate_volatility(self, values: List[float]) -> float:
        """Calculate coefficient of variation as volatility measure."""
        if len(values) < 2:
            return 0.0

        mean_value = statistics.mean(values)
        if mean_value == 0:
            return 0.0

        std_value = statistics.stdev(values)
        return std_value / abs(mean_value)

    def _generate_trend_summary(
        self, direction: TrendDirection, change_percentage: float, confidence: float
    ) -> str:
        """Generate human-readable trend summary."""
        confidence_text = "high" if confidence > 0.8 else "moderate" if confidence > 0.5 else "low"

        if direction == TrendDirection.STABLE:
            return f"Stable trend with {confidence_text} confidence"
        elif direction == TrendDirection.INCREASING:
            return f"Increasing trend (+{change_percentage:.1f}%) with {confidence_text} confidence"
        elif direction == TrendDirection.DECREASING:
            return f"Decreasing trend ({change_percentage:.1f}%) with {confidence_text} confidence"
        else:
            return f"Volatile trend with {confidence_text} confidence"
