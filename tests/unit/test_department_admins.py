"""Naming and removing department admins on manage_customers (BACK-5501)."""

from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.client import ReveniumAPIError
from src.revenium_mcp_server.common.dry_run_guard import preview_actions
from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError
from src.revenium_mcp_server.common.tool_surface import ToolSide, domain_for
from src.revenium_mcp_server.tools_decomposed.customer_management import (
    CustomerManagement,
    DepartmentManager,
    _normalize_department,
)
from src.revenium_mcp_server.tools_decomposed.department_admins import (
    DEPARTMENT_ADMIN_NAME_EFFECT_NOTE,
    DepartmentTree,
    DEPARTMENT_ADMIN_REMOVE_EFFECT_NOTE,
    format_name_admin_text,
    format_remove_admin_text,
)
from tests.unit._helpers_recording_client import recording_client

ASH = {"personId": 97, "email": "ash@acme.com", "hasLogin": True, "source": "MANUAL"}
BISHOP = {"personId": 98, "email": "bishop@acme.com", "hasLogin": False, "source": "CSV"}
DALLAS = {"personId": 99, "email": "dallas@acme.com", "hasLogin": True, "source": "MANUAL"}


def _departments(payments_admins: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {"id": 12, "name": "Company", "parentId": None, "path": "/12/", "admins": [DALLAS]},
        {"id": 40, "name": "Engineering", "parentId": 12, "path": "/12/40/", "admins": []},
        {"id": 173, "name": "Payments", "parentId": 40, "path": "/12/40/173/", "admins": payments_admins},
        {"id": 174, "name": "Ledger", "parentId": 173, "path": "/12/40/173/174/", "admins": []},
        {"id": 175, "name": "Cards", "parentId": 173, "path": "/12/40/173/175/", "admins": []},
        {"id": 176, "name": "Settlement", "parentId": 174, "path": "/12/40/173/174/176/", "admins": []},
        {"id": 50, "name": "Sales", "parentId": 12, "path": "/12/50/", "admins": []},
    ]


@pytest.fixture
def client() -> MagicMock:
    mock = MagicMock()
    mock.get_departments = AsyncMock(return_value=_departments([ASH, BISHOP]))
    mock.add_department_admin = AsyncMock()
    mock.remove_department_admin = AsyncMock(return_value={})
    return mock


@pytest.fixture
def manager(client) -> DepartmentManager:
    return DepartmentManager(client)


def _api_error(status: int, message: str = "upstream") -> ReveniumAPIError:
    return ReveniumAPIError(message, status_code=status)


class TestNamePreview:
    @pytest.mark.asyncio
    async def test_the_preview_names_the_department_and_every_department_below_it(self, manager, client):
        result = await manager.name_department_admin(
            {"department_id": 173, "email": "ripley@acme.com", "dry_run": True}
        )
        text = format_name_admin_text(result)

        assert "## Dry run - name ripley@acme.com an admin of Company / Engineering / Payments (id 173)" in text
        assert (
            "Once named, ripley@acme.com will be able to see Company / Engineering / Payments (id 173) "
            "and the 3 department(s) below it:" in text
        )
        assert "- Company / Engineering / Payments / Cards (id 175)" in text
        assert "- Company / Engineering / Payments / Ledger (id 174)" in text
        assert "- Company / Engineering / Payments / Ledger / Settlement (id 176)" in text
        assert "Sales" not in text
        assert "- ash@acme.com (person_id 97, named MANUAL)" in text
        assert "- bishop@acme.com (person_id 98, named CSV, no Revenium login yet)" in text
        assert DEPARTMENT_ADMIN_NAME_EFFECT_NOTE in text
        assert 'with `{"email": "ripley@acme.com"}`' in text
        assert "no write was sent" in text
        client.add_department_admin.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_leaf_department_says_nothing_is_below_it(self, manager):
        text = format_name_admin_text(
            await manager.name_department_admin({"department_id": 176, "email": "ripley@acme.com", "dry_run": True})
        )

        assert "It has no departments below it." in text

    @pytest.mark.asyncio
    async def test_an_existing_admin_is_told_nothing_new_is_granted(self, manager):
        text = format_name_admin_text(
            await manager.name_department_admin({"department_id": 173, "email": "BISHOP@acme.com", "dry_run": True})
        )

        assert "BISHOP@acme.com is already an admin of this department (named CSV)" in text
        assert "it only turns the CSV naming into a naming by hand" in text

    @pytest.mark.asyncio
    async def test_an_admin_of_a_department_above_already_sees_the_subtree(self, manager):
        text = format_name_admin_text(
            await manager.name_department_admin({"department_id": 173, "email": "dallas@acme.com", "dry_run": True})
        )

        assert "dallas@acme.com is already an admin of Company (id 12)" in text

    @pytest.mark.asyncio
    async def test_an_unknown_department_is_previewed_as_not_found(self, manager, client):
        text = format_name_admin_text(
            await manager.name_department_admin({"department_id": 999, "email": "ripley@acme.com", "dry_run": True})
        )

        assert "Department 999 is not among the team's active departments" in text
        client.add_department_admin.assert_not_called()


