"""get_agent_costs with a cost-source filter on a deployment without the new-API setting.

Hosted deployments never set the setting, so a filtered named-period read was
refused with advice to change it (BACK-4690). The read now goes to the
analytics route, and the answer's coding-assistant scope note follows that
route.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.revenium_mcp_server.analytics.simple_analytics_engine import (
    SimpleAnalyticsEngine,
)

_ANALYTICS_PLANE_NOTE = "every analytics cost action"
_LEGACY_PLANE_NOTE = "legacy analytics endpoints"
_FILTER = {"costSources": ["provider_billing"]}


def _engine(envelope):
    client = MagicMock()
    client.team_id = "team-abc"
    client.get = AsyncMock(return_value=envelope)
    return SimpleAnalyticsEngine(client), client


@pytest.fixture
def flag_unset(monkeypatch):
    monkeypatch.delenv("REVENIUM_USE_NEW_ANALYTICS_API", raising=False)
    monkeypatch.setenv("REVENIUM_APP_BASE_URL", "https://app.dev.example")


@pytest.mark.asyncio
async def test_filtered_answer_carries_the_analytics_scope_note(flag_unset):
    engine, client = _engine({"_embedded": {"items": []}})

    text = await engine.get_agent_costs(period="THIRTY_DAYS", filters=_FILTER)

    assert _ANALYTICS_PLANE_NOTE in text
    assert _LEGACY_PLANE_NOTE not in text
    assert "REVENIUM_USE_NEW_ANALYTICS_API" not in text
    client.get.assert_awaited_once()
    assert client.get.call_args[0][0] == "/api/v2/analytics/cost-by-agent"


@pytest.mark.asyncio
async def test_filtered_rows_footer_carries_the_analytics_scope_note(flag_unset):
    bucket = {"groups": [{"groupName": "agent-a", "metrics": [{"metricResult": 12.5}]}]}
    engine, _ = _engine({"_embedded": {"items": [bucket]}})

    text = await engine.get_agent_costs(period="THIRTY_DAYS", filters=_FILTER)

    assert "agent-a" in text
    assert "$12.50" in text
    assert _ANALYTICS_PLANE_NOTE in text
    assert _LEGACY_PLANE_NOTE not in text
    assert "REVENIUM_USE_NEW_ANALYTICS_API" not in text
