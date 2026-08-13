"""Delete-acknowledgement envelope relaxation tolerance.

Backend 2.19.0-SNAPSHOT relaxed the DELETE acknowledgement envelope: the
fields ``created``, ``id``, ``message`` and ``resourceType`` became optional on
the DELETE responses for every resource the MCP wraps. These tests feed a
fully-empty ack (``{}``, all relaxed fields absent) through each delete
handler's rendering path and pin the house-standard behavior: a structured
success render keyed off the INPUT id, no KeyError/TypeError from a
now-absent field, and no literal ``"None"`` presented as a real value.

Every handler here renders the confirmation from the request-supplied id and
treats the ack as opaque (ignored, or passed through as JSON ``data``), so
these are pins (green from the outset), not fix-provers.

The jobs tool (``manage_jobs``) exposes no delete or bulk-delete action, so the
relaxed bulk-DELETE ack (deletedCount/deletedIds/requestedCount/message) has no
MCP consumer and is intentionally not exercised here.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.types import TextContent

from src.revenium_mcp_server.tools_decomposed.agent_management import AgentManagement
from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement
from src.revenium_mcp_server.tools_decomposed.cost_controls_management import (
    CostControlsManagement,
)
from src.revenium_mcp_server.tools_decomposed.customer_management import CustomerManagement
from src.revenium_mcp_server.tools_decomposed.metering_elements_management import (
    MeteringElementsManagement,
)
from src.revenium_mcp_server.tools_decomposed.product_management import ProductManagement
from src.revenium_mcp_server.tools_decomposed.source_management import SourceManagement
from src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management import (
    SubscriberCredentialsManagement,
)
from src.revenium_mcp_server.tools_decomposed.subscription_management import (
    SubscriptionManagement,
)
from src.revenium_mcp_server.tools_decomposed.tool_management import ToolManagement


# The empty ack: every field the backend relaxed from required to optional is
# absent. A tolerant reader must never index into it.
RELAXED_ACK: dict = {}


def _rendered_text(result) -> str:
    """Join the text of every TextContent block the handler returned."""
    assert isinstance(result, list) and result, "handler returned no content"
    parts = []
    for block in result:
        assert isinstance(block, TextContent), f"non-text block: {block!r}"
        parts.append(block.text)
    return "\n".join(parts)


def _assert_tolerant_success(result, *, marker: str) -> str:
    """Pin the three house-standard invariants for a relaxed-ack delete render."""
    text = _rendered_text(result)
    assert marker.lower() in text.lower(), (
        f"expected success marker {marker!r} in render, got:\n{text}"
    )
    # A relaxed field that got hard-read and stringified would surface here.
    assert "None" not in text, f"literal 'None' leaked into render:\n{text}"
    return text


def _tool(cls):
    """Instantiate a top-level tool with get_client patched to a mock client."""
    tool = cls()
    client = MagicMock()
    client.team_id = "team_test"
    tool.get_client = AsyncMock(return_value=client)
    return tool, client


@pytest.mark.asyncio
async def test_product_delete_tolerates_empty_ack():
    tool, client = _tool(ProductManagement)
    client.delete_product = AsyncMock(return_value=RELAXED_ACK)

    result = await tool.handle_action("delete", {"product_id": "prod_123"})

    text = _assert_tolerant_success(result, marker="deleted successfully")
    assert "prod_123" in text


@pytest.mark.asyncio
async def test_source_delete_tolerates_empty_ack():
    tool, client = _tool(SourceManagement)
    client.delete_source = AsyncMock(return_value=RELAXED_ACK)

    result = await tool.handle_action("delete", {"source_id": "src_123"})

    text = _assert_tolerant_success(result, marker="deleted successfully")
    assert "src_123" in text


@pytest.mark.asyncio
async def test_customer_delete_user_tolerates_empty_ack():
    tool, client = _tool(CustomerManagement)
    client.delete_user = AsyncMock(return_value=RELAXED_ACK)

    result = await tool.handle_action(
        "delete", {"resource_type": "users", "user_id": "user_123"}
    )

    text = _assert_tolerant_success(result, marker="deleted successfully")
    assert "user_123" in text


@pytest.mark.asyncio
async def test_customer_delete_subscriber_tolerates_empty_ack():
    tool, client = _tool(CustomerManagement)
    client.delete_subscriber = AsyncMock(return_value=RELAXED_ACK)

    result = await tool.handle_action(
        "delete", {"resource_type": "subscribers", "subscriber_id": "sub_123"}
    )

    text = _assert_tolerant_success(result, marker="deleted successfully")
    assert "sub_123" in text


@pytest.mark.asyncio
async def test_customer_delete_organization_tolerates_empty_ack():
    tool, client = _tool(CustomerManagement)
    client.delete_organization = AsyncMock(return_value=RELAXED_ACK)

    result = await tool.handle_action(
        "delete", {"resource_type": "organizations", "organization_id": "org_123"}
    )

    text = _assert_tolerant_success(result, marker="deleted successfully")
    assert "org_123" in text


@pytest.mark.asyncio
async def test_customer_delete_team_tolerates_empty_ack():
    tool, client = _tool(CustomerManagement)
    client.delete_team = AsyncMock(return_value=RELAXED_ACK)

    result = await tool.handle_action(
        "delete", {"resource_type": "teams", "team_id": "team_123"}
    )

    text = _assert_tolerant_success(result, marker="deleted successfully")
    assert "team_123" in text


@pytest.mark.asyncio
async def test_subscription_delete_tolerates_empty_ack():
    tool, client = _tool(SubscriptionManagement)
    # delete_subscription routes through the DELETE-based cancel endpoint.
    client.cancel_subscription = AsyncMock(return_value=RELAXED_ACK)

    result = await tool.handle_action("delete", {"subscription_id": "sub_123"})

    text = _assert_tolerant_success(result, marker="deleted successfully")
    assert "sub_123" in text


@pytest.mark.asyncio
async def test_subscriber_credential_delete_tolerates_empty_ack():
    tool, client = _tool(SubscriberCredentialsManagement)
    client.delete_credential = AsyncMock(return_value=RELAXED_ACK)

    result = await tool.handle_action("delete", {"credential_id": "cred_123"})

    text = _assert_tolerant_success(result, marker="completed successfully")
    assert "cred_123" in text


@pytest.mark.asyncio
async def test_metering_element_delete_tolerates_empty_ack():
    tool, client = _tool(MeteringElementsManagement)
    client.delete_metering_element_definition = AsyncMock(return_value=RELAXED_ACK)

    result = await tool.handle_action("delete", {"element_id": "elem_123"})

    text = _assert_tolerant_success(result, marker="deleted successfully")
    assert "elem_123" in text


@pytest.mark.asyncio
async def test_agent_delete_tolerates_empty_ack():
    tool, client = _tool(AgentManagement)
    client.delete_agent = AsyncMock(return_value=RELAXED_ACK)

    result = await tool.handle_action("delete", {"agent_id": "agt_123"})

    text = _assert_tolerant_success(result, marker="Agent agt_123 deleted")
    assert "agt_123" in text


@pytest.mark.asyncio
async def test_cost_control_delete_tolerates_empty_ack():
    tool, client = _tool(CostControlsManagement)
    client.delete_cost_control = AsyncMock(return_value=RELAXED_ACK)

    result = await tool.handle_action("delete", {"control_id": "cc_123"})

    text = _assert_tolerant_success(result, marker="Cost control cc_123 deleted")
    assert "cc_123" in text


@pytest.mark.asyncio
async def test_anomaly_delete_tolerates_empty_ack():
    tool, client = _tool(AlertManagement)
    client.delete_anomaly = AsyncMock(return_value=RELAXED_ACK)

    result = await tool.handle_action(
        "delete", {"resource_type": "anomalies", "anomaly_id": "anom_123"}
    )

    text = _assert_tolerant_success(result, marker="Anomaly Deleted")
    assert "anom_123" in text


@pytest.mark.asyncio
async def test_tool_delete_tolerates_empty_ack():
    tool, client = _tool(ToolManagement)
    client.delete_tool = AsyncMock(return_value=RELAXED_ACK)

    result = await tool.handle_action("delete", {"tool_id": "tool_123"})

    text = _assert_tolerant_success(result, marker="Tool tool_123 deleted")
    assert "tool_123" in text
