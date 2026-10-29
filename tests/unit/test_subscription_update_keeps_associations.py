"""BACK-5125: a subscription update keeps the links the caller did not change.

The platform reads a subscription's links back as ``credentials`` and
``namedOrganizations`` but writes them only through the write-only
``credentialIds`` and ``namedOrganizationIds``; a PUT without them unlinks
everything. The stored record below is the audit capture
get_subscriptions/responses/7a-iso-0-sub.json, trimmed to the fields that matter.
"""

from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.common.partial_update_handler import PartialUpdateHandler
from src.revenium_mcp_server.common.update_configs import UpdateConfigs
from src.revenium_mcp_server.tools_decomposed.subscription_management import (
    SubscriptionManagement,
    SubscriptionManager,
)
from tests.unit.test_partial_update_stale_read import LaggingClient

SUBSCRIPTION_ID = "jM7wnmB"
CREDENTIAL_ID = "3ByzZRb"
NAMED_ORGANIZATION_ID = "6PV0xe"


def _reference(resource_id: str, resource_type: str) -> Dict[str, Any]:
    return {
        "_links": {
            "self": {"href": f"/profitstream/v2/api/{resource_type}s/{resource_id}"}
        },
        "id": resource_id,
        "label": f"mcp-test-{resource_type}",
        "resourceType": resource_type,
    }


def _stored_subscription(**overrides: Any) -> Dict[str, Any]:
    record = {
        "id": SUBSCRIPTION_ID,
        "resourceType": "subscription",
        "name": "mcp-test-sub-e7fb83d2-updated",
        "clientEmailAddress": "mcp-test-e7fb83d2@example.com",
        "client": {
            **_reference("RdKqPpQ", "user"),
            "label": "mcp-test-e7fb83d2@example.com",
        },
        "organization": _reference("OQNBA6J", "organization"),
        "product": _reference("3ByoYab", "product"),
        "credentials": [_reference(CREDENTIAL_ID, "credential")],
        "namedOrganizations": [_reference(NAMED_ORGANIZATION_ID, "organization")],
        "namedSubscribers": [],
        "tags": [],
    }
    record.update(overrides)
    return record


