"""Unit tests for FastMCP Performance Dashboard formatters.

Tests the FastMCPPerformanceFormatters class which builds markdown dashboard
output from structured performance data, including latency metrics,
alert summaries, and compliance sections.
"""

import pytest

from src.revenium_mcp_server.tools_decomposed.fastmcp_performance_formatters import (
    FastMCPPerformanceFormatters,
)


@pytest.fixture
def healthy_dashboard_data():
    """Dashboard data representing a healthy system."""
    return {
        "status": "healthy",
        "timestamp": "2024-01-15T10:00:00Z",
        "monitoring_window_hours": 24,
        "metrics_collected": 1500,
        "message": "All systems operational",
        "performance_summary": {
            "latency_p50_ms": 12.5,
            "latency_p95_ms": 45.0,
            "latency_p99_ms": 120.0,
            "throughput_avg_ops_per_sec": 50.0,
            "error_rate_avg_percent": 0.5,
            "memory_usage_avg_mb": 256.0,
            "cpu_usage_avg_percent": 35.0,
            "cache_hit_rate_avg_percent": 92.5,
        },
        "target_compliance": {
            "latency_p95_target_met": True,
            "latency_p99_target_met": True,
            "error_rate_target_met": True,
        },
        "alerts": {
            "total_active": 0,
            "critical": 0,
            "warning": 0,
            "recent_alerts": [],
        },
    }


@pytest.fixture
def degraded_dashboard_data():
    """Dashboard data representing a degraded system with alerts."""
    return {
        "status": "degraded",
        "timestamp": "2024-01-15T10:00:00Z",
        "monitoring_window_hours": 1,
        "metrics_collected": 50,
        "message": "Performance degraded",
        "performance_summary": {
            "latency_p50_ms": 80.0,
            "latency_p95_ms": 250.0,
            "latency_p99_ms": 500.0,
            "throughput_avg_ops_per_sec": 10.0,
            "error_rate_avg_percent": 5.0,
            "memory_usage_avg_mb": 1024.0,
            "cpu_usage_avg_percent": 90.0,
            "cache_hit_rate_avg_percent": 40.0,
        },
        "target_compliance": {
            "latency_p95_target_met": False,
            "latency_p99_target_met": False,
            "error_rate_target_met": False,
        },
        "alerts": {
            "total_active": 3,
            "critical": 1,
            "warning": 2,
            "recent_alerts": [
                {"severity": "CRITICAL", "message": "P99 latency exceeded 500ms", "tool_name": "manage_products"},
                {"severity": "WARNING", "message": "Error rate above 3%", "tool_name": "manage_alerts"},
            ],
        },
    }


class TestBuildCompleteDashboard:
    """Test full dashboard assembly from components."""

    def test_healthy_dashboard_contains_all_sections(self, healthy_dashboard_data):
        """Healthy dashboard includes header, perf, alerts, compliance, features."""
        result = FastMCPPerformanceFormatters.build_complete_dashboard(healthy_dashboard_data)
        assert isinstance(result, str)
        assert "FastMCP Performance Dashboard" in result
        assert "Performance Summary" in result
        assert "Active Alerts" in result
        assert "Target Compliance" in result
        assert "FastMCP Features" in result

    def test_degraded_dashboard_shows_failures(self, degraded_dashboard_data):
        """Degraded dashboard shows FAIL indicators in compliance section."""
        result = FastMCPPerformanceFormatters.build_complete_dashboard(degraded_dashboard_data)
        assert isinstance(result, str)
        # All three compliance items are failing — expect three FAIL occurrences
        assert result.count("FAIL") == 3
        # Status is uppercased in header
        assert "DEGRADED" in result

    def test_healthy_dashboard_shows_pass(self, healthy_dashboard_data):
        """Healthy dashboard shows PASS indicators in compliance section."""
        result = FastMCPPerformanceFormatters.build_complete_dashboard(healthy_dashboard_data)
        assert isinstance(result, str)
        # All three compliance items are passing — expect three PASS occurrences
        assert result.count("PASS") == 3
        assert "HEALTHY" in result

    def test_complete_dashboard_includes_metric_values(self, healthy_dashboard_data):
        """Complete dashboard embeds actual numeric values from the fixture."""
        result = FastMCPPerformanceFormatters.build_complete_dashboard(healthy_dashboard_data)
        assert isinstance(result, str)
        assert "12.50ms" in result   # P50
        assert "45.00ms" in result   # P95
        assert "120.00ms" in result  # P99
        assert "50.00 ops/sec" in result
        assert "256.00 MB" in result


class TestFormatNoDataResponse:
    """Test response when no performance data is available."""

    def test_no_data_includes_message(self):
        """No-data response includes the dashboard message."""
        data = {"message": "No tools have been executed yet"}
        result = FastMCPPerformanceFormatters.format_no_data_response(data)
        assert isinstance(result, str)
        assert "No tools have been executed yet" in result
        assert "No recent performance data" in result
        # Header still present
        assert "FastMCP Performance Dashboard" in result

    def test_no_data_includes_recommendations(self):
        """No-data response includes recommendations for generating data."""
        data = {"message": "Waiting for data"}
        result = FastMCPPerformanceFormatters.format_no_data_response(data)
        assert isinstance(result, str)
        assert "Recommendations" in result
        # At least one concrete recommendation bullet is present
        assert "performance monitoring" in result or "performance data" in result or "FastMCP" in result

    def test_no_data_response_is_string(self):
        """format_no_data_response returns a plain string."""
        data = {"message": "test"}
        result = FastMCPPerformanceFormatters.format_no_data_response(data)
        assert isinstance(result, str)
        assert len(result) > 0