class TestName:
    @pytest.mark.asyncio
    async def test_naming_sends_the_email_and_reports_the_new_subtree(self, manager, client):
        ripley = {"personId": 120, "email": "ripley@acme.com", "hasLogin": False, "source": "MANUAL"}
        client.add_department_admin.return_value = [ASH, BISHOP, ripley]

        result = await manager.name_department_admin(
            {"department_id": "173", "email": "ripley@acme.com", "team_id": "jR2kmLs"}
        )
        text = format_name_admin_text(result)

        client.add_department_admin.assert_awaited_once_with(173, "ripley@acme.com", "jR2kmLs")
        assert text.startswith("## Named ripley@acme.com an admin of Company / Engineering / Payments (id 173) in team jR2kmLs")
        assert "ripley@acme.com can now see Company / Engineering / Payments (id 173) and the 3 department(s) below it:" in text
        assert "has no Revenium login yet" in text
        assert result["was_admin_before"] is False

    @pytest.mark.asyncio
    async def test_naming_an_existing_admin_is_not_reported_as_a_new_grant(self, manager, client):
        client.add_department_admin.return_value = [ASH, {**BISHOP, "source": "MANUAL"}]

        result = await manager.name_department_admin({"department_id": 173, "email": "bishop@acme.com"})
        text = format_name_admin_text(result)

        assert text.startswith("## bishop@acme.com was already an admin of Company / Engineering / Payments (id 173); nothing new was granted")
        assert "undoing that CSV import no longer removes them" in text
        assert "Named" not in text

    @pytest.mark.asyncio
    async def test_a_response_without_the_person_is_not_reported_as_success(self, manager, client):
        client.add_department_admin.return_value = []

        text = format_name_admin_text(
            await manager.name_department_admin(
                {"department_id": 173, "email": "ripley@acme.com", "team_id": "jR2kmLs"}
            )
        )

        assert "ripley@acme.com is not among the admins it returned" in text
        assert "dry_run=true, team_id='jR2kmLs')`" in text

    @pytest.mark.asyncio
    async def test_a_secondary_email_is_not_matched_to_whoever_the_put_added(self, manager, client):
        ripley = {"personId": 120, "email": "ripley@acme.com", "hasLogin": True, "source": "MANUAL"}
        client.add_department_admin.return_value = [ASH, BISHOP, ripley]

        result = await manager.name_department_admin({"department_id": 173, "email": "ellen@weyland.io"})
        text = format_name_admin_text(result)

        assert result["named_admin"] is None
        assert result["was_admin_before"] is False
        assert [a["person_id"] for a in result["admins_added"]] == [120]
        assert "ellen@weyland.io is not among the admins it returned" in text
        assert "Admins listed now that were not listed before the call:" in text
        assert "ripley@acme.com" in text
        assert "left unconfirmed" in text
        assert "Named ellen@weyland.io" not in text
        assert "can now see" not in text

    @pytest.mark.asyncio
    async def test_a_secondary_email_of_an_existing_admin_is_not_a_new_grant(self, manager, client):
        client.add_department_admin.return_value = [ASH, BISHOP]

        result = await manager.name_department_admin({"department_id": 173, "email": "ash.alt@acme.com"})
        text = format_name_admin_text(result)

        assert result["was_admin_before"] is True
        assert "nothing new was granted" in text
        assert "most likely belongs to an existing admin listed under their primary email" in text

    @pytest.mark.asyncio
    async def test_an_unknown_department_is_refused_before_the_write(self, manager, client):
        with pytest.raises(ToolError) as refused:
            await manager.name_department_admin({"department_id": 999, "email": "ripley@acme.com"})

        assert (refused.value.field, refused.value.value) == ("department_id", 999)
        assert refused.value.error_code == ErrorCodes.RESOURCE_NOT_FOUND
        client.add_department_admin.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "message, field, value",
        [
            ("Department not found in current organization", "department_id", 173),
            ("No directory person for this email", "email", "ripley@acme.com"),
        ],
    )
    async def test_a_404_names_the_department_or_the_email(self, manager, client, message, field, value):
        client.add_department_admin.side_effect = _api_error(404, message)

        with pytest.raises(ToolError) as refused:
            await manager.name_department_admin({"department_id": 173, "email": "ripley@acme.com"})

        assert refused.value.error_code == ErrorCodes.RESOURCE_NOT_FOUND
        assert (refused.value.field, refused.value.value) == (field, value)

    @pytest.mark.asyncio
    async def test_a_409_is_a_conflict_not_a_success(self, manager, client):
        client.add_department_admin.side_effect = _api_error(409, "Resource conflicts with an existing record")

        with pytest.raises(ToolError) as refused:
            await manager.name_department_admin({"department_id": 173, "email": "ripley@acme.com"})

        assert refused.value.error_code == ErrorCodes.RESOURCE_CONFLICT
        assert "Resource conflicts with an existing record" in refused.value.message

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [400, 422])
    async def test_a_400_or_422_is_a_validation_error_with_the_platform_text(self, manager, client, status):
        client.add_department_admin.side_effect = _api_error(status, "Email matches more than one directory person")

        with pytest.raises(ToolError) as refused:
            await manager.name_department_admin({"department_id": 173, "email": "ripley@acme.com"})

        assert refused.value.error_code == ErrorCodes.VALIDATION_ERROR
        assert "more than one directory person" in refused.value.message

    @pytest.mark.asyncio
    async def test_a_403_on_the_listing_read_says_departments_are_not_enabled(self, manager, client):
        client.get_departments.side_effect = _api_error(403, "Forbidden")

        with pytest.raises(ToolError) as refused:
            await manager.name_department_admin(
                {"department_id": 173, "email": "ripley@acme.com", "dry_run": True}
            )

        assert refused.value.message == "Departments are not enabled for this tenant"
        client.add_department_admin.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_404_hint_keeps_the_callers_team(self, manager, client):
        client.add_department_admin.side_effect = _api_error(404, "Department not found in current organization")

        with pytest.raises(ToolError) as refused:
            await manager.name_department_admin(
                {"department_id": 173, "email": "ripley@acme.com", "team_id": "jR2kmLs"}
            )

        assert "Use list_departments(team_id='jR2kmLs') to check the department id" in refused.value.suggestions

    @pytest.mark.asyncio
    async def test_a_403_names_both_causes(self, manager, client):
        client.add_department_admin.side_effect = _api_error(403, "Forbidden")

        with pytest.raises(ToolError) as refused:
            await manager.name_department_admin({"department_id": 173, "email": "ripley@acme.com"})

        assert refused.value.error_code == ErrorCodes.API_AUTHORIZATION
        assert "Two causes give this answer" in refused.value.message

    @pytest.mark.asyncio
    @pytest.mark.parametrize("department_id", [None, 0, -4, "abc", True])
    async def test_a_missing_or_malformed_department_id_is_refused_before_any_read(
        self, manager, client, department_id
    ):
        with pytest.raises(ToolError) as refused:
            await manager.name_department_admin({"department_id": department_id, "email": "ripley@acme.com"})

        assert refused.value.field == "department_id"
        client.get_departments.assert_not_called()


