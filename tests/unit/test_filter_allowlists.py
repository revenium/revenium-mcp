"""BACK-2783: per-tool filter allowlists and the parameters we stopped sending.

Three things are pinned here:

1. Every list tool that accepts a caller-supplied ``filters`` object bounds its
   keys to the parameters its endpoint declares. An unrecognised key raises,
   naming the key and listing the valid ones, instead of being forwarded and
   silently discarded upstream — which returned an unfiltered list that read as
   a filtered one.
2. Every allowlisted key reaches the client under the camelCase name the
   backend declares.
3. The parameters that were being sent but are not in any endpoint's declared
   set — ``paged`` on two client calls, ``group`` on three analytics reports —
   are gone, and asking for an aggregation those three reports cannot produce
   is an error rather than TOTAL-shaped data wearing a MEAN label.

The allowlists themselves were verified against hypercurrent origin/develop on
2026-08-28; each map carries the controller it was checked against.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.revenium_mcp_server.auth import AuthConfig
from src.revenium_mcp_server.client import ReveniumClient
from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError
from src.revenium_mcp_server.common.validation import apply_filter_allowlist


# ---------------------------------------------------------------------------
# apply_filter_allowlist — the shared boundary
# ---------------------------------------------------------------------------


_MAP = {"query": "query", "start_date": "startDate", "sort": "sort"}


class TestApplyFilterAllowlist:
    def test_none_is_empty(self):
        assert apply_filter_allowlist(None, _MAP, action="list") == {}

    def test_empty_is_empty(self):
        assert apply_filter_allowlist({}, _MAP, action="list") == {}

    def test_snake_case_key_maps_to_camel_case(self):
        assert apply_filter_allowlist(
            {"start_date": "2026-01-01"}, _MAP, action="list"
        ) == {"startDate": "2026-01-01"}

    def test_camel_case_key_passes_through(self):
        """Callers and older examples already write camelCase."""
        assert apply_filter_allowlist(
            {"startDate": "2026-01-01"}, _MAP, action="list"
        ) == {"startDate": "2026-01-01"}

    def test_none_values_are_omitted(self):
        assert apply_filter_allowlist({"query": None}, _MAP, action="list") == {}

    def test_pagination_keys_are_dropped_not_rejected(self):
        """page/size inside filters duplicate the explicit arguments."""
        assert apply_filter_allowlist(
            {"page": 3, "size": 5, "query": "x"}, _MAP, action="list"
        ) == {"query": "x"}

    def test_unknown_key_raises_naming_key_and_valid_set(self):
        with pytest.raises(ToolError) as exc:
            apply_filter_allowlist({"stauts": "active"}, _MAP, action="list_things")
        message = str(exc.value)
        assert "'stauts'" in message
        assert "list_things" in message
        for valid in _MAP:
            assert valid in message
        assert exc.value.error_code == ErrorCodes.VALIDATION_ERROR
        assert exc.value.field == "filters"

    def test_every_unknown_key_is_named(self):
        with pytest.raises(ToolError) as exc:
            apply_filter_allowlist({"a": 1, "b": 2}, _MAP, action="list")
        assert "'a'" in str(exc.value)
        assert "'b'" in str(exc.value)

    def test_non_mapping_raises(self):
        with pytest.raises(ToolError) as exc:
            apply_filter_allowlist(["query"], _MAP, action="list")
        assert "must be an object" in str(exc.value)

    def test_empty_allowlist_rejects_everything(self):
        with pytest.raises(ToolError) as exc:
            apply_filter_allowlist({"query": "x"}, {}, action="list")
        assert "does not accept any filter keys" in str(exc.value)


# ---------------------------------------------------------------------------
# Per-tool allowlists
# ---------------------------------------------------------------------------


def _paged_client():
    client = MagicMock()
    client._extract_embedded_data = MagicMock(return_value=[])
    client._extract_pagination_info = MagicMock(return_value={})
    return client


async def _list_sources(client, filters):
    from src.revenium_mcp_server.tools_decomposed.source_management import SourceManager

    client.get_sources = AsyncMock(return_value={})
    await SourceManager(client).list_sources({"filters": filters})
    return client.get_sources.call_args[1]


async def _list_agents(client, filters):
    from src.revenium_mcp_server.tools_decomposed.agent_management import AgentManager

    client.get_agents = AsyncMock(return_value={})
    await AgentManager(client).list_agents({"filters": filters})
    return client.get_agents.call_args[1]


async def _list_cost_controls(client, filters):
    from src.revenium_mcp_server.tools_decomposed.cost_controls_management import (
        CostControlsManager,
    )

    client.get_cost_controls = AsyncMock(return_value={})
    await CostControlsManager(client).list_cost_controls({"filters": filters})
    return client.get_cost_controls.call_args[1]


async def _list_subscriptions(client, filters):
    from src.revenium_mcp_server.tools_decomposed.subscription_management import (
        SubscriptionManager,
    )

    client.get_subscriptions = AsyncMock(return_value={})
    await SubscriptionManager(client).list_subscriptions({"filters": filters})
    return client.get_subscriptions.call_args[1]


async def _list_users(client, filters):
    from src.revenium_mcp_server.tools_decomposed.customer_management import UserManager

    client.get_users = AsyncMock(return_value={})
    await UserManager(client).list_users({"filters": filters})
    return client.get_users.call_args[1]


async def _list_teams(client, filters):
    from src.revenium_mcp_server.tools_decomposed.customer_management import TeamManager

    client.get_teams = AsyncMock(return_value={})
    await TeamManager(client).list_teams({"filters": filters})
    return client.get_teams.call_args[1]


async def _list_jobs(client, filters):
    from src.revenium_mcp_server.tools_decomposed.job_management import JobManager

    client.get_jobs = AsyncMock(return_value={})
    await JobManager(client).list_jobs({"filters": filters})
    return client.get_jobs.call_args[1]


async def _conversion_funnel(client, filters):
    from src.revenium_mcp_server.tools_decomposed.job_management import JobManager

    client.get_job_conversion_funnel = AsyncMock(return_value={})
    await JobManager(client).get_conversion_funnel({"filters": filters})
    return client.get_job_conversion_funnel.call_args[1]


async def _list_tools(client, filters):
    from src.revenium_mcp_server.tools_decomposed.tool_management import ToolManager

    client.list_tools = AsyncMock(return_value={})
    await ToolManager(client).list_tools({"filters": filters})
    return client.list_tools.call_args[1]


async def _list_tool_events(client, filters):
    from src.revenium_mcp_server.tools_decomposed.tool_management import ToolManager

    client.list_tool_events = AsyncMock(return_value={})
    await ToolManager(client).list_events({"filters": filters})
    return client.list_tool_events.call_args[1]


async def _list_metering_elements(client, filters):
    from src.revenium_mcp_server.tools_decomposed.metering_elements_management import (
        MeteringElementsManager,
    )

    client.get_metering_element_definitions = AsyncMock(return_value={})
    await MeteringElementsManager().list_elements(client, {"filters": filters})
    return client.get_metering_element_definitions.call_args[1]


# (label, caller, one valid snake_case filter, the camelCase name it becomes)
_TOOL_CASES = [
    ("list_sources", _list_sources, {"query": "payments"}, {"query": "payments"}),
    ("list_agents", _list_agents, {"query": "copilot"}, {"query": "copilot"}),
    ("list_cost_controls", _list_cost_controls, {"query": "monthly"}, {"query": "monthly"}),
    ("list_subscriptions", _list_subscriptions, {"query": "ent"}, {"query": "ent"}),
    ("list_users", _list_users, {"query": "acme"}, {"query": "acme"}),
    ("list_teams", _list_teams, {"query": "acme"}, {"query": "acme"}),
    (
        "list_jobs",
        _list_jobs,
        {"execution_status": "SUCCESS", "start_date": "2026-01-01"},
        {"executionStatus": "SUCCESS", "startDate": "2026-01-01"},
    ),
    (
        "get_conversion_funnel",
        _conversion_funnel,
        {"job_type": "LEAD", "end_date": "2026-01-31"},
        {"jobType": "LEAD", "endDate": "2026-01-31"},
    ),
    ("list_tools", _list_tools, {"query": "search"}, {"query": "search"}),
    (
        "list_tool_events",
        _list_tool_events,
        {"tool_id": "tool_1", "charge_min": "0.5"},
        {"toolId": "tool_1", "chargeMin": "0.5"},
    ),
    (
        "list_metering_elements",
        _list_metering_elements,
        {"source_ids": "src_1"},
        {"sourceIds": "src_1"},
    ),
]


@pytest.mark.parametrize(
    "label,caller,valid_filters,expected",
    _TOOL_CASES,
    ids=[case[0] for case in _TOOL_CASES],
)
@pytest.mark.asyncio
async def test_allowlisted_filters_reach_the_client_camel_cased(
    label, caller, valid_filters, expected
):
    kwargs = await caller(_paged_client(), valid_filters)
    for name, value in expected.items():
        assert kwargs.get(name) == value, f"{label}: {name} missing from {kwargs}"


@pytest.mark.parametrize(
    "label,caller,valid_filters,expected",
    _TOOL_CASES,
    ids=[case[0] for case in _TOOL_CASES],
)
@pytest.mark.asyncio
async def test_invented_filter_key_is_rejected_naming_it(
    label, caller, valid_filters, expected
):
    """The model's invented key never reaches the API."""
    with pytest.raises(ToolError) as exc:
        await caller(_paged_client(), {"statuss": "active"})
    message = str(exc.value)
    assert "'statuss'" in message
    # The valid set is named in the same message the caller reads.
    for key in valid_filters:
        assert key in message, f"{label}: {key} missing from {message}"


