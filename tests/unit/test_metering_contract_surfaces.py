"""The metering tool must accept the fields it publishes, and document the rules it enforces.

Covers three contract breaks found by the 2026-09-02 functional audit:

* BACK-2934 - `get_examples` published fields (`organization_name`, `product_name`,
  `error_reason`, `request_time`, `response_time`, `completion_start_time`) were absent
  from the registered `manage_metering` signature, so FastMCP rejected the tool's own
  example before the handler saw it, and dry-run disagreed with the live submit about
  the deprecated `organization_id` / `product_id` aliases.
* BACK-2939 - `get_supported_providers` reported the size of the fetched page as the
  catalog total.
* BACK-2942 - the documentation claimed `> 0` for all three numeric fields while the
  validator deliberately accepts zero output tokens and zero duration.
"""

import ast
import inspect
import json
import re
import textwrap
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import Client, FastMCP

from src.revenium_mcp_server.auth.tenant_scope import LOCAL_TENANT_SCOPE
from src.revenium_mcp_server.capability_manager.integration_service import (
    ucm_integration_service,
)
from src.revenium_mcp_server.introspection.integration import introspection_integration
from src.revenium_mcp_server.tool_configuration import registry as registry_module
from src.revenium_mcp_server.tool_configuration.config import ToolConfig
from src.revenium_mcp_server.tools_decomposed import metering_management
from src.revenium_mcp_server.tools_decomposed.metering_management import (
    MeteringManagement,
    MeteringTransactionManager,
)

from tests.unit._helpers_hal import wire_embedded_reader
from src.revenium_mcp_server.common.error_handling import ToolError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def registered_manage_metering_parameters():
    """Parameter names of the closure FastMCP builds the manage_metering schema from."""
    source = textwrap.dedent(
        inspect.getsource(registry_module.ToolConfigurationRegistry._register_manage_metering)
    )
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "manage_metering":
            args = node.args
            return {a.arg for a in args.args + args.posonlyargs + args.kwonlyargs}
    raise AssertionError("manage_metering closure not found in the registry")


def published_example_payloads(text):
    """Every JSON tool call the get_examples output publishes."""
    payloads = []
    for block in re.findall(r"```json\n(.*?)```", text, flags=re.DOTALL):
        try:
            parsed = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and "action" in parsed:
            payloads.append(parsed)
    return payloads


def make_client():
    client = MagicMock()
    client.team_id = "test_team_id_456"
    client.post = AsyncMock(return_value={"status": "ok", "id": "api_tx_001"})
    client.get = AsyncMock(return_value={})
    return wire_embedded_reader(client)


TOKEN_DETAIL_FIELDS = ["reasoning_tokens", "cache_creation_tokens", "cache_read_tokens"]


@pytest.fixture
async def in_process_metering(monkeypatch):
    """The registered manage_metering tool, served in process over a mocked platform."""
    client = make_client()

    async def platform_client(self, ctx=None):
        return client

    monkeypatch.setattr(MeteringManagement, "get_client", platform_client)
    monkeypatch.setattr(metering_management, "_prime_provider_validation", AsyncMock())
    monkeypatch.setattr(
        MeteringTransactionManager,
        "_validate_transaction_inputs_async",
        AsyncMock(return_value={"valid": True, "message": "ok"}),
    )
    monkeypatch.setattr(
        ucm_integration_service,
        "get_health_status",
        AsyncMock(return_value={"status": "unhealthy"}),
    )
    server = FastMCP("metering-contract-surfaces")
    registry = registry_module.ToolConfigurationRegistry(
        tool_config=ToolConfig.create_for_testing(profile="business")
    )
    await registry._register_manage_metering(server)
    providers = introspection_integration.engine.registry
    monkeypatch.setattr(providers, "_providers", {})
    await providers.register_provider("manage_metering", MeteringManagement())
    with patch.object(metering_management, "response_cache") as cache:
        cache.get_cached_response = AsyncMock(return_value=None)
        cache.set_cached_response = AsyncMock()
        yield {"server": server, "client": client}


