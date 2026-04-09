"""Endpoint registry for Revenium analytics API migration (BACK-716).

Maps analytics endpoint keys to their old (profitstream) and new (ClickHouse-backed)
paths, along with routing metadata consumed by the client layer during migration.

Feature flag: set env var REVENIUM_USE_NEW_ANALYTICS_API=true to route through the
new analytics host (REVENIUM_APP_BASE_URL / https://app.revenium.ai).
"""

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

from .config_store import get_config_value


# Default production base URL for the new analytics API
DEFAULT_APP_BASE_URL = "https://app.revenium.ai"


@dataclass
class EndpointConfig:
    """Configuration for a single analytics endpoint."""

    old_path: str
    """Path on the legacy profitstream API (x-api-key auth)."""

    new_path: Optional[str]
    """Path on the new ClickHouse-backed analytics API (Bearer auth). None if not yet mapped."""

    new_base_url: str = DEFAULT_APP_BASE_URL
    """Base URL for the new analytics host. Defaults to app.revenium.ai."""

    client_side_only: bool = False
    """True for metrics that are computed client-side with no direct new-API endpoint.

    When client_side_only=True, the new_path points to the data source used for the
    client-side calculation (e.g. revenue-per-customer for percentage-revenue).
    """

    mapping_status: str = "READY"
    """Migration status: 'READY' means the new path is confirmed; 'TBD' means not yet verified."""

    unit_multiplier: float = 1.0
    """Multiplier applied to new-API metric values to convert to the same unit as the old API.

    When non-1.0, callers must multiply the raw ``metricResult`` value by this factor.
    Example: the three response-time endpoints return seconds in the new API but milliseconds
    in the old API, so ``unit_multiplier=1000.0`` normalises new-API values to milliseconds.
    """


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_ENDPOINT_REGISTRY: Dict[str, EndpointConfig] = {
    # ── Timeseries cost endpoints ──────────────────────────────────────────
    # Old: /profitstream/v2/api/sources/metrics/ai/total-cost-by-provider-over-time
    # New: /api/v2/analytics/cost-by-provider  (BACK-718 swap #1)
    "total_cost_by_provider_over_time": EndpointConfig(
        old_path="/profitstream/v2/api/sources/metrics/ai/total-cost-by-provider-over-time",
        new_path="/api/v2/analytics/cost-by-provider",
    ),
    # Old: /profitstream/v2/api/sources/metrics/ai/cost-metric-by-provider-over-time
    # New: /api/v2/analytics/cost-by-provider  (BACK-718 swap #2)
    "cost_metric_by_provider_over_time": EndpointConfig(
        old_path="/profitstream/v2/api/sources/metrics/ai/cost-metric-by-provider-over-time",
        new_path="/api/v2/analytics/cost-by-provider",
    ),
    # Old: /profitstream/v2/api/sources/metrics/ai/total-cost-by-model
    # New: /api/v2/analytics/cost-by-model  (BACK-718 swap #3)
    "total_cost_by_model": EndpointConfig(
        old_path="/profitstream/v2/api/sources/metrics/ai/total-cost-by-model",
        new_path="/api/v2/analytics/cost-by-model",
    ),
    # Old: /profitstream/v2/api/sources/metrics/ai/cost-metrics-by-subscriber-credential
    # New: /api/v2/analytics/cost-by-api-key  (BACK-718 swap #4)
    "cost_metrics_by_subscriber_credential": EndpointConfig(
        old_path="/profitstream/v2/api/sources/metrics/ai/cost-metrics-by-subscriber-credential",
        new_path="/api/v2/analytics/cost-by-api-key",
    ),
    # Old: /profitstream/v2/api/sources/metrics/ai/cost-metric-by-organization
    # New: /api/v2/analytics/cost-by-organization  (BACK-718 swap #5 — timeseries variant)
    "cost_metric_by_organization": EndpointConfig(
        old_path="/profitstream/v2/api/sources/metrics/ai/cost-metric-by-organization",
        new_path="/api/v2/analytics/cost-by-organization",
    ),
    # Old: same as above — aggregated variant for summary/comparison use-cases
    # New: /api/v2/analytics/cost-by-organization-aggregated  (BACK-718 swap #5 — aggregated)
    "cost_metric_by_organization_aggregated": EndpointConfig(
        old_path="/profitstream/v2/api/sources/metrics/ai/cost-metric-by-organization",
        new_path="/api/v2/analytics/cost-by-organization-aggregated",
    ),
    # Old: /profitstream/v2/api/sources/metrics/ai/cost-metric-by-product
    # New: /api/v2/analytics/cost-by-product  (BACK-718 swap #6 — timeseries variant)
    "cost_metric_by_product": EndpointConfig(
        old_path="/profitstream/v2/api/sources/metrics/ai/cost-metric-by-product",
        new_path="/api/v2/analytics/cost-by-product",
    ),
    # Old: same as above — aggregated variant
    # New: /api/v2/analytics/cost-by-product-aggregated  (BACK-718 swap #6 — aggregated)
    "cost_metric_by_product_aggregated": EndpointConfig(
        old_path="/profitstream/v2/api/sources/metrics/ai/cost-metric-by-product",
        new_path="/api/v2/analytics/cost-by-product-aggregated",
    ),
    # Old: /profitstream/v2/api/sources/metrics/ai/cost-metrics-by-agents-over-time
    # New: /api/v2/analytics/cost-by-agent  (BACK-718 swap #7)
    "cost_metrics_by_agents_over_time": EndpointConfig(
        old_path="/profitstream/v2/api/sources/metrics/ai/cost-metrics-by-agents-over-time",
        new_path="/api/v2/analytics/cost-by-agent",
    ),
    # ── Aggregated cost endpoints ──────────────────────────────────────────
    # Old: /profitstream/v2/api/sources/metrics/ai/cost-metric-by-provider
    # New: /api/v2/analytics/cost-by-provider-aggregated  (BACK-718 swap #8)
    "cost_metric_by_provider": EndpointConfig(
        old_path="/profitstream/v2/api/sources/metrics/ai/cost-metric-by-provider",
        new_path="/api/v2/analytics/cost-by-provider-aggregated",
    ),
    # Old: /profitstream/v2/api/sources/metrics/ai/cost-metric-by-model
    # New: /api/v2/analytics/cost-by-model-aggregated  (BACK-718 swap #9)
    "cost_metric_by_model": EndpointConfig(
        old_path="/profitstream/v2/api/sources/metrics/ai/cost-metric-by-model",
        new_path="/api/v2/analytics/cost-by-model-aggregated",
    ),
    # ── Token usage endpoints ──────────────────────────────────────────────
    # Old: /profitstream/v2/api/sources/metrics/ai/tokens-per-minute-by-provider
    # New: /api/v2/analytics/tokens-per-minute  (BACK-718 swap #10)
    "tokens_per_minute_by_provider": EndpointConfig(
        old_path="/profitstream/v2/api/sources/metrics/ai/tokens-per-minute-by-provider",
        new_path="/api/v2/analytics/tokens-per-minute",
    ),
    # ── Revenue endpoints ──────────────────────────────────────────────────
    # Old: /profitstream/v2/api/sources/metrics/ai/revenue-metric-by-organization
    # New: /api/v2/analytics/revenue-per-customer  (BACK-718 swap #11)
    "revenue_metric_by_organization": EndpointConfig(
        old_path="/profitstream/v2/api/sources/metrics/ai/revenue-metric-by-organization",
        new_path="/api/v2/analytics/revenue-per-customer",
    ),
    # Old: /profitstream/v2/api/sources/metrics/ai/revenue-metric-by-product
    # New: /api/v2/analytics/revenue-per-product  (BACK-718 swap #12)
    "revenue_metric_by_product": EndpointConfig(
        old_path="/profitstream/v2/api/sources/metrics/ai/revenue-metric-by-product",
        new_path="/api/v2/analytics/revenue-per-product",
    ),
    # ── Client-side calculation endpoints (no direct new-API replacement) ──
    # Old: percentage-revenue-metric-by-organization
    # New: fetch from revenue-per-customer, calculate pct client-side  (BACK-718)
    "percentage_revenue_metric_by_organization": EndpointConfig(
        old_path="/profitstream/v2/api/sources/metrics/ai/percentage-revenue-metric-by-organization",
        new_path="/api/v2/analytics/revenue-per-customer",
        client_side_only=True,
    ),
    # Old: percentage-revenue-metric-by-product
    # New: fetch from revenue-per-product, calculate pct client-side  (BACK-718)
    "percentage_revenue_metric_by_product": EndpointConfig(
        old_path="/profitstream/v2/api/sources/metrics/ai/percentage-revenue-metric-by-product",
        new_path="/api/v2/analytics/revenue-per-product",
        client_side_only=True,
    ),
    # ── Agent task/call-count endpoints ───────────────────────────────────
    # Old: /profitstream/v2/api/sources/metrics/ai/call-count-metrics-by-agents
    # New: /api/v2/analytics/tasks-completed-by-agent  (BACK-718 swap #13)
    "call_count_metrics_by_agents": EndpointConfig(
        old_path="/profitstream/v2/api/sources/metrics/ai/call-count-metrics-by-agents",
        new_path="/api/v2/analytics/tasks-completed-by-agent",
    ),
    # ── Performance / latency endpoints (confirmed in BACK-717) ───────────
    # Old: performance-metric-by-provider  → measures requestDuration (avg latency)
    # New: /api/v2/analytics/response-time-by-vendor  (BACK-717 confirmed match)
    # Note: old returns milliseconds, new returns seconds — unit_multiplier=1000.0 normalises
    "performance_metric_by_provider": EndpointConfig(
        old_path="/profitstream/v2/api/sources/metrics/ai/performance-metric-by-provider",
        new_path="/api/v2/analytics/response-time-by-vendor",
        unit_multiplier=1000.0,
    ),
    # Old: performance-metric-by-model  → measures requestDuration (avg latency)
    # New: /api/v2/analytics/response-time-by-model  (BACK-717 confirmed match)
    # Note: old returns milliseconds, new returns seconds — unit_multiplier=1000.0 normalises
    "performance_metric_by_model": EndpointConfig(
        old_path="/profitstream/v2/api/sources/metrics/ai/performance-metric-by-model",
        new_path="/api/v2/analytics/response-time-by-model",
        unit_multiplier=1000.0,
    ),
    # Old: performance-metrics-by-agents  → avg task duration per agent
    # New: /api/v2/analytics/avg-time-by-agent  (BACK-717 confirmed match)
    # Note: old returns milliseconds, new returns seconds — unit_multiplier=1000.0 normalises
    "performance_metrics_by_agents": EndpointConfig(
        old_path="/profitstream/v2/api/sources/metrics/ai/performance-metrics-by-agents",
        new_path="/api/v2/analytics/avg-time-by-agent",
        unit_multiplier=1000.0,
    ),
    # ── Status / connectivity endpoint ────────────────────────────────────
    # Old: /profitstream/v2/api/sources/metrics/ai/data-connected
    # New: /api/v2/status/connection  (BACK-718 swap #14)
    "data_connected": EndpointConfig(
        old_path="/profitstream/v2/api/sources/metrics/ai/data-connected",
        new_path="/api/v2/status/connection",
    ),
    # ── Transaction listing endpoint ──────────────────────────────────────
    # Old: /profitstream/v2/api/sources/metrics/ai/completions  (GET — list transactions)
    # New: TBD — new ClickHouse-backed transactions endpoint not yet confirmed
    "completions": EndpointConfig(
        old_path="/profitstream/v2/api/sources/metrics/ai/completions",
        new_path=None,
        mapping_status="TBD",
    ),
}


