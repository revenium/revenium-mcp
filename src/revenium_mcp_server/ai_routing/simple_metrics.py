"""Simplified metrics collection for AI routing POC validation.

This module provides basic metrics collection focused on functionality validation
and performance baselines. Complex A/B testing will be added in Phase 2.
"""

import json
import statistics
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import uuid4

from loguru import logger

from .models import RoutingMetrics

if TYPE_CHECKING:
    from .models import RoutingResult


class SimpleMetricsCollector:
    """Simplified metrics collector focused on POC validation needs.

    Collects basic functionality and performance metrics without complex
    A/B testing infrastructure that requires real AI integration.
    """

    def __init__(self, session_id: Optional[str] = None):
        """Initialize simple metrics collector.

        Args:
            session_id: Optional session identifier for tracking
        """
        self.session_id = session_id or str(uuid4())
        self.metrics: List[RoutingMetrics] = []
        self.start_time = datetime.now()

        logger.info(f"Simple metrics collector initialized with session: " f"{self.session_id}")

    def record_routing(self, query: str, result: "RoutingResult", response_time_ms: float) -> None:
        """Record metrics for any routing operation.

        Args:
            query: Original query text
            result: Routing result
            response_time_ms: Time taken for routing operation
        """
        metrics = self._create_routing_metrics(query, result, response_time_ms)
        self.metrics.append(metrics)
        self._log_recorded_metrics(query, result)

    def _create_routing_metrics(
        self, query: str, result: "RoutingResult", response_time_ms: float
    ) -> RoutingMetrics:
        """Create routing metrics object."""
        return RoutingMetrics(
            query=query,
            tool_selected=result.tool_name,
            action_selected=result.action,
            parameters_extracted=result.parameters.parameters,
            routing_method=result.routing_method,
            response_time_ms=response_time_ms,
            success=result.is_successful(),
            confidence_score=result.confidence,
            timestamp=datetime.now(),
            session_id=self.session_id,
        )

    def _log_recorded_metrics(self, query: str, result: "RoutingResult") -> None:
        """Log recorded metrics for debugging."""
        method_name = result.routing_method.value
        query_preview = query[:50]
        logger.debug(f"Recorded {method_name} routing metrics for query: " f"{query_preview}...")

    def get_basic_summary(self) -> Dict[str, Any]:
        """Generate basic metrics summary for POC validation.

        Returns:
            Dictionary containing basic performance and functionality metrics
        """
        if not self.metrics:
            return {"error": "No metrics collected yet"}

        return {
            "session_id": self.session_id,
            "collection_period": self._get_collection_period(),
            "basic_metrics": self._get_basic_metrics(),
            "performance_metrics": self._get_performance_metrics(),
            "routing_methods": self._get_routing_method_counts(),
            "validation_status": self._get_validation_status(),
        }

    def _get_collection_period(self) -> Dict[str, Any]:
        """Get collection period information."""
        end_time = datetime.now()
        duration_seconds = (end_time - self.start_time).total_seconds()
        return {
            "start_time": self.start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "duration_minutes": duration_seconds / 60,
        }

    def _get_basic_metrics(self) -> Dict[str, Any]:
        """Get basic query metrics."""
        total_queries = len(self.metrics)
        successful_queries = [m for m in self.metrics if m.success]

        success_rate = 0
        if total_queries > 0:
            success_rate = len(successful_queries) / total_queries

        return {
            "total_queries": total_queries,
            "successful_queries": len(successful_queries),
            "failed_queries": total_queries - len(successful_queries),
            "success_rate": success_rate,
        }

    def _get_performance_metrics(self) -> Dict[str, Any]:
        """Get performance metrics."""
        response_times = [m.response_time_ms for m in self.metrics]

        if not response_times:
            return {
                "avg_response_time_ms": 0,
                "min_response_time_ms": 0,
                "max_response_time_ms": 0,
                "p95_response_time_ms": 0,
            }

        return {
            "avg_response_time_ms": statistics.mean(response_times),
            "min_response_time_ms": min(response_times),
            "max_response_time_ms": max(response_times),
            "p95_response_time_ms": self._calculate_percentile(response_times, 95),
        }

    def _get_routing_method_counts(self) -> Dict[str, int]:
        """Get routing method breakdown."""
        method_counts = {}
        for metric in self.metrics:
            method = metric.routing_method.value
            method_counts[method] = method_counts.get(method, 0) + 1
        return method_counts

    def _calculate_percentile(self, values: List[float], percentile: int) -> float:
        """Calculate percentile value from a list of numbers."""
        if not values:
            return 0.0

        sorted_values = sorted(values)
        index = (percentile / 100) * (len(sorted_values) - 1)

        if index.is_integer():
            return sorted_values[int(index)]

        lower_index = int(index)
        upper_index = lower_index + 1
        weight = index - lower_index
        lower_value = sorted_values[lower_index]
        upper_value = sorted_values[upper_index]
        return lower_value * (1 - weight) + upper_value * weight

    def _get_validation_status(self) -> Dict[str, Any]:
        """Get validation status for POC requirements."""
        if not self.metrics:
            return {"status": "no_data"}

        response_times = [m.response_time_ms for m in self.metrics]
        success_rate = self._calculate_success_rate()
        avg_response_time = statistics.mean(response_times)
        p95_response_time = self._calculate_percentile(response_times, 95)

        validations = self._create_validation_criteria(
            success_rate, avg_response_time, p95_response_time
        )

        all_passed = all(v["passed"] for v in validations.values())

        return {
            "overall_status": "PASSED" if all_passed else "FAILED",
            "validations": validations,
            "recommendations": self._generate_simple_recommendations(),
        }

    def _calculate_success_rate(self) -> float:
        """Calculate success rate from metrics."""
        if not self.metrics:
            return 0.0
        return sum(1 for m in self.metrics if m.success) / len(self.metrics)

    def _create_validation_criteria(
        self, success_rate: float, avg_response_time: float, p95_response_time: float
    ) -> Dict[str, Dict[str, Any]]:
        """Create validation criteria dictionary."""
        return {
            "success_rate_target": {
                "target": 0.95,  # 95% success rate
                "actual": success_rate,
                "passed": success_rate >= 0.95,
            },
            "avg_response_time_target": {
                "target": 50.0,  # <50ms average
                "actual": avg_response_time,
                "passed": avg_response_time < 50.0,
            },
            "p95_response_time_target": {
                "target": 100.0,  # <100ms 95th percentile
                "actual": p95_response_time,
                "passed": p95_response_time < 100.0,
            },
        }

    def _generate_simple_recommendations(self) -> List[str]:
        """Generate simple recommendations based on collected metrics."""
        if not self.metrics:
            return ["No metrics collected - unable to generate recommendations"]

        recommendations = []
        recommendations.extend(self._check_performance_recommendations())
        recommendations.extend(self._check_success_rate_recommendations())
        recommendations.extend(self._check_fallback_rate_recommendations())

        if not recommendations:
            recommendations.append("All metrics meet POC validation targets")

        return recommendations

    def _check_performance_recommendations(self) -> List[str]:
        """Check performance-related recommendations."""
        response_times = [m.response_time_ms for m in self.metrics]
        avg_time = statistics.mean(response_times)

        recommendations = []
        if avg_time > 50:
            recommendations.append(
                f"Average response time ({avg_time:.2f}ms) exceeds " f"target (<50ms)"
            )
        return recommendations

    def _check_success_rate_recommendations(self) -> List[str]:
        """Check success rate recommendations."""
        success_rate = self._calculate_success_rate()
        recommendations = []

        if success_rate < 0.95:
            recommendations.append(f"Success rate ({success_rate:.1%}) below target (95%)")
        return recommendations

    def _check_fallback_rate_recommendations(self) -> List[str]:
        """Check fallback rate recommendations."""
        method_counts = self._get_routing_method_counts()
        recommendations = []

        if "ai" in method_counts and "fallback" in method_counts:
            fallback_rate = method_counts["fallback"] / len(self.metrics)
            if fallback_rate > 0.1:
                recommendations.append(
                    f"High fallback rate ({fallback_rate:.1%}) indicates " f"AI reliability issues"
                )
        return recommendations

    def get_comparison_report(self) -> Dict[str, Any]:
        """Generate comprehensive A/B testing comparison report.

        Returns:
            Dictionary containing detailed comparison metrics
        """
        if not self.metrics:
            return {"error": "No metrics collected yet"}

        ai_metrics = self._filter_metrics_by_method("ai")
        rule_metrics = self._filter_metrics_by_method("rule_based")
        fallback_metrics = self._filter_metrics_by_method("fallback")

        return {
            "session_id": self.session_id,
            "collection_period": self._get_collection_period(),
            "summary": self._get_routing_summary(ai_metrics, rule_metrics, fallback_metrics),
            "ai_routing": self._calculate_method_metrics(ai_metrics),
            "rule_based_routing": self._calculate_method_metrics(rule_metrics),
            "fallback_routing": self._calculate_method_metrics(fallback_metrics),
            "comparative_analysis": self._generate_comparative_analysis(ai_metrics, rule_metrics),
            "recommendations": self._generate_comprehensive_recommendations(
                ai_metrics, rule_metrics, fallback_metrics
            ),
        }

    def _filter_metrics_by_method(self, method: str) -> List[RoutingMetrics]:
        """Filter metrics by routing method."""
        return [m for m in self.metrics if m.routing_method.value.lower() == method.lower()]

    def _get_routing_summary(
        self,
        ai_metrics: List[RoutingMetrics],
        rule_metrics: List[RoutingMetrics],
        fallback_metrics: List[RoutingMetrics],
    ) -> Dict[str, Any]:
        """Get routing method summary."""
        total_queries = len(self.metrics)
        if total_queries == 0:
            return {
                "total_queries": 0,
                "ai_queries": 0,
                "rule_based_queries": 0,
                "fallback_queries": 0,
                "ai_usage_rate": 0,
                "fallback_rate": 0,
            }

        return {
            "total_queries": total_queries,
            "ai_queries": len(ai_metrics),
            "rule_based_queries": len(rule_metrics),
            "fallback_queries": len(fallback_metrics),
            "ai_usage_rate": len(ai_metrics) / total_queries,
            "fallback_rate": len(fallback_metrics) / total_queries,
        }

    def _calculate_method_metrics(self, metrics: List[RoutingMetrics]) -> Dict[str, Any]:
        """Calculate metrics for a specific routing method."""
        if not metrics:
            return {
                "total_queries": 0,
                "success_rate": 0.0,
                "avg_response_time_ms": 0.0,
                "median_response_time_ms": 0.0,
                "p95_response_time_ms": 0.0,
                "avg_confidence": 0.0,
                "parameter_extraction_rate": 0.0,
            }

        response_times = [m.response_time_ms for m in metrics]
        confidence_scores = [m.confidence_score for m in metrics if m.confidence_score is not None]
        successful_queries = [m for m in metrics if m.success]
        queries_with_parameters = [m for m in metrics if m.parameters_extracted]

        return {
            "total_queries": len(metrics),
            "success_rate": len(successful_queries) / len(metrics),
            "avg_response_time_ms": statistics.mean(response_times),
            "median_response_time_ms": statistics.median(response_times),
            "p95_response_time_ms": self._calculate_percentile(response_times, 95),
            "avg_confidence": (statistics.mean(confidence_scores) if confidence_scores else 0.0),
            "parameter_extraction_rate": len(queries_with_parameters) / len(metrics),
        }

    def _generate_comparative_analysis(
        self, ai_metrics: List[RoutingMetrics], rule_metrics: List[RoutingMetrics]
    ) -> Dict[str, Any]:
        """Generate comparative analysis between AI and rule-based routing."""
        if not ai_metrics or not rule_metrics:
            return {"note": "Insufficient data for comparison"}

        ai_success_rate = sum(1 for m in ai_metrics if m.success) / len(ai_metrics)
        rule_success_rate = sum(1 for m in rule_metrics if m.success) / len(rule_metrics)

        ai_avg_time = statistics.mean([m.response_time_ms for m in ai_metrics])
        rule_avg_time = statistics.mean([m.response_time_ms for m in rule_metrics])

        return self._create_comparison_metrics(
            ai_success_rate, rule_success_rate, ai_avg_time, rule_avg_time
        )

    def _create_comparison_metrics(
        self,
        ai_success_rate: float,
        rule_success_rate: float,
        ai_avg_time: float,
        rule_avg_time: float,
    ) -> Dict[str, Any]:
        """Create comparison metrics dictionary."""
        success_diff_pct = 0
        if rule_success_rate > 0:
            success_diff_pct = (ai_success_rate - rule_success_rate) / rule_success_rate * 100

        perf_improvement_pct = 0
        if rule_avg_time > 0:
            perf_improvement_pct = (rule_avg_time - ai_avg_time) / rule_avg_time * 100

        return {
            "success_rate_comparison": {
                "ai_advantage": ai_success_rate - rule_success_rate,
                "ai_better": ai_success_rate > rule_success_rate,
                "difference_percentage": success_diff_pct,
            },
            "performance_comparison": {
                "ai_faster": ai_avg_time < rule_avg_time,
                "time_difference_ms": ai_avg_time - rule_avg_time,
                "performance_improvement_percentage": perf_improvement_pct,
            },
        }

    def _generate_comprehensive_recommendations(
        self,
        ai_metrics: List[RoutingMetrics],
        rule_metrics: List[RoutingMetrics],
        fallback_metrics: List[RoutingMetrics],
    ) -> List[str]:
        """Generate comprehensive recommendations based on collected metrics."""
        recommendations = []
        total_metrics = len(self.metrics)
        fallback_rate = len(fallback_metrics) / total_metrics if total_metrics > 0 else 0

        recommendations.extend(self._check_fallback_rate_issues(fallback_rate))
        recommendations.extend(self._check_performance_comparison(ai_metrics, rule_metrics))
        recommendations.extend(self._check_ai_success_rate(ai_metrics))

        return recommendations

    def _check_fallback_rate_issues(self, fallback_rate: float) -> List[str]:
        """Check for high fallback rate issues."""
        recommendations = []
        if fallback_rate > 0.1:  # More than 10% fallback
            recommendations.append(
                f"High fallback rate ({fallback_rate:.1%}) indicates AI routing "
                f"reliability issues. Consider improving AI service stability or "
                f"adjusting circuit breaker settings."
            )
        return recommendations

    def _check_performance_comparison(
        self, ai_metrics: List[RoutingMetrics], rule_metrics: List[RoutingMetrics]
    ) -> List[str]:
        """Check performance comparison recommendations."""
        recommendations = []
        if not ai_metrics or not rule_metrics:
            return recommendations

        ai_avg_time = statistics.mean([m.response_time_ms for m in ai_metrics])
        rule_avg_time = statistics.mean([m.response_time_ms for m in rule_metrics])

        if ai_avg_time > rule_avg_time * 2:  # AI is significantly slower
            recommendations.append(
                f"AI routing is {ai_avg_time/rule_avg_time:.1f}x slower than "
                f"rule-based routing. Consider optimizing AI client configuration "
                f"or caching strategies."
            )
        elif ai_avg_time < rule_avg_time * 0.8:  # AI is significantly faster
            recommendations.append(
                "AI routing shows better performance than rule-based routing. "
                "Consider expanding AI routing to more tools."
            )
        return recommendations

    def _check_ai_success_rate(self, ai_metrics: List[RoutingMetrics]) -> List[str]:
        """Check AI success rate recommendations."""
        recommendations = []
        if ai_metrics:
            ai_success_rate = sum(1 for m in ai_metrics if m.success) / len(ai_metrics)
            if ai_success_rate < 0.9:  # Less than 90% success
                recommendations.append(
                    f"AI routing success rate ({ai_success_rate:.1%}) is below "
                    f"target. Review AI prompts and response parsing logic."
                )
        return recommendations

    def export_metrics(self, format: str = "json") -> str:
        """Export collected metrics in specified format.

        Args:
            format: Export format ("json" or "csv")

        Returns:
            Formatted metrics data
        """
        if format.lower() == "json":
            return json.dumps([m.__dict__ for m in self.metrics], indent=2, default=str)
        elif format.lower() == "csv":
            return self._export_csv_format()
        else:
            raise ValueError(f"Unsupported export format: {format}")

    def _export_csv_format(self) -> str:
        """Export metrics in CSV format."""
        if not self.metrics:
            return "No metrics to export"

        import csv
        import io

        output = io.StringIO()
        if self.metrics:
            fieldnames = [
                "query",
                "tool_selected",
                "action_selected",
                "routing_method",
                "response_time_ms",
                "success",
                "confidence_score",
                "timestamp",
                "session_id",
            ]
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            for metric in self.metrics:
                row = {
                    "query": metric.query,
                    "tool_selected": metric.tool_selected,
                    "action_selected": metric.action_selected,
                    "routing_method": metric.routing_method.value,
                    "response_time_ms": metric.response_time_ms,
                    "success": metric.success,
                    "confidence_score": metric.confidence_score,
                    "timestamp": metric.timestamp.isoformat(),
                    "session_id": metric.session_id,
                }
                writer.writerow(row)

        return output.getvalue()

    def export_simple_metrics(self, format: str = "json") -> str:
        """Export basic metrics in specified format.

        Args:
            format: Export format ("json" only for now)

        Returns:
            Formatted metrics data
        """
        if format.lower() == "json":
            return json.dumps(self.get_basic_summary(), indent=2)
        else:
            raise ValueError(f"Unsupported export format: {format}")

    def clear_metrics(self) -> None:
        """Clear all collected metrics."""
        self.metrics.clear()
        self.start_time = datetime.now()
        logger.info(f"Cleared metrics for session: {self.session_id}")


# Backward compatibility alias
MetricsCollector = SimpleMetricsCollector