# ===========================================================================
# BACK-2934 - published fields reach the registered schema and the payload
# ===========================================================================


class TestPublishedFieldsAreDrivable:
    """The tool's own examples must be submittable verbatim."""

    @pytest.mark.asyncio
    async def test_every_field_published_by_get_examples_is_in_the_schema(self):
        mm = MeteringManagement.__new__(MeteringManagement)
        examples = await mm._handle_get_examples({})
        payloads = published_example_payloads(examples[0].text)
        assert payloads, "get_examples published no JSON tool calls"

        declared = registered_manage_metering_parameters()
        published = {field for payload in payloads for field in payload}
        missing = sorted(published - declared)
        assert not missing, (
            "get_examples publishes fields the registered manage_metering schema does "
            f"not declare, so submitting the example verbatim fails: {missing}"
        )

    @pytest.mark.parametrize(
        "field",
        [
            "organization_name",
            "product_name",
            "error_reason",
            "request_time",
            "response_time",
            "completion_start_time",
            "reasoning_tokens",
            "cache_creation_tokens",
            "cache_read_tokens",
        ],
    )
    def test_documented_submission_field_is_declared(self, field):
        assert field in registered_manage_metering_parameters()

    @pytest.mark.parametrize(
        "field",
        [
            "organization_name",
            "product_name",
            "error_reason",
            "request_time",
            "response_time",
            "completion_start_time",
            "reasoning_tokens",
            "cache_creation_tokens",
            "cache_read_tokens",
        ],
    )
    def test_documented_submission_field_is_forwarded(self, field):
        source = inspect.getsource(
            registry_module.ToolConfigurationRegistry._register_manage_metering
        )
        assert f'"{field}": {field}' in source

    @pytest.mark.asyncio
    async def test_attribution_fields_reach_the_outbound_payload(self):
        manager = MeteringTransactionManager()
        client = make_client()
        arguments = {
            "model": "gpt-4o",
            "provider": "openai",
            "input_tokens": 3247,
            "output_tokens": 1856,
            "duration_ms": 4250,
            "organization_name": "mcp-test-org",
            "product_name": "mcp-test-product",
            "error_reason": "none",
            "request_time": "2026-09-02T15:30:45.123Z",
            "response_time": "2026-09-02T15:30:49.373Z",
            "completion_start_time": "2026-09-02T15:30:46.000Z",
        }
        with patch.object(
            manager,
            "_validate_transaction_inputs_async",
            new_callable=AsyncMock,
            return_value={"valid": True, "message": "ok"},
        ):
            with patch(
                "src.revenium_mcp_server.tools_decomposed.metering_management.response_cache"
            ) as mock_cache:
                mock_cache.get_cached_response = AsyncMock(return_value=None)
                mock_cache.set_cached_response = AsyncMock()
                await manager.submit_transaction(client, arguments, LOCAL_TENANT_SCOPE)

        payload = client.post.call_args.kwargs["data"]
        assert payload["organizationName"] == "mcp-test-org"
        assert payload["productName"] == "mcp-test-product"
        assert payload["errorReason"] == "none"
        assert payload["requestTime"] == "2026-09-02T15:30:45.123Z"
        assert payload["responseTime"] == "2026-09-02T15:30:49.373Z"
        assert payload["completionStartTime"] == "2026-09-02T15:30:46.000Z"

    @pytest.mark.asyncio
    async def test_cache_and_reasoning_tokens_are_documented_for_submission(self):
        mm = MeteringManagement.__new__(MeteringManagement)
        properties = (await mm._get_input_schema())["properties"]
        for field in TOKEN_DETAIL_FIELDS:
            assert properties.get(field, {}).get("type") == "integer", field

    @pytest.mark.asyncio
    async def test_cache_and_reasoning_tokens_given_top_level_reach_the_platform(
        self, in_process_metering
    ):
        """BACK-4713: the token-detail arguments are accepted and metered as sent."""
        async with Client(in_process_metering["server"]) as session:
            await session.call_tool(
                "manage_metering",
                {
                    "action": "submit_ai_transaction",
                    "model": "claude-sonnet-4-5",
                    "provider": "ANTHROPIC",
                    "input_tokens": 1500,
                    "output_tokens": 800,
                    "duration_ms": 2500,
                    "reasoning_tokens": 100,
                    "cache_creation_tokens": 50,
                    "cache_read_tokens": 25,
                },
            )

        payload = in_process_metering["client"].post.call_args.kwargs["data"]
        assert payload["reasoningTokenCount"] == 100
        assert payload["cacheCreationTokenCount"] == 50
        assert payload["cacheReadTokenCount"] == 25


