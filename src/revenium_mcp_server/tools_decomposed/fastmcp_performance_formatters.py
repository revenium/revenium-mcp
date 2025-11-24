"""FastMCP Performance Dashboard Formatters.

This module contains all formatting methods for the FastMCP Performance Dashboard.
Extracted to maintain ≤300 lines per module enterprise standard.
"""

from typing import Any, Dict


class FastMCPPerformanceFormatters:
    """Formatters for FastMCP Performance Dashboard."""

    @staticmethod
    def format_no_data_response(dashboard_data: Dict[str, Any]) -> str:
        """Format response when no performance data is available.

        Args:
            dashboard_data: Dashboard data containing status and message

        Returns:
            Formatted no data response string
        """
        return f"""# **FastMCP Performance Dashboard**

⚠️ **Status**: No recent performance data available

**Message**: {dashboard_data["message"]}

**Recommendations**:
- Wait for tool operations to generate performance data
- Check if performance monitoring is enabled
- Verify FastMCP decorators are applied to tools

**Next Steps**:
- Use any MCP tool to generate performance metrics
- Check back in a few minutes for updated data
"""

    @staticmethod
    def get_status_emoji(dashboard_data: Dict[str, Any]) -> str:
        """Get status emoji based on dashboard health.

        Args:
            dashboard_data: Dashboard data containing status

        Returns:
            Status emoji string
        """
        return "" if dashboard_data["status"] == "healthy" else ""

    @staticmethod
    def format_dashboard_header(dashboard_data: Dict[str, Any], status_emoji: str) -> str:
        """Format dashboard header section.

        Args:
            dashboard_data: Dashboard data containing metadata
            status_emoji: Status emoji for the header

        Returns:
            Formatted header string
        """
        return f"""# **FastMCP Performance Dashboard** {status_emoji}

**Status**: {dashboard_data["status"].upper()}
**Last Updated**: {dashboard_data["timestamp"]}
**Monitoring Window**: {dashboard_data["monitoring_window_hours"]} hour(s)
**Metrics Collected**: {dashboard_data["metrics_collected"]:,}

"""

    @staticmethod
    def format_latency_metrics(perf: Dict[str, Any], compliance: Dict[str, Any]) -> str:
        """Format latency metrics subsection.

        Args:
            perf: Performance summary data
            compliance: Target compliance data

        Returns:
            Formatted latency metrics string
        """
        return f"""### **Latency Metrics**
- **P50 Latency**: {perf["latency_p50_ms"]:.2f}ms
- **P95 Latency**: {perf["latency_p95_ms"]:.2f}ms {'[OK]' if compliance["latency_p95_target_met"] else '❌'} (Target: ≤100ms)
- **P99 Latency**: {perf["latency_p99_ms"]:.2f}ms {'[OK]' if compliance["latency_p99_target_met"] else '❌'} (Target: ≤250ms)
"""

    @staticmethod
    def format_throughput_reliability(perf: Dict[str, Any], compliance: Dict[str, Any]) -> str:
        """Format throughput and reliability subsection.

        Args:
            perf: Performance summary data
            compliance: Target compliance data

        Returns:
            Formatted throughput and reliability string
        """
        return f"""### **Throughput & Reliability**
- **Average Throughput**: {perf["throughput_avg_ops_per_sec"]:.2f} ops/sec
- **Error Rate**: {perf["error_rate_avg_percent"]:.2f}% {'[OK]' if compliance["error_rate_target_met"] else '❌'} (Target: ≤1.0%)
"""

    @staticmethod
    def format_resource_usage(perf: Dict[str, Any]) -> str:
        """Format resource usage subsection.

        Args:
            perf: Performance summary data

        Returns:
            Formatted resource usage string
        """
        return f"""### **Resource Usage**
- **Memory Usage**: {perf["memory_usage_avg_mb"]:.2f} MB
- **CPU Usage**: {perf["cpu_usage_avg_percent"]:.2f}%
- **Cache Hit Rate**: {perf["cache_hit_rate_avg_percent"]:.2f}%
"""

    @staticmethod
    def format_performance_summary(perf: Dict[str, Any], compliance: Dict[str, Any]) -> str:
        """Format performance summary section.

        Args:
            perf: Performance summary data
            compliance: Target compliance data

        Returns:
            Formatted performance summary string
        """
        latency = FastMCPPerformanceFormatters.format_latency_metrics(perf, compliance)
        throughput = FastMCPPerformanceFormatters.format_throughput_reliability(perf, compliance)
        resources = FastMCPPerformanceFormatters.format_resource_usage(perf)

        return f"""## **Performance Summary**

{latency}

{throughput}

{resources}

"""

    @staticmethod
    def format_alert_summary(alerts: Dict[str, Any]) -> str:
        """Format alert summary subsection.

        Args:
            alerts: Alerts data containing active alert counts

        Returns:
            Formatted alert summary string
        """
        return f"""## **Active Alerts**

**Total Active**: {alerts["total_active"]}
- **Critical**: {alerts["critical"]} 
- **Warning**: {alerts["warning"]} 

"""

    @staticmethod
    def format_recent_alerts_list(alerts: Dict[str, Any]) -> str:
        """Format recent alerts list subsection.

        Args:
            alerts: Alerts data containing recent alerts

        Returns:
            Formatted recent alerts list string
        """
        if alerts["recent_alerts"]:
            alerts_text = "### **Recent Alerts**\n"
            for alert in alerts["recent_alerts"]:
                severity_emoji = "" if alert["severity"] == "CRITICAL" else ""
                alerts_text += f"- {severity_emoji} **{alert['severity']}**: {alert['message']} ({alert['tool_name']})\n"
        else:
            alerts_text = "### **Recent Alerts**\n[OK] No active alerts\n"
        return alerts_text

    @staticmethod
    def format_alerts_section(alerts: Dict[str, Any]) -> str:
        """Format active alerts section.

        Args:
            alerts: Alerts data containing active alerts and recent alerts

        Returns:
            Formatted alerts section string
        """
        summary = FastMCPPerformanceFormatters.format_alert_summary(alerts)
        recent = FastMCPPerformanceFormatters.format_recent_alerts_list(alerts)
        return summary + recent + "\n"

    @staticmethod
    def format_compliance_section(compliance: Dict[str, Any]) -> str:
        """Format target compliance section.

        Args:
            compliance: Target compliance data

        Returns:
            Formatted compliance section string
        """
        return f"""## **Target Compliance**

- **Latency P95**: {'[OK] PASS' if compliance["latency_p95_target_met"] else '❌ FAIL'} (≤100ms)
- **Latency P99**: {'[OK] PASS' if compliance["latency_p99_target_met"] else '❌ FAIL'} (≤250ms)
- **Error Rate**: {'[OK] PASS' if compliance["error_rate_target_met"] else '❌ FAIL'} (≤1.0%)

"""

    @staticmethod
    def format_features_section() -> str:
        """Format FastMCP features section.

        Returns:
            Formatted features section string
        """
        return """## **FastMCP Features**

- [OK] Real-time performance monitoring
- [OK] Automated alerting system
- [OK] Percentile-based latency tracking
- [OK] Throughput analysis
- [OK] Resource usage monitoring
- [OK] Performance baseline calculation
- [OK] Target compliance validation

---
**FastMCP Performance Monitoring**: Enhanced real-time visibility with automated alerting
"""

    @staticmethod
    def build_complete_dashboard(dashboard_data: Dict[str, Any]) -> str:
        """Build complete dashboard from data components.

        Args:
            dashboard_data: Complete dashboard data

        Returns:
            Formatted complete dashboard string
        """
        perf = dashboard_data["performance_summary"]
        compliance = dashboard_data["target_compliance"]
        alerts = dashboard_data["alerts"]

        status_emoji = FastMCPPerformanceFormatters.get_status_emoji(dashboard_data)

        header = FastMCPPerformanceFormatters.format_dashboard_header(dashboard_data, status_emoji)
        performance_summary = FastMCPPerformanceFormatters.format_performance_summary(
            perf, compliance
        )
        alerts_section = FastMCPPerformanceFormatters.format_alerts_section(alerts)
        compliance_section = FastMCPPerformanceFormatters.format_compliance_section(compliance)
        features_section = FastMCPPerformanceFormatters.format_features_section()

        return header + performance_summary + alerts_section + compliance_section + features_section
