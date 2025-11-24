"""Advanced analytics and insights for AI anomalies and alerts.

This module provides comprehensive analytics capabilities including trend analysis,
pattern detection, performance metrics, and predictive insights for anomaly management.
"""

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from ..client import ReveniumClient
from ..models import FilterParams, PaginationParams
from ..pagination import PaginationHelper


@dataclass
class TimeRange:
    """Time range for analytics queries."""

    start: datetime
    end: datetime

    def __post_init__(self):
        """Validate time range."""
        if self.start >= self.end:
            raise ValueError("Start time must be before end time")

        # Ensure timezone awareness
        if self.start.tzinfo is None:
            self.start = self.start.replace(tzinfo=timezone.utc)
        if self.end.tzinfo is None:
            self.end = self.end.replace(tzinfo=timezone.utc)

    @property
    def duration_hours(self) -> float:
        """Get duration in hours."""
        return (self.end - self.start).total_seconds() / 3600

    @property
    def duration_days(self) -> float:
        """Get duration in days."""
        return self.duration_hours / 24

    @classmethod
    def last_hours(cls, hours: int) -> "TimeRange":
        """Create time range for last N hours."""
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=hours)
        return cls(start=start, end=end)

    @classmethod
    def last_days(cls, days: int) -> "TimeRange":
        """Create time range for last N days."""
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        return cls(start=start, end=end)


@dataclass
class AnomalyFrequencyData:
    """Anomaly frequency analysis data."""

    total_anomalies: int
    active_anomalies: int
    inactive_anomalies: int
    enabled_anomalies: int
    disabled_anomalies: int
    anomalies_by_status: Dict[str, int]
    anomalies_by_team: Dict[str, int]
    detection_rule_types: Dict[str, int]
    most_common_metrics: List[Tuple[str, int]]
    creation_trend: List[Dict[str, Any]]

    def get_activation_rate(self) -> float:
        """Get anomaly activation rate."""
        if self.total_anomalies == 0:
            return 0.0
        return (self.active_anomalies / self.total_anomalies) * 100

    def get_enablement_rate(self) -> float:
        """Get anomaly enablement rate."""
        if self.total_anomalies == 0:
            return 0.0
        return (self.enabled_anomalies / self.total_anomalies) * 100


@dataclass
class AlertTrendData:
    """Alert trend analysis data."""

    total_alerts: int
    alerts_by_severity: Dict[str, int]
    alerts_by_status: Dict[str, int]
    resolution_times: List[float]  # in hours
    alert_frequency: List[Dict[str, Any]]  # time-series data
    top_triggering_anomalies: List[Dict[str, Any]]

    def get_average_resolution_time(self) -> float:
        """Get average resolution time in hours."""
        if not self.resolution_times:
            return 0.0
        return statistics.mean(self.resolution_times)

    def get_median_resolution_time(self) -> float:
        """Get median resolution time in hours."""
        if not self.resolution_times:
            return 0.0
        return statistics.median(self.resolution_times)


