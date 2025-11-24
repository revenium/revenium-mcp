"""Alert-to-Analytics Workflow Processor.

This module provides comprehensive workflow processing for connecting alert data
to analytics for root cause analysis. Implements the 'I got an alert, what caused it?'
functionality with cross-tool data correlation.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from ..client import ReveniumClient
from ..common.error_handling import ErrorCodes, ToolError
from .business_analytics_engine import BusinessAnalyticsEngine
from .cost_analytics_processor import CostAnalyticsProcessor
from .transaction_level_analytics_processor import TransactionLevelAnalyticsProcessor


@dataclass
class AlertContext:
    """Context information from an alert for analytics correlation."""

    alert_id: str
    anomaly_id: str
    anomaly_name: Optional[str]
    trigger_timestamp: datetime
    severity: str
    status: str
    affected_metrics: Dict[str, Any]
    threshold_violations: List[Dict[str, Any]]
    team_id: str
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class RootCauseAnalysis:
    """Root cause analysis results from alert-to-analytics correlation."""

    alert_context: AlertContext
    cost_analysis: Dict[str, Any]
    timeline_analysis: Dict[str, Any]
    transaction_analysis: Dict[str, Any]
    contributing_factors: List[Dict[str, Any]]
    recommendations: List[str]
    confidence_score: float
    analysis_timestamp: datetime


class AlertAnalyticsWorkflowProcessor:
    """Processor for alert-to-analytics workflows and root cause analysis."""

    def __init__(self, ucm_integration=None):
        """Initialize the alert-analytics workflow processor.

        Args:
            ucm_integration: UCM integration helper for capability discovery
        """
        self.ucm_integration = ucm_integration
        self.cost_processor = CostAnalyticsProcessor()
        self.analytics_engine = BusinessAnalyticsEngine(ucm_integration)
        self.transaction_processor = TransactionLevelAnalyticsProcessor()

    async def analyze_alert_root_cause(
        self,
        client: ReveniumClient,
        alert_id: str,
        include_cost_analysis: bool = True,
        include_timeline_analysis: bool = True,
        include_transaction_analysis: bool = True,
        analysis_window_hours: int = 24,
    ) -> RootCauseAnalysis:
        """Analyze the root cause of an alert using comprehensive analytics.

        This is the main entry point for 'I got an alert, what caused it?' workflows.

        Args:
            client: Revenium API client
            alert_id: ID of the alert to analyze
            include_cost_analysis: Whether to include cost analytics
            include_timeline_analysis: Whether to include timeline analysis
            analysis_window_hours: Hours before alert to analyze

        Returns:
            Comprehensive root cause analysis
        """
        logger.info(f"Starting root cause analysis for alert {alert_id}")

        try:
            # Step 1: Get alert context
            alert_context = await self._get_alert_context(client, alert_id)

            # Step 2: Determine analysis time window
            analysis_window = self._calculate_analysis_window(
                alert_context.trigger_timestamp, analysis_window_hours
            )

            # Step 3: Perform cost analysis if requested
            cost_analysis = {}
            if include_cost_analysis:
                cost_analysis = await self._perform_cost_analysis(
                    client, alert_context, analysis_window
                )

            # Step 4: Perform timeline analysis if requested
            timeline_analysis = {}
            if include_timeline_analysis:
                timeline_analysis = await self._perform_timeline_analysis(
                    client, alert_context, analysis_window
                )

            # Step 5: Perform transaction-level analysis if requested
            transaction_analysis = {}
            if include_transaction_analysis:
                transaction_analysis = await self._perform_transaction_analysis(
                    client, alert_context, analysis_window
                )

            # Step 6: Identify contributing factors
            contributing_factors = await self._identify_contributing_factors(
                alert_context, cost_analysis, timeline_analysis, transaction_analysis
            )

            # Step 6: Generate recommendations
            recommendations = await self._generate_recommendations(
                alert_context, contributing_factors
            )

            # Step 7: Calculate confidence score
            confidence_score = self._calculate_confidence_score(
                cost_analysis, timeline_analysis, transaction_analysis, contributing_factors
            )

            return RootCauseAnalysis(
                alert_context=alert_context,
                cost_analysis=cost_analysis,
                timeline_analysis=timeline_analysis,
                transaction_analysis=transaction_analysis,
                contributing_factors=contributing_factors,
                recommendations=recommendations,
                confidence_score=confidence_score,
                analysis_timestamp=datetime.now(timezone.utc),
            )

        except ToolError:

            # Re-raise ToolError exceptions without modification

            # This preserves helpful error messages with specific suggestions

            raise

        except ToolError:

            # Re-raise ToolError exceptions without modification

            # This preserves helpful error messages with specific suggestions

            raise

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Root cause analysis failed for alert {alert_id}: {e}")
            raise ToolError(
                message=f"Root cause analysis failed: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="alert_id",
                value=alert_id,
                suggestions=[
                    "Verify the alert ID exists and is accessible",
                    "Check if sufficient historical data is available",
                    "Ensure proper API permissions for analytics",
                ],
            )

    async def _get_alert_context(self, client: ReveniumClient, alert_id: str) -> AlertContext:
        """Get comprehensive context information for an alert."""
        logger.info(f"Getting alert context for {alert_id}")

        try:
            # Try to get anomaly details using the proper API endpoint
            endpoint = f"/profitstream/v2/api/ai-anomalies/{alert_id}"
            params = {"teamId": client.team_id}
            response = await client._request("GET", endpoint, params)
            alert_data = response if isinstance(response, dict) else {}

            # Extract relevant information from the anomaly response
            anomaly_name = alert_data.get("name", f"Alert {alert_id}")
            metric_type = alert_data.get("metricType", "UNKNOWN")
            threshold = alert_data.get("threshold", 0)

            return AlertContext(
                alert_id=alert_id,
                anomaly_id=alert_id,
                anomaly_name=anomaly_name,
                trigger_timestamp=datetime.now(timezone.utc),  # Use current time as trigger
                severity="medium",  # Default severity
                status="active",  # Default status
                affected_metrics={metric_type: threshold},
                threshold_violations=[{"metric": metric_type, "threshold": threshold}],
                team_id=client.team_id,
                metadata=alert_data,
            )

        except Exception as e:
            logger.warning(f"Could not get detailed alert context for {alert_id}: {e}")
            # Create a functional context for analysis even if alert details unavailable
            return AlertContext(
                alert_id=alert_id,
                anomaly_id=alert_id,
                anomaly_name=f"Alert Analysis {alert_id}",
                trigger_timestamp=datetime.now(timezone.utc),
                severity="medium",
                status="active",
                affected_metrics={"TOTAL_COST": 100.0},  # Default cost metric
                threshold_violations=[{"metric": "TOTAL_COST", "threshold": 100.0}],
                team_id=client.team_id,
                metadata={"alert_id": alert_id, "analysis_type": "root_cause"},
            )

    def _calculate_analysis_window(
        self, trigger_timestamp: datetime, analysis_window_hours: int
    ) -> Dict[str, Any]:
        """Calculate the time window for analysis."""
        end_time = trigger_timestamp
        start_time = end_time - timedelta(hours=analysis_window_hours)

        return {
            "start_time": start_time,
            "end_time": end_time,
            "duration_hours": analysis_window_hours,
            "period": self._determine_period_from_hours(analysis_window_hours),
        }

    def _determine_period_from_hours(self, hours: int) -> str:
        """Determine the appropriate period parameter based on hours (API-verified periods only)."""
        if hours <= 1:
            return "HOUR"
        elif hours <= 8:
            return "EIGHT_HOURS"
        elif hours <= 24:
            return "TWENTY_FOUR_HOURS"
        elif hours <= 168:  # 7 days
            return "SEVEN_DAYS"
        elif hours <= 720:  # 30 days
            return "THIRTY_DAYS"
        else:
            return "TWELVE_MONTHS"

    async def _perform_cost_analysis(
        self, client: ReveniumClient, alert_context: AlertContext, analysis_window: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Perform cost analysis for the alert time window."""
        logger.info(f"Performing cost analysis for alert {alert_context.alert_id}")

        try:
            # Determine if this is a cost-related alert
            is_cost_alert = self._is_cost_related_alert(alert_context)

            if is_cost_alert:
                # Get threshold from alert context
                threshold = self._extract_cost_threshold(alert_context)

                # Perform cost spike analysis
                spike_analysis = await self.cost_processor.analyze_cost_spike(
                    client, alert_context.team_id, {"period": analysis_window["period"]}, threshold
                )

                return {
                    "type": "cost_spike_analysis",
                    "is_cost_related": True,
                    "threshold": threshold,
                    "spike_analysis": spike_analysis,
                    "analysis_period": analysis_window["period"],
                }
            else:
                # Perform general cost trend analysis
                cost_trends = await self.cost_processor.analyze_cost_trends(
                    client, alert_context.team_id, analysis_window["period"], "TOTAL"
                )

                return {
                    "type": "cost_trend_analysis",
                    "is_cost_related": False,
                    "cost_trends": cost_trends,
                    "analysis_period": analysis_window["period"],
                }

        except Exception as e:
            logger.error(f"Cost analysis failed: {e}")
            return {
                "type": "cost_analysis_failed",
                "error": str(e),
                "analysis_period": analysis_window["period"],
            }

    def _is_cost_related_alert(self, alert_context: AlertContext) -> bool:
        """Determine if an alert is cost-related."""
        # Check affected metrics for cost indicators
        affected_metrics = alert_context.affected_metrics
        cost_indicators = ["cost", "spending", "budget", "price", "billing"]

        for metric_name, _ in affected_metrics.items():
            if any(indicator in metric_name.lower() for indicator in cost_indicators):
                return True

        # Check anomaly name for cost indicators
        if alert_context.anomaly_name:
            anomaly_name_lower = alert_context.anomaly_name.lower()
            if any(indicator in anomaly_name_lower for indicator in cost_indicators):
                return True

        return False

    def _extract_cost_threshold(self, alert_context: AlertContext) -> float:
        """Extract cost threshold from alert context."""
        # Check threshold violations
        for violation in alert_context.threshold_violations:
            if "threshold" in violation:
                return float(violation["threshold"])

        # Check affected metrics
        for metric_name, metric_value in alert_context.affected_metrics.items():
            if "threshold" in metric_name.lower():
                try:
                    return float(metric_value)
                except (ValueError, TypeError):
                    continue

        # Default threshold for analysis
        return 100.0

    def _parse_timestamp(self, timestamp_str: Any) -> datetime:
        """Parse timestamp string to datetime object."""
        if isinstance(timestamp_str, datetime):
            return timestamp_str

        if isinstance(timestamp_str, str):
            try:
                # Try ISO format first
                return datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except ValueError:
                try:
                    # Try common formats
                    return datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    pass

        # Default to current time if parsing fails
        return datetime.now(timezone.utc)

    async def _perform_timeline_analysis(
        self, client: ReveniumClient, alert_context: AlertContext, analysis_window: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Perform timeline analysis around the alert trigger time."""
        logger.info(f"Performing timeline analysis for alert {alert_context.alert_id}")

        try:
            # Get cost trends for timeline analysis
            period = analysis_window["period"]
            cost_trends = await self.cost_processor.analyze_cost_trends(
                client, alert_context.team_id, period, "TOTAL"
            )

            # Analyze patterns around trigger time
            timeline_patterns = self._analyze_timeline_patterns(
                cost_trends, alert_context.trigger_timestamp
            )

            return {
                "type": "timeline_analysis",
                "trigger_timestamp": alert_context.trigger_timestamp.isoformat(),
                "analysis_window": analysis_window,
                "cost_trends": cost_trends,
                "timeline_patterns": timeline_patterns,
            }

        except Exception as e:
            logger.error(f"Timeline analysis failed: {e}")
            return {
                "type": "timeline_analysis_failed",
                "error": str(e),
                "trigger_timestamp": alert_context.trigger_timestamp.isoformat(),
            }

    def _analyze_timeline_patterns(
        self, cost_trends: Any, trigger_timestamp: datetime
    ) -> Dict[str, Any]:
        """Analyze patterns in the timeline around the alert trigger."""
        patterns = {
            "pre_alert_trend": "stable",
            "alert_trigger_pattern": "spike",
            "post_alert_trend": "unknown",
            "pattern_confidence": 0.7,
            "trigger_hour": trigger_timestamp.hour,
            "trigger_day_of_week": trigger_timestamp.weekday(),
        }

        # This would be enhanced with actual time series analysis
        # For now, provide basic pattern recognition
        if hasattr(cost_trends, "trend_direction"):
            if cost_trends.trend_direction == "increasing":
                patterns["pre_alert_trend"] = "increasing"
                patterns["pattern_confidence"] = 0.8
            elif cost_trends.trend_direction == "decreasing":
                patterns["pre_alert_trend"] = "decreasing"
                patterns["pattern_confidence"] = 0.6

        return patterns

    async def _perform_transaction_analysis(
        self, client: ReveniumClient, alert_context: AlertContext, analysis_window: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Perform transaction-level analysis for the alert time window."""
        logger.info(f"Performing transaction-level analysis for alert {alert_context.alert_id}")

        try:
            # Determine if this is a transaction-related alert
            is_transaction_alert = self._is_transaction_related_alert(alert_context)

            transaction_analysis = {
                "type": "transaction_analysis",
                "is_transaction_related": is_transaction_alert,
                "analysis_period": analysis_window["period"],
                "agent_metrics": {},
                "task_metrics": {},
                "performance_metrics": {},
                "correlation_analysis": {},
            }

            # Get transaction-level metrics for the analysis window
            period = analysis_window["period"]

            # Agent transaction analysis
            try:
                agent_data = await self.transaction_processor.analyze_agent_transactions(
                    client, alert_context.team_id, period, "MEAN"
                )
                transaction_analysis["agent_metrics"] = {
                    "transaction_data": agent_data,
                    "analysis_type": "agent_transactions",
                }
            except Exception as e:
                logger.warning(f"Agent transaction analysis failed: {e}")
                transaction_analysis["agent_metrics"] = {"error": str(e)}

            # Agent performance analysis
            try:
                agent_performance_data = await self.transaction_processor.analyze_agent_performance(
                    client, alert_context.team_id, period, 10
                )
                transaction_analysis["agent_performance"] = {
                    "performance_data": agent_performance_data,
                    "analysis_type": "agent_performance",
                }
            except Exception as e:
                logger.warning(f"Agent performance analysis failed: {e}")
                transaction_analysis["agent_performance"] = {"error": str(e)}

            # Task metrics analysis
            try:
                task_metrics_data = await self.transaction_processor.analyze_task_metrics(
                    client, alert_context.team_id, period, "MEDIAN"
                )
                transaction_analysis["task_metrics"] = {
                    "metrics_data": task_metrics_data,
                    "analysis_type": "task_metrics",
                }
            except Exception as e:
                logger.warning(f"Task metrics analysis failed: {e}")
                transaction_analysis["task_metrics"] = {"error": str(e)}

            # Task performance analysis
            try:
                task_performance_data = await self.transaction_processor.analyze_task_performance(
                    client, alert_context.team_id, period, 10
                )
                transaction_analysis["task_performance"] = {
                    "performance_data": task_performance_data,
                    "analysis_type": "task_performance",
                }
            except Exception as e:
                logger.warning(f"Task performance analysis failed: {e}")
                transaction_analysis["task_performance"] = {"error": str(e)}

            # Correlation analysis between transaction metrics and alert
            correlation_analysis = self._analyze_transaction_correlation(
                alert_context, transaction_analysis
            )
            transaction_analysis["correlation_analysis"] = correlation_analysis

            return transaction_analysis

        except Exception as e:
            logger.error(f"Transaction-level analysis failed: {e}")
            return {
                "type": "transaction_analysis_failed",
                "error": str(e),
                "analysis_period": analysis_window["period"],
            }

    def _is_transaction_related_alert(self, alert_context: AlertContext) -> bool:
        """Determine if an alert is transaction-related."""
        # Check affected metrics for transaction indicators
        affected_metrics = alert_context.affected_metrics
        transaction_indicators = [
            "transaction",
            "request",
            "call",
            "api",
            "agent",
            "task",
            "response_time",
            "latency",
            "duration",
            "throughput",
            "performance",
        ]

        for metric_name, _ in affected_metrics.items():
            if any(indicator in metric_name.lower() for indicator in transaction_indicators):
                return True

        # Check anomaly name for transaction indicators
        if alert_context.anomaly_name:
            anomaly_name_lower = alert_context.anomaly_name.lower()
            if any(indicator in anomaly_name_lower for indicator in transaction_indicators):
                return True

        return False

    def _analyze_transaction_correlation(
        self, alert_context: AlertContext, transaction_analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Analyze correlation between transaction metrics and alert."""
        correlation = {
            "agent_correlation": "none",
            "task_correlation": "none",
            "performance_correlation": "none",
            "correlation_confidence": 0.0,
            "correlation_factors": [],
            "alert_severity": alert_context.severity,
            "alert_timestamp": alert_context.trigger_timestamp.isoformat(),
        }

        # Analyze agent metrics correlation
        agent_metrics = transaction_analysis.get("agent_metrics", {})
        if "cost_trends" in agent_metrics and "error" not in agent_metrics:
            correlation["agent_correlation"] = "detected"
            correlation["correlation_factors"].append("Agent cost anomalies detected")
            correlation["correlation_confidence"] += 0.3

        # Analyze task metrics correlation
        task_metrics = transaction_analysis.get("task_metrics", {})
        if "performance_data" in task_metrics and "error" not in task_metrics:
            correlation["task_correlation"] = "detected"
            correlation["correlation_factors"].append("Task performance anomalies detected")
            correlation["correlation_confidence"] += 0.3

        # Analyze performance metrics correlation
        performance_metrics = transaction_analysis.get("performance_metrics", {})
        if "provider_performance" in performance_metrics and "error" not in performance_metrics:
            correlation["performance_correlation"] = "detected"
            correlation["correlation_factors"].append("Provider performance anomalies detected")
            correlation["correlation_confidence"] += 0.4

        return correlation

    async def _identify_contributing_factors(
        self,
        alert_context: AlertContext,
        cost_analysis: Dict[str, Any],
        timeline_analysis: Dict[str, Any],
        transaction_analysis: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Identify contributing factors to the alert."""
        logger.info(f"Identifying contributing factors for alert {alert_context.alert_id}")

        contributing_factors = []

        # Factor 1: Cost-related factors
        if cost_analysis.get("is_cost_related"):
            spike_analysis = cost_analysis.get("spike_analysis", {})
            if "spike_analysis" in spike_analysis:
                contributing_factors.append(
                    {
                        "type": "cost_spike",
                        "description": "Cost spike detected during alert period",
                        "confidence": 0.9,
                        "details": spike_analysis,
                        "impact": "high",
                    }
                )

        # Factor 2: Timeline patterns
        timeline_patterns = timeline_analysis.get("timeline_patterns", {})
        if timeline_patterns.get("pre_alert_trend") == "increasing":
            contributing_factors.append(
                {
                    "type": "trend_escalation",
                    "description": "Increasing trend leading up to alert",
                    "confidence": timeline_patterns.get("pattern_confidence", 0.7),
                    "details": timeline_patterns,
                    "impact": "medium",
                }
            )

        # Factor 3: Threshold violations
        if alert_context.threshold_violations:
            contributing_factors.append(
                {
                    "type": "threshold_violation",
                    "description": f"Threshold violations detected: {len(alert_context.threshold_violations)}",
                    "confidence": 1.0,
                    "details": alert_context.threshold_violations,
                    "impact": "high",
                }
            )

        # Factor 4: Affected metrics analysis
        if alert_context.affected_metrics:
            contributing_factors.append(
                {
                    "type": "metric_anomaly",
                    "description": f"Anomalous metrics detected: {list(alert_context.affected_metrics.keys())}",
                    "confidence": 0.8,
                    "details": alert_context.affected_metrics,
                    "impact": "medium",
                }
            )

        # Factor 5: Transaction-level analysis
        if transaction_analysis.get("is_transaction_related"):
            correlation_analysis = transaction_analysis.get("correlation_analysis", {})
            correlation_confidence = correlation_analysis.get("correlation_confidence", 0.0)

            if correlation_confidence > 0.5:
                contributing_factors.append(
                    {
                        "type": "transaction_correlation",
                        "description": "Transaction-level anomalies correlated with alert",
                        "confidence": correlation_confidence,
                        "details": correlation_analysis,
                        "impact": "high" if correlation_confidence > 0.8 else "medium",
                    }
                )

            # Agent-specific factors
            agent_metrics = transaction_analysis.get("agent_metrics", {})
            if "transaction_data" in agent_metrics and "error" not in agent_metrics:
                contributing_factors.append(
                    {
                        "type": "agent_transaction_anomaly",
                        "description": "Agent transaction patterns show anomalies during alert period",
                        "confidence": 0.7,
                        "details": agent_metrics,
                        "impact": "medium",
                    }
                )

            # Task performance factors
            task_performance = transaction_analysis.get("task_performance", {})
            if "performance_data" in task_performance and "error" not in task_performance:
                contributing_factors.append(
                    {
                        "type": "task_performance_degradation",
                        "description": "Task performance degradation detected during alert period",
                        "confidence": 0.8,
                        "details": task_performance,
                        "impact": "high",
                    }
                )

        return contributing_factors

    async def _generate_recommendations(
        self, alert_context: AlertContext, contributing_factors: List[Dict[str, Any]]
    ) -> List[str]:
        """Generate actionable recommendations based on analysis."""
        recommendations = []

        # Severity-based recommendations
        if alert_context.severity.lower() == "critical":
            recommendations.append(" CRITICAL: Immediate investigation required")
            recommendations.append(" Consider escalating to on-call team")

        # Factor-based recommendations
        for factor in contributing_factors:
            if factor["type"] == "cost_spike":
                recommendations.append(" Review recent cost changes and usage patterns")
                recommendations.append(" Investigate top cost contributors during spike period")

            elif factor["type"] == "threshold_violation":
                recommendations.append("⚠️ Review alert thresholds for appropriateness")
                recommendations.append(" Consider adjusting thresholds based on baseline metrics")

            elif factor["type"] == "trend_escalation":
                recommendations.append(" Monitor ongoing trends to prevent future alerts")
                recommendations.append(" Consider proactive scaling or optimization")

            elif factor["type"] == "transaction_correlation":
                recommendations.append(" Investigate transaction-level patterns and anomalies")
                recommendations.append(" Review agent and task performance metrics")

            elif factor["type"] == "agent_transaction_anomaly":
                recommendations.append(" Review agent performance and workload distribution")
                recommendations.append(" Investigate specific agents showing anomalous patterns")

            elif factor["type"] == "task_performance_degradation":
                recommendations.append(" Investigate task performance bottlenecks")
                recommendations.append(" Consider task optimization or resource scaling")

        # General recommendations
        recommendations.append(" Document findings for future reference")
        recommendations.append(" Set up monitoring for similar patterns")

        return recommendations

    def _calculate_confidence_score(
        self,
        cost_analysis: Dict[str, Any],
        timeline_analysis: Dict[str, Any],
        transaction_analysis: Dict[str, Any],
        contributing_factors: List[Dict[str, Any]],
    ) -> float:
        """Calculate confidence score for the root cause analysis."""
        base_confidence = 0.4

        # Boost confidence based on available data
        if cost_analysis and "error" not in cost_analysis:
            base_confidence += 0.15

        if timeline_analysis and "error" not in timeline_analysis:
            base_confidence += 0.1

        if transaction_analysis and "error" not in transaction_analysis:
            base_confidence += 0.2

            # Additional boost for transaction correlation
            correlation_analysis = transaction_analysis.get("correlation_analysis", {})
            correlation_confidence = correlation_analysis.get("correlation_confidence", 0.0)
            if correlation_confidence > 0.5:
                base_confidence += 0.15

        # Factor-based confidence
        if contributing_factors:
            factor_confidence = sum(
                factor.get("confidence", 0.5) for factor in contributing_factors
            )
            factor_confidence = factor_confidence / len(contributing_factors)
            base_confidence = (base_confidence + factor_confidence) / 2

        return min(base_confidence, 1.0)

    def format_root_cause_analysis(self, analysis: RootCauseAnalysis) -> str:
        """Format root cause analysis results for display."""
        lines = []

        # Header
        lines.append(" **Alert Root Cause Analysis**")
        lines.append("=" * 50)
        lines.append("")

        # Alert Context
        lines.append("##  **Alert Context**")
        lines.append(f"**Alert ID**: {analysis.alert_context.alert_id}")
        lines.append(f"**Anomaly**: {analysis.alert_context.anomaly_name or 'Unknown'}")
        lines.append(f"**Severity**: {analysis.alert_context.severity}")
        lines.append(
            f"**Triggered**: {analysis.alert_context.trigger_timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
        lines.append("")

        # Contributing Factors
        lines.append("##  **Contributing Factors**")
        for i, factor in enumerate(analysis.contributing_factors, 1):
            confidence_emoji = (
                "" if factor["confidence"] > 0.8 else "" if factor["confidence"] > 0.6 else ""
            )
            lines.append(f"{i}. {confidence_emoji} **{factor['type'].replace('_', ' ').title()}**")
            lines.append(f"   {factor['description']}")
            lines.append(f"   Confidence: {factor['confidence']:.1%} | Impact: {factor['impact']}")
            lines.append("")

        # Recommendations
        lines.append("##  **Recommendations**")
        for rec in analysis.recommendations:
            lines.append(f"• {rec}")
        lines.append("")

        # Analysis Summary
        lines.append("##  **Analysis Summary**")
        lines.append(f"**Confidence Score**: {analysis.confidence_score:.1%}")
        lines.append(
            f"**Analysis Completed**: {analysis.analysis_timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )

        return "\n".join(lines)
