"""Enhanced Spike Analyzer for temporal anomaly detection.

This module implements Enhanced Spike Analysis v2.0 as specified in the PRD.
Provides deterministic statistical analysis using z-score calculations for
detecting temporal anomalies in cost data across multiple dimensions.
"""

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from .statistical_anomaly_detector import SENSITIVITY_THRESHOLDS, StatisticalAnomalyDetector

# API endpoint mappings as specified in PRD
TEMPORAL_ANALYSIS_ENDPOINTS = {
    "providers": "/profitstream/v2/api/sources/metrics/ai/total-cost-by-provider-over-time",
    "models": "/profitstream/v2/api/sources/metrics/ai/total-cost-by-model",
    "api_keys": "/profitstream/v2/api/sources/metrics/ai/cost-metrics-by-subscriber-credential",
    "agents": "/profitstream/v2/api/sources/metrics/ai/cost-metrics-by-agents-over-time",
    "customers": "/profitstream/v2/api/sources/metrics/ai/cost-metric-by-organization",
    "tokens": "/profitstream/v2/api/sources/metrics/ai/tokens-per-minute-by-provider",
}

# Dimensions that support time-series data for new entity detection
NEW_ENTITY_DETECTION_SUPPORTED_DIMENSIONS = {
    "providers", "agents", "api_keys"
}


@dataclass
class TemporalAnomaly:
    """Temporal anomaly data structure exactly as specified in PRD."""

    entity_name: str  # "OpenAI", "gpt-4", "api-key-123"
    entity_type: str  # "provider", "model", "api_key", "agent"
    time_group: str  # "2024-01-15T14:00:00Z"
    time_group_label: str  # "Saturday 2PM" or "Day 6"
    anomaly_value: float  # 2000.0
    normal_range_min: float  # 100.0
    normal_range_max: float  # 300.0
    z_score: float  # 2.8
    severity_score: float  # 125.6 (z_score * sqrt(dollar_impact))
    anomaly_type: str  # "entity_temporal" or "period_wide"
    context: str  # Human-readable explanation
    percentage_above_normal: float  # 566.7