class AnalyticsEngine:
    """Advanced analytics engine for anomaly and alert data."""

    def __init__(self, cache_ttl: int = 600):  # 10 minutes default cache
        """Initialize analytics engine.

        Args:
            cache_ttl: Cache time-to-live in seconds
        """
        self.pagination_helper = PaginationHelper(cache_ttl=cache_ttl, enable_cache=True)
        self.cache_ttl = cache_ttl

    async def get_anomaly_frequency_analysis(
        self, client: ReveniumClient, time_range: Optional[TimeRange] = None
    ) -> AnomalyFrequencyData:
        """Analyze anomaly frequency and patterns.

        Args:
            client: API client instance
            time_range: Time range for analysis (defaults to last 30 days)

        Returns:
            Comprehensive anomaly frequency analysis
        """
        if time_range is None:
            time_range = TimeRange.last_days(30)

        logger.info(f"Analyzing anomaly frequency for {time_range.duration_days:.1f} days")

        # Get all anomalies with filtering by creation date
        filters = FilterParams(created_after=time_range.start, created_before=time_range.end)

        # Collect all anomalies
        all_anomalies = []
        page = 0
        page_size = 100

        while True:
            pagination = PaginationParams(page=page, size=page_size)
            response = await self.pagination_helper.execute_paginated_query(
                client=client,
                endpoint="/ai/anomalies",
                pagination=pagination,
                filters=filters,
                use_cache=True,
            )

            if not response.items:
                break

            all_anomalies.extend(response.items)

            if not response.pagination.has_next:
                break

            page += 1

        # Analyze the data
        total_anomalies = len(all_anomalies)
        active_anomalies = sum(1 for a in all_anomalies if a.get("status") == "active")
        inactive_anomalies = total_anomalies - active_anomalies
        enabled_anomalies = sum(1 for a in all_anomalies if a.get("enabled", True))
        disabled_anomalies = total_anomalies - enabled_anomalies

        # Status distribution
        status_counter = Counter(a.get("status", "unknown") for a in all_anomalies)
        anomalies_by_status = dict(status_counter)

        # Team distribution
        team_counter = Counter(a.get("team_id", "unknown") for a in all_anomalies)
        anomalies_by_team = dict(team_counter.most_common(10))  # Top 10 teams

        # Detection rule types
        rule_type_counter = Counter()
        for anomaly in all_anomalies:
            for rule in anomaly.get("detection_rules", []):
                rule_type_counter[rule.get("rule_type", "unknown")] += 1
        detection_rule_types = dict(rule_type_counter)

        # Most common metrics
        metric_counter = Counter()
        for anomaly in all_anomalies:
            for rule in anomaly.get("detection_rules", []):
                metric_counter[rule.get("metric", "unknown")] += 1
        most_common_metrics = metric_counter.most_common(10)

        # Creation trend (daily buckets)
        creation_trend = self._analyze_creation_trend(all_anomalies, time_range)

        return AnomalyFrequencyData(
            total_anomalies=total_anomalies,
            active_anomalies=active_anomalies,
            inactive_anomalies=inactive_anomalies,
            enabled_anomalies=enabled_anomalies,
            disabled_anomalies=disabled_anomalies,
            anomalies_by_status=anomalies_by_status,
            anomalies_by_team=anomalies_by_team,
            detection_rule_types=detection_rule_types,
            most_common_metrics=most_common_metrics,
            creation_trend=creation_trend,
        )

    async def get_top_alerting_anomalies(
        self, client: ReveniumClient, limit: int = 10, time_range: Optional[TimeRange] = None
    ) -> List[Dict[str, Any]]:
        """Get anomalies that generate the most alerts.

        Args:
            client: API client instance
            limit: Maximum number of anomalies to return
            time_range: Time range for analysis (defaults to last 7 days)

        Returns:
            List of top alerting anomalies with alert counts
        """
        if time_range is None:
            time_range = TimeRange.last_days(7)

        logger.info(f"Analyzing top alerting anomalies for {time_range.duration_days:.1f} days")

        # Get all alerts in the time range
        filters = FilterParams(created_after=time_range.start, created_before=time_range.end)

        # Collect all alerts
        all_alerts = []
        page = 0
        page_size = 100

        while True:
            pagination = PaginationParams(page=page, size=page_size)
            response = await self.pagination_helper.execute_paginated_query(
                client=client,
                endpoint="/ai/alerts",
                pagination=pagination,
                filters=filters,
                use_cache=True,
            )

            if not response.items:
                break

            all_alerts.extend(response.items)

            if not response.pagination.has_next:
                break

            page += 1

        # Count alerts by anomaly
        anomaly_alert_counts = Counter()
        anomaly_details = {}

        for alert in all_alerts:
            anomaly_id = alert.get("anomaly_id")
            if anomaly_id:
                anomaly_alert_counts[anomaly_id] += 1
                if anomaly_id not in anomaly_details:
                    anomaly_details[anomaly_id] = {
                        "anomaly_name": alert.get("anomaly_name", "Unknown"),
                        "latest_alert": alert.get("trigger_timestamp"),
                        "severities": [],
                    }
                anomaly_details[anomaly_id]["severities"].append(alert.get("severity", "unknown"))

        # Get top anomalies and enrich with details
        top_anomalies = []
        for anomaly_id, alert_count in anomaly_alert_counts.most_common(limit):
            details = anomaly_details[anomaly_id]
            severity_counts = Counter(details["severities"])

            top_anomalies.append(
                {
                    "anomaly_id": anomaly_id,
                    "anomaly_name": details["anomaly_name"],
                    "alert_count": alert_count,
                    "latest_alert": details["latest_alert"],
                    "severity_distribution": dict(severity_counts),
                    "most_common_severity": (
                        severity_counts.most_common(1)[0][0] if severity_counts else "unknown"
                    ),
                }
            )

        return top_anomalies

    async def get_alert_trend_analysis(
        self,
        client: ReveniumClient,
        anomaly_id: Optional[str] = None,
        time_range: Optional[TimeRange] = None,
    ) -> AlertTrendData:
        """Analyze alert trends and patterns.

        Args:
            client: API client instance
            anomaly_id: Specific anomaly ID to analyze (optional)
            time_range: Time range for analysis (defaults to last 7 days)

        Returns:
            Comprehensive alert trend analysis
        """
        if time_range is None:
            time_range = TimeRange.last_days(7)

        logger.info(f"Analyzing alert trends for {time_range.duration_days:.1f} days")

        # Build filters
        filters = FilterParams(created_after=time_range.start, created_before=time_range.end)

        if anomaly_id:
            # Add anomaly-specific filter
            filters.conditions.append(
                {"field": "anomaly_id", "operator": "eq", "value": anomaly_id}
            )

        # Collect all alerts
        all_alerts = []
        page = 0
        page_size = 100

        while True:
            pagination = PaginationParams(page=page, size=page_size)
            response = await self.pagination_helper.execute_paginated_query(
                client=client,
                endpoint="/ai/alerts",
                pagination=pagination,
                filters=filters,
                use_cache=True,
            )

            if not response.items:
                break

            all_alerts.extend(response.items)

            if not response.pagination.has_next:
                break

            page += 1

        # Analyze alert data
        total_alerts = len(all_alerts)

        # Severity distribution
        severity_counter = Counter(alert.get("severity", "unknown") for alert in all_alerts)
        alerts_by_severity = dict(severity_counter)

        # Status distribution
        status_counter = Counter(alert.get("status", "unknown") for alert in all_alerts)
        alerts_by_status = dict(status_counter)

        # Resolution times
        resolution_times = []
        for alert in all_alerts:
            if alert.get("resolved_at") and alert.get("trigger_timestamp"):
                try:
                    trigger_time = datetime.fromisoformat(
                        alert["trigger_timestamp"].replace("Z", "+00:00")
                    )
                    resolved_time = datetime.fromisoformat(
                        alert["resolved_at"].replace("Z", "+00:00")
                    )
                    resolution_hours = (resolved_time - trigger_time).total_seconds() / 3600
                    resolution_times.append(resolution_hours)
                except (ValueError, TypeError):
                    continue

        # Alert frequency (daily buckets)
        alert_frequency = self._analyze_alert_frequency(all_alerts, time_range)

        # Top triggering anomalies (if not filtered by anomaly_id)
        top_triggering_anomalies = []
        if not anomaly_id:
            anomaly_counter = Counter()
            for alert in all_alerts:
                if alert.get("anomaly_id"):
                    anomaly_counter[alert["anomaly_id"]] += 1

            for anomaly_id, count in anomaly_counter.most_common(5):
                # Get anomaly name from alerts
                anomaly_name = next(
                    (
                        alert.get("anomaly_name", "Unknown")
                        for alert in all_alerts
                        if alert.get("anomaly_id") == anomaly_id
                    ),
                    "Unknown",
                )
                top_triggering_anomalies.append(
                    {"anomaly_id": anomaly_id, "anomaly_name": anomaly_name, "alert_count": count}
                )

        return AlertTrendData(
            total_alerts=total_alerts,
            alerts_by_severity=alerts_by_severity,
            alerts_by_status=alerts_by_status,
            resolution_times=resolution_times,
            alert_frequency=alert_frequency,
            top_triggering_anomalies=top_triggering_anomalies,
        )

    def _analyze_creation_trend(
        self, anomalies: List[Dict[str, Any]], time_range: TimeRange
    ) -> List[Dict[str, Any]]:
        """Analyze anomaly creation trend over time."""
        # Create daily buckets
        daily_counts = defaultdict(int)

        for anomaly in anomalies:
            created_at = anomaly.get("created_at")
            if created_at:
                try:
                    created_date = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    day_key = created_date.date().isoformat()
                    daily_counts[day_key] += 1
                except (ValueError, TypeError):
                    continue

        # Generate complete time series
        trend_data = []
        current_date = time_range.start.date()
        end_date = time_range.end.date()

        while current_date <= end_date:
            day_key = current_date.isoformat()
            trend_data.append({"date": day_key, "count": daily_counts.get(day_key, 0)})
            current_date += timedelta(days=1)

        return trend_data

    def _analyze_alert_frequency(
        self, alerts: List[Dict[str, Any]], time_range: TimeRange
    ) -> List[Dict[str, Any]]:
        """Analyze alert frequency over time."""
        # Create hourly buckets for detailed analysis
        hourly_counts = defaultdict(int)

        for alert in alerts:
            trigger_timestamp = alert.get("trigger_timestamp")
            if trigger_timestamp:
                try:
                    trigger_time = datetime.fromisoformat(trigger_timestamp.replace("Z", "+00:00"))
                    hour_key = trigger_time.replace(minute=0, second=0, microsecond=0).isoformat()
                    hourly_counts[hour_key] += 1
                except (ValueError, TypeError):
                    continue

        # Generate complete time series
        frequency_data = []
        current_time = time_range.start.replace(minute=0, second=0, microsecond=0)
        end_time = time_range.end.replace(minute=0, second=0, microsecond=0)

        while current_time <= end_time:
            hour_key = current_time.isoformat()
            frequency_data.append({"timestamp": hour_key, "count": hourly_counts.get(hour_key, 0)})
            current_time += timedelta(hours=1)

        return frequency_data
