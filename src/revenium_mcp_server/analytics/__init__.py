"""Analytics package for business intelligence and insights.

This package provides comprehensive analytics capabilities for the Revenium MCP server,
including cost analysis, profitability tracking, and business intelligence features.

Key Components:
- BusinessAnalyticsEngine: Core analytics processing and orchestration
- CostAnalyticsProcessor: Cost trend analysis and breakdown
- ProfitabilityAnalyticsProcessor: Customer and product profitability analysis
- ComparativeAnalyticsProcessor: Period-over-period and benchmarking analysis
- AlertAnalyticsWorkflowProcessor: Alert-to-analytics workflows and root cause analysis
- TimeSeriesProcessor: Time series data processing utilities
- ChartDataFormatter: Chart data formatting for visualizations
- NLPBusinessProcessor: Natural language processing for business queries
- AnalyticsMiddleware: Data processing middleware

Architecture:
This analytics package follows the hybrid service layer approach, providing
shared analytics services that can be used by multiple MCP tools while
maintaining clean separation of concerns.
"""

from .alert_analytics_workflow_processor import (
    AlertAnalyticsWorkflowProcessor,
    AlertContext,
    RootCauseAnalysis,
)
from .business_analytics_engine import BusinessAnalyticsEngine
from .chart_data_formatter import ChartDataFormatter
from .comparative_analytics_processor import (
    BenchmarkData,
    ComparativeAnalyticsProcessor,
    ComparisonMetadata,
    ComparisonResult,
    PercentageChange,
)
from .cost_analytics_processor import CostAnalyticsProcessor
from .nlp_business_processor import NLPBusinessProcessor, NLPQueryResult, QueryIntent
from .profitability_analytics_processor import (
    CustomerProfitability,
    ProductProfitability,
    ProfitabilityAnalyticsProcessor,
    ProfitabilityData,
)
from .time_series_processor import TimeSeriesProcessor
from .transaction_level_analytics_processor import (
    AgentTransactionData,
    TaskAnalyticsData,
    TransactionLevelAnalyticsProcessor,
    TransactionLevelData,
)
from .transaction_level_validation import TransactionLevelParameterValidator
from .ucm_integration import AnalyticsCapabilityDiscovery, AnalyticsUCMIntegration

__all__ = [
    "BusinessAnalyticsEngine",
    "CostAnalyticsProcessor",
    "ProfitabilityAnalyticsProcessor",
    "ProfitabilityData",
    "CustomerProfitability",
    "ProductProfitability",
    "ComparativeAnalyticsProcessor",
    "ComparisonResult",
    "PercentageChange",
    "BenchmarkData",
    "ComparisonMetadata",
    "TimeSeriesProcessor",
    "ChartDataFormatter",
    "AnalyticsUCMIntegration",
    "AnalyticsCapabilityDiscovery",
    "NLPBusinessProcessor",
    "QueryIntent",
    "NLPQueryResult",
    "AlertAnalyticsWorkflowProcessor",
    "AlertContext",
    "RootCauseAnalysis",
    "TransactionLevelAnalyticsProcessor",
    "TransactionLevelData",
    "AgentTransactionData",
    "TaskAnalyticsData",
    "TransactionLevelParameterValidator",
]

__version__ = "1.0.0"
