"""Payload-shape guards for the resource update endpoints.

The upstream write DTOs on the update endpoints accept the full resource, so a
full-replacement PUT fed a PARTIAL body would clear every field the caller did
not mention. Each test here fixes the merge contract for one updater: it mocks
the client's GET to return a current resource carrying an unmentioned writable
field (a sentinel), calls the tool's update action with a small partial change,
and asserts the outgoing body preserves the sentinel while the caller's change
still wins. The single PATCH endpoint (cost controls) is a genuine partial
verb, so its guard asserts the opposite: the partial body is sent as-is and no
GET is issued to inflate it into a full PUT-style body.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.revenium_mcp_server.tools_decomposed.agent_management import AgentManager
from src.revenium_mcp_server.tools_decomposed.cost_controls_management import (
    CostControlsManager,
)
from src.revenium_mcp_server.tools_decomposed.source_management import SourceManager
from src.revenium_mcp_server.tools_decomposed.subscription_management import (
    SubscriptionManager,
)
from src.revenium_mcp_server.tools_decomposed.customer_management import (
    UserManager,
    SubscriberManager,
)
from src.revenium_mcp_server.tools_decomposed.metering_elements_management import (
    MeteringElementsManager,
)
from src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management import (
    SubscriberCredentialsManagement,
)
from src.revenium_mcp_server.alerts.anomaly_manager import AnomalyManager


def _base_client() -> MagicMock:
    """A mock client with a stable team id for config defaults."""
    client = MagicMock()
    client.team_id = "team_1"
    return client


# ---------------------------------------------------------------------------
# PUT /agents/{id} -> AgentManager.update_agent
# Merges over _WRITE_VIEW_FIELDS; server-managed fields are never echoed back.
# ---------------------------------------------------------------------------
class TestAgentUpdatePayload:
    @pytest.mark.asyncio
    async def test_partial_update_preserves_unmentioned_write_view_field(self):
        client = _base_client()
        client.get_agent_by_id = AsyncMock(
            return_value={
                "id": "agt_1",
                "telemetryKey": "keep-key",
                "displayName": "Old Name",
                "ownerId": "owner_keep",
                "created": "2020-01-01",
            }
        )
        client.update_agent = AsyncMock(return_value={"id": "agt_1"})
        manager = AgentManager(client)

        await manager.update_agent(
            {"agent_id": "agt_1", "agent_data": {"displayName": "New Name"}}
        )

        sent = client.update_agent.call_args[0][1]
        # Unmentioned writable fields survive the full-replacement PUT.
        assert sent["ownerId"] == "owner_keep"
        assert sent["telemetryKey"] == "keep-key"
        # Caller change wins.
        assert sent["displayName"] == "New Name"
        # Server-managed fields are not echoed back.
        assert "id" not in sent
        assert "created" not in sent


# ---------------------------------------------------------------------------
# PATCH /ai/cost-controls/{id} -> CostControlsManager.update_cost_control
# Genuine partial verb: the body is passed through as-is, never inflated.
# ---------------------------------------------------------------------------
class TestCostControlUpdatePayload:
    @pytest.mark.asyncio
    async def test_patch_sends_partial_body_and_does_not_read_current(self):
        client = _base_client()
        client.get_cost_control_by_id = AsyncMock()
        client.update_cost_control = AsyncMock(return_value={"id": "cc_1"})
        manager = CostControlsManager(client)

        await manager.update_cost_control(
            {"control_id": "cc_1", "control_data": {"hardLimit": 2000}}
        )

        sent = client.update_cost_control.call_args[0][1]
        # PATCH carries only the caller's fields, not a merged full resource.
        assert sent == {"hardLimit": 2000}
        # No fetch-and-merge: the partial body is not inflated into a full PUT.
        client.get_cost_control_by_id.assert_not_called()


# ---------------------------------------------------------------------------
# PUT /credentials/{id} -> SubscriberCredentialsManagement._update_credential
# Custom read-modify-write; server-managed fields stripped from the payload.
# ---------------------------------------------------------------------------
class TestCredentialUpdatePayload:
    @pytest.mark.asyncio
    async def test_partial_update_preserves_unmentioned_writable_field(self):
        client = _base_client()
        client.get_credential_by_id = AsyncMock(
            return_value={
                "id": "cred_1",
                "label": "Old Label",
                "name": "Old Label",
                "externalId": "external-keep",
                "externalSecret": "secret-keep",
                "subscriberId": "sub_1",
                "organizationId": "org_1",
                "_links": {"self": "..."},
                "created": "2020-01-01",
            }
        )
        client.update_credential = AsyncMock(return_value={"id": "cred_1"})
        tool = SubscriberCredentialsManagement(client=client)

        await tool._update_credential(
            {"credential_id": "cred_1", "credential_data": {"label": "New Label"}},
            client=client,
        )

        sent = client.update_credential.call_args[0][1]
        # Unmentioned writable field survives the full-replacement PUT.
        assert sent["externalId"] == "external-keep"
        assert sent["externalSecret"] == "secret-keep"
        # Caller change wins (and name mirrors label).
        assert sent["label"] == "New Label"
        assert sent["name"] == "New Label"
        # Server-managed fields are not echoed back.
        assert "id" not in sent
        assert "_links" not in sent
        assert "created" not in sent


# ---------------------------------------------------------------------------
# PUT /metering-element-definitions/{id} -> MeteringElementsManager.update_element
# PartialUpdateHandler read-modify-write.
# ---------------------------------------------------------------------------
class TestMeteringElementUpdatePayload:
    @pytest.mark.asyncio
    async def test_partial_update_preserves_unmentioned_writable_field(self):
        client = _base_client()
        client.get_metering_element_definition_by_id = AsyncMock(
            return_value={
                "id": "elem_1",
                "name": "Old Name",
                "description": "keep-description",
                "type": "NUMBER",
                "created": "2020-01-01",
            }
        )
        client.update_metering_element_definition = AsyncMock(
            return_value={"id": "elem_1"}
        )
        manager = MeteringElementsManager(client=client)

        await manager.update_element(
            client, {"element_id": "elem_1", "element_data": {"name": "New Name"}}
        )

        sent = client.update_metering_element_definition.call_args[0][1]
        assert sent["description"] == "keep-description"
        assert sent["name"] == "New Name"
        assert "created" not in sent


# ---------------------------------------------------------------------------
# PUT /sources/{id} -> SourceManager.update_source
# PartialUpdateHandler read-modify-write.
# ---------------------------------------------------------------------------
class TestSourceUpdatePayload:
    @pytest.mark.asyncio
    async def test_partial_update_preserves_unmentioned_writable_field(self):
        client = _base_client()
        client.get_source_by_id = AsyncMock(
            return_value={
                "id": "src_1",
                "name": "Old Name",
                "description": "keep-description",
                "version": "1.0.0",
                "type": "API",
                "created": "2020-01-01",
            }
        )
        client.update_source = AsyncMock(return_value={"id": "src_1"})
        manager = SourceManager(client)

        await manager.update_source(
            {"source_id": "src_1", "source_data": {"name": "New Name"}}
        )

        sent = client.update_source.call_args[0][1]
        assert sent["description"] == "keep-description"
        assert sent["name"] == "New Name"
        assert "created" not in sent


# ---------------------------------------------------------------------------
# PUT /subscribers/{id} -> SubscriberManager.update_subscriber
# PartialUpdateHandler read-modify-write.
# ---------------------------------------------------------------------------
class TestSubscriberUpdatePayload:
    @pytest.mark.asyncio
    async def test_partial_update_preserves_unmentioned_writable_field(self):
        client = _base_client()
        client.get_subscriber_by_id = AsyncMock(
            return_value={
                "id": "sub_1",
                "email": "person@example.com",
                "firstName": "keep-first",
                "lastName": "Old Last",
                "created": "2020-01-01",
            }
        )
        client.update_subscriber = AsyncMock(return_value={"id": "sub_1"})
        manager = SubscriberManager(client)

        await manager.update_subscriber(
            {"subscriber_id": "sub_1", "subscriber_data": {"lastName": "New Last"}}
        )

        sent = client.update_subscriber.call_args[0][1]
        assert sent["firstName"] == "keep-first"
        assert sent["lastName"] == "New Last"
        assert "created" not in sent


# ---------------------------------------------------------------------------
# PUT /subscriptions/{id} -> SubscriptionManager.update_subscription
# PartialUpdateHandler read-modify-write.
# ---------------------------------------------------------------------------
class TestSubscriptionUpdatePayload:
    @pytest.mark.asyncio
    async def test_partial_update_preserves_unmentioned_writable_field(self):
        client = _base_client()
        client.get_subscription_by_id = AsyncMock(
            return_value={
                "id": "subn_1",
                "name": "Old Name",
                "description": "keep-description",
                "created": "2020-01-01",
            }
        )
        client.update_subscription = AsyncMock(return_value={"id": "subn_1"})
        manager = SubscriptionManager(client)

        await manager.update_subscription(
            {"subscription_id": "subn_1", "subscription_data": {"name": "New Name"}}
        )

        sent = client.update_subscription.call_args[0][1]
        assert sent["description"] == "keep-description"
        assert sent["name"] == "New Name"
        assert "created" not in sent


# ---------------------------------------------------------------------------
# PUT /users/{id} -> UserManager.update_user
# PartialUpdateHandler read-modify-write.
# ---------------------------------------------------------------------------
class TestUserUpdatePayload:
    @pytest.mark.asyncio
    async def test_partial_update_preserves_unmentioned_writable_field(self):
        client = _base_client()
        client.get_user_by_id = AsyncMock(
            return_value={
                "id": "user_1",
                "email": "person@example.com",
                "firstName": "Old First",
                "lastName": "keep-last",
                "created": "2020-01-01",
            }
        )
        client.update_user = AsyncMock(return_value={"id": "user_1"})
        manager = UserManager(client)

        await manager.update_user(
            {"user_id": "user_1", "user_data": {"firstName": "New First"}}
        )

        sent = client.update_user.call_args[0][1]
        assert sent["lastName"] == "keep-last"
        assert sent["firstName"] == "New First"
        assert "created" not in sent


# ---------------------------------------------------------------------------
# PUT /sources/ai/anomaly/{id} -> AnomalyManager.update_anomaly
# Read-modify-write: the current resource is fetched and merged under the
# caller's fields before the full-replacement PUT.
# ---------------------------------------------------------------------------
class TestAnomalyUpdatePayload:
    @pytest.mark.asyncio
    async def test_partial_update_preserves_unmentioned_writable_field(self):
        client = MagicMock()
        client.get_anomaly_by_id = AsyncMock(
            return_value={
                "id": "anom_1",
                "name": "Old Name",
                "threshold": 100,
                "enabled": True,
            }
        )
        client.update_anomaly = AsyncMock(return_value={"id": "anom_1", "name": "New Name"})
        manager = AnomalyManager()

        await manager.update_anomaly(client, "anom_1", {"name": "New Name"})

        sent = client.update_anomaly.call_args[0][1]
        assert sent["threshold"] == 100
        assert sent["enabled"] is True
        assert sent["name"] == "New Name"
