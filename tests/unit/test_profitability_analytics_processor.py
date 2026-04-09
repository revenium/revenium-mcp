"""Unit tests for ProfitabilityAnalyticsProcessor.

Tests the behavioral correctness of:
- Processor initialization with revenue and cost endpoints
- Profitability data processing (_process_profitability_data)
- Customer profitability processing (_process_customer_profitability)
- Product profitability processing (_process_product_profitability)
- Top performers ranking (_get_top_performers)
- Percentage change calculation (_calculate_percentage_change)
- Period-over-period profitability changes (_calculate_profitability_changes)
"""

import pytest

from src.revenium_mcp_server.analytics.profitability_analytics_processor import (
    ProfitabilityAnalyticsProcessor,
    ProfitabilityData,
    CustomerProfitability,
    ProductProfitability,
)


# ─────────────────────────────────────────────────────────────────────────────
# Initialization
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# _process_profitability_data
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessProfitabilityData:
    """Tests for processing raw revenue and cost data into ProfitabilityData."""

    def setup_method(self):
        self.proc = ProfitabilityAnalyticsProcessor()

    def _make_revenue_data(self, org_groups=None, product_groups=None):
        data = {}
        if org_groups:
            data["revenue_by_organization"] = {"groups": org_groups}
        if product_groups:
            data["revenue_by_product"] = {"groups": product_groups}
        return data

    def _make_cost_data(self, org_groups=None, product_groups=None):
        data = {}
        if org_groups:
            data["cost_by_organization"] = {"groups": org_groups}
        if product_groups:
            data["cost_by_product"] = {"groups": product_groups}
        return data

    def test_calculates_net_profit_and_margin(self):
        revenue = self._make_revenue_data(org_groups=[
            {"groupName": "Acme", "metrics": [{"metricResult": 1000}]},
        ])
        cost = self._make_cost_data(org_groups=[
            {"groupName": "Acme", "metrics": [{"metricResult": 400}]},
        ])
        result = self.proc._process_profitability_data(revenue, cost, "TWELVE_MONTHS", "customers")
        assert isinstance(result, ProfitabilityData)
        assert result.total_revenue == 1000.0
        assert result.total_cost == 400.0
        assert result.net_profit == 600.0
        assert result.profit_margin == pytest.approx(60.0)

    def test_zero_revenue_gives_zero_margin(self):
        revenue = self._make_revenue_data()
        cost = self._make_cost_data(org_groups=[
            {"groupName": "X", "metrics": [{"metricResult": 100}]},
        ])
        result = self.proc._process_profitability_data(revenue, cost, "TWELVE_MONTHS", "customers")
        assert result.profit_margin == 0.0

    def test_customer_profitability_calculated(self):
        revenue = self._make_revenue_data(org_groups=[
            {"groupName": "Acme", "metrics": [{"metricResult": 500}]},
            {"groupName": "Beta", "metrics": [{"metricResult": 300}]},
        ])
        cost = self._make_cost_data(org_groups=[
            {"groupName": "Acme", "metrics": [{"metricResult": 200}]},
            {"groupName": "Beta", "metrics": [{"metricResult": 250}]},
        ])
        result = self.proc._process_profitability_data(revenue, cost, "TWELVE_MONTHS", "customers")
        assert "Acme" in result.profitability_by_customer
        assert result.profitability_by_customer["Acme"]["profit"] == 300.0
        assert result.profitability_by_customer["Beta"]["profit"] == 50.0

    def test_product_profitability_calculated(self):
        revenue = self._make_revenue_data(product_groups=[
            {"groupName": "API Pro", "metrics": [{"metricResult": 800}]},
        ])
        cost = self._make_cost_data(product_groups=[
            {"groupName": "API Pro", "metrics": [{"metricResult": 300}]},
        ])
        result = self.proc._process_profitability_data(revenue, cost, "TWELVE_MONTHS", "products")
        assert "API Pro" in result.profitability_by_product
        assert result.profitability_by_product["API Pro"]["profit"] == 500.0

    def test_empty_data_returns_zero_totals(self):
        result = self.proc._process_profitability_data({}, {}, "TWELVE_MONTHS", "customers")
        assert result.total_revenue == 0.0
        assert result.total_cost == 0.0
        assert result.net_profit == 0.0

    def test_non_dict_groups_skipped(self):
        revenue = {"revenue_by_organization": {"groups": ["not-a-dict"]}}
        cost = self._make_cost_data()
        result = self.proc._process_profitability_data(revenue, cost, "TWELVE_MONTHS", "customers")
        assert result.total_revenue == 0.0

    def test_non_dict_metrics_skipped(self):
        revenue = self._make_revenue_data(org_groups=[
            {"groupName": "X", "metrics": ["not-a-dict"]},
        ])
        cost = self._make_cost_data()
        result = self.proc._process_profitability_data(revenue, cost, "TWELVE_MONTHS", "customers")
        assert result.total_revenue == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# _get_top_performers
