"""Pagination Performance Management.

This module provides enhanced pagination validation with graduated performance warnings
and monitoring capabilities to optimize user experience and system performance.

Following development best practices:
- Graduated performance warnings (25, 40, 50 items)
- Performance tier classification
- Execution time monitoring
- User guidance for optimal pagination
"""

import time
from typing import Any, Dict, Optional, Tuple

from loguru import logger

# Performance monitoring removed - infrastructure monitoring handled externally


class PaginationPerformanceManager:
    """Manages pagination performance with graduated warnings and monitoring."""

    # Performance tier thresholds
    OPTIMAL_THRESHOLD = 25
    MEDIUM_THRESHOLD = 40
    HIGH_THRESHOLD = 50
    MAXIMUM_LIMIT = 50  # Revenium API absolute maximum

    def __init__(self):
        """Initialize pagination performance manager."""
        self.execution_times = []
        self.performance_stats = {
            "optimal_requests": 0,
            "medium_requests": 0,
            "high_requests": 0,
            "total_requests": 0,
        }

    def validate_pagination_params(
        self, page: int, size: int, tool_name: str = "unknown"
    ) -> Dict[str, Any]:
        """Validate pagination parameters with graduated performance warnings.

        Args:
            page: Page number (0-based)
            size: Page size (number of items)
            tool_name: Name of the tool making the request

        Returns:
            Dictionary with validation result and performance guidance

        Raises:
            ValueError: If parameters exceed absolute limits
        """
        # Basic validation
        if page < 0:
            raise ValueError("Page number cannot be negative")

        if size <= 0:
            raise ValueError("Page size must be positive")

        # Enforce absolute maximum (Revenium API limit)
        if size > self.MAXIMUM_LIMIT:
            raise ValueError(f"Maximum page size is {self.MAXIMUM_LIMIT} items")

        # Determine performance tier and generate guidance
        performance_tier, guidance = self._analyze_performance_tier(size)

        # Update statistics
        self._update_performance_stats(performance_tier)

        # Log performance guidance if needed
        self._log_performance_guidance(tool_name, size, performance_tier, guidance)

        return {
            "page": page,
            "size": size,
            "performance_tier": performance_tier,
            "guidance": guidance,
            "validation_status": "valid",
            "tool_name": tool_name,
        }

    def _analyze_performance_tier(self, size: int) -> Tuple[str, Dict[str, Any]]:
        """Analyze performance tier and generate guidance.

        Args:
            size: Page size to analyze

        Returns:
            Tuple of (performance_tier, guidance_dict)
        """
        if size <= self.OPTIMAL_THRESHOLD:
            return "optimal", {
                "level": "info",
                "message": "Optimal page size for best performance",
                "recommendation": None,
                "performance_impact": "minimal",
                "estimated_response_time": "< 100ms",
            }

        elif size <= self.MEDIUM_THRESHOLD:
            return "medium", {
                "level": "info",
                "message": "Medium page size - consider smaller sizes for better performance",
                "recommendation": f"Consider using size={self.OPTIMAL_THRESHOLD} for optimal performance",
                "performance_impact": "moderate",
                "estimated_response_time": "100-250ms",
            }

        else:  # size <= HIGH_THRESHOLD (already validated above)
            return "high", {
                "level": "warning",
                "message": "Large page size may impact performance",
                "recommendation": f"Consider using size={self.OPTIMAL_THRESHOLD} for optimal performance",
                "performance_impact": "significant",
                "estimated_response_time": "250-500ms",
                "alternative_approaches": [
                    "Use smaller page sizes with multiple requests",
                    "Implement cursor-based pagination for large datasets",
                    "Consider filtering to reduce result set size",
                ],
            }

    def _update_performance_stats(self, performance_tier: str) -> None:
        """Update performance statistics.

        Args:
            performance_tier: Performance tier (optimal, medium, high)
        """
        self.performance_stats["total_requests"] += 1

        if performance_tier == "optimal":
            self.performance_stats["optimal_requests"] += 1
        elif performance_tier == "medium":
            self.performance_stats["medium_requests"] += 1
        elif performance_tier == "high":
            self.performance_stats["high_requests"] += 1

    def _log_performance_guidance(
        self, tool_name: str, size: int, performance_tier: str, guidance: Dict[str, Any]
    ) -> None:
        """Log performance guidance based on tier.

        Args:
            tool_name: Name of the tool
            size: Page size
            performance_tier: Performance tier
            guidance: Guidance dictionary
        """
        if performance_tier == "high":
            logger.warning(
                f"🚨 {tool_name}: Large page size ({size}) may impact performance. "
                f"Recommendation: {guidance['recommendation']}"
            )
        elif performance_tier == "medium":
            logger.info(
                f"📊 {tool_name}: Medium page size ({size}). "
                f"Consider size={self.OPTIMAL_THRESHOLD} for optimal performance"
            )
        else:
            logger.debug(f"✅ {tool_name}: Optimal page size ({size})")

    async def monitor_pagination_performance(
        self, tool_name: str, action: str, page: int, size: int, execution_func
    ) -> Dict[str, Any]:
        """Monitor pagination performance during execution.

        Args:
            tool_name: Name of the tool
            action: Action being performed
            page: Page number
            size: Page size
            execution_func: Function to execute and monitor

        Returns:
            Dictionary with execution result and performance metrics
        """
        # Validate parameters first
        validation_result = self.validate_pagination_params(page, size, tool_name)

        # Monitor execution
        start_time = time.time()

        try:
            result = await execution_func()
            execution_time_ms = (time.time() - start_time) * 1000
            success = True
            error_message = None

        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            success = False
            error_message = str(e)
            result = None

            # Log performance impact of failed requests
            logger.error(
                f"❌ {tool_name}.{action}: Failed after {execution_time_ms:.2f}ms "
                f"(page={page}, size={size})"
            )
            raise

        # Performance metrics recording removed - handled by external monitoring

        # Log performance results
        performance_tier = validation_result["performance_tier"]
        self._log_execution_performance(
            tool_name, action, page, size, execution_time_ms, performance_tier
        )

        # Store execution time for analysis
        self.execution_times.append(
            {
                "tool_name": tool_name,
                "action": action,
                "page": page,
                "size": size,
                "execution_time_ms": execution_time_ms,
                "performance_tier": performance_tier,
                "timestamp": time.time(),
            }
        )

        # Keep only recent execution times (last 1000)
        if len(self.execution_times) > 1000:
            self.execution_times = self.execution_times[-1000:]

        return {
            "result": result,
            "performance_metrics": {
                "execution_time_ms": execution_time_ms,
                "performance_tier": performance_tier,
                "page": page,
                "size": size,
                "success": success,
            },
            "validation": validation_result,
        }

    def _log_execution_performance(
        self,
        tool_name: str,
        action: str,
        page: int,
        size: int,
        execution_time_ms: float,
        performance_tier: str,
    ) -> None:
        """Log execution performance results.

        Args:
            tool_name: Name of the tool
            action: Action performed
            page: Page number
            size: Page size
            execution_time_ms: Execution time in milliseconds
            performance_tier: Performance tier
        """
        tier_emoji = {"optimal": "✅", "medium": "📊", "high": "⚠️"}

        emoji = tier_emoji.get(performance_tier, "❓")

        logger.info(
            f"{emoji} {tool_name}.{action}: {execution_time_ms:.2f}ms "
            f"(page={page}, size={size}, tier={performance_tier})"
        )

        # Warn if execution time is high for the tier
        if performance_tier == "optimal" and execution_time_ms > 200:
            logger.warning(
                f"🐌 {tool_name}.{action}: Slow execution ({execution_time_ms:.2f}ms) "
                f"for optimal page size ({size}). Consider investigating performance."
            )
        elif performance_tier == "high" and execution_time_ms > 1000:
            logger.warning(
                f"🚨 {tool_name}.{action}: Very slow execution ({execution_time_ms:.2f}ms) "
                f"for large page size ({size}). Strongly recommend smaller page sizes."
            )

    def get_performance_summary(self) -> Dict[str, Any]:
        """Get performance summary statistics.

        Returns:
            Dictionary with performance summary
        """
        total = self.performance_stats["total_requests"]
        if total == 0:
            return {"message": "No pagination requests recorded yet"}

        optimal_pct = (self.performance_stats["optimal_requests"] / total) * 100
        medium_pct = (self.performance_stats["medium_requests"] / total) * 100
        high_pct = (self.performance_stats["high_requests"] / total) * 100

        # Calculate average execution times by tier
        tier_times = {"optimal": [], "medium": [], "high": []}
        for exec_time in self.execution_times:
            tier = exec_time["performance_tier"]
            if tier in tier_times:
                tier_times[tier].append(exec_time["execution_time_ms"])

        avg_times = {}
        for tier, times in tier_times.items():
            avg_times[tier] = sum(times) / len(times) if times else 0

        return {
            "total_requests": total,
            "performance_distribution": {
                "optimal": f"{optimal_pct:.1f}%",
                "medium": f"{medium_pct:.1f}%",
                "high": f"{high_pct:.1f}%",
            },
            "average_execution_times_ms": avg_times,
            "recommendations": {
                "optimal_usage": f"{optimal_pct:.1f}% of requests use optimal page sizes",
                "improvement_potential": f"{high_pct:.1f}% of requests could benefit from smaller page sizes",
                "performance_score": f"{optimal_pct + (medium_pct * 0.7):.1f}/100",
            },
            "thresholds": {
                "optimal": f"≤ {self.OPTIMAL_THRESHOLD} items",
                "medium": f"{self.OPTIMAL_THRESHOLD + 1}-{self.MEDIUM_THRESHOLD} items",
                "high": f"{self.MEDIUM_THRESHOLD + 1}-{self.HIGH_THRESHOLD} items",
            },
        }


# Global pagination performance manager instance
pagination_performance_manager = PaginationPerformanceManager()


def validate_pagination_with_performance(
    page: int, size: int, tool_name: str = "unknown"
) -> Dict[str, Any]:
    """Convenience function for pagination validation with performance guidance.

    Args:
        page: Page number
        size: Page size
        tool_name: Name of the tool

    Returns:
        Validation result with performance guidance
    """
    return pagination_performance_manager.validate_pagination_params(page, size, tool_name)


async def monitor_paginated_execution(
    tool_name: str, action: str, page: int, size: int, execution_func
) -> Dict[str, Any]:
    """Convenience function for monitoring paginated execution.

    Args:
        tool_name: Name of the tool
        action: Action being performed
        page: Page number
        size: Page size
        execution_func: Function to execute

    Returns:
        Execution result with performance metrics
    """
    return await pagination_performance_manager.monitor_pagination_performance(
        tool_name, action, page, size, execution_func
    )


def get_pagination_performance_summary() -> Dict[str, Any]:
    """Get pagination performance summary.

    Returns:
        Performance summary statistics
    """
    return pagination_performance_manager.get_performance_summary()
