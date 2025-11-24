"""Automated Regression Testing Pipeline.

This module provides a comprehensive automated regression testing pipeline that
orchestrates all existing testing infrastructure to ensure continuous validation
of MCP functionality.

Features:
- Orchestrates existing test suites (load testing, functional testing, edge cases)
- Automated test execution with configurable schedules
- Regression detection and baseline management
- Comprehensive reporting and alerting
- CI/CD integration support
- Performance trend analysis

Following development best practices:
- Builds on existing testing infrastructure
- Provides unified test orchestration
- Maintains test result history
- Supports multiple execution modes
"""

import asyncio
import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

# Import existing testing components
from .load_testing_framework import (
    run_performance_regression_test,
)


class TestSuite(str, Enum):
    """Available test suites."""

    FUNCTIONAL = "functional"
    LOAD_TESTING = "load_testing"
    EDGE_CASES = "edge_cases"
    INTEGRATION = "integration"
    UNIT_TESTS = "unit_tests"
    COMPLIANCE = "compliance"
    ALL = "all"


class TestResult(str, Enum):
    """Test execution results."""

    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"
    SKIP = "skip"


@dataclass
class TestExecution:
    """Individual test execution result."""

    suite: str
    test_name: str
    result: TestResult
    duration_seconds: float
    error_message: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)


@dataclass
class RegressionTestReport:
    """Comprehensive regression test report."""

    pipeline_id: str
    execution_timestamp: datetime
    total_duration_seconds: float
    test_executions: List[TestExecution]
    summary: Dict[str, Any]
    regression_analysis: Dict[str, Any]
    baseline_comparison: Dict[str, Any]
    recommendations: List[str]
    overall_result: TestResult
    environment: str = "development"

    def __post_init__(self):
        if self.execution_timestamp is None:
            self.execution_timestamp = datetime.now(timezone.utc)


