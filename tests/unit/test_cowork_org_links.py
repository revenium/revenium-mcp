"""The team Claude organization links: list, link and unlink on manage_customers."""

from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.client import ReveniumAPIError
from src.revenium_mcp_server.common.dry_run_guard import preview_actions
from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError
from src.revenium_mcp_server.common.tool_surface import ToolSide, domain_for
from src.revenium_mcp_server.tools_decomposed.cowork_org_links import (
    COWORK_ORG_UNLINK_EFFECT_NOTE,
    CoworkOrgLinkManager,
    format_cowork_org_links_text,
    format_link_result_text,
    format_unlink_result_text,
)
from src.revenium_mcp_server.tools_decomposed.customer_management import (
    CustomerManagement,
)
from tests.unit._helpers_recording_client import recording_client

ORG_LINKED = "0f8e1a2b-3c4d-4e5f-8a9b-0c1d2e3f4a5b"
ORG_UNLINKED = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
ORG_ELSEWHERE = "2b3c4d5e-6f7a-4b8c-9d0e-1f2a3b4c5d6e"

LINKS: List[Dict[str, Any]] = [
    {"claudeOrgUuid": ORG_LINKED, "id": "lnk1", "source": "CREDENTIAL", "state": "LINKED"},
    {"claudeOrgUuid": ORG_UNLINKED, "id": None, "source": "CREDENTIAL", "state": "NOT_LINKED"},
    {"claudeOrgUuid": ORG_ELSEWHERE, "id": None, "source": None, "state": "LINKED_BY_ANOTHER_ACCOUNT"},
]


@pytest.fixture
def client() -> MagicMock:
    mock = MagicMock()
    mock.team_id = "ambientTeam"
    mock.list_team_cowork_org_links = AsyncMock(return_value=LINKS)
    mock.link_team_cowork_org = AsyncMock(
        return_value={"claudeOrgUuid": ORG_UNLINKED, "id": "lnk2", "source": "MANUAL", "state": "LINKED"}
    )
    mock.unlink_team_cowork_org = AsyncMock(return_value={})
    return mock


@pytest.fixture
def manager(client) -> CoworkOrgLinkManager:
    return CoworkOrgLinkManager(client)


def _api_error(status: int, message: str = "upstream") -> ReveniumAPIError:
    return ReveniumAPIError(message, status_code=status)