def _client(stored: Dict[str, Any]) -> MagicMock:
    client = MagicMock()
    client.team_id = "JMwaj9y"
    client.get_subscription_by_id = AsyncMock(return_value=stored)

    async def _answer(subscription_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        return {
            **stored,
            "name": body.get("name", stored["name"]),
            "credentials": [
                _reference(i, "credential") for i in body.get("credentialIds") or []
            ],
            "namedOrganizations": [
                _reference(i, "organization")
                for i in body.get("namedOrganizationIds") or []
            ],
        }

    client.update_subscription = AsyncMock(side_effect=_answer)
    return client


async def _sent_body(
    subscription_data: Dict[str, Any], stored: Dict[str, Any]
) -> Dict[str, Any]:
    client = _client(stored)
    await SubscriptionManager(client).update_subscription(
        {"subscription_id": SUBSCRIPTION_ID, "subscription_data": subscription_data}
    )
    return client.update_subscription.call_args[0][1]


class TestAnUpdateResendsTheStoredLinks:
    @pytest.mark.asyncio
    async def test_a_name_only_update_resends_the_linked_credential(self):
        body = await _sent_body(
            {"name": "mcp-test-sub-e7fb83d2-iso1"}, _stored_subscription()
        )

        assert body["credentialIds"] == [CREDENTIAL_ID]
        assert body["name"] == "mcp-test-sub-e7fb83d2-iso1"

    @pytest.mark.asyncio
    async def test_a_name_only_update_resends_the_named_organizations(self):
        body = await _sent_body({"name": "renamed"}, _stored_subscription())

        assert body["namedOrganizationIds"] == [NAMED_ORGANIZATION_ID]

    @pytest.mark.asyncio
    async def test_the_read_only_link_objects_are_not_sent(self):
        body = await _sent_body({"name": "renamed"}, _stored_subscription())

        assert "credentials" not in body
        assert "namedOrganizations" not in body

    @pytest.mark.asyncio
    async def test_credential_ids_the_caller_sends_replace_the_stored_links(self):
        body = await _sent_body({"credentialIds": []}, _stored_subscription())

        assert body["credentialIds"] == []
        assert body["namedOrganizationIds"] == [NAMED_ORGANIZATION_ID]

    @pytest.mark.asyncio
    async def test_a_subscription_without_links_sends_empty_link_lists(self):
        body = await _sent_body(
            {"name": "renamed"},
            _stored_subscription(credentials=None, namedOrganizations=[]),
        )

        assert body["credentialIds"] == []
        assert body["namedOrganizationIds"] == []


def _text(result) -> str:
    return "\n".join(part.text for part in result)


async def _handle(arguments: Dict[str, Any], client: MagicMock):
    tool = SubscriptionManagement()
    with patch.object(tool, "get_client", new_callable=AsyncMock, return_value=client):
        return await tool.handle_action("update", arguments)


class TestTheAnswerNamesTheLinks:
    @pytest.mark.asyncio
    async def test_the_update_answer_says_the_credential_is_still_linked(self):
        client = _client(_stored_subscription())

        result = await _handle(
            {
                "subscription_id": SUBSCRIPTION_ID,
                "subscription_data": {"name": "renamed"},
            },
            client,
        )

        text = _text(result)
        assert "updated successfully" in text
        assert f"credentials: {CREDENTIAL_ID}" in text
        assert f"namedOrganizations: {NAMED_ORGANIZATION_ID}" in text


class TestTheUpdatePreview:
    @pytest.mark.asyncio
    async def test_the_preview_shows_the_credential_ids_it_would_resend(self):
        client = _client(_stored_subscription())

        result = await _handle(
            {
                "subscription_id": SUBSCRIPTION_ID,
                "subscription_data": {"name": "renamed"},
                "dry_run": True,
            },
            client,
        )

        text = _text(result)
        assert "DRY RUN" in text
        assert '"credentialIds": [\n    "3ByzZRb"\n  ]' in text
        assert "resent as stored" in text
        client.update_subscription.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "subscription_data",
        [
            {"status": "cancelled"},
            {"label": "x"},
            {"clientEmailAddress": "not-an-address"},
        ],
    )
    async def test_the_preview_refuses_exactly_what_the_update_refuses(
        self, subscription_data
    ):
        refusals = []
        for dry_run in (True, False):
            client = _client(_stored_subscription())
            arguments = {
                "subscription_id": SUBSCRIPTION_ID,
                "subscription_data": dict(subscription_data),
                "dry_run": dry_run,
            }
            with pytest.raises(ToolError) as refused:
                await _handle(arguments, client)
            client.update_subscription.assert_not_awaited()
            refusals.append(
                (refused.value.message, refused.value.field, refused.value.error_code)
            )

        assert refusals[0] == refusals[1]


class _LinkingClient(LaggingClient):
    """A lagging platform that stores credentialIds as the credentials it reads back."""

    def __init__(self, stored: Dict[str, Any]):
        super().__init__(stored)
        self.sent_bodies: List[Dict[str, Any]] = []

    async def _put(self, resource_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        self.sent_bodies.append(dict(body))
        stored = dict(body)
        if "credentialIds" in stored:
            stored["credentials"] = [
                _reference(i, "credential") for i in stored.pop("credentialIds")
            ]
        return await super()._put(resource_id, stored)


class TestALinkChangeSurvivesALaggingRead:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("new_links", [[], [CREDENTIAL_ID, "o41Yn0r"]])
    async def test_a_rename_right_after_a_link_change_keeps_that_change(
        self, new_links
    ):
        client = _LinkingClient(_stored_subscription())
        config = UpdateConfigs.create_subscriptions_config(client)
        handler = PartialUpdateHandler()

        await handler.update_with_merge(
            SUBSCRIPTION_ID, {"credentialIds": new_links}, config
        )
        await handler.update_with_merge(SUBSCRIPTION_ID, {"name": "renamed"}, config)

        assert client.sent_bodies[1]["credentialIds"] == new_links
        assert [c["id"] for c in client.committed["credentials"]] == new_links
