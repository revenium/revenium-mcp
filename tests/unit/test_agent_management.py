"""Unit tests for Agent Management tools.

Tests the AgentManager and AgentManagement classes from the decomposed tools
module. Covers CRUD (list, get, create, update, delete), discovery
(list_discovered), and the introspection actions.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.revenium_mcp_server.tools_decomposed.agent_management import (
    AgentManager,
    AgentManagement,
    SquadManager,
    INLINE_LIST_CAP,
)
from src.revenium_mcp_server.client import ReveniumAPIError
from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError
from mcp.types import TextContent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_client():
    """Create a mock ReveniumClient for AgentManager."""
    client = MagicMock()
    client.team_id = "test_team_id_456"
    client.get_agents = AsyncMock()
    client.get_agent_by_id = AsyncMock()
    client.create_agent = AsyncMock()
    client.update_agent = AsyncMock()
    client.delete_agent = AsyncMock()
    client.get_discovered_agents = AsyncMock()
    client.get_squads = AsyncMock()
    client.get_squad_executions = AsyncMock()
    client.get_squad_entity_executions = AsyncMock()
    client.get_squad_detail = AsyncMock()
    client.get_squad_timeline = AsyncMock()
    client._extract_embedded_data = MagicMock()
    client._extract_pagination_info = MagicMock()
    return client


@pytest.fixture
def agent_manager(mock_client):
    """Create AgentManager with mocked client."""
    return AgentManager(mock_client)


@pytest.fixture
def squad_manager(mock_client):
    """Create SquadManager with mocked client."""
    return SquadManager(mock_client)


@pytest.fixture
def agent_mgmt():
    """Create AgentManagement instance (top-level tool)."""
    return AgentManagement()


# ===========================================================================
# AgentManager CRUD Tests
# ===========================================================================


class TestAgentManagerList:
    """Test AgentManager.list_agents behavior."""

    @pytest.mark.asyncio
    async def test_list_agents_returns_paginated_result(self, agent_manager, mock_client):
        mock_client._extract_embedded_data.return_value = [
            {"id": "agt_1", "label": "copilot"},
            {"id": "agt_2", "label": "support-bot"},
        ]
        mock_client._extract_pagination_info.return_value = {"totalPages": 1, "totalElements": 2}
        mock_client.get_agents.return_value = {"_embedded": {}}

        result = await agent_manager.list_agents({"page": 0, "size": 20})

        assert result["total_found"] == 2
        assert result["pagination"]["totalElements"] == 2
        mock_client.get_agents.assert_called_once_with(page=0, size=20)

    @pytest.mark.asyncio
    async def test_list_agents_forwards_query_search_filter(self, agent_manager, mock_client):
        """Server-side query search reaches the API call."""
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {"totalPages": 0, "totalElements": 0}
        mock_client.get_agents.return_value = {}

        await agent_manager.list_agents({"filters": {"query": "copilot"}})

        mock_client.get_agents.assert_called_once_with(page=0, size=20, query="copilot")

    @pytest.mark.asyncio
    async def test_list_agents_strips_reserved_filter_keys(self, agent_manager, mock_client):
        """page/size inside filters must not collide with keyword args."""
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {"totalPages": 0, "totalElements": 0}
        mock_client.get_agents.return_value = {}

        await agent_manager.list_agents({"filters": {"page": 3, "size": 5, "query": "x"}})

        mock_client.get_agents.assert_called_once_with(page=0, size=20, query="x")


class TestAgentManagerGet:
    """Test AgentManager.get_agent behavior."""

    @pytest.mark.asyncio
    async def test_get_agent_returns_data(self, agent_manager, mock_client):
        mock_client.get_agent_by_id.return_value = {"id": "agt_1", "label": "copilot"}
        result = await agent_manager.get_agent({"agent_id": "agt_1"})
        assert result["id"] == "agt_1"

    @pytest.mark.asyncio
    async def test_get_agent_missing_id_raises(self, agent_manager):
        with pytest.raises(ToolError):
            await agent_manager.get_agent({})

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [400, 403, 404])
    async def test_get_agent_not_found_is_structured(self, agent_manager, mock_client, status):
        """Upstream 400/403/404 for missing IDs folds into RESOURCE_NOT_FOUND.

        Live dev evidence: unknown ids return 400, deleted ids return 403.
        GET-by-id has no other input than the id, so all three can only mean
        the id does not resolve to an accessible agent.
        """
        mock_client.get_agent_by_id.side_effect = ReveniumAPIError(
            "boom", status_code=status
        )
        with pytest.raises(ToolError) as exc_info:
            await agent_manager.get_agent({"agent_id": "agt_missing"})
        assert exc_info.value.error_code == ErrorCodes.RESOURCE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_get_agent_500_propagates_as_api_error(self, agent_manager, mock_client):
        """A 500 is a server failure, not evidence the agent is missing —
        it must propagate so retry/error handling can see it."""
        mock_client.get_agent_by_id.side_effect = ReveniumAPIError(
            "server down", status_code=500
        )
        with pytest.raises(ReveniumAPIError):
            await agent_manager.get_agent({"agent_id": "agt_1"})


class TestAgentManagerCreate:
    """Test AgentManager.create_agent behavior."""

    @pytest.mark.asyncio
    async def test_create_agent_missing_data_raises(self, agent_manager):
        with pytest.raises(ToolError):
            await agent_manager.create_agent({})

    @pytest.mark.asyncio
    async def test_create_agent_missing_telemetry_key_raises(self, agent_manager):
        """telemetryKey is the write-side required field on the API."""
        with pytest.raises(ToolError):
            await agent_manager.create_agent({"agent_data": {"displayName": "My Agent"}})

    @pytest.mark.asyncio
    async def test_create_agent_injects_team_id(self, agent_manager, mock_client):
        mock_client.create_agent.return_value = {"id": "agt_new"}
        await agent_manager.create_agent(
            {"agent_data": {"telemetryKey": "my-agent"}}
        )
        sent = mock_client.create_agent.call_args[0][0]
        assert sent["teamId"] == "test_team_id_456"
        assert sent["telemetryKey"] == "my-agent"

    @pytest.mark.asyncio
    async def test_create_agent_preserves_explicit_team_id(self, agent_manager, mock_client):
        mock_client.create_agent.return_value = {"id": "agt_new"}
        await agent_manager.create_agent(
            {"agent_data": {"telemetryKey": "my-agent", "teamId": "other_team"}}
        )
        sent = mock_client.create_agent.call_args[0][0]
        assert sent["teamId"] == "other_team"


class TestAgentManagerUpdate:
    """Test AgentManager.update_agent behavior."""

    @pytest.mark.asyncio
    async def test_update_agent_missing_id_raises(self, agent_manager):
        with pytest.raises(ToolError):
            await agent_manager.update_agent({"agent_data": {"displayName": "x"}})

    @pytest.mark.asyncio
    async def test_update_agent_missing_data_raises(self, agent_manager):
        with pytest.raises(ToolError):
            await agent_manager.update_agent({"agent_id": "agt_1"})

    @pytest.mark.asyncio
    async def test_update_merges_full_write_view_from_current(
        self, agent_manager, mock_client
    ):
        """PUT is full-replacement on the write view; a partial update merges
        every writable field from the current resource so omitted fields
        (telemetryKey, ownerId) are never cleared."""
        mock_client.get_agent_by_id.return_value = {
            "id": "agt_1",
            "telemetryKey": "existing-key",
            "displayName": "Old Name",
            "ownerId": "usr_7",
            "teamId": "team_x",
            "created": "2026-01-01T00:00:00Z",
        }
        mock_client.update_agent.return_value = {"id": "agt_1"}

        await agent_manager.update_agent(
            {"agent_id": "agt_1", "agent_data": {"displayName": "Renamed"}}
        )

        sent = mock_client.update_agent.call_args[0][1]
        assert sent["telemetryKey"] == "existing-key"
        assert sent["displayName"] == "Renamed"
        assert sent["ownerId"] == "usr_7"
        assert sent["teamId"] == "team_x"
        assert "created" not in sent

    @pytest.mark.asyncio
    async def test_update_explicit_fields_override_current(
        self, agent_manager, mock_client
    ):
        """Caller-supplied fields win over the current resource's values."""
        mock_client.get_agent_by_id.return_value = {
            "id": "agt_1",
            "telemetryKey": "old-key",
            "ownerId": "usr_7",
        }
        mock_client.update_agent.return_value = {"id": "agt_1"}

        await agent_manager.update_agent(
            {"agent_id": "agt_1", "agent_data": {"telemetryKey": "new-key"}}
        )

        sent = mock_client.update_agent.call_args[0][1]
        assert sent["telemetryKey"] == "new-key"
        assert sent["ownerId"] == "usr_7"