def _use_new_api() -> bool:
    """Return True when the new analytics API feature flag is enabled."""
    value = os.getenv("REVENIUM_USE_NEW_ANALYTICS_API", "false").strip().lower()
    return value in ("true", "1", "yes")


def _resolved_app_base_url() -> str:
    """Return the configured new-analytics base URL, falling back to the default.

    Raises:
        ValueError: If the resolved URL does not use the HTTPS scheme, to prevent
            Bearer tokens from being forwarded to a non-HTTPS host.
    """
    url = (
        get_config_value("REVENIUM_APP_BASE_URL", DEFAULT_APP_BASE_URL)
        or DEFAULT_APP_BASE_URL
    )
    if not url.startswith("https://"):
        raise ValueError(
            f"REVENIUM_APP_BASE_URL must use HTTPS to prevent Bearer token leakage,"
            f" got: {url!r}"
        )
    return url


def get_endpoint_path(endpoint_key: str) -> str:
    """Return the active API path for the given endpoint key.

    When REVENIUM_USE_NEW_ANALYTICS_API is enabled, returns the new ClickHouse-backed
    analytics path. Otherwise returns the legacy profitstream path.

    Args:
        endpoint_key: Registry key (e.g. 'cost_metric_by_provider')

    Returns:
        The active path string to use for HTTP requests.

    Raises:
        KeyError: If the key is not in the registry
    """
    config = get_endpoint_config(endpoint_key)
    if _use_new_api() and config.new_path is not None:
        return config.new_path
    return config.old_path


