"""Endpoint registry for Revenium analytics API migration (BACK-716).

Maps analytics endpoint keys to their old (profitstream) and new (ClickHouse-backed)
paths, along with routing metadata consumed by the client layer during migration.

Feature flag: set env var REVENIUM_USE_NEW_ANALYTICS_API=true to route through the
new analytics host (REVENIUM_APP_BASE_URL / https://app.revenium.ai).
"""

import os
from dataclasses import dataclass, field
from typing import Dict, Optional

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
    """True for metrics that are computed client-side with no direct new-API endpoint."""

    mapping_status: str = "READY"
    """Migration status: 'READY' means the new path is confirmed; 'TBD' means not yet verified."""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_ENDPOINT_REGISTRY: Dict[str, EndpointConfig] = {
    # Cost analytics
    "cost_by_provider": EndpointConfig(
        old_path="/api/v1/analytics/cost/by-provider",
        new_path="/api/v2/analytics/cost/by-provider",
    ),
    "cost_by_model": EndpointConfig(
        old_path="/api/v1/analytics/cost/by-model",
        new_path="/api/v2/analytics/cost/by-model",
    ),
    "cost_by_project": EndpointConfig(
        old_path="/api/v1/analytics/cost/by-project",
        new_path="/api/v2/analytics/cost/by-project",
    ),
    "cost_by_agent": EndpointConfig(
        old_path="/api/v1/analytics/cost/by-agent",
        new_path="/api/v2/analytics/cost/by-agent",
    ),
    # Token analytics
    "token_by_provider": EndpointConfig(
        old_path="/api/v1/analytics/tokens/by-provider",
        new_path="/api/v2/analytics/tokens/by-provider",
    ),
    "token_by_model": EndpointConfig(
        old_path="/api/v1/analytics/tokens/by-model",
        new_path="/api/v2/analytics/tokens/by-model",
    ),
    "token_by_project": EndpointConfig(
        old_path="/api/v1/analytics/tokens/by-project",
        new_path="/api/v2/analytics/tokens/by-project",
    ),
    "token_by_agent": EndpointConfig(
        old_path="/api/v1/analytics/tokens/by-agent",
        new_path="/api/v2/analytics/tokens/by-agent",
    ),
    # Request analytics
    "request_by_provider": EndpointConfig(
        old_path="/api/v1/analytics/requests/by-provider",
        new_path="/api/v2/analytics/requests/by-provider",
    ),
    "request_by_model": EndpointConfig(
        old_path="/api/v1/analytics/requests/by-model",
        new_path="/api/v2/analytics/requests/by-model",
    ),
    "request_by_project": EndpointConfig(
        old_path="/api/v1/analytics/requests/by-project",
        new_path="/api/v2/analytics/requests/by-project",
    ),
    "request_by_agent": EndpointConfig(
        old_path="/api/v1/analytics/requests/by-agent",
        new_path="/api/v2/analytics/requests/by-agent",
    ),
    # Performance analytics — new endpoints not yet confirmed
    "performance_metric_by_provider": EndpointConfig(
        old_path="/api/v1/analytics/performance/by-provider",
        new_path=None,
        mapping_status="TBD",
    ),
    "performance_metric_by_model": EndpointConfig(
        old_path="/api/v1/analytics/performance/by-model",
        new_path=None,
        mapping_status="TBD",
    ),
    "performance_metrics_by_agents": EndpointConfig(
        old_path="/api/v1/analytics/performance/by-agent",
        new_path=None,
        mapping_status="TBD",
    ),
}


def _use_new_api() -> bool:
    """Return True when the new analytics API feature flag is enabled."""
    value = os.getenv("REVENIUM_USE_NEW_ANALYTICS_API", "false").strip().lower()
    return value in ("true", "1", "yes")


def _resolved_app_base_url() -> str:
    """Return the configured new-analytics base URL, falling back to the default."""
    return (
        get_config_value("REVENIUM_APP_BASE_URL", DEFAULT_APP_BASE_URL)
        or DEFAULT_APP_BASE_URL
    )


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
    """
    config = _ENDPOINT_REGISTRY[key]

    if _use_new_api():
        # Patch new_base_url to whatever is currently configured
        app_base_url = _resolved_app_base_url()
        if app_base_url != config.new_base_url:
            # Return a copy with the live base URL so the original is not mutated
            return EndpointConfig(
                old_path=config.old_path,
                new_path=config.new_path,
                new_base_url=app_base_url,
                client_side_only=config.client_side_only,
                mapping_status=config.mapping_status,
            )

    return config