class TestAgentManagerDelete:
    """Test AgentManager.delete_agent behavior."""

    @pytest.mark.asyncio
    async def test_delete_agent_missing_id_raises(self, agent_manager):
        with pytest.raises(ToolError):
            await agent_manager.delete_agent({})

    @pytest.mark.asyncio
    async def test_delete_agent_calls_client(self, agent_manager, mock_client):
        mock_client.delete_agent.return_value = {}
        await agent_manager.delete_agent({"agent_id": "agt_9"})
        mock_client.delete_agent.assert_called_once_with("agt_9")


class TestAgentManagerDiscovered:
    """Test AgentManager.list_discovered behavior."""

    @pytest.mark.asyncio
    async def test_list_discovered_defaults_period(self, agent_manager, mock_client):
        """period is required by the API; the manager defaults it."""
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {"totalPages": 0, "totalElements": 0}
        mock_client.get_discovered_agents.return_value = {}

        await agent_manager.list_discovered({})

        mock_client.get_discovered_agents.assert_called_once_with(
            period="THIRTY_DAYS", page=0, size=20
        )

    @pytest.mark.asyncio
    async def test_list_discovered_forwards_period(self, agent_manager, mock_client):
        mock_client._extract_embedded_data.return_value = [
            {"telemetryKey": "cli-agent", "registered": False, "agentId": None}
        ]
        mock_client._extract_pagination_info.return_value = {"totalPages": 1, "totalElements": 1}
        mock_client.get_discovered_agents.return_value = {"_embedded": {}}

        result = await agent_manager.list_discovered({"period": "SEVEN_DAYS"})

        mock_client.get_discovered_agents.assert_called_once_with(
            period="SEVEN_DAYS", page=0, size=20
        )
        assert result["total_found"] == 1
        assert result["discovered_agents"][0]["telemetryKey"] == "cli-agent"


