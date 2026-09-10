"""AI model price pins are rendered, and never accepted (BACK-3084 / BACK-3005).

`priceOverridden` / `priceOverrideReason` ship on every AI model read. Before
this suite the MCP rendered neither, so a model whose rate card is pinned by a
platform-curated override looked identical to one tracking the upstream price
list — and any cost figure derived from it was indefensible against an invoice.

The fields are READ-ONLY by platform design: `AIModelResource` declares both
with `Schema.AccessMode.READ_ONLY` and `@JsonView(Views.Read::class)`, and
`AIModelService.stampOverride` stamps them only on global rows, driven by a
platform operator (`revctl ai-model override set`). The two fields the API-drift
report saw on the POST/PUT *request* schemas are readme.io write-view artifacts
of those same read-only properties. So the second half of this suite pins that
the MCP has no AI-model write path at all, and therefore no way to send either
field upstream.
"""

from __future__ import annotations

import ast
import inspect
import json
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server import client as client_module
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.tools_decomposed import metering_management
from src.revenium_mcp_server.tools_decomposed.metering_management import (
    MeteringManagement,
)

from tests.unit._helpers_hal import wire_embedded_reader

PINNED_REASON = "BACK-3005: upstream carries no 1-hour cache-write price"


def _model(name="gpt-4o", **extra):
    model = {
        "id": f"m-{name}",
        "name": name,
        "provider": "OPENAI",
        "inputCostPerToken": "0.000005",
        "outputCostPerToken": "0.000015",
    }
    model.update(extra)
    return model


def _envelope(*models):
    return {
        "_embedded": {"aIModelResourceList": list(models)},
        "page": {"totalElements": len(models), "totalPages": 1},
    }


async def _list_text(*models):
    mgmt = MeteringManagement(ucm_helper=None)
    client = wire_embedded_reader(MagicMock())
    client.get_ai_models = AsyncMock(return_value=_envelope(*models))
    with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=client):
        result = await mgmt._handle_list_ai_models({})
    return result[0].text


async def _search_text(*models):
    mgmt = MeteringManagement(ucm_helper=None)
    client = wire_embedded_reader(MagicMock())
    client.search_ai_models = AsyncMock(return_value=_envelope(*models))
    with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=client):
        result = await mgmt._handle_search_ai_models({"query": "gpt"})
    return result[0].text


# ===========================================================================
# Rendering
# ===========================================================================


class TestPricePinFormatting:
    """`_format_price_pin` — the one place the three answers are decided."""

    def test_pinned_price_reports_yes_and_the_reason(self):
        rendered = metering_management._format_price_pin(
            _model(priceOverridden=True, priceOverrideReason=PINNED_REASON)
        )
        assert rendered == f"yes - {PINNED_REASON}"

    def test_pinned_price_without_a_reason_still_reports_yes(self):
        rendered = metering_management._format_price_pin(_model(priceOverridden=True))
        assert rendered.startswith("yes - ")
        assert "no reason recorded" in rendered

    def test_a_blank_reason_is_not_rendered_as_an_empty_pin(self):
        rendered = metering_management._format_price_pin(
            _model(priceOverridden=True, priceOverrideReason="   ")
        )
        assert rendered == "yes - no reason recorded"

    def test_an_unpinned_price_reports_no_and_says_it_tracks_upstream(self):
        rendered = metering_management._format_price_pin(_model(priceOverridden=False))
        assert rendered.startswith("no")
        assert "upstream" in rendered

    def test_an_absent_flag_is_unavailable_never_false(self):
        """A server that predates BACK-3005 sends nothing; that is not 'no'."""
        rendered = metering_management._format_price_pin(_model())
        assert rendered.startswith("unavailable")

    def test_a_null_flag_is_unavailable_too(self):
        rendered = metering_management._format_price_pin(
            _model(priceOverridden=None, priceOverrideReason=None)
        )
        assert rendered.startswith("unavailable")

    @pytest.mark.parametrize("flag", ["false", "true", "", 0, 1, 2, [], {}, 1.0])
    def test_only_a_real_boolean_is_an_answer(self, flag):
        """A non-boolean must never be read as a verdict either way.

        The rows arrive off the HAL payload with no coercion, so a string
        `"false"` is truthy in Python — rendering it as a pinned price would
        state the exact opposite of what the platform sent.
        """
        rendered = metering_management._format_price_pin(
            _model(priceOverridden=flag, priceOverrideReason=PINNED_REASON)
        )
        assert rendered.startswith("unavailable"), (flag, rendered)

    @pytest.mark.parametrize("flag", ["true", 1, "false", 0, None])
    def test_a_reason_is_never_printed_beside_a_non_boolean_flag(self, flag):
        """The reason only qualifies a boolean True; otherwise it says nothing."""
        rendered = metering_management._format_price_pin(
            _model(priceOverridden=flag, priceOverrideReason=PINNED_REASON)
        )
        assert PINNED_REASON not in rendered, (flag, rendered)

    def test_the_two_boolean_singletons_are_matched_by_identity_not_equality(self):
        """`1 == True` in Python; the renderer must not accept 1 as pinned."""
        assert metering_management._format_price_pin(
            _model(priceOverridden=True)
        ).startswith("yes")
        assert metering_management._format_price_pin(
            _model(priceOverridden=1)
        ).startswith("unavailable")
        assert metering_management._format_price_pin(
            _model(priceOverridden=False)
        ).startswith("no")
        assert metering_management._format_price_pin(
            _model(priceOverridden=0)
        ).startswith("unavailable")


