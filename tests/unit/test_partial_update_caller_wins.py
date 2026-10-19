"""BACK-4627: a field the caller sends reaches the PUT body unchanged.

Each test drives PartialUpdateHandler with the production UpdateConfig for the
resource, a stored record whose nested objects carry the old relationship, and
a caller value for the field being moved, then reads the body the fake client
received.
"""

from typing import Any, Dict, List, Optional, Tuple

import pytest

from src.revenium_mcp_server.client import ReveniumClient
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.common.partial_update_handler import PartialUpdateHandler
from src.revenium_mcp_server.common.update_configs import UpdateConfigs


class RecordingClient:
    """Serves one stored record on every GET and records every PUT body."""

    team_id = "team_1"

    class auth_config:
        tenant_id = "tenant_1"
        team_id = "team_1"

    def __init__(self, stored: Dict[str, Any]):
        self._stored = stored
        self.get_count = 0
        self.put_bodies: List[Tuple[str, Dict[str, Any]]] = []

    async def _get(self, resource_id: str) -> Dict[str, Any]:
        self.get_count += 1
        return dict(self._stored)

    async def _put(self, resource_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        self.put_bodies.append((resource_id, body))
        return {"id": resource_id, **body}

    def __getattr__(self, name: str):
        if name.startswith("get_") and name.endswith("_by_id"):
            return self._get
        if name.startswith("update_"):
            return self._put
        raise AttributeError(name)

    @property
    def sent(self) -> Dict[str, Any]:
        assert len(self.put_bodies) == 1
        return self.put_bodies[0][1]


async def _update(config_factory, stored, caller_data, **config_kwargs) -> RecordingClient:
    client = RecordingClient(stored)
    config = config_factory(client, **config_kwargs)
    await PartialUpdateHandler().update_with_merge(stored["id"], caller_data, config)
    return client


async def _refused_update(
    config_factory, stored, caller_data, **config_kwargs
) -> Tuple[RecordingClient, ToolError]:
    client = RecordingClient(stored)
    config = config_factory(client, **config_kwargs)
    with pytest.raises(ToolError) as refusal:
        await PartialUpdateHandler().update_with_merge(stored["id"], caller_data, config)
    return client, refusal.value


def _ref(resource_id: Optional[str]) -> Dict[str, Any]:
    return {"id": resource_id, "resourceType": "x", "label": "x"}


STORED_SUBSCRIPTION = {
    "id": "subn_1",
    "name": "Pro",
    "product": _ref("OLD_PRODUCT"),
    "productId": "OLD_PRODUCT",
    "client": {"id": "subr_1", "label": "buyer@example.com"},
    "organization": _ref("org_1"),
    "owner": _ref("owner_1"),
}

STORED_SUBSCRIBER = {
    "id": "subr_1",
    "email": "person@example.com",
    "firstName": "Pat",
    "lastName": "Doe",
    "organizations": [_ref("OLD_ORG")],
}

STORED_ORGANIZATION = {
    "id": "org_1",
    "name": "Acme",
    "parent": _ref("OLD_PARENT"),
}

STORED_SOURCE = {
    "id": "src_1",
    "name": "gateway",
    "description": "d",
    "version": "1.0.0",
    "type": "API",
    "owner": _ref("owner_1"),
    "tags": ["old-tag"],
    "externalId": "old-external",
    "externalUsagePlanId": "old-plan",
}


class TestCallerValueWins:
    @pytest.mark.asyncio
    async def test_subscription_moves_to_the_product_the_caller_names(self):
        client = await _update(
            UpdateConfigs.create_subscriptions_config,
            STORED_SUBSCRIPTION,
            {"productId": "NEW_PRODUCT"},
        )
        assert client.sent["productId"] == "NEW_PRODUCT"
        assert "product" not in client.sent

    @pytest.mark.asyncio
    async def test_subscriber_moves_to_the_organization_the_caller_names(self):
        client = await _update(
            UpdateConfigs.create_customers_config,
            STORED_SUBSCRIBER,
            {"organizationIds": ["NEW_ORG"]},
            resource_type="subscriber",
        )
        assert client.sent["organizationIds"] == ["NEW_ORG"]
        assert "organizations" not in client.sent

    @pytest.mark.asyncio
    async def test_organization_takes_the_parent_the_caller_names(self):
        client = await _update(
            UpdateConfigs.create_customers_config,
            STORED_ORGANIZATION,
            {"parentId": "NEW_PARENT"},
            resource_type="organization",
        )
        assert client.sent["parentId"] == "NEW_PARENT"
        assert "parent" not in client.sent

    @pytest.mark.asyncio
    async def test_source_takes_the_tags_external_id_and_usage_plan_the_caller_names(self):
        client = await _update(
            UpdateConfigs.create_sources_config,
            STORED_SOURCE,
            {
                "tags": ["new-tag"],
                "externalId": "new-external",
                "externalUsagePlanId": "new-plan",
            },
        )
        assert client.sent["tags"] == ["new-tag"]
        assert client.sent["externalId"] == "new-external"
        assert client.sent["externalUsagePlanId"] == "new-plan"


class TestMultiTargetSourceFollowsTheCaller:
    @pytest.mark.asyncio
    async def test_new_subscriber_is_not_paired_with_the_old_client_email(self):
        client = await _update(
            UpdateConfigs.create_subscriptions_config,
            STORED_SUBSCRIPTION,
            {"subscriberId": "subr_NEW"},
        )
        assert client.sent["subscriberId"] == "subr_NEW"
        assert "clientEmailAddress" not in client.sent
        assert "client" not in client.sent

    @pytest.mark.asyncio
    async def test_a_new_client_email_keeps_the_stored_subscriber(self):
        client = await _update(
            UpdateConfigs.create_subscriptions_config,
            STORED_SUBSCRIPTION,
            {"clientEmailAddress": "new-buyer@example.com"},
        )
        assert client.sent["clientEmailAddress"] == "new-buyer@example.com"
        assert client.sent["subscriberId"] == "subr_1"
        assert "client" not in client.sent

    @pytest.mark.asyncio
    async def test_both_client_fields_are_derived_when_the_caller_sends_neither(self):
        client = await _update(
            UpdateConfigs.create_subscriptions_config,
            STORED_SUBSCRIPTION,
            {"name": "Pro renamed"},
        )
        assert client.sent["subscriberId"] == "subr_1"
        assert client.sent["clientEmailAddress"] == "buyer@example.com"


class TestUnsentRelationshipsAreKept:
    @pytest.mark.asyncio
    async def test_name_only_organization_update_keeps_the_parent(self):
        client = await _update(
            UpdateConfigs.create_customers_config,
            STORED_ORGANIZATION,
            {"name": "Acme Holdings"},
            resource_type="organization",
        )
        assert client.sent["parentId"] == "OLD_PARENT"
        assert client.sent["name"] == "Acme Holdings"

    @pytest.mark.asyncio
    async def test_name_only_subscription_update_keeps_the_product(self):
        client = await _update(
            UpdateConfigs.create_subscriptions_config,
            STORED_SUBSCRIPTION,
            {"name": "Pro renamed"},
        )
        assert client.sent["productId"] == "OLD_PRODUCT"

    @pytest.mark.asyncio
    async def test_name_only_subscriber_update_keeps_the_organization(self):
        client = await _update(
            UpdateConfigs.create_customers_config,
            STORED_SUBSCRIBER,
            {"lastName": "Smith"},
            resource_type="subscriber",
        )
        assert client.sent["organizationIds"] == ["OLD_ORG"]

    @pytest.mark.asyncio
    async def test_name_only_source_update_keeps_tags_and_external_ids(self):
        client = await _update(
            UpdateConfigs.create_sources_config, STORED_SOURCE, {"name": "renamed"}
        )
        assert client.sent["tags"] == ["old-tag"]
        assert client.sent["externalId"] == "old-external"
        assert client.sent["externalUsagePlanId"] == "old-plan"
        assert "externalPlanId" not in client.sent


STORED_TEAM = {"id": "team_9", "name": "Platform", "metadata": "k=old"}

STORED_PRODUCT = {
    "id": "prod_1",
    "name": "Gold",
    "version": "1.0.0",
    "paymentSource": "INVOICE_ONLY_NO_PAYMENT",
    "plan": {"type": "SUBSCRIPTION", "tiers": [{"name": "t1", "up_to": None}]},
}


class TestMetadataReachesThePutBody:
    @pytest.mark.asyncio
    async def test_organization_metadata_the_caller_sends_reaches_the_put_body(self):
        client = await _update(
            UpdateConfigs.create_customers_config,
            {**STORED_ORGANIZATION, "metadata": "k=old"},
            {"metadata": "k=new"},
            resource_type="organization",
        )
        assert client.sent["metadata"] == "k=new"

    @pytest.mark.asyncio
    async def test_name_only_organization_update_keeps_the_stored_metadata(self):
        client = await _update(
            UpdateConfigs.create_customers_config,
            {**STORED_ORGANIZATION, "metadata": "k=old"},
            {"name": "renamed"},
            resource_type="organization",
        )
        assert client.sent["name"] == "renamed"
        assert "metadata" not in client.sent

    @pytest.mark.asyncio
    async def test_source_metadata_the_caller_sends_reaches_the_put_body(self):
        client = await _update(
            UpdateConfigs.create_sources_config,
            {**STORED_SOURCE, "metadata": "k=old"},
            {"metadata": "k=new, region=eu"},
        )
        assert client.sent["metadata"] == "k=new, region=eu"

    @pytest.mark.asyncio
    async def test_team_metadata_the_caller_sends_reaches_the_put_body(self):
        client = await _update(
            UpdateConfigs.create_customers_config,
            STORED_TEAM,
            {"metadata": "k=new"},
            resource_type="team",
        )
        assert client.sent["metadata"] == "k=new"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("malformed", ["plain", "a=b=c", {"k": "v"}, "=v"])
    async def test_malformed_metadata_is_refused_before_any_put(self, malformed):
        client, refusal = await _refused_update(
            UpdateConfigs.create_customers_config,
            {**STORED_ORGANIZATION, "metadata": "k=old"},
            {"metadata": malformed},
            resource_type="organization",
        )
        assert "name=value" in refusal.message
        assert client.get_count == 0
        assert client.put_bodies == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("metadata", "dropped_piece"),
        [
            (
                "k=new2,coding-assistant-filter-policy.team.providers="
                "ClaudeCode,ClaudeCowork,GeminiCli",
                "ClaudeCowork",
            ),
            (
                "callback=https://x.example/cb?a=b&c=d",
                "callback=https://x.example/cb?a=b&c=d",
            ),
            ("k=v,region=eu,west", "west"),
        ],
        ids=["comma-in-value", "equals-in-value", "trailing-piece"],
    )
    @pytest.mark.parametrize(
        ("config_factory", "stored", "config_kwargs"),
        [
            (UpdateConfigs.create_customers_config, STORED_TEAM, {"resource_type": "team"}),
            (UpdateConfigs.create_sources_config, {**STORED_SOURCE, "metadata": "k=old"}, {}),
        ],
        ids=["team", "source"],
    )
    async def test_metadata_whose_values_hold_commas_is_refused_naming_the_dropped_piece(
        self, config_factory, stored, config_kwargs, metadata, dropped_piece
    ):
        """BACK-4818: the platform answers 200 but drops these pieces, so the refusal says which."""
        client, refusal = await _refused_update(
            config_factory, stored, {"metadata": metadata}, **config_kwargs
        )
        assert f"'{dropped_piece}'" in refusal.message
        assert "a comma always ends a value" in refusal.message
        assert client.get_count == 0
        assert client.put_bodies == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "metadata",
        ["region=eu,", "region=eu, ,tier=gold", ",region=eu"],
        ids=["trailing-comma", "blank-piece", "leading-comma"],
    )
    async def test_an_empty_metadata_piece_is_refused_in_words_not_as_quotes(self, metadata):
        """BACK-4818: an empty piece used to be quoted as '' in the refusal."""
        client, refusal = await _refused_update(
            UpdateConfigs.create_customers_config,
            STORED_TEAM,
            {"metadata": metadata},
            resource_type="team",
        )
        assert "an empty piece next to a comma" in refusal.message
        assert "''" not in refusal.message
        assert client.get_count == 0
        assert client.put_bodies == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("config_factory", "stored", "config_kwargs"),
        [
            (
                UpdateConfigs.create_customers_config,
                STORED_SUBSCRIBER,
                {"resource_type": "subscriber"},
            ),
            (UpdateConfigs.create_products_config, STORED_PRODUCT, {}),
        ],
        ids=["subscriber", "product"],
    )
    async def test_metadata_on_a_resource_without_the_field_is_refused(
        self, config_factory, stored, config_kwargs
    ):
        client, refusal = await _refused_update(
            config_factory, stored, {"metadata": "k=v"}, **config_kwargs
        )
        assert "no metadata field" in refusal.message
        assert client.get_count == 0
        assert client.put_bodies == []