class TestListing:
    @pytest.mark.asyncio
    async def test_each_organization_is_shown_with_its_state_and_link_id(self, manager):
        text = format_cowork_org_links_text(await manager.list_links({"team_id": "jR2kmLs"}))

        assert "## Claude organizations for team jR2kmLs" in text
        assert f"- `{ORG_LINKED}` - Linked to this team, link id `lnk1`, source CREDENTIAL" in text
        assert f"- `{ORG_UNLINKED}` - Not linked, source CREDENTIAL" in text
        assert f"- `{ORG_ELSEWHERE}` - Linked by another account" in text
        assert "Found 3 organization(s): 1 linked to this team, 1 not linked, 1 linked by another account." in text

    @pytest.mark.asyncio
    async def test_an_unrecognised_state_is_counted_so_the_summary_adds_up(self, manager, client):
        client.list_team_cowork_org_links.return_value = [
            LINKS[0],
            {"claudeOrgUuid": ORG_UNLINKED, "state": "PENDING"},
        ]

        text = format_cowork_org_links_text(await manager.list_links({}))

        assert "Found 2 organization(s): 1 linked to this team, 0 not linked, 0 linked by another account, 1 in an unrecognised state." in text
        assert f"- `{ORG_UNLINKED}` - Unrecognised state PENDING" in text

    @pytest.mark.asyncio
    async def test_without_team_id_the_callers_own_team_is_listed(self, manager, client):
        result = await manager.list_links({})

        client.list_team_cowork_org_links.assert_awaited_once_with("ambientTeam")
        assert result["team_id"] == "ambientTeam"

    @pytest.mark.asyncio
    async def test_a_blank_team_id_is_refused_instead_of_falling_back(self, manager, client):
        with pytest.raises(ToolError) as refused:
            await manager.list_links({"team_id": "  "})

        assert refused.value.field == "team_id"
        client.list_team_cowork_org_links.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_team_anywhere_is_a_missing_parameter(self, manager, client):
        client.team_id = None

        with pytest.raises(ToolError) as refused:
            await manager.list_links({})

        assert refused.value.error_code == ErrorCodes.MISSING_PARAMETER

    @pytest.mark.asyncio
    async def test_an_empty_listing_says_the_team_knows_no_organization(self, manager, client):
        client.list_team_cowork_org_links.return_value = []

        text = format_cowork_org_links_text(await manager.list_links({}))

        assert "No Claude organizations are known for this team" in text

    @pytest.mark.asyncio
    async def test_a_non_list_answer_is_reported_rather_than_shown_as_empty(self, manager, client):
        client.list_team_cowork_org_links.return_value = {"unexpected": True}

        text = format_cowork_org_links_text(await manager.list_links({}))

        assert "WARNING: The platform answered with something other than a list" in text
        assert "No Claude organizations are known" not in text

    @pytest.mark.asyncio
    async def test_the_follow_up_calls_name_the_listed_team(self, manager):
        text = format_cowork_org_links_text(await manager.list_links({"team_id": "jR2kmLs"}))

        assert "`link_cowork_org(team_id='jR2kmLs', claude_org_uuid='...')`" in text
        assert "`unlink_cowork_org(team_id='jR2kmLs', link_id='...')`" in text

    @pytest.mark.asyncio
    async def test_an_entry_without_a_uuid_is_skipped_and_counted(self, manager, client):
        client.list_team_cowork_org_links.return_value = [LINKS[0], {"state": "LINKED"}, "junk"]

        result = await manager.list_links({})

        assert [link["claudeOrgUuid"] for link in result["links"]] == [ORG_LINKED]
        assert "2 of 3 entries" in result["warning"]

    @pytest.mark.asyncio
    async def test_a_403_names_the_team_management_permission(self, manager, client):
        client.list_team_cowork_org_links.side_effect = _api_error(403)

        with pytest.raises(ToolError) as refused:
            await manager.list_links({"team_id": "jR2kmLs"})

        assert refused.value.error_code == ErrorCodes.API_AUTHORIZATION
        assert refused.value.field == "team_id"

    @pytest.mark.asyncio
    async def test_a_feature_gate_403_says_the_feature_is_off_not_a_permission(self, manager, client):
        client.list_team_cowork_org_links.side_effect = _api_error(403, "HTTP 403: Feature not available")

        with pytest.raises(ToolError) as refused:
            await manager.list_links({"team_id": "jR2kmLs"})

        assert refused.value.message == "Claude organization links are not enabled for this tenant"
        assert refused.value.field == "action"


class TestLink:
    @pytest.mark.asyncio
    async def test_dry_run_previews_the_body_and_sends_nothing(self, manager, client):
        result = await manager.link({"claude_org_uuid": ORG_UNLINKED.upper(), "dry_run": True})

        client.link_team_cowork_org.assert_not_called()
        assert result["request"] == {"claudeOrgUuid": ORG_UNLINKED}
        text = format_link_result_text(result)
        assert text.startswith("## Dry run - link a Claude organization to team ambientTeam")
        assert "No request was sent" in text

    @pytest.mark.asyncio
    async def test_links_by_uuid(self, manager, client):
        result = await manager.link({"team_id": "jR2kmLs", "claude_org_uuid": ORG_UNLINKED})

        client.link_team_cowork_org.assert_awaited_once_with("jR2kmLs", {"claudeOrgUuid": ORG_UNLINKED})
        assert f"- `{ORG_UNLINKED}` - Linked to this team, link id `lnk2`" in format_link_result_text(result)

    @pytest.mark.asyncio
    async def test_links_by_credential(self, manager, client):
        await manager.link({"credential_id": "cred_9"})

        client.link_team_cowork_org.assert_awaited_once_with("ambientTeam", {"credentialId": "cred_9"})

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "arguments, field",
        [
            ({}, "claude_org_uuid"),
            ({"claude_org_uuid": ORG_UNLINKED, "credential_id": "cred_9"}, "credential_id"),
            ({"claude_org_uuid": "not-a-uuid"}, "claude_org_uuid"),
            ({"credential_id": " "}, "credential_id"),
            ({"credential_id": "", "claude_org_uuid": ORG_UNLINKED}, "credential_id"),
            ({"credential_id": "cred_9", "claude_org_uuid": " "}, "claude_org_uuid"),
        ],
    )
    async def test_a_request_without_exactly_one_valid_mode_is_refused(
        self, manager, client, arguments, field
    ):
        with pytest.raises(ToolError) as refused:
            await manager.link({**arguments, "dry_run": True})

        assert refused.value.field == field
        client.link_team_cowork_org.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_409_says_the_organization_cannot_be_linked_from_here(self, manager, client):
        client.link_team_cowork_org.side_effect = _api_error(409)

        with pytest.raises(ToolError) as refused:
            await manager.link({"claude_org_uuid": ORG_ELSEWHERE})

        assert refused.value.error_code == ErrorCodes.RESOURCE_CONFLICT
        assert "cannot be linked from this account" in refused.value.message
        assert (refused.value.field, refused.value.value) == ("claude_org_uuid", ORG_ELSEWHERE)

    @pytest.mark.asyncio
    async def test_a_409_on_a_credential_link_names_the_credential(self, manager, client):
        client.link_team_cowork_org.side_effect = _api_error(409)

        with pytest.raises(ToolError) as refused:
            await manager.link({"credential_id": "cred_9"})

        assert (refused.value.field, refused.value.value) == ("credential_id", "cred_9")

    @pytest.mark.asyncio
    async def test_a_404_on_a_uuid_link_does_not_mention_a_credential(self, manager, client):
        client.link_team_cowork_org.side_effect = _api_error(404)

        with pytest.raises(ToolError) as refused:
            await manager.link({"claude_org_uuid": ORG_UNLINKED})

        assert refused.value.field == "team_id"
        assert not any("credential_id" in hint for hint in refused.value.suggestions)


