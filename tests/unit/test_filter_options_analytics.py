"""Tests for analytics filter-options discovery.

Covers:
- endpoint_registry "analytics_filter_options" entry (NEW_API_ONLY, force_new)
- SimpleCostAnalyzer.get_analytics_filter_options: dimension validation,
  snake_case alias normalization, dimension-agnostic path building,
  unwrap_hal_embedded=False regression, plain-string item parsing, empty
  items, and missing-envelope handling.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.revenium_mcp_server.endpoint_registry import (
    _ENDPOINT_REGISTRY,
    get_endpoint_path,
    resolve_analytics_request,
)
from src.revenium_mcp_server.analytics.simple_cost_analyzer import (
    SimpleCostAnalyzer,
    _FILTER_OPTION_DIMENSIONS,
)
from src.revenium_mcp_server.analytics.validation import ValidationError


# ---------------------------------------------------------------------------
# Unit 1 — endpoint_registry entry
# ---------------------------------------------------------------------------


@pytest.fixture
def flag_off(monkeypatch):
    monkeypatch.delenv("REVENIUM_USE_NEW_ANALYTICS_API", raising=False)


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setenv("REVENIUM_USE_NEW_ANALYTICS_API", "true")


class TestFilterOptionsRegistryEntry:
    def test_entry_registered(self):
        assert "analytics_filter_options" in _ENDPOINT_REGISTRY

    def test_entry_is_force_new_new_api_only(self):
        config = _ENDPOINT_REGISTRY["analytics_filter_options"]
        assert config.force_new is True
        assert config.mapping_status == "NEW_API_ONLY"
        assert config.new_path == "/api/v2/analytics/filter-options"

    def test_resolves_to_new_path_with_flag_off(self, flag_off):
        assert get_endpoint_path("analytics_filter_options") == (
            "/api/v2/analytics/filter-options"
        )

    def test_resolves_to_new_path_with_flag_on(self, flag_on):
        assert get_endpoint_path("analytics_filter_options") == (
            "/api/v2/analytics/filter-options"
        )

    def test_resolve_request_uses_bearer_and_dates(self, flag_off):
        path, params, call_kwargs = resolve_analytics_request(
            "analytics_filter_options",
            team_id="team-123",
            period="THIRTY_DAYS",
        )
        # Registry stays dimension-agnostic: the analyzer appends the segment.
        assert path == "/api/v2/analytics/filter-options"
        assert call_kwargs.get("use_bearer") is True
        assert "startDate" in params and "endDate" in params
        assert "teamId" not in params
        assert "period" not in params


# ---------------------------------------------------------------------------
# Unit 2 — SimpleCostAnalyzer.get_analytics_filter_options
# ---------------------------------------------------------------------------


def _make_analyzer(get_return=None, get_side_effect=None):
    """Build a SimpleCostAnalyzer with a mocked client.get and a team_id."""
    client = MagicMock()
    client.team_id = "team-abc"
    if get_side_effect is not None:
        client.get = AsyncMock(side_effect=get_side_effect)
    else:
        client.get = AsyncMock(return_value=get_return)
    return SimpleCostAnalyzer(client), client


def _envelope(items):
    return {
        "id": "filter_options_models",
        "resourceType": "filter_options",
        "label": "Models",
        "period": "THIRTY_DAYS",
        "_embedded": {"items": items},
    }


class TestFilterOptionDimensionsConstant:
    def test_fourteen_published_dimensions(self):
        assert _FILTER_OPTION_DIMENSIONS == frozenset(
            {
                "agents",
                "api-keys",
                "customers",
                "model-sources",
                "models",
                "organizations",
                "products",
                "providers",
                "task-types",
                "teams",
                "tool-providers",
                "tools",
                "users",
                "vendors",
            }
        )


class TestGetAnalyticsFilterOptions:
    @pytest.mark.asyncio
    async def test_valid_dimension_returns_string_values(self, flag_off):
        items = ["claude-haiku-4-5-20251001", "gpt-4o", "gemini-2.0-flash"]
        analyzer, client = _make_analyzer(get_return=_envelope(items))

        result = await analyzer.get_analytics_filter_options("models", "THIRTY_DAYS")

        assert result == items
        # Dimension appended to the registry path as a segment.
        called_path = client.get.call_args[0][0]
        assert called_path == "/api/v2/analytics/filter-options/models"

    @pytest.mark.asyncio
    async def test_passes_unwrap_hal_embedded_false(self, flag_off):
        """Regression: the client's default unwrap_hal_embedded=True would
        collapse the HAL envelope and drop the plain-string items. The
        analyzer must opt out so it can parse _embedded.items itself."""
        analyzer, client = _make_analyzer(get_return=_envelope(["gpt-4o"]))

        await analyzer.get_analytics_filter_options("models", "THIRTY_DAYS")

        assert client.get.call_args.kwargs.get("unwrap_hal_embedded") is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "alias,expected_segment",
        [
            ("api_keys", "api-keys"),
            ("tool_providers", "tool-providers"),
            ("api-keys", "api-keys"),
            ("MODELS", "models"),
            ("  providers  ", "providers"),
        ],
    )
    async def test_alias_normalization(self, flag_off, alias, expected_segment):
        analyzer, client = _make_analyzer(get_return=_envelope(["x"]))

        await analyzer.get_analytics_filter_options(alias, "THIRTY_DAYS")

        called_path = client.get.call_args[0][0]
        assert called_path == f"/api/v2/analytics/filter-options/{expected_segment}"

    @pytest.mark.asyncio
    async def test_invalid_dimension_raises_and_never_calls_api(self, flag_off):
        analyzer, client = _make_analyzer(get_return=_envelope([]))

        with pytest.raises(ValidationError) as exc_info:
            await analyzer.get_analytics_filter_options("widgets", "THIRTY_DAYS")

        # The valid list is surfaced to the caller.
        suggestions_text = " ".join(exc_info.value.suggestions)
        assert "models" in suggestions_text
        assert "tool-providers" in suggestions_text
        # And the API is never hit (it 404s with a poor body).
        client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_items_returns_empty_list(self, flag_off):
        analyzer, _ = _make_analyzer(get_return=_envelope([]))

        result = await analyzer.get_analytics_filter_options("models", "THIRTY_DAYS")

        assert result == []

    @pytest.mark.asyncio
    async def test_missing_envelope_returns_empty_list(self, flag_off):
        analyzer, _ = _make_analyzer(get_return={})

        result = await analyzer.get_analytics_filter_options("models", "THIRTY_DAYS")

        assert result == []

    @pytest.mark.asyncio
    async def test_none_response_returns_empty_list(self, flag_off):
        analyzer, _ = _make_analyzer(get_return=None)

        result = await analyzer.get_analytics_filter_options("models", "THIRTY_DAYS")

        assert result == []

    @pytest.mark.asyncio
    async def test_dict_items_are_stringified_defensively(self, flag_off):
        """Items should be plain strings, but tolerate dicts by using label/id."""
        items = [
            {"label": "Claude Haiku", "id": "claude-haiku"},
            {"id": "only-id"},
            "already-a-string",
        ]
        analyzer, _ = _make_analyzer(get_return=_envelope(items))

        result = await analyzer.get_analytics_filter_options("models", "THIRTY_DAYS")

        assert result == ["Claude Haiku", "only-id", "already-a-string"]


class TestNewlyPublishedDimensions:
    """model-sources and task-types are served by the analytics API and must
    not be rejected by the client-side allowlist before the HTTP call."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("dimension", ["model-sources", "task-types"])
    async def test_new_dimension_is_accepted_and_reaches_the_api(
        self, flag_off, dimension
    ):
        analyzer, client = _make_analyzer(get_return=_envelope(["value-1"]))

        result = await analyzer.get_analytics_filter_options(dimension, "THIRTY_DAYS")

        assert result == ["value-1"]
        called_path = client.get.call_args[0][0]
        assert called_path == f"/api/v2/analytics/filter-options/{dimension}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "alias,expected_segment",
        [
            ("model_sources", "model-sources"),
            ("task_types", "task-types"),
            ("MODEL-SOURCES", "model-sources"),
            ("  task-types  ", "task-types"),
        ],
    )
    async def test_new_dimension_aliases_normalize(
        self, flag_off, alias, expected_segment
    ):
        analyzer, client = _make_analyzer(get_return=_envelope(["x"]))

        await analyzer.get_analytics_filter_options(alias, "THIRTY_DAYS")

        called_path = client.get.call_args[0][0]
        assert called_path == f"/api/v2/analytics/filter-options/{expected_segment}"

    @pytest.mark.asyncio
    async def test_unknown_dimension_still_raises_and_lists_the_new_names(
        self, flag_off
    ):
        """An unknown dimension is still rejected client-side, and the valid
        list handed back (derived from the allowlist) names both new
        dimensions so a caller can discover them from the error alone."""
        analyzer, client = _make_analyzer(get_return=_envelope([]))

        with pytest.raises(ValidationError) as exc_info:
            await analyzer.get_analytics_filter_options("widgets", "THIRTY_DAYS")

        suggestions_text = " ".join(exc_info.value.suggestions)
        assert "model-sources" in suggestions_text
        assert "task-types" in suggestions_text
        client.get.assert_not_called()