STORED_ELEMENT = {"id": "el_1", "name": "tokens", "type": "NUMBER"}


class TestProductUpdateKeepsItsTeam:
    """BACK-4818: an update sends the record's own team, never the server's configured one."""

    @pytest.mark.asyncio
    async def test_product_rename_sends_the_stored_team_not_the_configured_one(self):
        client = await _update(
            UpdateConfigs.create_products_config,
            {**STORED_PRODUCT, "team": _ref("team_prod")},
            {"name": "renamed"},
        )
        assert client.sent["teamId"] == "team_prod"
        assert "team" not in client.sent

    @pytest.mark.asyncio
    async def test_product_whose_stored_team_is_a_bare_id_sends_that_id(self):
        client = await _update(
            UpdateConfigs.create_products_config,
            {**STORED_PRODUCT, "team": "team_prod"},
            {"name": "renamed"},
        )
        assert client.sent["teamId"] == "team_prod"
        assert "team" not in client.sent

    @pytest.mark.asyncio
    async def test_product_without_a_stored_team_falls_back_to_the_configured_team(self):
        client = await _update(
            UpdateConfigs.create_products_config, STORED_PRODUCT, {"name": "renamed"}
        )
        assert client.sent["teamId"] == RecordingClient.team_id

    @pytest.mark.asyncio
    async def test_product_update_naming_a_team_id_sends_it(self):
        client = await _update(
            UpdateConfigs.create_products_config,
            {**STORED_PRODUCT, "team": _ref("team_prod")},
            {"teamId": "team_new"},
        )
        assert client.sent["teamId"] == "team_new"

    @pytest.mark.asyncio
    async def test_product_update_naming_a_team_sends_it_as_the_team_id(self):
        client = await _update(
            UpdateConfigs.create_products_config,
            {**STORED_PRODUCT, "team": _ref("team_prod")},
            {"team": "team_new"},
        )
        assert client.sent["teamId"] == "team_new"
        assert "team" not in client.sent

    @pytest.mark.asyncio
    async def test_metering_element_rename_sends_the_stored_team(self):
        client = await _update(
            UpdateConfigs.create_metering_elements_config,
            {**STORED_ELEMENT, "team": _ref("team_el")},
            {"name": "renamed"},
        )
        assert client.sent["teamId"] == "team_el"
        assert "team" not in client.sent

    @pytest.mark.asyncio
    async def test_metering_element_without_a_stored_team_sends_the_configured_team(self):
        client = await _update(
            UpdateConfigs.create_metering_elements_config,
            {**STORED_ELEMENT, "team": None},
            {"name": "renamed"},
        )
        # The recording client's update_* bypasses ReveniumClient, so run the real
        # body preparation that update_metering_element_definition applies before its PUT.
        body = ReveniumClient.prepare_metering_element_update_body(client, client.sent)
        assert body["teamId"] == "team_1"


