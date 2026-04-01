"""Unit tests for ai_routing.ab_testing_framework module.

Tests TestScenarioManager, PerformanceComparator, and ABTestingFramework
summary generation and recommendation logic without making real routing calls.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.revenium_mcp_server.ai_routing.ab_testing_framework import (
    ABTestingFramework,
    ABTestResult,
    ABTestSummary,
    PerformanceComparator,
    TestScenario,
    TestScenarioManager,
)
from src.revenium_mcp_server.ai_routing.models import (
    RoutingMethod,
    RoutingResult,
    RoutingStatus,
)


def _make_routing_result(tool="products", action="create", success=True, confidence=0.9):
    return RoutingResult(
        tool_name=tool,
        action=action,
        confidence=confidence,
        routing_method=RoutingMethod.AI if tool else RoutingMethod.FALLBACK,
        status=RoutingStatus.SUCCESS if success else RoutingStatus.FAILED,
    )


def _make_ab_result(
    scenario_id="test_1",
    query="test query",
    ai_success=True,
    rule_success=True,
    ai_time=10.0,
    rule_time=20.0,
    accuracy_match=True,
    ai_tool="products",
    ai_action="create",
    rule_tool="products",
    rule_action="create",
):
    ai_result = _make_routing_result(tool=ai_tool, action=ai_action) if ai_success else None
    rule_result = _make_routing_result(tool=rule_tool, action=rule_action) if rule_success else None
    return ABTestResult(
        scenario_id=scenario_id,
        query=query,
        ai_result=ai_result,
        ai_response_time_ms=ai_time,
        ai_success=ai_success,
        ai_error=None if ai_success else "error",
        rule_result=rule_result,
        rule_response_time_ms=rule_time,
        rule_success=rule_success,
        rule_error=None if rule_success else "error",
        accuracy_match=accuracy_match,
        ai_faster=ai_time < rule_time if ai_success and rule_success else False,
        time_difference_ms=ai_time - rule_time if ai_success and rule_success else 0,
        timestamp=datetime.now(),
    )


class TestTestScenarioManager:
    """Tests for TestScenarioManager scenario management."""

    def test_creates_priority_scenarios(self):
        mgr = TestScenarioManager()
        assert len(mgr.scenarios) > 0

    def test_all_scenarios_have_required_fields(self):
        mgr = TestScenarioManager()
        for s in mgr.scenarios:
            assert s.id
            assert s.query
            assert s.expected_tool
            assert s.expected_action
            assert s.category
            assert s.description

    def test_get_priority_scenarios_filters(self):
        mgr = TestScenarioManager()
        p1 = mgr.get_priority_scenarios(priority=1)
        assert all(s.priority <= 1 for s in p1)

    def test_get_scenarios_by_category(self):
        mgr = TestScenarioManager()
        product_scenarios = mgr.get_scenarios_by_category("product_creation")
        assert len(product_scenarios) > 0
        assert all(s.category == "product_creation" for s in product_scenarios)

    def test_get_all_scenarios_returns_copy(self):
        mgr = TestScenarioManager()
        all_scenarios = mgr.get_all_scenarios()
        assert len(all_scenarios) == len(mgr.scenarios)
        # Should be a copy, not the same list
        assert all_scenarios is not mgr.scenarios

    def test_has_all_five_categories(self):
        mgr = TestScenarioManager()
        categories = {s.category for s in mgr.scenarios}
        assert "product_creation" in categories
        assert "alert_management" in categories
        assert "subscription_management" in categories
        assert "customer_management" in categories
        assert "workflow_management" in categories


class TestPerformanceComparator:
    """Tests for PerformanceComparator metrics calculation."""

    @pytest.fixture
    def comparator(self):
        return PerformanceComparator()

    def test_empty_results_returns_error(self, comparator):
        result = comparator.calculate_performance_metrics([])
        assert "error" in result

    def test_no_successful_comparisons_returns_error(self, comparator):
        results = [_make_ab_result(ai_success=False)]
        result = comparator.calculate_performance_metrics(results)
        assert "error" in result

    def test_calculates_response_time_analysis(self, comparator):
        results = [
            _make_ab_result(ai_time=10.0, rule_time=20.0),
            _make_ab_result(ai_time=15.0, rule_time=25.0),
        ]
        metrics = comparator.calculate_performance_metrics(results)
        rta = metrics["response_time_analysis"]
        assert rta["ai_avg_ms"] == 12.5
        assert rta["rule_avg_ms"] == 22.5
        assert rta["ai_faster_rate"] == 1.0

    def test_calculates_accuracy_analysis(self, comparator):
        results = [
            _make_ab_result(accuracy_match=True),
            _make_ab_result(accuracy_match=False),
        ]
        metrics = comparator.calculate_performance_metrics(results)
        assert metrics["accuracy_analysis"]["accuracy_match_rate"] == 0.5

    def test_insufficient_data_for_significance(self, comparator):
        results = [_make_ab_result() for _ in range(5)]
        metrics = comparator.calculate_performance_metrics(results)
        assert metrics["statistical_significance"]["sufficient_data"] is False

    def test_sufficient_data_calculates_significance(self, comparator):
        results = [
            _make_ab_result(ai_time=10.0 + i, rule_time=50.0 + i)
            for i in range(12)
        ]
        metrics = comparator.calculate_performance_metrics(results)
        sig = metrics["statistical_significance"]
        assert sig["sufficient_data"] is True
        assert "effect_size" in sig
        assert "significance_level" in sig

    def test_percentile_calculation(self, comparator):
        assert comparator._calculate_percentile([], 95) == 0.0
        assert comparator._calculate_percentile([10.0], 50) == 10.0


class TestABTestingFrameworkSummary:
    """Tests for ABTestingFramework._generate_summary."""

    @pytest.fixture
    def framework(self):
        ai_router = MagicMock()
        rule_router = MagicMock()
        return ABTestingFramework(ai_router, rule_router)

    def test_no_successful_comparisons(self, framework):
        results = [_make_ab_result(ai_success=False, rule_success=False)]
        summary = framework._generate_summary(results)
        assert summary.successful_comparisons == 0
        assert summary.confidence_level == "insufficient_data"

    def test_summary_with_successful_comparisons(self, framework):
        results = [
            _make_ab_result(ai_time=10.0, rule_time=20.0),
            _make_ab_result(ai_time=15.0, rule_time=25.0),
        ]
        summary = framework._generate_summary(results)
        assert summary.total_scenarios == 2
        assert summary.successful_comparisons == 2
        assert summary.ai_success_rate == 1.0
        assert summary.rule_success_rate == 1.0

    def test_performance_advantage_calculated(self, framework):
        results = [
            _make_ab_result(ai_time=10.0, rule_time=20.0),
        ]
        summary = framework._generate_summary(results)
        # AI is 50% faster
        assert summary.ai_performance_advantage == 50.0


class TestABTestingRecommendations:
    """Tests for _generate_recommendations."""

    @pytest.fixture
    def framework(self):
        return ABTestingFramework(MagicMock(), MagicMock())

    def test_low_ai_success_rate_flagged(self, framework):
        recs = framework._generate_recommendations(0.5, 1.0, 0.0, 1.0, 20)
        assert any("AI success rate" in r for r in recs)

    def test_low_rule_success_rate_flagged(self, framework):
        recs = framework._generate_recommendations(1.0, 0.5, 0.0, 1.0, 20)
        assert any("Rule-based" in r for r in recs)

    def test_high_ai_performance_advantage(self, framework):
        recs = framework._generate_recommendations(1.0, 1.0, 25.0, 1.0, 20)
        assert any("faster" in r.lower() for r in recs)

    def test_slow_ai_performance(self, framework):
        recs = framework._generate_recommendations(1.0, 1.0, -60.0, 1.0, 20)
        assert any("slower" in r.lower() for r in recs)

    def test_low_accuracy_match_flagged(self, framework):
        recs = framework._generate_recommendations(1.0, 1.0, 0.0, 0.5, 20)
        assert any("accuracy" in r.lower() for r in recs)

    def test_small_sample_size_flagged(self, framework):
        recs = framework._generate_recommendations(1.0, 1.0, 0.0, 1.0, 5)
        assert any("sample size" in r.lower() for r in recs)

    def test_all_good_returns_positive(self, framework):
        recs = framework._generate_recommendations(1.0, 1.0, 0.0, 1.0, 20)
        assert any("look good" in r.lower() for r in recs)


class TestConfidenceLevel:
    """Tests for _determine_confidence_level."""

    @pytest.fixture
    def framework(self):
        return ABTestingFramework(MagicMock(), MagicMock())

    def test_very_low(self, framework):
        assert framework._determine_confidence_level(3) == "very_low"

    def test_low(self, framework):
        assert framework._determine_confidence_level(7) == "low"

    def test_medium(self, framework):
        assert framework._determine_confidence_level(15) == "medium"

    def test_high(self, framework):
        assert framework._determine_confidence_level(30) == "high"

    def test_very_high(self, framework):
        assert framework._determine_confidence_level(60) == "very_high"


class TestAccuracyCheck:
    """Tests for _check_accuracy_match and _is_result_accurate."""

    @pytest.fixture
    def framework(self):
        return ABTestingFramework(MagicMock(), MagicMock())

    def test_match_when_both_correct(self, framework):
        scenario = TestScenario(
            id="t1",
            query="test",
            expected_tool="products",
            expected_action="create",
            category="test",
            description="test",
        )
        ai_result = _make_routing_result(tool="products", action="create")
        rule_result = _make_routing_result(tool="products", action="create")
        assert framework._check_accuracy_match(ai_result, rule_result, scenario) is True

    def test_no_match_when_tools_differ(self, framework):
        scenario = TestScenario(
            id="t1",
            query="test",
            expected_tool="products",
            expected_action="create",
            category="test",
            description="test",
        )
        ai_result = _make_routing_result(tool="alerts", action="create")
        rule_result = _make_routing_result(tool="products", action="create")
        assert framework._check_accuracy_match(ai_result, rule_result, scenario) is False

    def test_no_match_when_result_is_none(self, framework):
        scenario = TestScenario(
            id="t1",
            query="test",
            expected_tool="products",
            expected_action="create",
            category="test",
            description="test",
        )
        assert framework._check_accuracy_match(None, None, scenario) is False

    def test_is_result_accurate_ai(self, framework):
        result = _make_ab_result()
        assert framework._is_result_accurate(result, "ai") is True

    def test_is_result_accurate_rule(self, framework):
        result = _make_ab_result()
        assert framework._is_result_accurate(result, "rule") is True

    def test_is_result_accurate_no_result(self, framework):
        result = _make_ab_result(ai_success=False)
        assert framework._is_result_accurate(result, "ai") is False
