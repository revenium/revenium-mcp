"""Enhanced Spike Analyzer for temporal anomaly detection.

This module implements Enhanced Spike Analysis v2.0 as specified in the PRD.
Provides deterministic statistical analysis using z-score calculations for
detecting temporal anomalies in cost data across multiple dimensions.
"""

import asyncio
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

from loguru import logger

from .formatters.base_formatter import BaseFormattingUtilities
from .metric_units import render_dollars
from .report_reads import read_failure_reason
from .simple_cost_analyzer import RankedReportRead, SimpleCostAnalyzer
from .statistical_anomaly_detector import (
    DIMENSION_ENTITY_TYPES,
    SENSITIVITY_THRESHOLDS,
    NEW_ENTITY,
    DetectionSeries,
    StatisticalAnomalyDetector,
    bucket_span,
    describe_span,
    starts_at_midnight,
)
from ..auth import AuthenticationError

# Dimensions that support time-series data for new entity detection
NEW_ENTITY_DETECTION_SUPPORTED_DIMENSIONS = {
    "providers", "agents", "api_keys"
}

# The analytics route's API key report names only the costliest keys and rolls
# the rest into one group (get_cost_by_api_key in specs/openapi/isotope.json)
ANALYTICS_API_KEY_CAP = 20
ANALYTICS_API_KEY_ROLLUP_GROUP = "Other API keys"
API_KEYS_DIMENSION = "api_keys"
API_KEY_CAP_NOTE = (
    f"the analytics route names only the {ANALYTICS_API_KEY_CAP} costliest API keys in "
    f"the window and combines the rest as {ANALYTICS_API_KEY_ROLLUP_GROUP}, which is "
    f"not compared, so a new key outside the {ANALYTICS_API_KEY_CAP} is not reported"
)

# Windows too short to hold a baseline: new-entity detection reads this window instead
SHORT_WINDOWS = {"HOUR", "EIGHT_HOURS", "TWENTY_FOUR_HOURS"}
DETECTION_WINDOW = "SEVEN_DAYS"

# Dimension reports are read a few at a time, so one slow report (each read
# retries on a gateway timeout) does not hold up the others, without sending
# every report to the platform at once.
MAX_CONCURRENT_DIMENSION_READS = 3


def parse_bucket_instant(raw: Any) -> Optional[datetime]:
    """A bucket timestamp (epoch milliseconds or ISO 8601) as an aware UTC instant."""
    try:
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            return datetime.fromtimestamp(raw / 1000, tz=timezone.utc)
        if isinstance(raw, str) and raw:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None
    return None


class TemporalDataUnavailableError(Exception):
    """No dimension report could be read, so there is nothing to look for anomalies in."""

    def __init__(self, message: str, not_read: Optional[Dict[str, str]] = None) -> None:
        super().__init__(message)
        self.not_read = not_read or {}


