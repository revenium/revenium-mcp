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

from src.revenium_mcp_server.tool_configuration import registry as registry_module
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
                await manager.submit_transaction(client, arguments)

        payload = client.post.call_args.kwargs["data"]
        assert payload["organizationName"] == "mcp-test-org"
        assert payload["productName"] == "mcp-test-product"
        assert payload["errorReason"] == "none"
        assert payload["requestTime"] == "2026-09-02T15:30:45.123Z"
        assert payload["responseTime"] == "2026-09-02T15:30:49.373Z"
        assert payload["completionStartTime"] == "2026-09-02T15:30:46.000Z"


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
    @pytest.mark.parametrize("field", ["input_tokens", "output_tokens", "duration_ms"])
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
    @pytest.mark.parametrize("field", ["output_tokens", "duration_ms"])
    async def test_zero_is_accepted_for_output_tokens_and_duration(self, field):
        errors = await self.manager._validate_numeric_fields(self._arguments(**{field: 0}))
        assert errors == []


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
