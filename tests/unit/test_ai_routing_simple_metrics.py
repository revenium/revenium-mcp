"""Unit tests for ai_routing.simple_metrics module.

Tests SimpleMetricsCollector: recording routing metrics, generating summaries,
comparison reports, percentile calculations, export formats, and recommendations.
"""

import json

import pytest

from src.revenium_mcp_server.ai_routing.models import (
    ExtractedParameters,
    RoutingMethod,
    RoutingResult,
    RoutingStatus,
)
from src.revenium_mcp_server.ai_routing.simple_metrics import (
    SimpleMetricsCollector,
)


def _make_result(
    tool="products",
    action="list",
    method=RoutingMethod.RULE_BASED,
    status=RoutingStatus.SUCCESS,
    confidence=0.9,
):
    """Create a RoutingResult for testing."""
    return RoutingResult(
        tool_name=tool,
        action=action,
        parameters=ExtractedParameters(parameters={"page": 0}),
        confidence=confidence,
        routing_method=method,
        status=status,
    )


@pytest.fixture
def collector():
    return SimpleMetricsCollector(session_id="test-session")


class TestRecordRouting:
    """Tests for record_routing method."""

    def test_records_single_metric(self, collector):
        result = _make_result()
        collector.record_routing("list products", result, 10.0)
        assert len(collector.metrics) == 1

    def test_recorded_metric_has_correct_fields(self, collector):
        result = _make_result(tool="alerts", action="list")
        collector.record_routing("show alerts", result, 15.5)

        m = collector.metrics[0]
        assert m.query == "show alerts"
        assert m.tool_selected == "alerts"
        assert m.action_selected == "list"
        assert m.response_time_ms == 15.5
        assert m.session_id == "test-session"


class TestBasicSummary:
    """Tests for get_basic_summary method."""

    def test_empty_metrics_returns_error(self, collector):
        summary = collector.get_basic_summary()
        assert "error" in summary

    def test_summary_structure(self, collector):
        collector.record_routing("q1", _make_result(), 10.0)
        collector.record_routing("q2", _make_result(), 20.0)

        summary = collector.get_basic_summary()
        assert summary["session_id"] == "test-session"
        assert "basic_metrics" in summary
        assert "performance_metrics" in summary
        assert "routing_methods" in summary
        assert "validation_status" in summary

    def test_basic_metrics_counts(self, collector):
        collector.record_routing("q1", _make_result(), 5.0)
        collector.record_routing(
            "q2", _make_result(status=RoutingStatus.FAILED, tool=""), 5.0
        )

        summary = collector.get_basic_summary()
        bm = summary["basic_metrics"]
        assert bm["total_queries"] == 2
        assert bm["successful_queries"] == 1
        assert bm["failed_queries"] == 1
        assert bm["success_rate"] == 0.5

    def test_performance_metrics(self, collector):
        collector.record_routing("q1", _make_result(), 10.0)
        collector.record_routing("q2", _make_result(), 30.0)

        summary = collector.get_basic_summary()
        pm = summary["performance_metrics"]
        assert pm["avg_response_time_ms"] == 20.0
        assert pm["min_response_time_ms"] == 10.0
        assert pm["max_response_time_ms"] == 30.0

    def test_routing_method_counts(self, collector):
        collector.record_routing("q1", _make_result(method=RoutingMethod.RULE_BASED), 5.0)
        collector.record_routing("q2", _make_result(method=RoutingMethod.AI), 5.0)

        summary = collector.get_basic_summary()
        methods = summary["routing_methods"]
        assert methods["rule_based"] == 1
        assert methods["ai"] == 1


class TestValidationStatus:
    """Tests for validation status in summary."""

    def test_passes_when_all_targets_met(self, collector):
        # Record fast, successful queries
        for i in range(20):
            collector.record_routing(f"q{i}", _make_result(), 5.0)

        summary = collector.get_basic_summary()
        vs = summary["validation_status"]
        assert vs["overall_status"] == "PASSED"

    def test_fails_when_success_rate_low(self, collector):
        for i in range(20):
            # Half fail
            if i % 2 == 0:
                collector.record_routing(
                    f"q{i}", _make_result(status=RoutingStatus.FAILED, tool=""), 5.0
                )
            else:
                collector.record_routing(f"q{i}", _make_result(), 5.0)

        summary = collector.get_basic_summary()
        vs = summary["validation_status"]
        assert vs["overall_status"] == "FAILED"


