#!/usr/bin/env python3
"""Performance testing for enhanced API verification system.

This script tests the performance of the enhanced API verification system
to ensure it meets the <50ms UCM capability lookup requirement.
"""

import asyncio
import time
import statistics
from typing import List, Dict, Any
import sys
import os

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from revenium_mcp_server.capability_manager.verification import CapabilityVerifier
from revenium_mcp_server.client import ReveniumClient


class PerformanceTestSuite:
    """Performance test suite for API verification system."""
    
    def __init__(self):
        """Initialize the performance test suite."""
        self.client = ReveniumClient()
        self.verifier = CapabilityVerifier(self.client)
        self.test_results: Dict[str, List[float]] = {}
        
    async def run_all_tests(self) -> Dict[str, Any]:
        """Run all performance tests and return results."""
        print("🚀 Starting API Verification Performance Tests")
        print("=" * 60)
        
        # Test scenarios
        test_scenarios = [
            ("currency_verification", self._test_currency_verification),
            ("plan_type_verification", self._test_plan_type_verification),
            ("billing_period_verification", self._test_billing_period_verification),
            ("metrics_verification", self._test_metrics_verification),
            ("source_type_verification", self._test_source_type_verification),
            ("element_type_verification", self._test_element_type_verification),
            ("cache_performance", self._test_cache_performance),
            ("circuit_breaker_performance", self._test_circuit_breaker_performance)
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
                
                if p95_time <= 50:
                    print(f"✅ {test_name}: PASSED (avg: {avg_time:.2f}ms, p95: {p95_time:.2f}ms)")
                else:
                    print(f"❌ {test_name}: FAILED (avg: {avg_time:.2f}ms, p95: {p95_time:.2f}ms)")
                    
            except Exception as e:
                print(f"❌ {test_name}: ERROR - {str(e)}")
                results[test_name] = {"error": str(e)}
        
        # Generate summary report
        summary = self._generate_summary_report(results)
        print("\n" + "=" * 60)
        print("📋 PERFORMANCE TEST SUMMARY")
        print("=" * 60)
        print(summary)
        
        return results
    
    async def _test_currency_verification(self) -> Dict[str, Any]:
        """Test currency verification performance."""
        test_currencies = ["USD", "EUR", "GBP", "CAD", "AUD", "JPY", "CHF", "SEK"]
        times = []
        
        for currency in test_currencies:
            start_time = time.perf_counter()
            result = await self.verifier._verify_currency_capability("products", currency)
            end_time = time.perf_counter()
            
            execution_time = (end_time - start_time) * 1000  # Convert to milliseconds
            times.append(execution_time)
        
        return self._calculate_performance_metrics(times, len(test_currencies))
    
    async def _test_plan_type_verification(self) -> Dict[str, Any]:
        """Test plan type verification performance."""
        test_plan_types = ["SUBSCRIPTION", "USAGE_BASED", "HYBRID", "ONE_TIME"]
        times = []
        
        for plan_type in test_plan_types:
            start_time = time.perf_counter()
            result = await self.verifier._verify_plan_type_capability("products", plan_type)
            end_time = time.perf_counter()
            
            execution_time = (end_time - start_time) * 1000
            times.append(execution_time)
        
        return self._calculate_performance_metrics(times, len(test_plan_types))
    
    async def _test_billing_period_verification(self) -> Dict[str, Any]:
        """Test billing period verification performance."""
        test_periods = ["MONTH", "YEAR", "QUARTER", "WEEK", "DAY"]
        times = []
        
        for period in test_periods:
            start_time = time.perf_counter()
            result = await self.verifier._verify_billing_period_capability("products", period)
            end_time = time.perf_counter()
            
            execution_time = (end_time - start_time) * 1000
            times.append(execution_time)
        
        return self._calculate_performance_metrics(times, len(test_periods))
    
    async def _test_metrics_verification(self) -> Dict[str, Any]:
        """Test metrics verification performance."""
        test_metrics = ["TOTAL_COST", "TOKEN_COUNT", "ERROR_RATE", "TOKENS_PER_MINUTE", "REQUESTS_PER_MINUTE"]
        times = []
        
        for metric in test_metrics:
            start_time = time.perf_counter()
            result = await self.verifier._verify_metric_capability("metering", metric)
            end_time = time.perf_counter()
            
            execution_time = (end_time - start_time) * 1000
            times.append(execution_time)
        
        return self._calculate_performance_metrics(times, len(test_metrics))
    
    async def _test_source_type_verification(self) -> Dict[str, Any]:
        """Test source type verification performance."""
        test_source_types = ["API", "STREAM", "AI", "WEBHOOK", "DATABASE"]
        times = []
        
        for source_type in test_source_types:
            start_time = time.perf_counter()
            result = await self.verifier._verify_source_type_capability("sources", source_type)
            end_time = time.perf_counter()
            
            execution_time = (end_time - start_time) * 1000
            times.append(execution_time)
        
        return self._calculate_performance_metrics(times, len(test_source_types))
    
    async def _test_element_type_verification(self) -> Dict[str, Any]:
        """Test element type verification performance."""
        test_element_types = ["NUMBER", "STRING", "BOOLEAN", "DECIMAL", "INTEGER"]
        times = []
        
        for element_type in test_element_types:
            start_time = time.perf_counter()
            result = await self.verifier._verify_element_type_capability("metering_elements", element_type)
            end_time = time.perf_counter()
            
            execution_time = (end_time - start_time) * 1000
            times.append(execution_time)
        
        return self._calculate_performance_metrics(times, len(test_element_types))
    
    async def _test_cache_performance(self) -> Dict[str, Any]:
        """Test cache performance (should be <5ms for cached results)."""
        # First, populate cache
        await self.verifier._verify_currency_capability("products", "USD")
        
        # Now test cached performance
        times = []
        for _ in range(10):
            start_time = time.perf_counter()
            result = await self.verifier._verify_currency_capability("products", "USD")
            end_time = time.perf_counter()
            
            execution_time = (end_time - start_time) * 1000
            times.append(execution_time)
        
        return self._calculate_performance_metrics(times, 10, cache_test=True)
    
    async def _test_circuit_breaker_performance(self) -> Dict[str, Any]:
        """Test circuit breaker performance (should be <1ms when open)."""
        # Force circuit breaker open
        self.verifier._api_failure_count = self.verifier._max_failures
        self.verifier._circuit_open_until = time.time() + 300
        
        times = []
        for _ in range(10):
            start_time = time.perf_counter()
            result = await self.verifier._verify_currency_capability("products", "USD")
            end_time = time.perf_counter()
            
            execution_time = (end_time - start_time) * 1000
            times.append(execution_time)
        
        # Reset circuit breaker
        self.verifier.reset_circuit_breaker()
        
        return self._calculate_performance_metrics(times, 10, circuit_breaker_test=True)
    
    def _calculate_performance_metrics(self, times: List[float], test_count: int, 
                                     cache_test: bool = False, circuit_breaker_test: bool = False) -> Dict[str, Any]:
        """Calculate performance metrics from timing data."""
        if not times:
            return {"error": "No timing data collected"}
        
        avg_time = statistics.mean(times)
        min_time = min(times)
        max_time = max(times)
        p95_time = statistics.quantiles(times, n=20)[18] if len(times) >= 20 else max_time
        p99_time = statistics.quantiles(times, n=100)[98] if len(times) >= 100 else max_time
        
        # Determine performance targets based on test type
        if cache_test:
            target_time = 5.0  # <5ms for cached results
        elif circuit_breaker_test:
            target_time = 1.0  # <1ms when circuit breaker is open
        else:
            target_time = 50.0  # <50ms for regular API verification
        
        passed = p95_time <= target_time
        
        return {
            "test_count": test_count,
            "average_time_ms": avg_time,
            "min_time_ms": min_time,
            "max_time_ms": max_time,
            "p95_time_ms": p95_time,
            "p99_time_ms": p99_time,
            "target_time_ms": target_time,
            "passed": passed,
            "all_times": times
        }
    
    def _generate_summary_report(self, results: Dict[str, Any]) -> str:
        """Generate a summary report of all test results."""
        total_tests = len(results)
        passed_tests = sum(1 for result in results.values() 
                          if isinstance(result, dict) and result.get("passed", False))
        failed_tests = total_tests - passed_tests
        
        report = f"""
Performance Test Results:
- Total Tests: {total_tests}
- Passed: {passed_tests}
- Failed: {failed_tests}
- Success Rate: {(passed_tests/total_tests)*100:.1f}%

Performance Requirements:
✅ UCM Capability Lookup: <50ms (95th percentile)
✅ Cache Hit Performance: <5ms (95th percentile)  
✅ Circuit Breaker Performance: <1ms (95th percentile)

Status: {"✅ ALL TESTS PASSED" if failed_tests == 0 else "❌ SOME TESTS FAILED"}
"""
        return report


async def main():
    """Run the performance test suite."""
    test_suite = PerformanceTestSuite()
    results = await test_suite.run_all_tests()
    
    # Save results to file
    import json
    with open("performance_test_results.json", "w") as f:
        # Convert results to JSON-serializable format
        json_results = {}
        for test_name, result in results.items():
            if isinstance(result, dict) and "all_times" in result:
                # Remove the detailed timing data for JSON serialization
                json_result = {k: v for k, v in result.items() if k != "all_times"}
                json_results[test_name] = json_result
            else:
                json_results[test_name] = result
        
        json.dump(json_results, f, indent=2)
    
    print(f"\n📄 Detailed results saved to: performance_test_results.json")
    
    # Return exit code based on test results
    failed_tests = sum(1 for result in results.values() 
                      if isinstance(result, dict) and not result.get("passed", True))
    return 0 if failed_tests == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
