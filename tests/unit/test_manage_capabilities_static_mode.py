"""get_capabilities on a server where UCM never starts (the multi-customer modes).

Each test uses a fresh, uninitialized integration service, which is the state the
hosted server is in, and sets AUTH_MODE to pick the mode under test.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.capability_manager.discovery import CapabilityDiscovery
from src.revenium_mcp_server.capability_manager.factory import ucm_verdict
from src.revenium_mcp_server.capability_manager.integration_service import (
    UCMIntegrationService,
)
from src.revenium_mcp_server.capability_manager.static_capabilities import (
    STATIC_CAPABILITIES_NOTE,
    SUPPORTED_RESOURCE_TYPES,
)
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.plan_contract import platform_plan_currencies
from src.revenium_mcp_server.tools_decomposed.manage_capabilities import ManageCapabilities

SERVICE_PATH = "src.revenium_mcp_server.tools_decomposed.manage_capabilities.ucm_integration_service"
CONNECTIVITY_WORDING = ("connectivity", "not initialized", "Try again")


def _rendered(refusal: ToolError) -> str:
    return " ".join([refusal.message, *refusal.suggestions, str(refusal.context)])


def _running_ucm_service() -> UCMIntegrationService:
    service = UCMIntegrationService()
    service._initialized = True
    service.ucm = MagicMock()
    service.ucm.supported_resource_types = {"products", "analytics"}
    service.ucm.get_capabilities = AsyncMock(return_value={"currencies": ["USD"]})
    return service


def _tool_without_ucm(monkeypatch, auth_mode: str):
    monkeypatch.setenv("AUTH_MODE", auth_mode)
    with patch(SERVICE_PATH, UCMIntegrationService()):
        yield ManageCapabilities()


@pytest.fixture
def clerk_mode(monkeypatch):
    yield from _tool_without_ucm(monkeypatch, "clerk")


@pytest.fixture(params=["clerk", "api_key"])
def multi_customer_mode(monkeypatch, request):
    yield from _tool_without_ucm(monkeypatch, request.param)


@pytest.fixture
def env_mode_without_ucm(monkeypatch):
    yield from _tool_without_ucm(monkeypatch, "env")


class TestClerkModeCapabilityRead:
    @pytest.mark.asyncio
    async def test_products_answer_from_the_static_table_with_a_note(self, multi_customer_mode):
        result = await multi_customer_mode.handle_action(
            "get_capabilities", {"resource_type": "products"}
        )

        text = result[0].text
        assert STATIC_CAPABILITIES_NOTE in text
        assert '"plan_types"' in text
        for currency in platform_plan_currencies():
            assert f'"{currency}"' in text
        for wording in CONNECTIVITY_WORDING:
            assert wording not in text

    @pytest.mark.asyncio
    async def test_alerts_answer_without_touching_the_platform(self, clerk_mode):
        result = await clerk_mode.handle_action("get_capabilities", {"resource_type": "alerts"})

        assert '"alert_types"' in result[0].text

    @pytest.mark.asyncio
    async def test_overview_lists_every_static_resource_type(self, clerk_mode):
        result = await clerk_mode.handle_action("get_capabilities", {})

        assert "**products**" in result[0].text
        assert "**metering_elements**" in result[0].text

    @pytest.mark.asyncio
    async def test_get_capability_for_a_type_uses_the_static_table(self, clerk_mode):
        result = await clerk_mode.handle_action("get_capability", {"resource_type": "sources"})

        assert STATIC_CAPABILITIES_NOTE in result[0].text
        assert '"source_types"' in result[0].text

    @pytest.mark.asyncio
    async def test_get_capability_by_name_returns_the_static_values(self, clerk_mode):
        result = await clerk_mode.handle_action(
            "get_capability", {"resource_type": "products", "capability_name": "currencies"}
        )

        text = result[0].text
        assert STATIC_CAPABILITIES_NOTE in text
        assert "None" not in text
        for currency in platform_plan_currencies():
            assert f'"{currency}"' in text


class TestClerkModeVerifyCapability:
    @pytest.mark.asyncio
    async def test_a_listed_currency_is_valid(self, clerk_mode):
        currency = next(iter(platform_plan_currencies()))

        result = await clerk_mode.handle_action(
            "verify_capability",
            {"resource_type": "products", "capability_name": "currencies", "value": currency},
        )

        text = result[0].text
        assert STATIC_CAPABILITIES_NOTE in text
        assert "Valid" in text
        assert "Invalid" not in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("value", "verdict"), [("TOTAL_COST", "Valid"), ("NOT_A_METRIC", "Invalid")])
    async def test_alert_metrics_are_checked_against_the_listed_metrics(
        self, clerk_mode, value, verdict
    ):
        result = await clerk_mode.handle_action(
            "verify_capability",
            {"resource_type": "alerts", "capability_name": "metrics", "value": value},
        )

        assert f"**Status**: {'✅' if verdict == 'Valid' else '❌'} {verdict}" in result[0].text

    @pytest.mark.asyncio
    async def test_a_capability_without_listed_values_is_refused_not_accepted(self, clerk_mode):
        with pytest.raises(ToolError) as refused:
            await clerk_mode.handle_action(
                "verify_capability",
                {"resource_type": "products", "capability_name": "validation_rules", "value": "x"},
            )

        assert "not in the static capability set for products" in refused.value.message

    @pytest.mark.asyncio
    async def test_an_unlisted_currency_is_invalid(self, clerk_mode):
        result = await clerk_mode.handle_action(
            "verify_capability",
            {"resource_type": "products", "capability_name": "currencies", "value": "XYZ"},
        )

        assert "Invalid" in result[0].text

    @pytest.mark.asyncio
    async def test_a_capability_missing_from_the_table_is_refused_with_the_known_names(
        self, clerk_mode
    ):
        with pytest.raises(ToolError) as refused:
            await clerk_mode.handle_action(
                "verify_capability",
                {"resource_type": "products", "capability_name": "colours", "value": "red"},
            )

        rendered = _rendered(refused.value)
        assert "Capability 'colours' is not in the static capability set for products" in rendered
        assert "currencies" in rendered
        assert refused.value.field == "capability_name"
        for wording in CONNECTIVITY_WORDING:
            assert wording not in rendered


READ_ACTIONS = ["get_capabilities", "get_capability", "verify_capability"]


class TestUnsupportedResourceType:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", READ_ACTIONS)
    async def test_multi_customer_modes_refuse_bogus_type_as_unsupported(
        self, multi_customer_mode, action
    ):
        await self._assert_refused_as_unsupported(multi_customer_mode, action)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", READ_ACTIONS)
    async def test_env_mode_without_ucm_refuses_bogus_type_as_unsupported(
        self, env_mode_without_ucm, action
    ):
        await self._assert_refused_as_unsupported(env_mode_without_ucm, action)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", READ_ACTIONS)
    async def test_a_running_ucm_refuses_bogus_type_before_it_is_called(
        self, monkeypatch, action
    ):
        monkeypatch.setenv("AUTH_MODE", "env")
        service = _running_ucm_service()
        with patch(SERVICE_PATH, service):
            await self._assert_refused_as_unsupported(ManageCapabilities(), action)
        service.ucm.get_capabilities.assert_not_awaited()

    @staticmethod
    async def _assert_refused_as_unsupported(tool: ManageCapabilities, action: str) -> None:
        arguments = {"resource_type": "bogus_type", "capability_name": "currencies", "value": "USD"}

        with pytest.raises(ToolError) as refused:
            await tool.handle_action(action, arguments)

        rendered = _rendered(refused.value)
        assert refused.value.message == "Unsupported resource type: bogus_type"
        assert refused.value.field == "resource_type"
        for wording in CONNECTIVITY_WORDING:
            assert wording not in rendered


class TestApiKeyModeWithUcmIsUnchanged:
    @pytest.mark.asyncio
    async def test_reads_come_from_ucm_without_the_static_note(self, monkeypatch):
        monkeypatch.setenv("AUTH_MODE", "env")
        service = _running_ucm_service()
        with patch(SERVICE_PATH, service):
            result = await ManageCapabilities().handle_action(
                "get_capabilities", {"resource_type": "products"}
            )

        service.ucm.get_capabilities.assert_awaited_once_with("products")
        assert STATIC_CAPABILITIES_NOTE not in result[0].text

    @pytest.mark.asyncio
    async def test_a_type_ucm_registered_at_runtime_is_accepted(self, monkeypatch):
        monkeypatch.setenv("AUTH_MODE", "env")
        service = _running_ucm_service()
        with patch(SERVICE_PATH, service):
            await ManageCapabilities().handle_action(
                "get_capabilities", {"resource_type": "analytics"}
            )

        service.ucm.get_capabilities.assert_awaited_once_with("analytics")


class TestStaticTable:
    @pytest.mark.asyncio
    async def test_subscriptions_and_metering_make_no_platform_call_and_carry_no_error(self):
        discovery = CapabilityDiscovery()

        subscriptions = await discovery.static_capabilities("subscriptions")
        metering = await discovery.static_capabilities("metering")

        assert subscriptions["currencies"] == list(platform_plan_currencies())
        assert "error" not in metering
        assert "model" in metering["transaction_fields"]["required"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("resource_type", sorted(SUPPORTED_RESOURCE_TYPES))
    async def test_every_supported_type_has_a_static_table_built_without_a_client(
        self, resource_type
    ):
        table = await CapabilityDiscovery().static_capabilities(resource_type)

        assert table
        assert "error" not in table

    def test_ucm_still_accepts_a_dict_valued_capability_unchecked(self):
        assert ucm_verdict({"metrics": {"all": ["TOTAL_COST"]}}, "alerts", "metrics", "X") is True
