"""Auth + tenant-resolution contract test against the live HyperCurrent backend.

These surfaces are backend-owned semantics that our auth layer depends on but
does not control. The point of this test is drift detection: if the platform
changes the status code or body shape of any surface below, a build fails here
with actual-vs-expected output instead of the change silently breaking
production auth. BACK-2318 established the precedent that a backend contract our
code consumes deserves a pinned, live-run regression test rather than a mock.

The surfaces are auth-mode-independent. The identity and rejection contracts on
``/profitstream/v2/api/users/me`` (x-api-key) are what the ``api_key`` and
``env`` auth modes consume through
``src/revenium_mcp_server/auth/api_key_validator.py``. The analytics-host
contract (Bearer) is what the ``clerk``-mode analytics dependency consumes
through the ``_get_app_base_url`` path in ``src/revenium_mcp_server/client.py``.
Pinning them here keeps every mode honest against one backend.

Live-network opt-in only: skipped unless REVENIUM_INTEGRATION_TESTS,
REVENIUM_API_KEY, and REVENIUM_BASE_URL are all set. Never logs key material;
failure messages reflect only status codes and response bodies (the backend
error envelopes carry no secrets).
"""
from __future__ import annotations

import os

import httpx
import pytest

from src.revenium_mcp_server.endpoint_registry import paired_app_base_url

pytestmark = pytest.mark.skipif(
    not os.getenv("REVENIUM_INTEGRATION_TESTS")
    or not os.getenv("REVENIUM_API_KEY")
    or not os.getenv("REVENIUM_BASE_URL"),
    reason=(
        "Auth contract test needs REVENIUM_INTEGRATION_TESTS=1, REVENIUM_API_KEY, "
        "and REVENIUM_BASE_URL set (live dev network opt-in)"
    ),
)

_USERS_ME_PATH = "/profitstream/v2/api/users/me"
_PRODUCTS_PATH = "/profitstream/v2/api/products"
_ANALYTICS_PROVIDERS_PATH = "/api/v2/analytics/filter-options/providers"

# 403-forbidden rejection contract inputs: malformed, well-formed-but-unknown,
# metering-format fake, and empty. All four must reject identically.
_REJECTED_KEYS = [
    pytest.param("not-a-key", id="malformed"),
    pytest.param("rev_sk_0000000000000000000000000000", id="well-formed-unknown"),
    pytest.param("rev_mk_0000000000000000000000000000", id="metering-format-fake"),
    pytest.param("", id="empty"),
]

_HTTP_TIMEOUT = 30.0


def _base_url() -> str:
    return os.environ["REVENIUM_BASE_URL"].rstrip("/")


def _api_key() -> str:
    return os.environ["REVENIUM_API_KEY"]


def _detail(resp: httpx.Response, expected_status: int) -> str:
    """Failure detail: expected vs actual status and the (secret-free) body."""
    return (
        f"expected HTTP {expected_status}, got {resp.status_code}. "
        f"body={resp.text[:512]!r}"
    )


def test_valid_key_yields_identity() -> None:
    """A valid key resolves the exact identity shape the validator requires.

    Mirrors the 200 branch of ``api_key_validator._validate_uncached``: ``id``
    and ``tenantId`` are hard-required, ``teams`` must be non-empty, and
    ``defaultTeamId`` is either null (fall back to the first team) or a member
    of the team ids. On this dev key ``defaultTeamId`` is live-null, so the
    fall-back path is real behavior, not a hypothetical.
    """
    with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
        resp = client.get(
            f"{_base_url()}{_USERS_ME_PATH}",
            headers={"x-api-key": _api_key()},
        )
    assert resp.status_code == 200, _detail(resp, 200)
    data = resp.json()
    assert "id" in data, f"identity missing 'id'. body={data!r}"
    assert "tenantId" in data, f"identity missing 'tenantId'. body={data!r}"
    teams = data.get("teams") or []
    assert teams, f"identity has no teams; validator cannot resolve a tenant. body={data!r}"
    team_ids = [t["id"] for t in teams]
    default_team_id = data.get("defaultTeamId")
    assert default_team_id is None or default_team_id in team_ids, (
        f"defaultTeamId {default_team_id!r} is neither null nor a member of "
        f"team ids {team_ids!r} — validator fall-back invariant broken"
    )


