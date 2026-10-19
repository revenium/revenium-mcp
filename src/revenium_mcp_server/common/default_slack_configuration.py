"""The Slack configuration new alerts use when the caller names none, kept per organization."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Optional

from ..auth.tenant_scope import LOCAL_TENANT_SCOPE, tenant_scope
from ..config_store import get_config_value
from .tenant_scoped_store import TenantScopedStore

if TYPE_CHECKING:
    from ..auth.tenant_context import TenantContext

DEFAULT_SLACK_CONFIG_ENV = "REVENIUM_DEFAULT_SLACK_CONFIG_ID"
_DEFAULT_ENTRY_ID = "default_slack_configuration"
# Past the cap TenantScopedStore evicts the oldest default, and that organization's new
# alerts get no default Slack configuration until it sets one again. One hosted process
# serves far fewer organizations than this, so eviction should never happen in practice.
_MAX_HOSTED_ORGANIZATIONS = 10000
HOSTED_DEFAULT_LIFETIME_NOTE = (
    "Set it again if the server restarts, or if it later reports no default: "
    "the server keeps defaults for a limited number of organizations and forgets the oldest first."
)

_hosted_defaults: TenantScopedStore[str] = TenantScopedStore(max_entries=_MAX_HOSTED_ORGANIZATIONS)


def is_local_server(ctx: Optional["TenantContext"] = None) -> bool:
    """True on the single-customer server, where the process environment belongs to that customer.

    Raises:
        PermissionError: In clerk/api_key mode when no tenant context exists.
    """
    return tenant_scope(ctx) == LOCAL_TENANT_SCOPE


def get_default_slack_config_id(ctx: Optional["TenantContext"] = None) -> Optional[str]:
    """Return the default Slack configuration id of the organization this request acts for.

    The local server reads its environment (and auto-discovered values); a
    hosted organization only ever sees the default it chose itself.
    """
    scope = tenant_scope(ctx)
    if scope == LOCAL_TENANT_SCOPE:
        return get_config_value(DEFAULT_SLACK_CONFIG_ENV)
    return _hosted_defaults.get(scope, _DEFAULT_ENTRY_ID)


def set_default_slack_config_id(config_id: str, ctx: Optional["TenantContext"] = None) -> None:
    """Remember ``config_id`` as the default for the organization this request acts for.

    Hosted organizations keep it in this process's memory until it restarts;
    the process environment is shared by every hosted customer.
    """
    scope = tenant_scope(ctx)
    if scope == LOCAL_TENANT_SCOPE:
        os.environ[DEFAULT_SLACK_CONFIG_ENV] = config_id
        return
    _hosted_defaults.put(scope, _DEFAULT_ENTRY_ID, config_id)


def clear_hosted_defaults() -> None:
    _hosted_defaults.clear()