class TestListAiModelsRendersThePin:
    @pytest.mark.asyncio
    async def test_a_pinned_model_shows_the_pin_and_the_reason(self):
        text = await _list_text(
            _model(priceOverridden=True, priceOverrideReason=PINNED_REASON)
        )
        assert "gpt-4o" in text
        assert "Price pinned: yes" in text
        assert PINNED_REASON in text

    @pytest.mark.asyncio
    async def test_an_unpinned_model_says_so_explicitly(self):
        text = await _list_text(_model(priceOverridden=False))
        assert "Price pinned: no" in text
        assert "Price pinned: unavailable" not in text

    @pytest.mark.asyncio
    async def test_a_model_without_the_flag_reads_unavailable(self):
        text = await _list_text(_model())
        assert "Price pinned: unavailable" in text
        assert "Price pinned: no" not in text

    @pytest.mark.asyncio
    async def test_the_costs_and_the_pin_are_rendered_side_by_side(self):
        """The pin is only useful next to the number it qualifies."""
        text = await _list_text(
            _model(priceOverridden=True, priceOverrideReason=PINNED_REASON)
        )
        row = next(
            line
            for line in text.splitlines()
            if "gpt-4o" in line and line.startswith("- ")
        )
        assert "Input: $0.000005/token" in row
        assert "Price pinned: yes" in row


class TestSearchAiModelsRendersThePin:
    @pytest.mark.asyncio
    async def test_a_pinned_model_shows_the_pin_and_the_reason(self):
        text = await _search_text(
            _model(priceOverridden=True, priceOverrideReason=PINNED_REASON)
        )
        assert "**Price Pinned**: yes" in text
        assert PINNED_REASON in text

    @pytest.mark.asyncio
    async def test_an_unpinned_model_says_so_explicitly(self):
        text = await _search_text(_model(priceOverridden=False))
        assert "**Price Pinned**: no" in text

    @pytest.mark.asyncio
    async def test_a_model_without_the_flag_reads_unavailable(self):
        text = await _search_text(_model())
        assert "**Price Pinned**: unavailable" in text
        assert "**Price Pinned**: no" not in text