@pytest.mark.parametrize("token", _REJECTED_KEYS)
def test_rejected_keys_are_403_forbidden(token: str) -> None:
    """Every rejected key form returns a 403 Forbidden envelope, never 401.

    The live backend rejects malformed, unknown, metering-format, and empty
    keys with HTTP 403 and body ``{error, path, status, timestamp}`` where
    ``error == "Forbidden"``. A 401 here would mean the backend contract moved
    (our validator has a documented 401 branch that this surface does not
    exercise) — see BACK-2489 before relaxing this assertion toward our code.

    Revocation note: this platform's key management offers rename and delete
    only (no suspend/disable), and a deleted key becomes indistinguishable
    from one that never existed - so the well-formed-unknown case below IS
    the post-revocation contract on this backend. The validator's distinct
    suspended/expired 403 branches cannot be pinned from a UI-provisioned
    fixture; they would need a backend-side state change.
    """
    with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
        resp = client.get(
            f"{_base_url()}{_USERS_ME_PATH}",
            headers={"x-api-key": token},
        )
    assert resp.status_code == 403, _detail(resp, 403)
    body = resp.json()
    expected_keys = {"error", "path", "status", "timestamp"}
    assert expected_keys <= set(body), (
        f"403 envelope missing keys {expected_keys - set(body)}. body={body!r}"
    )
    assert body["error"] == "Forbidden", (
        f"expected error=='Forbidden', got {body['error']!r}. body={body!r}"
    )


@pytest.mark.parametrize(
    ("team_id", "assert_message"),
    [
        pytest.param("AAAAAAA", True, id="undecodable"),
        pytest.param("", False, id="empty"),
    ],
)
def test_undecodable_team_id_is_400(team_id: str, assert_message: bool) -> None:
    """An undecodable teamId is rejected 400 before any data is scoped.

    Authenticated with a valid key so the request reaches teamId decoding; the
    backend returns HTTP 400 with a ``{timestamp, status, error}`` envelope
    where ``error == "Bad Request"``. For a structurally-undecodable id the
    ``message`` starts with "Failed to decode hashed Id"; the empty-id case is
    pinned only to the 400 status because its message may differ.
    """
    with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
        resp = client.get(
            f"{_base_url()}{_PRODUCTS_PATH}",
            params={"teamId": team_id, "page": 0, "size": 1},
            headers={"x-api-key": _api_key()},
        )
    assert resp.status_code == 400, _detail(resp, 400)
    body = resp.json()
    assert body.get("error") == "Bad Request", (
        f"expected error=='Bad Request', got {body.get('error')!r}. body={body!r}"
    )
    if assert_message:
        message = body.get("message", "")
        assert message.startswith("Failed to decode hashed Id"), (
            f"expected message to start with 'Failed to decode hashed Id', "
            f"got {message!r}. body={body!r}"
        )