class TestUnlink:
    @pytest.mark.asyncio
    async def test_dry_run_names_the_organization_and_sends_no_write(self, manager, client):
        result = await manager.unlink({"link_id": "lnk1", "dry_run": True})

        client.unlink_team_cowork_org.assert_not_called()
        text = format_unlink_result_text(result)
        assert text.startswith(
            f"## Dry run - unlink organization `{ORG_LINKED}` (link id `lnk1`) from team ambientTeam"
        )
        assert COWORK_ORG_UNLINK_EFFECT_NOTE in text
        assert "`unlink_cowork_org(team_id='ambientTeam', link_id='lnk1')`" in text
        assert "no write was sent" in text

    @pytest.mark.asyncio
    async def test_dry_run_on_an_unknown_link_id_warns_it_would_not_be_found(self, manager):
        text = format_unlink_result_text(await manager.unlink({"link_id": "nope", "dry_run": True}))

        assert "not among the team's current links" in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "listing",
        [{"unexpected": True}, [{"id": "lnk1", "state": "LINKED"}]],
        ids=["not-a-list", "target-entry-has-no-uuid"],
    )
    async def test_dry_run_over_an_unreadable_listing_says_it_could_not_confirm(
        self, manager, client, listing
    ):
        client.list_team_cowork_org_links.return_value = listing

        text = format_unlink_result_text(await manager.unlink({"link_id": "lnk1", "dry_run": True}))

        assert "WARNING:" in text
        assert "could not confirm whether this link id exists" in text
        assert "not among the team's current links" not in text
        client.unlink_team_cowork_org.assert_not_called()

    @pytest.mark.asyncio
    async def test_dry_run_that_finds_the_link_in_a_partly_skipped_listing_still_names_it(
        self, manager, client
    ):
        client.list_team_cowork_org_links.return_value = [LINKS[0], {"state": "LINKED"}]

        text = format_unlink_result_text(await manager.unlink({"link_id": "lnk1", "dry_run": True}))

        assert f"organization `{ORG_LINKED}` (link id `lnk1`)" in text
        assert "WARNING: 1 of 2 entries" in text
        assert "could not confirm" not in text
        assert "not among the team's current links" not in text

    @pytest.mark.asyncio
    async def test_an_unlink_without_dry_run_deletes_the_link(self, manager, client):
        result = await manager.unlink({"team_id": "jR2kmLs", "link_id": "lnk1"})

        client.unlink_team_cowork_org.assert_awaited_once_with("jR2kmLs", "lnk1")
        assert format_unlink_result_text(result).startswith("## Unlinked link id `lnk1` from team jR2kmLs")

    @pytest.mark.asyncio
    async def test_missing_link_id_is_refused_before_anything_is_read(self, manager, client):
        with pytest.raises(ToolError) as refused:
            await manager.unlink({})

        assert refused.value.field == "link_id"
        client.list_team_cowork_org_links.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_404_on_the_preview_listing_names_the_team(self, manager, client):
        client.list_team_cowork_org_links.side_effect = _api_error(404)

        with pytest.raises(ToolError) as refused:
            await manager.unlink({"team_id": "stale", "link_id": "lnk1", "dry_run": True})

        assert (refused.value.field, refused.value.value) == ("team_id", "stale")

    @pytest.mark.asyncio
    async def test_a_feature_gate_on_the_preview_listing_names_the_unlink(self, manager, client):
        client.list_team_cowork_org_links.side_effect = _api_error(403, "HTTP 403: Feature not available")

        with pytest.raises(ToolError) as refused:
            await manager.unlink({"link_id": "lnk1", "dry_run": True})

        assert (refused.value.field, refused.value.value) == ("action", "unlink_cowork_org")

    @pytest.mark.asyncio
    async def test_a_404_points_at_the_listing(self, manager, client):
        client.unlink_team_cowork_org.side_effect = _api_error(404, "Link not found for this team")

        with pytest.raises(ToolError) as refused:
            await manager.unlink({"link_id": "lnk9"})

        assert refused.value.error_code == ErrorCodes.RESOURCE_NOT_FOUND
        assert (refused.value.field, refused.value.value) == ("link_id", "lnk9")


