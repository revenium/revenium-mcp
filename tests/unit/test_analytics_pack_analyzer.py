"""Analyzer tests for the BACK-2376 task/profitability/spend-mover analytics pack.

Fixtures mirror the three envelope families live-verified on dev:
  A. TIMESERIES (metric_timeseries): _embedded.items[].{startTimestamp,
     endTimestamp, groups[].{groupName, metrics[].{label, metricResult,
     taskType?/tokenType?}}}
  B. AGGREGATED (metric_aggregated): _embedded.items[].{groupName,
     metrics[].{label, metricResult, metricType, ...extra}}. top-movers
     metrics also carry currentValue, previousValue, trend.
  C. SCATTER (trace-cost-distribution): top-level {resourceType, dataPoints[]}
     — no _embedded.

The analyzer must extract _embedded.items, flatten B via the grouped-metric
logic while preserving per-endpoint extra fields, keep A's timeseries buckets
with groups flattened per bucket, return C's dataPoints as-is, render empty
_embedded.items as an empty list, and skip metrics whose metricResult is
missing/non-numeric (never fabricate 0).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.revenium_mcp_server.analytics.simple_cost_analyzer import SimpleCostAnalyzer


# ────────────────────────────────────────────────────────────────────────────
# Fixtures — envelope shapes
# ────────────────────────────────────────────────────────────────────────────

TIMESERIES_ENVELOPE = {
    "resourceType": "metric_timeseries",
    "_embedded": {
        "items": [
            {
                "startTimestamp": "2026-07-01T00:00:00Z",
                "endTimestamp": "2026-07-02T00:00:00Z",
                "groups": [
                    {
                        "groupName": "code-review",
                        "metrics": [
                            {"label": "cost", "metricResult": 12.5, "taskType": "code-review"},
                        ],
                    },
                    {
                        "groupName": "summarize",
                        "metrics": [
                            {"label": "cost", "metricResult": 3.25, "taskType": "summarize"},
                        ],
                    },
                ],
            },
            {
                "startTimestamp": "2026-07-02T00:00:00Z",
                "endTimestamp": "2026-07-03T00:00:00Z",
                "groups": [
                    {
                        "groupName": "code-review",
                        "metrics": [
                            {"label": "cost", "metricResult": 8.0, "taskType": "code-review"},
                        ],
                    },
                ],
            },
        ]
    },
}

AGGREGATED_ENVELOPE = {
    "resourceType": "metric_aggregated",
    "_embedded": {
        "items": [
            {
                "groupName": "acme-corp",
                "metrics": [
                    {"label": "margin", "metricResult": 42.5, "metricType": "PERCENTAGE"},
                ],
            },
            {
                "groupName": "globex",
                "metrics": [
                    {"label": "margin", "metricResult": 18.0, "metricType": "PERCENTAGE"},
                ],
            },
        ]
    },
}

TOP_MOVERS_ENVELOPE = {
    "resourceType": "metric_aggregated",
    "_embedded": {
        "items": [
            {
                "groupName": "gpt-4o",
                "metrics": [
                    {
                        "label": "cost",
                        "metricResult": 120.0,
                        "metricType": "MONEY",
                        "currentValue": 120.0,
                        "previousValue": 80.0,
                        "trend": "UP",
                    },
                ],
            },
            {
                "groupName": "claude-3",
                "metrics": [
                    {
                        "label": "cost",
                        "metricResult": 50.0,
                        "metricType": "MONEY",
                        "currentValue": 50.0,
                        "previousValue": 90.0,
                        "trend": "DOWN",
                    },
                ],
            },
        ]
    },
}

SCATTER_ENVELOPE = {
    "resourceType": "scatter_chart",
    "dataPoints": [
        {
            "transactionId": "tx-1",
            "agentName": "agent-a",
            "totalCost": 1.23,
            "totalCalls": 5,
            "distinctTools": 2,
            "traceStart": "2026-07-01T00:00:00Z",
            "traceEnd": "2026-07-01T00:01:00Z",
        },
        {
            "transactionId": "tx-2",
            "agentName": "agent-b",
            "totalCost": 4.56,
            "totalCalls": 9,
            "distinctTools": 4,
            "traceStart": "2026-07-01T01:00:00Z",
            "traceEnd": "2026-07-01T01:02:00Z",
        },
    ],
}

EMPTY_ENVELOPE = {"_embedded": {"items": []}}

MISSING_METRIC_AGG_ENVELOPE = {
    "_embedded": {
        "items": [
            {
                "groupName": "good",
                "metrics": [{"label": "margin", "metricResult": 10.0, "metricType": "PERCENTAGE"}],
            },
            {
                "groupName": "missing",
                "metrics": [{"label": "margin", "metricType": "PERCENTAGE"}],  # no metricResult
            },
            {
                "groupName": "nonnumeric",
                "metrics": [{"label": "margin", "metricResult": "n/a"}],  # non-numeric
            },
        ]
    },
}


def _analyzer_with_response(response):
    client = MagicMock()
    client.team_id = "team-123"
    client.get = AsyncMock(return_value=response)
    return SimpleCostAnalyzer(client)


# ────────────────────────────────────────────────────────────────────────────
# _fetch_analytics_envelope
# ────────────────────────────────────────────────────────────────────────────

class TestFetchAnalyticsEnvelope:
    @pytest.mark.asyncio
    async def test_returns_dict_response(self):
        analyzer = _analyzer_with_response(AGGREGATED_ENVELOPE)
        result = await analyzer._fetch_analytics_envelope("profit_margin_per_customer", "THIRTY_DAYS")
        assert result == AGGREGATED_ENVELOPE

    @pytest.mark.asyncio
    async def test_non_dict_response_becomes_empty_dict(self):
        analyzer = _analyzer_with_response(None)
        result = await analyzer._fetch_analytics_envelope("profit_margin_per_customer", "THIRTY_DAYS")
        assert result == {}

    @pytest.mark.asyncio
    async def test_forwards_extra_new_params(self):
        analyzer = _analyzer_with_response(AGGREGATED_ENVELOPE)
        await analyzer._fetch_analytics_envelope(
            "top_movers", "THIRTY_DAYS", extra_new_params={"groupBy": "model"}
        )
        _args, kwargs = analyzer.client.get.call_args
        assert kwargs["params"]["groupBy"] == "model"

    @pytest.mark.asyncio
    async def test_uses_bearer_call_kwargs(self):
        analyzer = _analyzer_with_response(AGGREGATED_ENVELOPE)
        await analyzer._fetch_analytics_envelope("cost_by_vendor", "SEVEN_DAYS")
        _args, kwargs = analyzer.client.get.call_args
        assert kwargs.get("use_bearer") is True


# ────────────────────────────────────────────────────────────────────────────
# Envelope B — aggregated (profit margins, vendor, top movers, task-perf)
# ────────────────────────────────────────────────────────────────────────────

class TestAggregatedFamily:
    @pytest.mark.asyncio
    async def test_profit_margins_customer_flattens_groups(self):
        analyzer = _analyzer_with_response(AGGREGATED_ENVELOPE)
        rows = await analyzer.get_profit_margins("THIRTY_DAYS", "customer")
        assert len(rows) == 2
        names = {r["group"] for r in rows}
        assert names == {"acme-corp", "globex"}
        acme = next(r for r in rows if r["group"] == "acme-corp")
        assert acme["metricResult"] == 42.5
        assert acme["metricType"] == "PERCENTAGE"

    @pytest.mark.asyncio
    async def test_profit_margins_rejects_bad_dimension(self):
        analyzer = _analyzer_with_response(AGGREGATED_ENVELOPE)
        with pytest.raises(ValueError):
            await analyzer.get_profit_margins("THIRTY_DAYS", "bogus")

    @pytest.mark.asyncio
    async def test_profit_margins_product_uses_product_endpoint(self):
        analyzer = _analyzer_with_response(AGGREGATED_ENVELOPE)
        await analyzer.get_profit_margins("THIRTY_DAYS", "product")
        args, kwargs = analyzer.client.get.call_args
        assert "profit-margin-per-product" in args[0]

    @pytest.mark.asyncio
    async def test_top_movers_preserves_trend_fields(self):
        analyzer = _analyzer_with_response(TOP_MOVERS_ENVELOPE)
        rows = await analyzer.get_top_movers("THIRTY_DAYS", group_by="model")
        gpt = next(r for r in rows if r["group"] == "gpt-4o")
        assert gpt["currentValue"] == 120.0
        assert gpt["previousValue"] == 80.0
        assert gpt["trend"] == "UP"

    @pytest.mark.asyncio
    async def test_top_movers_forwards_group_by(self):
        analyzer = _analyzer_with_response(TOP_MOVERS_ENVELOPE)
        await analyzer.get_top_movers("THIRTY_DAYS", group_by="agent")
        _args, kwargs = analyzer.client.get.call_args
        assert kwargs["params"]["groupBy"] == "agent"

    @pytest.mark.asyncio
    async def test_top_movers_omits_group_by_when_none(self):
        analyzer = _analyzer_with_response(TOP_MOVERS_ENVELOPE)
        await analyzer.get_top_movers("THIRTY_DAYS", group_by=None)
        _args, kwargs = analyzer.client.get.call_args
        assert "groupBy" not in kwargs["params"]

    @pytest.mark.asyncio
    async def test_vendor_costs_flattens(self):
        analyzer = _analyzer_with_response(AGGREGATED_ENVELOPE)
        rows = await analyzer.get_vendor_costs("SEVEN_DAYS")
        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_task_performance_by_agent_empty(self):
        analyzer = _analyzer_with_response(EMPTY_ENVELOPE)
        rows = await analyzer.get_task_performance_by_agent("SEVEN_DAYS")
        assert rows == []

    @pytest.mark.asyncio
    async def test_missing_or_nonnumeric_metric_is_skipped(self):
        analyzer = _analyzer_with_response(MISSING_METRIC_AGG_ENVELOPE)
        rows = await analyzer.get_profit_margins("THIRTY_DAYS", "customer")
        # Only the "good" group survives — the missing and non-numeric ones are dropped.
        assert len(rows) == 1
        assert rows[0]["group"] == "good"
        assert rows[0]["metricResult"] == 10.0

    @pytest.mark.asyncio
    async def test_task_costs_aggregated_uses_aggregated_endpoint(self):
        analyzer = _analyzer_with_response(AGGREGATED_ENVELOPE)
        rows = await analyzer.get_task_costs("THIRTY_DAYS", "aggregated")
        args, _kwargs = analyzer.client.get.call_args
        assert "cost-by-task-aggregated" in args[0]
        assert len(rows) == 2


# ────────────────────────────────────────────────────────────────────────────
# Envelope A — timeseries (task costs, task completion, token breakdown, etc.)
# ────────────────────────────────────────────────────────────────────────────

class TestTimeseriesFamily:
    @pytest.mark.asyncio
    async def test_task_costs_timeseries_returns_buckets(self):
        analyzer = _analyzer_with_response(TIMESERIES_ENVELOPE)
        buckets = await analyzer.get_task_costs("SEVEN_DAYS", "timeseries")
        assert len(buckets) == 2
        first = buckets[0]
        assert first["startTimestamp"] == "2026-07-01T00:00:00Z"
        assert first["endTimestamp"] == "2026-07-02T00:00:00Z"
        assert len(first["groups"]) == 2
        code = next(g for g in first["groups"] if g["group"] == "code-review")
        assert code["metrics"][0]["metricResult"] == 12.5
        assert code["metrics"][0]["taskType"] == "code-review"

    @pytest.mark.asyncio
    async def test_task_costs_default_is_timeseries(self):
        analyzer = _analyzer_with_response(TIMESERIES_ENVELOPE)
        await analyzer.get_task_costs("SEVEN_DAYS", "timeseries")
        args, _kwargs = analyzer.client.get.call_args
        assert args[0].endswith("/cost-by-task")

    @pytest.mark.asyncio
    async def test_task_completion_forwards_agents(self):
        analyzer = _analyzer_with_response(TIMESERIES_ENVELOPE)
        await analyzer.get_task_completion("SEVEN_DAYS", "timeseries", agents=["a1", "a2"])
        _args, kwargs = analyzer.client.get.call_args
        assert kwargs["params"]["agents"] == ["a1", "a2"]

    @pytest.mark.asyncio
    async def test_token_breakdown_forwards_providers(self):
        analyzer = _analyzer_with_response(TIMESERIES_ENVELOPE)
        await analyzer.get_token_breakdown("SEVEN_DAYS", providers=["openai"])
        _args, kwargs = analyzer.client.get.call_args
        assert kwargs["params"]["providers"] == ["openai"]

    @pytest.mark.asyncio
    async def test_token_breakdown_omits_providers_when_none(self):
        analyzer = _analyzer_with_response(TIMESERIES_ENVELOPE)
        await analyzer.get_token_breakdown("SEVEN_DAYS", providers=None)
        _args, kwargs = analyzer.client.get.call_args
        assert "providers" not in kwargs["params"]

    @pytest.mark.asyncio
    async def test_team_costs_timeseries(self):
        analyzer = _analyzer_with_response(TIMESERIES_ENVELOPE)
        buckets = await analyzer.get_team_costs("THIRTY_DAYS")
        args, _kwargs = analyzer.client.get.call_args
        assert args[0].endswith("/cost-by-team")
        assert len(buckets) == 2

    @pytest.mark.asyncio
    async def test_token_vs_tool_cost_timeseries(self):
        analyzer = _analyzer_with_response(TIMESERIES_ENVELOPE)
        buckets = await analyzer.get_token_vs_tool_cost("THIRTY_DAYS")
        args, _kwargs = analyzer.client.get.call_args
        assert args[0].endswith("/token-vs-tool-cost")
        assert len(buckets) == 2

    @pytest.mark.asyncio
    async def test_empty_timeseries_returns_empty_list(self):
        analyzer = _analyzer_with_response(EMPTY_ENVELOPE)
        buckets = await analyzer.get_task_costs("SEVEN_DAYS", "timeseries")
        assert buckets == []

    @pytest.mark.asyncio
    async def test_timeseries_skips_nonnumeric_metric_but_keeps_bucket(self):
        envelope = {
            "_embedded": {
                "items": [
                    {
                        "startTimestamp": "2026-07-01T00:00:00Z",
                        "endTimestamp": "2026-07-02T00:00:00Z",
                        "groups": [
                            {
                                "groupName": "keep",
                                "metrics": [{"label": "cost", "metricResult": 1.0}],
                            },
                            {
                                "groupName": "drop",
                                "metrics": [{"label": "cost", "metricResult": None}],
                            },
                        ],
                    }
                ]
            }
        }
        analyzer = _analyzer_with_response(envelope)
        buckets = await analyzer.get_task_costs("SEVEN_DAYS", "timeseries")
        assert len(buckets) == 1
        groups = buckets[0]["groups"]
        assert len(groups) == 1
        assert groups[0]["group"] == "keep"


# ────────────────────────────────────────────────────────────────────────────
# Envelope C — scatter (trace cost distribution)
# ────────────────────────────────────────────────────────────────────────────

class TestScatterFamily:
    @pytest.mark.asyncio
    async def test_trace_cost_distribution_returns_datapoints(self):
        analyzer = _analyzer_with_response(SCATTER_ENVELOPE)
        points = await analyzer.get_trace_cost_distribution("SEVEN_DAYS")
        assert points == SCATTER_ENVELOPE["dataPoints"]

    @pytest.mark.asyncio
    async def test_trace_cost_distribution_empty_when_no_datapoints(self):
        analyzer = _analyzer_with_response({"resourceType": "scatter_chart"})
        points = await analyzer.get_trace_cost_distribution("SEVEN_DAYS")
        assert points == []

    @pytest.mark.asyncio
    async def test_trace_cost_distribution_uses_scatter_endpoint(self):
        analyzer = _analyzer_with_response(SCATTER_ENVELOPE)
        await analyzer.get_trace_cost_distribution("SEVEN_DAYS")
        args, _kwargs = analyzer.client.get.call_args
        assert args[0].endswith("/trace-cost-distribution")


class TestFetchEnvelopeUnwrapBehavior:
    """Live-found regression: the client's default unwrap_hal_embedded=True
    collapses the envelope to a list (A/B) or [] (scatter — no _embedded),
    which _fetch_analytics_envelope's dict-only normalization then discards
    as {}. The fetch must request the full envelope."""

    @pytest.mark.asyncio
    async def test_fetch_requests_full_envelope(self, monkeypatch):
        analyzer = _analyzer_with_response({})
        analyzer.client.get = AsyncMock(return_value={"_embedded": {"items": []}})
        await analyzer._fetch_analytics_envelope("top_movers", "THIRTY_DAYS")
        kwargs = analyzer.client.get.call_args.kwargs
        assert kwargs.get("unwrap_hal_embedded") is False

    @pytest.mark.asyncio
    async def test_scatter_envelope_survives_fetch(self):
        """dataPoints (no _embedded) must reach the parser intact."""
        analyzer = _analyzer_with_response({})
        analyzer.client.get = AsyncMock(return_value={
            "resourceType": "scatter_chart",
            "dataPoints": [{"transactionId": "t1", "totalCost": 0.25}],
        })
        result = await analyzer.get_trace_cost_distribution("THIRTY_DAYS")
        assert len(result) == 1
        assert result[0]["transactionId"] == "t1"
