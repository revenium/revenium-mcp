"""A/B Testing Framework for AI vs Rule-based Routing Comparison.

This module provides comprehensive A/B testing infrastructure to compare
AI-powered routing against rule-based routing performance, enabling
data-driven decisions about AI routing expansion.
"""

import asyncio
import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from loguru import logger

from .models import RoutingResult
from .simple_metrics import SimpleMetricsCollector


@dataclass
class TestScenario:
    """Represents a single test scenario for A/B testing."""

    id: str
    query: str
    expected_tool: str
    expected_action: str
    category: str
    description: str
    priority: int = 1  # 1=high, 2=medium, 3=low


@dataclass
class ABTestResult:
    """Results from A/B testing comparison."""

    scenario_id: str
    query: str

    # AI routing results
    ai_result: Optional[RoutingResult]
    ai_response_time_ms: float
    ai_success: bool
    ai_error: Optional[str]

    # Rule-based routing results
    rule_result: Optional[RoutingResult]
    rule_response_time_ms: float
    rule_success: bool
    rule_error: Optional[str]

    # Comparison metrics
    accuracy_match: bool  # Both methods produced same result
    ai_faster: bool
    time_difference_ms: float
    timestamp: datetime


@dataclass
class ABTestSummary:
    """Summary of A/B testing results."""

    session_id: str
    total_scenarios: int
    successful_comparisons: int

    # Success rates
    ai_success_rate: float
    rule_success_rate: float

    # Performance metrics
    ai_avg_response_time: float
    rule_avg_response_time: float
    ai_performance_advantage: float  # Percentage improvement

    # Accuracy metrics
    accuracy_match_rate: float
    ai_accuracy_rate: float
    rule_accuracy_rate: float

    # Recommendations
    recommendations: List[str]
    confidence_level: str

    # Detailed results
    results: List[ABTestResult]


class TestScenarioManager:
    """Manages predefined test scenarios for consistent A/B testing."""

    def __init__(self):
        """Initialize with predefined test scenarios."""
        self.scenarios = self._create_priority_scenarios()

    def _create_priority_scenarios(self) -> List[TestScenario]:
        """Create test scenarios for the 5 priority operations."""
        scenarios = []

        # CREATE PRODUCT scenarios (Priority 1)
        scenarios.extend(
            [
                TestScenario(
                    id="create_product_1",
                    query="create a product called API Gateway",
                    expected_tool="products",
                    expected_action="create",
                    category="product_creation",
                    description="Basic product creation with simple name",
                    priority=1,
                ),
                TestScenario(
                    id="create_product_2",
                    query="add new product named Billing Service",
                    expected_tool="products",
                    expected_action="create",
                    category="product_creation",
                    description="Product creation with alternative phrasing",
                    priority=1,
                ),
                TestScenario(
                    id="create_product_3",
                    query="I need to create a product for monitoring APIs",
                    expected_tool="products",
                    expected_action="create",
                    category="product_creation",
                    description="Conversational product creation request",
                    priority=1,
                ),
            ]
        )

        # LIST ALERTS scenarios (Priority 1)
        scenarios.extend(
            [
                TestScenario(
                    id="list_alerts_1",
                    query="show me all alerts",
                    expected_tool="alerts",
                    expected_action="list",
                    category="alert_management",
                    description="Basic alert listing request",
                    priority=1,
                ),
                TestScenario(
                    id="list_alerts_2",
                    query="list current alerts and anomalies",
                    expected_tool="alerts",
                    expected_action="list",
                    category="alert_management",
                    description="Alert listing with multiple terms",
                    priority=1,
                ),
            ]
        )

        # SHOW SUBSCRIPTIONS scenarios (Priority 1)
        scenarios.extend(
            [
                TestScenario(
                    id="show_subscriptions_1",
                    query="display all subscriptions",
                    expected_tool="subscriptions",
                    expected_action="list",
                    category="subscription_management",
                    description="Basic subscription listing",
                    priority=1,
                ),
                TestScenario(
                    id="show_subscriptions_2",
                    query="what subscriptions do we have",
                    expected_tool="subscriptions",
                    expected_action="list",
                    category="subscription_management",
                    description="Conversational subscription query",
                    priority=1,
                ),
            ]
        )

        # ADD CUSTOMER scenarios (Priority 1)
        scenarios.extend(
            [
                TestScenario(
                    id="add_customer_1",
                    query="add customer john@company.com",
                    expected_tool="customers",
                    expected_action="create",
                    category="customer_management",
                    description="Basic customer creation with email",
                    priority=1,
                ),
                TestScenario(
                    id="add_customer_2",
                    query="create new customer for Acme Corp",
                    expected_tool="customers",
                    expected_action="create",
                    category="customer_management",
                    description="Customer creation with company name",
                    priority=1,
                ),
            ]
        )

        # START WORKFLOW scenarios (Priority 1)
        scenarios.extend(
            [
                TestScenario(
                    id="start_workflow_1",
                    query="start billing workflow",
                    expected_tool="workflows",
                    expected_action="start",
                    category="workflow_management",
                    description="Basic workflow start request",
                    priority=1,
                ),
                TestScenario(
                    id="start_workflow_2",
                    query="begin setup workflow for new customer",
                    expected_tool="workflows",
                    expected_action="start",
                    category="workflow_management",
                    description="Workflow start with context",
                    priority=1,
                ),
            ]
        )

        return scenarios

    def get_priority_scenarios(self, priority: int = 1) -> List[TestScenario]:
        """Get scenarios by priority level."""
        return [s for s in self.scenarios if s.priority <= priority]

    def get_scenarios_by_category(self, category: str) -> List[TestScenario]:
        """Get scenarios by category."""
        return [s for s in self.scenarios if s.category == category]

    def get_all_scenarios(self) -> List[TestScenario]:
        """Get all available scenarios."""
        return self.scenarios.copy()