class TestRemovePreview:
    @pytest.mark.asyncio
    async def test_the_preview_names_the_admin_and_the_subtree_they_would_lose(self, manager, client):
        text = format_remove_admin_text(
            await manager.remove_department_admin({"department_id": 173, "person_id": 97, "dry_run": True})
        )

        assert "## Dry run - remove ash@acme.com as an admin of Company / Engineering / Payments (id 173)" in text
        assert "Admin to remove: ash@acme.com (person_id 97, named MANUAL)" in text
        assert (
            "ash@acme.com would stop seeing:\n"
            "- Company / Engineering / Payments (id 173)\n"
            "- Company / Engineering / Payments / Cards (id 175)\n"
            "- Company / Engineering / Payments / Ledger (id 174)\n"
            "- Company / Engineering / Payments / Ledger / Settlement (id 176)\n" in text
        )
        assert DEPARTMENT_ADMIN_REMOVE_EFFECT_NOTE in text
        assert "`remove_department_admin(department_id=173, person_id=97)`" in text
        client.remove_department_admin.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_person_who_is_not_an_admin_is_previewed_as_no_change(self, manager):
        text = format_remove_admin_text(
            await manager.remove_department_admin({"department_id": 173, "email": "ripley@acme.com", "dry_run": True})
        )

        assert "ripley@acme.com is not among this department's admins, so the removal would change nothing" in text
        assert "would stop seeing" not in text

    @pytest.mark.asyncio
    async def test_an_admin_of_a_department_above_keeps_the_subtree(self, manager, client):
        client.get_departments.return_value = _departments([ASH, DALLAS])

        text = format_remove_admin_text(
            await manager.remove_department_admin({"department_id": 173, "person_id": 99, "dry_run": True})
        )

        assert "dallas@acme.com would lose nothing they can see." in text
        assert "dallas@acme.com would keep seeing these through their admin naming on Company (id 12):" in text
        assert "would stop seeing" not in text

    @pytest.mark.asyncio
    async def test_a_naming_below_keeps_its_own_subtree_out_of_the_loss(self, manager, client):
        departments = _departments([ASH])
        departments[3]["admins"] = [ASH]
        client.get_departments.return_value = departments

        text = format_remove_admin_text(
            await manager.remove_department_admin({"department_id": 173, "person_id": 97, "dry_run": True})
        )

        assert (
            "ash@acme.com would stop seeing:\n"
            "- Company / Engineering / Payments (id 173)\n"
            "- Company / Engineering / Payments / Cards (id 175)\n\n" in text
        )
        assert (
            "ash@acme.com would keep seeing these through their admin naming on "
            "Company / Engineering / Payments / Ledger (id 174):\n"
            "- Company / Engineering / Payments / Ledger (id 174)\n"
            "- Company / Engineering / Payments / Ledger / Settlement (id 176)" in text
        )