# ===========================================================================
# AgentManagement (top-level tool) Tests
# ===========================================================================


class TestAgentManagementMetadata:
    """Tool-level attributes and introspection."""

    def test_tool_name(self, agent_mgmt):
        assert agent_mgmt.tool_name == "manage_agents"

    @pytest.mark.asyncio
    async def test_supported_actions_include_crud_and_discovery(self, agent_mgmt):
        actions = await agent_mgmt._get_supported_actions()
        for expected in (
            "list",
            "get",
            "create",
            "update",
            "delete",
            "list_discovered",
            "get_capabilities",
            "get_examples",
        ):
            assert expected in actions

    @pytest.mark.asyncio
    async def test_input_schema_documents_telemetry_key(self, agent_mgmt):
        schema = await agent_mgmt._get_input_schema()
        agent_data = schema["properties"]["agent_data"]
        assert "telemetryKey" in agent_data["properties"]


class TestAgentManagementActions:
    """handle_action dispatch."""

    @pytest.mark.asyncio
    async def test_get_capabilities_returns_text(self, agent_mgmt):
        result = await agent_mgmt.handle_action("get_capabilities", {})
        assert isinstance(result[0], TextContent)
        assert "list_discovered" in result[0].text

    @pytest.mark.asyncio
    async def test_get_examples_returns_examples(self, agent_mgmt):
        result = await agent_mgmt.handle_action("get_examples", {})
        assert "telemetryKey" in result[0].text

    @pytest.mark.asyncio
    async def test_unknown_action_lists_supported(self, agent_mgmt):
        result = await agent_mgmt.handle_action("bogus_action", {})
        assert "Unknown action" in result[0].text
        assert "list_discovered" in result[0].text

    @pytest.mark.asyncio
    async def test_list_action_formats_result(self, agent_mgmt, mock_client):
        mock_client._extract_embedded_data.return_value = [{"id": "agt_1"}]
        mock_client._extract_pagination_info.return_value = {"totalPages": 1, "totalElements": 1}
        mock_client.get_agents.return_value = {}
        agent_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await agent_mgmt.handle_action("list", {"page": 0, "size": 20})

        assert "Found 1 agents" in result[0].text

    @pytest.mark.asyncio
    async def test_tool_error_propagates(self, agent_mgmt, mock_client):
        """A ToolError from the manager must propagate out of handle_action so
        FastMCP marks the envelope isError:true, not be rendered as content text."""
        agent_mgmt.get_client = AsyncMock(return_value=mock_client)
        with pytest.raises(ToolError):
            await agent_mgmt.handle_action("get", {})

    @pytest.mark.asyncio
    async def test_auth_failure_reraises_api_error(self, agent_mgmt, mock_client):
        """An auth failure from the client must propagate out of handle_action so
        FastMCP marks the envelope isError:true, not swallow it into content text."""
        mock_client.get_agents.side_effect = ReveniumAPIError(
            "Unauthorized", status_code=401
        )
        agent_mgmt.get_client = AsyncMock(return_value=mock_client)
        with pytest.raises(ReveniumAPIError) as exc:
            await agent_mgmt.handle_action("list", {"page": 0, "size": 20})
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_auth_failure_reraises_tool_error(self, agent_mgmt, mock_client):
        """A ToolError raised while handling an action must propagate, not be
        rendered as ``Tool error: ...`` content text without isError:true."""
        boom = ToolError(message="unauthorized", error_code=ErrorCodes.API_AUTHORIZATION)
        mock_client.get_agents.side_effect = boom
        agent_mgmt.get_client = AsyncMock(return_value=mock_client)
        with pytest.raises(ToolError) as exc:
            await agent_mgmt.handle_action("list", {"page": 0, "size": 20})
        assert exc.value is boom


