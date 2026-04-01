"""Unit tests for src/revenium_mcp_server/services/matplotlib_chart_renderer.py.

All matplotlib rendering calls are mocked to keep tests headless and fast.
"""

import base64
import io
import os
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from src.revenium_mcp_server.analytics.chart_data_formatter import (
    ChartConfig,
    ChartData,
    ChartType,
    ColorScheme,
)
from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError
from src.revenium_mcp_server.services.matplotlib_chart_renderer import (
    ChartRenderConfig,
    MatplotlibChartRenderer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chart_data(
    chart_type: ChartType = ChartType.LINE,
    data: list = None,
    x_field: str = "date",
    y_field: str = "value",
    title: str = "Test Chart",
    show_legend: bool = True,
    show_grid: bool = True,
    color_scheme: ColorScheme = ColorScheme.BUSINESS,
) -> ChartData:
    config = ChartConfig(
        title=title,
        chart_type=chart_type,
        x_field=x_field,
        y_field=y_field,
        show_legend=show_legend,
        show_grid=show_grid,
        color_scheme=color_scheme,
    )
    return ChartData(
        config=config,
        data=data if data is not None else [{"date": "2024-01", "value": 10}],
        metadata={},
        export_options={},
    )


def _make_renderer(style_template: str = "revenium") -> MatplotlibChartRenderer:
    """Create renderer with mocked pyplot to avoid display requirements."""
    config = ChartRenderConfig()
    with patch("src.revenium_mcp_server.services.matplotlib_chart_renderer.plt"):
        renderer = MatplotlibChartRenderer(config=config, style_template=style_template)
    return renderer


def _stub_ax() -> MagicMock:
    ax = MagicMock()
    ax.get_children.return_value = []
    ax.get_legend_handles_labels.return_value = ([], [])
    return ax


def _stub_fig() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# ChartRenderConfig dataclass
# ---------------------------------------------------------------------------

class TestChartRenderConfig:
    async def test_defaults_are_used_by_renderer_for_figsize(self):
        # The default config should produce a 10x6 figure when no dimensions are passed.
        captured_figsize = []

        def fake_subplots(figsize=None):
            captured_figsize.append(figsize)
            return (_stub_fig(), _stub_ax())

        renderer = _make_renderer()
        chart_data = _make_chart_data()
        with patch.object(renderer, "_render_chart_by_type"), \
             patch.object(renderer, "_export_to_base64", return_value="b64"), \
             patch("src.revenium_mcp_server.services.matplotlib_chart_renderer.plt") as mock_plt:
            mock_plt.subplots.side_effect = fake_subplots
            await renderer.render_chart(chart_data)
        assert captured_figsize[0] == (10, 6)

    def test_defaults_dpi_used_by_export(self):
        # The default 300 dpi must be forwarded to savefig.
        renderer = _make_renderer()
        fig = MagicMock()
        fig.savefig.side_effect = lambda buf, **kw: buf.write(b"x")
        renderer._export_to_base64(fig)
        assert fig.savefig.call_args[1]["dpi"] == 300


# ---------------------------------------------------------------------------
# MatplotlibChartRenderer.__init__ and _setup_matplotlib_style
# ---------------------------------------------------------------------------

class TestRendererInit:
    def test_init_styler_applies_requested_template(self):
        # The styler's style dict must correspond to the requested template.
        # If the template wiring were broken, the styler would use a wrong template.
        with patch("src.revenium_mcp_server.services.matplotlib_chart_renderer.plt"):
            renderer_rv = MatplotlibChartRenderer(style_template="revenium")
            renderer_fin = MatplotlibChartRenderer(style_template="financial")
        # Both should have a non-empty style dict, and the two templates differ.
        assert renderer_rv.styler.style is not None
        assert renderer_fin.styler.style is not None
        assert renderer_rv.styler.style != renderer_fin.styler.style

    def test_init_uses_provided_config(self):
        cfg = ChartRenderConfig(dpi=72)
        with patch("src.revenium_mcp_server.services.matplotlib_chart_renderer.plt"):
            renderer = MatplotlibChartRenderer(config=cfg)
        assert renderer.config.dpi == 72

    def test_setup_style_fallback_on_oserror(self):
        """When plt.style.use raises OSError, fallback to 'default' is applied."""
        with patch("src.revenium_mcp_server.services.matplotlib_chart_renderer.plt") as mock_plt:
            mock_plt.style.use.side_effect = [OSError("style not found"), None]
            mock_plt.rcParams = {}
            renderer = MatplotlibChartRenderer()
        # Both calls happened: first raising OSError, then 'default'
        assert mock_plt.style.use.call_count == 2
        second_call_arg = mock_plt.style.use.call_args_list[1][0][0]
        assert second_call_arg == "default"

    def test_rcparams_set_during_setup(self):
        rcparams = {}
        with patch("src.revenium_mcp_server.services.matplotlib_chart_renderer.plt") as mock_plt:
            mock_plt.rcParams = rcparams
            MatplotlibChartRenderer()
        assert rcparams.get("font.size") == 10
        assert rcparams.get("axes.titlesize") == 14


# ---------------------------------------------------------------------------
# _load_default_config
# ---------------------------------------------------------------------------

class TestLoadDefaultConfig:
    def test_defaults_from_environment(self, monkeypatch):
        monkeypatch.setenv("CHART_DEFAULT_WIDTH", "14")
        monkeypatch.setenv("CHART_DEFAULT_HEIGHT", "8")
        monkeypatch.setenv("CHART_DPI", "150")
        monkeypatch.setenv("CHART_FORMAT", "SVG")

        with patch("src.revenium_mcp_server.services.matplotlib_chart_renderer.plt"):
            renderer = MatplotlibChartRenderer()
        cfg = renderer.config
        assert cfg.default_width == 14
        assert cfg.default_height == 8
        assert cfg.dpi == 150
        assert cfg.format == "svg"  # lower-cased

    def test_fallback_defaults_when_env_absent(self, monkeypatch):
        monkeypatch.delenv("CHART_DEFAULT_WIDTH", raising=False)
        monkeypatch.delenv("CHART_DEFAULT_HEIGHT", raising=False)
        monkeypatch.delenv("CHART_DPI", raising=False)
        monkeypatch.delenv("CHART_FORMAT", raising=False)

        with patch("src.revenium_mcp_server.services.matplotlib_chart_renderer.plt"):
            renderer = MatplotlibChartRenderer()
        assert renderer.config.default_width == 10
        assert renderer.config.dpi == 300


# ---------------------------------------------------------------------------
# render_chart
# ---------------------------------------------------------------------------

class TestRenderChart:
    @pytest.mark.asyncio
    async def test_returns_base64_string(self):
        chart_data = _make_chart_data()

        fake_b64 = base64.b64encode(b"fake_png_data").decode("utf-8")
        renderer = _make_renderer()

        with patch.object(renderer, "_render_chart_by_type"), \
             patch.object(renderer, "_export_to_base64", return_value=fake_b64) as mock_export, \
             patch("src.revenium_mcp_server.services.matplotlib_chart_renderer.plt") as mock_plt:
            mock_plt.subplots.return_value = (_stub_fig(), _stub_ax())
            result = await renderer.render_chart(chart_data)

        assert result == fake_b64
        mock_export.assert_called_once()

    @pytest.mark.asyncio
    async def test_plt_close_called_even_on_error(self):
        chart_data = _make_chart_data()
        renderer = _make_renderer()

        with patch.object(renderer, "_render_chart_by_type", side_effect=RuntimeError("boom")), \
             patch("src.revenium_mcp_server.services.matplotlib_chart_renderer.plt") as mock_plt:
            mock_plt.subplots.return_value = (_stub_fig(), _stub_ax())
            with pytest.raises(ToolError):
                await renderer.render_chart(chart_data)
            mock_plt.close.assert_called_once_with("all")

    @pytest.mark.asyncio
    async def test_raises_tool_error_on_failure(self):
        chart_data = _make_chart_data()
        renderer = _make_renderer()

        with patch.object(renderer, "_render_chart_by_type", side_effect=ValueError("bad data")), \
             patch("src.revenium_mcp_server.services.matplotlib_chart_renderer.plt") as mock_plt:
            mock_plt.subplots.return_value = (_stub_fig(), _stub_ax())
            with pytest.raises(ToolError) as exc_info:
                await renderer.render_chart(chart_data)
        assert exc_info.value.error_code == ErrorCodes.PROCESSING_ERROR

    @pytest.mark.asyncio
    async def test_uses_custom_width_height(self):
        chart_data = _make_chart_data()
        renderer = _make_renderer()
        captured_figsize = []

        def fake_subplots(figsize=None):
            captured_figsize.append(figsize)
            return (_stub_fig(), _stub_ax())

        with patch.object(renderer, "_render_chart_by_type"), \
             patch.object(renderer, "_export_to_base64", return_value="b64"), \
             patch("src.revenium_mcp_server.services.matplotlib_chart_renderer.plt") as mock_plt:
            mock_plt.subplots.side_effect = fake_subplots
            await renderer.render_chart(chart_data, width=16, height=9)

        assert captured_figsize[0] == (16, 9)

    @pytest.mark.asyncio
    async def test_uses_default_width_height_when_not_specified(self):
        chart_data = _make_chart_data()
        renderer = _make_renderer()
        captured_figsize = []

        def fake_subplots(figsize=None):
            captured_figsize.append(figsize)
            return (_stub_fig(), _stub_ax())

        with patch.object(renderer, "_render_chart_by_type"), \
             patch.object(renderer, "_export_to_base64", return_value="b64"), \
             patch("src.revenium_mcp_server.services.matplotlib_chart_renderer.plt") as mock_plt:
            mock_plt.subplots.side_effect = fake_subplots
            await renderer.render_chart(chart_data)

        assert captured_figsize[0] == (renderer.config.default_width, renderer.config.default_height)


# ---------------------------------------------------------------------------
# _render_chart_by_type dispatch
# ---------------------------------------------------------------------------

class TestRenderChartByType:
    def _renderer(self):
        return _make_renderer()

    def test_dispatches_line_chart(self):
        renderer = self._renderer()
        ax, fig = _stub_ax(), _stub_fig()
        chart_data = _make_chart_data(ChartType.LINE)
        with patch.object(renderer, "_render_line_chart") as mock_line, \
             patch.object(renderer, "_apply_chart_styling"):
            renderer._render_chart_by_type(fig, ax, chart_data)
        mock_line.assert_called_once_with(ax, chart_data)

    def test_dispatches_bar_chart(self):
        renderer = self._renderer()
        ax, fig = _stub_ax(), _stub_fig()
        chart_data = _make_chart_data(ChartType.BAR)
        with patch.object(renderer, "_render_bar_chart") as mock_bar, \
             patch.object(renderer, "_apply_chart_styling"):
            renderer._render_chart_by_type(fig, ax, chart_data)
        mock_bar.assert_called_once_with(ax, chart_data)

    def test_dispatches_pie_chart(self):
        renderer = self._renderer()
        ax, fig = _stub_ax(), _stub_fig()
        chart_data = _make_chart_data(ChartType.PIE, data=[{"name": "A", "value": 50}])
        with patch.object(renderer, "_render_pie_chart") as mock_pie, \
             patch.object(renderer, "_apply_chart_styling"):
            renderer._render_chart_by_type(fig, ax, chart_data)
        mock_pie.assert_called_once_with(ax, chart_data)

    def test_dispatches_area_chart(self):
        renderer = self._renderer()
        ax, fig = _stub_ax(), _stub_fig()
        chart_data = _make_chart_data(ChartType.AREA)
        with patch.object(renderer, "_render_area_chart") as mock_area, \
             patch.object(renderer, "_apply_chart_styling"):
            renderer._render_chart_by_type(fig, ax, chart_data)
        mock_area.assert_called_once_with(ax, chart_data)

    def test_dispatches_scatter_chart(self):
        renderer = self._renderer()
        ax, fig = _stub_ax(), _stub_fig()
        chart_data = _make_chart_data(ChartType.SCATTER)
        with patch.object(renderer, "_render_scatter_chart") as mock_scatter, \
             patch.object(renderer, "_apply_chart_styling"):
            renderer._render_chart_by_type(fig, ax, chart_data)
        mock_scatter.assert_called_once_with(ax, chart_data)

    def test_dispatches_stacked_bar_chart(self):
        renderer = self._renderer()
        ax, fig = _stub_ax(), _stub_fig()
        chart_data = _make_chart_data(ChartType.STACKED_BAR)
        with patch.object(renderer, "_render_stacked_bar_chart") as mock_stacked, \
             patch.object(renderer, "_apply_chart_styling"):
            renderer._render_chart_by_type(fig, ax, chart_data)
        mock_stacked.assert_called_once_with(ax, chart_data)

    def test_dispatches_dual_axis_chart(self):
        renderer = self._renderer()
        ax, fig = _stub_ax(), _stub_fig()
        chart_data = _make_chart_data(ChartType.DUAL_AXIS)
        with patch.object(renderer, "_render_dual_axis_chart") as mock_dual, \
             patch.object(renderer, "_apply_chart_styling"):
            renderer._render_chart_by_type(fig, ax, chart_data)
        mock_dual.assert_called_once_with(fig, ax, chart_data)

    def test_dispatches_donut_chart(self):
        renderer = self._renderer()
        ax, fig = _stub_ax(), _stub_fig()
        chart_data = _make_chart_data(ChartType.DONUT, data=[{"name": "A", "value": 50}])
        with patch.object(renderer, "_render_donut_chart") as mock_donut, \
             patch.object(renderer, "_apply_chart_styling"):
            renderer._render_chart_by_type(fig, ax, chart_data)
        mock_donut.assert_called_once_with(ax, chart_data)

    def test_unknown_chart_type_raises(self):
        renderer = self._renderer()
        ax, fig = _stub_ax(), _stub_fig()
        chart_data = _make_chart_data(ChartType.LINE)
        chart_data.config.chart_type = "unknown_type"
        with pytest.raises(ValueError, match="Unsupported chart type"):
            renderer._render_chart_by_type(fig, ax, chart_data)


# ---------------------------------------------------------------------------
# _render_line_chart
# ---------------------------------------------------------------------------

class TestRenderLineChart:
    def test_plots_line_with_data(self):
        renderer = _make_renderer()
        ax = _stub_ax()
        data = [{"date": "2024-01", "value": 10}, {"date": "2024-02", "value": 20}]
        chart_data = _make_chart_data(ChartType.LINE, data=data)
        renderer._render_line_chart(ax, chart_data)
        ax.plot.assert_called_once()
        _, kwargs = ax.plot.call_args
        # linewidth should be 2
        assert kwargs.get("linewidth") == 2

    def test_no_data_shows_text_message(self):
        renderer = _make_renderer()
        ax = _stub_ax()
        chart_data = _make_chart_data(ChartType.LINE, data=[])
        renderer._render_line_chart(ax, chart_data)
        ax.text.assert_called_once()
        text_arg = ax.text.call_args[0][2]
        assert "No data" in text_arg

    def test_x_y_values_extracted_from_data(self):
        renderer = _make_renderer()
        ax = _stub_ax()
        data = [{"ts": "Jan", "cost": 100}, {"ts": "Feb", "cost": 200}]
        chart_data = _make_chart_data(ChartType.LINE, data=data, x_field="ts", y_field="cost")
        renderer._render_line_chart(ax, chart_data)
        call_args = ax.plot.call_args[0]
        assert list(call_args[0]) == ["Jan", "Feb"]
        assert list(call_args[1]) == [100, 200]


# ---------------------------------------------------------------------------
# _render_bar_chart
# ---------------------------------------------------------------------------

class TestRenderBarChart:
    def test_plots_bars_with_data(self):
        renderer = _make_renderer()
        ax = _stub_ax()
        data = [{"label": "A", "count": 5}, {"label": "B", "count": 10}]
        chart_data = _make_chart_data(ChartType.BAR, data=data, x_field="label", y_field="count")
        with patch("src.revenium_mcp_server.services.matplotlib_chart_renderer.plt"):
            renderer._render_bar_chart(ax, chart_data)
        ax.bar.assert_called_once()

    def test_no_data_shows_text_message(self):
        renderer = _make_renderer()
        ax = _stub_ax()
        chart_data = _make_chart_data(ChartType.BAR, data=[])
        with patch("src.revenium_mcp_server.services.matplotlib_chart_renderer.plt"):
            renderer._render_bar_chart(ax, chart_data)
        ax.text.assert_called_once()

    def test_long_labels_rotate_xticklabels(self):
        renderer = _make_renderer()
        ax = _stub_ax()
        # Label longer than 8 chars triggers rotation
        data = [{"label": "LongLabel1", "value": 1}, {"label": "LongLabel2", "value": 2}]
        chart_data = _make_chart_data(ChartType.BAR, data=data, x_field="label", y_field="value")
        with patch("src.revenium_mcp_server.services.matplotlib_chart_renderer.plt") as mock_plt:
            renderer._render_bar_chart(ax, chart_data)
        mock_plt.setp.assert_called_once()


# ---------------------------------------------------------------------------
# _render_pie_chart
# ---------------------------------------------------------------------------

class TestRenderPieChart:
    def test_plots_pie_with_data(self):
        renderer = _make_renderer()
        ax = _stub_ax()
        data = [{"name": "A", "value": 60}, {"name": "B", "value": 40}]
        chart_data = _make_chart_data(ChartType.PIE, data=data)
        renderer._render_pie_chart(ax, chart_data)
        ax.pie.assert_called_once()
        ax.axis.assert_called_once_with("equal")

    def test_no_data_shows_text_message(self):
        renderer = _make_renderer()
        ax = _stub_ax()
        chart_data = _make_chart_data(ChartType.PIE, data=[])
        renderer._render_pie_chart(ax, chart_data)
        ax.text.assert_called_once()

    def test_category_used_when_name_absent(self):
        renderer = _make_renderer()
        ax = _stub_ax()
        data = [{"category": "X", "value": 100}]
        chart_data = _make_chart_data(ChartType.PIE, data=data)
        renderer._render_pie_chart(ax, chart_data)
        call_kwargs = ax.pie.call_args[1]
        assert "X" in call_kwargs["labels"]


# ---------------------------------------------------------------------------
# _render_area_chart
# ---------------------------------------------------------------------------

class TestRenderAreaChart:
    def test_fills_between_with_data(self):
        renderer = _make_renderer()
        ax = _stub_ax()
        data = [{"ts": "Jan", "val": 5}, {"ts": "Feb", "val": 8}]
        chart_data = _make_chart_data(ChartType.AREA, data=data, x_field="ts", y_field="val")
        renderer._render_area_chart(ax, chart_data)
        ax.fill_between.assert_called_once()
        ax.plot.assert_called_once()

    def test_no_data_shows_text_message(self):
        renderer = _make_renderer()
        ax = _stub_ax()
        chart_data = _make_chart_data(ChartType.AREA, data=[])
        renderer._render_area_chart(ax, chart_data)
        ax.text.assert_called_once()

    def test_xticks_set_to_index_range_for_data(self):
        # set_xticks must receive range(len(data)) so axis positions match data points.
        renderer = _make_renderer()
        ax = _stub_ax()
        data = [{"ts": "Jan", "val": 5}, {"ts": "Feb", "val": 8}]
        chart_data = _make_chart_data(ChartType.AREA, data=data, x_field="ts", y_field="val")
        renderer._render_area_chart(ax, chart_data)
        ax.set_xticks.assert_called_once_with(range(2))


# ---------------------------------------------------------------------------
# _render_scatter_chart
# ---------------------------------------------------------------------------

class TestRenderScatterChart:
    def test_plots_scatter_with_data(self):
        renderer = _make_renderer()
        ax = _stub_ax()
        data = [{"x": 1, "y": 2}, {"x": 3, "y": 4}]
        chart_data = _make_chart_data(ChartType.SCATTER, data=data, x_field="x", y_field="y")
        renderer._render_scatter_chart(ax, chart_data)
        ax.scatter.assert_called_once()
        _, kwargs = ax.scatter.call_args
        assert kwargs.get("alpha") == 0.7

    def test_no_data_shows_text_message(self):
        renderer = _make_renderer()
        ax = _stub_ax()
        chart_data = _make_chart_data(ChartType.SCATTER, data=[])
        renderer._render_scatter_chart(ax, chart_data)
        ax.text.assert_called_once()


# ---------------------------------------------------------------------------
# _render_stacked_bar_chart
# ---------------------------------------------------------------------------

class TestRenderStackedBarChart:
    def test_plots_stacked_bars_with_data(self):
        renderer = _make_renderer()
        ax = _stub_ax()
        data = [
            {"category": "A", "period": "Q1", "value": 10},
            {"category": "A", "period": "Q2", "value": 20},
            {"category": "B", "period": "Q1", "value": 15},
            {"category": "B", "period": "Q2", "value": 25},
        ]
        chart_data = _make_chart_data(ChartType.STACKED_BAR, data=data, show_legend=True)
        renderer._render_stacked_bar_chart(ax, chart_data)
        assert ax.bar.call_count == 2  # two series (Q1, Q2)
        ax.legend.assert_called_once()

    def test_no_data_shows_text_message(self):
        renderer = _make_renderer()
        ax = _stub_ax()
        chart_data = _make_chart_data(ChartType.STACKED_BAR, data=[])
        renderer._render_stacked_bar_chart(ax, chart_data)
        ax.text.assert_called_once()

    def test_legend_not_shown_when_disabled(self):
        renderer = _make_renderer()
        ax = _stub_ax()
        data = [{"category": "A", "period": "Q1", "value": 10}]
        chart_data = _make_chart_data(ChartType.STACKED_BAR, data=data, show_legend=False)
        renderer._render_stacked_bar_chart(ax, chart_data)
        ax.legend.assert_not_called()


# ---------------------------------------------------------------------------
# _render_dual_axis_chart
# ---------------------------------------------------------------------------

class TestRenderDualAxisChart:
    def test_creates_secondary_axis(self):
        renderer = _make_renderer()
        ax = _stub_ax()
        ax2 = _stub_ax()
        ax.twinx.return_value = ax2
        fig = _stub_fig()
        data = [{"entity": "ModelA", "revenue": 1000, "cost": 200}]
        chart_data = _make_chart_data(ChartType.DUAL_AXIS, data=data, show_legend=True)
        renderer._render_dual_axis_chart(fig, ax, chart_data)
        ax.twinx.assert_called_once()
        # Both axes should have bar called
        ax.bar.assert_called_once()
        ax2.bar.assert_called_once()

    def test_no_data_shows_text_message(self):
        renderer = _make_renderer()
        ax = _stub_ax()
        fig = _stub_fig()
        chart_data = _make_chart_data(ChartType.DUAL_AXIS, data=[])
        renderer._render_dual_axis_chart(fig, ax, chart_data)
        ax.text.assert_called_once()

    def test_legend_not_combined_when_disabled(self):
        renderer = _make_renderer()
        ax = _stub_ax()
        ax2 = _stub_ax()
        ax.twinx.return_value = ax2
        fig = _stub_fig()
        data = [{"entity": "A", "revenue": 100, "cost": 50}]
        chart_data = _make_chart_data(ChartType.DUAL_AXIS, data=data, show_legend=False)
        renderer._render_dual_axis_chart(fig, ax, chart_data)
        ax.legend.assert_not_called()


# ---------------------------------------------------------------------------
# _render_donut_chart
# ---------------------------------------------------------------------------

class TestRenderDonutChart:
    def test_plots_donut_with_wedgeprops(self):
        renderer = _make_renderer()
        ax = _stub_ax()
        # pie needs to return a 3-tuple
        ax.pie.return_value = ([], [], [])
        data = [{"name": "Slice1", "value": 70}, {"name": "Slice2", "value": 30}]
        chart_data = _make_chart_data(ChartType.DONUT, data=data)
        renderer._render_donut_chart(ax, chart_data)
        ax.pie.assert_called_once()
        call_kwargs = ax.pie.call_args[1]
        # width=0.5 creates the hole
        assert call_kwargs["wedgeprops"]["width"] == 0.5
        ax.axis.assert_called_once_with("equal")

    def test_no_data_shows_text_message(self):
        renderer = _make_renderer()
        ax = _stub_ax()
        chart_data = _make_chart_data(ChartType.DONUT, data=[])
        renderer._render_donut_chart(ax, chart_data)
        ax.text.assert_called_once()


# ---------------------------------------------------------------------------
# _apply_chart_styling
# ---------------------------------------------------------------------------

class TestApplyChartStyling:
    def test_sets_title(self):
        renderer = _make_renderer()
        ax = _stub_ax()
        fig = _stub_fig()
        chart_data = _make_chart_data(title="My Title")
        with patch.object(renderer, "_apply_color_scheme"):
            renderer._apply_chart_styling(fig, ax, chart_data)
        ax.set_title.assert_called_once_with("My Title", fontsize=14, fontweight="bold", pad=20)

    def test_grid_applied_for_non_pie(self):
        renderer = _make_renderer()
        ax = _stub_ax()
        fig = _stub_fig()
        chart_data = _make_chart_data(ChartType.LINE, show_grid=True)
        with patch.object(renderer, "_apply_color_scheme"):
            renderer._apply_chart_styling(fig, ax, chart_data)
        ax.grid.assert_called_once_with(True, alpha=0.3)

    def test_grid_not_applied_for_pie(self):
        renderer = _make_renderer()
        ax = _stub_ax()
        fig = _stub_fig()
        chart_data = _make_chart_data(ChartType.PIE, show_grid=True, data=[{"name": "A", "value": 1}])
        with patch.object(renderer, "_apply_color_scheme"):
            renderer._apply_chart_styling(fig, ax, chart_data)
        ax.grid.assert_not_called()

    def test_axis_labels_not_set_for_pie(self):
        renderer = _make_renderer()
        ax = _stub_ax()
        fig = _stub_fig()
        chart_data = _make_chart_data(ChartType.PIE, data=[{"name": "A", "value": 1}])
        with patch.object(renderer, "_apply_color_scheme"):
            renderer._apply_chart_styling(fig, ax, chart_data)
        ax.set_xlabel.assert_not_called()
        ax.set_ylabel.assert_not_called()

    def test_axis_labels_set_for_non_pie(self):
        renderer = _make_renderer()
        ax = _stub_ax()
        fig = _stub_fig()
        chart_data = _make_chart_data(ChartType.LINE, x_field="my_date", y_field="total_cost")
        with patch.object(renderer, "_apply_color_scheme"):
            renderer._apply_chart_styling(fig, ax, chart_data)
        ax.set_xlabel.assert_called_once()
        ax.set_ylabel.assert_called_once()

    def test_tight_layout_called(self):
        renderer = _make_renderer()
        ax = _stub_ax()
        fig = _stub_fig()
        chart_data = _make_chart_data()
        with patch.object(renderer, "_apply_color_scheme"):
            renderer._apply_chart_styling(fig, ax, chart_data)
        fig.tight_layout.assert_called_once()

    def test_grid_not_applied_when_show_grid_false(self):
        renderer = _make_renderer()
        ax = _stub_ax()
        fig = _stub_fig()
        chart_data = _make_chart_data(ChartType.LINE, show_grid=False)
        with patch.object(renderer, "_apply_color_scheme"):
            renderer._apply_chart_styling(fig, ax, chart_data)
        ax.grid.assert_not_called()


# ---------------------------------------------------------------------------
# _apply_color_scheme
# ---------------------------------------------------------------------------

class TestApplyColorScheme:
    def test_applies_colors_to_children(self):
        renderer = _make_renderer()
        ax = _stub_ax()
        child = MagicMock()
        child.set_color = MagicMock()
        ax.get_children.return_value = [child]
        renderer._apply_color_scheme(ax, ColorScheme.BUSINESS)
        child.set_color.assert_called_once()

    def test_trend_scheme_applies_a_color_from_its_palette(self):
        # TREND is a known scheme; its palette must be applied to children with set_color.
        # The production code maps ColorScheme.TREND to a specific palette — verify the
        # color applied is from that palette (starts with "#"), not arbitrary.
        renderer = _make_renderer()
        ax = _stub_ax()
        child = MagicMock()
        ax.get_children.return_value = [child]
        renderer._apply_color_scheme(ax, ColorScheme.TREND)
        child.set_color.assert_called_once()
        applied_color = child.set_color.call_args[0][0]
        assert applied_color.startswith("#"), f"Expected a hex color, got: {applied_color}"

    def test_child_without_set_color_is_skipped(self):
        renderer = _make_renderer()
        ax = _stub_ax()
        child = MagicMock(spec=[])  # no set_color attribute
        ax.get_children.return_value = [child]
        # Should not raise
        renderer._apply_color_scheme(ax, ColorScheme.BUSINESS)

    def test_all_color_schemes_are_handled(self):
        renderer = _make_renderer()
        ax = _stub_ax()
        ax.get_children.return_value = []
        for scheme in ColorScheme:
            renderer._apply_color_scheme(ax, scheme)  # must not raise


# ---------------------------------------------------------------------------
# _export_to_base64
# ---------------------------------------------------------------------------

class TestExportToBase64:
    def test_returns_valid_base64_string(self):
        renderer = _make_renderer()
        fig = MagicMock()
        fake_bytes = b"fake_image_bytes"

        def fake_savefig(buffer, **kwargs):
            buffer.write(fake_bytes)

        fig.savefig.side_effect = fake_savefig
        result = renderer._export_to_base64(fig)
        decoded = base64.b64decode(result)
        assert decoded == fake_bytes

    def test_savefig_called_with_correct_kwargs(self):
        renderer = _make_renderer()
        fig = MagicMock()
        fig.savefig.side_effect = lambda buf, **kw: buf.write(b"x")
        renderer._export_to_base64(fig)
        call_kwargs = fig.savefig.call_args[1]
        assert call_kwargs["format"] == renderer.config.format
        assert call_kwargs["dpi"] == renderer.config.dpi
        assert call_kwargs["bbox_inches"] == "tight"