@pytest.mark.asyncio
async def test_subscriber_credentials_allowlist():
    from src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management import (
        SubscriberCredentialsManagement,
    )

    tool = SubscriberCredentialsManagement.__new__(SubscriberCredentialsManagement)
    client = _paged_client()
    client.get_credentials = AsyncMock(return_value={})

    with pytest.raises(ToolError) as exc:
        await tool._list_credentials({"filters": {"statuss": "active"}}, client=client)
    assert "'statuss'" in str(exc.value)
    assert "query" in str(exc.value)
    client.get_credentials.assert_not_called()


@pytest.mark.asyncio
async def test_alert_list_allowlist_rejects_severity():
    """'severity' is the exact key the natural-language path used to invent."""
    from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement

    tool = AlertManagement.__new__(AlertManagement)
    tool.alert_manager = MagicMock()
    tool.alert_manager.list_alerts = AsyncMock(return_value=[])

    with pytest.raises(ToolError) as exc:
        await tool._handle_list(
            _paged_client(), {"resource_type": "alerts", "filters": {"severity": "high"}}
        )
    message = str(exc.value)
    assert "'severity'" in message
    assert "resolved" in message
    tool.alert_manager.list_alerts.assert_not_called()


@pytest.mark.asyncio
async def test_alert_list_forwards_declared_keys():
    from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement

    tool = AlertManagement.__new__(AlertManagement)
    tool.alert_manager = MagicMock()
    tool.alert_manager.list_alerts = AsyncMock(return_value=[])

    await tool._handle_list(
        _paged_client(),
        {"resource_type": "alerts", "filters": {"anomaly_id": "an_1", "resolved": True}},
    )
    forwarded = tool.alert_manager.list_alerts.call_args[0][3]
    assert forwarded == {"anomalyId": "an_1", "resolved": True}


