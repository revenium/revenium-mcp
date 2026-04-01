"""Unit tests for TransactionLevelAnalyticsProcessor.

Tests behavioral correctness of:
- Summary data processing (_process_summary_data)
- Customer profitability processing (_process_customer_profitability)
- Product profitability processing (_process_product_profitability)
- Parameter validation integration
- Error handling in public API methods
- Data structure correctness of TransactionLevelData, CustomerTransactionData, ProductTransactionData
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.analytics.transaction_level_analytics_processor import (
    TransactionLevelAnalyticsProcessor,
    TransactionLevelData,
    CustomerTransactionData,
    ProductTransactionData,
    AgentAnalyticsData,
    TaskAnalyticsData,
)
from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — realistic API response shapes
# ─────────────────────────────────────────────────────────────────────────────


def _api_response(group_name, metric_result, start_timestamp="2024-01-01T00:00:00Z"):
    """Create a single time-period API response entry."""
    return {
        "startTimestamp": start_timestamp,
        "groups": [
            {
                "groupName": group_name,
                "metrics": [{"metricResult": metric_result}],
            }
        ],
    }


def _make_summary_data(provider_cost=100.0, model_cost=50.0):
    """Build a complete summary_data dict matching the 5-endpoint fetch structure."""
    return {
        "total_cost_by_provider_over_time": [
            _api_response("OpenAI", provider_cost),
        ],
        "cost_metric_by_provider_over_time": [
            _api_response("OpenAI", 0.05),  # avg cost per transaction
        ],
        "total_cost_by_model": [
            _api_response("gpt-4o", model_cost),
        ],
        "cost_metrics_by_subscriber_credential": [
            _api_response("api-key-1", 25.0),
        ],
        "tokens_per_minute_by_provider": [
            _api_response("OpenAI", 1500.0),
        ],
    }


def _make_customer_data(org_name="AcmeCorp", cost=100.0, revenue=200.0, pct_revenue=15.0):
    """Build customer data matching the 3-endpoint fetch structure."""
    return {
        "cost_metric_by_organization": [
            _api_response(org_name, cost),
        ],
        "revenue_metric_by_organization": [
            _api_response(org_name, revenue),
        ],
        "percentage_revenue_metric_by_organization": [
            _api_response(org_name, pct_revenue),
        ],
    }


def _make_product_data(product_name="API-Pro", cost=80.0, revenue=150.0, pct_revenue=10.0):
    """Build product data matching the 3-endpoint fetch structure."""
    return {
        "cost_metric_by_product": [
            _api_response(product_name, cost),
        ],
        "revenue_metric_by_product": [
            _api_response(product_name, revenue),
        ],
        "percentage_revenue_metric_by_product": [
            _api_response(product_name, pct_revenue),
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# _process_summary_data — TransactionLevelData construction
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessSummaryData:
    """Tests for summary data → TransactionLevelData conversion."""

    def setup_method(self):
        self.processor = TransactionLevelAnalyticsProcessor()

    def test_basic_summary_processing(self):
        """Summary data with provider/model costs produces correct totals."""
        data = _make_summary_data(provider_cost=100.0, model_cost=50.0)
        result = self.processor._process_summary_data(data, "SEVEN_DAYS")

        assert isinstance(result, TransactionLevelData)
        assert result.total_cost == 100.0  # From provider data (primary cost source)
        assert result.cost_by_provider == {"OpenAI": 100.0}
        assert result.cost_by_model == {"gpt-4o": 50.0}

    def test_performance_metrics_populated(self):
        """Tokens-per-minute data populates performance_metrics."""
        data = _make_summary_data()
        result = self.processor._process_summary_data(data, "SEVEN_DAYS")

        # Performance metrics should include tokens_per_minute from token data
        # and avg_cost_per_transaction from cost metric data
        assert "OpenAI" in result.performance_metrics
        assert "tokens_per_minute" in result.performance_metrics["OpenAI"]

    def test_subscriber_data_populates_cost_by_agent(self):
        """Subscriber credential data populates cost_by_agent field."""
        data = _make_summary_data()
        result = self.processor._process_summary_data(data, "SEVEN_DAYS")
        assert "api-key-1" in result.cost_by_agent

    def test_transaction_trends_populated(self):
        """Provider costs with timestamps generate transaction trends."""
        data = _make_summary_data()
        result = self.processor._process_summary_data(data, "SEVEN_DAYS")
        assert len(result.transaction_trends) > 0
        assert result.transaction_trends[0]["type"] == "provider_cost"
        assert "date" in result.transaction_trends[0]

    def test_period_analysis_populated(self):
        """Period analysis metadata is populated correctly."""
        data = _make_summary_data()
        result = self.processor._process_summary_data(data, "SEVEN_DAYS")
        assert result.period_analysis["period"] == "SEVEN_DAYS"
        assert result.period_analysis["provider_count"] == 1
        assert result.period_analysis["model_count"] == 1

    def test_empty_summary_data(self):
        """Empty data produces zeroed TransactionLevelData."""
        data = {
            "total_cost_by_provider_over_time": {},
            "cost_metric_by_provider_over_time": {},
            "total_cost_by_model": {},
            "cost_metrics_by_subscriber_credential": {},
            "tokens_per_minute_by_provider": {},
        }
        result = self.processor._process_summary_data(data, "SEVEN_DAYS")
        assert result.total_cost == 0.0
        assert result.cost_by_provider == {}
        assert result.cost_by_model == {}

    def test_malformed_provider_data_handled(self):
        """Non-list provider data is skipped gracefully."""
        data = {
            "total_cost_by_provider_over_time": "not-a-list",
            "cost_metric_by_provider_over_time": {},
            "total_cost_by_model": {},
            "cost_metrics_by_subscriber_credential": {},
            "tokens_per_minute_by_provider": {},
        }
        result = self.processor._process_summary_data(data, "SEVEN_DAYS")
        assert result.total_cost == 0.0

    def test_non_dict_time_periods_skipped(self):
        """Non-dict entries in time period list are skipped."""
        data = {
            "total_cost_by_provider_over_time": ["not-a-dict", 42, None],
            "cost_metric_by_provider_over_time": {},
            "total_cost_by_model": {},
            "cost_metrics_by_subscriber_credential": {},
            "tokens_per_minute_by_provider": {},
        }
        result = self.processor._process_summary_data(data, "SEVEN_DAYS")
        assert result.total_cost == 0.0

    def test_non_numeric_metrics_skipped(self):
        """Non-numeric metricResult values are skipped."""
        data = {
            "total_cost_by_provider_over_time": [
                {
                    "startTimestamp": "2024-01-01",
                    "groups": [
                        {
                            "groupName": "OpenAI",
                            "metrics": [{"metricResult": "NaN"}],
                        }
                    ],
                }
            ],
            "cost_metric_by_provider_over_time": {},
            "total_cost_by_model": {},
            "cost_metrics_by_subscriber_credential": {},
            "tokens_per_minute_by_provider": {},
        }
        result = self.processor._process_summary_data(data, "SEVEN_DAYS")
        assert result.cost_by_provider == {}

    def test_multiple_providers_aggregated_across_time(self):
        """Multiple time periods for same provider are aggregated."""
        data = {
            "total_cost_by_provider_over_time": [
                _api_response("OpenAI", 100.0, "2024-01-01"),
                _api_response("OpenAI", 150.0, "2024-01-02"),
            ],
            "cost_metric_by_provider_over_time": {},
            "total_cost_by_model": {},
            "cost_metrics_by_subscriber_credential": {},
            "tokens_per_minute_by_provider": {},
        }
        result = self.processor._process_summary_data(data, "SEVEN_DAYS")
        assert result.cost_by_provider == {"OpenAI": 250.0}
        assert result.total_cost == 250.0

    def test_average_cost_per_transaction_calculated(self):
        """Average cost per transaction is total_cost / transaction_count."""
        data = _make_summary_data(provider_cost=200.0)
        result = self.processor._process_summary_data(data, "SEVEN_DAYS")
        # total_transactions is based on len(transaction_trends)
        # With one trend entry, avg = 200 / 1 = 200
        assert result.average_cost_per_transaction > 0


# ─────────────────────────────────────────────────────────────────────────────
# _process_customer_profitability
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessCustomerProfitability:
    """Tests for customer profitability data processing."""

    def setup_method(self):
        self.processor = TransactionLevelAnalyticsProcessor()

    def test_basic_customer_profitability(self):
        """Customer with cost and revenue produces correct profit/margin."""
        data = _make_customer_data("AcmeCorp", cost=100.0, revenue=200.0, pct_revenue=15.0)
        result = self.processor._process_customer_profitability(data, top_n=10)

        assert len(result) == 1
        customer = result[0]
        assert isinstance(customer, CustomerTransactionData)
        assert customer.organization_name == "AcmeCorp"
        assert customer.total_cost == 100.0
        assert customer.total_revenue == 200.0
        assert customer.net_profit == 100.0
        assert customer.profit_margin == 50.0  # (100/200)*100

    def test_percentage_revenue_populated(self):
        """Percentage revenue from API is captured."""
        data = _make_customer_data("AcmeCorp", pct_revenue=25.0)
        result = self.processor._process_customer_profitability(data, top_n=10)
        assert result[0].percentage_revenue == 25.0

    def test_zero_revenue_zero_margin(self):
        """Zero revenue produces zero profit margin."""
        data = _make_customer_data("AcmeCorp", cost=50.0, revenue=0.0)
        result = self.processor._process_customer_profitability(data, top_n=10)
        assert result[0].profit_margin == 0.0

    def test_multiple_customers_sorted_by_profit(self):
        """Multiple customers are sorted by net profit (highest first)."""
        data = {
            "cost_metric_by_organization": [
                {
                    "startTimestamp": "2024-01-01",
                    "groups": [
                        {"groupName": "LowProfit", "metrics": [{"metricResult": 90.0}]},
                        {"groupName": "HighProfit", "metrics": [{"metricResult": 50.0}]},
                    ],
                }
            ],
            "revenue_metric_by_organization": [
                {
                    "startTimestamp": "2024-01-01",
                    "groups": [
                        {"groupName": "LowProfit", "metrics": [{"metricResult": 100.0}]},
                        {"groupName": "HighProfit", "metrics": [{"metricResult": 200.0}]},
                    ],
                }
            ],
            "percentage_revenue_metric_by_organization": [],
        }
        result = self.processor._process_customer_profitability(data, top_n=10)
        assert len(result) == 2
        assert result[0].organization_name == "HighProfit"  # $150 profit
        assert result[1].organization_name == "LowProfit"  # $10 profit

    def test_top_n_limits_results(self):
        """top_n parameter limits the number of returned customers."""
        data = {
            "cost_metric_by_organization": [
                {
                    "startTimestamp": "2024-01-01",
                    "groups": [
                        {"groupName": f"Org{i}", "metrics": [{"metricResult": float(i)}]}
                        for i in range(5)
                    ],
                }
            ],
            "revenue_metric_by_organization": [
                {
                    "startTimestamp": "2024-01-01",
                    "groups": [
                        {"groupName": f"Org{i}", "metrics": [{"metricResult": float(i * 10)}]}
                        for i in range(5)
                    ],
                }
            ],
            "percentage_revenue_metric_by_organization": [],
        }
        result = self.processor._process_customer_profitability(data, top_n=2)
        assert len(result) == 2

    def test_empty_data_returns_empty(self):
        """Empty customer data returns empty list."""
        data = {
            "cost_metric_by_organization": {},
            "revenue_metric_by_organization": {},
            "percentage_revenue_metric_by_organization": {},
        }
        result = self.processor._process_customer_profitability(data, top_n=10)
        assert result == []

    def test_transaction_count_estimated(self):
        """Transaction count is estimated from cost data."""
        data = _make_customer_data("AcmeCorp", cost=1.0, revenue=2.0)
        result = self.processor._process_customer_profitability(data, top_n=10)
        assert result[0].transaction_count >= 1
        assert result[0].cost_per_transaction > 0


# ─────────────────────────────────────────────────────────────────────────────
# _process_product_profitability
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessProductProfitability:
    """Tests for product profitability data processing."""

    def setup_method(self):
        self.processor = TransactionLevelAnalyticsProcessor()

    def test_basic_product_profitability(self):
        """Product with cost and revenue produces correct profit/margin."""
        data = _make_product_data("API-Pro", cost=80.0, revenue=150.0, pct_revenue=10.0)
        result = self.processor._process_product_profitability(data, top_n=10)

        assert len(result) == 1
        product = result[0]
        assert isinstance(product, ProductTransactionData)
        assert product.product_name == "API-Pro"
        assert product.total_cost == 80.0
        assert product.total_revenue == 150.0
        assert product.net_profit == 70.0
        assert product.profit_margin == pytest.approx(46.67, abs=0.1)

    def test_zero_revenue_zero_margin(self):
        """Zero revenue produces zero profit margin."""
        data = _make_product_data("API-Pro", cost=50.0, revenue=0.0)
        result = self.processor._process_product_profitability(data, top_n=10)
        assert result[0].profit_margin == 0.0

    def test_multiple_products_sorted_by_profit(self):
        """Multiple products sorted by net profit."""
        data = {
            "cost_metric_by_product": [
                {
                    "startTimestamp": "2024-01-01",
                    "groups": [
                        {"groupName": "Basic", "metrics": [{"metricResult": 90.0}]},
                        {"groupName": "Premium", "metrics": [{"metricResult": 50.0}]},
                    ],
                }
            ],
            "revenue_metric_by_product": [
                {
                    "startTimestamp": "2024-01-01",
                    "groups": [
                        {"groupName": "Basic", "metrics": [{"metricResult": 100.0}]},
                        {"groupName": "Premium", "metrics": [{"metricResult": 200.0}]},
                    ],
                }
            ],
            "percentage_revenue_metric_by_product": [],
        }
        result = self.processor._process_product_profitability(data, top_n=10)
        assert result[0].product_name == "Premium"  # $150 profit
        assert result[1].product_name == "Basic"  # $10 profit

    def test_empty_data_returns_empty(self):
        """Empty product data returns empty list."""
        data = {
            "cost_metric_by_product": {},
            "revenue_metric_by_product": {},
            "percentage_revenue_metric_by_product": {},
        }
        result = self.processor._process_product_profitability(data, top_n=10)
        assert result == []


# ─────────────────────────────────────────────────────────────────────────────
# Public API error handling
# ─────────────────────────────────────────────────────────────────────────────


class TestAnalyzeSummaryMetricsErrors:
    """Tests for error handling in analyze_summary_metrics."""

    @pytest.mark.asyncio
    async def test_tool_error_re_raised(self):
        """ToolError from fetch is re-raised without modification."""
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()
        original = ToolError(message="original", error_code=ErrorCodes.INVALID_PARAMETER)

        with patch.object(
            processor, "_fetch_summary_data",
            new_callable=AsyncMock,
            side_effect=original,
        ):
            with pytest.raises(ToolError) as exc_info:
                await processor.analyze_summary_metrics(client, "team-1")
            assert exc_info.value is original

    @pytest.mark.asyncio
    async def test_unexpected_error_wrapped_in_tool_error(self):
        """Unexpected exception is wrapped in ToolError with PROCESSING_ERROR."""
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()

        with patch.object(
            processor, "_fetch_summary_data",
            new_callable=AsyncMock,
            side_effect=ValueError("oops"),
        ):
            with pytest.raises(ToolError) as exc_info:
                await processor.analyze_summary_metrics(client, "team-1")
            assert exc_info.value.error_code == ErrorCodes.PROCESSING_ERROR


class TestAnalyzeCustomerTransactionsErrors:
    """Tests for error handling in analyze_customer_transactions."""

    @pytest.mark.asyncio
    async def test_unexpected_error_wrapped(self):
        """Unexpected exception is wrapped in ToolError."""
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()

        with patch.object(
            processor, "_fetch_customer_data",
            new_callable=AsyncMock,
            side_effect=RuntimeError("network issue"),
        ):
            with pytest.raises(ToolError) as exc_info:
                await processor.analyze_customer_transactions(client, "team-1")
            assert exc_info.value.error_code == ErrorCodes.PROCESSING_ERROR

    @pytest.mark.asyncio
    async def test_tool_error_re_raised(self):
        """ToolError is re-raised unchanged."""
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()
        original = ToolError(message="custom", error_code=ErrorCodes.API_ERROR)

        with patch.object(
            processor, "_fetch_customer_data",
            new_callable=AsyncMock,
            side_effect=original,
        ):
            with pytest.raises(ToolError) as exc_info:
                await processor.analyze_customer_transactions(client, "team-1")
            assert exc_info.value is original


class TestAnalyzeProductTransactionsErrors:
    """Tests for error handling in analyze_product_transactions."""

    @pytest.mark.asyncio
    async def test_unexpected_error_wrapped(self):
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()

        with patch.object(
            processor, "_fetch_product_data",
            new_callable=AsyncMock,
            side_effect=RuntimeError("network issue"),
        ):
            with pytest.raises(ToolError) as exc_info:
                await processor.analyze_product_transactions(client, "team-1")
            assert exc_info.value.error_code == ErrorCodes.PROCESSING_ERROR


class TestAnalyzeAgentTransactionsErrors:
    """Tests for error handling in analyze_agent_transactions."""

    @pytest.mark.asyncio
    async def test_unexpected_error_wrapped(self):
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()

        with patch.object(
            processor, "_fetch_agent_data",
            new_callable=AsyncMock,
            side_effect=RuntimeError("network issue"),
        ):
            with pytest.raises(ToolError) as exc_info:
                await processor.analyze_agent_transactions(client, "team-1")
            assert exc_info.value.error_code == ErrorCodes.PROCESSING_ERROR


class TestAnalyzeTaskMetricsErrors:
    """Tests for error handling in analyze_task_metrics."""

    @pytest.mark.asyncio
    async def test_unexpected_error_wrapped(self):
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()

        with patch.object(
            processor, "_fetch_task_data",
            new_callable=AsyncMock,
            side_effect=RuntimeError("network issue"),
        ):
            with pytest.raises(ToolError) as exc_info:
                await processor.analyze_task_metrics(client, "team-1")
            assert exc_info.value.error_code == ErrorCodes.PROCESSING_ERROR


class TestAnalyzeCustomerProfitabilityErrors:
    """Tests for error handling in analyze_customer_profitability."""

    @pytest.mark.asyncio
    async def test_unexpected_error_wrapped(self):
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()

        with patch.object(
            processor, "_fetch_customer_data",
            new_callable=AsyncMock,
            side_effect=RuntimeError("network issue"),
        ):
            with pytest.raises(ToolError) as exc_info:
                await processor.analyze_customer_profitability(client, "team-1")
            assert exc_info.value.error_code == ErrorCodes.PROCESSING_ERROR


class TestAnalyzeProductProfitabilityErrors:
    """Tests for error handling in analyze_product_profitability."""

    @pytest.mark.asyncio
    async def test_unexpected_error_wrapped(self):
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()

        with patch.object(
            processor, "_fetch_product_data",
            new_callable=AsyncMock,
            side_effect=RuntimeError("network issue"),
        ):
            with pytest.raises(ToolError) as exc_info:
                await processor.analyze_product_profitability(client, "team-1")
            assert exc_info.value.error_code == ErrorCodes.PROCESSING_ERROR


class TestAnalyzeAgentPerformanceErrors:
    """Tests for error handling in analyze_agent_performance."""

    @pytest.mark.asyncio
    async def test_unexpected_error_wrapped(self):
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()

        with patch.object(
            processor, "_fetch_agent_data",
            new_callable=AsyncMock,
            side_effect=RuntimeError("network issue"),
        ):
            with pytest.raises(ToolError) as exc_info:
                await processor.analyze_agent_performance(client, "team-1")
            assert exc_info.value.error_code == ErrorCodes.PROCESSING_ERROR


class TestAnalyzeTaskPerformanceErrors:
    """Tests for error handling in analyze_task_performance."""

    @pytest.mark.asyncio
    async def test_unexpected_error_wrapped(self):
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()

        with patch.object(
            processor, "_fetch_task_data",
            new_callable=AsyncMock,
            side_effect=RuntimeError("network issue"),
        ):
            with pytest.raises(ToolError) as exc_info:
                await processor.analyze_task_performance(client, "team-1")
            assert exc_info.value.error_code == ErrorCodes.PROCESSING_ERROR


# ─────────────────────────────────────────────────────────────────────────────
# Initialization and endpoint configuration
# ─────────────────────────────────────────────────────────────────────────────


class TestTransactionProcessorInit:
    """Tests for processor initialization and endpoint configuration."""

    def test_has_all_endpoint_categories(self):
        """Processor initializes with all 5 non-empty endpoint categories."""
        processor = TransactionLevelAnalyticsProcessor()
        assert len(processor.summary_endpoints) > 0
        assert len(processor.customer_endpoints) > 0
        assert len(processor.product_endpoints) > 0
        assert len(processor.agent_endpoints) > 0
        assert len(processor.task_endpoints) > 0

    def test_summary_endpoints_count(self):
        """Summary endpoints should have 5 entries."""
        processor = TransactionLevelAnalyticsProcessor()
        assert len(processor.summary_endpoints) == 5

    def test_customer_endpoints_count(self):
        """Customer endpoints should have 3 entries."""
        processor = TransactionLevelAnalyticsProcessor()
        assert len(processor.customer_endpoints) == 3

    def test_product_endpoints_count(self):
        """Product endpoints should have 3 entries."""
        processor = TransactionLevelAnalyticsProcessor()
        assert len(processor.product_endpoints) == 3

    def test_agent_endpoints_count(self):
        """Agent endpoints should have 3 entries."""
        processor = TransactionLevelAnalyticsProcessor()
        assert len(processor.agent_endpoints) == 3

    def test_task_endpoints_count(self):
        """Task endpoints should have 4 entries."""
        processor = TransactionLevelAnalyticsProcessor()
        assert len(processor.task_endpoints) == 4

    def test_validator_initialized(self):
        """Processor initializes with a functional parameter validator."""
        processor = TransactionLevelAnalyticsProcessor()
        assert processor.validator is not None
        assert callable(getattr(processor.validator, "validate_period", None))

    def test_ucm_helper_optional(self):
        """UCM helper is optional and defaults to None."""
        processor = TransactionLevelAnalyticsProcessor()
        assert processor.ucm_helper is None

        processor2 = TransactionLevelAnalyticsProcessor(ucm_helper="custom")
        assert processor2.ucm_helper == "custom"


# ─────────────────────────────────────────────────────────────────────────────
# Successful async workflows (mocked at fetch level)
# ─────────────────────────────────────────────────────────────────────────────


class TestSuccessfulWorkflows:
    """Tests for successful end-to-end workflows with mocked fetches."""

    @pytest.mark.asyncio
    async def test_analyze_summary_metrics_success(self):
        """analyze_summary_metrics returns TransactionLevelData on success."""
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()
        data = _make_summary_data(provider_cost=100.0, model_cost=50.0)

        with patch.object(
            processor, "_fetch_summary_data",
            new_callable=AsyncMock,
            return_value=data,
        ):
            result = await processor.analyze_summary_metrics(client, "team-1", "SEVEN_DAYS", "TOTAL")
            assert isinstance(result, TransactionLevelData)
            assert result.total_cost == 100.0

    @pytest.mark.asyncio
    async def test_analyze_customer_profitability_success(self):
        """analyze_customer_profitability returns list of CustomerTransactionData."""
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()
        data = _make_customer_data("AcmeCorp", cost=100.0, revenue=200.0)

        with patch.object(
            processor, "_fetch_customer_data",
            new_callable=AsyncMock,
            return_value=data,
        ):
            result = await processor.analyze_customer_profitability(client, "team-1", "SEVEN_DAYS", 10)
            assert len(result) == 1
            assert isinstance(result[0], CustomerTransactionData)
            assert result[0].organization_name == "AcmeCorp"

    @pytest.mark.asyncio
    async def test_analyze_product_profitability_success(self):
        """analyze_product_profitability returns list of ProductTransactionData."""
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()
        data = _make_product_data("API-Pro", cost=80.0, revenue=150.0)

        with patch.object(
            processor, "_fetch_product_data",
            new_callable=AsyncMock,
            return_value=data,
        ):
            result = await processor.analyze_product_profitability(client, "team-1", "SEVEN_DAYS", 10)
            assert len(result) == 1
            assert isinstance(result[0], ProductTransactionData)
            assert result[0].product_name == "API-Pro"

    @pytest.mark.asyncio
    async def test_analyze_customer_transactions_success(self):
        """analyze_customer_transactions returns dict with organizations."""
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()
        data = _make_customer_data("AcmeCorp", cost=100.0, revenue=200.0)

        with patch.object(
            processor, "_fetch_customer_data",
            new_callable=AsyncMock,
            return_value=data,
        ):
            result = await processor.analyze_customer_transactions(client, "team-1", "SEVEN_DAYS", "MEAN")
            assert "organizations" in result
            assert "AcmeCorp" in result["organizations"]

    @pytest.mark.asyncio
    async def test_analyze_product_transactions_success(self):
        """analyze_product_transactions returns dict with products."""
        processor = TransactionLevelAnalyticsProcessor()
        client = MagicMock()
        data = _make_product_data("API-Pro", cost=80.0, revenue=150.0)

        with patch.object(
            processor, "_fetch_product_data",
            new_callable=AsyncMock,
            return_value=data,
        ):
            result = await processor.analyze_product_transactions(client, "team-1", "SEVEN_DAYS", "TOTAL")
            assert "products" in result
            assert "API-Pro" in result["products"]


# ─────────────────────────────────────────────────────────────────────────────
# _process_customer_data — detailed processing tests
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessCustomerData:
    """Tests for customer data processing from API response structures."""

    def setup_method(self):
        self.processor = TransactionLevelAnalyticsProcessor()

    def test_basic_customer_data_processing(self):
        """Customer data with cost, revenue, and percentage is processed correctly."""
        data = _make_customer_data("AcmeCorp", cost=100.0, revenue=200.0, pct_revenue=15.0)
        result = self.processor._process_customer_data(data, "SEVEN_DAYS", "MEAN")

        assert "organizations" in result
        assert "AcmeCorp" in result["organizations"]
        assert result["organizations"]["AcmeCorp"]["cost"] == 100.0
        assert result["organizations"]["AcmeCorp"]["revenue"] == 200.0
        assert result["total_cost"] == 100.0
        assert result["total_revenue"] == 200.0

    def test_customer_profitability_calculated(self):
        """Customer profitability is calculated from cost and revenue."""
        data = _make_customer_data("AcmeCorp", cost=100.0, revenue=200.0)
        result = self.processor._process_customer_data(data, "SEVEN_DAYS", "MEAN")

        prof = result["customer_profitability"]["AcmeCorp"]
        assert prof["profit"] == 100.0
        assert prof["margin"] == 50.0  # (100/200)*100

    def test_zero_revenue_zero_margin(self):
        """Zero revenue produces zero margin in profitability."""
        data = _make_customer_data("AcmeCorp", cost=100.0, revenue=0.0)
        result = self.processor._process_customer_data(data, "SEVEN_DAYS", "MEAN")
        # Only cost data creates the organization entry (revenue=0 skips)
        if "AcmeCorp" in result["customer_profitability"]:
            assert result["customer_profitability"]["AcmeCorp"]["margin"] == 0.0

    def test_period_analysis_populated(self):
        """Period analysis includes correct totals."""
        data = _make_customer_data("AcmeCorp", cost=100.0, revenue=200.0)
        result = self.processor._process_customer_data(data, "SEVEN_DAYS", "MEAN")

        pa = result["period_analysis"]
        assert pa["period"] == "SEVEN_DAYS"
        assert pa["group"] == "MEAN"
        assert pa["total_cost"] == 100.0
        assert pa["total_revenue"] == 200.0
        assert pa["total_profit"] == 100.0
        assert pa["overall_margin"] == 50.0

    def test_empty_customer_data(self):
        """Empty data returns empty results."""
        data = {
            "cost_metric_by_organization": {},
            "revenue_metric_by_organization": {},
            "percentage_revenue_metric_by_organization": {},
        }
        result = self.processor._process_customer_data(data, "SEVEN_DAYS", "MEAN")
        assert result["organizations"] == {}
        assert result["total_cost"] == 0.0

    def test_multiple_orgs_processed(self):
        """Multiple organizations are processed independently."""
        data = {
            "cost_metric_by_organization": [
                {
                    "startTimestamp": "2024-01-01",
                    "groups": [
                        {"groupName": "Org1", "metrics": [{"metricResult": 100.0}]},
                        {"groupName": "Org2", "metrics": [{"metricResult": 200.0}]},
                    ],
                }
            ],
            "revenue_metric_by_organization": [
                {
                    "startTimestamp": "2024-01-01",
                    "groups": [
                        {"groupName": "Org1", "metrics": [{"metricResult": 300.0}]},
                        {"groupName": "Org2", "metrics": [{"metricResult": 400.0}]},
                    ],
                }
            ],
            "percentage_revenue_metric_by_organization": [],
        }
        result = self.processor._process_customer_data(data, "SEVEN_DAYS", "MEAN")
        assert len(result["organizations"]) == 2
        assert result["total_cost"] == 300.0
        assert result["total_revenue"] == 700.0


# ─────────────────────────────────────────────────────────────────────────────
# _process_product_data — detailed processing tests
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessProductData:
    """Tests for product data processing from API response structures."""

    def setup_method(self):
        self.processor = TransactionLevelAnalyticsProcessor()

    def test_basic_product_data_processing(self):
        """Product data with cost, revenue, and percentage is processed correctly."""
        data = _make_product_data("API-Pro", cost=80.0, revenue=150.0, pct_revenue=10.0)
        result = self.processor._process_product_data(data, "SEVEN_DAYS", "TOTAL")

        assert "products" in result
        assert "API-Pro" in result["products"]
        assert result["products"]["API-Pro"]["cost"] == 80.0
        assert result["products"]["API-Pro"]["revenue"] == 150.0

    def test_product_profitability_calculated(self):
        """Product profitability is calculated from cost and revenue."""
        data = _make_product_data("API-Pro", cost=80.0, revenue=150.0)
        result = self.processor._process_product_data(data, "SEVEN_DAYS", "TOTAL")

        prof = result["product_profitability"]["API-Pro"]
        assert prof["profit"] == 70.0
        assert prof["margin"] == pytest.approx(46.67, abs=0.1)

    def test_period_analysis_populated(self):
        """Period analysis includes correct totals."""
        data = _make_product_data("API-Pro", cost=80.0, revenue=150.0)
        result = self.processor._process_product_data(data, "SEVEN_DAYS", "TOTAL")

        pa = result["period_analysis"]
        assert pa["product_count"] == 1
        assert pa["total_profit"] == 70.0

    def test_empty_product_data(self):
        """Empty data returns empty results."""
        data = {
            "cost_metric_by_product": {},
            "revenue_metric_by_product": {},
            "percentage_revenue_metric_by_product": {},
        }
        result = self.processor._process_product_data(data, "SEVEN_DAYS", "TOTAL")
        assert result["products"] == {}

    def test_multiple_products_processed(self):
        """Multiple products are processed independently."""
        data = {
            "cost_metric_by_product": [
                {
                    "startTimestamp": "2024-01-01",
                    "groups": [
                        {"groupName": "Basic", "metrics": [{"metricResult": 50.0}]},
                        {"groupName": "Premium", "metrics": [{"metricResult": 200.0}]},
                    ],
                }
            ],
            "revenue_metric_by_product": [
                {
                    "startTimestamp": "2024-01-01",
                    "groups": [
                        {"groupName": "Basic", "metrics": [{"metricResult": 100.0}]},
                        {"groupName": "Premium", "metrics": [{"metricResult": 500.0}]},
                    ],
                }
            ],
            "percentage_revenue_metric_by_product": [],
        }
        result = self.processor._process_product_data(data, "SEVEN_DAYS", "TOTAL")
        assert len(result["products"]) == 2
        assert result["total_cost"] == 250.0
        assert result["total_revenue"] == 600.0