class TestPercentileCalculation:
    """Tests for _calculate_percentile."""

    def test_single_value(self, collector):
        assert collector._calculate_percentile([10.0], 95) == 10.0

    def test_empty_returns_zero(self, collector):
        assert collector._calculate_percentile([], 95) == 0.0

    def test_two_values_interpolation(self, collector):
        result = collector._calculate_percentile([10.0, 20.0], 50)
        assert result == 15.0

    def test_exact_index(self, collector):
        values = [10.0, 20.0, 30.0, 40.0, 50.0]
        # 50th percentile of 5 values: index = 0.5 * 4 = 2.0 -> exact -> 30.0
        assert collector._calculate_percentile(values, 50) == 30.0


class TestComparisonReport:
    """Tests for get_comparison_report."""

    def test_empty_metrics_returns_error(self, collector):
        report = collector.get_comparison_report()
        assert "error" in report

    def test_report_structure(self, collector):
        collector.record_routing("q1", _make_result(method=RoutingMethod.AI), 10.0)
        collector.record_routing("q2", _make_result(method=RoutingMethod.RULE_BASED), 20.0)

        report = collector.get_comparison_report()
        assert "summary" in report
        assert "ai_routing" in report
        assert "rule_based_routing" in report
        assert "comparative_analysis" in report
        assert "recommendations" in report

    def test_method_metrics_with_no_data(self, collector):
        collector.record_routing("q1", _make_result(method=RoutingMethod.RULE_BASED), 10.0)

        report = collector.get_comparison_report()
        # AI routing should have zero data
        assert report["ai_routing"]["total_queries"] == 0

    def test_comparative_analysis_insufficient_data(self, collector):
        collector.record_routing("q1", _make_result(method=RoutingMethod.RULE_BASED), 10.0)
        report = collector.get_comparison_report()
        assert "note" in report["comparative_analysis"]

    def test_comparative_analysis_with_both_methods(self, collector):
        for i in range(3):
            collector.record_routing(
                f"ai{i}", _make_result(method=RoutingMethod.AI), 10.0
            )
            collector.record_routing(
                f"rule{i}", _make_result(method=RoutingMethod.RULE_BASED), 20.0
            )

        report = collector.get_comparison_report()
        ca = report["comparative_analysis"]
        assert "success_rate_comparison" in ca
        assert "performance_comparison" in ca


class TestRecommendations:
    """Tests for recommendation generation."""

    def test_slow_performance_recommendation(self, collector):
        for i in range(5):
            collector.record_routing(f"q{i}", _make_result(), 100.0)

        summary = collector.get_basic_summary()
        vs = summary["validation_status"]
        recs = vs["recommendations"]
        assert any("response time" in r.lower() for r in recs)

    def test_low_success_rate_recommendation(self, collector):
        for i in range(5):
            collector.record_routing(
                f"q{i}", _make_result(status=RoutingStatus.FAILED, tool=""), 5.0
            )

        summary = collector.get_basic_summary()
        recs = summary["validation_status"]["recommendations"]
        assert any("success rate" in r.lower() for r in recs)

    def test_all_good_recommendation(self, collector):
        for i in range(20):
            collector.record_routing(f"q{i}", _make_result(), 5.0)

        summary = collector.get_basic_summary()
        recs = summary["validation_status"]["recommendations"]
        assert any("meet" in r.lower() or "target" in r.lower() for r in recs)


class TestExport:
    """Tests for export_metrics and export_simple_metrics."""

    def test_export_json(self, collector):
        collector.record_routing("q1", _make_result(), 10.0)
        exported = collector.export_metrics("json")
        parsed = json.loads(exported)
        assert isinstance(parsed, list)
        assert len(parsed) == 1

    def test_export_csv(self, collector):
        collector.record_routing("q1", _make_result(), 10.0)
        exported = collector.export_metrics("csv")
        assert "query" in exported
        assert "tool_selected" in exported

    def test_export_csv_empty(self, collector):
        exported = collector.export_metrics("csv")
        assert "No metrics" in exported

    def test_export_unsupported_format_raises(self, collector):
        with pytest.raises(ValueError, match="Unsupported"):
            collector.export_metrics("xml")

    def test_export_simple_json(self, collector):
        collector.record_routing("q1", _make_result(), 10.0)
        exported = collector.export_simple_metrics("json")
        parsed = json.loads(exported)
        assert "session_id" in parsed

    def test_export_simple_unsupported_raises(self, collector):
        with pytest.raises(ValueError, match="Unsupported"):
            collector.export_simple_metrics("xml")


class TestClearMetrics:
    """Tests for clear_metrics."""

    def test_clears_all_metrics(self, collector):
        collector.record_routing("q1", _make_result(), 10.0)
        assert len(collector.metrics) == 1

        collector.clear_metrics()
        assert len(collector.metrics) == 0