def test_analytics_host_bearer_contract() -> None:
    """The analytics host authorizes Bearer tokens: valid -> 200, garbage -> 401.

    The analytics host is derived from REVENIUM_BASE_URL via the same known-host
    pairing the client uses (``paired_app_base_url``), so this test follows the
    configured environment rather than a hardcoded host. A garbage bearer yields
    HTTP 401 with body ``{"code": "UNAUTHORIZED", ...}`` — the regression surface
    BACK-2318 pinned.
    """
    # Production (resolve_analytics_request, force_new endpoints) sends
    # startDate/endDate and NO teamId - the analytics host resolves the team
    # from the bearer auth context. The window is built with the SAME code
    # path production uses (period_to_date_range -> _format_iso8601,
    # millisecond precision), so this probe can never drift from the request
    # shape real analytics calls send.
    from src.revenium_mcp_server.analytics_parameters import TimePeriod
    from src.revenium_mcp_server.date_parser import period_to_date_range

    start_date, end_date = period_to_date_range(TimePeriod.THIRTY_DAYS)
    window = {"startDate": start_date, "endDate": end_date}
    app_base_url = paired_app_base_url(_base_url()).rstrip("/")
    url = f"{app_base_url}{_ANALYTICS_PROVIDERS_PATH}"

    with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
        ok = client.get(
            url,
            params=window,
            headers={"Authorization": f"Bearer {_api_key()}"},
        )
        bad = client.get(
            url,
            params=window,
            headers={"Authorization": "Bearer garbage-token"},
        )

    assert ok.status_code == 200, _detail(ok, 200)
    assert bad.status_code == 401, _detail(bad, 401)
    bad_body = bad.json()
    assert bad_body.get("code") == "UNAUTHORIZED", (
        f"expected code=='UNAUTHORIZED' on garbage bearer, got {bad_body.get('code')!r}. "
        f"body={bad_body!r}"
    )


# --- Optional surfaces: each gated on its own env var. They stay skipped until
# the corresponding value is provisioned in dev, then pin behavior we cannot
# safely fabricate (a real metering key, a real revoked key, a real foreign
# team id). ---


def test_metering_key_rejected_by_users_me() -> None:
    """A real metering (rev_mk_) key must not yield a full identity.

    Our validator pre-checks the rev_mk_ prefix client-side, but the backend
    behavior must still be pinned: metering scope is not identity scope.
    """
    metering_key = os.getenv("REVENIUM_CONTRACT_METERING_KEY")
    if not metering_key:
        pytest.skip(
            "REVENIUM_CONTRACT_METERING_KEY not set; provision a real rev_mk_ dev "
            "key to pin metering-scope rejection at /users/me"
        )
    with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
        resp = client.get(
            f"{_base_url()}{_USERS_ME_PATH}",
            headers={"x-api-key": metering_key},
        )
    assert resp.status_code != 200, (
        "metering key yields a full identity — scope contract violation"
    )
    assert resp.status_code == 403, _detail(resp, 403)
    body = resp.json()
    assert body.get("error") == "Forbidden", (
        f"expected error=='Forbidden', got {body.get('error')!r}. body={body!r}"
    )


def test_foreign_team_id_is_not_accessible() -> None:
    """A valid other-tenant team id must not return 200 — cross-tenant isolation."""
    foreign_team_id = os.getenv("REVENIUM_CONTRACT_FOREIGN_TEAM_ID")
    if not foreign_team_id:
        pytest.skip(
            "REVENIUM_CONTRACT_FOREIGN_TEAM_ID not set; provision a valid "
            "other-tenant team id to pin cross-tenant isolation on /products"
        )
    with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
        resp = client.get(
            f"{_base_url()}{_PRODUCTS_PATH}",
            params={"teamId": foreign_team_id, "page": 0, "size": 1},
            headers={"x-api-key": _api_key()},
        )
    assert resp.status_code != 200, (
        f"foreign teamId returned 200 — cross-tenant isolation breach. "
        f"actual status={resp.status_code}, body={resp.text[:512]!r}"
    )
    # Live-pinned semantics (dev, 2026-08-03): a valid but foreign teamId is
    # 403 with message "Access Denied" - distinct from the auth-rejection 403
    # ("Forbidden" with no access message). A drift here below 403 (e.g. an
    # empty 200) would be the isolation-breach case caught above; a different
    # rejection shape still fails loudly so the change is looked at.
    assert resp.status_code == 403, _detail(resp, 403)
    body = resp.json()
    assert body.get("message") == "Access Denied", (
        f"expected message=='Access Denied' on foreign teamId, got "
        f"{body.get('message')!r}. body={body!r}"
    )
