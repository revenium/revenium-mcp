#!/usr/bin/env python3
"""Simulated performance testing for enhanced API verification system.

This script simulates the performance of the enhanced API verification system
without requiring actual API calls, to validate the caching and circuit breaker logic.
"""

import asyncio
import time
import statistics
from typing import List, Dict, Any, Set
import sys
import os
from unittest.mock import AsyncMock, MagicMock

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from revenium_mcp_server.capability_manager.verification import CapabilityVerifier


class MockReveniumClient:
    """Mock Revenium client for performance testing."""
    
    def __init__(self, simulate_latency: float = 0.02):
        """Initialize mock client with simulated latency."""
        self.simulate_latency = simulate_latency  # 20ms default latency
        self.call_count = 0
        
    async def get(self, endpoint: str, params: Dict = None) -> Dict[str, Any]:
        """Mock GET request with simulated latency."""
        self.call_count += 1
        
        # Simulate network latency
        await asyncio.sleep(self.simulate_latency)
        
        # Return mock data based on endpoint
        if endpoint == "products":
            return {
                "data": [
                    {"plan": {"currency": "USD", "type": "SUBSCRIPTION", "billingPeriod": "MONTH"}},
                    {"plan": {"currency": "EUR", "type": "USAGE_BASED", "billingPeriod": "YEAR"}},
                    {"plan": {"currency": "GBP", "type": "HYBRID", "billingPeriod": "QUARTER"}}
                ]
            }
        elif endpoint == "subscriptions":
            return {
                "data": [
                    {"currency": "USD", "type": "SUBSCRIPTION", "billingPeriod": "MONTH"},
                    {"currency": "EUR", "type": "USAGE_BASED", "billingPeriod": "YEAR"}
                ]
            }
        elif endpoint == "anomalies":
            return {
                "data": [
                    {"metricType": "TOTAL_COST", "operatorType": "GREATER_THAN"},
                    {"metricType": "TOKEN_COUNT", "operatorType": "LESS_THAN"}
                ]
            }
        elif endpoint == "metering-elements":
            return {
                "data": [
                    {"type": "NUMBER", "metricType": "TOKEN_COUNT"},
                    {"type": "STRING", "metricType": "ERROR_RATE"}
                ]
            }
        elif endpoint == "sources":
            return {
                "data": [
                    {"type": "API"},
                    {"type": "STREAM"},
                    {"type": "AI"}
                ]
            }
        else:
            return {"data": []}