class PerformanceComparator:
    """Provides statistical analysis for A/B testing results."""

    def calculate_performance_metrics(self, results: List[ABTestResult]) -> Dict[str, Any]:
        """Calculate comprehensive performance metrics."""
        if not results:
            return {"error": "No results to analyze"}

        # Filter successful results for analysis
        successful_results = [r for r in results if r.ai_success and r.rule_success]

        if not successful_results:
            return {"error": "No successful comparisons available"}

        # Response time analysis
        ai_times = [r.ai_response_time_ms for r in successful_results]
        rule_times = [r.rule_response_time_ms for r in successful_results]

        # Accuracy analysis
        accuracy_matches = sum(1 for r in successful_results if r.accuracy_match)
        accuracy_rate = accuracy_matches / len(successful_results)

        # Performance comparison
        ai_faster_count = sum(1 for r in successful_results if r.ai_faster)
        ai_faster_rate = ai_faster_count / len(successful_results)

        return {
            "sample_size": len(successful_results),
            "response_time_analysis": {
                "ai_avg_ms": statistics.mean(ai_times),
                "ai_median_ms": statistics.median(ai_times),
                "ai_p95_ms": self._calculate_percentile(ai_times, 95),
                "rule_avg_ms": statistics.mean(rule_times),
                "rule_median_ms": statistics.median(rule_times),
                "rule_p95_ms": self._calculate_percentile(rule_times, 95),
                "ai_faster_rate": ai_faster_rate,
            },
            "accuracy_analysis": {
                "accuracy_match_rate": accuracy_rate,
                "total_matches": accuracy_matches,
                "total_comparisons": len(successful_results),
            },
            "statistical_significance": self._calculate_significance(ai_times, rule_times),
        }

    def _calculate_percentile(self, values: List[float], percentile: int) -> float:
        """Calculate percentile value."""
        if not values:
            return 0.0

        sorted_values = sorted(values)
        index = (percentile / 100) * (len(sorted_values) - 1)

        if index.is_integer():
            return sorted_values[int(index)]

        lower_index = int(index)
        upper_index = lower_index + 1
        weight = index - lower_index
        return sorted_values[lower_index] * (1 - weight) + sorted_values[upper_index] * weight

    def _calculate_significance(
        self, ai_times: List[float], rule_times: List[float]
    ) -> Dict[str, Any]:
        """Calculate statistical significance of performance difference."""
        if len(ai_times) < 10 or len(rule_times) < 10:
            return {
                "sufficient_data": False,
                "message": "Need at least 10 samples for statistical significance",
            }

        ai_mean = statistics.mean(ai_times)
        rule_mean = statistics.mean(rule_times)

        # Simple effect size calculation (Cohen's d approximation)
        pooled_std = statistics.stdev(ai_times + rule_times)
        effect_size = abs(ai_mean - rule_mean) / pooled_std if pooled_std > 0 else 0

        # Interpret effect size
        if effect_size < 0.2:
            significance = "negligible"
        elif effect_size < 0.5:
            significance = "small"
        elif effect_size < 0.8:
            significance = "medium"
        else:
            significance = "large"

        return {
            "sufficient_data": True,
            "effect_size": effect_size,
            "significance_level": significance,
            "performance_difference_ms": ai_mean - rule_mean,
            "performance_difference_pct": (
                ((ai_mean - rule_mean) / rule_mean * 100) if rule_mean > 0 else 0
            ),
        }


