# Chart visualization services
# Provides chart generation services for visual analytics using Matplotlib

try:
    from .matplotlib_chart_renderer import ChartRenderConfig, MatplotlibChartRenderer

    __all__ = [
        "MatplotlibChartRenderer",
        "ChartRenderConfig",
    ]
except ImportError:
    # Matplotlib not installed - provide minimal interface for testing
    from dataclasses import dataclass

    @dataclass
    class ChartRenderConfig:
        default_width: int = 10
        default_height: int = 6
        dpi: int = 300
        format: str = "png"

    __all__ = [
        "ChartRenderConfig",
    ]
