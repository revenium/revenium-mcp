"""Tests for the per-endpoint ``force_new`` override on the analytics endpoint registry."""


import pytest

from src.revenium_mcp_server.endpoint_registry import (
    _ENDPOINT_REGISTRY,
    get_endpoint_config,
    get_endpoint_path,
    resolve_analytics_request,
)


REVENUE_KEYS = (
    "revenue_metric_by_organization",
    "percentage_revenue_metric_by_organization",
)


@pytest.fixture
def flag_off(monkeypatch):
    monkeypatch.delenv("REVENIUM_USE_NEW_ANALYTICS_API", raising=False)


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setenv("REVENIUM_USE_NEW_ANALYTICS_API", "true")


@pytest.mark.parametrize("key", REVENUE_KEYS)
def test_force_new_endpoints_marked_in_registry(key):
    config = _ENDPOINT_REGISTRY[key]
    assert config.force_new is True, f"{key} must have force_new=True"
    assert config.new_path is not None, f"{key} must have a new_path mapped"


@pytest.mark.parametrize("key", REVENUE_KEYS)
def test_force_new_resolves_to_new_path_with_flag_off(flag_off, key):
    path = get_endpoint_path(key)
    assert path.startswith("/api/v2/analytics/"), (
        f"{key} resolved to {path!r}; expected new analytics path"
    )


@pytest.mark.parametrize("key", REVENUE_KEYS)
def test_force_new_resolves_to_new_path_with_flag_on(flag_on, key):
    path = get_endpoint_path(key)
    assert path.startswith("/api/v2/analytics/"), (
        f"{key} resolved to {path!r}; expected new analytics path"
    )


def test_non_forced_endpoint_respects_flag_off(flag_off):
    path = get_endpoint_path("cost_metric_by_provider")
    assert path.startswith("/profitstream/v2/api/"), (
        f"cost_metric_by_provider resolved to {path!r}; expected legacy path when flag is off"
    )


def test_non_forced_endpoint_follows_flag_on(flag_on):
    path = get_endpoint_path("cost_metric_by_provider")
    assert path.startswith("/api/v2/analytics/"), (
        f"cost_metric_by_provider resolved to {path!r}; expected new path when flag is on"
    )


def test_resolve_analytics_request_uses_bearer_for_forced_endpoint(flag_off):
    path, params, call_kwargs = resolve_analytics_request(
        "revenue_metric_by_organization",
        team_id="team-123",
        period="THIRTY_DAYS",
    )
    assert path == "/api/v2/analytics/revenue-per-customer"
    assert call_kwargs.get("use_bearer") is True
    assert "startDate" in params and "endDate" in params
    assert "teamId" not in params
    assert "period" not in params


def test_resolve_analytics_request_uses_legacy_for_non_forced_when_flag_off(flag_off):
    path, params, call_kwargs = resolve_analytics_request(
        "cost_metric_by_provider",
        team_id="team-123",
        period="THIRTY_DAYS",
    )
    assert path.startswith("/profitstream/v2/api/")
    assert call_kwargs == {}
    assert params.get("teamId") == "team-123"
    assert params.get("period") == "THIRTY_DAYS"


def test_get_endpoint_config_preserves_force_new(flag_off):
    config = get_endpoint_config("revenue_metric_by_organization")
    assert config.force_new is True
    assert config.new_path == "/api/v2/analytics/revenue-per-customer"


# ---------------------------------------------------------------------------