class TestToolSurface:
    def test_the_read_is_on_get_customers_and_the_writes_on_manage_customers(self):
        domain = domain_for("manage_customers")

        assert domain.serving_side("list_cowork_org_links") is ToolSide.READ
        assert domain.serving_side("link_cowork_org") is ToolSide.WRITE
        assert domain.serving_side("unlink_cowork_org") is ToolSide.WRITE

    def test_both_writes_honour_dry_run(self):
        assert {"link_cowork_org", "unlink_cowork_org"} <= preview_actions("manage_customers")

    @pytest.mark.asyncio
    async def test_the_actions_route_through_manage_customers(self, client):
        tool = CustomerManagement()
        with patch.object(tool, "get_client", new_callable=AsyncMock, return_value=client):
            listed = await tool.handle_action("list_cowork_org_links", {})
            previewed = await tool.handle_action(
                "unlink_cowork_org", {"link_id": "lnk1", "dry_run": True}
            )

        assert ORG_LINKED in listed[0].text
        assert "Dry run - unlink" in previewed[0].text
        client.unlink_team_cowork_org.assert_not_called()


class TestClientPaths:
    @pytest.mark.asyncio
    async def test_each_method_hits_its_route(self, monkeypatch):
        client, requests = recording_client(monkeypatch, lambda method, url, params: [] if method == "GET" else {})

        await client.list_team_cowork_org_links("jR2kmLs")
        await client.link_team_cowork_org("jR2kmLs", {"claudeOrgUuid": ORG_LINKED})
        await client.unlink_team_cowork_org("jR2kmLs", "lnk1")

        routes = [(request["method"], request["url"].split("example.invalid")[-1]) for request in requests]
        assert routes == [
            ("GET", "/profitstream/v2/api/teams/jR2kmLs/cowork-org-links"),
            ("POST", "/profitstream/v2/api/teams/jR2kmLs/cowork-org-links"),
            ("DELETE", "/profitstream/v2/api/teams/jR2kmLs/cowork-org-links/lnk1"),
        ]
        assert requests[1]["json"] == {"claudeOrgUuid": ORG_LINKED}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "link_id, encoded",
        [("../../OtherTeam", "..%2F..%2FOtherTeam"), ("..", "%2E%2E"), ("a?b#c", "a%3Fb%23c")],
    )
    async def test_a_link_id_stays_one_path_segment(self, monkeypatch, link_id, encoded):
        client, requests = recording_client(monkeypatch, lambda method, url, params: {})

        await client.unlink_team_cowork_org("jR2kmLs", link_id)

        assert requests[0]["url"].endswith(f"/profitstream/v2/api/teams/jR2kmLs/cowork-org-links/{encoded}")