STORED_NAMELESS_SUBSCRIBER = {
    "id": "subr_2",
    "email": "nameless@example.com",
    "firstName": None,
    "lastName": None,
    "organizations": [_ref("org_1")],
}


def _assert_no_invented_name(sent: Dict[str, Any]) -> None:
    assert "firstName" in sent and "lastName" in sent
    assert "Unknown" not in sent.values()
    assert "User" not in sent.values()


class TestSubscriberNamesAreNeverInvented:
    @pytest.mark.asyncio
    async def test_phone_only_update_of_a_nameless_subscriber_sends_no_invented_name(self):
        client = await _update(
            UpdateConfigs.create_customers_config,
            STORED_NAMELESS_SUBSCRIBER,
            {"phoneNumber": "5550100"},
            resource_type="subscriber",
        )
        _assert_no_invented_name(client.sent)
        assert client.sent["firstName"] is None
        assert client.sent["lastName"] is None
        assert client.sent["phoneNumber"] == "5550100"

    @pytest.mark.asyncio
    async def test_subscriber_name_the_caller_sends_reaches_the_put_body(self):
        client = await _update(
            UpdateConfigs.create_customers_config,
            STORED_NAMELESS_SUBSCRIBER,
            {"firstName": "Pat"},
            resource_type="subscriber",
        )
        _assert_no_invented_name(client.sent)
        assert client.sent["firstName"] == "Pat"
        assert client.sent["lastName"] is None

    @pytest.mark.asyncio
    async def test_phone_only_update_keeps_a_missing_last_name_missing(self):
        client = await _update(
            UpdateConfigs.create_customers_config,
            {**STORED_NAMELESS_SUBSCRIBER, "firstName": "Pat"},
            {"phoneNumber": "5550100"},
            resource_type="subscriber",
        )
        _assert_no_invented_name(client.sent)
        assert client.sent["firstName"] == "Pat"
        assert client.sent["lastName"] is None