class TestFilterOptionsReviewHardening:
    """Review round: dimension-aware guidance, client-side paging, e2e plumbing."""

    def _engine_with_values(self, values):
        from src.revenium_mcp_server.analytics.simple_analytics_engine import (
            SimpleAnalyticsEngine,
        )
        from unittest.mock import AsyncMock, MagicMock

        engine = SimpleAnalyticsEngine(MagicMock())
        engine.analyzer = MagicMock()
        engine.analyzer.get_analytics_filter_options = AsyncMock(return_value=values)
        return engine

    @pytest.mark.asyncio
    async def test_guidance_is_dimension_aware(self):
        engine = self._engine_with_values(["gpt-4o"])
        text = await engine.get_filter_options(dimension="models")
        assert "filters.models" in text
        assert "filters.agents" not in text

    @pytest.mark.asyncio
    async def test_guidance_generic_for_unmapped_dimension(self):
        engine = self._engine_with_values(["t1"])
        text = await engine.get_filter_options(dimension="teams")
        assert "filter arguments" in text

    @pytest.mark.asyncio
    async def test_overflow_page_retrieves_next_slice(self):
        values = [f"v{i:03d}" for i in range(150)]
        engine = self._engine_with_values(values)
        page0 = await engine.get_filter_options(dimension="models")
        assert "v099" in page0 and "v100" not in page0
        assert "page=1" in page0  # continuation guidance
        page1 = await engine.get_filter_options(dimension="models", page=1)
        assert "v100" in page1 and "v149" in page1
        assert "v099" not in page1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_page", [-1, "-3", "abc", None])
    async def test_invalid_page_clamps_to_zero(self, bad_page):
        """Negative/garbage page values clamp to the first slice."""
        engine = self._engine_with_values([f"v{i:03d}" for i in range(120)])
        text = await engine.get_filter_options(dimension="models", page=bad_page)
        assert "v000" in text  # first slice rendered
        assert "-" not in text.split("Showing values")[1][:12] if "Showing values" in text else True

    @pytest.mark.asyncio
    async def test_page_beyond_end_renders_sane_message(self):
        """page past the last slice must not render 'values 101-100 of 40'."""
        engine = self._engine_with_values([f"v{i:02d}" for i in range(40)])
        text = await engine.get_filter_options(dimension="models", page=5)
        assert "101" not in text and "501" not in text
        assert "beyond" in text.lower() or "no values" in text.lower() or "page=0" in text

    @pytest.mark.asyncio
    async def test_dimension_plumbs_end_to_end_to_url(self):
        """Only the HTTP client is mocked: tool -> engine -> analyzer -> URL."""
        from unittest.mock import AsyncMock, MagicMock
        from src.revenium_mcp_server.tools_decomposed.business_analytics_management import (
            BusinessAnalyticsManagement,
        )

        tool = BusinessAnalyticsManagement(ucm_helper=None)
        client = MagicMock()
        client.team_id = "team-1"
        client.get = AsyncMock(return_value={"_embedded": {"items": ["gpt-4o"]}})
        tool.get_client = AsyncMock(return_value=client)

        result = await tool.handle_action(
            "get_filter_options", {"dimension": "models", "period": "SEVEN_DAYS"}
        )
        text = result[0].text
        assert "gpt-4o" in text
        called_path = client.get.call_args[0][0]
        assert called_path.endswith("/filter-options/models")
        assert client.get.call_args.kwargs.get("unwrap_hal_embedded") is False