class ABTestingFramework:
    """Main A/B testing framework for comparing AI vs rule-based routing."""

    def __init__(
        self,
        ai_router,
        rule_based_router,
        metrics_collector: Optional[SimpleMetricsCollector] = None,
    ):
        """Initialize A/B testing framework.

        Args:
            ai_router: AI-powered router instance
            rule_based_router: Rule-based router instance
            metrics_collector: Optional metrics collector for integration
        """
        self.ai_router = ai_router
        self.rule_based_router = rule_based_router
        self.metrics_collector = metrics_collector or SimpleMetricsCollector()
        self.scenario_manager = TestScenarioManager()
        self.comparator = PerformanceComparator()
        self.session_id = str(uuid4())

        logger.info(f"A/B Testing Framework initialized with session: {self.session_id}")

    async def run_ab_test(
        self, scenarios: Optional[List[TestScenario]] = None, priority_filter: int = 1
    ) -> ABTestSummary:
        """Run comprehensive A/B test comparing AI vs rule-based routing.

        Args:
            scenarios: Optional list of specific scenarios to test
            priority_filter: Priority level filter (1=high, 2=medium, 3=low)

        Returns:
            Comprehensive A/B test summary with results and recommendations
        """
        if scenarios is None:
            scenarios = self.scenario_manager.get_priority_scenarios(priority_filter)

        logger.info(f"Starting A/B test with {len(scenarios)} scenarios")

        results = []
        for scenario in scenarios:
            logger.debug(f"Testing scenario: {scenario.id}")
            result = await self._test_scenario(scenario)
            results.append(result)

            # Brief pause between tests to avoid overwhelming the system
            await asyncio.sleep(0.1)

        # Generate comprehensive summary
        summary = self._generate_summary(results)

        logger.info(
            f"A/B test completed: {summary.successful_comparisons}/"
            f"{summary.total_scenarios} successful comparisons"
        )

        return summary

    async def _test_scenario(self, scenario: TestScenario) -> ABTestResult:
        """Test a single scenario through both AI and rule-based routing."""
        start_time = datetime.now()

        # Test AI routing
        ai_result, ai_time, ai_success, ai_error = await self._test_ai_routing(
            scenario.query, scenario.expected_tool
        )

        # Test rule-based routing
        rule_result, rule_time, rule_success, rule_error = await self._test_rule_routing(
            scenario.query, scenario.expected_tool
        )

        # Compare results
        accuracy_match = self._check_accuracy_match(ai_result, rule_result, scenario)
        ai_faster = ai_time < rule_time if ai_success and rule_success else False
        time_difference = ai_time - rule_time if ai_success and rule_success else 0

        return ABTestResult(
            scenario_id=scenario.id,
            query=scenario.query,
            ai_result=ai_result,
            ai_response_time_ms=ai_time,
            ai_success=ai_success,
            ai_error=ai_error,
            rule_result=rule_result,
            rule_response_time_ms=rule_time,
            rule_success=rule_success,
            rule_error=rule_error,
            accuracy_match=accuracy_match,
            ai_faster=ai_faster,
            time_difference_ms=time_difference,
            timestamp=start_time,
        )

    async def _test_ai_routing(
        self, query: str, tool_context: str
    ) -> Tuple[Optional[RoutingResult], float, bool, Optional[str]]:
        """Test AI routing for a query."""
        try:
            start_time = datetime.now()
            result = await self.ai_router.route_query(query, tool_context)
            end_time = datetime.now()

            response_time = (end_time - start_time).total_seconds() * 1000
            return result, response_time, True, None

        except Exception as e:
            logger.warning(f"AI routing failed for query '{query}': {e}")
            return None, 0.0, False, str(e)

    async def _test_rule_routing(
        self, query: str, tool_context: str
    ) -> Tuple[Optional[RoutingResult], float, bool, Optional[str]]:
        """Test rule-based routing for a query."""
        try:
            start_time = datetime.now()
            result = await self.rule_based_router.route_query(query, tool_context)
            end_time = datetime.now()

            response_time = (end_time - start_time).total_seconds() * 1000
            return result, response_time, True, None

        except Exception as e:
            logger.warning(f"Rule-based routing failed for query '{query}': {e}")
            return None, 0.0, False, str(e)

    def _check_accuracy_match(
        self,
        ai_result: Optional[RoutingResult],
        rule_result: Optional[RoutingResult],
        scenario: TestScenario,
    ) -> bool:
        """Check if AI and rule-based routing produced matching results."""
        if not ai_result or not rule_result:
            return False

        # Check if both methods selected the same tool and action
        tool_match = ai_result.tool_name == rule_result.tool_name
        action_match = ai_result.action == rule_result.action

        # Check if results match expected scenario
        expected_tool_match = (
            ai_result.tool_name == scenario.expected_tool
            and rule_result.tool_name == scenario.expected_tool
        )
        expected_action_match = (
            ai_result.action == scenario.expected_action
            and rule_result.action == scenario.expected_action
        )

        return tool_match and action_match and expected_tool_match and expected_action_match

    def _generate_summary(self, results: List[ABTestResult]) -> ABTestSummary:
        """Generate comprehensive A/B test summary."""
        total_scenarios = len(results)
        successful_comparisons = sum(1 for r in results if r.ai_success and r.rule_success)

        if successful_comparisons == 0:
            return ABTestSummary(
                session_id=self.session_id,
                total_scenarios=total_scenarios,
                successful_comparisons=0,
                ai_success_rate=0.0,
                rule_success_rate=0.0,
                ai_avg_response_time=0.0,
                rule_avg_response_time=0.0,
                ai_performance_advantage=0.0,
                accuracy_match_rate=0.0,
                ai_accuracy_rate=0.0,
                rule_accuracy_rate=0.0,
                recommendations=["No successful comparisons available"],
                confidence_level="insufficient_data",
                results=results,
            )

        # Calculate success rates
        ai_successes = sum(1 for r in results if r.ai_success)
        rule_successes = sum(1 for r in results if r.rule_success)
        ai_success_rate = ai_successes / total_scenarios
        rule_success_rate = rule_successes / total_scenarios

        # Calculate performance metrics from successful comparisons
        successful_results = [r for r in results if r.ai_success and r.rule_success]
        ai_times = [r.ai_response_time_ms for r in successful_results]
        rule_times = [r.rule_response_time_ms for r in successful_results]

        ai_avg_time = statistics.mean(ai_times) if ai_times else 0.0
        rule_avg_time = statistics.mean(rule_times) if rule_times else 0.0

        # Calculate performance advantage
        ai_performance_advantage = 0.0
        if rule_avg_time > 0:
            ai_performance_advantage = ((rule_avg_time - ai_avg_time) / rule_avg_time) * 100

        # Calculate accuracy metrics
        accuracy_matches = sum(1 for r in successful_results if r.accuracy_match)
        accuracy_match_rate = (
            accuracy_matches / len(successful_results) if successful_results else 0.0
        )

        # Calculate individual accuracy rates (vs expected results)
        ai_accurate = sum(1 for r in results if r.ai_success and self._is_result_accurate(r, "ai"))
        rule_accurate = sum(
            1 for r in results if r.rule_success and self._is_result_accurate(r, "rule")
        )

        ai_accuracy_rate = ai_accurate / ai_successes if ai_successes > 0 else 0.0
        rule_accuracy_rate = rule_accurate / rule_successes if rule_successes > 0 else 0.0

        # Generate recommendations and confidence level
        recommendations = self._generate_recommendations(
            ai_success_rate,
            rule_success_rate,
            ai_performance_advantage,
            accuracy_match_rate,
            successful_comparisons,
        )
        confidence_level = self._determine_confidence_level(successful_comparisons)

        return ABTestSummary(
            session_id=self.session_id,
            total_scenarios=total_scenarios,
            successful_comparisons=successful_comparisons,
            ai_success_rate=ai_success_rate,
            rule_success_rate=rule_success_rate,
            ai_avg_response_time=ai_avg_time,
            rule_avg_response_time=rule_avg_time,
            ai_performance_advantage=ai_performance_advantage,
            accuracy_match_rate=accuracy_match_rate,
            ai_accuracy_rate=ai_accuracy_rate,
            rule_accuracy_rate=rule_accuracy_rate,
            recommendations=recommendations,
            confidence_level=confidence_level,
            results=results,
        )

    def _is_result_accurate(self, result: ABTestResult, method: str) -> bool:
        """Check if a result is accurate against expected scenario."""
        # This would need access to the original scenario
        # For now, we'll use a simplified check
        if method == "ai" and result.ai_result:
            return result.ai_result.is_successful()
        elif method == "rule" and result.rule_result:
            return result.rule_result.is_successful()
        return False

    def _generate_recommendations(
        self,
        ai_success_rate: float,
        rule_success_rate: float,
        ai_performance_advantage: float,
        accuracy_match_rate: float,
        sample_size: int,
    ) -> List[str]:
        """Generate actionable recommendations based on A/B test results."""
        recommendations = []

        # Success rate recommendations
        if ai_success_rate < 0.9:
            recommendations.append(
                f"AI success rate ({ai_success_rate:.1%}) is below target (90%). "
                f"Review AI prompts and error handling."
            )

        if rule_success_rate < 0.95:
            recommendations.append(
                f"Rule-based success rate ({rule_success_rate:.1%}) is below "
                f"target (95%). Review rule-based routing logic."
            )

        # Performance recommendations
        if ai_performance_advantage > 20:
            recommendations.append(
                f"AI routing is {ai_performance_advantage:.1f}% faster than "
                f"rule-based. Consider expanding AI routing to more operations."
            )
        elif ai_performance_advantage < -50:
            recommendations.append(
                f"AI routing is {abs(ai_performance_advantage):.1f}% slower than "
                f"rule-based. Optimize AI client configuration or consider caching."
            )

        # Accuracy recommendations
        if accuracy_match_rate < 0.8:
            recommendations.append(
                f"Accuracy match rate ({accuracy_match_rate:.1%}) is low. "
                f"Review routing consistency between AI and rule-based methods."
            )

        # Sample size recommendations
        if sample_size < 10:
            recommendations.append(
                f"Sample size ({sample_size}) is small. "
                f"Run more tests for statistically significant results."
            )

        if not recommendations:
            recommendations.append(
                "A/B testing results look good! Both routing methods are " "performing well."
            )

        return recommendations

    def _determine_confidence_level(self, sample_size: int) -> str:
        """Determine confidence level based on sample size and results."""
        if sample_size < 5:
            return "very_low"
        elif sample_size < 10:
            return "low"
        elif sample_size < 20:
            return "medium"
        elif sample_size < 50:
            return "high"
        else:
            return "very_high"
