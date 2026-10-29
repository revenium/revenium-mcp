"""BACK-5147: a usage meter create whose name already exists is refused.

The platform upserts metering element definitions by name: a create with a
taken name answers with the existing element, unchanged. The fixtures are the
element shapes the audit captured on dev on 2026-10-28.
"""

import json
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.client import ReveniumClient
from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError
from src.revenium_mcp_server.tools_decomposed.metering_elements_management import (
    MeteringElementsManagement,
)
from tests.unit._registered_tool_harness import call_domain_tool

EXISTING_NAME = "mcp-test-elem-1e124205-updated"

EXISTING_ELEMENT: Dict[str, Any] = {
    "id": "ByMEyoB",
    "resourceType": "metering.element.definition",
    "label": EXISTING_NAME,
    "created": "2026-10-28T21:27:32.729Z",
    "updated": "2026-10-28T21:28:33.119Z",
    "name": EXISTING_NAME,
    "description": "mcp audit element v2",
    "type": "STRING",
    "team": None,
    "isSystem": False,
}

TEMPLATE_ELEMENT: Dict[str, Any] = {
    "id": "Agkmg3w",
    "resourceType": "metering.element.definition",
    "label": "",
    "created": "2026-10-28T21:29:37.098Z",
    "updated": None,
    "name": "mcp-test-tpl-1e124205",
    "description": "Shipping cost for deliveries",
    "type": "NUMBER",
    "team": None,
    "isSystem": False,
}

SYSTEM_ELEMENT: Dict[str, Any] = {
    "id": "MrVQz3n",
    "resourceType": "metering.element.definition",
    "label": "operationSubtype",
    "created": "2026-06-18T11:13:11.144960Z",
    "updated": None,
    "name": "operationSubtype",
    "description": "Operation Subtype",
    "type": "STRING",
    "team": None,
    "isSystem": True,
}

DUPLICATE_CREATE = {
    "element_data": {"name": EXISTING_NAME, "type": "NUMBER", "description": "d"},
}

DUPLICATE_TEMPLATE_CREATE = {
    "template_name": "shippingCost",
    "overrides": {"name": TEMPLATE_ELEMENT["name"]},
}


def _page(
    rows: List[Dict[str, Any]], number: int = 0, total_pages: int = 1
) -> Dict[str, Any]:
    return {
        "_embedded": {"meteringElementDefinitionResourceList": rows},
        "page": {
            "number": number,
            "size": 100,
            "totalPages": total_pages,
            "totalElements": len(rows),
        },
    }


def _copy(element: Dict[str, Any]) -> Dict[str, Any]:
    return json.loads(json.dumps(element))


def _platform(listed: List[Dict[str, Any]], answer: Dict[str, Any]) -> MagicMock:
    """A platform that lists `listed` and answers every create with `answer`."""
    client = MagicMock()
    client.get_metering_element_definitions = AsyncMock(
        return_value=_page([_copy(row) for row in listed])
    )
    client.create_metering_element_definition = AsyncMock(return_value=_copy(answer))
    return client


async def _call(client: MagicMock, action: str, arguments: Dict[str, Any]):
    mgmt = MeteringElementsManagement()
    with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=client):
        return await mgmt.handle_action(action, arguments)


async def _refusal(
    client: MagicMock, action: str, arguments: Dict[str, Any]
) -> ToolError:
    with pytest.raises(ToolError) as refused:
        await _call(client, action, arguments)
    return refused.value


