"""Statistical anomaly detector for temporal analysis.

This module provides deterministic statistical analysis using z-score calculations
for detecting temporal anomalies in cost data. Used by Enhanced Spike Analysis v2.0.
"""

import math
import statistics
from dataclasses import dataclass
from typing import Dict, List, Tuple

from loguru import logger

from ..models import NewEntityIntroduction

# Sensitivity thresholds as specified in PRD
SENSITIVITY_THRESHOLDS = {
    "conservative": 3.0,  # 3 standard deviations (99.7% confidence)
    "normal": 2.0,  # 2 standard deviations (95% confidence)
    "aggressive": 1.5,  # 1.5 standard deviations (86.6% confidence)
}

# Baseline period mapping for new entity detection
BASELINE_PERIOD_MAPPING = {
    "SEVEN_DAYS": {"baseline_days": 2, "recent_days": 5},
    "THIRTY_DAYS": {"baseline_days": 7, "recent_days": 23},
    "TWELVE_MONTHS": {"baseline_days": 30, "recent_days": 335},
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
        entity_time_matrix: Dict[str, List[float]],
        period: str,
        entity_dimension_map: Dict[str, str],
        min_new_entity_threshold: float = 0.0,
    ) -> List[NewEntityIntroduction]:
        """Detect new cost source introductions using dynamic baseline approach.

        Args:
            entity_time_matrix: Dict mapping entity names to time series cost data
            period: Analysis period (SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS)
            entity_dimension_map: Dict mapping entity names to their dimensions/types
            min_new_entity_threshold: Minimum cost threshold to flag new entities

        Returns:
            List of NewEntityIntroduction objects for detected new entities

        Raises:
            ValueError: If period is not supported for new entity detection
        """
        # Validate period support
        if period not in BASELINE_PERIOD_MAPPING:
            supported_periods = list(BASELINE_PERIOD_MAPPING.keys())
            raise ValueError(
                f"Period '{period}' not supported for new entity detection. "
                f"Supported periods: {supported_periods}"
            )

        self.logger.info(f"Detecting new entities for period: {period}")

        # Get baseline configuration for this period
        baseline_config = BASELINE_PERIOD_MAPPING[period]
        baseline_days = baseline_config["baseline_days"]
        recent_days = baseline_config["recent_days"]

        self.logger.debug(f"Using baseline: {baseline_days} days, recent: {recent_days} days")

        # Split entity time matrix into baseline and recent periods
        baseline_entities, recent_entities = self._split_entity_periods(
            entity_time_matrix, baseline_days, recent_days
        )

        # Detect new entity introductions
        new_entities = self._identify_new_entities(
            baseline_entities, recent_entities, min_new_entity_threshold, period, entity_dimension_map
        )

        # Detect zero-to-cost activations
        activated_entities = self._identify_activated_entities(
            baseline_entities, recent_entities, min_new_entity_threshold, period, entity_dimension_map
        )

        # Combine results
        all_new_entities = new_entities + activated_entities

        self.logger.info(f"Detected {len(all_new_entities)} new/activated entities")
        return all_new_entities

    def _split_entity_periods(
        self,
        entity_time_matrix: Dict[str, List[float]],
        baseline_days: int,
        recent_days: int
    ) -> Tuple[Dict[str, List[float]], Dict[str, List[float]]]:
        """Split entity time matrix into baseline and recent periods.

        Args:
            entity_time_matrix: Full entity time series data
            baseline_days: Number of days for baseline period
            recent_days: Number of days for recent period

        Returns:
            Tuple of (baseline_entities, recent_entities) dictionaries
        """
        baseline_entities = {}
        recent_entities = {}

        for entity_name, time_series in entity_time_matrix.items():
            if len(time_series) < baseline_days + recent_days:
                self.logger.warning(
                    f"Insufficient data for {entity_name}: {len(time_series)} points, "
                    f"need {baseline_days + recent_days}"
                )
                continue

            # Split time series: baseline period comes first, then recent period
            baseline_period = time_series[:baseline_days]
            recent_period = time_series[baseline_days:baseline_days + recent_days]

            baseline_entities[entity_name] = baseline_period
            recent_entities[entity_name] = recent_period

        return baseline_entities, recent_entities

    def _identify_new_entities(
        self,
        baseline_entities: Dict[str, List[float]],
        recent_entities: Dict[str, List[float]],
        min_threshold: float,
        period: str,
        entity_dimension_map: Dict[str, str],
    ) -> List[NewEntityIntroduction]:
        """Identify entities present in recent period but absent from baseline.

        Args:
            baseline_entities: Entities from baseline period
            recent_entities: Entities from recent period
            min_threshold: Minimum cost threshold
            period: Analysis period for context
            entity_dimension_map: Mapping of entity names to their dimensions

        Returns:
            List of new entity introductions
        """
        new_entities = []
        baseline_entity_names = set(baseline_entities.keys())

        for entity_name, recent_costs in recent_entities.items():
            # Skip if entity existed in baseline period
            if entity_name in baseline_entity_names:
                continue

            # Calculate cost impact
            total_cost = sum(recent_costs)
            if total_cost < min_threshold:
                continue

            # Find first non-zero appearance
            first_appearance_index = 0
            for i, cost in enumerate(recent_costs):
                if cost > 0:
                    first_appearance_index = i
                    break

            # Calculate periods active and average cost
            non_zero_costs = [c for c in recent_costs if c > 0]
            periods_active = len(non_zero_costs)
            avg_daily_cost = sum(non_zero_costs) / periods_active if periods_active > 0 else 0.0

            # Calculate first active date and period type
            first_active_date, period_type = self._calculate_first_active_date(period, first_appearance_index)

            # Create new entity introduction
            new_entity = NewEntityIntroduction(
                entity_name=entity_name,
                entity_type=self._get_entity_type_from_dimension(entity_name, entity_dimension_map),
                introduction_period=self._format_period_description(period),
                first_appearance_index=first_appearance_index,
                first_active_date=first_active_date,
                periods_active=periods_active,
                period_type=period_type,
                total_cost_impact=total_cost,
                average_daily_cost=avg_daily_cost,
                introduction_type="new_entity",
                cost_periods=recent_costs,
                context=f"Newly active cost source detected with ${total_cost:.2f} total cost impact"
            )

            new_entities.append(new_entity)
            self.logger.debug(f"Detected new entity: {entity_name} (${total_cost:.2f})")

        return new_entities

    def _identify_activated_entities(
        self,
        baseline_entities: Dict[str, List[float]],
        recent_entities: Dict[str, List[float]],
        min_threshold: float,
        period: str,
        entity_dimension_map: Dict[str, str],
    ) -> List[NewEntityIntroduction]:
        """Identify entities that transition from dormant (mostly $0) to active.

        Args:
            baseline_entities: Entities from baseline period
            recent_entities: Entities from recent period
            min_threshold: Minimum cost threshold
            period: Analysis period for context
            entity_dimension_map: Mapping of entity names to their dimensions

        Returns:
            List of activated entity introductions
        """
        activated_entities = []

        for entity_name in baseline_entities.keys():
            if entity_name not in recent_entities:
                continue

            baseline_costs = baseline_entities[entity_name]
            recent_costs = recent_entities[entity_name]

            # Check if entity was dormant in baseline (≥50% zero-cost periods)
            zero_count = sum(1 for cost in baseline_costs if cost == 0.0)
            dormant_threshold = len(baseline_costs) * 0.5

            if zero_count < dormant_threshold:
                continue  # Not dormant in baseline

            # Check if entity became active in recent period
            recent_total_cost = sum(recent_costs)
            if recent_total_cost < min_threshold:
                continue  # Still not active enough

            # Find first significant activation
            first_activation_index = 0
            for i, cost in enumerate(recent_costs):
                if cost > 0:
                    first_activation_index = i
                    break

            # Calculate periods active and average cost
            non_zero_costs = [c for c in recent_costs if c > 0]
            periods_active = len(non_zero_costs)
            avg_daily_cost = sum(non_zero_costs) / periods_active if periods_active > 0 else 0.0

            # Calculate first active date and period type
            first_active_date, period_type = self._calculate_first_active_date(period, first_activation_index)

            # Create activated entity introduction
            activated_entity = NewEntityIntroduction(
                entity_name=entity_name,
                entity_type=self._get_entity_type_from_dimension(entity_name, entity_dimension_map),
                introduction_period=self._format_period_description(period),
                first_appearance_index=first_activation_index,
                first_active_date=first_active_date,
                periods_active=periods_active,
                period_type=period_type,
                total_cost_impact=recent_total_cost,
                average_daily_cost=avg_daily_cost,
                introduction_type="activation",
                cost_periods=recent_costs,
                context=f"Newly active cost source detected with ${recent_total_cost:.2f} total cost impact"
            )

            activated_entities.append(activated_entity)
            self.logger.debug(f"Detected activated entity: {entity_name} (${recent_total_cost:.2f})")

        return activated_entities

    def _get_entity_type_from_dimension(self, entity_name: str, entity_dimension_map: Dict[str, str]) -> str:
        """Determine entity type from dimension mapping (definitive, not pattern-based).

        Args:
            entity_name: Name of the entity
            entity_dimension_map: Mapping of entity names to their dimensions

        Returns:
            Entity type based on dimension: 'agent', 'api_key', or 'provider'
        """
        # Get dimension from the mapping
        dimension = entity_dimension_map.get(entity_name, "providers")  # Default to providers

        # Map dimension to entity type (only supported dimensions for new entity detection)
        dimension_to_type = {
            "providers": "provider",
            "agents": "agent",
            "api_keys": "api_key",
            # Note: models and customers excluded - they don't have time-series endpoints
        }

        entity_type = dimension_to_type.get(dimension, "provider")
        self.logger.debug(f"Entity '{entity_name}' mapped from dimension '{dimension}' to type '{entity_type}'")
        return entity_type

    def _format_period_description(self, period: str) -> str:
        """Format period into human-readable description.

        Args:
            period: Period string (e.g., 'THIRTY_DAYS')

        Returns:
            Human-readable period description
        """
        period_descriptions = {
            "SEVEN_DAYS": "last 7 days",
            "THIRTY_DAYS": "last 30 days",
            "TWELVE_MONTHS": "last 12 months",
        }

        return period_descriptions.get(period, period.lower().replace('_', ' '))

    def _calculate_first_active_date(self, period: str, first_appearance_index: int) -> Tuple[str, str]:
        """Calculate the first active date and period type based on analysis period.

        Args:
            period: Analysis period (SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS)
            first_appearance_index: Index of first appearance in recent period

        Returns:
            Tuple of (first_active_date, period_type)
        """
        from datetime import datetime, timedelta

        # Determine period type and calculate date offset
        if period == "TWELVE_MONTHS":
            period_type = "monthly"
            # For 12-month analysis, each index represents a month
            # Index 0 = most recent month, so we go back by index months
            base_date = datetime.now().replace(day=1)  # First day of current month
            offset_date = base_date - timedelta(days=30 * first_appearance_index)
            first_active_date = offset_date.strftime("%Y-%m-%d")
        else:
            period_type = "daily"
            # For daily analysis (7-day, 30-day), each index represents a day
            # Index 0 = most recent day, so we go back by index days
            base_date = datetime.now()
            offset_date = base_date - timedelta(days=first_appearance_index)
            first_active_date = offset_date.strftime("%Y-%m-%d")

        return first_active_date, period_type