def _without_configured_owner(monkeypatch) -> None:
    from src.revenium_mcp_server import config_store

    monkeypatch.setattr(config_store, "get_config_value", lambda name, default=None: default)


class TestSourceUpdateFollowsTheContract:
    @pytest.mark.asyncio
    async def test_rename_of_a_source_without_description_is_sent(self):
        client = await _update(
            UpdateConfigs.create_sources_config,
            {**STORED_SOURCE, "description": None},
            {"name": "renamed"},
        )
        assert client.sent["name"] == "renamed"
        assert client.sent["description"] is None

    @pytest.mark.asyncio
    async def test_source_update_sends_no_value_the_record_and_caller_lack(self):
        unset = {"assetUsageIdentifier": None, "code": None, "planId": None, "sourceType": None}
        client = await _update(
            UpdateConfigs.create_sources_config,
            {**STORED_SOURCE, **unset},
            {"name": "renamed"},
        )
        for field in unset:
            assert client.sent.get(field) is None, field

    @pytest.mark.asyncio
    async def test_source_update_keeps_the_stored_asset_usage_identifier(self):
        client = await _update(
            UpdateConfigs.create_sources_config,
            {**STORED_SOURCE, "assetUsageIdentifier": "CUSTOM_ID"},
            {"name": "renamed"},
        )
        assert client.sent["assetUsageIdentifier"] == "CUSTOM_ID"

    @pytest.mark.asyncio
    async def test_source_rename_carries_owner_and_team(self, monkeypatch):
        _without_configured_owner(monkeypatch)
        client = await _update(
            UpdateConfigs.create_sources_config,
            {**STORED_SOURCE, "team": _ref("team_src")},
            {"name": "renamed"},
        )
        assert client.sent["ownerId"] == "owner_1"
        assert client.sent["teamId"] == "team_src"

    @pytest.mark.asyncio
    async def test_source_update_without_owner_is_refused_naming_owner_id(self, monkeypatch):
        _without_configured_owner(monkeypatch)
        stored = {key: value for key, value in STORED_SOURCE.items() if key != "owner"}
        client, refusal = await _refused_update(
            UpdateConfigs.create_sources_config, stored, {"name": "renamed"}
        )
        assert "ownerId" in refusal.message
        assert client.put_bodies == []