@dataclass(frozen=True)
class TemporalCollection:
    """The dimension reports read, the ones that could not be read and why, and the ones read in part."""

    data: Dict[str, Any]
    not_read: Dict[str, str]
    incomplete: Dict[str, str]
    capped: Dict[str, str] = field(default_factory=dict)


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

        # Maps dimension name → endpoint registry key for resolve_analytics_request
        # (BACK-718 migration — paths resolved per-call so feature flag toggles are handled)
        self.temporal_analysis_endpoint_keys = {
            "providers": "total_cost_by_provider_over_time",
            "models": "total_cost_by_model",
            "api_keys": "cost_metrics_by_subscriber_credential",
            "agents": "cost_metrics_by_agents_over_time",
            "customers": "cost_metric_by_organization",
            "tokens": "tokens_per_minute_by_provider",
        }

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
        collection = await self._collect_temporal_data(period, include_dimensions)

        # Step 2: Build entity-time matrix
        entity_time_matrix = self._build_entity_time_matrix(collection.data)

        # Step 3: Detect entity-level temporal anomalies
        entity_anomalies = await self._detect_entity_anomalies(
            entity_time_matrix, sensitivity, min_impact_threshold, period
        )

        # Step 4: Detect new entities if requested
        new_entities: List = []
        new_entity_detection: Optional[Dict[str, Any]] = None
        period_conversion_notice = None
        if detect_new_entities:
            new_entities, new_entity_detection = await self._detect_new_entities(
                collection, period, include_dimensions, min_new_entity_threshold
            )
            period_conversion_notice = self._detection_window_notice(new_entity_detection)

        # Step 5: Sort by severity score and return formatted results
        entity_anomalies.sort(key=lambda x: x.severity_score, reverse=True)
        bucket_counts = {
            dimension: len(self._bucket_starts(collection.data, dimension))
            for dimension in collection.data
        }

        return self._format_temporal_results(
            entity_anomalies,
            period,
            sensitivity,
            include_dimensions,
            new_entities,
            period_conversion_notice,
            not_read=collection.not_read,
            incomplete=collection.incomplete,
            new_entity_detection=new_entity_detection,
            bucket_counts=bucket_counts,
        )

    async def _collect_temporal_data(
        self, period: str, include_dimensions: List[str]
    ) -> TemporalCollection:
        """Collect time-series data from all specified endpoints.

        Every page of each report is read on the analytics API (the legacy
        route answers one unpaged list), at most MAX_CONCURRENT_DIMENSION_READS
        reports at a time. A report that could not be read is recorded with its
        reason instead of standing in as an empty report.

        Args:
            period: Time period for data collection
            include_dimensions: Dimensions to collect data for

        Returns:
            The reports read, in include_dimensions order, with the ones not read or read in part

        Raises:
            TemporalDataUnavailableError: When no report could be read
        """
        reader = SimpleCostAnalyzer(self.client)
        # Resolve every request first: a missing team id fails the whole call, not each report
        requests = {
            # No aggregation: the anomaly reports are read over time, not ranked by group
            dimension: reader._resolve_ranked_request(
                self.temporal_analysis_endpoint_keys[dimension], period, aggregation=""
            )
            for dimension in include_dimensions
            if dimension in self.temporal_analysis_endpoint_keys
        }

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_DIMENSION_READS)
        outcomes = await asyncio.gather(
            *(
                self._read_dimension(semaphore, dimension, reader, request)
                for dimension, request in requests.items()
            ),
            return_exceptions=True,
        )

        reads: Dict[str, RankedReportRead] = {}
        reasons: Dict[str, str] = {}
        for dimension, outcome in zip(requests, outcomes):
            if isinstance(outcome, BaseException):
                raise outcome
            if isinstance(outcome, str):
                reasons[dimension] = outcome
            else:
                reads[dimension] = outcome
        for dimension in include_dimensions:
            if dimension not in self.temporal_analysis_endpoint_keys:
                self.logger.warning(f"Unknown dimension: {dimension}")
                reasons[dimension] = (
                    f"not a supported dimension ({', '.join(self.temporal_analysis_endpoint_keys)})"
                )

        not_read: Dict[str, str] = {
            dimension: reasons[dimension] for dimension in include_dimensions if dimension in reasons
        }
        if not reads:
            raise TemporalDataUnavailableError(
                "No cost report could be read, so no anomaly was looked for: "
                + ("; ".join(f"{dimension}: {reason}" for dimension, reason in not_read.items())
                   or "no dimension was requested"),
                not_read=not_read,
            )

        data: Dict[str, Any] = {}
        incomplete: Dict[str, str] = {}
        capped: Dict[str, str] = {}
        for dimension, read in reads.items():
            data[dimension] = read.response
            note = self._incomplete_note(read)
            if note:
                incomplete[dimension] = note
            if (
                dimension == API_KEYS_DIMENSION
                and not requests[dimension].routes_to_legacy_api
                and _has_api_key_rollup(read.response)
            ):
                capped[dimension] = API_KEY_CAP_NOTE
        return TemporalCollection(
            data=data, not_read=not_read, incomplete=incomplete, capped=capped
        )

    async def _read_dimension(
        self,
        semaphore: asyncio.Semaphore,
        dimension: str,
        reader: SimpleCostAnalyzer,
        request: Any,
    ) -> Union[RankedReportRead, str]:
        """Read one dimension's report, or say why it could not be read."""
        async with semaphore:
            try:
                self.logger.info(f"Collecting {dimension} data")
                read = await reader._read_ranked_report(request)
            except AuthenticationError:
                raise
            except Exception as error:
                self.logger.error(f"Failed to collect {dimension} data: {error}")
                return self._failure_reason(error)
        self.logger.info(f"Successfully collected {dimension} data")
        self.logger.debug(f"API response for {dimension}: {type(read.response)}")
        return read

    @staticmethod
    def _failure_reason(error: BaseException) -> str:
        """The reason a report could not be read, as the answer states it."""
        return read_failure_reason(error)

    @staticmethod
    def _incomplete_note(read: RankedReportRead) -> Optional[str]:
        """Which part of the window a read that stopped before the last page left unexamined."""
        unread = read.unread
        if unread is None:
            return None
        pages = f"read {unread.pages_read} of {unread.total_pages} pages"
        items = read.response if isinstance(read.response, list) else []
        last_item = items[-1] if items and isinstance(items[-1], dict) else {}
        last = last_item.get("endTimestamp") or last_item.get("startTimestamp")
        if last:
            return f"{pages}; buckets after {last} were not examined"
        return f"{pages}; pages after page {unread.pages_read} were not examined"

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

                raw_name = group.get("groupName")
                entity_name = str(raw_name).upper() if raw_name else "UNKNOWN"
                total_cost = self._calculate_group_cost(group.get("metrics", []))

                self.entity_dimension_map[entity_name] = dimension

                if entity_name not in entity_time_matrix:
                    entity_time_matrix[entity_name] = []

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

            raw_name = group.get("groupName")
            entity_name = str(raw_name).upper() if raw_name else "UNKNOWN"
            total_cost = self._calculate_group_cost(group.get("metrics", []))

            self.entity_dimension_map[entity_name] = dimension

            if entity_name not in entity_time_matrix:
                entity_time_matrix[entity_name] = []
            entity_time_matrix[entity_name].append((timestamp, total_cost))

    def _build_detection_series(
        self, time_series_data: Dict[str, Any], dimension: str, skip_group: str = ""
    ) -> Tuple[List[datetime], DetectionSeries]:
        """One dimension's bucket starts, oldest first, and a cost per bucket per name.

        Only the buckets this dimension's report returned count: another report
        can split the window into different buckets. A bucket where an entity
        has no group counts as no cost, so every series covers the same buckets.
        A name that repeats inside one bucket is summed; a group without a name,
        or named ``skip_group`` in any case, is left out.
        """
        costs: Dict[Tuple[str, str], Dict[datetime, float]] = {}
        starts = set()
        for entry, start in self._dated_entries(time_series_data, dimension):
            starts.add(start)
            for group in entry.get("groups") or []:
                if not isinstance(group, dict) or not group.get("groupName"):
                    continue
                key = (dimension, str(group["groupName"]).upper())
                if skip_group and key[1] == skip_group.upper():
                    continue
                by_start = costs.setdefault(key, {})
                by_start[start] = by_start.get(start, 0.0) + self._calculate_group_cost(
                    group.get("metrics") or []
                )
        ordered = sorted(starts)
        series = {
            key: [by_start.get(start, 0.0) for start in ordered]
            for key, by_start in costs.items()
        }
        return ordered, series

    def _bucket_starts(
        self, time_series_data: Dict[str, Any], dimension: str
    ) -> List[datetime]:
        """One dimension's distinct bucket starts, oldest first."""
        return sorted(
            {start for _, start in self._dated_entries(time_series_data, dimension)}
        )

    def _dated_entries(
        self, time_series_data: Dict[str, Any], dimension: str
    ) -> Iterator[Tuple[Dict[str, Any], datetime]]:
        """Each bucket this dimension's report returned, with its start."""
        data = time_series_data.get(dimension)
        if isinstance(data, dict) and "groups" in data:
            data = [data]
        for entry in data if isinstance(data, list) else []:
            start = self._bucket_start(entry) if isinstance(entry, dict) else None
            if start is not None:
                yield entry, start

    @staticmethod
    def _bucket_start(entry: Dict[str, Any]) -> Optional[datetime]:
        """A bucket's start, from startTimestamp or else its first metric's timestamp."""
        raw = entry.get("startTimestamp")
        if not raw:
            groups = entry.get("groups") or []
            first_group = groups[0] if groups and isinstance(groups[0], dict) else {}
            metrics = first_group.get("metrics") or []
            raw = metrics[0].get("timestamp") if metrics and isinstance(metrics[0], dict) else None
        return parse_bucket_instant(raw)

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
        not_read: Optional[Dict[str, str]] = None,
        incomplete: Optional[Dict[str, str]] = None,
        new_entity_detection: Optional[Dict[str, Any]] = None,
        bucket_counts: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """Format temporal anomaly results with optional new entity data.

        ``bucket_counts`` is the number of buckets each dimension's report
        returned: one ``time_groups_analyzed`` when they agree, else
        ``time_groups_by_dimension``.

        Args:
            anomalies: List of detected anomalies
            period: Analysis period
            sensitivity: Sensitivity level used
            include_dimensions: Dimensions that were analyzed
            new_entities: Optional list of new entity introductions
            not_read: Dimensions whose report could not be read, with the reason
            incomplete: Dimensions whose report was read in part, with what was left out
            new_entity_detection: What new-entity detection examined, or why it could not run

        Returns:
            Formatted results with anomalies and optional new entity data
        """
        # Calculate entities analyzed by dimension
        not_read = not_read or {}
        entities_analyzed = {}
        for dimension in include_dimensions:
            if dimension in not_read:
                continue
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
                    "percentage_above_normal": self._percent_vs_normal(anomaly),
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
            "entities_analyzed": entities_analyzed,
            "total_anomalies_detected": len(temporal_anomalies),
            "temporal_anomalies": temporal_anomalies,
            "time_period_summary": time_period_summary,
            "entity_summary": entity_summary,
            "recommendations": recommendations,
        }

        counts = bucket_counts or {}
        if len(set(counts.values())) == 1:
            result["time_groups_analyzed"] = next(iter(counts.values()))
        elif counts:
            result["time_groups_by_dimension"] = counts

        if new_entity_detection is not None:
            result["new_entity_detection"] = new_entity_detection

        # Add new entity detection results if available
        if new_entities:
            new_entity_data = self._format_new_entity_results(new_entities)
            result.update(new_entity_data)

        # Add period conversion notice if period was adjusted
        if period_conversion_notice:
            result["period_conversion_notice"] = period_conversion_notice

        if not_read:
            result["dimensions_not_read"] = not_read
        if incomplete:
            result["dimensions_incomplete"] = incomplete

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
        entities_by_type: Dict[str, Dict[str, Any]] = {}
        total_new_entities = len(new_entities)
        total_cost_impact = sum(entity.total_cost_impact for entity in new_entities)

        for entity in sorted(new_entities, key=lambda item: item.total_cost_impact, reverse=True):
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
                "baseline_buckets_without_cost": getattr(
                    entity, "baseline_buckets_without_cost", None
                ),
                "context": entity.context
            })
            entities_by_type[entity_type]["count"] += 1
            entities_by_type[entity_type]["total_cost_impact"] += entity.total_cost_impact

        format_currency = BaseFormattingUtilities.format_currency
        for entity_type, data in entities_by_type.items():
            types = [entity["introduction_type"] for entity in data["entities"]]
            data["summary"] = (
                f"{_new_and_activated(types, entity_type)}, "
                f"{format_currency(data['total_cost_impact'])} in the recent part"
            )

        all_types = [entity.introduction_type for entity in new_entities]
        new_count = all_types.count(NEW_ENTITY)
        return {
            "new_entities_detected": total_new_entities,
            "new_entities_new_count": new_count,
            "new_entities_activated_count": total_new_entities - new_count,
            "new_entities_total_cost_impact": total_cost_impact,
            "new_entities_by_type": entities_by_type,
            "new_entity_summary": (
                f"Detected {_new_and_activated(all_types, 'cost source')} with "
                f"{format_currency(total_cost_impact)} in the recent part"
            ),
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

            # Total both figures: the excess over normal (the anomalous cost impact)
            # and the full value (for the "x normal" multiplier)
            total_anomalous_cost = 0.0
            total_anomaly_value = 0.0
            normal_cost_for_period = 0.0

            for anomaly in primary_anomalies:
                normal_baseline = self._normal_baseline(anomaly)

                # Calculate anomalous excess above normal baseline
                # This represents the actual anomalous cost impact, not the full cost value
                anomalous_excess = max(0, anomaly.anomaly_value - normal_baseline)

                total_anomalous_cost += anomalous_excess
                total_anomaly_value += anomaly.anomaly_value
                normal_cost_for_period += normal_baseline

            # "x normal" is the period's cost divided by its normal cost (a doubling is 2.0x),
            # based on the primary entity type only
            cost_multiplier = round(
                total_anomaly_value / normal_cost_for_period if normal_cost_for_period > 0 else 0.0,
                1,
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
                "cost_multiplier": cost_multiplier,
                "anomaly_explanation": f"{time_label} had {entity_desc} with {cost_multiplier:.1f}x normal cost levels",
                "primary_entity_type_used": primary_entity_type,  # Add transparency about which entity type was used
                "entity_types_detected": list(entity_type_groups.keys()),  # Show all detected types
            }

        return time_period_summary

    @staticmethod
    def _normal_baseline(anomaly: TemporalAnomaly) -> float:
        """The normal cost every magnitude in the answer is measured against: the middle of the normal range."""
        return (anomaly.normal_range_min + anomaly.normal_range_max) / 2

    def _percent_vs_normal(self, anomaly: TemporalAnomaly) -> float:
        """How far the anomaly sits from normal, in percent, on the same basis as the cost multiplier."""
        base = self._normal_baseline(anomaly)
        return round((anomaly.anomaly_value / base - 1) * 100, 1) if base > 0 else 0.0

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
                normal_baseline = self._normal_baseline(anomaly)
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
            return f"Weekend anomaly pattern for this entity ({len(time_periods)} weekend periods)"

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

        # The z-score is absolute, so a cost far below the average is flagged too
        direction = "below" if anomaly_result.percentage_above_normal < 0 else "above"

        return (
            f"{entity_name} costs {preposition}{time_label} ({render_dollars(anomaly_result.value)}) "
            f"were {anomaly_result.z_score:.1f} standard deviations {direction} "
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
            f"{entity_name} costs {preposition}{time_label} ({render_dollars(anomaly_result.value)}) "
            f"were {anomaly_result.z_score:.1f} standard deviations above "
            f"the average value in the evaluated period"
        )

    async def _detect_new_entities(
        self,
        collection: TemporalCollection,
        period: str,
        include_dimensions: List[str],
        min_new_entity_threshold: float = 0.0,
    ) -> Tuple[List, Dict[str, Any]]:
        """Detect new cost sources, and say what was examined or why detection could not run.

        A window in SHORT_WINDOWS holds no baseline, so the supported dimensions are
        read again over DETECTION_WINDOW for detection only; the anomalies keep the
        requested window.

        Args:
            collection: The reports read for the requested window
            period: The requested period
            include_dimensions: The requested dimensions
            min_new_entity_threshold: Minimum recent cost to report an entity

        Returns:
            Tuple of (NewEntityIntroduction list, the detection outcome for the answer)
        """
        dimensions = [
            dimension
            for dimension in dict.fromkeys(include_dimensions)
            if dimension in NEW_ENTITY_DETECTION_SUPPORTED_DIMENSIONS
        ]
        detection_period = DETECTION_WINDOW if period in SHORT_WINDOWS else period
        outcome: Dict[str, Any] = {
            "requested_period": period,
            "detection_period": detection_period,
            "min_new_entity_threshold": min_new_entity_threshold,
            "dimensions_examined": [],
            "dimensions_not_read": {},
            "dimensions_incomplete": {},
            "dimensions_not_compared": {},
        }
        if not dimensions:
            supported = ", ".join(sorted(NEW_ENTITY_DETECTION_SUPPORTED_DIMENSIONS))
            return [], self._not_run(
                outcome, f"none of the requested dimensions supports it (use {supported})"
            )

        source = collection
        if detection_period != period:
            try:
                source = await self._collect_temporal_data(detection_period, dimensions)
            except TemporalDataUnavailableError as error:
                failed = "; ".join(f"{name} ({reason})" for name, reason in error.not_read.items())
                return [], self._not_run(
                    outcome, f"the {detection_period} read it needs failed: {failed}"
                )

        examined = [dimension for dimension in dimensions if dimension in source.data]
        outcome["dimensions_examined"] = examined
        outcome["dimensions_not_read"] = {
            dimension: reason
            for dimension, reason in source.not_read.items()
            if dimension in dimensions
        }
        outcome["dimensions_incomplete"] = {
            dimension: note for dimension, note in source.incomplete.items() if dimension in examined
        }
        outcome["dimensions_capped"] = {
            dimension: note for dimension, note in source.capped.items() if dimension in examined
        }
        if not examined:
            failed = "; ".join(
                f"{name} ({reason})" for name, reason in outcome["dimensions_not_read"].items()
            )
            return [], self._not_run(outcome, f"no report it needs could be read: {failed}")

        new_entities: List = []
        spans_by_dimension: Dict[str, Dict[str, Any]] = {}
        not_compared: Dict[str, str] = outcome["dimensions_not_compared"]
        for dimension in examined:
            skip = ANALYTICS_API_KEY_ROLLUP_GROUP if dimension in source.capped else ""
            bucket_starts, series = self._build_detection_series(
                source.data, dimension, skip_group=skip
            )
            try:
                found = self.detector.detect_new_cost_sources(
                    series, bucket_starts, detection_period, min_new_entity_threshold
                )
            except ValueError as error:
                not_compared[dimension] = str(error)
                continue
            new_entities.extend(found)
            spans_by_dimension[dimension] = self._spans(detection_period, bucket_starts)
        if not spans_by_dimension:
            return [], self._not_run(outcome, self._not_compared_reason(not_compared))

        grids = list(spans_by_dimension.values())
        if all(spans == grids[0] for spans in grids):
            outcome.update(grids[0])
        else:
            outcome["spans_by_dimension"] = spans_by_dimension
        outcome["status"] = "found" if new_entities else "none"
        return new_entities, outcome

    @staticmethod
    def _not_run(outcome: Dict[str, Any], reason: str) -> Dict[str, Any]:
        outcome.update(status="not_run", reason=reason)
        return outcome

    @staticmethod
    def _not_compared_reason(not_compared: Dict[str, str]) -> str:
        """Why no dimension could be compared: the shared reason, or each one's own."""
        reasons = set(not_compared.values())
        if len(reasons) == 1:
            return reasons.pop()
        return "; ".join(f"{name}: {reason}" for name, reason in not_compared.items())

    def _spans(self, period: str, bucket_starts: List[datetime]) -> Dict[str, Any]:
        """The whole window, baseline and recent part of one dimension's buckets."""
        baseline_count = self.detector.baseline_bucket_count(period, len(bucket_starts))
        return {
            "whole_window": bucket_span(bucket_starts),
            "baseline": bucket_span(bucket_starts[:baseline_count]),
            "recent": bucket_span(bucket_starts[baseline_count:]),
            "buckets_start_at_midnight": starts_at_midnight(bucket_starts),
        }

    @staticmethod
    def _detection_window_notice(detection: Dict[str, Any]) -> Optional[str]:
        """The true sentence for a short window whose detection read DETECTION_WINDOW."""
        requested = detection["requested_period"]
        groups = detection_span_groups(detection)
        if detection["detection_period"] == requested or not groups:
            return None
        if len(groups) == 1:
            read = describe_part(groups[0][1], "whole_window")
        else:
            read = "; ".join(
                f"{', '.join(dimensions)}: {describe_part(spans, 'whole_window')}"
                for dimensions, spans in groups
            )
        return (
            f"New-entity detection read {detection['detection_period']} of data "
            f"({read}), because {requested} is too short to "
            f"hold a baseline; the anomalies cover {requested} only."
        )


def _new_and_activated(introduction_types: List[str], noun: str) -> str:
    """'1 new and 2 activated agents', leaving out a count of zero."""
    total = len(introduction_types)
    new = introduction_types.count(NEW_ENTITY)
    counts = [f"{count} {kind}" for count, kind in ((new, "new"), (total - new, "activated")) if count]
    return f"{' and '.join(counts)} {noun}{'s' if total > 1 else ''}"


def _has_api_key_rollup(response: Any) -> bool:
    """Whether any bucket of an API key report holds the roll-up group."""
    rollup = ANALYTICS_API_KEY_ROLLUP_GROUP.upper()
    buckets = [response] if isinstance(response, dict) else response
    return any(
        str(group.get("groupName") or "").upper() == rollup
        for bucket in (buckets if isinstance(buckets, list) else [])
        if isinstance(bucket, dict)
        for group in bucket.get("groups") or []
        if isinstance(group, dict)
    )


def describe_part(spans: Dict[str, Any], part: str) -> str:
    """'the N buckets starting A to B' for whole_window, baseline or recent of spans."""
    return describe_span(spans[part], not spans.get("buckets_start_at_midnight", True))


def detection_span_groups(
    detection: Dict[str, Any],
) -> List[Tuple[List[str], Dict[str, Any]]]:
    """The compared dimensions, each group with the spans its buckets share."""
    by_dimension = detection.get("spans_by_dimension")
    if by_dimension:
        return [([dimension], spans) for dimension, spans in by_dimension.items()]
    if not detection.get("whole_window"):
        return []
    not_compared = detection.get("dimensions_not_compared") or {}
    compared = [
        dimension
        for dimension in detection.get("dimensions_examined") or []
        if dimension not in not_compared
    ]
    return [(compared, detection)]


def spans_for_entity_type(
    detection: Dict[str, Any], entity_type: str
) -> Dict[str, Any]:
    """The spans an entity of this type was compared over."""
    by_dimension: Dict[str, Dict[str, Any]] = detection.get("spans_by_dimension") or {}
    for dimension, dimension_type in DIMENSION_ENTITY_TYPES.items():
        if dimension_type == entity_type and dimension in by_dimension:
            return by_dimension[dimension]
    return detection