# ===========================================================================
# SquadManager (observability) Tests
# ===========================================================================


class TestSquadManagerListSquads:
    """Test SquadManager.list_squads behavior."""

    @pytest.mark.asyncio
    async def test_list_squads_returns_paginated_result(self, squad_manager, mock_client):
        mock_client._extract_embedded_data.return_value = [
            {
                "id": "sq_1",
                "label": "checkout-squad",
                "executionCount": 12,
                "agentCount": 3,
                "totalCost": 4.5,
            },
        ]
        mock_client._extract_pagination_info.return_value = {"totalPages": 1, "totalElements": 1}
        mock_client.get_squads.return_value = {"_embedded": {}}

        result = await squad_manager.list_squads({"page": 0, "size": 20})

        assert result["total_found"] == 1
        assert result["pagination"]["totalElements"] == 1
        mock_client.get_squads.assert_called_once_with(page=0, size=20)

    @pytest.mark.asyncio
    async def test_list_squads_empty_state(self, squad_manager, mock_client):
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {"totalPages": 0, "totalElements": 0}
        mock_client.get_squads.return_value = {}

        result = await squad_manager.list_squads({})

        assert result["total_found"] == 0
        assert result["rendered"] == []

    @pytest.mark.asyncio
    async def test_list_squads_forwards_period_filter(self, squad_manager, mock_client):
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {}
        mock_client.get_squads.return_value = {}

        await squad_manager.list_squads({"period": "SEVEN_DAYS"})

        mock_client.get_squads.assert_called_once_with(page=0, size=20, period="SEVEN_DAYS")

    @pytest.mark.asyncio
    async def test_list_squads_cost_none_is_honest(self, squad_manager, mock_client):
        """totalCost is nullable — a None must render 'cost unavailable',
        never 0 or the None literal."""
        mock_client._extract_embedded_data.return_value = [
            {"id": "sq_1", "label": "no-cost-squad", "executionCount": 1,
             "agentCount": 2, "totalCost": None},
        ]
        mock_client._extract_pagination_info.return_value = {}
        mock_client.get_squads.return_value = {}

        result = await squad_manager.list_squads({})

        line = result["rendered"][0]
        assert "cost unavailable" in line
        assert "None" not in line
        assert "$0" not in line

    @pytest.mark.asyncio
    async def test_list_squads_cost_present_renders_value(self, squad_manager, mock_client):
        mock_client._extract_embedded_data.return_value = [
            {"id": "sq_1", "label": "paid-squad", "executionCount": 1,
             "agentCount": 2, "totalCost": 4.5},
        ]
        mock_client._extract_pagination_info.return_value = {}
        mock_client.get_squads.return_value = {}

        result = await squad_manager.list_squads({})

        assert "4.5" in result["rendered"][0]


