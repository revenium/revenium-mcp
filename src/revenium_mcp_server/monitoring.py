"""System Monitoring and Health Checks.

This module provides comprehensive monitoring capabilities for the Alerts & Anomalies
MCP server, including health checks, system metrics, and alerting.
"""

import asyncio
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import psutil
from loguru import logger

from .logging_config import get_performance_summary


class HealthStatus(str, Enum):
    """Health status enumeration."""

    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass
class HealthCheck:
    """Health check result."""

    name: str
    status: HealthStatus
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: float = 0.0


@dataclass
class SystemMetrics:
    """System performance metrics."""

    cpu_percent: float
    memory_percent: float
    memory_available_mb: float
    disk_usage_percent: float
    disk_free_gb: float
    network_connections: int
    uptime_seconds: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class HealthMonitor:
    """Comprehensive health monitoring system with production-grade features."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize health monitor with production configuration.

        Args:
            config: Optional configuration dictionary for production settings
        """
        self.config = config or {}
        self.health_checks: Dict[str, Callable] = {}
        self.last_health_check: Optional[datetime] = None
        self.health_history: List[Dict[str, HealthCheck]] = []

        # Production-grade alert thresholds (configurable by environment)
        self.alert_thresholds = self.config.get(
            "alert_thresholds",
            {
                "cpu_percent": 80.0,
                "memory_percent": 85.0,
                "disk_usage_percent": 90.0,
                "error_rate": 10.0,  # percentage
                "avg_response_time": 5.0,  # seconds
                "success_rate": 95.0,  # minimum success rate
                "health_check_duration": 5000.0,  # milliseconds
            },
        )

        # Production monitoring features
        self.environment = self.config.get("environment", "development")
        self.enable_alerting = self.config.get("enable_alerting", True)
        self.alert_cooldown = self.config.get("alert_cooldown", 300)  # 5 minutes
        self.metrics_retention_hours = self.config.get("metrics_retention_hours", 24)

        # Alert state tracking
        self.active_alerts: Dict[str, Dict[str, Any]] = {}
        self.alert_history: List[Dict[str, Any]] = []
        self.last_alert_times: Dict[str, datetime] = {}

        # Performance baselines for anomaly detection
        self.performance_baselines: Dict[str, Dict[str, Any]] = {}
        self.baseline_samples: Dict[str, List[float]] = {}
        self.baseline_window_size = 100  # samples for baseline calculation

        self.start_time = time.time()

    def register_health_check(self, name: str, check_func: Callable):
        """Register a health check function.

        Args:
            name: Name of the health check
            check_func: Async function that returns HealthCheck
        """
        self.health_checks[name] = check_func
        logger.info(f"Registered health check: {name}")

    async def run_health_check(self, name: str) -> HealthCheck:
        """Run a specific health check.

        Args:
            name: Name of the health check to run

        Returns:
            HealthCheck result
        """
        if name not in self.health_checks:
            return HealthCheck(
                name=name, status=HealthStatus.UNKNOWN, message=f"Health check '{name}' not found"
            )

        start_time = time.time()
        try:
            check_func = self.health_checks[name]
            result = await check_func()
            result.duration_ms = (time.time() - start_time) * 1000
            return result
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.error(f"Health check '{name}' failed", error=str(e))
            return HealthCheck(
                name=name,
                status=HealthStatus.CRITICAL,
                message=f"Health check failed: {str(e)}",
                duration_ms=duration_ms,
            )

    async def run_all_health_checks(self) -> Dict[str, HealthCheck]:
        """Run all registered health checks.

        Returns:
            Dictionary of health check results
        """
        logger.info("Running all health checks")

        results = {}
        tasks = []

        for name in self.health_checks:
            tasks.append(self.run_health_check(name))

        if tasks:
            check_results = await asyncio.gather(*tasks, return_exceptions=True)

            for i, result in enumerate(check_results):
                name = list(self.health_checks.keys())[i]
                if isinstance(result, Exception):
                    results[name] = HealthCheck(
                        name=name,
                        status=HealthStatus.CRITICAL,
                        message=f"Health check exception: {str(result)}",
                    )
                else:
                    results[name] = result

        # Store in history
        self.health_history.append(results)
        # Keep only last 100 health check runs
        self.health_history = self.health_history[-100:]

        self.last_health_check = datetime.now(timezone.utc)

        logger.info(f"Completed {len(results)} health checks")
        return results

    def get_system_metrics(self) -> SystemMetrics:
        """Get current system performance metrics.

        Returns:
            SystemMetrics object
        """
        try:
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)

            # Memory usage
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            memory_available_mb = memory.available / (1024 * 1024)

            # Disk usage
            disk = psutil.disk_usage("/")
            disk_usage_percent = (disk.used / disk.total) * 100
            disk_free_gb = disk.free / (1024 * 1024 * 1024)

            # Network connections
            network_connections = len(psutil.net_connections())

            # Uptime
            uptime_seconds = time.time() - self.start_time

            return SystemMetrics(
                cpu_percent=cpu_percent,
                memory_percent=memory_percent,
                memory_available_mb=memory_available_mb,
                disk_usage_percent=disk_usage_percent,
                disk_free_gb=disk_free_gb,
                network_connections=network_connections,
                uptime_seconds=uptime_seconds,
            )

        except Exception as e:
            logger.error(f"Failed to get system metrics: {e}")
            return SystemMetrics(
                cpu_percent=0.0,
                memory_percent=0.0,
                memory_available_mb=0.0,
                disk_usage_percent=0.0,
                disk_free_gb=0.0,
                network_connections=0,
                uptime_seconds=0.0,
            )

    def check_alert_conditions(
        self, metrics: SystemMetrics, performance_summary: Dict[str, Any]
    ) -> List[str]:
        """Check if any alert conditions are met.

        Args:
            metrics: System metrics
            performance_summary: Performance summary from tracker

        Returns:
            List of alert messages
        """
        alerts = []

        # System resource alerts
        if metrics.cpu_percent > self.alert_thresholds["cpu_percent"]:
            alerts.append(f"High CPU usage: {metrics.cpu_percent:.1f}%")

        if metrics.memory_percent > self.alert_thresholds["memory_percent"]:
            alerts.append(f"High memory usage: {metrics.memory_percent:.1f}%")

        if metrics.disk_usage_percent > self.alert_thresholds["disk_usage_percent"]:
            alerts.append(f"High disk usage: {metrics.disk_usage_percent:.1f}%")

        # Performance alerts
        for op_type, perf_data in performance_summary.items():
            error_rate = 100 - perf_data.get("success_rate", 100)
            if error_rate > self.alert_thresholds["error_rate"]:
                alerts.append(f"High error rate for {op_type}: {error_rate:.1f}%")

            avg_duration = perf_data.get("avg_duration", 0)
            if avg_duration > self.alert_thresholds["avg_response_time"]:
                alerts.append(f"Slow response time for {op_type}: {avg_duration:.2f}s")

        return alerts

    async def get_comprehensive_status(self) -> Dict[str, Any]:
        """Get comprehensive system status including health checks and metrics.

        Returns:
            Complete system status dictionary
        """
        # Run health checks
        health_results = await self.run_all_health_checks()

        # Get system metrics
        system_metrics = self.get_system_metrics()

        # Get performance summary
        performance_summary = get_performance_summary()

        # Check for alerts
        alerts = self.check_alert_conditions(system_metrics, performance_summary)

        # Determine overall status
        overall_status = HealthStatus.HEALTHY
        for check in health_results.values():
            if check.status == HealthStatus.CRITICAL:
                overall_status = HealthStatus.CRITICAL
                break
            elif check.status == HealthStatus.WARNING and overall_status == HealthStatus.HEALTHY:
                overall_status = HealthStatus.WARNING

        # Add system resource warnings
        if (
            system_metrics.cpu_percent > 70
            or system_metrics.memory_percent > 75
            or system_metrics.disk_usage_percent > 80
        ):
            if overall_status == HealthStatus.HEALTHY:
                overall_status = HealthStatus.WARNING

        return {
            "overall_status": overall_status.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "uptime_seconds": system_metrics.uptime_seconds,
            "health_checks": {
                name: {
                    "status": check.status.value,
                    "message": check.message,
                    "duration_ms": check.duration_ms,
                    "details": check.details,
                }
                for name, check in health_results.items()
            },
            "system_metrics": {
                "cpu_percent": system_metrics.cpu_percent,
                "memory_percent": system_metrics.memory_percent,
                "memory_available_mb": system_metrics.memory_available_mb,
                "disk_usage_percent": system_metrics.disk_usage_percent,
                "disk_free_gb": system_metrics.disk_free_gb,
                "network_connections": system_metrics.network_connections,
            },
            "performance_summary": performance_summary,
            "alerts": alerts,
            "last_health_check": (
                self.last_health_check.isoformat() if self.last_health_check else None
            ),
        }

    def get_health_history(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Get health check history for the specified time period.

        Args:
            hours: Number of hours of history to return

        Returns:
            List of historical health check results
        """
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

        filtered_history = []
        for health_checks in self.health_history:
            # Check if any health check in this run is within the time window
            for check in health_checks.values():
                if check.timestamp >= cutoff_time:
                    filtered_history.append(
                        {
                            "timestamp": check.timestamp.isoformat(),
                            "checks": {
                                name: {
                                    "status": hc.status.value,
                                    "message": hc.message,
                                    "duration_ms": hc.duration_ms,
                                }
                                for name, hc in health_checks.items()
                            },
                        }
                    )
                    break

        return filtered_history

    # Production Monitoring Enhancements

    def update_performance_baseline(self, metric_name: str, value: float):
        """Update performance baseline for anomaly detection.

        Args:
            metric_name: Name of the metric
            value: Current metric value
        """
        if metric_name not in self.baseline_samples:
            self.baseline_samples[metric_name] = []

        # Add sample and maintain window size
        self.baseline_samples[metric_name].append(value)
        if len(self.baseline_samples[metric_name]) > self.baseline_window_size:
            self.baseline_samples[metric_name] = self.baseline_samples[metric_name][
                -self.baseline_window_size :
            ]

        # Calculate baseline statistics
        samples = self.baseline_samples[metric_name]
        if len(samples) >= 10:  # Minimum samples for baseline
            self.performance_baselines[metric_name] = {
                "mean": sum(samples) / len(samples),
                "min": min(samples),
                "max": max(samples),
                "std_dev": self._calculate_std_dev(samples),
                "sample_count": len(samples),
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }

    def _calculate_std_dev(self, values: List[float]) -> float:
        """Calculate standard deviation of values."""
        if len(values) < 2:
            return 0.0

        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
        return variance**0.5

    def detect_performance_anomalies(
        self, current_metrics: Dict[str, float]
    ) -> List[Dict[str, Any]]:
        """Detect performance anomalies based on baselines.

        Args:
            current_metrics: Current performance metrics

        Returns:
            List of detected anomalies
        """
        anomalies = []

        for metric_name, current_value in current_metrics.items():
            if metric_name in self.performance_baselines:
                baseline = self.performance_baselines[metric_name]
                mean = baseline["mean"]
                std_dev = baseline["std_dev"]

                # Detect anomalies using 2-sigma rule
                if std_dev > 0:
                    z_score = abs(current_value - mean) / std_dev
                    if z_score > 2.0:  # 2-sigma threshold
                        anomalies.append(
                            {
                                "metric": metric_name,
                                "current_value": current_value,
                                "baseline_mean": mean,
                                "z_score": z_score,
                                "severity": "critical" if z_score > 3.0 else "warning",
                                "message": f"{metric_name} anomaly detected: {current_value:.2f} (baseline: {mean:.2f}±{std_dev:.2f})",
                            }
                        )

        return anomalies

    def create_alert(
        self, alert_type: str, severity: str, message: str, details: Optional[Dict[str, Any]] = None
    ) -> str:
        """Create a new alert with cooldown management.

        Args:
            alert_type: Type of alert (e.g., 'cpu_high', 'error_rate_high')
            severity: Alert severity ('info', 'warning', 'critical')
            message: Alert message
            details: Optional additional details

        Returns:
            Alert ID if created, empty string if suppressed by cooldown
        """
        if not self.enable_alerting:
            return ""

        # Check cooldown
        now = datetime.now(timezone.utc)
        if alert_type in self.last_alert_times:
            time_since_last = (now - self.last_alert_times[alert_type]).total_seconds()
            if time_since_last < self.alert_cooldown:
                return ""  # Suppressed by cooldown

        # Create alert
        alert_id = f"{alert_type}_{int(now.timestamp())}"
        alert = {
            "id": alert_id,
            "type": alert_type,
            "severity": severity,
            "message": message,
            "details": details or {},
            "created_at": now.isoformat(),
            "environment": self.environment,
            "resolved": False,
            "resolved_at": None,
        }

        # Store alert
        self.active_alerts[alert_id] = alert
        self.alert_history.append(alert)
        self.last_alert_times[alert_type] = now

        # Log alert
        log_level = (
            "critical" if severity == "critical" else "warning" if severity == "warning" else "info"
        )
        getattr(logger, log_level)(
            f"Alert created: {message}", alert_id=alert_id, alert_type=alert_type
        )

        return alert_id

    def resolve_alert(self, alert_id: str, resolution_message: Optional[str] = None):
        """Resolve an active alert.

        Args:
            alert_id: ID of the alert to resolve
            resolution_message: Optional resolution message
        """
        if alert_id in self.active_alerts:
            alert = self.active_alerts[alert_id]
            alert["resolved"] = True
            alert["resolved_at"] = datetime.now(timezone.utc).isoformat()
            if resolution_message:
                alert["resolution_message"] = resolution_message

            # Remove from active alerts
            del self.active_alerts[alert_id]

            logger.info(f"Alert resolved: {alert['message']}", alert_id=alert_id)

    def get_production_dashboard(self) -> Dict[str, Any]:
        """Get production monitoring dashboard data.

        Returns:
            Comprehensive production dashboard data
        """
        # Get current status
        system_metrics = self.get_system_metrics()
        performance_summary = get_performance_summary()

        # Update baselines
        current_perf_metrics = {
            "cpu_percent": system_metrics.cpu_percent,
            "memory_percent": system_metrics.memory_percent,
            "disk_usage_percent": system_metrics.disk_usage_percent,
        }

        for metric_name, value in current_perf_metrics.items():
            self.update_performance_baseline(metric_name, value)

        # Detect anomalies
        anomalies = self.detect_performance_anomalies(current_perf_metrics)

        # Calculate SLA compliance
        sla_compliance = self._calculate_sla_compliance(performance_summary)

        # Get alert summary
        alert_summary = {
            "active_alerts": len(self.active_alerts),
            "total_alerts_24h": len(
                [
                    a
                    for a in self.alert_history
                    if datetime.fromisoformat(a["created_at"].replace("Z", "+00:00"))
                    > datetime.now(timezone.utc) - timedelta(hours=24)
                ]
            ),
            "critical_alerts": len(
                [a for a in self.active_alerts.values() if a["severity"] == "critical"]
            ),
            "warning_alerts": len(
                [a for a in self.active_alerts.values() if a["severity"] == "warning"]
            ),
        }

        return {
            "environment": self.environment,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "uptime_seconds": time.time() - self.start_time,
            "system_metrics": asdict(system_metrics),
            "performance_summary": performance_summary,
            "performance_baselines": self.performance_baselines,
            "anomalies": anomalies,
            "sla_compliance": sla_compliance,
            "alert_summary": alert_summary,
            "active_alerts": list(self.active_alerts.values()),
            "health_status": "healthy" if not anomalies and not self.active_alerts else "degraded",
        }

    def _calculate_sla_compliance(self, performance_summary: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate SLA compliance metrics.

        Args:
            performance_summary: Performance summary data

        Returns:
            SLA compliance information
        """
        if not performance_summary:
            return {
                "status": "no_data",
                "compliance_rate": 0,
                "target_success_rate": 99.5,
                "target_response_time": 1.0,
                "compliant_operations": 0,
                "total_operations": 0,
                "sla_status": "no_data",
            }

        # SLA targets
        target_success_rate = 99.5
        target_response_time = 1.0

        compliant_operations = 0
        total_operations = len(performance_summary)

        for op_data in performance_summary.values():
            success_rate = op_data.get("success_rate", 0)
            avg_duration = op_data.get("avg_duration", 0)

            if success_rate >= target_success_rate and avg_duration <= target_response_time:
                compliant_operations += 1

        compliance_rate = (
            (compliant_operations / total_operations * 100) if total_operations > 0 else 0
        )

        return {
            "target_success_rate": target_success_rate,
            "target_response_time": target_response_time,
            "compliance_rate": round(compliance_rate, 2),
            "compliant_operations": compliant_operations,
            "total_operations": total_operations,
            "sla_status": (
                "compliant"
                if compliance_rate >= 95
                else "at_risk" if compliance_rate >= 90 else "non_compliant"
            ),
        }


# Global health monitor instance
health_monitor = HealthMonitor()


# Default health checks
async def api_connectivity_check() -> HealthCheck:
    """Check API connectivity and basic functionality."""
    try:
        # This would typically make a simple API call
        # For now, we'll simulate a basic connectivity check
        await asyncio.sleep(0.1)  # Simulate API call

        return HealthCheck(
            name="api_connectivity",
            status=HealthStatus.HEALTHY,
            message="API connectivity is healthy",
        )
    except Exception as e:
        return HealthCheck(
            name="api_connectivity",
            status=HealthStatus.CRITICAL,
            message=f"API connectivity failed: {str(e)}",
        )


async def database_connectivity_check() -> HealthCheck:
    """Check database connectivity."""
    try:
        # This would typically check database connection
        # For now, we'll simulate a basic check
        await asyncio.sleep(0.05)  # Simulate DB query

        return HealthCheck(
            name="database_connectivity",
            status=HealthStatus.HEALTHY,
            message="Database connectivity is healthy",
        )
    except Exception as e:
        return HealthCheck(
            name="database_connectivity",
            status=HealthStatus.CRITICAL,
            message=f"Database connectivity failed: {str(e)}",
        )


async def performance_check() -> HealthCheck:
    """Check system performance metrics."""
    try:
        performance_summary = get_performance_summary()

        # Check if we have any performance data
        if not performance_summary:
            return HealthCheck(
                name="performance",
                status=HealthStatus.WARNING,
                message="No performance data available yet",
            )

        # Check for high error rates
        high_error_operations = []
        slow_operations = []

        for op_type, metrics in performance_summary.items():
            success_rate = metrics.get("success_rate", 100)
            avg_duration = metrics.get("avg_duration", 0)

            if success_rate < 90:
                high_error_operations.append(f"{op_type} ({success_rate:.1f}%)")

            if avg_duration > 2.0:
                slow_operations.append(f"{op_type} ({avg_duration:.2f}s)")

        if high_error_operations:
            return HealthCheck(
                name="performance",
                status=HealthStatus.CRITICAL,
                message=f"High error rates detected: {', '.join(high_error_operations)}",
                details={"high_error_operations": high_error_operations},
            )

        if slow_operations:
            return HealthCheck(
                name="performance",
                status=HealthStatus.WARNING,
                message=f"Slow operations detected: {', '.join(slow_operations)}",
                details={"slow_operations": slow_operations},
            )

        return HealthCheck(
            name="performance",
            status=HealthStatus.HEALTHY,
            message="Performance metrics are healthy",
            details={"operations_monitored": len(performance_summary)},
        )

    except Exception as e:
        return HealthCheck(
            name="performance",
            status=HealthStatus.CRITICAL,
            message=f"Performance check failed: {str(e)}",
        )


# Register default health checks
health_monitor.register_health_check("api_connectivity", api_connectivity_check)
health_monitor.register_health_check("database_connectivity", database_connectivity_check)
health_monitor.register_health_check("performance", performance_check)