# ---------------------------------------------------------------------------
# `paged` — a name no endpoint declares
# ---------------------------------------------------------------------------


def _client_with_mocked_get() -> ReveniumClient:
    client = ReveniumClient(
        auth_config=AuthConfig(
            api_key="test-key-xyz-long-enough",
            team_id="team_abc",
            base_url="https://api.test.revenium.ai",
            timeout=5.0,
            max_retries=0,
        )
    )
    client.get = AsyncMock(return_value={})
    return client


class TestPagedIsNotSent:
    @pytest.mark.asyncio
    async def test_get_alerts_omits_paged(self):
        client = _client_with_mocked_get()
        await client.get_alerts(page=0, size=10)
        params = client.get.call_args[1]["params"]
        assert "paged" not in params
        assert params["page"] == 0
        assert params["size"] == 10

    @pytest.mark.asyncio
    async def test_get_metering_element_definitions_omits_paged(self):
        client = _client_with_mocked_get()
        await client.get_metering_element_definitions(page=1, size=5)
        params = client.get.call_args[1]["params"]
        assert "paged" not in params
        assert params["page"] == 1
        assert params["size"] == 5


# ---------------------------------------------------------------------------
# `group` — three analytics reports that do not declare it
# ---------------------------------------------------------------------------


def _analytics_client() -> MagicMock:
    client = MagicMock()
    client._request_with_retry = AsyncMock(return_value=[])
    return client


