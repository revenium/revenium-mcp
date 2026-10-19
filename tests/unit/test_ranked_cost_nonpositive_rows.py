"""Provider, model and customer cost reports list zero and negative rows (BACK-4690).

A provider the platform reports at exactly $0 (unpriced or unmetered) was left
out, so it read as never used, and a credit arriving as a negative cost was
dropped and the total overstated. A row is listed whenever the platform sent a
numeric figure for it; a group with no numeric figure at all is not a row.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.revenium_mcp_server.analytics.formatters.base_formatter import (
    BaseFormattingUtilities,
)
from src.revenium_mcp_server.analytics.response_formatter import ResponseFormatter
from src.revenium_mcp_server.analytics.simple_cost_analyzer import SimpleCostAnalyzer


@pytest.fixture(autouse=True)
def legacy_route(monkeypatch):
    """The legacy route hands the platform's body to the parsers untouched."""
    monkeypatch.delenv("REVENIUM_USE_NEW_ANALYTICS_API", raising=False)


def _analyzer(response):
    client = MagicMock()
    client.team_id = "team-abc"
    client.get = AsyncMock(return_value=response)
    return SimpleCostAnalyzer(client)


def _group(name, *values):
    return {"groupName": name, "metrics": [{"metricResult": v} for v in values]}


def _costs(rows, name_field):
    return {row[name_field]: row["cost"] for row in rows}


@pytest.mark.asyncio
async def test_provider_costs_list_zero_and_negative_providers():
    analyzer = _analyzer(
        [{"groups": [_group("openai", 100.0), _group("vertex_ai", 0), _group("credit", -5.0)]}]
    )

    rows = await analyzer.get_provider_costs("THIRTY_DAYS", "TOTAL")

    assert _costs(rows, "provider") == {"OpenAI": 100.0, "vertex_ai": 0, "credit": -5.0}
    assert sum(row["cost"] for row in rows) == pytest.approx(95.0)
    text = ResponseFormatter().format_provider_costs_response(
        data=list(rows), period="THIRTY_DAYS", aggregation="TOTAL"
    )
    assert "**Providers Found**: 3" in text
    assert "vertex_ai" in text


_MODEL_GROUPS = [
    _group("gpt-4", 100.0, -10.0),
    _group("unpriced-model", 0),
    _group("credit-model", -5.0),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        pytest.param({"groups": _MODEL_GROUPS}, id="aggregated-dict"),
        pytest.param([{"groups": _MODEL_GROUPS}], id="bucket-list"),
        pytest.param(list(_MODEL_GROUPS), id="bare-list"),
    ],
)
async def test_model_costs_list_zero_and_negative_models_in_every_shape(response):
    analyzer = _analyzer(response)

    rows = await analyzer.get_model_costs("THIRTY_DAYS", "TOTAL")

    assert _costs(rows, "model") == {
        "gpt-4": pytest.approx(90.0),
        "unpriced-model": 0,
        "credit-model": -5.0,
    }
    text = ResponseFormatter().format_model_costs_response(
        data=list(rows), period="THIRTY_DAYS", aggregation="TOTAL"
    )
    assert "**Models Found**: 3" in text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        pytest.param(
            [{"groups": [_group("Acme", 100.0), _group("Free Tier", 0), _group("Refund", -5.0)]}],
            id="bucket-list",
        ),
        pytest.param(
            [
                {"customer": "Acme", "cost": 100.0},
                {"customer": "Free Tier", "cost": 0},
                {"customer": "Refund", "cost": -5.0},
            ],
            id="bare-list",
        ),
    ],
)
async def test_customer_costs_list_zero_and_negative_customers(response):
    analyzer = _analyzer(response)

    rows = await analyzer.get_customer_costs("THIRTY_DAYS", "TOTAL")

    assert _costs(rows, "customer") == {"Acme": 100.0, "Free Tier": 0, "Refund": -5.0}
    text = ResponseFormatter().format_customer_costs_response(
        data=list(rows), period="THIRTY_DAYS", aggregation="TOTAL"
    )
    assert "**Customers Found**: 3" in text


@pytest.mark.asyncio
async def test_summary_total_includes_credit_rows():
    analyzer = _analyzer(
        [{"groups": [_group("openai", 100.0), _group("vertex_ai", 0), _group("credit", -5.0)]}]
    )

    summary = await analyzer.get_cost_summary("THIRTY_DAYS", "TOTAL")

    assert summary["total_cost"] == pytest.approx(95.0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "read, name_field",
    [
        ("get_provider_costs", "provider"),
        ("get_model_costs", "model"),
        ("get_customer_costs", "customer"),
    ],
)
async def test_groups_without_a_numeric_value_are_not_listed(read, name_field):
    analyzer = _analyzer(
        [
            {
                "groups": [
                    {"groupName": "no-metrics", "metrics": []},
                    {"groupName": "null-metric", "metrics": [{"metricResult": None}]},
                    _group("zero", 0),
                ]
            }
        ]
    )

    rows = await getattr(analyzer, read)("THIRTY_DAYS", "TOTAL")

    assert _costs(rows, name_field) == {"zero": 0}