class TestSquadManagerListExecutions:
    """Test SquadManager.list_squad_executions routing and filters."""

    @pytest.mark.asyncio
    async def test_global_executions_uses_global_endpoint(self, squad_manager, mock_client):
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {}
        mock_client.get_squad_executions.return_value = {}

        await squad_manager.list_squad_executions({})

        mock_client.get_squad_executions.assert_called_once_with(page=0, size=20)
        mock_client.get_squad_entity_executions.assert_not_called()

    @pytest.mark.asyncio
    async def test_with_squad_id_uses_per_squad_endpoint(self, squad_manager, mock_client):
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {}
        mock_client.get_squad_entity_executions.return_value = {}

        await squad_manager.list_squad_executions({"squad_id": "sq_9"})

        mock_client.get_squad_entity_executions.assert_called_once_with("sq_9", page=0, size=20)
        mock_client.get_squad_executions.assert_not_called()

    @pytest.mark.asyncio
    async def test_global_forwards_name_status_period(self, squad_manager, mock_client):
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {}
        mock_client.get_squad_executions.return_value = {}

        await squad_manager.list_squad_executions(
            {"squad_name": "checkout", "status": "COMPLETED", "period": "THIRTY_DAYS"}
        )

        mock_client.get_squad_executions.assert_called_once_with(
            page=0, size=20, squadName="checkout", status="COMPLETED", period="THIRTY_DAYS"
        )

    @pytest.mark.asyncio
    async def test_per_squad_forwards_period_not_name(self, squad_manager, mock_client):
        """The per-squad endpoint is already scoped, so squadName is not sent;
        period still forwards."""
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {}
        mock_client.get_squad_entity_executions.return_value = {}

        await squad_manager.list_squad_executions(
            {"squad_id": "sq_9", "period": "SEVEN_DAYS", "squad_name": "ignored"}
        )

        mock_client.get_squad_entity_executions.assert_called_once_with(
            "sq_9", page=0, size=20, period="SEVEN_DAYS"
        )

    @pytest.mark.asyncio
    async def test_executions_empty_state(self, squad_manager, mock_client):
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {}
        mock_client.get_squad_executions.return_value = {}

        result = await squad_manager.list_squad_executions({})

        assert result["total_found"] == 0
        assert result["rendered"] == []

    @pytest.mark.asyncio
    async def test_executions_cost_none_is_honest(self, squad_manager, mock_client):
        mock_client._extract_embedded_data.return_value = [
            {"id": "ex_1", "squadName": "checkout", "startTime": "2026-07-01T00:00:00Z",
             "duration": 1200, "agentCount": 2, "totalCost": None, "status": "COMPLETED"},
        ]
        mock_client._extract_pagination_info.return_value = {}
        mock_client.get_squad_executions.return_value = {}

        result = await squad_manager.list_squad_executions({})

        line = result["rendered"][0]
        assert "cost unavailable" in line
        assert "None" not in line