def _groups_by_path(client) -> dict:
    out = {}
    for call in client._request_with_retry.call_args_list:
        out[call[0][1]] = call[1].get("params", {}).get("group")
    return out


class TestAnalyticsGroupParameter:
    @pytest.mark.asyncio
    async def test_summary_fetch_omits_group_on_undeclared_reports(self):
        from src.revenium_mcp_server.analytics.transaction_level_analytics_processor import (
            TransactionLevelAnalyticsProcessor,
        )

        client = _analytics_client()
        await TransactionLevelAnalyticsProcessor()._fetch_summary_data(
            client, "team-1", "SEVEN_DAYS", "MEAN"
        )
        groups = _groups_by_path(client)
        undeclared = [
            path
            for path in groups
            if "total-cost-by-provider-over-time" in path
            or "tokens-per-minute-by-provider" in path
        ]
        assert len(undeclared) == 2, groups
        for path in undeclared:
            assert groups[path] is None
        # The siblings that do declare `group` still receive it.
        assert any(value == "MEAN" for path, value in groups.items() if path not in undeclared)

    @pytest.mark.asyncio
    async def test_agent_fetch_omits_group_on_call_count(self):
        from src.revenium_mcp_server.analytics.transaction_level_analytics_processor import (
            TransactionLevelAnalyticsProcessor,
        )

        client = _analytics_client()
        await TransactionLevelAnalyticsProcessor()._fetch_agent_data(
            client, "team-1", "SEVEN_DAYS", "MAXIMUM"
        )
        groups = _groups_by_path(client)
        call_count = [p for p in groups if "call-count-metrics-by-agents" in p]
        assert call_count, groups
        assert groups[call_count[0]] is None

    @pytest.mark.asyncio
    async def test_summary_rejects_non_total_aggregation(self):
        from src.revenium_mcp_server.analytics.transaction_level_analytics_processor import (
            TransactionLevelAnalyticsProcessor,
        )

        processor = TransactionLevelAnalyticsProcessor()
        client = _analytics_client()
        with pytest.raises(ToolError) as exc:
            await processor.analyze_summary_metrics(client, "team-1", "SEVEN_DAYS", "MEAN")
        message = str(exc.value)
        assert "total cost by provider over time" in message
        assert "tokens per minute by provider" in message
        assert "MEAN" in message
        assert exc.value.field == "aggregation"
        client._request_with_retry.assert_not_called()

    @pytest.mark.asyncio
    async def test_agent_rejects_non_total_aggregation(self):
        from src.revenium_mcp_server.analytics.transaction_level_analytics_processor import (
            TransactionLevelAnalyticsProcessor,
        )

        processor = TransactionLevelAnalyticsProcessor()
        client = _analytics_client()
        with pytest.raises(ToolError) as exc:
            await processor.analyze_agent_transactions(client, "team-1", "SEVEN_DAYS", "MEAN")
        assert "call count by agent" in str(exc.value)
        client._request_with_retry.assert_not_called()

    @pytest.mark.asyncio
    async def test_total_aggregation_is_accepted(self):
        """The reports do produce totals, so TOTAL must not raise."""
        from src.revenium_mcp_server.analytics.transaction_level_analytics_processor import (
            TransactionLevelAnalyticsProcessor,
        )

        client = _analytics_client()
        await TransactionLevelAnalyticsProcessor()._fetch_agent_data(
            client, "team-1", "SEVEN_DAYS", "TOTAL"
        )
        assert all(value is None for value in _groups_by_path(client).values())


# ---------------------------------------------------------------------------
# Regression guard: completions and billing are untouched
# ---------------------------------------------------------------------------


class TestAlertDiscoveryMatchesTheAllowlist:
    """Greptile round-2 summary: the tool's own capability text advertised a
    severity filter that the allowlist rejects — the tool was directing
    callers into its own error."""

    def test_capabilities_do_not_advertise_severity_as_a_filter(self):
        import inspect
        from src.revenium_mcp_server.tools_decomposed import alert_management as m

        src = inspect.getsource(m)
        assert "filters={'severity'" not in src
        assert "dict (date ranges, severity)" not in src

    def test_capabilities_name_the_real_alert_filter_keys(self):
        import inspect
        from src.revenium_mcp_server.tools_decomposed import alert_management as m

        src = inspect.getsource(m)
        for key in ("anomaly_id", "owner_id", "resolved"):
            assert key in src


