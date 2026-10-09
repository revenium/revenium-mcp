"""Empty analytics results and coding-assistant scope claims (BACK-2838).

Two failure modes are pinned here:

1. An empty analytics result used to open its cause list with "No activity
   occurred during the time period" - a fact about the world the endpoint
   cannot know. The rewritten message must name the dataset boundary instead.

2. The tool's own capability text claimed both that user costs come from
   coding-assistant traces and that the transaction count excludes
   coding-assistant transactions. Responses now carry a scope note chosen from
   the analytics plane that actually served the request.
"""

from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.revenium_mcp_server.analytics.formatters.agent_costs_formatter import (
    AgentCostsFormatter,
)
from src.revenium_mcp_server.analytics.formatters.api_key_costs_formatter import (
    ApiKeyCostsFormatter,
)
from src.revenium_mcp_server.analytics.formatters.base_formatter import (
    BaseFormattingUtilities,
)
from src.revenium_mcp_server.analytics.formatters.customer_costs_formatter import (
    CustomerCostsFormatter,
)
from src.revenium_mcp_server.analytics.formatters.model_costs_formatter import (
    ModelCostsFormatter,
)
from src.revenium_mcp_server.analytics.formatters.provider_costs_formatter import (
    ProviderCostsFormatter,
)
from src.revenium_mcp_server.analytics.formatters.user_costs_formatter import (
    UserCostsFormatter,
)
from src.revenium_mcp_server.analytics.simple_analytics_engine import SimpleAnalyticsEngine
from src.revenium_mcp_server.tools_decomposed.business_analytics_management import (
    _strip_user_costs_section,
)

# Wording that asserts something about the user rather than about the dataset.
INACTIVITY_CLAIMS = (
    "No activity occurred",
    "no activity occurred",
    "Check if there was any AI activity",
)

COUNT_ENVELOPE = {
    "_embedded": {
        "items": [
            {
                "groupName": "Transaction Count",
                "metrics": [
                    {"metricResult": 144, "metricType": "TRANSACTION_COUNT_BY_TEAM"}
                ],
            }
        ]
    }
}

PARAMS = {"period": "SEVEN_DAYS", "aggregation": "TOTAL"}

# (formatter, one populated row) for every cost action that reads the shared
# analytics cost universe.
COST_FORMATTERS = [
    (ProviderCostsFormatter, {"provider": "openai", "cost": 400.0}),
    (ModelCostsFormatter, {"model": "gpt-4", "cost": 300.0}),
    (CustomerCostsFormatter, {"customer": "Acme Corp", "cost": 250.0}),
    (ApiKeyCostsFormatter, {"api_key": "sk-abcd1234", "cost": 120.0}),
    (AgentCostsFormatter, {"agent": "support-bot", "cost": 90.0}),
    (UserCostsFormatter, {"user_email": "engineer@example.com", "cost": 42.0, "requests": 10}),
]


def _engine_with_response(response):
    client = MagicMock()
    client.team_id = "team-1"
    client.get = AsyncMock(return_value=response)
    return SimpleAnalyticsEngine(client), client


class TestNoDataWording:
    """The empty-result template describes the dataset, not the user."""

    @pytest.fixture
    def response(self):
        return BaseFormattingUtilities.format_no_data_response(
            "provider costs", "SEVEN_DAYS", "aggregation: TOTAL"
        )

    def test_does_not_assert_inactivity_as_fact(self, response):
        for claim in INACTIVITY_CLAIMS:
            assert claim not in response

    def test_names_the_unpopulated_dimension_cause(self, response):
        assert "dimension you asked for is not populated" in response

    def test_names_the_other_data_plane_cause(self, response):
        assert "data plane this endpoint does not cover" in response

    def test_keeps_the_existing_structure(self, response):
        assert "## **No Data Available**" in response
        assert "**Time Period**: SEVEN_DAYS" in response
        assert "**Additional Info**: aggregation: TOTAL" in response
        assert "**Analysis Date**" in response
        assert "**Suggestions:**" in response
        assert "**For Help:**" in response

    def test_scope_note_is_appended_when_given(self):
        response = BaseFormattingUtilities.format_no_data_response(
            "user costs", "SEVEN_DAYS", "aggregation: TOTAL", scope_note="SCOPE MARKER\n"
        )
        assert "SCOPE MARKER" in response

    def test_scope_section_absent_by_default(self, response):
        assert "SCOPE MARKER" not in response


