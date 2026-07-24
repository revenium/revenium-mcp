"""Registry tests for the BACK-2376 task/profitability/spend-mover analytics pack.

These endpoints are NEW_API_ONLY with force_new=True — they always resolve to
their new analytics path regardless of REVENIUM_USE_NEW_ANALYTICS_API, mirror the
transaction_count_by_team pattern, and carry Bearer auth via resolve_analytics_request.

Kept in a dedicated file (not test_endpoint_registry_force_new.py) so the pack's
resolution tests stay separate from that file's live-gated integration test.
"""

import pytest

from src.revenium_mcp_server.endpoint_registry import (
    _ENDPOINT_REGISTRY,
    get_endpoint_config,
    get_endpoint_path,
    resolve_analytics_request,
)


# key -> expected new_path
PACK_ENDPOINTS = {
    "cost_by_task": "/api/v2/analytics/cost-by-task",
    "cost_by_task_aggregated": "/api/v2/analytics/cost-by-task-aggregated",
    "task_completion": "/api/v2/analytics/task-completion",
    "task_completion_aggregated": "/api/v2/analytics/task-completion-aggregated",
    "task_performance_by_agent": "/api/v2/analytics/task-performance-by-agent",
    "profit_margin_per_customer": "/api/v2/analytics/profit-margin-per-customer",
    "profit_margin_per_product": "/api/v2/analytics/profit-margin-per-product",
    "top_movers": "/api/v2/analytics/top-movers",
    "token_breakdown_by_type": "/api/v2/analytics/token-breakdown-by-type",
    "token_vs_tool_cost": "/api/v2/analytics/token-vs-tool-cost",
    "trace_cost_distribution": "/api/v2/analytics/trace-cost-distribution",
    "cost_by_team_timeseries": "/api/v2/analytics/cost-by-team",
    "cost_by_vendor": "/api/v2/analytics/cost-by-vendor",
}

PACK_KEYS = sorted(PACK_ENDPOINTS)


@pytest.fixture
def flag_off(monkeypatch):
    monkeypatch.delenv("REVENIUM_USE_NEW_ANALYTICS_API", raising=False)


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setenv("REVENIUM_USE_NEW_ANALYTICS_API", "true")


def test_pack_has_thirteen_endpoints():
    assert len(PACK_ENDPOINTS) == 13


@pytest.mark.parametrize("key", PACK_KEYS)
def test_pack_endpoint_registered(key):
    assert key in _ENDPOINT_REGISTRY, f"{key} missing from endpoint registry"


@pytest.mark.parametrize("key", PACK_KEYS)
def test_pack_endpoint_is_force_new_new_api_only(key):
    config = _ENDPOINT_REGISTRY[key]
    assert config.force_new is True, f"{key} must have force_new=True"
    assert config.mapping_status == "NEW_API_ONLY", f"{key} must be NEW_API_ONLY"
    assert config.new_path == PACK_ENDPOINTS[key]


@pytest.mark.parametrize("key", PACK_KEYS)
def test_pack_endpoint_has_no_legacy_path(key):
    """old_path is a placeholder equal to new_path and is never routed to (force_new)."""
    config = _ENDPOINT_REGISTRY[key]
    assert config.old_path == config.new_path


@pytest.mark.parametrize("key", PACK_KEYS)
def test_pack_resolves_to_new_path_with_flag_off(flag_off, key):
    path = get_endpoint_path(key)
    assert path == PACK_ENDPOINTS[key]


@pytest.mark.parametrize("key", PACK_KEYS)
def test_pack_resolves_to_new_path_with_flag_on(flag_on, key):
    path = get_endpoint_path(key)
    assert path == PACK_ENDPOINTS[key]


@pytest.mark.parametrize("key", PACK_KEYS)
def test_get_endpoint_config_preserves_force_new(flag_off, key):
    config = get_endpoint_config(key)
    assert config.force_new is True
    assert config.new_path == PACK_ENDPOINTS[key]


@pytest.mark.parametrize("key", PACK_KEYS)
def test_resolve_uses_bearer_and_iso_dates_with_flag_off(flag_off, key):
    """force_new endpoints route Bearer + startDate/endDate even with the flag off."""
    path, params, call_kwargs = resolve_analytics_request(
        key, team_id="team-123", period="THIRTY_DAYS"
    )
    assert path == PACK_ENDPOINTS[key]
    assert call_kwargs.get("use_bearer") is True
    assert "base_url" in call_kwargs
    assert "startDate" in params and "endDate" in params
    assert "teamId" not in params
    assert "period" not in params


@pytest.mark.parametrize("key", PACK_KEYS)
def test_resolve_merges_extra_new_params(flag_off, key):
    """Optional params (groupBy, providers, agents) merge into the new-API query."""
    _path, params, _call_kwargs = resolve_analytics_request(
        key,
        team_id="team-123",
        period="SEVEN_DAYS",
        extra_new_params={"groupBy": "model"},
    )
    assert params["groupBy"] == "model"
    assert "startDate" in params and "endDate" in params
