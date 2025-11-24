"""Load Testing Framework for MCP Server Performance Validation.

This module provides comprehensive load testing capabilities including:
- Concurrent user simulation
- Latency assertion testing (<100ms target)
- Regression prevention testing
- Performance baseline establishment
- Stress testing with configurable scenarios
"""

import asyncio
import statistics
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List

from loguru import logger


@dataclass
class LoadTestConfig:
    """Configuration for load testing scenarios."""

    name: str
    concurrent_users: int
    duration_seconds: int
    ramp_up_seconds: int
    target_latency_ms: float
    target_throughput_rps: float
    target_error_rate_percent: float
    operations: List[Dict[str, Any]]


@dataclass
class LoadTestResult:
    """Results from a load test execution."""

    config_name: str
    start_time: datetime
    end_time: datetime
    total_requests: int
    successful_requests: int
    failed_requests: int
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    max_latency_ms: float
    min_latency_ms: float
    throughput_rps: float
    error_rate_percent: float
    concurrent_users: int
    target_compliance: Dict[str, bool]
    errors: List[str]


@dataclass
class PerformanceBaseline:
    """Performance baseline for regression testing."""

    name: str
    established_date: datetime
    avg_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    throughput_rps: float
    error_rate_percent: float
    sample_size: int


class LoadTestingFramework:
    """Comprehensive load testing framework for MCP server."""

    def __init__(self):
        """Initialize the load testing framework."""
        self.baselines: Dict[str, PerformanceBaseline] = {}
        self.test_results: List[LoadTestResult] = []
        self.active_tests: Dict[str, bool] = {}

        # Default test configurations
        self.default_configs = self._create_default_configs()

    def _create_default_configs(self) -> List[LoadTestConfig]:
        """Create default load test configurations."""
        return [
            LoadTestConfig(
                name="light_load",
                concurrent_users=5,
                duration_seconds=30,
                ramp_up_seconds=5,
                target_latency_ms=100.0,
                target_throughput_rps=10.0,
                target_error_rate_percent=1.0,
                operations=[
                    {"type": "get_capabilities", "weight": 30},
                    {"type": "validate_transaction", "weight": 40},
                    {"type": "cache_access", "weight": 30},
                ],
            ),
            LoadTestConfig(
                name="moderate_load",
                concurrent_users=20,
                duration_seconds=60,
                ramp_up_seconds=10,
                target_latency_ms=150.0,
                target_throughput_rps=50.0,
                target_error_rate_percent=2.0,
                operations=[
                    {"type": "get_capabilities", "weight": 25},
                    {"type": "validate_transaction", "weight": 35},
                    {"type": "cache_access", "weight": 25},
                    {"type": "api_call", "weight": 15},
                ],
            ),
            LoadTestConfig(
                name="heavy_load",
                concurrent_users=50,
                duration_seconds=120,
                ramp_up_seconds=20,
                target_latency_ms=200.0,
                target_throughput_rps=100.0,
                target_error_rate_percent=3.0,
                operations=[
                    {"type": "get_capabilities", "weight": 20},
                    {"type": "validate_transaction", "weight": 30},
                    {"type": "cache_access", "weight": 20},
                    {"type": "api_call", "weight": 20},
                    {"type": "complex_operation", "weight": 10},
                ],
            ),
            LoadTestConfig(
                name="stress_test",
                concurrent_users=100,
                duration_seconds=180,
                ramp_up_seconds=30,
                target_latency_ms=500.0,
                target_throughput_rps=200.0,
                target_error_rate_percent=5.0,
                operations=[
                    {"type": "get_capabilities", "weight": 15},
                    {"type": "validate_transaction", "weight": 25},
                    {"type": "cache_access", "weight": 15},
                    {"type": "api_call", "weight": 25},
                    {"type": "complex_operation", "weight": 20},
                ],
            ),
        ]

    async def run_load_test(
        self, config: LoadTestConfig, operation_handlers: Dict[str, Callable]
    ) -> LoadTestResult:
        """Run a load test with the specified configuration.

        Args:
            config: Load test configuration
            operation_handlers: Dictionary mapping operation types to handler functions

        Returns:
            Load test results
        """
        logger.info(f"Starting load test: {config.name}")
        logger.info(f"Config: {config.concurrent_users} users, {config.duration_seconds}s duration")

        self.active_tests[config.name] = True
        start_time = datetime.now(timezone.utc)

        # Results tracking
        request_latencies: List[float] = []
        request_results: List[bool] = []
        errors: List[str] = []

        # Create semaphore for concurrent user limit
        semaphore = asyncio.Semaphore(config.concurrent_users)

        # User simulation tasks
        user_tasks = []

        # Calculate user spawn timing for ramp-up
        spawn_interval = (
            config.ramp_up_seconds / config.concurrent_users if config.concurrent_users > 0 else 0
        )

        for user_id in range(config.concurrent_users):
            # Stagger user creation during ramp-up period
            spawn_delay = user_id * spawn_interval

            task = asyncio.create_task(
                self._simulate_user(
                    user_id=user_id,
                    config=config,
                    operation_handlers=operation_handlers,
                    semaphore=semaphore,
                    spawn_delay=spawn_delay,
                    request_latencies=request_latencies,
                    request_results=request_results,
                    errors=errors,
                )
            )
            user_tasks.append(task)

        # Wait for all users to complete
        await asyncio.gather(*user_tasks, return_exceptions=True)

        end_time = datetime.now(timezone.utc)
        self.active_tests[config.name] = False

        # Calculate results
        result = self._calculate_results(
            config=config,
            start_time=start_time,
            end_time=end_time,
            request_latencies=request_latencies,
            request_results=request_results,
            errors=errors,
        )

        self.test_results.append(result)

        logger.info(f"Load test completed: {config.name}")
        logger.info(
            f"Results: {result.successful_requests}/{result.total_requests} successful, "
            f"avg latency: {result.avg_latency_ms:.2f}ms, "
            f"throughput: {result.throughput_rps:.2f} RPS"
        )

        return result

    async def _simulate_user(
        self,
        user_id: int,
        config: LoadTestConfig,
        operation_handlers: Dict[str, Callable],
        semaphore: asyncio.Semaphore,
        spawn_delay: float,
        request_latencies: List[float],
        request_results: List[bool],
        errors: List[str],
    ):
        """Simulate a single user's load testing behavior.

        Args:
            user_id: Unique user identifier
            config: Load test configuration
            operation_handlers: Operation handler functions
            semaphore: Concurrency control semaphore
            spawn_delay: Delay before user starts
            request_latencies: Shared list for latency tracking
            request_results: Shared list for success/failure tracking
            errors: Shared list for error tracking
        """
        # Wait for spawn delay (ramp-up)
        if spawn_delay > 0:
            await asyncio.sleep(spawn_delay)

        user_start_time = time.time()
        user_end_time = user_start_time + config.duration_seconds

        logger.debug(f"User {user_id} starting load test simulation")

        while time.time() < user_end_time and self.active_tests.get(config.name, False):
            async with semaphore:
                try:
                    # Select operation based on weights
                    operation = self._select_weighted_operation(config.operations)
                    operation_type = operation["type"]

                    if operation_type not in operation_handlers:
                        errors.append(f"No handler for operation type: {operation_type}")
                        request_results.append(False)
                        continue

                    # Execute operation and measure latency
                    start_time = time.time()

                    try:
                        await operation_handlers[operation_type](user_id)
                        success = True
                    except Exception as e:
                        success = False
                        errors.append(f"Operation {operation_type} failed: {str(e)}")

                    latency_ms = (time.time() - start_time) * 1000

                    # Record results (thread-safe append)
                    request_latencies.append(latency_ms)
                    request_results.append(success)

                    # Small delay between requests to simulate realistic usage
                    await asyncio.sleep(0.1)

                except Exception as e:
                    errors.append(f"User {user_id} error: {str(e)}")
                    request_results.append(False)

        logger.debug(f"User {user_id} completed load test simulation")

    def _select_weighted_operation(self, operations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Select an operation based on weighted probabilities.

        Args:
            operations: List of operations with weights

        Returns:
            Selected operation
        """
        import random

        total_weight = sum(op.get("weight", 1) for op in operations)
        random_value = random.uniform(0, total_weight)

        current_weight = 0
        for operation in operations:
            current_weight += operation.get("weight", 1)
            if random_value <= current_weight:
                return operation

        # Fallback to first operation
        return operations[0] if operations else {"type": "default", "weight": 1}

    def _calculate_results(
        self,
        config: LoadTestConfig,
        start_time: datetime,
        end_time: datetime,
        request_latencies: List[float],
        request_results: List[bool],
        errors: List[str],
    ) -> LoadTestResult:
        """Calculate load test results from collected data.

        Args:
            config: Load test configuration
            start_time: Test start time
            end_time: Test end time
            request_latencies: List of request latencies
            request_results: List of request success/failure
            errors: List of error messages

        Returns:
            Calculated load test results
        """
        total_requests = len(request_results)
        successful_requests = sum(request_results)
        failed_requests = total_requests - successful_requests

        if request_latencies:
            sorted_latencies = sorted(request_latencies)
            avg_latency_ms = statistics.mean(request_latencies)
            p50_latency_ms = statistics.median(request_latencies)

            # Calculate percentiles safely
            n = len(sorted_latencies)
            if n >= 20:
                p95_index = int(n * 0.95)
                p95_latency_ms = sorted_latencies[p95_index]
            else:
                # For small samples, use a conservative estimate
                p95_latency_ms = max(
                    avg_latency_ms, sorted_latencies[int(n * 0.9)] if n > 1 else sorted_latencies[0]
                )

            if n >= 100:
                p99_index = int(n * 0.99)
                p99_latency_ms = sorted_latencies[p99_index]
            else:
                # For small samples, use max or conservative estimate
                p99_latency_ms = max(p95_latency_ms, sorted_latencies[-1])

            max_latency_ms = max(request_latencies)
            min_latency_ms = min(request_latencies)
        else:
            avg_latency_ms = p50_latency_ms = p95_latency_ms = p99_latency_ms = 0.0
            max_latency_ms = min_latency_ms = 0.0

        duration_seconds = (end_time - start_time).total_seconds()
        throughput_rps = total_requests / duration_seconds if duration_seconds > 0 else 0.0
        error_rate_percent = (failed_requests / total_requests * 100) if total_requests > 0 else 0.0

        # Check target compliance
        target_compliance = {
            "latency_p95": p95_latency_ms <= config.target_latency_ms,
            "latency_p99": p99_latency_ms
            <= config.target_latency_ms * 1.5,  # Allow 50% margin for P99
            "throughput": throughput_rps >= config.target_throughput_rps,
            "error_rate": error_rate_percent <= config.target_error_rate_percent,
        }

        return LoadTestResult(
            config_name=config.name,
            start_time=start_time,
            end_time=end_time,
            total_requests=total_requests,
            successful_requests=successful_requests,
            failed_requests=failed_requests,
            avg_latency_ms=avg_latency_ms,
            p50_latency_ms=p50_latency_ms,
            p95_latency_ms=p95_latency_ms,
            p99_latency_ms=p99_latency_ms,
            max_latency_ms=max_latency_ms,
            min_latency_ms=min_latency_ms,
            throughput_rps=throughput_rps,
            error_rate_percent=error_rate_percent,
            concurrent_users=config.concurrent_users,
            target_compliance=target_compliance,
            errors=errors[:100],  # Limit error list size
        )

    def establish_baseline(
        self, test_name: str, results: List[LoadTestResult]
    ) -> PerformanceBaseline:
        """Establish performance baseline from test results.

        Args:
            test_name: Name for the baseline
            results: List of test results to analyze

        Returns:
            Established performance baseline
        """
        if not results:
            raise ValueError("Cannot establish baseline from empty results")

        # Calculate baseline metrics from successful results
        successful_results = [r for r in results if r.error_rate_percent <= 5.0]

        if not successful_results:
            logger.warning("No successful results for baseline, using all results")
            successful_results = results

        avg_latencies = [r.avg_latency_ms for r in successful_results]
        p95_latencies = [r.p95_latency_ms for r in successful_results]
        p99_latencies = [r.p99_latency_ms for r in successful_results]
        throughputs = [r.throughput_rps for r in successful_results]
        error_rates = [r.error_rate_percent for r in successful_results]

        baseline = PerformanceBaseline(
            name=test_name,
            established_date=datetime.now(timezone.utc),
            avg_latency_ms=statistics.mean(avg_latencies),
            p95_latency_ms=statistics.mean(p95_latencies),
            p99_latency_ms=statistics.mean(p99_latencies),
            throughput_rps=statistics.mean(throughputs),
            error_rate_percent=statistics.mean(error_rates),
            sample_size=len(successful_results),
        )

        self.baselines[test_name] = baseline

        logger.info(
            f"Established baseline '{test_name}': "
            f"avg latency {baseline.avg_latency_ms:.2f}ms, "
            f"P95 {baseline.p95_latency_ms:.2f}ms, "
            f"throughput {baseline.throughput_rps:.2f} RPS"
        )

        return baseline

    def check_regression(self, test_result: LoadTestResult, baseline_name: str) -> Dict[str, Any]:
        """Check for performance regression against baseline.

        Args:
            test_result: Recent test result to check
            baseline_name: Name of baseline to compare against

        Returns:
            Regression analysis results
        """
        if baseline_name not in self.baselines:
            raise ValueError(f"Baseline '{baseline_name}' not found")

        baseline = self.baselines[baseline_name]

        # Define regression thresholds (percentage increase that indicates regression)
        regression_thresholds = {
            "avg_latency": 20.0,  # 20% increase in average latency
            "p95_latency": 25.0,  # 25% increase in P95 latency
            "p99_latency": 30.0,  # 30% increase in P99 latency
            "throughput": -15.0,  # 15% decrease in throughput
            "error_rate": 100.0,  # 100% increase in error rate (doubling)
        }

        # Calculate percentage changes
        changes = {
            "avg_latency": (
                (test_result.avg_latency_ms - baseline.avg_latency_ms) / baseline.avg_latency_ms
            )
            * 100,
            "p95_latency": (
                (test_result.p95_latency_ms - baseline.p95_latency_ms) / baseline.p95_latency_ms
            )
            * 100,
            "p99_latency": (
                (test_result.p99_latency_ms - baseline.p99_latency_ms) / baseline.p99_latency_ms
            )
            * 100,
            "throughput": (
                (test_result.throughput_rps - baseline.throughput_rps) / baseline.throughput_rps
            )
            * 100,
            "error_rate": (
                (test_result.error_rate_percent - baseline.error_rate_percent)
                / max(baseline.error_rate_percent, 0.1)
            )
            * 100,
        }

        # Check for regressions
        regressions = {}
        for metric, change in changes.items():
            threshold = regression_thresholds[metric]

            if metric == "throughput":
                # For throughput, negative change is bad
                is_regression = change < threshold
            else:
                # For latency and error rate, positive change is bad
                is_regression = change > threshold

            regressions[metric] = {
                "change_percent": change,
                "threshold_percent": threshold,
                "is_regression": is_regression,
                "current_value": getattr(
                    test_result,
                    metric.replace("_", "_")
                    + (
                        "_ms"
                        if "latency" in metric
                        else "_rps" if metric == "throughput" else "_percent"
                    ),
                ),
                "baseline_value": getattr(
                    baseline,
                    metric.replace("_", "_")
                    + (
                        "_ms"
                        if "latency" in metric
                        else "_rps" if metric == "throughput" else "_percent"
                    ),
                ),
            }

        # Overall regression status
        has_regression = any(r["is_regression"] for r in regressions.values())

        return {
            "baseline_name": baseline_name,
            "test_result": test_result.config_name,
            "has_regression": has_regression,
            "regressions": regressions,
            "summary": f"{'REGRESSION DETECTED' if has_regression else 'NO REGRESSION'} compared to baseline '{baseline_name}'",
        }

    def get_test_summary(self) -> Dict[str, Any]:
        """Get summary of all load test results.

        Returns:
            Summary of test results and baselines
        """
        if not self.test_results:
            return {"message": "No load test results available"}

        # Calculate overall statistics
        recent_results = self.test_results[-10:]  # Last 10 tests

        avg_latencies = [r.avg_latency_ms for r in recent_results]
        p95_latencies = [r.p95_latency_ms for r in recent_results]
        throughputs = [r.throughput_rps for r in recent_results]
        error_rates = [r.error_rate_percent for r in recent_results]

        return {
            "total_tests_run": len(self.test_results),
            "recent_tests": len(recent_results),
            "baselines_established": len(self.baselines),
            "recent_performance": {
                "avg_latency_ms": statistics.mean(avg_latencies) if avg_latencies else 0,
                "p95_latency_ms": statistics.mean(p95_latencies) if p95_latencies else 0,
                "avg_throughput_rps": statistics.mean(throughputs) if throughputs else 0,
                "avg_error_rate_percent": statistics.mean(error_rates) if error_rates else 0,
            },
            "available_configs": [config.name for config in self.default_configs],
            "baseline_names": list(self.baselines.keys()),
        }


# Global load testing framework instance
load_testing_framework = LoadTestingFramework()


async def create_mcp_operation_handlers() -> Dict[str, Callable]:
    """Create operation handlers for MCP server load testing.

    Returns:
        Dictionary of operation handlers for load testing
    """
    from ..capability_manager.cache import CapabilityCache
    from ..core.response_cache import response_cache

    # Create test cache for operations
    test_cache = CapabilityCache(ttl=300)

    async def get_capabilities_operation(user_id: int):
        """Simulate UCM capabilities retrieval."""
        resource_types = ["products", "subscriptions", "alerts", "customers"]
        resource_type = resource_types[user_id % len(resource_types)]

        # Simulate cache lookup
        cache_key = f"capabilities_{resource_type}_{user_id}"
        result = await test_cache.get(cache_key)

        if result is None:
            # Simulate API call delay
            await asyncio.sleep(0.01)  # 10ms simulated API call
            result = {
                "resource_type": resource_type,
                "capabilities": ["create", "read", "update", "delete"],
                "user_id": user_id,
            }
            await test_cache.set(cache_key, result)

        return result

    async def validate_transaction_operation(user_id: int):
        """Simulate transaction validation."""
        # Simulate validation logic
        await asyncio.sleep(0.005)  # 5ms validation time

        transaction_data = {
            "model": "gpt-4o",
            "provider": "openai",
            "input_tokens": 1000 + (user_id * 10),
            "output_tokens": 500 + (user_id * 5),
            "duration_ms": 2000,
            "user_id": user_id,
        }

        # Simulate validation result
        return {"valid": True, "transaction": transaction_data}

    async def cache_access_operation(user_id: int):
        """Simulate cache access patterns."""
        cache_key = f"cache_test_{user_id % 10}"  # Create some cache overlap

        # Try to get from cache
        result = await response_cache.get_cached_response("api", cache_key)

        if result is None:
            # Cache miss - simulate data generation
            await asyncio.sleep(0.002)  # 2ms data generation
            result = {"data": f"generated_data_{user_id}", "timestamp": time.time()}
            await response_cache.set_cached_response("api", cache_key, result)

        return result

    async def api_call_operation(user_id: int):
        """Simulate API call with variable latency."""
        # Simulate variable API latency (10-50ms)
        import random

        latency = random.uniform(0.01, 0.05)
        await asyncio.sleep(latency)

        return {
            "api_response": f"response_for_user_{user_id}",
            "latency_ms": latency * 1000,
            "status": "success",
        }

    async def complex_operation(user_id: int):
        """Simulate complex operation with multiple steps."""
        # Step 1: Capability check
        await get_capabilities_operation(user_id)

        # Step 2: Validation
        await validate_transaction_operation(user_id)

        # Step 3: Cache access
        await cache_access_operation(user_id)

        # Step 4: Final processing
        await asyncio.sleep(0.003)  # 3ms processing time

        return {"complex_result": f"completed_for_user_{user_id}"}

    return {
        "get_capabilities": get_capabilities_operation,
        "validate_transaction": validate_transaction_operation,
        "cache_access": cache_access_operation,
        "api_call": api_call_operation,
        "complex_operation": complex_operation,
    }


async def run_performance_regression_test() -> Dict[str, Any]:
    """Run performance regression test suite.

    Returns:
        Regression test results
    """
    logger.info("Starting performance regression test suite...")

    # Get operation handlers
    operation_handlers = await create_mcp_operation_handlers()

    # Run light load test for regression checking
    light_config = load_testing_framework.default_configs[0]  # light_load

    # Run test
    result = await load_testing_framework.run_load_test(light_config, operation_handlers)

    # Check against baseline if it exists
    baseline_name = "regression_baseline"
    regression_results = None

    if baseline_name in load_testing_framework.baselines:
        regression_results = load_testing_framework.check_regression(result, baseline_name)
    else:
        # Establish baseline if it doesn't exist
        load_testing_framework.establish_baseline(baseline_name, [result])
        regression_results = {"message": "Baseline established", "baseline_name": baseline_name}

    return {
        "test_result": asdict(result),
        "regression_analysis": regression_results,
        "compliance_summary": {
            "latency_target_met": result.p95_latency_ms <= 100.0,
            "throughput_target_met": result.throughput_rps >= 10.0,
            "error_rate_target_met": result.error_rate_percent <= 1.0,
            "overall_pass": all(result.target_compliance.values()),
        },
    }


async def run_comprehensive_load_test_suite() -> Dict[str, Any]:
    """Run comprehensive load test suite with all configurations.

    Returns:
        Complete test suite results
    """
    logger.info("Starting comprehensive load test suite...")

    # Get operation handlers
    operation_handlers = await create_mcp_operation_handlers()

    suite_results = []

    # Run all default configurations
    for config in load_testing_framework.default_configs:
        logger.info(f"Running load test configuration: {config.name}")

        try:
            result = await load_testing_framework.run_load_test(config, operation_handlers)
            suite_results.append(result)

            # Log key metrics
            logger.info(f"Config {config.name} completed:")
            logger.info(
                f"  - P95 Latency: {result.p95_latency_ms:.2f}ms (target: {config.target_latency_ms}ms)"
            )
            logger.info(
                f"  - Throughput: {result.throughput_rps:.2f} RPS (target: {config.target_throughput_rps} RPS)"
            )
            logger.info(
                f"  - Error Rate: {result.error_rate_percent:.2f}% (target: {config.target_error_rate_percent}%)"
            )
            logger.info(f"  - Target Compliance: {all(result.target_compliance.values())}")

        except Exception as e:
            logger.error(f"Load test {config.name} failed: {e}")
            continue

    # Establish baselines for each configuration
    for result in suite_results:
        baseline_name = f"{result.config_name}_baseline"
        if baseline_name not in load_testing_framework.baselines:
            load_testing_framework.establish_baseline(baseline_name, [result])

    # Calculate suite summary
    successful_tests = [r for r in suite_results if all(r.target_compliance.values())]

    suite_summary = {
        "total_configurations": len(load_testing_framework.default_configs),
        "completed_tests": len(suite_results),
        "successful_tests": len(successful_tests),
        "success_rate_percent": (
            (len(successful_tests) / len(suite_results) * 100) if suite_results else 0
        ),
        "overall_performance": {
            "avg_p95_latency_ms": (
                statistics.mean([r.p95_latency_ms for r in suite_results]) if suite_results else 0
            ),
            "avg_throughput_rps": (
                statistics.mean([r.throughput_rps for r in suite_results]) if suite_results else 0
            ),
            "avg_error_rate_percent": (
                statistics.mean([r.error_rate_percent for r in suite_results])
                if suite_results
                else 0
            ),
        },
        "test_results": [asdict(r) for r in suite_results],
    }

    logger.info(
        f"Load test suite completed: {len(successful_tests)}/{len(suite_results)} tests passed"
    )

    return suite_summary