class TestNonPaginatedCallersRejectPageAndSize:
    """Tessie round-2 correctness: on a caller with no explicit page/size
    arguments, silently dropping those keys is a silent no-op, not a shadowed
    duplicate - they must be rejected like any unknown key."""

    def test_paginated_caller_still_drops_reserved_keys(self):
        from src.revenium_mcp_server.common.validation import apply_filter_allowlist

        out = apply_filter_allowlist(
            {"page": 3, "size": 10}, {"query": "query"}, action="list_x"
        )
        assert out == {}

    def test_non_paginated_caller_rejects_reserved_keys(self):
        from src.revenium_mcp_server.common.error_handling import ToolError
        from src.revenium_mcp_server.common.validation import apply_filter_allowlist

        with pytest.raises(ToolError) as exc:
            apply_filter_allowlist(
                {"page": 3}, {"environment": "environment"},
                action="get_conversion_funnel", paginated=False,
            )
        assert "page" in str(exc.value.message)


class TestInternalCallersSurviveTheGroupGuard:
    """Internal fixed-purpose callers must not trip the non-TOTAL rejection.

    Greptile round-1 P1: alert root-cause analysis called
    analyze_agent_transactions with a hardcoded MEAN, so every root-cause run
    with transaction analysis enabled would have produced an error instead of
    agent metrics.
    """

    def test_alert_root_cause_calls_agent_transactions_with_total(self):
        import inspect
        from src.revenium_mcp_server.analytics import alert_analytics_workflow_processor as m

        src = inspect.getsource(m)
        call = src.split("analyze_agent_transactions(")[1].split(")")[0]
        assert '"TOTAL"' in call
        assert '"MEAN"' not in call

    def test_agent_performance_fetches_total_not_mean(self):
        """Greptile round-3 P1: the performance path fetched cost/performance
        with MEAN while call counts came back TOTAL (its endpoint has no
        aggregation parameter), then divided mean cost by total calls. The
        processor sums buckets, so TOTAL is the only aggregation that yields
        well-defined sums across the whole report set."""
        import inspect
        from src.revenium_mcp_server.analytics import (
            transaction_level_analytics_processor as m,
        )

        src = inspect.getsource(m.TransactionLevelAnalyticsProcessor.analyze_agent_performance)
        assert '"TOTAL"' in src
        assert '"MEAN"' not in src

    @pytest.mark.asyncio
    async def test_analyze_agent_transactions_accepts_total(self):
        """The guard admits TOTAL — the value the internal caller now uses."""
        from src.revenium_mcp_server.analytics.transaction_level_analytics_processor import (
            _reject_unsupported_group,
        )

        _reject_unsupported_group(
            ["call_count_metrics_by_agents"], "TOTAL", "agent analytics"
        )  # must not raise


class TestExistingAllowlistsUnchanged:
    def test_completions_map_still_maps_snake_to_camel(self):
        from src.revenium_mcp_server.tools_decomposed.metering_management import (
            _COMPLETIONS_FILTER_PARAM_MAP,
            _extract_completions_filters,
        )

        assert _COMPLETIONS_FILTER_PARAM_MAP["start_date"] == "startDate"
        extracted = _extract_completions_filters(
            {"start_date": "2026-01-01", "unrelated": "x"}
        )
        assert extracted["startDate"] == "2026-01-01"
        assert "unrelated" not in extracted
        # BACK-2785 (merged alongside this branch) makes includeCodingAssistants
        # always present with an explicit boolean - tolerated here rather than
        # pinned, since that behaviour is owned by its own test module.
        extra = set(extracted) - {"startDate", "includeCodingAssistants"}
        assert not extra

    def test_billing_maps_still_drop_unknown_arguments(self):
        from src.revenium_mcp_server.tools_decomposed.business_analytics_management import (
            BusinessAnalyticsManagement,
        )

        mapped = BusinessAnalyticsManagement._map_billing_filters(
            {"invoice_number": "INV-1", "action": "list_invoices", "page": 0},
            BusinessAnalyticsManagement._INVOICE_FILTER_MAP,
        )
        assert mapped == {"invoiceNumber": "INV-1"}
