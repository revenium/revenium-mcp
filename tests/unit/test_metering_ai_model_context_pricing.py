"""AI model long-prompt price bands are rendered wherever the catalog prices are (BACK-5678).

The model read carries `contextPricing.bands`: a prompt larger than a band's
`abovePromptTokens` (and at most its `throughPromptTokens`, when present) bills
at that band's prices instead of the model's ordinary prices. A null
`contextPricing` and an empty band list both mean every prompt bills at the
ordinary prices, so neither adds anything to the output. The platform's pricing
sync stores a band that starts at the first token with `abovePromptTokens: -1`
(hypercurrent `ContextPriceParser`), so a negative lower bound is not printed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.tools_decomposed import metering_management
from src.revenium_mcp_server.tools_decomposed.metering_management import (
    MeteringManagement,
)

from tests.unit._helpers_hal import wire_embedded_reader

LONG_PROMPT = "Long-prompt price"


def _price(value):
    return metering_management._format_price_per_token(value)


def _band(above, through=None, input_cost=0.0000025, output_cost=0.00002):
    band = {
        "abovePromptTokens": above,
        "inputCostPerToken": input_cost,
        "outputCostPerToken": output_cost,
        "cacheReadCostPerInputToken": 0.00000025,
    }
    if through is not None:
        band["throughPromptTokens"] = through
    return band


def _model(*bands, name="gpt-5", **extra):
    model = {
        "id": f"m-{name}",
        "name": name,
        "provider": "OPENAI",
        "inputCostPerToken": 0.00000125,
        "outputCostPerToken": 0.00001,
        "contextPricing": {"bands": list(bands)},
    }
    model.update(extra)
    return model


def _envelope(*models):
    return {
        "_embedded": {"aIModelResourceList": list(models)},
        "page": {"totalElements": len(models), "totalPages": 1},
    }


def _client_answering(*models):
    client = wire_embedded_reader(MagicMock())
    client.get_ai_models = AsyncMock(return_value=_envelope(*models))
    client.search_ai_models = AsyncMock(return_value=_envelope(*models))
    return client


async def _render(handler_name, arguments, *models):
    mgmt = MeteringManagement(ucm_helper=None)
    client = _client_answering(*models)
    with patch.object(mgmt, "get_client", new_callable=AsyncMock, return_value=client):
        result = await getattr(mgmt, handler_name)(arguments)
    return result[0].text


async def _list_text(*models):
    return await _render("_handle_list_ai_models", {}, *models)


async def _search_text(*models):
    return await _render("_handle_search_ai_models", {"query": "gpt"}, *models)


async def _validate_text(*models):
    return await _render(
        "_handle_validate_model_provider", {"model": "gpt-5", "provider": "openai"}, *models
    )


def _band_lines(text):
    return [line for line in text.splitlines() if LONG_PROMPT in line]


class TestBandWording:
    def test_one_band_names_its_threshold_and_both_prices(self):
        lines = _band_lines(metering_management._context_price_bands(_model(_band(272000))))
        assert lines == [
            f"- {LONG_PROMPT} (prompts above 272,000 tokens): "
            f"Input {_price(0.0000025)}, Output {_price(0.00002)}"
        ]

    def test_sub_cent_prices_render_exactly_as_the_ordinary_prices_do(self):
        rendered = metering_management._context_price_bands(
            _model(_band(200000, input_cost=0.000000075, output_cost="0.0000003"))
        )
        assert _price(0.000000075) in rendered
        assert _price("0.0000003") in rendered
        assert "e-" not in rendered

    def test_a_band_with_an_upper_bound_says_through(self):
        lines = _band_lines(
            metering_management._context_price_bands(_model(_band(272000, through=1000000)))
        )
        assert len(lines) == 1
        assert "prompts above 272,000 through 1,000,000 tokens" in lines[0]

    def test_a_band_without_an_upper_bound_names_no_ceiling(self):
        line = _band_lines(metering_management._context_price_bands(_model(_band(272000))))[0]
        assert "through" not in line

    def test_several_bands_render_one_line_each_in_the_order_served(self):
        lines = _band_lines(
            metering_management._context_price_bands(
                _model(
                    _band(128000, through=272000, input_cost=0.0000025, output_cost=0.00002),
                    _band(272000, input_cost=0.000005, output_cost=0.00004),
                )
            )
        )
        assert len(lines) == 2
        assert "prompts above 128,000 through 272,000 tokens" in lines[0]
        assert _price(0.0000025) in lines[0]
        assert "prompts above 272,000 tokens" in lines[1]
        assert _price(0.000005) in lines[1] and _price(0.00004) in lines[1]

    def test_a_band_from_the_first_token_does_not_print_a_negative_bound(self):
        rendered = metering_management._context_price_bands(
            _model(_band(-1, through=200000), _band(200000))
        )
        lines = _band_lines(rendered)
        assert "prompts of at most 200,000 tokens" in lines[0]
        assert "-1" not in rendered

    def test_an_open_band_from_the_first_token_covers_every_prompt(self):
        line = _band_lines(metering_management._context_price_bands(_model(_band(-1))))[0]
        assert "(every prompt)" in line

    def test_a_missing_band_price_reads_n_a(self):
        band = _band(272000)
        del band["outputCostPerToken"]
        line = _band_lines(metering_management._context_price_bands(_model(band)))[0]
        assert "Output n/a" in line

    def test_the_indent_nests_the_lines_under_a_listing_row(self):
        rendered = metering_management._context_price_bands(_model(_band(272000)), indent="  ")
        assert rendered.startswith(f"  - {LONG_PROMPT}")
        assert rendered.endswith("\n")


def _range_of(band):
    line = _band_lines(metering_management._context_price_bands(_model(band)))[0]
    return line[line.index("(") + 1 : line.index(")")]


class TestBandBoundsThatCannotBeRead:
    @pytest.mark.parametrize(
        ("above", "through", "expected"),
        [
            (272000, None, "prompts above 272,000 tokens"),
            (272000, 1000000, "prompts above 272,000 through 1,000,000 tokens"),
            (0, None, "prompts above 0 tokens"),
            (-1, None, "every prompt"),
            (-1, 200000, "prompts of at most 200,000 tokens"),
        ],
    )
    def test_well_formed_bands_keep_their_wording(self, above, through, expected):
        assert _range_of(_band(above, through=through)) == expected

    @pytest.mark.parametrize("missing_lower", ["null", "absent"])
    def test_no_lower_bound_with_an_upper_bound_says_the_lower_bound_is_not_given(self, missing_lower):
        band = _band(None, through=200000)
        if missing_lower == "absent":
            del band["abovePromptTokens"]
        assert _range_of(band) == "prompts through 200,000 tokens, lower bound not given"

    @pytest.mark.parametrize("missing_lower", ["null", "absent"])
    def test_no_bound_at_all_names_no_size(self, missing_lower):
        band = _band(None)
        if missing_lower == "absent":
            del band["abovePromptTokens"]
        assert _range_of(band) == "prompt sizes not given"

    @pytest.mark.parametrize("lower", [True, 272000.0, "272000"], ids=["bool", "float", "string"])
    def test_a_lower_bound_that_is_not_a_whole_number_is_named_as_not_given(self, lower):
        assert _range_of(_band(lower, through=1000000)) == "prompts through 1,000,000 tokens, lower bound not given"
        assert _range_of(_band(lower)) == "prompt sizes not given"

    @pytest.mark.parametrize("upper", [True, 1000000.0, "1000000"], ids=["bool", "float", "string"])
    def test_an_upper_bound_that_is_not_a_whole_number_is_not_formatted(self, upper):
        assert (
            _range_of(_band(272000, through=upper))
            == "prompts above 272,000 tokens, upper bound not given"
        )
        assert _range_of(_band(-1, through=upper)) == "prompt sizes not given"

    def test_a_malformed_band_never_prints_n_a_as_a_size(self):
        rendered = metering_management._context_price_bands(
            _model(_band(None), _band(None, through=200000), _band("x", through="y"), _band(1.5))
        )
        assert len(_band_lines(rendered)) == 4
        assert "n/a" not in rendered


class TestNoBandsMeansNothingExtra:
    @pytest.mark.parametrize(
        "context_pricing",
        [None, {}, {"bands": None}, {"bands": []}, "unexpected", {"bands": "unexpected"}],
    )
    def test_null_or_empty_context_pricing_adds_nothing(self, context_pricing):
        model = _model()
        model["contextPricing"] = context_pricing
        assert metering_management._context_price_bands(model) == ""

    def test_a_model_without_the_field_adds_nothing(self):
        model = _model()
        del model["contextPricing"]
        assert metering_management._context_price_bands(model) == ""

    def test_a_null_band_entry_is_skipped(self):
        lines = _band_lines(metering_management._context_price_bands(_model(None, _band(272000))))
        assert len(lines) == 1


class TestEveryRenderSiteShowsTheBands:
    @pytest.mark.asyncio
    async def test_the_listing_nests_the_bands_under_the_model_row(self):
        text = await _list_text(_model(_band(272000, through=1000000)))
        rows = text.splitlines()
        model_row = next(i for i, line in enumerate(rows) if line.startswith("- **gpt-5**"))
        assert rows[model_row + 1].startswith(f"  - {LONG_PROMPT} (prompts above 272,000 through")
        assert _price(0.0000025) in rows[model_row + 1]

    @pytest.mark.asyncio
    async def test_the_search_shows_the_bands_beside_the_ordinary_prices(self):
        text = await _search_text(_model(_band(272000)))
        lines = _band_lines(text)
        assert len(lines) == 1
        assert lines[0].startswith(f"- {LONG_PROMPT} (prompts above 272,000 tokens)")
        assert text.index("**Output Cost**") < text.index(LONG_PROMPT)

    @pytest.mark.asyncio
    async def test_the_exact_match_shows_the_bands_in_its_cost_information(self):
        text = await _validate_text(_model(_band(272000)))
        lines = _band_lines(text)
        assert len(lines) == 1
        assert _price(0.00002) in lines[0]
        assert text.index("- Output:") < text.index(LONG_PROMPT) < text.index("Ready for metering")

    @pytest.mark.parametrize("bands_value", [None, []])
    @pytest.mark.asyncio
    async def test_no_site_adds_text_for_a_flat_model(self, bands_value):
        model = _model()
        model["contextPricing"] = None if bands_value is None else {"bands": bands_value}
        for render in (_list_text, _search_text, _validate_text):
            assert LONG_PROMPT not in await render(model), render.__name__