class TestRemove:
    @pytest.mark.asyncio
    async def test_the_answer_re_lists_the_admins_after_the_204(self, manager, client):
        client.get_departments.side_effect = [_departments([ASH, BISHOP]), _departments([BISHOP])]

        result = await manager.remove_department_admin({"department_id": 173, "person_id": 97, "team_id": "jR2kmLs"})
        text = format_remove_admin_text(result)

        client.remove_department_admin.assert_awaited_once_with(173, 97, "jR2kmLs")
        assert client.get_departments.await_count == 2
        assert result["still_admin"] is False
        assert text.startswith("## Removed ash@acme.com as an admin of Company / Engineering / Payments (id 173); they are no longer listed")
        assert "- bishop@acme.com (person_id 98" in text
        assert "- ash@acme.com" not in text

    @pytest.mark.asyncio
    async def test_a_person_still_listed_after_the_204_is_flagged(self, manager, client):
        client.get_departments.side_effect = [_departments([ASH]), _departments([ASH])]

        result = await manager.remove_department_admin({"department_id": 173, "person_id": 97})

        assert result["still_admin"] is True
        assert format_remove_admin_text(result).startswith("## WARNING: ash@acme.com is still listed")

    @pytest.mark.asyncio
    async def test_a_204_for_someone_who_was_not_an_admin_says_nothing_changed(self, manager, client):
        result = await manager.remove_department_admin({"department_id": 173, "person_id": 120})

        client.remove_department_admin.assert_awaited_once_with(173, 120, None)
        assert format_remove_admin_text(result).startswith(
            "## person 120 was not an admin of Company / Engineering / Payments (id 173); nothing changed"
        )

    @pytest.mark.asyncio
    async def test_a_failed_re_read_does_not_hide_that_the_removal_was_sent(self, manager, client):
        client.get_departments.side_effect = [_departments([ASH]), _api_error(500, "boom")]

        result = await manager.remove_department_admin({"department_id": 173, "person_id": 97})

        assert result["still_admin"] is None
        assert "could not confirm it" in format_remove_admin_text(result)

    @pytest.mark.asyncio
    async def test_a_re_read_without_admins_is_unconfirmed_not_a_removal(self, manager, client):
        without_admins = [{k: v for k, v in row.items() if k != "admins"} for row in _departments([])]
        client.get_departments.side_effect = [_departments([ASH]), without_admins]

        result = await manager.remove_department_admin({"department_id": 173, "person_id": 97})

        assert result["still_admin"] is None
        assert "could not confirm it" in format_remove_admin_text(result)

    @pytest.mark.asyncio
    async def test_an_email_cannot_be_resolved_when_the_listing_has_no_admins(self, manager, client):
        client.get_departments.return_value = [
            {k: v for k, v in row.items() if k != "admins"} for row in _departments([])
        ]

        with pytest.raises(ToolError) as refused:
            await manager.remove_department_admin({"department_id": 173, "email": "ash@acme.com"})

        assert "cannot be resolved" in refused.value.message
        client.remove_department_admin.assert_not_called()

    @pytest.mark.asyncio
    async def test_an_email_is_resolved_to_the_admins_person_id(self, manager, client):
        await manager.remove_department_admin({"department_id": 173, "email": "Bishop@acme.com"})

        client.remove_department_admin.assert_awaited_once_with(173, 98, None)

    @pytest.mark.asyncio
    async def test_an_email_that_is_not_an_admin_sends_nothing(self, manager, client):
        with pytest.raises(ToolError) as refused:
            await manager.remove_department_admin({"department_id": 173, "email": "ripley@acme.com"})

        assert refused.value.field == "email"
        client.remove_department_admin.assert_not_called()

    @pytest.mark.asyncio
    async def test_an_unknown_department_is_refused_before_the_write(self, manager, client):
        with pytest.raises(ToolError) as refused:
            await manager.remove_department_admin({"department_id": 999, "person_id": 97})

        assert refused.value.field == "department_id"
        client.remove_department_admin.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_404_from_the_delete_names_the_department(self, manager, client):
        client.remove_department_admin.side_effect = _api_error(404, "Department not found in current organization")

        with pytest.raises(ToolError) as refused:
            await manager.remove_department_admin({"department_id": 173, "person_id": 97})

        assert refused.value.error_code == ErrorCodes.RESOURCE_NOT_FOUND
        assert (refused.value.field, refused.value.value) == ("department_id", 173)

    @pytest.mark.asyncio
    async def test_a_409_from_the_delete_is_a_conflict(self, manager, client):
        client.remove_department_admin.side_effect = _api_error(409, "Resource conflicts with an existing record")

        with pytest.raises(ToolError) as refused:
            await manager.remove_department_admin({"department_id": 173, "person_id": 97})

        assert refused.value.error_code == ErrorCodes.RESOURCE_CONFLICT

    @pytest.mark.asyncio
    async def test_person_id_and_email_together_are_refused(self, manager, client):
        with pytest.raises(ToolError):
            await manager.remove_department_admin({"department_id": 173, "person_id": 97, "email": "ash@acme.com"})

        client.get_departments.assert_not_called()