class TestSquadManagerGetSquad:
    """Test SquadManager.get_squad detail rendering + not-found translation."""

    @pytest.mark.asyncio
    async def test_get_squad_missing_id_raises(self, squad_manager):
        with pytest.raises(ToolError):
            await squad_manager.get_squad({})

    @pytest.mark.asyncio
    async def test_get_squad_returns_detail(self, squad_manager, mock_client):
        mock_client.get_squad_detail.return_value = {
            "id": "sq_1",
            "label": "checkout-squad",
            "agentCount": 3,
            "traceCount": 10,
            "totalCost": 4.5,
            "status": "COMPLETED",
            "agents": [{"id": "a1"}, {"id": "a2"}],
        }
        result = await squad_manager.get_squad({"squad_id": "sq_1"})
        assert result["squad"]["id"] == "sq_1"
        mock_client.get_squad_detail.assert_called_once_with("sq_1")

    @pytest.mark.asyncio
    async def test_get_squad_forwards_period(self, squad_manager, mock_client):
        mock_client.get_squad_detail.return_value = {"id": "sq_1", "agents": []}
        await squad_manager.get_squad({"squad_id": "sq_1", "period": "SEVEN_DAYS"})
        mock_client.get_squad_detail.assert_called_once_with("sq_1", period="SEVEN_DAYS")

    @pytest.mark.asyncio
    async def test_get_squad_cost_none_is_honest(self, squad_manager, mock_client):
        mock_client.get_squad_detail.return_value = {
            "id": "sq_1", "label": "x", "totalCost": None, "agents": [],
        }
        result = await squad_manager.get_squad({"squad_id": "sq_1"})
        assert "cost unavailable" in result["rendered"]
        assert "None" not in result["rendered"]

    @pytest.mark.asyncio
    async def test_get_squad_caps_agents_rendering(self, squad_manager, mock_client):
        """A long agents[] list must be bounded in the rendered summary."""
        mock_client.get_squad_detail.return_value = {
            "id": "sq_1", "label": "big",
            "agents": [{"id": f"a{i}", "label": f"agent-{i}"} for i in range(60)],
        }
        result = await squad_manager.get_squad({"squad_id": "sq_1"})
        assert len(result["rendered_agents"]) <= INLINE_LIST_CAP
        assert "more" in result["rendered"].lower()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [400, 403, 404])
    async def test_get_squad_not_found_is_structured(self, squad_manager, mock_client, status):
        mock_client.get_squad_detail.side_effect = ReveniumAPIError("boom", status_code=status)
        with pytest.raises(ToolError) as exc_info:
            await squad_manager.get_squad({"squad_id": "sq_missing"})
        assert exc_info.value.error_code == ErrorCodes.RESOURCE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_get_squad_500_propagates(self, squad_manager, mock_client):
        mock_client.get_squad_detail.side_effect = ReveniumAPIError("down", status_code=500)
        with pytest.raises(ReveniumAPIError):
            await squad_manager.get_squad({"squad_id": "sq_1"})


