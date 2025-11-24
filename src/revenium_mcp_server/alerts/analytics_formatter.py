"""Analytics report formatting utilities.

This module provides utilities for formatting analytics data into human-readable
reports with charts, tables, and insights.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .analytics_engine import AlertTrendData, AnomalyFrequencyData, TimeRange


class AnalyticsFormatter:
    """Formatter for analytics reports and visualizations."""

    @staticmethod
    def format_anomaly_frequency_report(data: AnomalyFrequencyData, time_range: TimeRange) -> str:
        """Format anomaly frequency analysis into a comprehensive report.

        Args:
            data: Anomaly frequency analysis data
            time_range: Time range for the analysis

        Returns:
            Formatted report string
        """
        report = []

        # Header
        report.append("📊 **Anomaly Frequency Analysis Report**")
        report.append(
            f"📅 **Period**: {time_range.start.strftime('%Y-%m-%d')} to {time_range.end.strftime('%Y-%m-%d')} ({time_range.duration_days:.1f} days)"
        )
        report.append("")

        # Overview
        report.append("## 📈 **Overview**")
        report.append(f"• **Total Anomalies**: {data.total_anomalies:,}")
        report.append(
            f"• **Active**: {data.active_anomalies:,} ({data.get_activation_rate():.1f}%)"
        )
        report.append(
            f"• **Inactive**: {data.inactive_anomalies:,} ({100 - data.get_activation_rate():.1f}%)"
        )
        report.append(
            f"• **Enabled**: {data.enabled_anomalies:,} ({data.get_enablement_rate():.1f}%)"
        )
        report.append(
            f"• **Disabled**: {data.disabled_anomalies:,} ({100 - data.get_enablement_rate():.1f}%)"
        )
        report.append("")

        # Status Distribution
        if data.anomalies_by_status:
            report.append("## 🔄 **Status Distribution**")
            total = sum(data.anomalies_by_status.values())
            for status, count in sorted(
                data.anomalies_by_status.items(), key=lambda x: x[1], reverse=True
            ):
                percentage = (count / total * 100) if total > 0 else 0
                status_emoji = AnalyticsFormatter._get_status_emoji(status)
                bar = AnalyticsFormatter._create_progress_bar(percentage, 20)
                report.append(
                    f"• {status_emoji} **{status.title()}**: {count:,} ({percentage:.1f}%) {bar}"
                )
            report.append("")

        # Team Distribution
        if data.anomalies_by_team:
            report.append("## 👥 **Top Teams by Anomaly Count**")
            total_teams = len(data.anomalies_by_team)
            for i, (team_id, count) in enumerate(data.anomalies_by_team.items(), 1):
                percentage = (count / data.total_anomalies * 100) if data.total_anomalies > 0 else 0
                medal = AnalyticsFormatter._get_ranking_emoji(i)
                report.append(f"{medal} **{team_id}**: {count:,} anomalies ({percentage:.1f}%)")
                if i >= 5:  # Show top 5
                    break
            if total_teams > 5:
                report.append(f"• ... and {total_teams - 5} more teams")
            report.append("")

        # Detection Rule Types
        if data.detection_rule_types:
            report.append("## 🔍 **Detection Rule Types**")
            total_rules = sum(data.detection_rule_types.values())
            for rule_type, count in sorted(
                data.detection_rule_types.items(), key=lambda x: x[1], reverse=True
            ):
                percentage = (count / total_rules * 100) if total_rules > 0 else 0
                rule_emoji = AnalyticsFormatter._get_rule_type_emoji(rule_type)
                report.append(
                    f"• {rule_emoji} **{rule_type.title()}**: {count:,} rules ({percentage:.1f}%)"
                )
            report.append("")

        # Most Common Metrics
        if data.most_common_metrics:
            report.append("## 📏 **Most Monitored Metrics**")
            for i, (metric, count) in enumerate(data.most_common_metrics[:10], 1):
                medal = AnalyticsFormatter._get_ranking_emoji(i)
                report.append(f"{medal} **{metric}**: {count:,} anomalies")
            report.append("")

        # Creation Trend
        if data.creation_trend:
            report.append("## 📅 **Creation Trend**")
            trend_summary = AnalyticsFormatter._analyze_trend_pattern(data.creation_trend)
            report.append(trend_summary)

            # Show recent activity
            recent_days = (
                data.creation_trend[-7:] if len(data.creation_trend) >= 7 else data.creation_trend
            )
            if recent_days:
                report.append("\n**Recent Activity (Last 7 Days):**")
                for day_data in recent_days:
                    date_obj = datetime.fromisoformat(day_data["date"])
                    day_name = date_obj.strftime("%a")
                    count = day_data["count"]
                    bar = AnalyticsFormatter._create_mini_bar(
                        count, max(d["count"] for d in recent_days) if recent_days else 1
                    )
                    report.append(f"• {day_name} {day_data['date']}: {count:,} {bar}")
            report.append("")

        # Health Insights
        report.append("## 💡 **Health Insights**")
        insights = AnalyticsFormatter._generate_anomaly_insights(data)
        for insight in insights:
            report.append(f"• {insight}")
        report.append("")

        # Recommendations
        report.append("## 🎯 **Recommendations**")
        recommendations = AnalyticsFormatter._generate_anomaly_recommendations(data)
        for recommendation in recommendations:
            report.append(f"• {recommendation}")

        return "\n".join(report)

    @staticmethod
    def format_alert_trend_report(
        data: AlertTrendData, time_range: TimeRange, anomaly_id: Optional[str] = None
    ) -> str:
        """Format alert trend analysis into a comprehensive report.

        Args:
            data: Alert trend analysis data
            time_range: Time range for the analysis
            anomaly_id: Specific anomaly ID if filtered

        Returns:
            Formatted report string
        """
        report = []

        # Header
        title = "🚨 **Alert Trend Analysis Report**"
        if anomaly_id:
            title += f" (Anomaly: {anomaly_id})"
        report.append(title)
        report.append(
            f"📅 **Period**: {time_range.start.strftime('%Y-%m-%d %H:%M')} to {time_range.end.strftime('%Y-%m-%d %H:%M')} ({time_range.duration_hours:.1f} hours)"
        )
        report.append("")

        # Overview
        report.append("## 📈 **Overview**")
        report.append(f"• **Total Alerts**: {data.total_alerts:,}")

        if data.resolution_times:
            avg_resolution = data.get_average_resolution_time()
            median_resolution = data.get_median_resolution_time()
            report.append(
                f"• **Average Resolution Time**: {AnalyticsFormatter._format_duration(avg_resolution)}"
            )
            report.append(
                f"• **Median Resolution Time**: {AnalyticsFormatter._format_duration(median_resolution)}"
            )

        alert_rate = (
            data.total_alerts / time_range.duration_hours if time_range.duration_hours > 0 else 0
        )
        report.append(f"• **Alert Rate**: {alert_rate:.2f} alerts/hour")
        report.append("")

        # Severity Distribution
        if data.alerts_by_severity:
            report.append("## ⚠️ **Severity Distribution**")
            total = sum(data.alerts_by_severity.values())
            severity_order = ["critical", "high", "medium", "low", "info"]

            for severity in severity_order:
                if severity in data.alerts_by_severity:
                    count = data.alerts_by_severity[severity]
                    percentage = (count / total * 100) if total > 0 else 0
                    severity_emoji = AnalyticsFormatter._get_severity_emoji(severity)
                    bar = AnalyticsFormatter._create_progress_bar(percentage, 20)
                    report.append(
                        f"• {severity_emoji} **{severity.title()}**: {count:,} ({percentage:.1f}%) {bar}"
                    )

            # Add any other severities not in the standard order
            for severity, count in data.alerts_by_severity.items():
                if severity not in severity_order:
                    percentage = (count / total * 100) if total > 0 else 0
                    report.append(f"• ⚪ **{severity.title()}**: {count:,} ({percentage:.1f}%)")
            report.append("")

        # Status Distribution
        if data.alerts_by_status:
            report.append("## 🔄 **Status Distribution**")
            total = sum(data.alerts_by_status.values())
            for status, count in sorted(
                data.alerts_by_status.items(), key=lambda x: x[1], reverse=True
            ):
                percentage = (count / total * 100) if total > 0 else 0
                status_emoji = AnalyticsFormatter._get_alert_status_emoji(status)
                bar = AnalyticsFormatter._create_progress_bar(percentage, 20)
                report.append(
                    f"• {status_emoji} **{status.title()}**: {count:,} ({percentage:.1f}%) {bar}"
                )
            report.append("")

        # Resolution Time Analysis
        if data.resolution_times:
            report.append("## ⏱️ **Resolution Time Analysis**")
            resolution_stats = AnalyticsFormatter._analyze_resolution_times(data.resolution_times)
            for stat in resolution_stats:
                report.append(f"• {stat}")
            report.append("")

        # Top Triggering Anomalies
        if data.top_triggering_anomalies and not anomaly_id:
            report.append("## 🔥 **Top Triggering Anomalies**")
            for i, anomaly in enumerate(data.top_triggering_anomalies, 1):
                medal = AnalyticsFormatter._get_ranking_emoji(i)
                percentage = (
                    (anomaly["alert_count"] / data.total_alerts * 100)
                    if data.total_alerts > 0
                    else 0
                )
                report.append(f"{medal} **{anomaly['anomaly_name']}** ({anomaly['anomaly_id']})")
                report.append(f"   • {anomaly['alert_count']:,} alerts ({percentage:.1f}%)")
            report.append("")

        # Alert Frequency Pattern
        if data.alert_frequency:
            report.append("## 📊 **Alert Frequency Pattern**")
            frequency_insights = AnalyticsFormatter._analyze_alert_frequency_pattern(
                data.alert_frequency
            )
            for insight in frequency_insights:
                report.append(f"• {insight}")
            report.append("")

        # Insights and Recommendations
        report.append("## 💡 **Insights**")
        insights = AnalyticsFormatter._generate_alert_insights(data, time_range)
        for insight in insights:
            report.append(f"• {insight}")
        report.append("")

        report.append("## 🎯 **Recommendations**")
        recommendations = AnalyticsFormatter._generate_alert_recommendations(data)
        for recommendation in recommendations:
            report.append(f"• {recommendation}")

        return "\n".join(report)

    @staticmethod
    def format_top_alerting_anomalies_report(
        anomalies: List[Dict[str, Any]], time_range: TimeRange
    ) -> str:
        """Format top alerting anomalies into a report.

        Args:
            anomalies: List of top alerting anomalies
            time_range: Time range for the analysis

        Returns:
            Formatted report string
        """
        if not anomalies:
            return "📋 **No alerting anomalies found** in the specified time range."

        report = []

        # Header
        report.append("🔥 **Top Alerting Anomalies Report**")
        report.append(
            f"📅 **Period**: {time_range.start.strftime('%Y-%m-%d')} to {time_range.end.strftime('%Y-%m-%d')} ({time_range.duration_days:.1f} days)"
        )
        report.append("")

        # Summary
        total_alerts = sum(a["alert_count"] for a in anomalies)
        report.append("## 📈 **Summary**")
        report.append(f"• **Top {len(anomalies)} anomalies** generated **{total_alerts:,} alerts**")
        report.append(f"• **Average**: {total_alerts / len(anomalies):.1f} alerts per anomaly")
        report.append("")

        # Detailed breakdown
        report.append("## 🏆 **Detailed Breakdown**")

        for i, anomaly in enumerate(anomalies, 1):
            medal = AnalyticsFormatter._get_ranking_emoji(i)
            percentage = (anomaly["alert_count"] / total_alerts * 100) if total_alerts > 0 else 0

            report.append(f"{medal} **{anomaly['anomaly_name']}**")
            report.append(f"   • **ID**: `{anomaly['anomaly_id']}`")
            report.append(f"   • **Alert Count**: {anomaly['alert_count']:,} ({percentage:.1f}%)")
            report.append(
                f"   • **Most Common Severity**: {AnalyticsFormatter._get_severity_emoji(anomaly['most_common_severity'])} {anomaly['most_common_severity'].title()}"
            )

            if anomaly.get("latest_alert"):
                latest_alert_time = datetime.fromisoformat(
                    anomaly["latest_alert"].replace("Z", "+00:00")
                )
                time_ago = (
                    datetime.now().replace(tzinfo=latest_alert_time.tzinfo) - latest_alert_time
                )
                report.append(
                    f"   • **Latest Alert**: {AnalyticsFormatter._format_time_ago(time_ago)} ago"
                )

            # Severity distribution
            if anomaly.get("severity_distribution"):
                severity_parts = []
                for severity, count in anomaly["severity_distribution"].items():
                    emoji = AnalyticsFormatter._get_severity_emoji(severity)
                    severity_parts.append(f"{emoji}{count}")
                report.append(f"   • **Severity Breakdown**: {' | '.join(severity_parts)}")

            report.append("")

        return "\n".join(report)

    # Helper methods for formatting

    @staticmethod
    def _get_status_emoji(status: str) -> str:
        """Get emoji for anomaly status."""
        # Return empty string - no decorative emojis for status
        return ""

    @staticmethod
    def _get_severity_emoji(severity: str) -> str:
        """Get emoji for alert severity."""
        # Return empty string - no decorative emojis for severity
        return ""

    @staticmethod
    def _get_alert_status_emoji(status: str) -> str:
        """Get emoji for alert status."""
        # Return empty string - no decorative emojis for status
        return ""

    @staticmethod
    def _get_rule_type_emoji(rule_type: str) -> str:
        """Get emoji for detection rule type."""
        # Return empty string - no decorative emojis for rule types
        return ""

    @staticmethod
    def _get_ranking_emoji(rank: int) -> str:
        """Get emoji for ranking position."""
        # Return simple number format - no decorative emojis for rankings
        return f"{rank}."

    @staticmethod
    def _create_progress_bar(percentage: float, width: int = 20) -> str:
        """Create a text-based progress bar."""
        filled = int(percentage / 100 * width)
        bar = "█" * filled + "░" * (width - filled)
        return f"[{bar}]"

    @staticmethod
    def _create_mini_bar(value: int, max_value: int, width: int = 10) -> str:
        """Create a mini bar chart."""
        if max_value == 0:
            return "▁" * width

        filled = int(value / max_value * width) if max_value > 0 else 0
        return "▇" * filled + "▁" * (width - filled)

    @staticmethod
    def _format_duration(hours: float) -> str:
        """Format duration in hours to human-readable format."""
        if hours < 1:
            minutes = int(hours * 60)
            return f"{minutes}m"
        elif hours < 24:
            return f"{hours:.1f}h"
        else:
            days = int(hours / 24)
            remaining_hours = int(hours % 24)
            return f"{days}d {remaining_hours}h"

    @staticmethod
    def _format_time_ago(delta: timedelta) -> str:
        """Format time delta to human-readable 'time ago' format."""
        total_seconds = int(delta.total_seconds())

        if total_seconds < 60:
            return f"{total_seconds}s"
        elif total_seconds < 3600:
            minutes = total_seconds // 60
            return f"{minutes}m"
        elif total_seconds < 86400:
            hours = total_seconds // 3600
            return f"{hours}h"
        else:
            days = total_seconds // 86400
            return f"{days}d"

    @staticmethod
    def _analyze_trend_pattern(trend_data: List[Dict[str, Any]]) -> str:
        """Analyze trend pattern and provide insights."""
        if not trend_data or len(trend_data) < 2:
            return "Insufficient data for trend analysis."

        counts = [day["count"] for day in trend_data]
        total = sum(counts)
        avg_daily = total / len(counts)

        # Calculate trend direction
        recent_avg = sum(counts[-7:]) / min(7, len(counts))  # Last week average
        earlier_avg = sum(counts[:-7]) / max(1, len(counts) - 7) if len(counts) > 7 else avg_daily

        if recent_avg > earlier_avg * 1.2:
            trend = "📈 **Increasing trend** - Recent activity is significantly higher"
        elif recent_avg < earlier_avg * 0.8:
            trend = "📉 **Decreasing trend** - Recent activity is significantly lower"
        else:
            trend = "➡️ **Stable trend** - Activity levels are relatively consistent"

        peak_day = max(trend_data, key=lambda x: x["count"])
        peak_date = datetime.fromisoformat(peak_day["date"]).strftime("%A, %B %d")

        return f"{trend}\n• **Daily Average**: {avg_daily:.1f} anomalies\n• **Peak Day**: {peak_date} ({peak_day['count']} anomalies)"

    @staticmethod
    def _analyze_resolution_times(resolution_times: List[float]) -> List[str]:
        """Analyze resolution time statistics."""
        if not resolution_times:
            return ["No resolution time data available"]

        import statistics

        stats = []

        # Basic statistics
        min_time = min(resolution_times)
        max_time = max(resolution_times)
        avg_time = statistics.mean(resolution_times)
        median_time = statistics.median(resolution_times)

        stats.append(f"**Fastest Resolution**: {AnalyticsFormatter._format_duration(min_time)}")
        stats.append(f"**Slowest Resolution**: {AnalyticsFormatter._format_duration(max_time)}")
        stats.append(f"**Average**: {AnalyticsFormatter._format_duration(avg_time)}")
        stats.append(f"**Median**: {AnalyticsFormatter._format_duration(median_time)}")

        # Percentiles
        if len(resolution_times) >= 4:
            sorted_times = sorted(resolution_times)
            p90 = sorted_times[int(len(sorted_times) * 0.9)]
            p95 = sorted_times[int(len(sorted_times) * 0.95)]
            stats.append(f"**90th Percentile**: {AnalyticsFormatter._format_duration(p90)}")
            stats.append(f"**95th Percentile**: {AnalyticsFormatter._format_duration(p95)}")

        # Performance assessment
        if avg_time <= 1:  # 1 hour
            stats.append("🟢 **Performance**: Excellent - Very fast resolution times")
        elif avg_time <= 4:  # 4 hours
            stats.append("🟡 **Performance**: Good - Reasonable resolution times")
        elif avg_time <= 24:  # 24 hours
            stats.append("🟠 **Performance**: Fair - Consider optimization")
        else:
            stats.append("🔴 **Performance**: Poor - Resolution times need improvement")

        return stats

    @staticmethod
    def _analyze_alert_frequency_pattern(frequency_data: List[Dict[str, Any]]) -> List[str]:
        """Analyze alert frequency patterns."""
        if not frequency_data:
            return ["No frequency data available"]

        insights = []
        counts = [hour["count"] for hour in frequency_data]
        total_alerts = sum(counts)

        if total_alerts == 0:
            return ["No alerts in the analyzed period"]

        # Find peak hours
        max_count = max(counts)
        peak_hours = [i for i, count in enumerate(counts) if count == max_count]

        if peak_hours:
            peak_times = []
            for hour_idx in peak_hours[:3]:  # Show up to 3 peak hours
                timestamp = frequency_data[hour_idx]["timestamp"]
                hour_time = datetime.fromisoformat(timestamp).strftime("%H:%M")
                peak_times.append(hour_time)

            insights.append(f"**Peak Activity**: {', '.join(peak_times)} ({max_count} alerts)")

        # Calculate hourly average
        non_zero_hours = [count for count in counts if count > 0]
        if non_zero_hours:
            avg_when_active = sum(non_zero_hours) / len(non_zero_hours)
            insights.append(f"**Average (Active Hours)**: {avg_when_active:.1f} alerts/hour")

        # Identify quiet periods
        zero_hours = counts.count(0)
        if zero_hours > 0:
            quiet_percentage = (zero_hours / len(counts)) * 100
            insights.append(f"**Quiet Periods**: {quiet_percentage:.1f}% of time with no alerts")

        # Pattern analysis
        if len(counts) >= 24:  # At least 24 hours of data
            # Group by hour of day to find daily patterns
            hourly_patterns = {}
            for i, hour_data in enumerate(frequency_data):
                timestamp = datetime.fromisoformat(hour_data["timestamp"])
                hour_of_day = timestamp.hour
                if hour_of_day not in hourly_patterns:
                    hourly_patterns[hour_of_day] = []
                hourly_patterns[hour_of_day].append(hour_data["count"])

            # Find busiest hour of day
            hourly_averages = {
                hour: sum(counts) / len(counts) for hour, counts in hourly_patterns.items()
            }
            busiest_hour = max(hourly_averages.keys(), key=lambda h: hourly_averages[h])
            insights.append(
                f"**Busiest Hour**: {busiest_hour:02d}:00 (avg {hourly_averages[busiest_hour]:.1f} alerts)"
            )

        return insights

    @staticmethod
    def _generate_anomaly_insights(data: AnomalyFrequencyData) -> List[str]:
        """Generate insights from anomaly frequency data."""
        insights = []

        # Activation rate insights
        activation_rate = data.get_activation_rate()
        if activation_rate >= 80:
            insights.append("🟢 High activation rate indicates well-configured anomalies")
        elif activation_rate >= 60:
            insights.append("🟡 Moderate activation rate - some anomalies may need attention")
        else:
            insights.append("🔴 Low activation rate suggests many inactive anomalies")

        # Enablement insights
        enablement_rate = data.get_enablement_rate()
        if enablement_rate < 90:
            disabled_count = data.total_anomalies - data.enabled_anomalies
            insights.append(f"⚠️ {disabled_count} anomalies are disabled and not monitoring")

        # Rule type diversity
        if len(data.detection_rule_types) == 1:
            insights.append("📊 Consider diversifying detection rule types for better coverage")
        elif len(data.detection_rule_types) >= 3:
            insights.append("✅ Good diversity in detection rule types")

        # Team distribution
        if len(data.anomalies_by_team) == 1:
            insights.append("👥 All anomalies belong to a single team")
        elif len(data.anomalies_by_team) >= 5:
            insights.append("🏢 Anomalies are well-distributed across multiple teams")

        return insights

    @staticmethod
    def _generate_anomaly_recommendations(data: AnomalyFrequencyData) -> List[str]:
        """Generate recommendations from anomaly frequency data."""
        recommendations = []

        # Activation recommendations
        if data.get_activation_rate() < 70:
            recommendations.append("Review and activate inactive anomalies or remove obsolete ones")

        # Enablement recommendations
        if data.get_enablement_rate() < 90:
            recommendations.append(
                "Enable disabled anomalies or document reasons for keeping them disabled"
            )

        # Rule type recommendations
        if "threshold" not in data.detection_rule_types:
            recommendations.append(
                "Consider adding threshold-based rules for immediate value detection"
            )

        if "statistical" not in data.detection_rule_types:
            recommendations.append("Add statistical rules for detecting subtle anomalies")

        # Metric diversity
        if len(data.most_common_metrics) < 5:
            recommendations.append("Expand monitoring to cover more diverse metrics")

        # Creation trend recommendations
        if data.creation_trend:
            recent_activity = sum(day["count"] for day in data.creation_trend[-7:])
            if recent_activity == 0:
                recommendations.append(
                    "No recent anomaly creation - consider reviewing monitoring gaps"
                )
            elif recent_activity > 10:
                recommendations.append(
                    "High recent anomaly creation - ensure quality over quantity"
                )

        return recommendations

    @staticmethod
    def _generate_alert_insights(data: AlertTrendData, time_range: TimeRange) -> List[str]:
        """Generate insights from alert trend data."""
        insights = []

        # Alert volume insights
        alert_rate = (
            data.total_alerts / time_range.duration_hours if time_range.duration_hours > 0 else 0
        )
        if alert_rate > 10:
            insights.append("🔴 Very high alert rate - potential alert fatigue risk")
        elif alert_rate > 5:
            insights.append("🟡 Moderate alert rate - monitor for trends")
        elif alert_rate > 0:
            insights.append("🟢 Reasonable alert rate")
        else:
            insights.append("📭 No alerts in this period")

        # Severity distribution insights
        if data.alerts_by_severity:
            critical_pct = (
                (data.alerts_by_severity.get("critical", 0) / data.total_alerts * 100)
                if data.total_alerts > 0
                else 0
            )
            if critical_pct > 50:
                insights.append("⚠️ High percentage of critical alerts - review thresholds")
            elif critical_pct < 5:
                insights.append("✅ Low critical alert rate indicates good threshold tuning")

        # Resolution time insights
        if data.resolution_times:
            avg_resolution = data.get_average_resolution_time()
            if avg_resolution > 24:
                insights.append("🔴 Long average resolution time impacts service quality")
            elif avg_resolution < 1:
                insights.append("🟢 Excellent resolution times")

        return insights

    @staticmethod
    def _generate_alert_recommendations(data: AlertTrendData) -> List[str]:
        """Generate recommendations from alert trend data."""
        recommendations = []

        # Volume recommendations
        if data.total_alerts > 1000:
            recommendations.append(
                "Consider alert consolidation or threshold adjustment to reduce noise"
            )

        # Severity recommendations
        if data.alerts_by_severity:
            total = sum(data.alerts_by_severity.values())
            critical_pct = (
                (data.alerts_by_severity.get("critical", 0) / total * 100) if total > 0 else 0
            )

            if critical_pct > 30:
                recommendations.append(
                    "Review critical alert thresholds - too many critical alerts"
                )
            elif critical_pct < 2:
                recommendations.append("Ensure critical thresholds are sensitive enough")

        # Resolution time recommendations
        if data.resolution_times:
            avg_resolution = data.get_average_resolution_time()
            if avg_resolution > 4:
                recommendations.append(
                    "Implement automated response procedures to reduce resolution times"
                )

            # Check for wide variance
            import statistics

            if len(data.resolution_times) > 1:
                std_dev = statistics.stdev(data.resolution_times)
                if std_dev > avg_resolution:
                    recommendations.append(
                        "High variance in resolution times - standardize response procedures"
                    )

        # Top triggering anomalies
        if data.top_triggering_anomalies:
            top_anomaly = data.top_triggering_anomalies[0]
            if top_anomaly["alert_count"] > data.total_alerts * 0.3:
                recommendations.append(
                    f"Review '{top_anomaly['anomaly_name']}' - generating too many alerts"
                )

        return recommendations