@pytest.mark.asyncio
class TestCreateOfAnExistingName:
    @pytest.mark.parametrize("dry_run", [False, True], ids=["live", "dry_run"])
    async def test_a_create_with_an_existing_name_is_refused_and_writes_nothing(
        self, dry_run
    ):
        client = _platform([EXISTING_ELEMENT], answer=EXISTING_ELEMENT)

        refused = await _refusal(
            client, "create", {**DUPLICATE_CREATE, "dry_run": dry_run}
        )

        assert refused.error_code == ErrorCodes.RESOURCE_CONFLICT
        assert "ByMEyoB" in refused.message
        assert "nothing was created" in refused.message
        assert refused.field == "element_data.name"
        client.create_metering_element_definition.assert_not_awaited()

    @pytest.mark.parametrize("dry_run", [False, True], ids=["live", "dry_run"])
    async def test_a_template_create_whose_element_exists_is_refused(self, dry_run):
        client = _platform([TEMPLATE_ELEMENT], answer=TEMPLATE_ELEMENT)

        refused = await _refusal(
            client,
            "create_from_template",
            {**DUPLICATE_TEMPLATE_CREATE, "dry_run": dry_run},
        )

        assert refused.error_code == ErrorCodes.RESOURCE_CONFLICT
        assert "Agkmg3w" in refused.message
        assert "nothing was created" in refused.message
        client.create_metering_element_definition.assert_not_awaited()

    async def test_the_refusal_points_at_the_existing_meter(self):
        client = _platform([EXISTING_ELEMENT], answer=EXISTING_ELEMENT)

        refused = await _refusal(client, "create", DUPLICATE_CREATE)

        guidance = " ".join(refused.suggestions)
        assert "get_usage_meters(action='get', element_id='ByMEyoB')" in guidance
        assert "manage_usage_meters(action='update', element_id='ByMEyoB')" in guidance

    async def test_a_system_meter_with_the_name_is_refused_as_unchangeable(self):
        client = _platform([SYSTEM_ELEMENT], answer=SYSTEM_ELEMENT)

        refused = await _refusal(
            client,
            "create_from_template",
            {
                "template_name": "shippingCost",
                "overrides": {"name": "operationSubtype"},
            },
        )

        assert refused.error_code == ErrorCodes.RESOURCE_CONFLICT
        assert "system usage meter, which cannot be changed" in refused.message
        assert "action='update'" not in " ".join(refused.suggestions)

    async def test_a_name_on_a_later_page_is_found(self):
        client = _platform([], answer=EXISTING_ELEMENT)
        client.get_metering_element_definitions = AsyncMock(
            side_effect=[
                _page([_copy(TEMPLATE_ELEMENT)], number=0, total_pages=2),
                _page([_copy(EXISTING_ELEMENT)], number=1, total_pages=2),
            ]
        )

        refused = await _refusal(client, "create", DUPLICATE_CREATE)

        assert "ByMEyoB" in refused.message
        pages = [
            call.kwargs["page"]
            for call in client.get_metering_element_definitions.await_args_list
        ]
        assert pages == [0, 1]

    async def test_an_answer_with_a_pre_existing_id_is_refused(self):
        listed_under_other_case = {**EXISTING_ELEMENT, "name": EXISTING_NAME.upper()}
        client = _platform([listed_under_other_case], answer=EXISTING_ELEMENT)

        refused = await _refusal(client, "create", DUPLICATE_CREATE)

        assert refused.error_code == ErrorCodes.RESOURCE_CONFLICT
        assert "ByMEyoB" in refused.message
        assert "nothing was created" in refused.message

    async def test_a_returned_system_meter_the_list_did_not_show_is_refused(self):
        client = _platform([], answer=SYSTEM_ELEMENT)

        refused = await _refusal(
            client,
            "create_from_template",
            {
                "template_name": "shippingCost",
                "overrides": {"name": "OperationSubtype"},
            },
        )

        assert refused.error_code == ErrorCodes.RESOURCE_CONFLICT
        assert "already exists as element MrVQz3n" in refused.message

    async def test_an_answer_that_drops_the_fields_sent_is_refused(self):
        created_by_someone_else = {**EXISTING_ELEMENT, "id": "Rc7Race"}
        client = _platform([], answer=created_by_someone_else)

        refused = await _refusal(client, "create", DUPLICATE_CREATE)

        assert refused.error_code == ErrorCodes.RESOURCE_CONFLICT
        assert "already exists as element Rc7Race" in refused.message
        client.create_metering_element_definition.assert_awaited_once()

    async def test_an_overridden_name_conflict_points_at_overrides_name(self):
        client = _platform([TEMPLATE_ELEMENT], answer=TEMPLATE_ELEMENT)

        refused = await _refusal(
            client, "create_from_template", DUPLICATE_TEMPLATE_CREATE
        )

        assert refused.field == "overrides.name"
        assert refused.value == TEMPLATE_ELEMENT["name"]

    async def test_a_template_name_conflict_points_at_template_name(self):
        shipping_weight = {**TEMPLATE_ELEMENT, "name": "shippingWeight"}
        client = _platform([shipping_weight], answer=shipping_weight)

        refused = await _refusal(
            client, "create_from_template", {"template_name": "shippingWeight"}
        )

        assert refused.field == "template_name"

    async def test_an_unreadable_list_refuses_instead_of_creating(self):
        client = _platform([], answer=EXISTING_ELEMENT)
        client.get_metering_element_definitions = AsyncMock(return_value={"items": []})

        refused = await _refusal(client, "create", DUPLICATE_CREATE)

        assert "shape this server does not read" in refused.message
        client.create_metering_element_definition.assert_not_awaited()

    async def test_a_list_that_shifted_while_paged_refuses_instead_of_creating(self):
        client = _platform([], answer=EXISTING_ELEMENT)
        shifted = _page([_copy(TEMPLATE_ELEMENT)], number=0, total_pages=1)
        shifted["page"]["totalElements"] = 2
        client.get_metering_element_definitions = AsyncMock(return_value=shifted)

        refused = await _refusal(client, "create", DUPLICATE_CREATE)

        assert "changed while being paged" in refused.message
        client.create_metering_element_definition.assert_not_awaited()

    async def test_a_lookup_that_cannot_finish_refuses_instead_of_creating(self):
        client = _platform([], answer=EXISTING_ELEMENT)
        client.get_metering_element_definitions = AsyncMock(
            return_value=_page([_copy(TEMPLATE_ELEMENT)], total_pages=10_000)
        )

        refused = await _refusal(client, "create", DUPLICATE_CREATE)

        assert "more than 5000 usage meters" in refused.message
        client.create_metering_element_definition.assert_not_awaited()