class TestClientPaths:
    @pytest.mark.asyncio
    async def test_each_method_hits_its_route_once(self, monkeypatch):
        client, requests = recording_client(monkeypatch, lambda method, url, params: [ASH] if method == "PUT" else {})

        admins = await client.add_department_admin(173, "ash@acme.com", "jR2kmLs")
        await client.remove_department_admin(173, 97)

        routes = [(r["method"], r["url"].split("example.invalid")[-1]) for r in requests]
        assert routes == [
            ("PUT", "/profitstream/v2/api/departments/173/admins"),
            ("DELETE", "/profitstream/v2/api/departments/173/admins/97"),
        ]
        assert requests[0]["json"] == {"email": "ash@acme.com"}
        assert requests[0]["params"]["teamId"] == "jR2kmLs"
        assert requests[1]["params"]["teamId"] == "team_1"
        assert admins == [ASH]

    @pytest.mark.asyncio
    async def test_neither_write_is_retried(self, monkeypatch):
        client, _ = recording_client(monkeypatch, lambda method, url, params: {})

        with patch.object(client, "put", new_callable=AsyncMock, return_value=[]) as put, patch.object(
            client, "delete", new_callable=AsyncMock, return_value={}
        ) as delete:
            await client.add_department_admin(173, "ash@acme.com")
            await client.remove_department_admin(173, 97)

        assert put.await_args.kwargs["use_retry"] is False
        assert delete.await_args.kwargs["use_retry"] is False