class TestLatencyMetrics:
    """Test latency metrics formatting with compliance indicators."""

    def test_passing_latency_shows_ok(self, healthy_dashboard_data):
        """P95 and P99 within targets show [OK] markers."""
        perf = healthy_dashboard_data["performance_summary"]
        compliance = healthy_dashboard_data["target_compliance"]
        result = FastMCPPerformanceFormatters.format_latency_metrics(perf, compliance)
        assert isinstance(result, str)
        assert "[OK]" in result
        assert "12.50ms" in result  # P50
        assert "45.00ms" in result  # P95
        assert "120.00ms" in result  # P99

    def test_failing_latency_shows_fail_marker(self, degraded_dashboard_data):
        """P95/P99 exceeding targets show fail markers."""
        perf = degraded_dashboard_data["performance_summary"]
        compliance = degraded_dashboard_data["target_compliance"]
        result = FastMCPPerformanceFormatters.format_latency_metrics(perf, compliance)
        assert isinstance(result, str)
        # Exact values from fixture are rendered
        assert "250.00ms" in result  # P95
        assert "500.00ms" in result  # P99
        # No [OK] since both targets are missed
        assert "[OK]" not in result

    def test_latency_section_header_present(self, healthy_dashboard_data):
        """Latency section includes the Latency Metrics heading."""
        perf = healthy_dashboard_data["performance_summary"]
        compliance = healthy_dashboard_data["target_compliance"]
        result = FastMCPPerformanceFormatters.format_latency_metrics(perf, compliance)
        assert isinstance(result, str)
        assert "Latency Metrics" in result
        assert "P50" in result or "P95" in result or "P99" in result


class TestAlertFormatting:
    """Test alert section formatting."""

    def test_no_alerts_shows_ok(self, healthy_dashboard_data):
        """No recent alerts shows [OK] No active alerts."""
        alerts = healthy_dashboard_data["alerts"]
        result = FastMCPPerformanceFormatters.format_recent_alerts_list(alerts)
        assert isinstance(result, str)
        assert "No active alerts" in result
        assert "Recent Alerts" in result

    def test_critical_alerts_displayed(self, degraded_dashboard_data):
        """Critical alerts are displayed with severity and tool name."""
        alerts = degraded_dashboard_data["alerts"]
        result = FastMCPPerformanceFormatters.format_recent_alerts_list(alerts)
        assert isinstance(result, str)
        assert "CRITICAL" in result
        assert "WARNING" in result
        assert "P99 latency exceeded 500ms" in result
        assert "manage_products" in result
        # The second alert's tool name also appears
        assert "manage_alerts" in result

    def test_alert_summary_shows_counts(self, degraded_dashboard_data):
        """Alert summary shows total, critical, and warning counts."""
        alerts = degraded_dashboard_data["alerts"]
        result = FastMCPPerformanceFormatters.format_alert_summary(alerts)
        assert isinstance(result, str)
        assert "3" in result   # total
        assert "1" in result   # critical
        assert "2" in result   # warning
        # Section heading is present
        assert "Active Alerts" in result

    def test_alert_summary_zero_counts(self, healthy_dashboard_data):
        """Alert summary for a healthy system shows zero counts."""
        alerts = healthy_dashboard_data["alerts"]
        result = FastMCPPerformanceFormatters.format_alert_summary(alerts)
        assert isinstance(result, str)
        assert "0" in result
        assert "Active Alerts" in result


class TestComplianceSection:
    """Test target compliance section formatting."""

    def test_all_passing(self, healthy_dashboard_data):
        """All targets met shows PASS for each."""
        compliance = healthy_dashboard_data["target_compliance"]
        result = FastMCPPerformanceFormatters.format_compliance_section(compliance)
        assert isinstance(result, str)
        assert result.count("PASS") == 3
        assert "FAIL" not in result
        assert "Target Compliance" in result

    def test_all_failing(self, degraded_dashboard_data):
        """All targets missed shows FAIL for each."""
        compliance = degraded_dashboard_data["target_compliance"]
        result = FastMCPPerformanceFormatters.format_compliance_section(compliance)
        assert isinstance(result, str)
        assert result.count("FAIL") == 3
        assert "PASS" not in result
        assert "Target Compliance" in result

    def test_compliance_section_labels_present(self, healthy_dashboard_data):
        """Compliance section lists all three target labels."""
        compliance = healthy_dashboard_data["target_compliance"]
        result = FastMCPPerformanceFormatters.format_compliance_section(compliance)
        assert isinstance(result, str)
        assert "Latency P95" in result or "P95" in result
        assert "Latency P99" in result or "P99" in result
        assert "Error Rate" in result


class TestFeaturesSection:
    """Test features section formatting."""

    def test_features_section_content(self):
        """Features section lists expected FastMCP capabilities."""
        result = FastMCPPerformanceFormatters.format_features_section()
        assert isinstance(result, str)
        assert "Real-time performance monitoring" in result
        assert "Automated alerting system" in result
        # Verify additional capability entries are present
        assert "Percentile-based latency tracking" in result
        assert "Throughput analysis" in result
        assert "Target compliance validation" in result

    def test_features_section_has_heading(self):
        """Features section includes the FastMCP Features heading."""
        result = FastMCPPerformanceFormatters.format_features_section()
        assert isinstance(result, str)
        assert "FastMCP Features" in result
