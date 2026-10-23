"""BACK-4623: the API key answers carry one figure per distinct key for the whole window.

The legacy per-credential report answers one row per key per half-day bucket.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.revenium_mcp_server.analytics.formatters.api_key_costs_formatter import (
    ApiKeyCostsFormatter,
    mask_api_key_name,
)
from src.revenium_mcp_server.analytics.formatters.cost_summary_formatter import (
    CostSummaryFormatter,
)
from src.revenium_mcp_server.analytics.simple_cost_analyzer import SimpleCostAnalyzer

ANN = "Application Autodiscovery (ann@revenium.io)"
BOB = "Application Autodiscovery (bob@revenium.io)"


def _bucket(values: dict) -> dict:
    return {
        "groups": [
            {"groupName": name, "metrics": [{"metricResult": value}]}
            for name, value in values.items()
        ]
    }


# ANONYMOUS has the most spend over the window, ANN the largest single slice.
CREDENTIAL_BUCKETS = [
    _bucket({"ANONYMOUS": 900.0, ANN: 1262.0, BOB: 3.0}),
    _bucket({"ANONYMOUS": 1197.0, ANN: 1198.0, BOB: 4.0}),
    _bucket({"ANONYMOUS": 1100.0, BOB: 5.0}),
    _bucket({"ANONYMOUS": 1000.0}),
]


@pytest.fixture(autouse=True)
def _legacy_route(monkeypatch):
    monkeypatch.delenv("REVENIUM_USE_NEW_ANALYTICS_API", raising=False)


@pytest.fixture
def analyzer() -> SimpleCostAnalyzer:
    client = MagicMock()
    client.team_id = "team-1"
    client.get = AsyncMock(return_value=CREDENTIAL_BUCKETS)
    return SimpleCostAnalyzer(client)


@pytest.mark.asyncio
async def test_each_key_is_the_sum_of_its_buckets(analyzer):
    rows = await analyzer.get_api_key_costs("SEVEN_DAYS", "TOTAL")
    assert [(row["api_key"], row["cost"]) for row in rows] == [
        ("ANONYMOUS", 4197.0),
        (ANN, 2460.0),
        (BOB, 12.0),
    ]


@pytest.mark.asyncio
async def test_summary_top_api_keys_lists_each_key_once(analyzer):
    summary = await analyzer.get_cost_summary("SEVEN_DAYS", "TOTAL")
    top = [row["api_key"] for row in summary["top_api_keys"]]
    assert top == ["ANONYMOUS", ANN, BOB]


@pytest.mark.asyncio
async def test_key_report_counts_distinct_keys_in_cost_order(analyzer):
    rows = await analyzer.get_api_key_costs("SEVEN_DAYS", "TOTAL")
    text = ApiKeyCostsFormatter().format(rows, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
    assert "API Keys Found**: 3" in text
    assert text.index("$4,197.00") < text.index("$2,460.00") < text.index("$12.00")
    assert "sources" not in text.lower()


@pytest.mark.asyncio
async def test_summary_and_key_report_show_keys_the_same_way(analyzer):
    rows = await analyzer.get_api_key_costs("SEVEN_DAYS", "TOTAL")
    report = ApiKeyCostsFormatter().format(rows, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"})
    summary = await analyzer.get_cost_summary("SEVEN_DAYS", "TOTAL")
    summary_text = CostSummaryFormatter().format(
        summary, {"period": "SEVEN_DAYS", "aggregation": "TOTAL"}
    )
    api_key_section = summary_text.split("**Top API Keys:**")[1].split("**Top Agents:**")[0]
    shown = mask_api_key_name(ANN)
    assert shown == "Appl****.io)"
    assert f"- {shown}: $2,460.00" in api_key_section
    assert f"{shown}**\n   - Cost: $2,460.00" in report
    assert ANN not in api_key_section
    assert ANN not in report


ROLLUP = "Other API keys"


@pytest.mark.parametrize("label", [ROLLUP, ROLLUP.upper()])
def test_the_analytics_rollup_is_shown_unmasked(label):
    """The roll-up of unnamed keys is a label, not a key value (BACK-4846)."""
    assert mask_api_key_name(label) == label


@pytest.mark.asyncio
async def test_the_rollup_reads_in_full_in_the_key_report_and_the_summary():
    client = MagicMock()
    client.team_id = "team-1"
    client.get = AsyncMock(return_value=[_bucket({ROLLUP: 522.08, ANN: 10.0})])
    analyzer = SimpleCostAnalyzer(client)
    params = {"period": "SEVEN_DAYS", "aggregation": "TOTAL"}

    report = ApiKeyCostsFormatter().format(
        await analyzer.get_api_key_costs("SEVEN_DAYS", "TOTAL"), params
    )
    summary_text = CostSummaryFormatter().format(
        await analyzer.get_cost_summary("SEVEN_DAYS", "TOTAL"), params
    )

    assert f"{ROLLUP}**\n   - Cost: $522.08" in report
    assert f"- {ROLLUP}: $522.08" in summary_text
    assert "Othe****keys" not in report + summary_text