# ─────────────────────────────────────────────────────────────────────────────


class TestGetTopPerformers:
    """Tests for top performer ranking."""

    def setup_method(self):
        self.proc = ProfitabilityAnalyticsProcessor()

    def test_ranks_by_profit_descending(self):
        data = {
            "Acme": {"revenue": 1000, "cost": 400, "profit": 600, "margin": 60},
            "Beta": {"revenue": 500, "cost": 100, "profit": 400, "margin": 80},
            "Gamma": {"revenue": 2000, "cost": 200, "profit": 1800, "margin": 90},
        }
        result = self.proc._get_top_performers(data, "customers", top_n=2)
        assert len(result) == 2
        assert result[0]["name"] == "Gamma"
        assert result[0]["rank"] == 1
        assert result[1]["name"] == "Acme"
        assert result[1]["rank"] == 2

    def test_empty_data_returns_empty(self):
        result = self.proc._get_top_performers({}, "customers")
        assert result == []

    def test_top_n_limits_results(self):
        data = {f"C{i}": {"profit": i} for i in range(20)}
        result = self.proc._get_top_performers(data, "customers", top_n=5)
        assert len(result) == 5


# ─────────────────────────────────────────────────────────────────────────────
# _process_customer_profitability
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessCustomerProfitability:
    """Tests for customer profitability processing."""

    def setup_method(self):
        self.proc = ProfitabilityAnalyticsProcessor()

    def test_calculates_profit_and_margin(self):
        revenue_data = {
            "groups": [
                {"groupName": "Acme", "metrics": [{"metricResult": 1000}]},
            ]
        }
        cost_data = {
            "groups": [
                {"groupName": "Acme", "metrics": [{"metricResult": 400}]},
            ]
        }
        result = self.proc._process_customer_profitability(revenue_data, cost_data, 10)
        assert len(result) == 1
        assert isinstance(result[0], CustomerProfitability)
        assert result[0].net_profit == 600.0
        assert result[0].profit_margin == pytest.approx(60.0)
        assert result[0].profitability_rank == 1

    def test_sorted_by_profit_descending(self):
        revenue_data = {
            "groups": [
                {"groupName": "Low", "metrics": [{"metricResult": 100}]},
                {"groupName": "High", "metrics": [{"metricResult": 1000}]},
            ]
        }
        cost_data = {
            "groups": [
                {"groupName": "Low", "metrics": [{"metricResult": 50}]},
                {"groupName": "High", "metrics": [{"metricResult": 200}]},
            ]
        }
        result = self.proc._process_customer_profitability(revenue_data, cost_data, 10)
        assert result[0].customer_name == "High"
        assert result[0].profitability_rank == 1

    def test_top_n_limits_results(self):
        revenue_data = {
            "groups": [
                {"groupName": f"C{i}", "metrics": [{"metricResult": i * 100}]}
                for i in range(5)
            ]
        }
        cost_data = {"groups": []}
        result = self.proc._process_customer_profitability(revenue_data, cost_data, 2)
        assert len(result) == 2

    def test_zero_revenue_gives_zero_margin(self):
        revenue_data = {"groups": []}
        cost_data = {
            "groups": [
                {"groupName": "X", "metrics": [{"metricResult": 100}]},
            ]
        }
        result = self.proc._process_customer_profitability(revenue_data, cost_data, 10)
        assert result[0].profit_margin == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# _process_product_profitability
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessProductProfitability:
    """Tests for product profitability processing."""

    def setup_method(self):
        self.proc = ProfitabilityAnalyticsProcessor()

    def test_calculates_product_metrics(self):
        revenue_data = {
            "groups": [
                {"groupName": "API Pro", "metrics": [{"metricResult": 2000}]},
            ]
        }
        cost_data = {
            "groups": [
                {"groupName": "API Pro", "metrics": [{"metricResult": 500}]},
            ]
        }
        result = self.proc._process_product_profitability(revenue_data, cost_data, 10)
        assert len(result) == 1
        assert isinstance(result[0], ProductProfitability)
        assert result[0].net_profit == 1500.0
        assert result[0].profitability_rank == 1

    def test_tracks_customer_count_from_organization_field(self):
        revenue_data = {
            "groups": [
                {"groupName": "Product A", "metrics": [
                    {"metricResult": 100, "organizationName": "Acme"},
                    {"metricResult": 200, "organizationName": "Beta"},
                ]},
            ]
        }
        cost_data = {"groups": []}
        result = self.proc._process_product_profitability(revenue_data, cost_data, 10)
        assert result[0].customer_count == 2
        assert result[0].revenue_per_customer == pytest.approx(150.0)