class TestToolSurface:
    def test_both_actions_are_writes_on_manage_customers(self):
        domain = domain_for("manage_customers")

        assert domain.serving_side("name_department_admin") is ToolSide.WRITE
        assert domain.serving_side("remove_department_admin") is ToolSide.WRITE

    def test_both_writes_honour_dry_run(self):
        assert {"name_department_admin", "remove_department_admin"} <= preview_actions("manage_customers")

    @pytest.mark.asyncio
    async def test_the_actions_route_through_manage_customers(self, client):
        tool = CustomerManagement()
        with patch.object(tool, "get_client", new_callable=AsyncMock, return_value=client):
            named = await tool.handle_action(
                "name_department_admin", {"department_id": 173, "email": "ripley@acme.com", "dry_run": True}
            )
            removed = await tool.handle_action(
                "remove_department_admin", {"department_id": 173, "person_id": 97, "dry_run": True}
            )

        assert "Dry run - name ripley@acme.com" in named[0].text
        assert "Dry run - remove ash@acme.com" in removed[0].text
        client.add_department_admin.assert_not_called()
        client.remove_department_admin.assert_not_called()


class TestUnreadableListing:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("listing", [{"unexpected": True}, [{"name": "no id"}, "junk"]])
    async def test_previews_warn_instead_of_reporting_an_unknown_department(self, manager, client, listing):
        client.get_departments.return_value = listing

        named = format_name_admin_text(
            await manager.name_department_admin({"department_id": 173, "email": "ripley@acme.com", "dry_run": True})
        )
        removed = format_remove_admin_text(
            await manager.remove_department_admin({"department_id": 173, "person_id": 97, "dry_run": True})
        )

        for text in (named, removed):
            assert "WARNING:" in text
            assert "not among the team's active departments" not in text
        client.add_department_admin.assert_not_called()
        client.remove_department_admin.assert_not_called()

    @pytest.mark.asyncio
    async def test_skipped_entries_are_reported_on_a_readable_listing(self, manager, client):
        client.get_departments.return_value = [*_departments([ASH]), {"name": "no id"}]

        text = format_name_admin_text(
            await manager.name_department_admin({"department_id": 173, "email": "ripley@acme.com", "dry_run": True})
        )

        assert "WARNING: 1 malformed entries in the departments listing were skipped" in text

    @pytest.mark.asyncio
    async def test_an_email_removal_sends_nothing(self, manager, client):
        client.get_departments.return_value = {"unexpected": True}

        with pytest.raises(ToolError) as refused:
            await manager.remove_department_admin({"department_id": 173, "email": "ash@acme.com"})

        assert refused.value.error_code == ErrorCodes.API_ERROR
        client.remove_department_admin.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_person_id_removal_is_still_sent_and_left_unconfirmed(self, manager, client):
        client.get_departments.return_value = {"unexpected": True}

        result = await manager.remove_department_admin({"department_id": 173, "person_id": 97})

        client.remove_department_admin.assert_awaited_once_with(173, 97, None)
        assert result["still_admin"] is None
        assert "something other than a list" in result["reread_problem"]

    @pytest.mark.asyncio
    async def test_a_naming_is_still_sent_when_the_department_cannot_be_checked(self, manager, client):
        client.get_departments.return_value = {"unexpected": True}
        client.add_department_admin.return_value = [ASH]

        result = await manager.name_department_admin({"department_id": 173, "email": "ash@acme.com"})

        client.add_department_admin.assert_awaited_once_with(173, "ash@acme.com", None)
        assert result["named_admin"]["person_id"] == 97