class TestSquadManagerTimeline:
    """Test SquadManager.get_squad_timeline rendering + event cap."""

    @pytest.mark.asyncio
    async def test_timeline_missing_id_raises(self, squad_manager):
        with pytest.raises(ToolError):
            await squad_manager.get_squad_timeline({})

    @pytest.mark.asyncio
    async def test_timeline_returns_header_and_events(self, squad_manager, mock_client):
        mock_client.get_squad_timeline.return_value = {
            "squadId": "sq_1",
            "squadName": "checkout",
            "startTime": "2026-07-01T00:00:00Z",
            "endTime": "2026-07-01T00:05:00Z",
            "totalDuration": 300,
            "events": [{"id": "e1", "agent": "a", "role": "planner",
                        "timestamp": "2026-07-01T00:00:01Z"}],
        }
        result = await squad_manager.get_squad_timeline({"squad_id": "sq_1"})
        assert result["timeline"]["squadName"] == "checkout"
        assert len(result["rendered_events"]) == 1
        mock_client.get_squad_timeline.assert_called_once_with("sq_1")

    @pytest.mark.asyncio
    async def test_timeline_forwards_period(self, squad_manager, mock_client):
        mock_client.get_squad_timeline.return_value = {"squadId": "sq_1", "events": []}
        await squad_manager.get_squad_timeline({"squad_id": "sq_1", "period": "SEVEN_DAYS"})
        mock_client.get_squad_timeline.assert_called_once_with("sq_1", period="SEVEN_DAYS")

    @pytest.mark.asyncio
    async def test_timeline_empty_events(self, squad_manager, mock_client):
        mock_client.get_squad_timeline.return_value = {"squadId": "sq_1", "events": []}
        result = await squad_manager.get_squad_timeline({"squad_id": "sq_1"})
        assert result["rendered_events"] == []
        assert result["event_count"] == 0

    @pytest.mark.asyncio
    async def test_timeline_caps_events(self, squad_manager, mock_client):
        """A 60-event timeline renders the first 50 and a '... 10 more events'
        overflow line (INLINE_LIST_CAP = 50)."""
        mock_client.get_squad_timeline.return_value = {
            "squadId": "sq_1",
            "squadName": "big",
            "events": [{"id": f"e{i}", "agent": "a", "role": "r",
                        "timestamp": f"2026-07-01T00:00:{i:02d}Z"} for i in range(60)],
        }
        result = await squad_manager.get_squad_timeline({"squad_id": "sq_1"})
        assert len(result["rendered_events"]) == INLINE_LIST_CAP
        assert result["event_count"] == 60
        overflow = result["events_overflow"]
        assert "10 more events" in overflow

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [400, 403, 404])
    async def test_timeline_not_found_is_structured(self, squad_manager, mock_client, status):
        mock_client.get_squad_timeline.side_effect = ReveniumAPIError("boom", status_code=status)
        with pytest.raises(ToolError) as exc_info:
            await squad_manager.get_squad_timeline({"squad_id": "sq_missing"})
        assert exc_info.value.error_code == ErrorCodes.RESOURCE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_timeline_500_propagates(self, squad_manager, mock_client):
        mock_client.get_squad_timeline.side_effect = ReveniumAPIError("down", status_code=500)
        with pytest.raises(ReveniumAPIError):
            await squad_manager.get_squad_timeline({"squad_id": "sq_1"})


# ===========================================================================
# SquadManagement action dispatch + capabilities Tests
# ===========================================================================


class TestSquadActionRouting:
    """handle_action routes the four squad actions to SquadManager."""

    @pytest.mark.asyncio
    async def test_list_squads_action(self, agent_mgmt, mock_client):
        mock_client._extract_embedded_data.return_value = [
            {"id": "sq_1", "label": "checkout", "executionCount": 2,
             "agentCount": 3, "totalCost": 1.0},
        ]
        mock_client._extract_pagination_info.return_value = {"totalElements": 1}
        mock_client.get_squads.return_value = {}
        agent_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await agent_mgmt.handle_action("list_squads", {"page": 0, "size": 20})

        assert "squad" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_list_squad_executions_action(self, agent_mgmt, mock_client):
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {}
        mock_client.get_squad_executions.return_value = {}
        agent_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await agent_mgmt.handle_action("list_squad_executions", {})

        assert isinstance(result[0], TextContent)

    @pytest.mark.asyncio
    async def test_get_squad_action(self, agent_mgmt, mock_client):
        mock_client.get_squad_detail.return_value = {"id": "sq_1", "label": "x", "agents": []}
        agent_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await agent_mgmt.handle_action("get_squad", {"squad_id": "sq_1"})

        assert "sq_1" in result[0].text

    @pytest.mark.asyncio
    async def test_get_squad_timeline_action(self, agent_mgmt, mock_client):
        mock_client.get_squad_timeline.return_value = {"squadId": "sq_1", "events": []}
        agent_mgmt.get_client = AsyncMock(return_value=mock_client)

        result = await agent_mgmt.handle_action("get_squad_timeline", {"squad_id": "sq_1"})

        assert isinstance(result[0], TextContent)

    @pytest.mark.asyncio
    async def test_squad_actions_in_supported_actions(self, agent_mgmt):
        actions = await agent_mgmt._get_supported_actions()
        for expected in ("list_squads", "list_squad_executions", "get_squad", "get_squad_timeline"):
            assert expected in actions

    @pytest.mark.asyncio
    async def test_input_schema_documents_squad_params(self, agent_mgmt):
        schema = await agent_mgmt._get_input_schema()
        props = schema["properties"]
        for param in ("squad_id", "squad_name", "status", "period"):
            assert param in props