def get_endpoint_config(key: str) -> EndpointConfig:
    """Return the EndpointConfig for the given endpoint key.

    When REVENIUM_USE_NEW_ANALYTICS_API is true, the returned config reflects
    the current REVENIUM_APP_BASE_URL so callers don't have to look it up separately.

    Args:
        key: Registry key (e.g. 'cost_by_provider')

    Returns:
        EndpointConfig for the requested endpoint

    Raises:
        KeyError: If the key is not in the registry
        NotImplementedError: If REVENIUM_USE_NEW_ANALYTICS_API is enabled and the
            endpoint's mapping_status is 'TBD' (new API path not yet confirmed)
    """
    if key not in _ENDPOINT_REGISTRY:
        raise KeyError(
            f"Unknown endpoint key '{key}'. Valid keys: {sorted(_ENDPOINT_REGISTRY.keys())}"
        )
    config = _ENDPOINT_REGISTRY[key]

    if _use_new_api():
        if config.new_path is None and config.mapping_status == "TBD":
            # No new API mapping yet — fall back to legacy routing so that enabling
            # REVENIUM_USE_NEW_ANALYTICS_API for already-migrated endpoints does not
            # simultaneously break all unmapped (TBD) endpoints.
            # The caller receives the legacy config unchanged; Phase 2 will supply
            # new_path values as each endpoint is confirmed.
            return config
        # Patch new_base_url to whatever is currently configured
        try:
            app_base_url = _resolved_app_base_url()
        except ValueError as exc:
            from .common.error_handling import ToolError

            raise ToolError(
                f"REVENIUM_APP_BASE_URL is misconfigured: {exc}. "
                "Set REVENIUM_APP_BASE_URL to a valid HTTPS URL (e.g. https://app.revenium.ai)."
            ) from exc
        if app_base_url != config.new_base_url:
            # Return a copy with the live base URL so the original is not mutated
            return EndpointConfig(
                old_path=config.old_path,
                new_path=config.new_path,
                new_base_url=app_base_url,
                client_side_only=config.client_side_only,
                mapping_status=config.mapping_status,
                unit_multiplier=config.unit_multiplier,
            )

    return config