class RegressionTestingPipeline:
    """Automated regression testing pipeline with comprehensive orchestration."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize regression testing pipeline.

        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        self.project_root = Path(__file__).parent.parent.parent.parent
        self.test_results_dir = self.project_root / "test_results"
        self.test_results_dir.mkdir(exist_ok=True)

        # Pipeline configuration
        self.environment = self.config.get("environment", "development")
        self.enable_performance_tests = self.config.get("enable_performance_tests", True)
        self.enable_load_tests = self.config.get("enable_load_tests", True)
        self.parallel_execution = self.config.get("parallel_execution", True)
        self.baseline_management = self.config.get("baseline_management", True)

        # Test suite configurations
        self.test_suites = {
            TestSuite.FUNCTIONAL: {
                "script": "development_test_scripts/comprehensive_mcp_testing.py",
                "timeout": 1800,  # 30 minutes
                "critical": True,
            },
            TestSuite.LOAD_TESTING: {
                "script": "development_test_scripts/test_load_testing_framework.py",
                "timeout": 900,  # 15 minutes
                "critical": True,
            },
            TestSuite.EDGE_CASES: {
                "script": "development_test_scripts/mcp_edge_case_testing.py",
                "timeout": 1200,  # 20 minutes
                "critical": True,
            },
            TestSuite.INTEGRATION: {
                "command": ["python", "-m", "pytest", "tests/integration/", "-v"],
                "timeout": 600,  # 10 minutes
                "critical": True,
            },
            TestSuite.UNIT_TESTS: {
                "command": ["python", "-m", "pytest", "tests/", "-v", "--tb=short"],
                "timeout": 300,  # 5 minutes
                "critical": False,
            },
            TestSuite.COMPLIANCE: {
                "script": "development_test_scripts/test_compliance_validation.py",
                "timeout": 600,  # 10 minutes
                "critical": False,
            },
        }

        # Test history storage
        self.test_history: List[RegressionTestReport] = []
        self.load_test_history()

    async def run_regression_pipeline(
        self, suites: Optional[List[TestSuite]] = None
    ) -> RegressionTestReport:
        """Run comprehensive regression testing pipeline.

        Args:
            suites: Optional list of test suites to run (defaults to all)

        Returns:
            Comprehensive regression test report
        """
        pipeline_id = f"regression_{int(datetime.now().timestamp())}"
        start_time = time.time()

        logger.info(f"Starting regression testing pipeline: {pipeline_id}")

        # Determine which suites to run
        if suites is None:
            suites = [
                TestSuite.FUNCTIONAL,
                TestSuite.LOAD_TESTING,
                TestSuite.EDGE_CASES,
                TestSuite.INTEGRATION,
            ]

        if TestSuite.ALL in suites:
            suites = list(TestSuite)
            suites.remove(TestSuite.ALL)

        # Execute test suites
        test_executions = []

        if self.parallel_execution:
            # Run non-conflicting tests in parallel
            test_executions = await self._run_tests_parallel(suites)
        else:
            # Run tests sequentially
            test_executions = await self._run_tests_sequential(suites)

        # Calculate total duration
        total_duration = time.time() - start_time

        # Generate summary
        summary = self._generate_test_summary(test_executions)

        # Perform regression analysis
        regression_analysis = await self._perform_regression_analysis()

        # Compare with baseline
        baseline_comparison = self._compare_with_baseline(test_executions)

        # Generate recommendations
        recommendations = self._generate_recommendations(test_executions, regression_analysis)

        # Determine overall result
        overall_result = self._determine_overall_result(test_executions)

        # Create comprehensive report
        report = RegressionTestReport(
            pipeline_id=pipeline_id,
            execution_timestamp=datetime.now(timezone.utc),
            total_duration_seconds=total_duration,
            test_executions=test_executions,
            summary=summary,
            regression_analysis=regression_analysis,
            baseline_comparison=baseline_comparison,
            recommendations=recommendations,
            overall_result=overall_result,
            environment=self.environment,
        )

        # Store results
        self._store_test_results(report)

        # Update baselines if needed
        if self.baseline_management and overall_result == TestResult.PASS:
            self._update_baselines(report)

        logger.info(
            f"Regression testing pipeline completed: {pipeline_id} ({overall_result.value})"
        )

        return report

    async def _run_tests_sequential(self, suites: List[TestSuite]) -> List[TestExecution]:
        """Run test suites sequentially."""
        test_executions = []

        for suite in suites:
            if suite not in self.test_suites:
                logger.warning(f"Unknown test suite: {suite}")
                continue

            execution = await self._execute_test_suite(suite)
            test_executions.append(execution)

            # Stop on critical failures if configured
            if execution.result == TestResult.FAIL and self.test_suites[suite].get(
                "critical", False
            ):
                logger.error(f"Critical test suite failed: {suite}")
                if self.config.get("stop_on_critical_failure", False):
                    break

        return test_executions

    async def _run_tests_parallel(self, suites: List[TestSuite]) -> List[TestExecution]:
        """Run compatible test suites in parallel."""
        # Group tests by compatibility (some tests may conflict)
        parallel_groups = [
            [TestSuite.UNIT_TESTS, TestSuite.COMPLIANCE],  # Fast, non-conflicting tests
            [TestSuite.INTEGRATION],  # May conflict with others
            [TestSuite.FUNCTIONAL, TestSuite.EDGE_CASES],  # Can run together
            [TestSuite.LOAD_TESTING],  # Resource intensive, run alone
        ]

        test_executions = []

        for group in parallel_groups:
            # Only run suites that are requested and available
            group_suites = [s for s in group if s in suites and s in self.test_suites]

            if not group_suites:
                continue

            # Run group in parallel
            tasks = [self._execute_test_suite(suite) for suite in group_suites]
            group_results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in group_results:
                if isinstance(result, Exception):
                    logger.error(f"Test execution failed with exception: {result}")
                    # Create error execution record
                    test_executions.append(
                        TestExecution(
                            suite="unknown",
                            test_name="execution_error",
                            result=TestResult.ERROR,
                            duration_seconds=0,
                            error_message=str(result),
                        )
                    )
                else:
                    test_executions.append(result)

        return test_executions

    async def _execute_test_suite(self, suite: TestSuite) -> TestExecution:
        """Execute a single test suite."""
        suite_config = self.test_suites[suite]
        start_time = time.time()

        logger.info(f"Executing test suite: {suite.value}")

        try:
            # Determine execution method
            if "script" in suite_config:
                # Python script execution
                script_path = self.project_root / suite_config["script"]
                result = await self._run_python_script(script_path, suite_config["timeout"])
            elif "command" in suite_config:
                # Command execution
                result = await self._run_command(suite_config["command"], suite_config["timeout"])
            else:
                raise ValueError(f"No execution method defined for suite: {suite}")

            duration = time.time() - start_time

            # Determine test result
            if result["returncode"] == 0:
                test_result = TestResult.PASS
                error_message = None
            else:
                test_result = TestResult.FAIL
                error_message = result.get("stderr", "Unknown error")

            return TestExecution(
                suite=suite.value,
                test_name=f"{suite.value}_suite",
                result=test_result,
                duration_seconds=duration,
                error_message=error_message,
                details={
                    "stdout": result.get("stdout", ""),
                    "stderr": result.get("stderr", ""),
                    "returncode": result["returncode"],
                },
            )

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"Test suite execution failed: {suite.value} - {e}")

            return TestExecution(
                suite=suite.value,
                test_name=f"{suite.value}_suite",
                result=TestResult.ERROR,
                duration_seconds=duration,
                error_message=str(e),
            )

    async def _run_python_script(self, script_path: Path, timeout: int) -> Dict[str, Any]:
        """Run a Python script and capture output."""
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(script_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.project_root,
            )

            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)

            return {
                "returncode": process.returncode,
                "stdout": stdout.decode() if stdout else "",
                "stderr": stderr.decode() if stderr else "",
            }

        except asyncio.TimeoutError:
            logger.error(f"Script execution timed out: {script_path}")
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": f"Execution timed out after {timeout} seconds",
            }
        except Exception as e:
            logger.error(f"Script execution failed: {script_path} - {e}")
            return {"returncode": -1, "stdout": "", "stderr": str(e)}

    async def _run_command(self, command: List[str], timeout: int) -> Dict[str, Any]:
        """Run a command and capture output."""
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.project_root,
            )

            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)

            return {
                "returncode": process.returncode,
                "stdout": stdout.decode() if stdout else "",
                "stderr": stderr.decode() if stderr else "",
            }

        except asyncio.TimeoutError:
            logger.error(f"Command execution timed out: {' '.join(command)}")
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": f"Execution timed out after {timeout} seconds",
            }
        except Exception as e:
            logger.error(f"Command execution failed: {' '.join(command)} - {e}")
            return {"returncode": -1, "stdout": "", "stderr": str(e)}

    async def _perform_regression_analysis(self) -> Dict[str, Any]:
        """Perform regression analysis using existing load testing framework."""
        if not self.enable_performance_tests:
            return {"status": "disabled", "message": "Performance regression analysis disabled"}

        try:
            # Use existing performance regression test
            regression_results = await run_performance_regression_test()

            return {
                "status": "completed",
                "results": regression_results,
                "performance_regression_detected": not regression_results.get(
                    "compliance_summary", {}
                ).get("overall_pass", False),
            }

        except Exception as e:
            logger.error(f"Regression analysis failed: {e}")
            return {"status": "error", "error": str(e), "performance_regression_detected": False}

    def _generate_test_summary(self, test_executions: List[TestExecution]) -> Dict[str, Any]:
        """Generate test execution summary."""
        total_tests = len(test_executions)
        passed_tests = len([t for t in test_executions if t.result == TestResult.PASS])
        failed_tests = len([t for t in test_executions if t.result == TestResult.FAIL])
        error_tests = len([t for t in test_executions if t.result == TestResult.ERROR])

        total_duration = sum(t.duration_seconds for t in test_executions)

        return {
            "total_tests": total_tests,
            "passed_tests": passed_tests,
            "failed_tests": failed_tests,
            "error_tests": error_tests,
            "success_rate": (passed_tests / total_tests * 100) if total_tests > 0 else 0,
            "total_duration_seconds": total_duration,
            "average_duration_seconds": total_duration / total_tests if total_tests > 0 else 0,
            "test_breakdown": {"pass": passed_tests, "fail": failed_tests, "error": error_tests},
        }

    def _compare_with_baseline(self, test_executions: List[TestExecution]) -> Dict[str, Any]:
        """Compare current results with historical baseline."""
        if not self.test_history:
            return {"status": "no_baseline", "message": "No historical data for comparison"}

        # Get recent successful runs for baseline
        recent_successful = [
            report
            for report in self.test_history[-10:]  # Last 10 runs
            if report.overall_result == TestResult.PASS
        ]

        if not recent_successful:
            return {
                "status": "no_successful_baseline",
                "message": "No recent successful runs for comparison",
            }

        # Calculate baseline metrics
        baseline_duration = sum(r.total_duration_seconds for r in recent_successful) / len(
            recent_successful
        )
        baseline_success_rate = sum(r.summary["success_rate"] for r in recent_successful) / len(
            recent_successful
        )

        # Current metrics
        current_duration = sum(t.duration_seconds for t in test_executions)
        current_success_rate = (
            len([t for t in test_executions if t.result == TestResult.PASS])
            / len(test_executions)
            * 100
        )

        # Calculate deviations
        duration_change = (
            ((current_duration - baseline_duration) / baseline_duration * 100)
            if baseline_duration > 0
            else 0
        )
        success_rate_change = current_success_rate - baseline_success_rate

        return {
            "status": "completed",
            "baseline_runs": len(recent_successful),
            "baseline_duration": baseline_duration,
            "baseline_success_rate": baseline_success_rate,
            "current_duration": current_duration,
            "current_success_rate": current_success_rate,
            "duration_change_percent": duration_change,
            "success_rate_change": success_rate_change,
            "performance_regression": duration_change > 20,  # 20% slower
            "quality_regression": success_rate_change < -5,  # 5% lower success rate
        }

    def _generate_recommendations(
        self, test_executions: List[TestExecution], regression_analysis: Dict[str, Any]
    ) -> List[str]:
        """Generate actionable recommendations based on test results."""
        recommendations = []

        # Analyze test failures
        failed_tests = [
            t for t in test_executions if t.result in [TestResult.FAIL, TestResult.ERROR]
        ]
        if failed_tests:
            recommendations.append(
                f"Investigate {len(failed_tests)} failed test(s) before deployment"
            )

            # Identify critical failures
            critical_failures = [
                t for t in failed_tests if self.test_suites.get(t.suite, {}).get("critical", False)
            ]
            if critical_failures:
                recommendations.append(
                    f"CRITICAL: {len(critical_failures)} critical test suite(s) failed - deployment not recommended"
                )

        # Performance recommendations
        if regression_analysis.get("performance_regression_detected", False):
            recommendations.append(
                "Performance regression detected - review recent changes for performance impact"
            )

        # Duration recommendations
        long_running_tests = [t for t in test_executions if t.duration_seconds > 600]  # 10 minutes
        if long_running_tests:
            recommendations.append(
                f"Consider optimizing {len(long_running_tests)} slow-running test(s)"
            )

        # Success rate recommendations
        success_rate = (
            len([t for t in test_executions if t.result == TestResult.PASS])
            / len(test_executions)
            * 100
        )
        if success_rate < 90:
            recommendations.append(
                f"Test success rate ({success_rate:.1f}%) below 90% - investigate test stability"
            )

        if not recommendations:
            recommendations.append("All tests passed successfully - ready for deployment")

        return recommendations

    def _determine_overall_result(self, test_executions: List[TestExecution]) -> TestResult:
        """Determine overall pipeline result."""
        # Check for critical failures
        critical_failures = [
            t
            for t in test_executions
            if t.result in [TestResult.FAIL, TestResult.ERROR]
            and self.test_suites.get(t.suite, {}).get("critical", False)
        ]

        if critical_failures:
            return TestResult.FAIL

        # Check for any failures
        failures = [t for t in test_executions if t.result in [TestResult.FAIL, TestResult.ERROR]]
        if failures:
            return TestResult.FAIL

        # All tests passed
        return TestResult.PASS

    def _store_test_results(self, report: RegressionTestReport):
        """Store test results for historical analysis."""
        # Store in memory
        self.test_history.append(report)

        # Keep only last 50 reports
        self.test_history = self.test_history[-50:]

        # Save to file
        report_file = self.test_results_dir / f"regression_report_{report.pipeline_id}.json"
        with open(report_file, "w") as f:
            json.dump(asdict(report), f, indent=2, default=str)

        # Save summary history
        history_file = self.test_results_dir / "regression_history.json"
        history_data = [asdict(r) for r in self.test_history]
        with open(history_file, "w") as f:
            json.dump(history_data, f, indent=2, default=str)

    def _update_baselines(self, report: RegressionTestReport):
        """Update performance baselines after successful runs."""
        if self.baseline_management and report.overall_result == TestResult.PASS:
            logger.info("Updating performance baselines after successful test run")
            # This would integrate with the load testing framework's baseline management
            # For now, we just log the intent

    def load_test_history(self):
        """Load test history from storage."""
        history_file = self.test_results_dir / "regression_history.json"
        if history_file.exists():
            try:
                with open(history_file, "r") as f:
                    history_data = json.load(f)

                # Convert back to dataclass instances
                for report_data in history_data:
                    # Convert test executions
                    executions = []
                    for exec_data in report_data.get("test_executions", []):
                        exec_data["timestamp"] = datetime.fromisoformat(exec_data["timestamp"])
                        executions.append(TestExecution(**exec_data))

                    # Convert report
                    report_data["test_executions"] = executions
                    report_data["execution_timestamp"] = datetime.fromisoformat(
                        report_data["execution_timestamp"]
                    )
                    report_data["overall_result"] = TestResult(report_data["overall_result"])

                    self.test_history.append(RegressionTestReport(**report_data))

                logger.info(f"Loaded {len(self.test_history)} historical test reports")

            except Exception as e:
                logger.error(f"Failed to load test history: {e}")
                self.test_history = []


# Global pipeline instance
regression_pipeline = RegressionTestingPipeline()


async def run_quick_regression() -> RegressionTestReport:
    """Run quick regression test (functional + integration only)."""
    return await regression_pipeline.run_regression_pipeline(
        [TestSuite.FUNCTIONAL, TestSuite.INTEGRATION]
    )


async def run_full_regression() -> RegressionTestReport:
    """Run full regression test suite."""
    return await regression_pipeline.run_regression_pipeline(
        [
            TestSuite.FUNCTIONAL,
            TestSuite.LOAD_TESTING,
            TestSuite.EDGE_CASES,
            TestSuite.INTEGRATION,
            TestSuite.UNIT_TESTS,
        ]
    )


async def run_performance_regression() -> RegressionTestReport:
    """Run performance-focused regression tests."""
    return await regression_pipeline.run_regression_pipeline(
        [TestSuite.LOAD_TESTING, TestSuite.FUNCTIONAL]
    )


def print_regression_report(report: RegressionTestReport):
    """Print formatted regression test report."""
    print(f"\n{'='*60}")
    print(f"REGRESSION TEST REPORT - {report.pipeline_id}")
    print(f"{'='*60}")
    print(f"Environment: {report.environment}")
    print(f"Execution Time: {report.execution_timestamp}")
    print(f"Total Duration: {report.total_duration_seconds:.1f} seconds")
    print(f"Overall Result: {report.overall_result.value.upper()}")

    print(f"\n📊 TEST SUMMARY:")
    summary = report.summary
    print(f"   Total Tests: {summary['total_tests']}")
    print(f"   Passed: {summary['passed_tests']}")
    print(f"   Failed: {summary['failed_tests']}")
    print(f"   Errors: {summary['error_tests']}")
    print(f"   Success Rate: {summary['success_rate']:.1f}%")

    print(f"\n🔍 TEST EXECUTIONS:")
    for execution in report.test_executions:
        status_icon = (
            "✅"
            if execution.result == TestResult.PASS
            else "❌" if execution.result == TestResult.FAIL else "⚠️"
        )
        print(
            f"   {status_icon} {execution.suite}: {execution.result.value} ({execution.duration_seconds:.1f}s)"
        )
        if execution.error_message:
            print(f"      Error: {execution.error_message[:100]}...")

    print(f"\n📈 REGRESSION ANALYSIS:")
    regression = report.regression_analysis
    if regression.get("status") == "completed":
        print(
            f"   Performance Regression: {'Yes' if regression.get('performance_regression_detected') else 'No'}"
        )
    else:
        print(f"   Status: {regression.get('status', 'unknown')}")

    print(f"\n📋 BASELINE COMPARISON:")
    baseline = report.baseline_comparison
    if baseline.get("status") == "completed":
        print(f"   Duration Change: {baseline.get('duration_change_percent', 0):.1f}%")
        print(f"   Success Rate Change: {baseline.get('success_rate_change', 0):.1f}%")
        print(
            f"   Performance Regression: {'Yes' if baseline.get('performance_regression') else 'No'}"
        )
        print(f"   Quality Regression: {'Yes' if baseline.get('quality_regression') else 'No'}")
    else:
        print(f"   Status: {baseline.get('status', 'unknown')}")

    print(f"\n💡 RECOMMENDATIONS:")
    for i, rec in enumerate(report.recommendations, 1):
        print(f"   {i}. {rec}")

    print(f"\n{'='*60}")


async def main():
    """Main CLI entry point for regression testing."""
    import argparse

    parser = argparse.ArgumentParser(description="Automated Regression Testing Pipeline")
    parser.add_argument(
        "--mode",
        choices=["quick", "full", "performance"],
        default="quick",
        help="Regression test mode",
    )
    parser.add_argument("--environment", default="development", help="Test environment")
    parser.add_argument(
        "--parallel", action="store_true", default=True, help="Enable parallel test execution"
    )
    parser.add_argument("--output", help="Output file for test report")

    args = parser.parse_args()

    # Configure global pipeline
    global regression_pipeline
    regression_pipeline = RegressionTestingPipeline(
        {"environment": args.environment, "parallel_execution": args.parallel}
    )

    try:
        # Run regression tests based on mode
        if args.mode == "quick":
            print("🚀 Running quick regression tests...")
            report = await run_quick_regression()
        elif args.mode == "full":
            print("🚀 Running full regression test suite...")
            report = await run_full_regression()
        elif args.mode == "performance":
            print("🚀 Running performance regression tests...")
            report = await run_performance_regression()

        # Print report
        print_regression_report(report)

        # Save to file if requested
        if args.output:
            with open(args.output, "w") as f:
                json.dump(asdict(report), f, indent=2, default=str)
            print(f"\n📄 Report saved to: {args.output}")

        # Exit with appropriate code
        exit_code = 0 if report.overall_result == TestResult.PASS else 1
        return exit_code

    except Exception as e:
        logger.error(f"Regression testing failed: {e}")
        print(f"\n💥 Regression testing failed: {e}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