class TestSquadCapabilities:
    """The Squad Observability capability advertises all four actions."""

    @pytest.mark.asyncio
    async def test_squad_capability_covers_all_actions(self, agent_mgmt):
        caps = await agent_mgmt._get_tool_capabilities()
        squad_caps = [c for c in caps if "squad" in c.name.lower()]
        assert squad_caps, "expected a Squad Observability capability"
        advertised = set()
        for cap in squad_caps:
            advertised.update(cap.parameters.keys())
        for action in ("list_squads", "list_squad_executions", "get_squad", "get_squad_timeline"):
            assert action in advertised

    @pytest.mark.asyncio
    async def test_get_examples_includes_squad_actions(self, agent_mgmt):
        result = await agent_mgmt.handle_action("get_examples", {})
        text = result[0].text
        assert "list_squads" in text
        assert "get_squad_timeline" in text


class TestSquadRenderingHardening:
    """Review hardening: caps apply to the raw payload too; clean scalars."""

    def test_format_cost_float_representation_clean(self):
        from src.revenium_mcp_server.tools_decomposed.agent_management import _format_cost

        assert _format_cost(4.100000000000001) == "$4.1"
        assert _format_cost(0.25) == "$0.25"
        assert _format_cost(None) == "cost unavailable"
        # Decimal at every magnitude — no scientific notation
        assert _format_cost(12345.67) == "$12345.67"
        assert _format_cost(0.000015) == "$0.000015"
        assert _format_cost(0) == "$0"

    def test_tool_description_mentions_squad_actions(self):
        from src.revenium_mcp_server.tools_decomposed.agent_management import (
            AgentManagement,
        )

        for action in ("list_squads", "list_squad_executions", "get_squad", "get_squad_timeline"):
            assert action in AgentManagement.tool_description

    @pytest.mark.asyncio
    async def test_get_squad_caps_raw_agents_in_payload(self, squad_manager, mock_client):
        agents = [{"label": f"agent-{i}"} for i in range(60)]
        mock_client.get_squad_detail = AsyncMock(
            return_value={"id": "sq_1", "label": "Big Squad", "agents": agents}
        )
        result = await squad_manager.get_squad({"squad_id": "sq_1"})
        assert len(result["squad"]["agents"]) == 50
        assert result["squad"]["agentsOmitted"] == 10

    @pytest.mark.asyncio
    async def test_get_squad_timeline_caps_raw_events_in_payload(self, squad_manager, mock_client):
        events = [
            {"id": f"ev-{i}", "agent": "a", "timestamp": i, "startTime": "t"}
            for i in range(60)
        ]
        mock_client.get_squad_timeline = AsyncMock(
            return_value={"squadId": "sq_1", "events": events}
        )
        result = await squad_manager.get_squad_timeline({"squad_id": "sq_1"})
        assert len(result["timeline"]["events"]) == 50
        assert result["timeline"]["eventsOmitted"] == 10

    @pytest.mark.asyncio
    async def test_rendered_agent_without_label_or_id_renders_na(self, squad_manager, mock_client):
        mock_client.get_squad_detail = AsyncMock(
            return_value={"id": "sq_1", "agents": [{"role": "planner"}]}
        )
        result = await squad_manager.get_squad({"squad_id": "sq_1"})
        assert result["rendered_agents"] == ["n/a"]