def resolve_analytics_request(
    key: str,
    team_id: str,
    period: str,
    extra_old_params: Optional[Dict[str, Any]] = None,
    extra_new_params: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    """Return (path, params, call_kwargs) for the given analytics endpoint key.

    Automatically selects either the old profitstream path or the new ClickHouse
    analytics path based on the REVENIUM_USE_NEW_ANALYTICS_API feature flag.

    When using the new API (flag enabled):
      - path is the new endpoint path on app.revenium.ai
      - params use startDate/endDate ISO 8601 (period converted automatically)
      - extra_new_params (if provided) are merged in (e.g. tokenType)
      - call_kwargs contains ``base_url`` and ``use_bearer=True``

    When using the old API (flag disabled or endpoint not yet mapped):
      - path is the legacy profitstream path
      - params use teamId and period
      - extra_old_params (if provided) are merged in (e.g. group, tokenType)
      - call_kwargs is empty (uses default base_url and x-api-key auth)

    Args:
        key: Registry key (e.g. 'cost_metric_by_provider')
        team_id: Team identifier — used for old API calls only
        period: Period string (e.g. 'SEVEN_DAYS') — converted to ISO 8601 dates
            for new API calls
        extra_old_params: Additional params merged into old-API calls only
            (e.g. ``{"group": "TOTAL", "tokenType": "TOTAL"}``). Ignored when
            the new API is active.
        extra_new_params: Additional params merged into new-API calls only
            (e.g. ``{"tokenType": "TOTAL"}``). Ignored when the old API is
            active.

    Returns:
        Tuple of (path, params, call_kwargs) ready to pass to ``client.get()``:
        ``await client.get(path, params=params, **call_kwargs)``
    """
    config = get_endpoint_config(key)

    if _use_new_api() and config.new_path is not None:
        from .analytics_parameters import TimePeriod
        from .date_parser import period_to_date_range

        try:
            start_date, end_date = period_to_date_range(TimePeriod(period))
        except ValueError:
            # Unknown period string — fall back to 30-day window rather than crash
            logger.warning("Unknown period %r — falling back to 30-day window", period)
            from datetime import datetime, timedelta, timezone

            now = datetime.now(timezone.utc)
            start = now - timedelta(days=30)
            ms_start = start.microsecond // 1000
            ms_end = now.microsecond // 1000
            start_date = start.strftime(f"%Y-%m-%dT%H:%M:%S.{ms_start:03d}Z")
            end_date = now.strftime(f"%Y-%m-%dT%H:%M:%S.{ms_end:03d}Z")

        new_params: Dict[str, Any] = {"startDate": start_date, "endDate": end_date}
        if extra_new_params:
            new_params.update(extra_new_params)
        return (
            config.new_path,
            new_params,
            {"base_url": config.new_base_url, "use_bearer": True},
        )

    # ── Legacy profitstream API ────────────────────────────────────────────
    params: Dict[str, Any] = {"teamId": team_id, "period": period}
    if extra_old_params:
        params.update(extra_old_params)
    return config.old_path, params, {}


def get_unit_multiplier(key: str) -> float:
    """Return the unit multiplier for the given endpoint key.

    Used to convert new-API metric values to the same unit as the old API.
    For most endpoints this returns 1.0 (no conversion needed).
    For the three response-time endpoints it returns 1000.0 (seconds → milliseconds).

    Apply to ``metricResult`` values only when ``REVENIUM_USE_NEW_ANALYTICS_API`` is
    enabled — old-API values are already in the correct unit.

    Args:
        key: Registry key (e.g. 'performance_metric_by_provider')

    Returns:
        Multiplier float (1.0 for no conversion, 1000.0 for seconds→ms)

    Raises:
        KeyError: If the key is not in the registry
    """
    config = get_endpoint_config(key)
    return config.unit_multiplier if _use_new_api() else 1.0