class TestScopeNoteFollowsThePlane:
    """The note is chosen from the path the registry resolves, not hardcoded."""

    def test_new_analytics_plane_states_the_cost_source_rule(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_USE_NEW_ANALYTICS_API", "true")
        monkeypatch.setenv("REVENIUM_APP_BASE_URL", "https://app.example.test")
        note = BaseFormattingUtilities.coding_assistant_scope_note(
            "cost_metric_by_provider_over_time"
        )
        assert "is reported only under the `coding_assistant` cost source" in note
        assert "revenium_metered" in note
        assert "get_transaction_count" in note

    def test_legacy_plane_states_the_tenant_policy_rule(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_USE_NEW_ANALYTICS_API", "false")
        note = BaseFormattingUtilities.coding_assistant_scope_note(
            "cost_metric_by_provider_over_time"
        )
        assert "legacy analytics endpoints" in note
        assert "coding-assistant filter policy" in note

    def test_unresolvable_endpoint_still_returns_a_note(self):
        note = BaseFormattingUtilities.coding_assistant_scope_note("not_a_registry_key")
        assert "Coding-assistant scope" in note


class TestCostResponsesCarryTheScopeNote:
    """Every cost action states its coding-assistant scope, empty or not."""

    @pytest.mark.parametrize("formatter_cls,row", COST_FORMATTERS)
    def test_populated_response_carries_note(self, formatter_cls, row):
        result = formatter_cls().format([row], PARAMS)
        assert "**Coding-assistant scope**" in result

    @pytest.mark.parametrize("formatter_cls,row", COST_FORMATTERS)
    def test_empty_response_carries_note(self, formatter_cls, row):
        result = formatter_cls().format([], PARAMS)
        assert "**Coding-assistant scope**" in result

    @pytest.mark.parametrize("formatter_cls,row", COST_FORMATTERS)
    def test_empty_response_never_claims_inactivity(self, formatter_cls, row):
        result = formatter_cls().format([], PARAMS)
        for claim in INACTIVITY_CLAIMS:
            assert claim not in result


class TestUserCostsAttributionNote:
    """A per-user total must not be read as a person's coding-assistant usage."""

    @pytest.fixture
    def formatter(self):
        return UserCostsFormatter()

    def test_empty_response_redirects_in_one_step(self, formatter):
        result = formatter.format([], PARAMS)
        assert "**Per-user attribution**" in result
        assert "AI by Employee" in result
        assert "revenium_metered" in result

    def test_populated_response_carries_the_same_caveat(self, formatter):
        result = formatter.format(
            [{"user_email": "engineer@example.com", "cost": 0.10, "requests": 3}], PARAMS
        )
        assert "**Per-user attribution**" in result
        assert "AI by Employee" in result


class TestTransactionCountScope:
    """The count response no longer claims coding assistants are excluded wholesale."""

    @pytest.mark.asyncio
    async def test_populated_count_carries_scope_note(self):
        engine, _ = _engine_with_response(deepcopy(COUNT_ENVELOPE))
        result = await engine.get_transaction_count(period="SEVEN_DAYS")
        assert "144" in result
        assert "**Coding-assistant scope**" in result
        assert "coding-assistant transactions excluded" not in result

    @pytest.mark.asyncio
    async def test_no_data_count_states_the_dataset_boundary(self):
        engine, _ = _engine_with_response({})
        result = await engine.get_transaction_count(period="SEVEN_DAYS")
        assert "No Data Available" in result
        assert "**Coding-assistant scope**" in result
        for claim in INACTIVITY_CLAIMS:
            assert claim not in result


class TestCapabilityTextIsConsistent:
    """The two capability claims that contradicted each other are reconciled."""

    @pytest.mark.asyncio
    async def test_capabilities_no_longer_claim_blanket_exclusion(self):
        tool = _analytics_tool()
        text = (await tool._handle_get_capabilities())[0].text
        assert "coding-assistant transactions excluded" not in text
        assert "Data from coding assistant traces" not in text

    @pytest.mark.asyncio
    async def test_capabilities_name_the_per_employee_boundary(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_USE_NEW_ANALYTICS_API", "true")
        tool = _analytics_tool()
        text = (await tool._handle_get_capabilities())[0].text
        assert "authoritative per-employee coding-assistant report" in text
        assert "returns no rows" not in text

    def test_stripping_user_costs_section_survives_rewording(self):
        capabilities = (
            "5. **get_agent_costs**\n   - x\n\n"
            "6. **get_user_costs**\n   - reworded line\n\n"
            "6a. **get_transaction_count**\n   - y\n"
        )
        stripped = _strip_user_costs_section(capabilities)
        assert "get_user_costs" not in stripped
        assert "get_transaction_count" in stripped
        assert "get_agent_costs" in stripped

    def test_stripping_is_a_no_op_when_markers_are_absent(self):
        capabilities = "no sections here"
        assert _strip_user_costs_section(capabilities) == capabilities


def _analytics_tool():
    from src.revenium_mcp_server.tools_decomposed.business_analytics_management import (
        BusinessAnalyticsManagement,
    )

    return BusinessAnalyticsManagement()


class TestCostSummaryCarriesTheScopeNote:
    """The aggregate summary reads the same universe as its five constituents."""

    def _summary_data(self):
        return {
            "total_cost": 700.0,
            "top_providers": [{"provider": "openai", "cost": 400.0}],
            "top_models": [{"model": "gpt-4", "cost": 300.0}],
            "top_customers": [],
            "top_api_keys": [],
            "top_agents": [],
        }

    def test_summary_response_carries_note(self):
        from src.revenium_mcp_server.analytics.formatters.cost_summary_formatter import (
            CostSummaryFormatter,
        )

        result = CostSummaryFormatter().format(self._summary_data(), PARAMS)
        assert "**Coding-assistant scope**" in result

    def test_summary_note_follows_the_plane(self, monkeypatch):
        from src.revenium_mcp_server.analytics.formatters.cost_summary_formatter import (
            CostSummaryFormatter,
        )

        monkeypatch.setenv("REVENIUM_USE_NEW_ANALYTICS_API", "true")
        result = CostSummaryFormatter().format(self._summary_data(), PARAMS)
        assert "is reported only under the `coding_assistant` cost source" in result