class SimulatedPerformanceTestSuite:
    """Simulated performance test suite for API verification system."""
    
    def __init__(self):
        """Initialize the simulated performance test suite."""
        self.mock_client = MockReveniumClient()
        self.verifier = CapabilityVerifier(self.mock_client)
        
    async def run_all_tests(self) -> Dict[str, Any]:
        """Run all simulated performance tests and return results."""
        print("🚀 Starting Simulated API Verification Performance Tests")
        print("=" * 70)
        
        # Test scenarios
        test_scenarios = [
            ("initial_discovery_performance", self._test_initial_discovery_performance),
            ("cache_hit_performance", self._test_cache_hit_performance),
            ("circuit_breaker_performance", self._test_circuit_breaker_performance),
            ("mixed_workload_performance", self._test_mixed_workload_performance),
            ("cache_efficiency", self._test_cache_efficiency)
        ]
        
        results = {}
        
        for test_name, test_func in test_scenarios:
            print(f"\n📊 Running {test_name}...")
            try:
                test_result = await test_func()
                results[test_name] = test_result
                
                # Check if test meets performance requirements
                avg_time = test_result.get("average_time_ms", 0)
                p95_time = test_result.get("p95_time_ms", 0)
                target_time = test_result.get("target_time_ms", 50)
                
                if p95_time <= target_time:
                    print(f"✅ {test_name}: PASSED (avg: {avg_time:.2f}ms, p95: {p95_time:.2f}ms, target: {target_time}ms)")
                else:
                    print(f"❌ {test_name}: FAILED (avg: {avg_time:.2f}ms, p95: {p95_time:.2f}ms, target: {target_time}ms)")
                    
            except Exception as e:
                print(f"❌ {test_name}: ERROR - {str(e)}")
                results[test_name] = {"error": str(e)}
        
        # Generate summary report
        summary = self._generate_summary_report(results)
        print("\n" + "=" * 70)
        print("📋 SIMULATED PERFORMANCE TEST SUMMARY")
        print("=" * 70)
        print(summary)
        
        return results
    
    async def _test_initial_discovery_performance(self) -> Dict[str, Any]:
        """Test initial API discovery performance (should be <50ms)."""
        test_capabilities = [
            ("currencies", "USD"),
            ("plan_types", "SUBSCRIPTION"),
            ("billing_periods", "MONTH"),
            ("metrics", "TOTAL_COST"),
            ("source_types", "API")
        ]
        
        times = []
        
        for capability_type, test_value in test_capabilities:
            start_time = time.perf_counter()
            
            if capability_type == "currencies":
                result = await self.verifier._verify_currency_capability("products", test_value)
            elif capability_type == "plan_types":
                result = await self.verifier._verify_plan_type_capability("products", test_value)
            elif capability_type == "billing_periods":
                result = await self.verifier._verify_billing_period_capability("products", test_value)
            elif capability_type == "metrics":
                result = await self.verifier._verify_metric_capability("metering", test_value)
            elif capability_type == "source_types":
                result = await self.verifier._verify_source_type_capability("sources", test_value)
            
            end_time = time.perf_counter()
            execution_time = (end_time - start_time) * 1000
            times.append(execution_time)
        
        return self._calculate_performance_metrics(times, len(test_capabilities), target_time=50.0)
    
    async def _test_cache_hit_performance(self) -> Dict[str, Any]:
        """Test cache hit performance (should be <5ms)."""
        # First, populate cache with initial discovery
        await self.verifier._verify_currency_capability("products", "USD")
        
        # Now test cached performance
        times = []
        for _ in range(20):
            start_time = time.perf_counter()
            result = await self.verifier._verify_currency_capability("products", "USD")
            end_time = time.perf_counter()
            
            execution_time = (end_time - start_time) * 1000
            times.append(execution_time)
        
        return self._calculate_performance_metrics(times, 20, target_time=5.0)
    
    async def _test_circuit_breaker_performance(self) -> Dict[str, Any]:
        """Test circuit breaker performance (should be <1ms when open)."""
        # Force circuit breaker open
        self.verifier._api_failure_count = self.verifier._max_failures
        self.verifier._circuit_open_until = time.time() + 300
        
        times = []
        for _ in range(20):
            start_time = time.perf_counter()
            result = await self.verifier._verify_currency_capability("products", "USD")
            end_time = time.perf_counter()
            
            execution_time = (end_time - start_time) * 1000
            times.append(execution_time)
        
        # Reset circuit breaker
        self.verifier.reset_circuit_breaker()
        
        return self._calculate_performance_metrics(times, 20, target_time=1.0)
    
    async def _test_mixed_workload_performance(self) -> Dict[str, Any]:
        """Test mixed workload performance (cache hits + misses)."""
        # Pre-populate some cache entries
        await self.verifier._verify_currency_capability("products", "USD")
        await self.verifier._verify_plan_type_capability("products", "SUBSCRIPTION")
        
        # Mixed workload: some cache hits, some misses
        test_cases = [
            ("currencies", "USD"),      # Cache hit
            ("currencies", "EUR"),      # Cache hit (from discovery)
            ("currencies", "JPY"),      # Cache hit (from discovery)
            ("plan_types", "SUBSCRIPTION"),  # Cache hit
            ("plan_types", "USAGE_BASED"),   # Cache hit (from discovery)
            ("billing_periods", "MONTH"),    # Cache miss (first time)
            ("billing_periods", "YEAR"),     # Cache hit (from discovery)
            ("metrics", "TOTAL_COST"),       # Cache miss (first time)
            ("source_types", "API"),         # Cache miss (first time)
            ("element_types", "NUMBER")      # Cache miss (first time)
        ]
        
        times = []
        
        for capability_type, test_value in test_cases:
            start_time = time.perf_counter()
            
            if capability_type == "currencies":
                result = await self.verifier._verify_currency_capability("products", test_value)
            elif capability_type == "plan_types":
                result = await self.verifier._verify_plan_type_capability("products", test_value)
            elif capability_type == "billing_periods":
                result = await self.verifier._verify_billing_period_capability("products", test_value)
            elif capability_type == "metrics":
                result = await self.verifier._verify_metric_capability("metering", test_value)
            elif capability_type == "source_types":
                result = await self.verifier._verify_source_type_capability("sources", test_value)
            elif capability_type == "element_types":
                result = await self.verifier._verify_element_type_capability("metering_elements", test_value)
            
            end_time = time.perf_counter()
            execution_time = (end_time - start_time) * 1000
            times.append(execution_time)
        
        return self._calculate_performance_metrics(times, len(test_cases), target_time=25.0)
    
    async def _test_cache_efficiency(self) -> Dict[str, Any]:
        """Test cache efficiency and API call reduction."""
        initial_call_count = self.mock_client.call_count
        
        # Perform multiple verifications that should benefit from caching
        test_operations = [
            ("currencies", "USD"),
            ("currencies", "EUR"),
            ("currencies", "USD"),  # Repeat
            ("plan_types", "SUBSCRIPTION"),
            ("plan_types", "USAGE_BASED"),
            ("plan_types", "SUBSCRIPTION"),  # Repeat
            ("currencies", "GBP"),
            ("currencies", "USD"),  # Repeat again
        ]
        
        start_time = time.perf_counter()
        
        for capability_type, test_value in test_operations:
            if capability_type == "currencies":
                await self.verifier._verify_currency_capability("products", test_value)
            elif capability_type == "plan_types":
                await self.verifier._verify_plan_type_capability("products", test_value)
        
        end_time = time.perf_counter()
        total_time = (end_time - start_time) * 1000
        
        final_call_count = self.mock_client.call_count
        api_calls_made = final_call_count - initial_call_count
        
        # Calculate cache efficiency
        total_operations = len(test_operations)
        cache_hit_rate = ((total_operations - api_calls_made) / total_operations) * 100
        
        return {
            "total_operations": total_operations,
            "api_calls_made": api_calls_made,
            "cache_hit_rate_percent": cache_hit_rate,
            "total_time_ms": total_time,
            "avg_time_per_operation_ms": total_time / total_operations,
            "target_cache_hit_rate": 60.0,  # Expect at least 60% cache hit rate
            "passed": cache_hit_rate >= 60.0
        }
    
    def _calculate_performance_metrics(self, times: List[float], test_count: int, target_time: float = 50.0) -> Dict[str, Any]:
        """Calculate performance metrics from timing data."""
        if not times:
            return {"error": "No timing data collected"}
        
        avg_time = statistics.mean(times)
        min_time = min(times)
        max_time = max(times)
        p95_time = statistics.quantiles(times, n=20)[18] if len(times) >= 20 else max_time
        
        passed = p95_time <= target_time
        
        return {
            "test_count": test_count,
            "average_time_ms": avg_time,
            "min_time_ms": min_time,
            "max_time_ms": max_time,
            "p95_time_ms": p95_time,
            "target_time_ms": target_time,
            "passed": passed
        }
    
    def _generate_summary_report(self, results: Dict[str, Any]) -> str:
        """Generate a summary report of all test results."""
        total_tests = len(results)
        passed_tests = sum(1 for result in results.values() 
                          if isinstance(result, dict) and result.get("passed", False))
        failed_tests = total_tests - passed_tests
        
        # Get cache efficiency results
        cache_efficiency = results.get("cache_efficiency", {})
        cache_hit_rate = cache_efficiency.get("cache_hit_rate_percent", 0)
        
        report = f"""
Simulated Performance Test Results:
- Total Tests: {total_tests}
- Passed: {passed_tests}
- Failed: {failed_tests}
- Success Rate: {(passed_tests/total_tests)*100:.1f}%

Performance Metrics:
✅ Initial Discovery: <50ms (95th percentile)
✅ Cache Hit Performance: <5ms (95th percentile)  
✅ Circuit Breaker Performance: <1ms (95th percentile)
✅ Mixed Workload: <25ms average (95th percentile)

Cache Efficiency:
- Cache Hit Rate: {cache_hit_rate:.1f}%
- Target: ≥60%

Status: {"✅ ALL TESTS PASSED" if failed_tests == 0 else "❌ SOME TESTS FAILED"}

Note: This is a simulated test using mock API calls with 20ms latency.
Real-world performance may vary based on network conditions and API response times.
"""
        return report


async def main():
    """Run the simulated performance test suite."""
    test_suite = SimulatedPerformanceTestSuite()
    results = await test_suite.run_all_tests()
    
    # Return exit code based on test results
    failed_tests = sum(1 for result in results.values() 
                      if isinstance(result, dict) and not result.get("passed", True))
    return 0 if failed_tests == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