class TestEmbeddedReadIsKeyAgnostic:
    """BACK-3084: both listings read the HAL list through the client helper."""

    @pytest.mark.asyncio
    async def test_list_reads_the_embedded_collection_through_the_client_helper(self):
        mgmt = MeteringManagement(ucm_helper=None)
        client = MagicMock()
        client.get_ai_models = AsyncMock(
            return_value={"_embedded": {"someOtherResourceList": [_model()]}}
        )
        client._extract_embedded_data = MagicMock(return_value=[_model()])
        with patch.object(
            mgmt, "get_client", new_callable=AsyncMock, return_value=client
        ):
            result = await mgmt._handle_list_ai_models({})
        client._extract_embedded_data.assert_called_once()
        assert "gpt-4o" in result[0].text

    @pytest.mark.asyncio
    async def test_search_reads_the_embedded_collection_through_the_client_helper(self):
        mgmt = MeteringManagement(ucm_helper=None)
        client = MagicMock()
        client.search_ai_models = AsyncMock(
            return_value={"_embedded": {"someOtherResourceList": [_model()]}}
        )
        client._extract_embedded_data = MagicMock(return_value=[_model()])
        with patch.object(
            mgmt, "get_client", new_callable=AsyncMock, return_value=client
        ):
            result = await mgmt._handle_search_ai_models({"query": "gpt"})
        client._extract_embedded_data.assert_called_once()
        assert "gpt-4o" in result[0].text

    @pytest.mark.asyncio
    async def test_a_response_with_no_envelope_still_answers_no_models_found(self):
        """Behaviour preserved: a missing `_embedded` is not an empty listing."""
        mgmt = MeteringManagement(ucm_helper=None)
        client = wire_embedded_reader(MagicMock())
        client.get_ai_models = AsyncMock(return_value={})
        with patch.object(
            mgmt, "get_client", new_callable=AsyncMock, return_value=client
        ):
            result = await mgmt._handle_list_ai_models({})
        assert "No AI models found" in result[0].text

    @pytest.mark.asyncio
    async def test_a_reshaped_envelope_is_an_error_in_the_listing_not_a_catalog(self):
        """`_embedded` with no collection must never render as an empty catalog.

        `_extract_embedded_data` answers `[]` for this shape, so without the
        classification ahead of it the handler printed a listing header and
        `page.totalElements` beside zero rows — a plausible-looking total for a
        catalog it never read.
        """
        mgmt = MeteringManagement(ucm_helper=None)
        client = wire_embedded_reader(MagicMock())
        client.get_ai_models = AsyncMock(
            return_value={
                "_embedded": {"somethingWeird": "not-a-list"},
                "page": {"totalElements": 42, "totalPages": 3},
            }
        )
        with patch.object(
            mgmt, "get_client", new_callable=AsyncMock, return_value=client
        ):
            with pytest.raises(ToolError) as excinfo:
                await mgmt._handle_list_ai_models({})
        message = excinfo.value.message
        assert "malformed" in message.lower()
        assert "42" not in message
        assert "AI Models List" not in message
        assert "Total Models Found" not in message

    @pytest.mark.asyncio
    async def test_a_reshaped_envelope_is_an_error_in_the_search_not_no_matches(self):
        """The same shape in search is not "no models matched" either."""
        mgmt = MeteringManagement(ucm_helper=None)
        client = wire_embedded_reader(MagicMock())
        client.search_ai_models = AsyncMock(
            return_value={
                "_embedded": {"somethingWeird": "not-a-list"},
                "page": {"totalElements": 42, "totalPages": 3},
            }
        )
        with patch.object(
            mgmt, "get_client", new_callable=AsyncMock, return_value=client
        ):
            result = await mgmt._handle_search_ai_models({"query": "gpt"})
        text = result[0].text
        assert "malformed" in text.lower()
        assert "No models found" not in text
        assert "AI Models Search Results" not in text
        assert "42" not in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("embedded", ["not-a-dict", 7, None, [], {}])
    async def test_every_non_collection_embedded_shape_is_rejected(self, embedded):
        mgmt = MeteringManagement(ucm_helper=None)
        client = wire_embedded_reader(MagicMock())
        client.get_ai_models = AsyncMock(return_value={"_embedded": embedded})
        with patch.object(
            mgmt, "get_client", new_callable=AsyncMock, return_value=client
        ):
            with pytest.raises(ToolError):
                await mgmt._handle_list_ai_models({})

    @pytest.mark.asyncio
    async def test_an_empty_collection_is_not_rendered_as_a_catalog(self):
        """A real but empty list is a paging answer, not a vanished catalog."""
        mgmt = MeteringManagement(ucm_helper=None)
        client = wire_embedded_reader(MagicMock())
        client.get_ai_models = AsyncMock(
            return_value={
                "_embedded": {"aIModelResourceList": []},
                "page": {"totalElements": 4085, "totalPages": 409},
            }
        )
        with patch.object(
            mgmt, "get_client", new_callable=AsyncMock, return_value=client
        ):
            result = await mgmt._handle_list_ai_models({"page": 500})
        text = result[0].text
        assert "No AI models found" in text
        assert "**Total Models Found**: 4085" not in text
        # The disagreement is stated rather than printed as the catalog size.
        assert "4085" in text
        assert "not the number of models on this page" in text
        assert "page: 0" in text

    @pytest.mark.asyncio
    async def test_an_empty_search_page_names_the_reported_total(self):
        mgmt = MeteringManagement(ucm_helper=None)
        client = wire_embedded_reader(MagicMock())
        client.search_ai_models = AsyncMock(
            return_value={
                "_embedded": {"aIModelResourceList": []},
                "page": {"totalElements": 12, "totalPages": 3},
            }
        )
        with patch.object(
            mgmt, "get_client", new_callable=AsyncMock, return_value=client
        ):
            result = await mgmt._handle_search_ai_models({"query": "gpt", "page": 9})
        text = result[0].text
        assert "No models found" in text
        assert "12" in text
        assert "Results Found" not in text

    @pytest.mark.asyncio
    async def test_a_genuinely_empty_catalog_adds_no_total_note(self):
        """totalElements 0 agrees with zero rows: nothing to reconcile."""
        mgmt = MeteringManagement(ucm_helper=None)
        client = wire_embedded_reader(MagicMock())
        client.get_ai_models = AsyncMock(
            return_value={
                "_embedded": {"aIModelResourceList": []},
                "page": {"totalElements": 0, "totalPages": 0},
            }
        )
        with patch.object(
            mgmt, "get_client", new_callable=AsyncMock, return_value=client
        ):
            result = await mgmt._handle_list_ai_models({})
        text = result[0].text
        assert "No AI models found" in text
        assert "not the number of models on this page" not in text

    def test_the_three_envelope_cases_are_classified_apart(self):
        classify = metering_management._classify_ai_model_envelope
        absent = metering_management._AI_MODEL_ENVELOPE_ABSENT
        malformed = metering_management._AI_MODEL_ENVELOPE_MALFORMED
        collection = metering_management._AI_MODEL_ENVELOPE_COLLECTION

        assert classify({}) == absent
        assert classify(None) == absent
        assert classify("not-a-dict") == absent
        assert classify({"page": {"totalElements": 4}}) == absent
        assert classify({"_embedded": {"anyListKey": []}}) == collection
        assert classify({"_embedded": {"aIModelResourceList": [{}]}}) == collection
        assert classify({"_embedded": {}}) == malformed
        assert classify({"_embedded": {"weird": "not-a-list"}}) == malformed
        assert classify({"_embedded": "not-a-dict"}) == malformed

    def test_no_literal_embedded_key_remains_in_either_listing(self):
        """The key must not survive as code — a comment naming it is fine."""
        for handler in (
            MeteringManagement._handle_list_ai_models,
            MeteringManagement._handle_search_ai_models,
        ):
            tree = ast.parse(textwrap.dedent(inspect.getsource(handler)))
            literals = [
                node.value
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
            ]
            assert "aIModelResourceList" not in literals, handler.__name__


