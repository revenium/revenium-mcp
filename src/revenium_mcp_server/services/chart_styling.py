"""Professional Chart Styling Templates.

Provides business-grade styling configurations for Matplotlib charts
that match modern UI design patterns and professional presentation standards.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List

try:
    from ..analytics.chart_data_formatter import ColorScheme
except ImportError:
    # Fallback for testing without full imports
    class ColorScheme(Enum):
        BUSINESS = "business"
        COST_ANALYSIS = "cost_analysis"
        PROFITABILITY = "profitability"
        TREND = "trend"
        COMPARISON = "comparison"


@dataclass
class ChartStyleConfig:
    """Configuration for professional chart styling."""

    # Color palettes
    primary_colors: List[str]
    accent_colors: List[str]
    neutral_colors: List[str]

    # Typography
    title_font_size: int = 16
    label_font_size: int = 12
    tick_font_size: int = 10
    legend_font_size: int = 10
    font_family: str = "sans-serif"

    # Layout
    figure_facecolor: str = "white"
    axes_facecolor: str = "white"
    grid_alpha: float = 0.3
    grid_color: str = "#E0E0E0"

    # Chart elements
    line_width: float = 2.5
    marker_size: float = 6
    bar_alpha: float = 0.8
    pie_start_angle: int = 90

    # Spacing
    title_pad: int = 20
    label_pad: int = 10


class BusinessStyleTemplates:
    """Professional styling templates for business charts.

    Provides pre-configured styling that matches modern business
    application design patterns and ensures professional presentation.
    """

    @staticmethod
    def get_revenium_style() -> ChartStyleConfig:
        """Get Revenium brand-specific styling configuration using official brand palette."""
        return ChartStyleConfig(
            primary_colors=[
                "#007982",  # Revenium Teal (primary brand color)
                "#13A0A6",  # Revenium Light Teal
                "#24AA8F",  # Revenium Green-Teal
                "#88D680",  # Revenium Light Green
                "#2C4959",  # Revenium Dark Blue-Gray
            ],
            accent_colors=[
                "#F9FA6E",  # Revenium Yellow (accent)
                "#007982",  # Revenium Teal (repeated for emphasis)
                "#13A0A6",  # Revenium Light Teal
                "#24AA8F",  # Revenium Green-Teal
                "#88D680",  # Revenium Light Green
            ],
            neutral_colors=[
                "#2C4959",  # Revenium Dark Blue-Gray
                "#6B7280",  # Neutral Gray 500
                "#9CA3AF",  # Neutral Gray 400
                "#D1D5DB",  # Neutral Gray 300
                "#F3F4F6",  # Neutral Gray 100
            ],
            title_font_size=16,
            label_font_size=12,
            font_family="Finlandica, system-ui, -apple-system, sans-serif",  # Revenium brand font
            figure_facecolor="white",
            axes_facecolor="white",
            grid_color="#E5E7EB",
            grid_alpha=0.3,
        )

    @staticmethod
    def get_financial_style() -> ChartStyleConfig:
        """Get financial/enterprise styling configuration."""
        return ChartStyleConfig(
            primary_colors=[
                "#1E40AF",  # Deep blue
                "#B91C1C",  # Deep red
                "#065F46",  # Deep green
                "#92400E",  # Deep orange
                "#581C87",  # Deep purple
            ],
            accent_colors=[
                "#3B82F6",  # Blue
                "#EF4444",  # Red
                "#10B981",  # Green
                "#F59E0B",  # Orange
                "#8B5CF6",  # Purple
            ],
            neutral_colors=[
                "#374151",  # Gray 700
                "#6B7280",  # Gray 500
                "#9CA3AF",  # Gray 400
                "#D1D5DB",  # Gray 300
                "#F9FAFB",  # Gray 50
            ],
            title_font_size=18,
            label_font_size=13,
            font_family="Georgia, serif",
            line_width=3.0,
            marker_size=8,
        )

    @staticmethod
    def get_modern_style() -> ChartStyleConfig:
        """Get modern/minimal styling configuration."""
        return ChartStyleConfig(
            primary_colors=[
                "#0F172A",  # Slate 900
                "#E11D48",  # Rose 600
                "#0891B2",  # Cyan 600
                "#CA8A04",  # Yellow 600
                "#9333EA",  # Violet 600
            ],
            accent_colors=[
                "#475569",  # Slate 600
                "#F43F5E",  # Rose 500
                "#06B6D4",  # Cyan 500
                "#EAB308",  # Yellow 500
                "#A855F7",  # Violet 500
            ],
            neutral_colors=[
                "#64748B",  # Slate 500
                "#94A3B8",  # Slate 400
                "#CBD5E1",  # Slate 300
                "#E2E8F0",  # Slate 200
                "#F8FAFC",  # Slate 50
            ],
            title_font_size=15,
            label_font_size=11,
            font_family="Inter, system-ui, sans-serif",
            grid_alpha=0.2,
            bar_alpha=0.9,
        )


class ChartStyler:
    """Applies professional styling to Matplotlib charts.

    Handles the application of business styling templates to chart elements
    with support for different color schemes and chart types.
    """

    def __init__(self, style_template: str = "revenium"):
        """Initialize styler with specified template.

        Args:
            style_template: Style template name (revenium, financial, modern)
        """
        self.templates = {
            "revenium": BusinessStyleTemplates.get_revenium_style(),
            "financial": BusinessStyleTemplates.get_financial_style(),
            "modern": BusinessStyleTemplates.get_modern_style(),
        }

        self.style = self.templates.get(style_template, self.templates["revenium"])

    def get_color_palette(self, color_scheme: ColorScheme) -> List[str]:
        """Get color palette for specified color scheme using Revenium brand colors.

        Args:
            color_scheme: Color scheme enum value

        Returns:
            List of hex color codes optimized for the specific use case
        """
        if color_scheme == ColorScheme.COST_ANALYSIS:
            # Warm-to-cool progression for cost analysis (yellow accent to teal)
            return ["#F9FA6E", "#88D680", "#24AA8F", "#13A0A6", "#007982"]

        elif color_scheme == ColorScheme.PROFITABILITY:
            # Green-focused palette emphasizing growth and success
            return ["#88D680", "#24AA8F", "#13A0A6", "#007982", "#2C4959"]

        elif color_scheme == ColorScheme.TREND:
            # Teal-focused palette for trend analysis
            return ["#007982", "#13A0A6", "#24AA8F", "#88D680", "#F9FA6E"]

        elif color_scheme == ColorScheme.COMPARISON:
            # High contrast colors for clear comparisons
            return ["#007982", "#F9FA6E", "#24AA8F", "#2C4959", "#13A0A6"]

        else:  # BUSINESS or default
            # Full Revenium brand palette
            return self.style.primary_colors

    def apply_matplotlib_style(self) -> Dict[str, Any]:
        """Get matplotlib rcParams for professional styling.

        Returns:
            Dictionary of matplotlib rcParams
        """
        return {
            # Figure
            "figure.facecolor": self.style.figure_facecolor,
            "figure.edgecolor": "none",
            "figure.figsize": (10, 6),
            "figure.dpi": 100,
            # Axes
            "axes.facecolor": self.style.axes_facecolor,
            "axes.edgecolor": self.style.neutral_colors[0],
            "axes.linewidth": 1.0,
            "axes.grid": True,
            "axes.axisbelow": True,
            "axes.titlesize": self.style.title_font_size,
            "axes.titleweight": "bold",
            "axes.titlepad": self.style.title_pad,
            "axes.labelsize": self.style.label_font_size,
            "axes.labelpad": self.style.label_pad,
            "axes.prop_cycle": f"cycler('color', {self.style.primary_colors})",
            # Grid
            "grid.color": self.style.grid_color,
            "grid.alpha": self.style.grid_alpha,
            "grid.linewidth": 0.8,
            # Ticks
            "xtick.labelsize": self.style.tick_font_size,
            "ytick.labelsize": self.style.tick_font_size,
            "xtick.color": self.style.neutral_colors[0],
            "ytick.color": self.style.neutral_colors[0],
            # Font
            "font.family": self.style.font_family,
            "font.size": self.style.tick_font_size,
            # Legend
            "legend.fontsize": self.style.legend_font_size,
            "legend.frameon": True,
            "legend.fancybox": True,
            "legend.shadow": False,
            "legend.framealpha": 0.9,
            "legend.facecolor": self.style.figure_facecolor,
            "legend.edgecolor": self.style.neutral_colors[2],
            # Lines
            "lines.linewidth": self.style.line_width,
            "lines.markersize": self.style.marker_size,
            "lines.markeredgewidth": 0.5,
            "lines.markeredgecolor": "white",
            # Patches (bars, pie slices, etc.)
            "patch.linewidth": 0.5,
            "patch.facecolor": self.style.primary_colors[0],
            "patch.edgecolor": "white",
            "patch.force_edgecolor": True,
        }

    def get_chart_specific_config(self, chart_type: str) -> Dict[str, Any]:
        """Get chart-type specific styling configuration.

        Args:
            chart_type: Type of chart (line, bar, pie, etc.)

        Returns:
            Chart-specific styling parameters
        """
        base_config = {
            "alpha": self.style.bar_alpha,
            "linewidth": self.style.line_width,
            "markersize": self.style.marker_size,
        }

        if chart_type == "pie":
            base_config.update(
                {
                    "startangle": self.style.pie_start_angle,
                    "autopct": "%1.1f%%",
                    "pctdistance": 0.85,
                    "explode": None,  # Can be customized per chart
                }
            )

        elif chart_type == "bar":
            base_config.update(
                {"alpha": self.style.bar_alpha, "edgecolor": "white", "linewidth": 0.5}
            )

        elif chart_type == "line":
            base_config.update(
                {
                    "linewidth": self.style.line_width,
                    "markersize": self.style.marker_size,
                    "markeredgewidth": 0.5,
                    "markeredgecolor": "white",
                }
            )

        return base_config
