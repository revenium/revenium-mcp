"""Live analytics smoke checks, relocated from tests/unit (2026-08-03).

Both tests were born gated on REVENIUM_LIVE_API_KEY - an env var no
environment ever set - so they had been skipped on every run since March and
May 2026, and their base URL defaulted to PRODUCTION. They now live where
integration tests belong, gated the same way as the rest of this directory
(explicit opt-in + the standard dev env vars, no production default), and run
nightly via the Buildkite auth-contract step.

- Revenue-per-customer via force_new routing (BACK-1362 origin).
- Completions search with provider and date filters (BACK-719 origin).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("REVENIUM_INTEGRATION_TESTS")
    or not os.getenv("REVENIUM_API_KEY")
    or not os.getenv("REVENIUM_BASE_URL"),
    reason=(
        "live analytics smoke needs REVENIUM_INTEGRATION_TESTS=1 plus "
        "REVENIUM_API_KEY and REVENIUM_BASE_URL (dev)"
    ),
)


def _auth():
    from src.revenium_mcp_server.auth import AuthConfig

    return AuthConfig(
        api_key=os.environ["REVENIUM_API_KEY"],
        team_id=os.environ.get("REVENIUM_TEAM_ID", ""),
        base_url=os.environ["REVENIUM_BASE_URL"],
    )


@pytest.mark.asyncio
async def test_revenue_metric_by_organization_via_force_new_routing(monkeypatch):
    """The revenue-per-customer endpoint answers through force_new routing."""
    from src.revenium_mcp_server.client import ReveniumClient
    from src.revenium_mcp_server.endpoint_registry import resolve_analytics_request

    monkeypatch.delenv("REVENIUM_USE_NEW_ANALYTICS_API", raising=False)

    path, params, call_kwargs = resolve_analytics_request(
        "revenue_metric_by_organization",
        team_id=os.environ.get("REVENIUM_TEAM_ID", ""),
        period="TWELVE_MONTHS",
    )
    assert path == "/api/v2/analytics/revenue-per-customer"
    assert call_kwargs.get("use_bearer") is True

    async with ReveniumClient(auth_config=_auth()) as client:
        response = await client.get(path, params=params, **call_kwargs)

    assert response is not None
    assert isinstance(response, (dict, list))


@pytest.mark.asyncio
async def test_completions_search_with_filters():
    """Completions search accepts provider and date-range filters live."""
    from src.revenium_mcp_server.client import ReveniumClient
    from src.revenium_mcp_server.endpoint_registry import get_endpoint_path

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=90)
    async with ReveniumClient(auth_config=_auth()) as client:
        endpoint = get_endpoint_path("completions")
        params = {
            "teamId": os.environ.get("REVENIUM_TEAM_ID", ""),
            "page": 0,
            "size": 5,
            "sort": "timestamp,desc",
            "provider": "anthropic",
            "startDate": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "endDate": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        response = await client.get(endpoint, params=params)

    assert isinstance(response, dict)
    assert "_embedded" in response or "content" in response, (
        f"expected a known response envelope, got keys={list(response.keys())}"
    )
