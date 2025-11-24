"""Matplotlib Chart Renderer Service.

Provides local chart generation using Matplotlib for professional business charts
without external dependencies or licensing requirements.
"""

import base64
import io
import os
from dataclasses import dataclass
from typing import Optional

import matplotlib
import matplotlib.pyplot as plt
from loguru import logger
from matplotlib.axes import Axes
from matplotlib.figure import Figure

# Use non-interactive backend for server-side rendering
matplotlib.use("Agg")

from ..analytics.chart_data_formatter import ChartData, ChartType, ColorScheme
from ..common.error_handling import ErrorCodes, ToolError
from .chart_styling import ChartStyler


@dataclass
class ChartRenderConfig:
    """Configuration for chart rendering operations."""

    default_width: int = 10
    default_height: int = 6
    dpi: int = 300
    format: str = "png"
    style: str = "seaborn-v0_8"
    font_family: str = "sans-serif"


class MatplotlibChartRenderer:
    """Local chart renderer using Matplotlib for professional business charts.

    Provides high-quality chart generation without external dependencies,
    licensing requirements, or network calls. Follows Python best practices:
    - Single responsibility: chart rendering only
    - ≤25 lines per method
    - ≤4 parameters per method
    - Clear error handling
    """

    def __init__(
        self, config: Optional[ChartRenderConfig] = None, style_template: str = "revenium"
    ):
        """Initialize chart renderer with configuration.

        Args:
            config: Rendering configuration, defaults to environment-based config
            style_template: Professional styling template (revenium, financial, modern)
        """
        self.config = config or self._load_default_config()
        self.styler = ChartStyler(style_template)
        self._setup_matplotlib_style()
        logger.info(f"Initialized Matplotlib chart renderer with {style_template} styling")

    async def render_chart(
        self, chart_data: ChartData, width: Optional[int] = None, height: Optional[int] = None
    ) -> str:
        """Render chart from ChartData object to base64 encoded image.

        Args:
            chart_data: Chart data and configuration
            width: Chart width in inches (optional)
            height: Chart height in inches (optional)

        Returns:
            Base64 encoded chart image

        Raises:
            ToolError: If chart rendering fails
        """
        try:
            # Set up figure dimensions
            fig_width = width or self.config.default_width
            fig_height = height or self.config.default_height

            # Create figure and render chart
            fig, ax = plt.subplots(figsize=(fig_width, fig_height))
            self._render_chart_by_type(fig, ax, chart_data)

            # Export to base64
            return self._export_to_base64(fig)

        except Exception as e:
            logger.error(f"Chart rendering failed: {e}")
            raise ToolError(
                message=f"Failed to render chart: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="chart_rendering",
                value=chart_data.config.title,
                suggestions=[
                    "Check that chart data is properly formatted",
                    "Verify chart type is supported",
                    "Ensure data contains required fields",
                ],
            )
        finally:
            plt.close("all")  # Clean up memory

    def _render_chart_by_type(self, fig: Figure, ax: Axes, chart_data: ChartData) -> None:
        """Render chart based on chart type."""
        chart_type = chart_data.config.chart_type

        if chart_type == ChartType.LINE:
            self._render_line_chart(ax, chart_data)
        elif chart_type == ChartType.BAR:
            self._render_bar_chart(ax, chart_data)
        elif chart_type == ChartType.PIE:
            self._render_pie_chart(ax, chart_data)
        elif chart_type == ChartType.AREA:
            self._render_area_chart(ax, chart_data)
        elif chart_type == ChartType.SCATTER:
            self._render_scatter_chart(ax, chart_data)
        elif chart_type == ChartType.STACKED_BAR:
            self._render_stacked_bar_chart(ax, chart_data)
        elif chart_type == ChartType.DUAL_AXIS:
            self._render_dual_axis_chart(fig, ax, chart_data)
        elif chart_type == ChartType.DONUT:
            self._render_donut_chart(ax, chart_data)
        else:
            raise ValueError(f"Unsupported chart type: {chart_type}")

        # Apply common styling
        self._apply_chart_styling(fig, ax, chart_data)

    def _render_line_chart(self, ax: Axes, chart_data: ChartData) -> None:
        """Render line chart."""
        data = chart_data.data
        x_field = chart_data.config.x_field
        y_field = chart_data.config.y_field

        if not data:
            ax.text(0.5, 0.5, "No data available", ha="center", va="center", transform=ax.transAxes)
            return

        # Extract data
        x_values = [item.get(x_field) for item in data]
        y_values = [item.get(y_field, 0) for item in data]

        # Plot line
        line_style = "-" if chart_data.config.smooth else "-"
        ax.plot(x_values, y_values, line_style, linewidth=2, marker="o", markersize=4)

    def _render_bar_chart(self, ax: Axes, chart_data: ChartData) -> None:
        """Render bar chart."""
        data = chart_data.data
        x_field = chart_data.config.x_field
        y_field = chart_data.config.y_field

        if not data:
            ax.text(0.5, 0.5, "No data available", ha="center", va="center", transform=ax.transAxes)
            return

        # Extract data
        x_values = [str(item.get(x_field, "")) for item in data]
        y_values = [item.get(y_field, 0) for item in data]

        # Plot bars
        ax.bar(x_values, y_values)

        # Rotate x-axis labels if needed
        if len(max(x_values, key=len)) > 8:
            plt.setp(ax.get_xticklabels(), rotation=45, ha="right")

    def _render_pie_chart(self, ax: Axes, chart_data: ChartData) -> None:
        """Render pie chart."""
        data = chart_data.data

        if not data:
            ax.text(0.5, 0.5, "No data available", ha="center", va="center", transform=ax.transAxes)
            return

        # Extract data for pie chart
        labels = [str(item.get("name", item.get("category", ""))) for item in data]
        values = [item.get("value", 0) for item in data]

        # Plot pie chart
        ax.pie(values, labels=labels, autopct="%1.1f%%", startangle=90)
        ax.axis("equal")  # Equal aspect ratio ensures circular pie

    def _render_area_chart(self, ax: Axes, chart_data: ChartData) -> None:
        """Render area chart."""
        data = chart_data.data
        x_field = chart_data.config.x_field
        y_field = chart_data.config.y_field

        if not data:
            ax.text(0.5, 0.5, "No data available", ha="center", va="center", transform=ax.transAxes)
            return

        # Extract data
        x_values = [item.get(x_field) for item in data]
        y_values = [item.get(y_field, 0) for item in data]

        # Plot area
        ax.fill_between(range(len(x_values)), y_values, alpha=0.7)
        ax.plot(range(len(x_values)), y_values, linewidth=2)
        ax.set_xticks(range(len(x_values)))
        ax.set_xticklabels(x_values)

    def _render_scatter_chart(self, ax: Axes, chart_data: ChartData) -> None:
        """Render scatter chart."""
        data = chart_data.data
        x_field = chart_data.config.x_field
        y_field = chart_data.config.y_field

        if not data:
            ax.text(0.5, 0.5, "No data available", ha="center", va="center", transform=ax.transAxes)
            return

        # Extract data
        x_values = [item.get(x_field, 0) for item in data]
        y_values = [item.get(y_field, 0) for item in data]

        # Plot scatter
        ax.scatter(x_values, y_values, alpha=0.7, s=50)

    def _render_stacked_bar_chart(self, ax: Axes, chart_data: ChartData) -> None:
        """Render stacked bar chart."""
        data = chart_data.data

        if not data:
            ax.text(0.5, 0.5, "No data available", ha="center", va="center", transform=ax.transAxes)
            return

        # Group data by category and period/series
        categories = list(set(item.get("category", "") for item in data))
        series = list(set(item.get("period", item.get("series", "")) for item in data))

        # Create data matrix
        data_matrix = {}
        for category in categories:
            data_matrix[category] = {}
            for serie in series:
                data_matrix[category][serie] = 0

        # Fill data matrix
        for item in data:
            category = item.get("category", "")
            serie = item.get("period", item.get("series", ""))
            value = item.get("value", 0)
            if category in data_matrix and serie in data_matrix[category]:
                data_matrix[category][serie] = value

        # Plot stacked bars
        bottom_values = [0] * len(categories)
        for i, serie in enumerate(series):
            values = [data_matrix[cat][serie] for cat in categories]
            ax.bar(categories, values, bottom=bottom_values, label=serie)
            bottom_values = [b + v for b, v in zip(bottom_values, values)]

        if chart_data.config.show_legend:
            ax.legend()

    def _render_dual_axis_chart(self, fig: Figure, ax: Axes, chart_data: ChartData) -> None:
        """Render dual-axis chart."""
        data = chart_data.data

        if not data:
            ax.text(0.5, 0.5, "No data available", ha="center", va="center", transform=ax.transAxes)
            return

        # Extract data for dual axis
        x_values = [str(item.get("entity", "")) for item in data]
        revenue_values = [item.get("revenue", 0) for item in data]
        cost_values = [item.get("cost", 0) for item in data]

        # Plot revenue on primary axis
        color1 = "tab:blue"
        ax.set_xlabel("Entity")
        ax.set_ylabel("Revenue", color=color1)
        ax.bar(
            [x + "_revenue" for x in x_values],
            revenue_values,
            color=color1,
            alpha=0.7,
            label="Revenue",
        )
        ax.tick_params(axis="y", labelcolor=color1)

        # Create secondary axis for cost
        ax2 = ax.twinx()
        color2 = "tab:red"
        ax2.set_ylabel("Cost", color=color2)
        ax2.bar([x + "_cost" for x in x_values], cost_values, color=color2, alpha=0.7, label="Cost")
        ax2.tick_params(axis="y", labelcolor=color2)

        # Combine legends
        if chart_data.config.show_legend:
            lines1, labels1 = ax.get_legend_handles_labels()
            lines2, labels2 = ax2.get_legend_handles_labels()
            ax.legend(lines1 + lines2, labels1 + labels2, loc="upper left")

    def _render_donut_chart(self, ax: Axes, chart_data: ChartData) -> None:
        """Render donut chart (pie chart with hole in center)."""
        data = chart_data.data

        if not data:
            ax.text(0.5, 0.5, "No data available", ha="center", va="center", transform=ax.transAxes)
            return

        # Extract data for donut chart
        labels = [str(item.get("name", item.get("category", ""))) for item in data]
        values = [item.get("value", 0) for item in data]

        # Plot donut chart (pie with wedgeprops to create hole)
        wedges, texts, autotexts = ax.pie(
            values, labels=labels, autopct="%1.1f%%", startangle=90, wedgeprops=dict(width=0.5)
        )
        ax.axis("equal")  # Equal aspect ratio ensures circular donut

    def _apply_chart_styling(self, fig: Figure, ax: Axes, chart_data: ChartData) -> None:
        """Apply professional styling to chart."""
        # Set title
        ax.set_title(chart_data.config.title, fontsize=14, fontweight="bold", pad=20)

        # Set axis labels
        if chart_data.config.chart_type != ChartType.PIE:
            ax.set_xlabel(chart_data.config.x_field.replace("_", " ").title(), fontsize=12)
            ax.set_ylabel(chart_data.config.y_field.replace("_", " ").title(), fontsize=12)

        # Apply grid if enabled
        if chart_data.config.show_grid and chart_data.config.chart_type != ChartType.PIE:
            ax.grid(True, alpha=0.3)

        # Apply color scheme
        self._apply_color_scheme(ax, chart_data.config.color_scheme)

        # Tight layout
        fig.tight_layout()

    def _apply_color_scheme(self, ax: Axes, color_scheme: ColorScheme) -> None:
        """Apply color scheme to chart elements."""
        color_palettes = {
            ColorScheme.BUSINESS: ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd"],
            ColorScheme.COST_ANALYSIS: ["#d62728", "#ff7f0e", "#2ca02c", "#1f77b4", "#9467bd"],
            ColorScheme.PROFITABILITY: ["#2ca02c", "#ff7f0e", "#d62728", "#1f77b4", "#9467bd"],
            ColorScheme.TREND: ["#1f77b4", "#aec7e8", "#ffbb78", "#98df8a", "#ff9896"],
            ColorScheme.COMPARISON: ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd"],
        }

        colors = color_palettes.get(color_scheme, color_palettes[ColorScheme.BUSINESS])

        # Apply colors to chart elements
        for i, child in enumerate(ax.get_children()):
            if hasattr(child, "set_color") and i < len(colors):
                child.set_color(colors[i % len(colors)])

    def _export_to_base64(self, fig: Figure) -> str:
        """Export figure to base64 encoded string."""
        img_buffer = io.BytesIO()
        fig.savefig(
            img_buffer,
            format=self.config.format,
            dpi=self.config.dpi,
            bbox_inches="tight",
            facecolor="white",
            edgecolor="none",
        )
        img_buffer.seek(0)

        # Encode to base64
        img_base64 = base64.b64encode(img_buffer.getvalue()).decode("utf-8")
        img_buffer.close()

        return img_base64

    def _load_default_config(self) -> ChartRenderConfig:
        """Load configuration from environment variables."""
        return ChartRenderConfig(
            default_width=int(os.getenv("CHART_DEFAULT_WIDTH", "10")),
            default_height=int(os.getenv("CHART_DEFAULT_HEIGHT", "6")),
            dpi=int(os.getenv("CHART_DPI", "300")),
            format=os.getenv("CHART_FORMAT", "png").lower(),
        )

    def _setup_matplotlib_style(self) -> None:
        """Setup matplotlib style for professional charts."""
        try:
            plt.style.use(self.config.style)
        except OSError:
            # Fallback to default style if seaborn not available
            plt.style.use("default")

        # Set font family
        plt.rcParams["font.family"] = self.config.font_family
        plt.rcParams["font.size"] = 10
        plt.rcParams["axes.titlesize"] = 14
        plt.rcParams["axes.labelsize"] = 12
        plt.rcParams["xtick.labelsize"] = 10
        plt.rcParams["ytick.labelsize"] = 10
        plt.rcParams["legend.fontsize"] = 10