# ===========================================================================
# Read-only by platform design
# ===========================================================================

PRICE_OVERRIDE_FIELDS = ("priceOverridden", "priceOverrideReason")


class TestPriceOverrideIsNeverAccepted:
    """The MCP renders the pin; it must never offer a way to set one."""

    def test_the_mcp_exposes_no_ai_model_write_call_site(self):
        """client.py only GETs the AI model endpoints — pin that it stays that way.

        Neither field can leak onto a write path that does not exist. A
        POST/PUT/PATCH added here would need its own review against
        `AIModelResource`, where both fields are `AccessMode.READ_ONLY`.
        """
        source = Path(inspect.getfile(client_module)).read_text(encoding="utf-8")
        tree = ast.parse(source)
        writes = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            method = func.attr if isinstance(func, ast.Attribute) else None
            if method not in {"post", "put", "patch", "delete"}:
                continue
            literals = [
                arg.value
                for arg in list(node.args) + [kw.value for kw in node.keywords]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            ]
            if any("sources/ai/models" in literal for literal in literals):
                writes.append((method, literals))
        assert writes == [], f"AI model write call site(s) added: {writes}"

    @pytest.mark.asyncio
    async def test_no_declared_metering_action_writes_an_ai_model(self):
        mgmt = MeteringManagement(ucm_helper=None)
        actions = await mgmt._get_supported_actions()
        model_write_verbs = ("create", "update", "delete", "clone", "override", "set")
        offenders = [
            action
            for action in actions
            if "model" in action and action.startswith(model_write_verbs)
        ]
        assert offenders == [], offenders

    @pytest.mark.asyncio
    async def test_neither_field_is_an_accepted_input_on_manage_metering(self):
        """No schema property, enum value or nested key may carry either name."""
        mgmt = MeteringManagement(ucm_helper=None)
        schema = json.dumps(await mgmt._get_input_schema())
        for field in PRICE_OVERRIDE_FIELDS:
            assert field not in schema, f"{field} is declared as an input"

    def test_neither_field_reaches_a_payload_dict(self):
        """No dict literal in the metering tool may carry either field as a key."""
        source = Path(inspect.getfile(metering_management)).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key in node.keys:
                if isinstance(key, ast.Constant) and key.value in PRICE_OVERRIDE_FIELDS:
                    raise AssertionError(
                        f"{key.value} is used as a dict key at line {key.lineno}"
                    )

    def test_the_renderer_records_that_the_fields_are_read_only(self):
        """The design constraint must be stated where the fields are used."""
        module_source = Path(inspect.getfile(metering_management)).read_text(
            encoding="utf-8"
        )
        assert "BACK-3005" in module_source
        assert "READ-ONLY BY PLATFORM DESIGN" in module_source
        assert "priceOverridden" in inspect.getsource(
            metering_management._format_price_pin
        )