def _without_admins(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{k: v for k, v in row.items() if k != "admins"} for row in rows]


class TestUnknownAdmins:
    @pytest.mark.asyncio
    async def test_a_dry_run_without_admins_does_not_call_the_removal_a_no_op(self, manager, client):
        client.get_departments.return_value = _without_admins(_departments([]))

        text = format_remove_admin_text(
            await manager.remove_department_admin({"department_id": 173, "person_id": 97, "dry_run": True})
        )

        assert "whether person 97 is an admin, and what they would stop seeing, cannot be told" in text
        assert "would change nothing" not in text

    @pytest.mark.asyncio
    async def test_a_removal_over_a_listing_without_admins_does_not_claim_nothing_changed(self, manager, client):
        client.get_departments.side_effect = [_without_admins(_departments([])), _departments([])]

        result = await manager.remove_department_admin({"department_id": 173, "person_id": 97})
        text = format_remove_admin_text(result)

        assert result["was_admin_before"] is None
        assert "whether they were before could not be read" in text
        assert "nothing changed" not in text


class TestOneEntryRule:
    @pytest.mark.parametrize("entry_id", [-5, "abc", None, True, "17.5"])
    def test_the_listing_and_the_admin_actions_skip_the_same_entries(self, entry_id):
        entry = {"id": entry_id, "name": "Odd", "path": "/1/"}

        assert _normalize_department(entry) is None
        assert DepartmentTree.from_response([entry]).get(-5) is None
        assert DepartmentTree.from_response([entry]).skipped == 1

    @pytest.mark.parametrize("entry_id, expected", [(173, "173"), (173.0, "173"), ("173", "173"), (0, "0")])
    def test_both_accept_the_same_ids(self, entry_id, expected):
        entry = {"id": entry_id, "name": "Payments", "path": f"/{expected}/"}

        assert _normalize_department(entry)["id"] == expected
        assert DepartmentTree.from_response([entry]).get(int(expected)) is not None