class TestDryRunAgreesWithLive:
    """A payload dry-run calls valid must not fail on submit."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "deprecated,replacement",
        [("organization_id", "organization_name"), ("product_id", "product_name")],
    )
    async def test_dry_run_rejects_the_deprecated_alias_like_the_live_path(
        self, deprecated, replacement
    ):
        mm = MeteringManagement()
        client = make_client()
        arguments = {
            "model": "gpt-4o",
            "provider": "openai",
            "input_tokens": 100,
            "output_tokens": 50,
            "duration_ms": 1000,
            deprecated: "value",
            "dry_run": True,
        }
        with patch.object(mm, "get_client", new_callable=AsyncMock, return_value=client):
            with pytest.raises(ToolError) as exc:
                await mm.handle_action("submit_ai_transaction", arguments)

        assert deprecated in str(exc.value.message)
        assert replacement in str(exc.value.message)

    @pytest.mark.asyncio
    async def test_the_suggested_replacement_is_accepted(self):
        """The rename the error asks for has to be a name the tool takes."""
        declared = registered_manage_metering_parameters()
        assert {"organization_name", "product_name"} <= declared

    @staticmethod
    def _submission(transaction_id, **overrides):
        arguments = {
            "model": "gpt-4o",
            "provider": "openai",
            "input_tokens": 100,
            "output_tokens": 50,
            "duration_ms": 1000,
            "transaction_id": transaction_id,
        }
        arguments.update(overrides)
        return arguments

    async def _raised_by(self, mm, arguments):
        with pytest.raises(ToolError) as exc:
            await mm.handle_action("submit_ai_transaction", arguments)
        return exc.value

    @pytest.mark.asyncio
    async def test_dry_run_rejects_an_unrecognized_transaction_id_like_the_live_path(self):
        """BACK-4713: a preview must refuse the id the real submit refuses."""
        mm = MeteringManagement()
        client = make_client()
        with patch.object(mm, "get_client", new_callable=AsyncMock, return_value=client):
            with patch(
                "src.revenium_mcp_server.tools_decomposed.metering_management.response_cache"
            ) as mock_cache:
                mock_cache.get_cached_response = AsyncMock(return_value=None)
                mock_cache.set_cached_response = AsyncMock()
                live = await self._raised_by(mm, self._submission("my-run-1"))
                dry = await self._raised_by(
                    mm, self._submission("my-run-1", dry_run=True)
                )

        assert "is not a recognized format" in str(live.message)
        assert dry.message == live.message
        client.post.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("transaction_id", ["my-run-1", "", "tx_short"])
    async def test_validate_rejects_an_unrecognized_transaction_id_like_the_live_path(
        self, transaction_id
    ):
        """BACK-4794: validate must refuse the id the real submit refuses."""
        mm = MeteringManagement()
        client = make_client()
        with patch.object(mm, "get_client", new_callable=AsyncMock, return_value=client):
            with patch(
                "src.revenium_mcp_server.tools_decomposed.metering_management.response_cache"
            ) as mock_cache:
                mock_cache.get_cached_response = AsyncMock(return_value=None)
                mock_cache.set_cached_response = AsyncMock()
                live = await self._raised_by(mm, self._submission(transaction_id))
                with pytest.raises(ToolError) as exc:
                    await mm.handle_action("validate", self._submission(transaction_id))

        assert exc.value.message == live.message
        assert exc.value.field == live.field == "transaction_id"
        client.post.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("deprecated", ["organization_id", "product_id"])
    async def test_validate_rejects_the_deprecated_alias_like_the_live_path(self, deprecated):
        """BACK-4794: validate must refuse the alias the real submit refuses."""
        mm = MeteringManagement()
        client = make_client()
        arguments = {
            "model": "gpt-4o",
            "provider": "openai",
            "input_tokens": 100,
            "output_tokens": 50,
            "duration_ms": 1000,
            deprecated: "value",
        }
        with patch.object(mm, "get_client", new_callable=AsyncMock, return_value=client):
            with patch(
                "src.revenium_mcp_server.tools_decomposed.metering_management.response_cache"
            ) as mock_cache:
                mock_cache.get_cached_response = AsyncMock(return_value=None)
                mock_cache.set_cached_response = AsyncMock()
                live = await self._raised_by(mm, dict(arguments))
                with pytest.raises(ToolError) as exc:
                    await mm.handle_action("validate", dict(arguments))

        assert deprecated in str(exc.value.message)
        assert exc.value.message == live.message
        assert exc.value.field == live.field == deprecated
        client.post.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "transaction_id", ["550e8400-e29b-41d4-a716-446655440000", None]
    )
    async def test_validate_accepts_a_recognized_transaction_id(self, transaction_id):
        mm = MeteringManagement()
        client = make_client()
        arguments = self._submission(transaction_id)
        if transaction_id is None:
            del arguments["transaction_id"]
        with patch.object(mm, "get_client", new_callable=AsyncMock, return_value=client):
            result = await mm.handle_action("validate", arguments)

        text = result[0].text
        assert "Validation Successful" in text, text
        client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_dry_run_accepts_a_recognized_transaction_id(self):
        mm = MeteringManagement()
        client = make_client()
        arguments = self._submission(
            "550e8400-e29b-41d4-a716-446655440000", dry_run=True
        )
        with patch.object(mm, "get_client", new_callable=AsyncMock, return_value=client):
            result = await mm.handle_action("submit_ai_transaction", arguments)

        text = result[0].text
        assert "DRY RUN MODE - Transaction Validation" in text, text
        assert "Validation Failed" not in text
        client.post.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("dry_run", [False, True])
    async def test_dry_run_and_live_share_one_transaction_id_check(self, dry_run):
        mm = MeteringManagement()
        client = make_client()
        arguments = self._submission("my-run-1", dry_run=dry_run)
        with patch.object(mm, "get_client", new_callable=AsyncMock, return_value=client):
            with patch.object(
                mm.transaction_manager,
                "reject_unrecognized_transaction_id",
                side_effect=ToolError(message="sentinel"),
            ):
                raised = await self._raised_by(mm, arguments)

        assert raised.message == "sentinel"


# ===========================================================================
# BACK-2939 - the supported-providers total is the catalog total
# ===========================================================================


class TestSupportedProvidersTotal:

    def _catalog_response(self, page_size, total):
        models = [
            {"id": f"m{i}", "name": f"model-{i}", "provider": "OPENAI"}
            for i in range(page_size)
        ]
        return {
            "_embedded": {"aIModelResourceList": models},
            "page": {"totalElements": total, "size": page_size},
        }

    @pytest.mark.asyncio
    async def test_total_models_is_the_paging_total_not_the_page_size(self):
        mm = MeteringManagement()
        client = make_client()
        client.get_ai_models = AsyncMock(return_value=self._catalog_response(100, 3749))
        with patch.object(mm, "get_client", new_callable=AsyncMock, return_value=client):
            result = await mm.handle_action("get_supported_providers", {})

        text = result[0].text
        assert "**Total Models**: 3749" in text, text
        assert "**Total Models**: 100" not in text

    @pytest.mark.asyncio
    async def test_a_truncated_page_says_the_breakdown_is_a_sample(self):
        mm = MeteringManagement()
        client = make_client()
        client.get_ai_models = AsyncMock(return_value=self._catalog_response(100, 3749))
        with patch.object(mm, "get_client", new_callable=AsyncMock, return_value=client):
            result = await mm.handle_action("get_supported_providers", {})

        text = result[0].text
        assert "sample" in text.lower(), text
        assert "not unsupported" in text

    @pytest.mark.asyncio
    async def test_the_sample_asks_for_and_states_the_platform_page_cap(self):
        """BACK-4853: the catalog read asks for the 100 rows a page the platform serves and says so."""
        mm = MeteringManagement()
        client = make_client()
        client.get_ai_models = AsyncMock(return_value=self._catalog_response(100, 3749))
        with patch.object(mm, "get_client", new_callable=AsyncMock, return_value=client):
            result = await mm.handle_action("get_supported_providers", {})

        assert client.get_ai_models.await_args.kwargs["size"] == 100
        assert (
            "(from the first 100 of 3749 models; the platform serves at most 100 models a page)"
            in result[0].text
        )

    def test_the_fallback_provider_scan_asks_for_the_platform_page_cap(self):
        assert metering_management._PROVIDER_CATALOG_PAGE_SIZE == 100

    @pytest.mark.asyncio
    async def test_a_complete_page_is_not_labelled_a_sample(self):
        mm = MeteringManagement()
        client = make_client()
        client.get_ai_models = AsyncMock(return_value=self._catalog_response(3, 3))
        with patch.object(mm, "get_client", new_callable=AsyncMock, return_value=client):
            result = await mm.handle_action("get_supported_providers", {})

        text = result[0].text
        assert "**Total Models**: 3" in text, text
        assert "**Total Providers**: 1" in text
        assert "sample of the catalog" not in text


# ===========================================================================
# BACK-2942 - the documented numeric rule is the rule the validator enforces
# ===========================================================================


class TestNumericBounds:
    """input_tokens rejects zero; output_tokens and duration_ms accept it.

    Deliberate, per the backend review on PR #181 (commit d6ff067) and PR #192
    (commit 1c266a3): embeddings legitimately report zero output tokens and
    republished traces carry no measured duration.
    """

    def setup_method(self):
        self.manager = MeteringTransactionManager()

    def _arguments(self, **overrides):
        args = {
            "model": "gpt-4o",
            "provider": "openai",
            "input_tokens": 100,
            "output_tokens": 50,
            "duration_ms": 1000,
        }
        args.update(overrides)
        return args

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "field", ["input_tokens", "output_tokens", "duration_ms", *TOKEN_DETAIL_FIELDS]
    )
    async def test_one_is_accepted(self, field):
        errors = await self.manager._validate_numeric_fields(self._arguments(**{field: 1}))
        assert errors == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("field", ["input_tokens", "output_tokens", "duration_ms"])
    async def test_negative_is_rejected(self, field):
        errors = await self.manager._validate_numeric_fields(self._arguments(**{field: -1}))
        assert any(field in error for error in errors), errors

    @pytest.mark.asyncio
    async def test_zero_input_tokens_is_rejected(self):
        errors = await self.manager._validate_numeric_fields(self._arguments(input_tokens=0))
        assert any("input_tokens" in error and "> 0" in error for error in errors), errors

    @pytest.mark.asyncio
    @pytest.mark.parametrize("field", ["output_tokens", "duration_ms", *TOKEN_DETAIL_FIELDS])
    async def test_zero_is_accepted_for_output_tokens_and_duration(self, field):
        errors = await self.manager._validate_numeric_fields(self._arguments(**{field: 0}))
        assert errors == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("field", TOKEN_DETAIL_FIELDS)
    async def test_negative_cache_tokens_are_rejected(self, field):
        errors = await self.manager._validate_numeric_fields(self._arguments(**{field: -1}))
        assert any(field in error and ">= 0" in error for error in errors), errors


class TestDocumentedNumericRule:
    """get_business_rules, get_field_documentation and get_capabilities must agree."""

    @pytest.mark.asyncio
    async def test_business_rules_state_the_enforced_rule(self):
        mm = MeteringManagement.__new__(MeteringManagement)
        text = await mm._build_business_rules_content(None)
        assert "`output_tokens` (≥ 0" in text, text
        assert "**Duration**: Milliseconds (≥ 0" in text
        assert "Positive integer milliseconds (> 0" not in text

    @pytest.mark.asyncio
    async def test_field_documentation_states_the_enforced_rule(self):
        mm = MeteringManagement.__new__(MeteringManagement)
        text = await mm._build_field_documentation_content(None)
        assert "Output tokens (≥ 0" in text, text
        assert "Duration in milliseconds (≥ 0" in text
        assert "Output tokens (> 0" not in text

    @pytest.mark.asyncio
    async def test_validation_capabilities_state_the_enforced_rule(self):
        mm = MeteringManagement.__new__(MeteringManagement)
        text = await mm._build_validation_capabilities_content(None)
        assert "`output_tokens`: Integer (≥ 0" in text, text
        assert "`duration_ms`: Integer (≥ 0" in text
        assert "`input_tokens`: Integer (> 0" in text
        for field in TOKEN_DETAIL_FIELDS:
            assert f"`{field}`: Integer (≥ 0" in text, field


# ===========================================================================
# BACK-4713 - backfilled response and completion-start times follow request_time
# ===========================================================================


class TestBackfilledTimestamps:
    """A transaction given only its request time is not recorded as finishing now."""

    NOW = "2026-10-17T12:00:00.000Z"

    async def _submitted_payload(self, manager, **overrides):
        arguments = {
            "model": "gpt-4o",
            "provider": "openai",
            "input_tokens": 1500,
            "output_tokens": 800,
            "duration_ms": 2500,
        }
        arguments.update(overrides)
        client = make_client()
        with patch.object(
            manager,
            "_validate_transaction_inputs_async",
            new_callable=AsyncMock,
            return_value={"valid": True, "message": "ok"},
        ):
            with patch(
                "src.revenium_mcp_server.tools_decomposed.metering_management.response_cache"
            ) as mock_cache:
                mock_cache.get_cached_response = AsyncMock(return_value=None)
                mock_cache.set_cached_response = AsyncMock()
                await manager.submit_transaction(client, arguments, LOCAL_TENANT_SCOPE)
        return client.post.call_args.kwargs["data"]

    async def _payload(self, **overrides):
        return await self._submitted_payload(MeteringTransactionManager(), **overrides)

    @pytest.mark.asyncio
    async def test_response_time_follows_request_time_plus_duration(self):
        payload = await self._payload(request_time="2026-10-16T10:00:00.000Z")
        assert payload["requestTime"] == "2026-10-16T10:00:00.000Z"
        assert payload["responseTime"] == "2026-10-16T10:00:02.500Z"
        assert payload["completionStartTime"] == "2026-10-16T10:00:00.250Z"

    @pytest.mark.asyncio
    async def test_request_time_without_milliseconds_derives_a_z_suffixed_response(self):
        payload = await self._payload(request_time="2026-10-16T10:00:00Z")
        assert payload["responseTime"] == "2026-10-16T10:00:02.500Z"

    @pytest.mark.asyncio
    async def test_date_only_request_time_derives_a_z_suffixed_response(self):
        payload = await self._payload(request_time="2026-10-16Z")
        assert payload["responseTime"].startswith("2026-10-16T00:00:02.500"), payload
        assert payload["responseTime"].endswith("Z"), payload

    @pytest.mark.asyncio
    async def test_microsecond_request_time_is_truncated_to_milliseconds(self):
        payload = await self._payload(request_time="2026-10-16T10:00:00.123456Z")
        assert payload["responseTime"] == "2026-10-16T10:00:02.623Z"

    @pytest.mark.asyncio
    async def test_explicit_time_to_first_token_sets_the_completion_start(self):
        payload = await self._payload(
            request_time="2026-10-16T10:00:00.000Z", time_to_first_token=400
        )
        assert payload["completionStartTime"] == "2026-10-16T10:00:00.400Z"
        assert payload["timeToFirstToken"] == 400

    @pytest.mark.asyncio
    async def test_a_caller_given_response_time_is_kept(self):
        payload = await self._payload(
            request_time="2026-10-16T10:00:00.000Z",
            response_time="2026-10-16T10:00:09.000Z",
            completion_start_time="2026-10-16T10:00:01.000Z",
        )
        assert payload["responseTime"] == "2026-10-16T10:00:09.000Z"
        assert payload["completionStartTime"] == "2026-10-16T10:00:01.000Z"

    @pytest.mark.asyncio
    async def test_without_request_time_every_timestamp_is_now(self):
        manager = MeteringTransactionManager()
        real_iso_utc = manager._iso_utc

        def fixed_now(dt=None):
            return self.NOW if dt is None else real_iso_utc(dt)

        with patch.object(manager, "_iso_utc", side_effect=fixed_now):
            payload = await self._submitted_payload(manager)

        assert payload["requestTime"] == self.NOW
        assert payload["responseTime"] == self.NOW
        assert payload["completionStartTime"] == self.NOW


class TestModelTipsNameRealActions:
    """list_ai_models and search_ai_models tips may only name actions the tool has."""

    @pytest.mark.asyncio
    async def test_list_and_search_tips_name_only_supported_actions(self):
        envelope = {
            "_embedded": {
                "aIModelResourceList": [{"name": "gpt-4o", "provider": "OPENAI", "id": "m1"}]
            },
            "page": {"totalElements": 1, "totalPages": 1},
        }
        mgmt = MeteringManagement(ucm_helper=None)
        client = wire_embedded_reader(MagicMock())
        client.get_ai_models = AsyncMock(return_value=envelope)
        client.search_ai_models = AsyncMock(return_value=envelope)
        with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=client):
            listed = (await mgmt._handle_list_ai_models({}))[0].text
            searched = (await mgmt._handle_search_ai_models({"query": "gpt"}))[0].text

        assert "**Results Found**" in searched
        supported = set(await MeteringManagement()._get_supported_actions())
        for text in (listed, searched):
            named = set(re.findall(r"`(\w+)\(", text))
            assert named <= supported, named - supported
            assert "get_ai_model" not in text


# ===========================================================================
# BACK-4861 - lookup_recent_transactions reads the size the schema advertises
# ===========================================================================


def _serve_the_size_asked_for(client):
    async def serve(endpoint, params=None, **_):
        rows = [
            {"transactionId": f"tx_{index}", "model": "gpt-4o", "provider": "openai"}
            for index in range(params["size"])
        ]
        return {"_embedded": {"aICompletionMetricResourceList": rows}}

    client.get = AsyncMock(side_effect=serve)


class TestRecentTransactionsPageSize:
    """size, the paging argument the thin schema advertises, sets the page on lookup_recent_transactions."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "arguments",
        [
            pytest.param({"size": 3}, id="top_level_size"),
            pytest.param({"params": {"size": 3}}, id="size_in_params"),
            pytest.param({"page_size": 3}, id="page_size"),
            pytest.param({"page_size": 3, "size": 50}, id="page_size_wins_over_size"),
        ],
    )
    async def test_lookup_recent_transactions_returns_the_size_asked_for(
        self, in_process_metering, arguments
    ):
        _serve_the_size_asked_for(in_process_metering["client"])

        async with Client(in_process_metering["server"]) as mcp_client:
            result = await mcp_client.call_tool(
                "get_metering", {"action": "lookup_recent_transactions", **arguments}
            )

        text = result.content[0].text
        sent = in_process_metering["client"].get.await_args.kwargs["params"]
        assert sent["size"] == 3
        assert "**Page**: 0 (size: 3)" in text
        assert "**Found**: 3 transactions" in text

    @pytest.mark.asyncio
    async def test_schema_says_lookup_recent_reads_size_and_analyze_reads_only_page_size(self):
        schema = await MeteringManagement()._get_input_schema()
        description = schema["properties"]["page_size"]["description"]

        assert "only accepted page/sample size" not in description
        assert (
            "lookup_recent_transactions also reads `size` when page_size is not sent "
            "(page_size wins when both are sent)"
        ) in description
        assert "analyze_recent_transactions reads only page_size" in description