@pytest.mark.asyncio
class TestCreateOfANewName:
    async def test_a_new_name_still_creates_with_a_fresh_id(self):
        fresh = {
            **EXISTING_ELEMENT,
            "id": "Nw4e5Fz",
            "name": "brand-new",
            "type": "NUMBER",
        }
        client = _platform([EXISTING_ELEMENT], answer=fresh)

        answer = await _call(
            client, "create", {"element_data": {"name": "brand-new", "type": "NUMBER"}}
        )

        assert "created successfully" in answer[0].text
        assert "Nw4e5Fz" in answer[0].text
        client.create_metering_element_definition.assert_awaited_once()

    async def test_a_new_template_name_still_creates(self):
        client = _platform([EXISTING_ELEMENT], answer=TEMPLATE_ELEMENT)

        answer = await _call(client, "create_from_template", DUPLICATE_TEMPLATE_CREATE)

        assert "created from template 'shippingCost'" in answer[0].text
        assert "Agkmg3w" in answer[0].text

    @pytest.mark.parametrize(
        ("action", "arguments"),
        [
            ("create", {"element_data": {"name": "brand-new", "type": "NUMBER"}}),
            ("create_from_template", {"template_name": "shippingWeight"}),
        ],
        ids=["create", "create_from_template"],
    )
    async def test_a_dry_run_with_a_new_name_previews_without_writing(
        self, action, arguments
    ):
        client = _platform([EXISTING_ELEMENT], answer=EXISTING_ELEMENT)

        answer = await _call(client, action, {**arguments, "dry_run": True})

        assert "DRY RUN" in answer[0].text
        client.get_metering_element_definitions.assert_awaited()
        client.create_metering_element_definition.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_registered_tool_flags_the_refusal(monkeypatch, tmp_path):
    monkeypatch.setattr(
        ReveniumClient,
        "get_metering_element_definitions",
        AsyncMock(return_value=_page([_copy(EXISTING_ELEMENT)])),
    )
    monkeypatch.setattr(
        ReveniumClient,
        "create_metering_element_definition",
        AsyncMock(return_value=_copy(EXISTING_ELEMENT)),
    )

    result, text = await call_domain_tool(
        monkeypatch,
        tmp_path,
        "manage_usage_meters",
        {"action": "create", **DUPLICATE_CREATE},
    )

    assert result.is_error is True, text
    assert "already exists as element ByMEyoB" in text
