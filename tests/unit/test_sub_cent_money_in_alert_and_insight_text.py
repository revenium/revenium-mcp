"""BACK-4845: alert values, insight lines and new-source lines keep a fraction of a cent."""

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from src.revenium_mcp_server.alerts.alert_manager import format_alert_value
from src.revenium_mcp_server.analytics.business_analytics_engine import BusinessAnalyticsEngine
from src.revenium_mcp_server.analytics.statistical_anomaly_detector import (
    StatisticalAnomalyDetector,
)

FRACTION_OF_A_CENT = 0.004


@dataclass
class TransactionData:
    total_cost: float
    average_cost_per_transaction: float
    cost_by_provider: dict = field(default_factory=dict)
    cost_by_model: dict = field(default_factory=dict)
    performance_metrics: dict = field(default_factory=dict)


@dataclass
class CostTrends:
    total_cost: float
    cost_by_provider: dict = field(default_factory=dict)
    cost_by_model: dict = field(default_factory=dict)
    trend_direction: str = "stable"
    period_over_period_change: float = 0.0


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (FRACTION_OF_A_CENT, "$0.004"),
        (0.534666666666667, "$0.534667"),
        (0.0000015, "$0.0000015"),
        (1023.49, "$1,023.49"),
        (-5.0, "-$5.00"),
    ],
)
def test_alert_cost_value_keeps_sub_cent_digits_and_separators(value, expected):
    assert format_alert_value(value, "TOTAL_COST") == expected


@pytest.mark.asyncio
async def test_cost_insight_lines_show_a_fraction_of_a_cent():
    trends = CostTrends(
        total_cost=FRACTION_OF_A_CENT,
        cost_by_provider={"openai": FRACTION_OF_A_CENT},
        cost_by_model={"gpt-4o": FRACTION_OF_A_CENT},
    )

    insights = await BusinessAnalyticsEngine(ucm_integration=None)._generate_cost_insights(
        trends, "SEVEN_DAYS"
    )

    money_lines = [line for line in insights if "$" in line]
    assert any("Total cost for seven days: $0.004" in line for line in money_lines)
    assert any("Top cost driver: openai ($0.004, " in line for line in money_lines)
    assert any("Most expensive model: gpt-4o ($0.004, " in line for line in money_lines)
    assert not any("$0.00" in line.replace("$0.004", "") for line in money_lines)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.0000015, "0.0000015"),
        (12345.678, "12,345.678"),
        (-1234.5, "-1,234.5"),
    ],
)
def test_alert_count_value_keeps_six_decimals_with_separators(value, expected):
    assert format_alert_value(value, "TOKEN_COUNT") == expected


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_a_non_finite_alert_value_reads_na_instead_of_raising(value):
    assert format_alert_value(value, "TOKEN_COUNT") == "n/a"
    assert format_alert_value(value, "TOTAL_COST") == "n/a"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("average", "shown"),
    [
        (0.0567, "$0.0567"),
        (0.00004, "$0.00004"),
    ],
)
async def test_average_cost_per_transaction_keeps_its_digits(average, shown):
    data = TransactionData(total_cost=5.67, average_cost_per_transaction=average)

    insights = await BusinessAnalyticsEngine(
        ucm_integration=None
    )._generate_transaction_level_insights(data, "SEVEN_DAYS")

    average_lines = [line for line in insights if "Average cost per transaction:" in line]
    assert [line.rsplit(": ", 1)[1] for line in average_lines] == [shown]


def test_new_cost_source_context_shows_a_fraction_of_a_cent():
    starts = [datetime(2026, 10, day, tzinfo=timezone.utc) for day in (8, 9)]

    found = StatisticalAnomalyDetector().detect_new_cost_sources(
        {("providers", "NEWBOT"): [0.002, 0.002]}, starts, {}, 1, "SEVEN_DAYS"
    )

    assert [entity.context for entity in found] == [
        "Newly active cost source detected with $0.004 total cost impact"
    ]
