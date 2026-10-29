"""BACK-5126: a product update refuses a non-semver version the way create does.

The audit previewed manage_products update with version "1.0" as a success,
then the live update came back from the platform as HTTP 400 "Version must be
semantic". Create already refused that version locally in both modes.
"""

import copy
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.api_field_mapper import APIFieldMapper
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.tools_decomposed.product_management import (
    ProductManagement,
)

SEMVER_REFUSAL = (
    "Version must be semantic (MAJOR.MINOR.PATCH or MAJOR.MINOR.PATCH-prerelease)"
)

STORED_PRODUCT: Dict[str, Any] = {
    "id": "3ByoYab",
    "name": "mcp-test-prod-e7fb83d2-updated",
    "description": "audit product",
    "version": "1.0.0",
    "paymentSource": "INVOICE_ONLY_NO_PAYMENT",
    "tags": ["mcp-test"],
    "plan": {
        "type": "SUBSCRIPTION",
        "name": "p",
        "currency": "USD",
        "period": "MONTH",
        "tiers": [{"name": "t", "upTo": None, "unitAmount": 0.01}],
    },
}


def _management():
    client = MagicMock()
    client.team_id = "JMwaj9y"
    client.get_product_by_id = AsyncMock(return_value=copy.deepcopy(STORED_PRODUCT))
    client.update_product = AsyncMock(
        side_effect=lambda product_id, body: {**body, "id": product_id}
    )
    client.create_product = AsyncMock(return_value={"id": "p_new"})
    client.prepare_product_update_body = APIFieldMapper.map_product_fields
    management = ProductManagement()
    management.get_client = AsyncMock(return_value=client)
    return management, client


async def _call(action: str, arguments: Dict[str, Any]):
    management, client = _management()
    with patch(
        "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
        return_value=None,
    ):
        result = await management.handle_action(action, arguments)
    return result[0].text, client


async def _refusal(action: str, arguments: Dict[str, Any]):
    management, client = _management()
    with (
        patch(
            "src.revenium_mcp_server.tools_decomposed.product_management.get_config_value",
            return_value=None,
        ),
        pytest.raises(ToolError) as refused,
    ):
        await management.handle_action(action, arguments)
    return str(refused.value.message), client


def _update(version: Any, *, dry_run: bool) -> Dict[str, Any]:
    return {
        "product_id": "3ByoYab",
        "product_data": {"version": version},
        "dry_run": dry_run,
    }


def _version_line(message: str) -> str:
    return next(line for line in message.splitlines() if "**version**" in line)


class TestNonSemverVersionIsRefusedOnUpdate:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("dry_run", [True, False], ids=["dry_run", "live"])
    async def test_the_update_refuses_it_before_any_platform_call(self, dry_run):
        message, client = await _refusal("update", _update("1.0", dry_run=dry_run))

        assert SEMVER_REFUSAL in message
        client.get_product_by_id.assert_not_awaited()
        client.update_product.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_preview_and_the_live_update_refuse_with_the_same_text(self):
        preview, _ = await _refusal("update", _update("1.0", dry_run=True))
        live, _ = await _refusal("update", _update("1.0", dry_run=False))

        assert preview == live

    @pytest.mark.asyncio
    @pytest.mark.parametrize("version", [1.0, 2], ids=["float", "int"])
    async def test_a_numeric_version_is_refused_too(self, version):
        message, client = await _refusal("update", _update(version, dry_run=True))

        assert SEMVER_REFUSAL in message
        client.get_product_by_id.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_hints_do_not_name_a_field_the_caller_may_not_have_sent(self):
        management, _ = _management()
        with pytest.raises(ToolError) as refused:
            await management.handle_action("update", _update("1.0", dry_run=True))

        hints = " ".join(refused.value.suggestions)
        assert hints
        assert "version" not in hints.lower()

    @pytest.mark.asyncio
    async def test_the_version_line_reads_as_it_does_on_create(self):
        created = {**STORED_PRODUCT, "version": "1.0"}
        create_message, _ = await _refusal(
            "create", {"product_data": created, "dry_run": True}
        )
        update_message, _ = await _refusal("update", _update("1.0", dry_run=True))

        assert _version_line(update_message) == _version_line(create_message)


class TestSemverVersionStillUpdates:
    @pytest.mark.asyncio
    async def test_the_preview_shows_the_new_version_in_the_body(self):
        text, client = await _call("update", _update("2.1.0", dry_run=True))

        assert text.startswith("DRY RUN MODE - Product Update")
        assert '"version": "2.1.0"' in text
        client.update_product.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_live_update_sends_the_new_version(self):
        _, client = await _call("update", _update("2.1.0-beta", dry_run=False))

        client.update_product.assert_awaited_once()
        assert client.update_product.await_args.args[1]["version"] == "2.1.0-beta"

    @pytest.mark.asyncio
    async def test_an_update_without_a_version_is_not_checked_for_one(self):
        text, _ = await _call(
            "update",
            {
                "product_id": "3ByoYab",
                "product_data": {"description": "d2"},
                "dry_run": True,
            },
        )

        assert '"description": "d2"' in text