@pytest.mark.asyncio
@pytest.mark.parametrize("read", ["get_model_costs", "get_customer_costs"])
async def test_bare_rows_without_a_numeric_cost_are_not_listed(read):
    analyzer = _analyzer([{"name": "no-cost"}, {"name": "zero", "cost": 0}])

    rows = await getattr(analyzer, read)("THIRTY_DAYS", "TOTAL")

    name_field = "model" if read == "get_model_costs" else "customer"
    assert _costs(rows, name_field) == {"zero": 0}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "read, name_field",
    [
        ("get_provider_costs", "provider"),
        ("get_model_costs", "model"),
        ("get_customer_costs", "customer"),
    ],
)
async def test_share_is_against_positive_rows_only(read, name_field):
    analyzer = _analyzer(
        [{"groups": [_group("paid", 100.0), _group("free", 0), _group("credit", -50.0)]}]
    )

    rows = await getattr(analyzer, read)("THIRTY_DAYS", "TOTAL")

    by_name = {row[name_field]: row for row in rows}
    assert set(by_name) == {"paid", "free", "credit"}
    assert by_name["paid"]["percentage"] == pytest.approx(100.0)
    assert "percentage" not in by_name["free"]
    assert "percentage" not in by_name["credit"]


@pytest.mark.asyncio
async def test_a_credit_prints_with_its_minus_sign_before_the_dollar():
    """A credit reads as -$5.00, the way money is written, not $-5.00 (BACK-4809)."""
    analyzer = _analyzer([{"groups": [_group("Acme", 100.0), _group("Refund", -5.0)]}])

    rows = await analyzer.get_customer_costs("THIRTY_DAYS", "TOTAL")
    text = ResponseFormatter().format_customer_costs_response(
        data=list(rows), period="THIRTY_DAYS", aggregation="TOTAL"
    )

    assert "-$5.00" in text
    assert "$-" not in text
    assert BaseFormattingUtilities.format_currency(-1234.5) == "-$1,234.50"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "read, name_field, found_line, render",
    [
        ("get_agent_costs", "agent", "**Agents Found**: 3", "format_agent_costs_response"),
        (
            "get_api_key_costs",
            "api_key",
            "**API Keys Found**: 3",
            "format_api_key_costs_response",
        ),
    ],
)
async def test_agent_and_api_key_costs_list_zero_and_negative_rows(
    read, name_field, found_line, render
):
    """An agent or key with no spend is still listed, so the count matches the platform (BACK-4809)."""
    analyzer = _analyzer(
        [
            {
                "groups": [
                    _group("support-bot", 10.0),
                    _group("idle-bot", 0),
                    _group("credit", -2.0),
                ]
            }
        ]
    )

    rows = await getattr(analyzer, read)("THIRTY_DAYS", "TOTAL")

    assert _costs(rows, name_field) == {"support-bot": 10.0, "idle-bot": 0, "credit": -2.0}
    text = getattr(ResponseFormatter(), render)(
        data=list(rows), period="THIRTY_DAYS", aggregation="TOTAL"
    )
    assert found_line in text


@pytest.mark.asyncio
async def test_summary_top_lists_leave_out_zero_and_credit_rows():
    """A top list holds only rows that added cost; a read part with none says so (BACK-4809)."""
    analyzer = _analyzer(
        [{"groups": [_group("openai", 100.0), _group("vertex_ai", 0), _group("credit", -5.0)]}]
    )

    summary = await analyzer.get_cost_summary("THIRTY_DAYS", "TOTAL")

    assert [row["provider"] for row in summary["top_providers"]] == ["OpenAI"]
    assert [row["agent"] for row in summary["top_agents"]] == ["openai"]
    assert summary["total_cost"] == pytest.approx(95.0)
    assert summary["cost_breakdown"]["agent_costs"] == pytest.approx(95.0)
    text = ResponseFormatter().format_cost_summary_response(
        summary, period="THIRTY_DAYS", aggregation="TOTAL"
    )
    assert "- vertex_ai:" not in text
    assert "- credit:" not in text

    idle = _analyzer([{"groups": [_group("idle-bot", 0), _group("refund", -5.0)]}])
    idle_summary = await idle.get_cost_summary("THIRTY_DAYS", "TOTAL")
    idle_text = ResponseFormatter().format_cost_summary_response(
        idle_summary, period="THIRTY_DAYS", aggregation="TOTAL"
    )
    assert idle_summary["top_agents"] == []
    assert "**Top Agents:** none above $0.00" in idle_text
    assert "**Top Providers:** none above $0.00" in idle_text
    assert "idle-bot" not in idle_text