class EnhancedSpikeAnalyzer:
    """Main orchestration class for temporal anomaly detection.

    Implements the complete Enhanced Spike Analysis v2.0 algorithm as specified
    in the PRD. Provides deterministic statistical analysis using z-score
    calculations for detecting temporal anomalies across multiple dimensions.
    """

    def __init__(self, client) -> None:
        """Initialize the enhanced spike analyzer.

        Args:
            client: Revenium API client for data fetching
        """
        self.client = client
        self.detector = StatisticalAnomalyDetector()
        self.logger = logger

        # Period validation mapping
        self.supported_periods = {
            "HOUR",
            "EIGHT_HOURS",
            "TWENTY_FOUR_HOURS",
            "SEVEN_DAYS",
            "THIRTY_DAYS",
            "TWELVE_MONTHS",
        }

    async def analyze_temporal_anomalies(
        self,
        period: str,
        sensitivity: str = "normal",
        min_impact_threshold: float = 10.0,
        include_dimensions: Optional[List[str]] = None,
        detect_new_entities: bool = False,
        min_new_entity_threshold: float = 0.0,
    ) -> Dict[str, Any]:
        """Complete algorithm for temporal anomaly detection with optional new entity detection.

        Args:
            period: Time period (HOUR, EIGHT_HOURS, etc.)
            sensitivity: Statistical sensitivity (conservative, normal, aggressive)
            min_impact_threshold: Minimum dollar impact to report
            include_dimensions: Dimensions to analyze (default: ["providers"])
            detect_new_entities: Whether to detect new cost source introductions
            min_new_entity_threshold: Minimum cost threshold for new entity detection

        Returns:
            Complete temporal anomaly analysis results with optional new entity data
        """
        # Phase 1: Validate inputs
        if period not in self.supported_periods:
            raise ValueError(f"Unsupported period: {period}")

        if sensitivity not in SENSITIVITY_THRESHOLDS:
            raise ValueError(f"Unsupported sensitivity: {sensitivity}")

        if include_dimensions is None:
            include_dimensions = ["providers"]  # Phase 1: providers only

        self.logger.info(
            f"Analyzing temporal anomalies: period={period}, sensitivity={sensitivity}"
        )

        # Step 1: Collect time-series data from endpoints
        time_series_data = await self._collect_temporal_data(period, include_dimensions)

        # Step 2: Build entity-time matrix
        entity_time_matrix = self._build_entity_time_matrix(time_series_data)

        # Step 3: Detect entity-level temporal anomalies
        entity_anomalies = await self._detect_entity_anomalies(
            entity_time_matrix, sensitivity, min_impact_threshold, period
        )

        # Step 4: Detect new entities if requested
        new_entities = []
        period_conversion_notice = None
        if detect_new_entities:
            try:
                new_entities, period_conversion_notice = await self._detect_new_entities(
                    entity_time_matrix, period, min_new_entity_threshold
                )
            except ValueError as e:
                self.logger.warning(f"New entity detection failed: {e}")
                # Continue with regular anomaly analysis

        # Step 5: Sort by severity score and return formatted results
        entity_anomalies.sort(key=lambda x: x.severity_score, reverse=True)

        return self._format_temporal_results(
            entity_anomalies, period, sensitivity, include_dimensions, new_entities, period_conversion_notice
        )

    async def _collect_temporal_data(
        self, period: str, include_dimensions: List[str]
    ) -> Dict[str, Any]:
        """Collect time-series data from all specified endpoints.

        Args:
            period: Time period for data collection
            include_dimensions: Dimensions to collect data for

        Returns:
            Raw time-series data from API endpoints
        """
        collected_data = {}

        # Get team_id for API calls
        team_id = getattr(self.client, "team_id", None)
        if not team_id:
            import os

            team_id = os.getenv("REVENIUM_TEAM_ID")
            if not team_id:
                raise Exception("Team ID not available from client or environment")

        # Collect data for each specified dimension
        for dimension in include_dimensions:
            if dimension not in TEMPORAL_ANALYSIS_ENDPOINTS:
                self.logger.warning(f"Unknown dimension: {dimension}")
                continue

            endpoint = TEMPORAL_ANALYSIS_ENDPOINTS[dimension]
            params = {"teamId": team_id, "period": period}

            try:
                self.logger.info(f"Collecting {dimension} data from {endpoint}")
                response = await self.client.get(endpoint, params=params)
                collected_data[dimension] = response
                self.logger.info(f"Successfully collected {dimension} data")

                # Debug logging to understand API response structure
                self.logger.debug(f"API response for {dimension}: {type(response)}")
                if isinstance(response, list) and response:
                    self.logger.debug(f"First item in {dimension} response: {response[0]}")
                elif isinstance(response, dict):
                    self.logger.debug(f"Keys in {dimension} response: {list(response.keys())}")
                    if "groups" in response:
                        groups = response.get("groups", [])
                        if groups:
                            self.logger.debug(f"First group in {dimension}: {groups[0]}")

            except Exception as e:
                self.logger.error(f"Failed to collect {dimension} data: {e}")
                collected_data[dimension] = []

        return collected_data

    def _build_entity_time_matrix(self, time_series_data: Dict[str, Any]) -> Dict[str, List[Tuple[str, float]]]:
        """Build entity-time matrix from time-series data.

        Args:
            time_series_data: Raw time-series data from API

        Returns:
            Entity-time matrix where keys are entity names and values are time series of (timestamp, cost) tuples
        """
        entity_time_matrix = {}
        # Track entity to dimension mapping for proper type identification
        self.entity_dimension_map = {}

        for dimension, data in time_series_data.items():
            if isinstance(data, list) and data:
                self._process_time_series_data(data, entity_time_matrix, dimension)
            elif isinstance(data, dict) and "groups" in data:
                self._process_single_period_data(data, entity_time_matrix, dimension)

        self.logger.info(f"Built entity-time matrix with {len(entity_time_matrix)} entities")
        return entity_time_matrix

    def _process_time_series_data(
        self, data: List[Dict], entity_time_matrix: Dict[str, List[Tuple[str, float]]], dimension: str
    ) -> None:
        """Process time-series format data with multiple time periods."""
        for time_entry in data:
            if not isinstance(time_entry, dict) or "groups" not in time_entry:
                continue

            # Extract timestamp from the time entry (use startTimestamp or first metric timestamp)
            timestamp = time_entry.get("startTimestamp")
            if not timestamp:
                # Fallback: try to get timestamp from first metric in first group
                groups = time_entry.get("groups", [])
                if groups and isinstance(groups[0], dict):
                    metrics = groups[0].get("metrics", [])
                    if metrics and isinstance(metrics[0], dict):
                        timestamp = metrics[0].get("timestamp")

            # Debug logging for timestamp extraction
            self.logger.debug(f"Extracted timestamp for {dimension}: {timestamp} (type: {type(timestamp)})")

            # If still no timestamp, skip this entry
            if not timestamp:
                self.logger.warning(f"No timestamp found in time_entry for dimension {dimension}")
                self.logger.debug(f"Time entry structure: {time_entry}")
                continue

            groups = time_entry.get("groups", [])
            for group in groups:
                if not isinstance(group, dict):
                    continue

                entity_name = group.get("groupName", "Unknown")
                total_cost = self._calculate_group_cost(group.get("metrics", []))

                # Track entity to dimension mapping
                self.entity_dimension_map[entity_name] = dimension

                if entity_name not in entity_time_matrix:
                    entity_time_matrix[entity_name] = []

                # Store both timestamp and cost
                entity_time_matrix[entity_name].append((timestamp, total_cost))

    def _process_single_period_data(
        self, data: Dict, entity_time_matrix: Dict[str, List[Tuple[str, float]]], dimension: str
    ) -> None:
        """Process single time period format data."""
        # Extract timestamp from the data (use startTimestamp or first metric timestamp)
        timestamp = data.get("startTimestamp")
        if not timestamp:
            # Fallback: try to get timestamp from first metric in first group
            groups = data.get("groups", [])
            if groups and isinstance(groups[0], dict):
                metrics = groups[0].get("metrics", [])
                if metrics and isinstance(metrics[0], dict):
                    timestamp = metrics[0].get("timestamp")

        # If still no timestamp, use current time as fallback
        if not timestamp:
            from datetime import datetime
            timestamp = datetime.utcnow().isoformat() + "Z"
            self.logger.warning(f"No timestamp found in single period data for dimension {dimension}, using current time")

        groups = data.get("groups", [])
        for group in groups:
            if not isinstance(group, dict):
                continue

            entity_name = group.get("groupName", "Unknown")
            total_cost = self._calculate_group_cost(group.get("metrics", []))

            # Track entity to dimension mapping
            self.entity_dimension_map[entity_name] = dimension

            # For single period, create single-item time series with timestamp
            entity_time_matrix[entity_name] = [(timestamp, total_cost)]

    def _calculate_group_cost(self, metrics: List[Dict]) -> float:
        """Calculate total cost for a group from metrics."""
        total_cost = 0.0
        for metric in metrics:
            if isinstance(metric, dict):
                cost = float(metric.get("metricResult", 0))
                total_cost += cost
        return total_cost

    async def _detect_entity_anomalies(
        self,
        entity_time_matrix: Dict[str, List[Tuple[str, float]]],
        sensitivity: str,
        min_impact_threshold: float,
        period: str,
    ) -> List[TemporalAnomaly]:
        """Detect entity-level temporal anomalies.

        Args:
            entity_time_matrix: Entity-time matrix data with (timestamp, cost) tuples
            sensitivity: Statistical sensitivity level
            min_impact_threshold: Minimum dollar impact threshold

        Returns:
            List of detected temporal anomalies
        """
        entity_anomalies = []

        for entity_name, time_data in entity_time_matrix.items():
            if len(time_data) < 3:
                self.logger.debug(f"Insufficient data for {entity_name}: {len(time_data)}")
                continue

            # Extract just the cost values for statistical analysis
            time_values = [cost for timestamp, cost in time_data]

            # Use statistical detector to find anomalies
            anomaly_results = self.detector.detect_entity_temporal_anomalies(
                entity_name, time_values, sensitivity, min_impact_threshold
            )

            # Convert to TemporalAnomaly objects using real timestamps
            for time_index, anomaly_result in anomaly_results:
                # Get the real timestamp for this time index
                raw_timestamp, _ = time_data[time_index]

                # Convert timestamp to ISO format for time_group field
                iso_timestamp = self._convert_timestamp_to_iso(raw_timestamp)

                temporal_anomaly = TemporalAnomaly(
                    entity_name=entity_name,
                    entity_type=self._get_entity_type(entity_name),
                    time_group=iso_timestamp,
                    time_group_label=self._get_time_group_label_from_timestamp(raw_timestamp),
                    anomaly_value=anomaly_result.value,
                    normal_range_min=anomaly_result.normal_range_min,
                    normal_range_max=anomaly_result.normal_range_max,
                    z_score=anomaly_result.z_score,
                    severity_score=anomaly_result.severity_score,
                    anomaly_type="entity_temporal",
                    context=self._generate_context_from_timestamp(entity_name, raw_timestamp, anomaly_result),
                    percentage_above_normal=anomaly_result.percentage_above_normal,
                )
                entity_anomalies.append(temporal_anomaly)

        self.logger.info(f"Detected {len(entity_anomalies)} entity temporal anomalies")
        return entity_anomalies

    def _format_temporal_results(
        self,
        anomalies: List[TemporalAnomaly],
        period: str,
        sensitivity: str,
        include_dimensions: List[str],
        new_entities: Optional[List] = None,
        period_conversion_notice: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Format temporal anomaly results with optional new entity data.

        Args:
            anomalies: List of detected anomalies
            period: Analysis period
            sensitivity: Sensitivity level used
            include_dimensions: Dimensions that were analyzed
            new_entities: Optional list of new entity introductions

        Returns:
            Formatted results with anomalies and optional new entity data
        """
        # Calculate entities analyzed by dimension
        entities_analyzed = {}
        for dimension in include_dimensions:
            # Count entities from this dimension based on entity_dimension_map
            dimension_entities = {
                name for name, dim in self.entity_dimension_map.items() if dim == dimension
            }
            entities_analyzed[dimension] = len(dimension_entities)

        # Convert anomalies to dict format
        temporal_anomalies = []
        for anomaly in anomalies:
            temporal_anomalies.append(
                {
                    "entity_name": anomaly.entity_name,
                    "entity_type": anomaly.entity_type,
                    "time_group": anomaly.time_group,
                    "time_group_label": anomaly.time_group_label,
                    "anomaly_value": round(anomaly.anomaly_value, 2),
                    "normal_range_min": round(anomaly.normal_range_min, 2),
                    "normal_range_max": round(anomaly.normal_range_max, 2),
                    "z_score": round(anomaly.z_score, 1),
                    "severity_score": round(anomaly.severity_score, 1),
                    "anomaly_type": anomaly.anomaly_type,
                    "context": anomaly.context,
                    "percentage_above_normal": round(anomaly.percentage_above_normal, 1),
                }
            )

        # Phase 3: Generate time period summary and entity summary
        time_period_summary = self._generate_time_period_summary(anomalies, period)
        entity_summary = self._generate_entity_summary(anomalies)

        # Generate intelligent recommendations based on detected patterns
        recommendations = self._generate_recommendations(anomalies, include_dimensions)

        # Complete result structure matching PRD Phase 3
        result = {
            "period_analyzed": period,
            "sensitivity_used": sensitivity,
            "time_groups_analyzed": self._get_time_groups_count(period),
            "entities_analyzed": entities_analyzed,
            "total_anomalies_detected": len(temporal_anomalies),
            "temporal_anomalies": temporal_anomalies,
            "time_period_summary": time_period_summary,
            "entity_summary": entity_summary,
            "recommendations": recommendations,
        }

        # Add new entity detection results if available
        if new_entities:
            new_entity_data = self._format_new_entity_results(new_entities)
            result.update(new_entity_data)

        # Add period conversion notice if period was adjusted
        if period_conversion_notice:
            result["period_conversion_notice"] = period_conversion_notice

        return result

    def _format_new_entity_results(self, new_entities: List) -> Dict[str, Any]:
        """Format new entity detection results for output.

        Args:
            new_entities: List of NewEntityIntroduction objects

        Returns:
            Dictionary with formatted new entity data
        """
        if not new_entities:
            return {}

        # Group entities by type
        entities_by_type = {}
        total_new_entities = len(new_entities)
        total_cost_impact = sum(entity.total_cost_impact for entity in new_entities)

        for entity in new_entities:
            entity_type = entity.entity_type
            if entity_type not in entities_by_type:
                entities_by_type[entity_type] = {
                    "entities": [],
                    "count": 0,
                    "total_cost_impact": 0.0,
                    "summary": ""
                }

            entities_by_type[entity_type]["entities"].append({
                "entity_name": entity.entity_name,
                "introduction_period": entity.introduction_period,
                "first_active_date": entity.first_active_date,
                "periods_active": entity.periods_active,
                "period_type": entity.period_type,
                "total_cost_impact": entity.total_cost_impact,
                "average_daily_cost": entity.average_daily_cost,
                "introduction_type": entity.introduction_type,
                "context": entity.context
            })
            entities_by_type[entity_type]["count"] += 1
            entities_by_type[entity_type]["total_cost_impact"] += entity.total_cost_impact

        # Generate summaries for each type
        for entity_type, data in entities_by_type.items():
            count = data["count"]
            cost = data["total_cost_impact"]
            data["summary"] = f"{count} new {entity_type}{'s' if count > 1 else ''} detected with ${cost:.2f} total cost impact"

        return {
            "new_entities_detected": total_new_entities,
            "new_entities_total_cost_impact": total_cost_impact,
            "new_entities_by_type": entities_by_type,
            "new_entity_summary": f"Detected {total_new_entities} new cost source{'s' if total_new_entities > 1 else ''} with ${total_cost_impact:.2f} total impact"
        }

    def _generate_recommendations(
        self, anomalies: List[TemporalAnomaly], include_dimensions: List[str]
    ) -> List[str]:
        """Generate intelligent recommendations based on detected anomaly patterns.

        Args:
            anomalies: List of detected anomalies
            include_dimensions: Dimensions that were analyzed

        Returns:
            List of actionable recommendations
        """
        recommendations = []

        # Check for ANONYMOUS API key anomalies
        if "api_keys" in include_dimensions:
            anonymous_anomalies = [
                a
                for a in anomalies
                if a.entity_type == "api_key" and a.entity_name.upper() == "ANONYMOUS"
            ]

            if anonymous_anomalies:
                # ANONYMOUS API key found in anomalies - critical attribution issue
                recommendations.append(
                    "Add subscriber credential tagging to usage metadata when submitting transactions to enable attribution of API Key spending to specific users or projects."
                )

        # Future: Add more pattern-based recommendations here
        # - Weekend spike patterns
        # - Multi-provider spikes (potential credential compromise)
        # - Model-specific anomalies (cost optimization opportunities)

        return recommendations

    def _generate_time_period_summary(
        self, anomalies: List[TemporalAnomaly], period: str
    ) -> Dict[str, Any]:
        """Generate time period summary with mathematical aggregations only.

        Args:
            anomalies: List of detected anomalies
            period: Analysis period

        Returns:
            Time period summary with absolute determinations only
        """
        # Entity type priority for deduplication (highest priority first)
        ENTITY_TYPE_PRIORITY = {
            "provider": 1,
            "model": 2,
            "agent": 3,
            "api_key": 4,
            "customer": 5
        }

        time_period_summary = {}

        # Group anomalies by time period
        period_groups = {}
        for anomaly in anomalies:
            time_label = anomaly.time_group_label
            if time_label not in period_groups:
                period_groups[time_label] = []
            period_groups[time_label].append(anomaly)

        # Calculate deduplicated mathematical aggregations for each time period
        for time_label, period_anomalies in period_groups.items():
            # Group by entity type to identify potential duplicates
            entity_type_groups = {}
            for anomaly in period_anomalies:
                entity_type = anomaly.entity_type
                if entity_type not in entity_type_groups:
                    entity_type_groups[entity_type] = []
                entity_type_groups[entity_type].append(anomaly)

            # Use only the highest priority entity type for cost calculation to avoid double-counting
            # This prevents the same underlying cost from being counted multiple times across dimensions
            primary_entity_type = min(entity_type_groups.keys(),
                                    key=lambda et: ENTITY_TYPE_PRIORITY.get(et, 999))
            primary_anomalies = entity_type_groups[primary_entity_type]

            # Calculate total anomalous excess cost (not full values) to get actual anomalous impact
            total_anomalous_cost = 0.0
            normal_cost_for_period = 0.0

            for anomaly in primary_anomalies:
                # Calculate normal baseline (midpoint of normal range)
                normal_baseline = (anomaly.normal_range_min + anomaly.normal_range_max) / 2

                # Calculate anomalous excess above normal baseline
                # This represents the actual anomalous cost impact, not the full cost value
                anomalous_excess = max(0, anomaly.anomaly_value - normal_baseline)

                total_anomalous_cost += anomalous_excess
                normal_cost_for_period += normal_baseline

            # Calculate cost multiplier based on primary entity type only
            cost_multiplier = (
                (total_anomalous_cost / normal_cost_for_period) if normal_cost_for_period > 0 else 0
            )

            # Generate factual explanation using all anomalies for context but deduplicated costs
            total_anomalies = len(period_anomalies)  # Count all anomalies for explanation
            primary_anomaly_count = len(primary_anomalies)  # Count used for cost calculation

            if total_anomalies == 1:
                entity_desc = f"{period_anomalies[0].entity_name} anomaly"
            elif len(entity_type_groups) > 1:
                # Multiple entity types detected - provide clear context about cost calculation
                entity_desc = f"{total_anomalies} entity anomalies across {len(entity_type_groups)} types (costs aggregated by {primary_entity_type})"
            else:
                entity_desc = f"{total_anomalies} entity anomalies"

            time_period_summary[time_label] = {
                "total_anomalies": total_anomalies,
                "total_anomalous_cost": round(total_anomalous_cost, 2),
                "normal_cost_for_period": round(normal_cost_for_period, 2),
                "cost_multiplier": round(cost_multiplier, 1),
                "anomaly_explanation": f"{time_label} had {entity_desc} with {cost_multiplier:.1f}x normal cost levels",
                "primary_entity_type_used": primary_entity_type,  # Add transparency about which entity type was used
                "entity_types_detected": list(entity_type_groups.keys()),  # Show all detected types
            }

        return time_period_summary

    def _generate_entity_summary(self, anomalies: List[TemporalAnomaly]) -> Dict[str, Any]:
        """Generate entity summary with absolute pattern detection.

        Args:
            anomalies: List of detected anomalies

        Returns:
            Entity summary with mathematical determinations only
        """
        entity_summary = {}

        # Group anomalies by entity
        entity_groups = {}
        for anomaly in anomalies:
            entity_name = anomaly.entity_name
            if entity_name not in entity_groups:
                entity_groups[entity_name] = []
            entity_groups[entity_name].append(anomaly)

        # Calculate mathematical summaries for each entity
        for entity_name, entity_anomalies in entity_groups.items():
            anomalous_time_periods = [a.time_group_label for a in entity_anomalies]

            # Calculate total anomalous excess cost (not full values) for consistency with time period summary
            total_anomalous_cost = 0.0
            normal_values = []

            for anomaly in entity_anomalies:
                # Calculate normal baseline (midpoint of normal range)
                normal_baseline = (anomaly.normal_range_min + anomaly.normal_range_max) / 2
                normal_values.append(normal_baseline)

                # Calculate anomalous excess above normal baseline
                # This represents the actual anomalous cost impact, not the full cost value
                anomalous_excess = max(0, anomaly.anomaly_value - normal_baseline)
                total_anomalous_cost += anomalous_excess

            normal_daily_average = statistics.mean(normal_values) if normal_values else 0

            # Detect absolute patterns (mathematical determination only)
            anomaly_pattern = self._detect_absolute_pattern(anomalous_time_periods)

            entity_summary[entity_name] = {
                "anomalous_time_periods": anomalous_time_periods,
                "total_anomalous_cost": round(total_anomalous_cost, 2),
                "normal_daily_average": round(normal_daily_average, 2),
                "anomaly_pattern": anomaly_pattern,
            }

        return entity_summary

    def _detect_absolute_pattern(self, time_periods: List[str]) -> str:
        """Detect absolute patterns in time periods using mathematical determination.

        Args:
            time_periods: List of time period labels where anomalies occurred

        Returns:
            Absolute pattern description (entity-specific, no inference)
        """
        if len(time_periods) < 2:
            return "Single period anomaly (this entity only)"

        # Check for weekend spike pattern (absolute determination)
        weekend_days = {"Saturday", "Sunday"}
        weekend_anomalies = [tp for tp in time_periods if any(day in tp for day in weekend_days)]

        # Absolute weekend spike: ALL anomalies on weekends AND ≥2 anomalies
        if len(weekend_anomalies) == len(time_periods) and len(time_periods) >= 2:
            return f"Weekend spike pattern for this entity ({len(time_periods)} weekend periods)"

        # Check for consecutive day pattern
        if len(time_periods) >= 2:
            # Convert day names to indices for mathematical comparison
            day_mapping = {
                "Sunday": 0,
                "Monday": 1,
                "Tuesday": 2,
                "Wednesday": 3,
                "Thursday": 4,
                "Friday": 5,
                "Saturday": 6,
            }

            day_indices = []
            for tp in time_periods:
                for day, index in day_mapping.items():
                    if day in tp:
                        day_indices.append(index)
                        break

            if len(day_indices) >= 2:
                day_indices.sort()
                # Check if consecutive (mathematical determination)
                is_consecutive = all(
                    day_indices[i] == day_indices[i - 1] + 1 for i in range(1, len(day_indices))
                )
                if is_consecutive:
                    return f"Consecutive day pattern for this entity ({len(time_periods)} consecutive periods)"

        # Default: Multiple anomaly pattern
        return f"Multiple period anomalies for this entity ({len(time_periods)} periods)"

    def _get_entity_type(self, entity_name: str) -> str:
        """Determine entity type from entity name based on dimension mapping."""
        # Use dimension mapping to determine entity type
        dimension = self.entity_dimension_map.get(entity_name, "providers")

        # Map dimension to entity type
        dimension_to_type = {
            "providers": "provider",
            "models": "model",
            "agents": "agent",
            "api_keys": "api_key",
            "customers": "customer",
        }

        return dimension_to_type.get(dimension, "provider")

    def _get_time_group_timestamp(self, time_index: int) -> str:
        """Generate timestamp for time group (DEPRECATED - use real timestamps instead)."""
        # This method is deprecated and should not be used for new anomaly detection
        # It generates fake timestamps which cause data accuracy issues
        self.logger.warning("Using deprecated _get_time_group_timestamp - should use real timestamps from API")
        base_time = datetime.utcnow()
        delta = timedelta(days=time_index)
        return (base_time - delta).isoformat() + "Z"

    def _convert_timestamp_to_iso(self, timestamp) -> str:
        """Convert timestamp to ISO format string."""
        try:
            if isinstance(timestamp, (int, float)):
                # Unix timestamp in milliseconds
                dt = datetime.fromtimestamp(timestamp / 1000.0)
                return dt.isoformat() + "Z"
            elif isinstance(timestamp, str):
                # Already a string, return as-is (assume it's already ISO format)
                return timestamp
            else:
                self.logger.warning(f"Unknown timestamp format for conversion: {timestamp} (type: {type(timestamp)})")
                return str(timestamp)
        except Exception as e:
            self.logger.warning(f"Failed to convert timestamp {timestamp} to ISO: {e}")
            return str(timestamp)

    def _get_time_group_label_from_timestamp(self, timestamp) -> str:
        """Generate human-readable label from real timestamp."""
        try:
            # Handle different timestamp formats
            if isinstance(timestamp, (int, float)):
                # Unix timestamp in milliseconds
                dt = datetime.fromtimestamp(timestamp / 1000.0)
            elif isinstance(timestamp, str):
                # ISO string format
                if timestamp.endswith('Z'):
                    dt = datetime.fromisoformat(timestamp[:-1])
                else:
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            else:
                self.logger.warning(f"Unknown timestamp format: {timestamp} (type: {type(timestamp)})")
                return "Unknown"

            # Get day name
            day_name = dt.strftime('%A')
            return day_name

        except Exception as e:
            self.logger.warning(f"Failed to parse timestamp {timestamp}: {e}")
            return "Unknown"

    def _generate_context_from_timestamp(self, entity_name: str, timestamp, anomaly_result) -> str:
        """Generate human-readable context for anomaly using real timestamp."""
        time_label = self._get_time_group_label_from_timestamp(timestamp)

        # Choose appropriate preposition based on time label
        if any(day in time_label for day in ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]):
            preposition = "on "
        else:
            preposition = "during "

        return (
            f"{entity_name} costs {preposition}{time_label} (${anomaly_result.value:.2f}) "
            f"were {anomaly_result.z_score:.1f} standard deviations above "
            f"the average value in the evaluated period"
        )

    def _get_time_group_label(self, time_index: int, period: str) -> str:
        """Generate human-readable label for time group based on period."""
        if period == "HOUR":
            # For hourly analysis, show specific time ranges
            start_hour = time_index
            end_hour = (time_index + 1) % 24
            return f"hour {start_hour:02d}:00-{end_hour:02d}:00"
        elif period == "EIGHT_HOURS":
            # For 8-hour analysis, show time ranges
            start_hour = time_index * 8
            end_hour = (start_hour + 8) % 24
            return f"period {start_hour:02d}:00-{end_hour:02d}:00"
        elif period == "TWENTY_FOUR_HOURS":
            # For daily analysis, show relative days
            if time_index == 0:
                return "today"
            elif time_index == 1:
                return "yesterday"
            else:
                return f"{time_index} days ago"
        elif period == "SEVEN_DAYS":
            # For weekly analysis, show day names
            days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
            return days[time_index % 7]
        elif period == "THIRTY_DAYS":
            # For monthly analysis, show relative days or weeks
            if time_index < 7:
                days = [
                    "Sunday",
                    "Monday",
                    "Tuesday",
                    "Wednesday",
                    "Thursday",
                    "Friday",
                    "Saturday",
                ]
                return f"{days[time_index % 7]} (week 1)"
            elif time_index < 14:
                days = [
                    "Sunday",
                    "Monday",
                    "Tuesday",
                    "Wednesday",
                    "Thursday",
                    "Friday",
                    "Saturday",
                ]
                return f"{days[time_index % 7]} (week 2)"
            else:
                return f"day {time_index + 1}"
        elif period == "TWELVE_MONTHS":
            # For yearly analysis, show month names
            months = [
                "January",
                "February",
                "March",
                "April",
                "May",
                "June",
                "July",
                "August",
                "September",
                "October",
                "November",
                "December",
            ]
            return months[time_index % 12]
        else:
            return f"period {time_index + 1}"

    def _generate_context(
        self, entity_name: str, time_index: int, anomaly_result, period: str
    ) -> str:
        """Generate human-readable context for anomaly."""
        time_label = self._get_time_group_label(time_index, period)

        # Choose appropriate preposition based on time label
        if time_label in ["today", "yesterday"]:
            # No preposition sounds more natural: "costs yesterday" vs "costs on yesterday"
            preposition = ""
        elif (
            "hour" in time_label
            or "period" in time_label
            or "day" in time_label
            and "ago" in time_label
        ):
            preposition = "during "
        elif any(
            day in time_label
            for day in [
                "Sunday",
                "Monday",
                "Tuesday",
                "Wednesday",
                "Thursday",
                "Friday",
                "Saturday",
            ]
        ):
            preposition = "on "
        elif any(
            month in time_label
            for month in ["January", "February", "March", "April", "May", "June"]
        ):
            preposition = "in "
        else:
            preposition = "during "

        return (
            f"{entity_name} costs {preposition}{time_label} (${anomaly_result.value:.2f}) "
            f"were {anomaly_result.z_score:.1f} standard deviations above "
            f"the average value in the evaluated period"
        )

    def _get_time_groups_count(self, period: str) -> int:
        """Get number of time groups for the period."""
        period_mapping = {
            "HOUR": 1,
            "EIGHT_HOURS": 8,
            "TWENTY_FOUR_HOURS": 24,
            "SEVEN_DAYS": 7,
            "THIRTY_DAYS": 30,
            "TWELVE_MONTHS": 12,
        }
        return period_mapping.get(period, 1)

    async def _detect_new_entities(
        self,
        entity_time_matrix: Dict[str, List[Tuple[str, float]]],
        period: str,
        min_new_entity_threshold: float = 0.0,
    ) -> Tuple[List, Optional[str]]:
        """Detect new cost source introductions using dynamic baseline approach.

        Args:
            entity_time_matrix: Dict mapping entity names to time series (timestamp, cost) data
            period: Analysis period (SEVEN_DAYS, THIRTY_DAYS, TWELVE_MONTHS)
            min_new_entity_threshold: Minimum cost threshold to flag new entities

        Returns:
            Tuple of (List of NewEntityIntroduction objects, period_conversion_notice)

        Raises:
            ValueError: If period is not supported for new entity detection
        """
        # Handle unsupported periods by gracefully degrading to SEVEN_DAYS
        original_period = period
        period_conversion_notice = None

        if period in ["HOUR", "EIGHT_HOURS", "TWENTY_FOUR_HOURS"]:
            period = "SEVEN_DAYS"
            period_conversion_notice = (
                f"Requested period '{original_period}' was automatically adjusted to 'SEVEN_DAYS' "
                f"for new entity detection. A minimum 7-day period is required for meaningful baseline analysis."
            )
            self.logger.info(
                f"Period '{original_period}' not supported for new entity detection. "
                f"Automatically adjusting to '{period}' for meaningful baseline analysis. "
                f"Currently a minimum of 7 days is required for accurate new entity detection."
            )

        # Filter entity-time matrix to only include supported dimensions
        supported_entity_time_matrix = {}
        for entity_name, time_series in entity_time_matrix.items():
            entity_dimension = self.entity_dimension_map.get(entity_name)
            if entity_dimension in NEW_ENTITY_DETECTION_SUPPORTED_DIMENSIONS:
                supported_entity_time_matrix[entity_name] = time_series
            else:
                self.logger.debug(
                    f"Skipping entity '{entity_name}' from dimension '{entity_dimension}' "
                    f"(not supported for new entity detection)"
                )

        if not supported_entity_time_matrix:
            self.logger.warning(
                "No entities from supported dimensions found for new entity detection. "
                f"Supported dimensions: {list(NEW_ENTITY_DETECTION_SUPPORTED_DIMENSIONS)}"
            )
            return [], period_conversion_notice

        # Use the statistical anomaly detector for new entity detection
        new_entities = self.detector.detect_new_cost_sources(
            supported_entity_time_matrix, period, self.entity_dimension_map, min_new_entity_threshold
        )

        return new_entities, period_conversion_notice