# ─────────────────────────────────────────────────────────────────────────────
# _calculate_percentage_change
# ─────────────────────────────────────────────────────────────────────────────


class TestCalculatePercentageChange:
    """Tests for percentage change calculation."""

    def setup_method(self):
        self.proc = ProfitabilityAnalyticsProcessor()

    def test_positive_change(self):
        result = self.proc._calculate_percentage_change(100, 150)
        assert result == pytest.approx(50.0)

    def test_negative_change(self):
        result = self.proc._calculate_percentage_change(100, 50)
        assert result == pytest.approx(-50.0)

    def test_zero_old_value_with_new_positive(self):
        result = self.proc._calculate_percentage_change(0, 100)
        assert result == 100.0

    def test_zero_old_value_with_new_zero(self):
        result = self.proc._calculate_percentage_change(0, 0)
        assert result == 0.0

    def test_no_change(self):
        result = self.proc._calculate_percentage_change(100, 100)
        assert result == pytest.approx(0.0)


# ─────────────────────────────────────────────────────────────────────────────
# _calculate_profitability_changes
# ─────────────────────────────────────────────────────────────────────────────


class TestCalculateProfitabilityChanges:
    """Tests for period-over-period profitability comparison."""

    def setup_method(self):
        self.proc = ProfitabilityAnalyticsProcessor()

    def _make_profitability_data(self, revenue, cost):
        return ProfitabilityData(
            total_revenue=revenue,
            total_cost=cost,
            net_profit=revenue - cost,
            profit_margin=(revenue - cost) / revenue * 100 if revenue > 0 else 0,
            profitability_by_customer={},
            profitability_by_product={},
            profitability_by_period=[],
            top_profitable_customers=[],
            top_profitable_products=[],
            trend_direction="stable",
            period_over_period_change=0.0,
        )

    def test_improving_trend(self):
        current = self._make_profitability_data(1000, 400)
        comparison = self._make_profitability_data(800, 500)
        result = self.proc._calculate_profitability_changes(
            current, comparison, "TWELVE_MONTHS", "SEVEN_DAYS"
        )
        assert result["trend"] == "improving"
        assert result["current_period"] == "TWELVE_MONTHS"
        assert result["comparison_period"] == "SEVEN_DAYS"

    def test_declining_trend(self):
        current = self._make_profitability_data(500, 400)
        comparison = self._make_profitability_data(1000, 400)
        result = self.proc._calculate_profitability_changes(
            current, comparison, "TWELVE_MONTHS", "SEVEN_DAYS"
        )
        assert result["trend"] == "declining"

    def test_stable_trend(self):
        current = self._make_profitability_data(1000, 400)
        comparison = self._make_profitability_data(1000, 400)
        result = self.proc._calculate_profitability_changes(
            current, comparison, "TWELVE_MONTHS", "SEVEN_DAYS"
        )
        assert result["trend"] == "stable"

    def test_result_contains_metrics(self):
        current = self._make_profitability_data(1000, 400)
        comparison = self._make_profitability_data(800, 300)
        result = self.proc._calculate_profitability_changes(
            current, comparison, "TWELVE_MONTHS", "SEVEN_DAYS"
        )
        assert "current_metrics" in result
        assert "comparison_metrics" in result
        assert result["current_metrics"]["revenue"] == 1000
        assert result["comparison_metrics"]["revenue"] == 800
        assert "analyzed_at" in result
