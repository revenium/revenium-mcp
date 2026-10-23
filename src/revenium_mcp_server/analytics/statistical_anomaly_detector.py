"""Statistical anomaly detector for temporal analysis.

This module provides deterministic statistical analysis using z-score calculations
for detecting temporal anomalies in cost data. Used by Enhanced Spike Analysis v2.0.
"""

import math
import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from loguru import logger

from ..common.money import render_dollars
from ..models import NewEntityIntroduction

# Sensitivity thresholds as specified in PRD
SENSITIVITY_THRESHOLDS = {
    "conservative": 3.0,  # 3 standard deviations (99.7% confidence)
    "normal": 2.0,  # 2 standard deviations (95% confidence)
    "aggressive": 1.5,  # 1.5 standard deviations (86.6% confidence)
}

# How a cost source entered the window: no cost in the comparison period at all,
# or none in at least half of its buckets
NEW_ENTITY = "new_entity"
ACTIVATION = "activation"

# A dense cost series per (dimension, entity name), one value per bucket
DetectionSeries = Dict[Tuple[str, str], List[float]]

DIMENSION_ENTITY_TYPES = {
    "providers": "provider",
    "agents": "agent",
    "api_keys": "api_key",
}

# How an answer names one entity of each type
ENTITY_TYPE_NOUNS = {
    "provider": "provider",
    "agent": "agent",
    "api_key": "API key",
}

# Default entity type thresholds (all zero for maximum sensitivity)
# Only includes supported dimensions with time-series endpoints
DEFAULT_ENTITY_THRESHOLDS = {
    "new_agent_threshold": 0.0,
    "new_api_key_threshold": 0.0,
    "new_provider_threshold": 0.0,
    # Note: models and customers excluded - no time-series endpoints available
}


@dataclass
class AnomalyResult:
    """Statistical anomaly detection result."""

    value: float
    z_score: float
    severity_score: float
    is_anomaly: bool
    normal_range_min: float
    normal_range_max: float
    percentage_above_normal: float


