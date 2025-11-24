"""AI Routing Infrastructure for Universal Query Interpreter.

This module provides the foundational infrastructure for AI-powered query routing
with feature flag control, graceful fallback, and A/B testing capabilities.

Key Components:
- AIRoutingConfig: Configuration management for feature flags
- UniversalQueryRouter: Core routing decision layer
- MetricsCollector: A/B testing and performance metrics
- ParameterExtractor: Natural language parameter extraction
- AIClient: AI service integration with rate limiting

Architecture:
The AI routing system is designed as an additive layer that can be enabled/disabled
without affecting existing functionality. It provides a hybrid approach where AI
routing can be used when enabled, with automatic fallback to rule-based routing.

Usage:
    from revenium_mcp_server.ai_routing import (
        AIRoutingConfig,
        UniversalQueryRouter,
        MetricsCollector
    )

    config = AIRoutingConfig()
    router = UniversalQueryRouter(config)
    result = await router.route_query("create a product called API Monitor", "products")
"""

from .ab_testing_framework import (
    ABTestingFramework,
    ABTestResult,
    ABTestSummary,
    PerformanceComparator,
    TestScenario,
    TestScenarioManager,
)
from .ai_client import AIClient, AIClientError
from .config import AIRoutingConfig
from .fallback_router import FallbackRouter
from .models import RoutingMetrics
from .parameter_extractor import ExtractedParameters, ParameterExtractor
from .router import RoutingResult, UniversalQueryRouter
from .simple_metrics import SimpleMetricsCollector

# Backward compatibility
MetricsCollector = SimpleMetricsCollector

__all__ = [
    "AIRoutingConfig",
    "UniversalQueryRouter",
    "RoutingResult",
    "SimpleMetricsCollector",
    "MetricsCollector",  # Backward compatibility
    "RoutingMetrics",
    "AIClient",
    "AIClientError",
    "ParameterExtractor",
    "ExtractedParameters",
    "FallbackRouter",
    # A/B Testing Framework
    "ABTestingFramework",
    "TestScenarioManager",
    "PerformanceComparator",
    "TestScenario",
    "ABTestResult",
    "ABTestSummary",
]

__version__ = "1.0.0"
