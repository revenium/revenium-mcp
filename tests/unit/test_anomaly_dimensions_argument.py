"""analyze_cost_anomalies reads include_dimensions as names, never as letters (BACK-4837).

A plain "providers" was iterated character by character, so the analysis
answered "p: not a supported dimension" for every letter, and the texts "",
"None" and "NULL" passed as dimension names.
"""

from unittest.mock import AsyncMock, patch

import pytest

from src.revenium_mcp_server.analytics.enhanced_spike_analyzer import EnhancedSpikeAnalyzer
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.tools_decomposed.business_analytics_management import (
    BusinessAnalyticsManagement,
)


@pytest.fixture
def tool():
    with patch(
        "src.revenium_mcp_server.tools_decomposed.business_analytics_management.CHART_RENDERING_AVAILABLE",
        False,
    ):
        instance = BusinessAnalyticsManagement()
    instance.get_client = AsyncMock(return_value=AsyncMock())
    return instance


@pytest.fixture
def analysis(monkeypatch):
    analyze = AsyncMock(return_value={"period_analyzed": "SEVEN_DAYS", "temporal_anomalies": []})
    monkeypatch.setattr(EnhancedSpikeAnalyzer, "analyze_temporal_anomalies", analyze)
    return analyze


async def _dimensions_read(tool, analysis, value):
    await tool.handle_action(
        "analyze_cost_anomalies", {"period": "SEVEN_DAYS", "include_dimensions": value}
    )
    return analysis.await_args.kwargs["include_dimensions"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value, dimensions",
    [
        ("providers", ["providers"]),
        (["providers"], ["providers"]),
        ("providers,agents", ["providers", "agents"]),
        ("providers, api_keys", ["providers", "api_keys"]),
        (["providers", "agents"], ["providers", "agents"]),
    ],
    ids=["one_word", "one_item_list", "comma_joined", "comma_and_space", "list"],
)
async def test_a_word_or_a_comma_joined_text_is_read_as_dimension_names(
    tool, analysis, value, dimensions
):
    assert await _dimensions_read(tool, analysis, value) == dimensions


@pytest.mark.asyncio
async def test_no_dimensions_reads_providers(tool, analysis):
    await tool.handle_action("analyze_cost_anomalies", {"period": "SEVEN_DAYS"})

    assert analysis.await_args.kwargs["include_dimensions"] == ["providers"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value, reason",
    [
        ("", "blank value"),
        ("None", "names nothing"),
        ("NULL", "names nothing"),
        (["providers", "None"], "names nothing"),
        ([], "must not be empty"),
    ],
    ids=["empty_text", "None_text", "NULL_text", "None_in_list", "empty_list"],
)
async def test_an_empty_or_placeholder_text_is_refused_naming_the_argument(
    tool, analysis, value, reason
):
    with pytest.raises(ToolError) as refusal:
        await tool.handle_action(
            "analyze_cost_anomalies", {"period": "SEVEN_DAYS", "include_dimensions": value}
        )

    analysis.assert_not_awaited()
    tool.get_client.assert_not_awaited()
    assert refusal.value.field == "include_dimensions"
    assert "include_dimensions" in refusal.value.message
    assert reason in refusal.value.message