class StatisticalAnomalyDetector:
    """Core statistical analysis engine for temporal anomaly detection.

    Implements deterministic z-score based anomaly detection as specified
    in Enhanced Spike Analysis v2.0 PRD. Uses exact formulas:
    - z_score = abs((value - mean) / std_dev)
    - severity_score = z_score * sqrt(dollar_impact)
    """

    def __init__(self) -> None:
        """Initialize the statistical anomaly detector."""
        self.logger = logger

    def detect_entity_temporal_anomalies(
        self,
        entity_name: str,
        time_values: List[float],
        sensitivity: str = "normal",
        min_impact_threshold: float = 10.0,
    ) -> List[Tuple[int, AnomalyResult]]:
        """Detect temporal anomalies for a specific entity across time periods.

        Args:
            entity_name: Name of the entity being analyzed
            time_values: List of cost values across time periods
            sensitivity: Sensitivity level (conservative, normal, aggressive)
            min_impact_threshold: Minimum dollar impact to consider

        Returns:
            List of (time_index, AnomalyResult) tuples for detected anomalies
        """
        if len(time_values) < 3:
            self.logger.debug(f"Insufficient data points for {entity_name}: {len(time_values)}")
            return []

        # Calculate statistical baseline
        mean_value = statistics.mean(time_values)
        std_value = statistics.stdev(time_values) if len(time_values) > 1 else 0

        if std_value == 0:
            self.logger.debug(f"No variation in data for {entity_name}")
            return []

        threshold = SENSITIVITY_THRESHOLDS.get(sensitivity, 2.0)
        anomalies = []

        for i, value in enumerate(time_values):
            if value < min_impact_threshold:
                continue

            anomaly_result = self._analyze_value(value, mean_value, std_value, threshold)

            if anomaly_result.is_anomaly:
                anomalies.append((i, anomaly_result))

        self.logger.info(f"Detected {len(anomalies)} anomalies for {entity_name}")
        return anomalies

    def detect_time_period_anomalies(
        self,
        time_group: str,
        entity_values: List[float],
        sensitivity: str = "normal",
        min_impact_threshold: float = 10.0,
    ) -> List[Tuple[int, AnomalyResult]]:
        """Detect anomalies within a specific time period across entities.

        Args:
            time_group: Time period identifier
            entity_values: List of cost values for different entities
            sensitivity: Sensitivity level (conservative, normal, aggressive)
            min_impact_threshold: Minimum dollar impact to consider

        Returns:
            List of (entity_index, AnomalyResult) tuples for detected anomalies
        """
        if len(entity_values) < 3:
            self.logger.debug(f"Insufficient entities for {time_group}: {len(entity_values)}")
            return []

        # Calculate statistical baseline across entities
        mean_value = statistics.mean(entity_values)
        std_value = statistics.stdev(entity_values) if len(entity_values) > 1 else 0

        if std_value == 0:
            self.logger.debug(f"No variation across entities for {time_group}")
            return []

        threshold = SENSITIVITY_THRESHOLDS.get(sensitivity, 2.0)
        anomalies = []

        for i, value in enumerate(entity_values):
            if value < min_impact_threshold:
                continue

            anomaly_result = self._analyze_value(value, mean_value, std_value, threshold)

            if anomaly_result.is_anomaly:
                anomalies.append((i, anomaly_result))

        self.logger.info(f"Detected {len(anomalies)} entity anomalies in {time_group}")
        return anomalies

    def calculate_z_score(self, value: float, mean: float, std_dev: float) -> float:
        """Calculate z-score using exact formula from PRD.

        Args:
            value: Observed value
            mean: Mean of the dataset
            std_dev: Standard deviation of the dataset

        Returns:
            Z-score as absolute value
        """
        if std_dev == 0:
            return 0.0
        return abs((value - mean) / std_dev)

    def calculate_severity_score(self, z_score: float, dollar_impact: float) -> float:
        """Calculate severity score using exact formula from PRD.

        Args:
            z_score: Statistical z-score
            dollar_impact: Dollar amount of the impact

        Returns:
            Severity score (z_score * sqrt(dollar_impact))
        """
        return z_score * math.sqrt(dollar_impact)

    def _analyze_value(
        self, value: float, mean_value: float, std_value: float, threshold: float
    ) -> AnomalyResult:
        """Analyze a single value for anomaly detection.

        Args:
            value: Value to analyze
            mean_value: Mean of the dataset
            std_value: Standard deviation of the dataset
            threshold: Z-score threshold for anomaly detection

        Returns:
            AnomalyResult with complete analysis
        """
        z_score = self.calculate_z_score(value, mean_value, std_value)
        severity_score = self.calculate_severity_score(z_score, value)
        is_anomaly = z_score > threshold

        # Calculate normal range (mean ± 1 std_dev for reference)
        # Ensure minimum is never negative for cost data
        normal_range_min = max(0.0, mean_value - std_value)
        normal_range_max = mean_value + std_value

        # Calculate percentage above normal
        if mean_value > 0:
            percentage_above_normal = ((value - mean_value) / mean_value) * 100
        else:
            percentage_above_normal = 0.0

        return AnomalyResult(
            value=value,
            z_score=z_score,
            severity_score=severity_score,
            is_anomaly=is_anomaly,
            normal_range_min=normal_range_min,
            normal_range_max=normal_range_max,
            percentage_above_normal=percentage_above_normal,
        )

    def detect_new_cost_sources(
        self,
        window: DetectionSeries,
        window_starts: Sequence[datetime],
        comparison: DetectionSeries,
        comparison_bucket_count: int,
        period: str,
        min_new_entity_threshold: float = 0.0,
    ) -> List[NewEntityIntroduction]:
        """Entities with cost in the window and none (new) or little (activated) in the comparison period.

        Args:
            window: Dense cost series per (dimension, name), aligned to window_starts
            window_starts: Every window bucket's start, oldest first
            comparison: Dense cost series per (dimension, name) over the comparison period
            comparison_bucket_count: How many buckets the comparison period returned
            period: The requested period, which names the bucket type
            min_new_entity_threshold: Minimum window cost to report an entity

        Raises:
            ValueError: When the window returned no bucket
        """
        if not window_starts:
            raise ValueError(
                "the report returned no bucket for the window, so nothing could be compared"
            )
        period_type = "monthly" if period == "TWELVE_MONTHS" else "bucket"
        introduction_period = describe_span(
            bucket_span(window_starts), not starts_at_midnight(window_starts)
        )

        found = []
        for key, recent in window.items():
            dimension, entity_name = key
            baseline = comparison.get(key) or [0.0] * comparison_bucket_count
            introduction_type = self._introduction_type(
                baseline, recent, min_new_entity_threshold
            )
            if introduction_type is None:
                continue
            first_index = next(index for index, cost in enumerate(recent) if cost > 0)
            active = [cost for cost in recent if cost > 0]
            recent_total = sum(recent)
            found.append(
                NewEntityIntroduction(
                    entity_name=entity_name,
                    entity_type=DIMENSION_ENTITY_TYPES.get(dimension, "provider"),
                    introduction_period=introduction_period,
                    first_appearance_index=first_index,
                    first_active_date=window_starts[first_index].strftime("%Y-%m-%d"),
                    periods_active=len(active),
                    period_type=period_type,
                    total_cost_impact=recent_total,
                    average_daily_cost=recent_total / len(active),
                    introduction_type=introduction_type,
                    cost_periods=recent,
                    baseline_buckets_without_cost=sum(1 for cost in baseline if cost == 0),
                    context=(
                        f"Newly active cost source detected with {render_dollars(recent_total)} "
                        "total cost impact"
                    ),
                )
            )

        self.logger.info(f"Detected {len(found)} new/activated entities")
        return found

    @staticmethod
    def reaches_threshold(recent: Sequence[float], min_threshold: float) -> bool:
        """Whether a window series has cost and at least ``min_threshold`` of it."""
        recent_total = sum(recent)
        return recent_total > 0 and recent_total >= min_threshold

    @staticmethod
    def _introduction_type(
        baseline: List[float], recent: List[float], min_threshold: float
    ) -> Optional[str]:
        """'new_entity' when the comparison period has no cost, 'activation' when it is mostly without cost."""
        if not StatisticalAnomalyDetector.reaches_threshold(recent, min_threshold):
            return None
        zero_buckets = sum(1 for cost in baseline if cost == 0)
        if zero_buckets == len(baseline):
            return NEW_ENTITY
        if zero_buckets >= len(baseline) * 0.5:
            return ACTIVATION
        return None


def bucket_span(bucket_starts: Sequence[datetime]) -> Dict[str, Any]:
    """The first and last bucket start of a part of the window, and its bucket count."""
    return {
        "start": bucket_starts[0].isoformat(),
        "end": bucket_starts[-1].isoformat(),
        "buckets": len(bucket_starts),
    }


def starts_at_midnight(bucket_starts: Sequence[datetime]) -> bool:
    """Whether every bucket starts at midnight UTC, so a date alone names each one."""
    return all(start.time() == datetime.min.time() for start in bucket_starts)


def format_bucket_start(iso_start: str, with_time: bool) -> str:
    """A bucket start as the answer shows it: the UTC date, with the time if asked."""
    instant = datetime.fromisoformat(iso_start)
    return instant.strftime("%Y-%m-%d %H:%M UTC" if with_time else "%Y-%m-%d")


def describe_span(span: Dict[str, Any], with_time: bool) -> str:
    """'the N buckets starting A to B', from a span made by bucket_span."""
    start = format_bucket_start(span["start"], with_time)
    if span["buckets"] == 1:
        return f"the 1 bucket starting {start}"
    end = format_bucket_start(span["end"], with_time)
    return f"the {span['buckets']} buckets starting {start} to {end}"
