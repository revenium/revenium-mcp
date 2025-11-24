"""Chart data formatting utilities for analytics visualizations.

This module provides comprehensive chart data formatting capabilities inspired by
antvis/mcp-server-chart patterns, supporting multiple chart types and interactive
features for business analytics visualizations.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from loguru import logger

from ..common.error_handling import ErrorCodes, ToolError, create_structured_validation_error


class ChartType(Enum):
    """Supported chart types for analytics visualizations."""

    LINE = "line"
    BAR = "bar"
    PIE = "pie"
    AREA = "area"
    SCATTER = "scatter"
    DUAL_AXIS = "dual_axis"
    STACKED_BAR = "stacked_bar"
    DONUT = "donut"


class ColorScheme(Enum):
    """Color schemes for chart visualizations."""

    BUSINESS = "business"
    COST_ANALYSIS = "cost_analysis"
    PROFITABILITY = "profitability"
    TREND = "trend"
    COMPARISON = "comparison"


@dataclass
class ChartConfig:
    """Chart configuration settings."""

    title: str
    chart_type: ChartType
    x_field: str
    y_field: str
    color_field: Optional[str] = None
    color_scheme: ColorScheme = ColorScheme.BUSINESS
    width: int = 800
    height: int = 400
    interactive: bool = True
    show_legend: bool = True
    show_grid: bool = True
    smooth: bool = False


@dataclass
class ChartData:
    """Formatted chart data with configuration."""

    config: ChartConfig
    data: List[Dict[str, Any]]
    metadata: Dict[str, Any]
    export_options: Dict[str, Any]


class ChartDataFormatter:
    """Comprehensive chart data formatting utilities.

    Provides chart data formatting capabilities inspired by antvis/mcp-server-chart
    patterns, supporting multiple visualization types for business analytics.
    """

    def __init__(self):
        """Initialize the chart data formatter."""
        self.color_schemes = {
            ColorScheme.BUSINESS: [
                "#1f77b4",
                "#ff7f0e",
                "#2ca02c",
                "#d62728",
                "#9467bd",
                "#8c564b",
                "#e377c2",
                "#7f7f7f",
                "#bcbd22",
                "#17becf",
            ],
            ColorScheme.COST_ANALYSIS: ["#d62728", "#ff7f0e", "#ffbb78", "#ff9896", "#c5b0d5"],
            ColorScheme.PROFITABILITY: ["#2ca02c", "#98df8a", "#1f77b4", "#aec7e8", "#ffbb78"],
            ColorScheme.TREND: ["#1f77b4", "#aec7e8", "#ff7f0e", "#ffbb78"],
            ColorScheme.COMPARISON: ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"],
        }

    def format_cost_trend_chart(
        self, data: List[Dict[str, Any]], title: str = "Cost Trends Over Time"
    ) -> ChartData:
        """Format cost trend data for line chart visualization.

        Args:
            data: Cost trend data with time and cost fields
            title: Chart title

        Returns:
            Formatted chart data for cost trends

        Raises:
            ToolError: If chart formatting fails or input validation errors occur
        """
        # Input validation
        if not isinstance(data, list):
            raise create_structured_validation_error(
                message=f"Data must be a list, got {type(data).__name__}",
                field="data",
                value=str(type(data)),
                suggestions=[
                    "Provide data as a list of dictionaries",
                    "Each dictionary should contain time and cost fields",
                    "Example: [{'date': '2024-01-01', 'cost': 100.0}]",
                ],
            )

        if not data:
            # Graceful handling for empty data scenarios
            logger.warning(f"No data available for cost trend chart generation")

            # Create empty chart with helpful message
            config = ChartConfig(
                title=title or "Cost Trends - No Data Available",
                chart_type=ChartType.LINE,
                x_field="date",
                y_field="cost",
                color_scheme=ColorScheme.COST_ANALYSIS,
                smooth=True,
            )

            metadata = {
                "chart_type": "cost_trend",
                "data_points": 0,
                "date_range": {"start": "N/A", "end": "N/A"},
                "total_cost": 0.0,
                "status": "no_data_available",
                "message": "No cost data available for the requested time period",
                "suggestions": [
                    "Try a longer time period (e.g., SEVEN_DAYS instead of HOUR)",
                    "Check if there are any transactions in the selected period",
                    "Consider using THIRTY_DAYS for more comprehensive analysis",
                ],
            }

            export_options = {
                "formats": ["png", "svg", "pdf"],
                "downloadable": False,
                "interactive_features": [],
            }

            return ChartData(
                config=config, data=[], metadata=metadata, export_options=export_options
            )

        if not isinstance(title, str):
            raise create_structured_validation_error(
                message=f"Title must be a string, got {type(title).__name__}",
                field="title",
                value=str(title),
                suggestions=[
                    "Provide title as a string",
                    "Use descriptive chart titles",
                    "Example: 'Cost Trends Over Time'",
                ],
            )

        try:
            logger.info(f"Formatting cost trend chart with {len(data)} data points")

            config = ChartConfig(
                title=title,
                chart_type=ChartType.LINE,
                x_field="date",
                y_field="cost",
                color_scheme=ColorScheme.COST_ANALYSIS,
                smooth=True,
            )

            # Process and format data
            formatted_data = self._process_time_series_data(data)

            metadata = {
                "chart_type": "cost_trend",
                "data_points": len(formatted_data),
                "date_range": self._get_date_range(formatted_data),
                "total_cost": sum(item.get("cost", 0) for item in formatted_data),
            }

            export_options = {
                "formats": ["png", "svg"],
                "downloadable": True,
                "interactive_features": [],  # Static images with Matplotlib
            }

            return ChartData(
                config=config, data=formatted_data, metadata=metadata, export_options=export_options
            )

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except ToolError:

            # Re-raise ToolError exceptions without modification

            # This preserves helpful error messages with specific suggestions

            raise

        except ToolError:

            # Re-raise ToolError exceptions without modification

            # This preserves helpful error messages with specific suggestions

            raise

        except ToolError:

            # Re-raise ToolError exceptions without modification

            # This preserves helpful error messages with specific suggestions

            raise

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Cost trend chart formatting failed: {e}")
            raise ToolError(
                message=f"Failed to format cost trend chart: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="chart_formatting",
                value=f"data_points={len(data) if isinstance(data, list) else 'invalid'}",
                suggestions=[
                    "Ensure data contains valid time and cost fields",
                    "Check that all data points have required fields",
                    "Verify data format matches expected structure",
                    "Try with a smaller dataset to isolate issues",
                ],
            )

    def format_cost_breakdown_chart(
        self, data: List[Dict[str, Any]], breakdown_type: str, title: Optional[str] = None
    ) -> ChartData:
        """Format cost breakdown data for pie or bar chart visualization.

        Args:
            data: Cost breakdown data
            breakdown_type: Type of breakdown (provider, model, customer, etc.)
            title: Chart title (auto-generated if not provided)

        Returns:
            Formatted chart data for cost breakdown

        Raises:
            ToolError: If chart formatting fails or input validation errors occur
        """
        # Input validation
        if not isinstance(data, list):
            raise create_structured_validation_error(
                message=f"Data must be a list, got {type(data).__name__}",
                field="data",
                value=str(type(data)),
                suggestions=[
                    "Provide data as a list of dictionaries",
                    "Each dictionary should contain breakdown categories and values",
                    "Example: [{'provider': 'OpenAI', 'cost': 100.0}]",
                ],
            )

        if not data:
            # Graceful handling for empty breakdown data
            logger.warning(f"No data available for breakdown chart generation")

            # Create empty chart with helpful message
            config = ChartConfig(
                title=title or "Cost Breakdown - No Data Available",
                chart_type=ChartType.BAR,
                x_field="name",
                y_field="value",
                color_scheme=ColorScheme.COST_ANALYSIS,
            )

            metadata = {
                "chart_type": "cost_breakdown",
                "breakdown_type": "unknown",
                "categories": 0,
                "total_value": 0.0,
                "status": "no_data_available",
                "message": "No breakdown data available for the requested time period",
                "suggestions": [
                    "Try a longer time period to capture more data",
                    "Check if there are any transactions in the selected period",
                    "Verify that the data source contains breakdown information",
                ],
            }

            export_options = {
                "formats": ["png", "svg", "pdf"],
                "downloadable": False,
                "interactive_features": [],
            }

            return ChartData(
                config=config, data=[], metadata=metadata, export_options=export_options
            )

        if not isinstance(breakdown_type, str) or not breakdown_type.strip():
            raise create_structured_validation_error(
                message="Breakdown type must be a non-empty string",
                field="breakdown_type",
                value=breakdown_type,
                suggestions=[
                    "Use valid breakdown types: provider, model, customer, product",
                    "Ensure breakdown type is not empty",
                    "Use descriptive breakdown categories",
                ],
            )

        try:
            if title is None:
                title = f"Cost Breakdown by {breakdown_type.title()}"

            logger.info(f"Formatting cost breakdown chart for {breakdown_type}")

            # Choose chart type based on data size
            chart_type = ChartType.PIE if len(data) <= 8 else ChartType.BAR

            config = ChartConfig(
                title=title,
                chart_type=chart_type,
                x_field="category" if chart_type == ChartType.BAR else "name",
                y_field="value" if chart_type == ChartType.BAR else "value",
                color_scheme=ColorScheme.COST_ANALYSIS,
            )

            # Process and format data
            formatted_data = self._process_breakdown_data(data, breakdown_type)

            metadata = {
                "chart_type": "cost_breakdown",
                "breakdown_type": breakdown_type,
                "categories": len(formatted_data),
                "total_value": sum(item.get("value", 0) for item in formatted_data),
            }

            export_options = {
                "formats": ["png", "svg"],
                "downloadable": True,
                "interactive_features": [],  # Static images with Matplotlib
            }

            return ChartData(
                config=config, data=formatted_data, metadata=metadata, export_options=export_options
            )

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except ToolError:

            # Re-raise ToolError exceptions without modification

            # This preserves helpful error messages with specific suggestions

            raise

        except ToolError:

            # Re-raise ToolError exceptions without modification

            # This preserves helpful error messages with specific suggestions

            raise

        except ToolError:

            # Re-raise ToolError exceptions without modification

            # This preserves helpful error messages with specific suggestions

            raise

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Cost breakdown chart formatting failed: {e}")
            raise ToolError(
                message=f"Failed to format cost breakdown chart: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="chart_formatting",
                value=f"breakdown_type={breakdown_type}, data_points={len(data) if isinstance(data, list) else 'invalid'}",
                suggestions=[
                    "Ensure data contains valid breakdown categories",
                    "Check that breakdown_type matches data structure",
                    "Verify all data points have required fields",
                    "Try with a simpler breakdown type first",
                ],
            )

    def format_profitability_chart(
        self, data: List[Dict[str, Any]], entity_type: str, title: Optional[str] = None
    ) -> ChartData:
        """Format profitability data for dual-axis chart visualization.

        Args:
            data: Profitability data with revenue and cost fields
            entity_type: Type of entity (product, customer, etc.)
            title: Chart title (auto-generated if not provided)

        Returns:
            Formatted chart data for profitability analysis
        """
        if title is None:
            title = f"{entity_type.title()} Profitability Analysis"

        logger.info(f"Formatting profitability chart for {entity_type}")

        config = ChartConfig(
            title=title,
            chart_type=ChartType.DUAL_AXIS,
            x_field="entity",
            y_field="revenue",
            color_scheme=ColorScheme.PROFITABILITY,
        )

        # Process and format data for dual-axis display
        formatted_data = self._process_profitability_data(data, entity_type)

        metadata = {
            "chart_type": "profitability",
            "entity_type": entity_type,
            "entities": len(formatted_data),
            "total_revenue": sum(item.get("revenue", 0) for item in formatted_data),
            "total_cost": sum(item.get("cost", 0) for item in formatted_data),
        }

        export_options = {
            "formats": ["png", "svg", "pdf"],
            "downloadable": True,
            "interactive_features": ["zoom", "tooltip", "dual_axis_toggle"],
        }

        return ChartData(
            config=config, data=formatted_data, metadata=metadata, export_options=export_options
        )

    def format_comparison_chart(
        self,
        current_data: List[Dict[str, Any]],
        previous_data: List[Dict[str, Any]],
        comparison_type: str,
        title: Optional[str] = None,
        group: str = "TOTAL",
    ) -> ChartData:
        """Format period comparison data for stacked bar chart visualization.

        Args:
            current_data: Current period data
            previous_data: Previous period data
            comparison_type: Type of comparison (monthly, quarterly, etc.)
            title: Chart title (auto-generated if not provided)
            group: Aggregation type (TOTAL, MEAN, MAXIMUM, MINIMUM, MEDIAN)

        Returns:
            Formatted chart data for period comparison
        """
        # Note: group parameter reserved for future aggregation functionality
        if title is None:
            title = f"{comparison_type.title()} Period Comparison"

        logger.info(f"Formatting comparison chart for {comparison_type}")

        config = ChartConfig(
            title=title,
            chart_type=ChartType.STACKED_BAR,
            x_field="category",
            y_field="value",
            color_field="period",
            color_scheme=ColorScheme.COMPARISON,
        )

        # Process and format comparison data
        formatted_data = self._process_comparison_data(current_data, previous_data)

        metadata = {
            "chart_type": "comparison",
            "comparison_type": comparison_type,
            "categories": len(set(item.get("category") for item in formatted_data)),
            "periods": 2,
        }

        export_options = {
            "formats": ["png", "svg", "pdf"],
            "downloadable": True,
            "interactive_features": ["tooltip", "stack_toggle", "legend_toggle"],
        }

        return ChartData(
            config=config, data=formatted_data, metadata=metadata, export_options=export_options
        )

    def format_multi_series_chart(
        self,
        data: Dict[str, List[Dict[str, Any]]],
        title: str,
        chart_type: ChartType = ChartType.LINE,
    ) -> ChartData:
        """Format multi-series data for complex visualizations.

        Args:
            data: Dictionary of series name to data points
            title: Chart title
            chart_type: Type of chart to generate

        Returns:
            Formatted chart data for multi-series visualization
        """
        logger.info(f"Formatting multi-series {chart_type.value} chart")

        config = ChartConfig(
            title=title,
            chart_type=chart_type,
            x_field="x",
            y_field="y",
            color_field="series",
            color_scheme=ColorScheme.BUSINESS,
        )

        # Process and format multi-series data
        formatted_data = self._process_multi_series_data(data)

        metadata = {
            "chart_type": "multi_series",
            "series_count": len(data),
            "total_points": len(formatted_data),
            "series_names": list(data.keys()),
        }

        export_options = {
            "formats": ["png", "svg", "pdf"],
            "downloadable": True,
            "interactive_features": ["zoom", "pan", "tooltip", "series_toggle"],
        }

        return ChartData(
            config=config, data=formatted_data, metadata=metadata, export_options=export_options
        )

    def format_agent_cost_trends_chart(
        self, data: List[Dict[str, Any]], title: str = "Agent Cost Trends Over Time"
    ) -> ChartData:
        """Format agent cost trends data for multi-series line chart visualization.

        Args:
            data: Agent cost trend data with time, agent, and cost fields
            title: Chart title

        Returns:
            Formatted chart data for agent cost trends

        Raises:
            ToolError: If chart formatting fails or input validation errors occur
        """
        # Input validation
        if not isinstance(data, list):
            raise create_structured_validation_error(
                message=f"Data must be a list, got {type(data).__name__}",
                field="data",
                value=str(type(data)),
                suggestions=[
                    "Provide data as a list of dictionaries",
                    "Each dictionary should contain time, agent, and cost fields",
                    "Example: [{'date': '2024-01-01', 'agent': 'agent1', 'cost': 100.0}]",
                ],
            )

        if not data:
            # Graceful handling for empty agent cost trends data
            logger.warning(f"No data available for agent cost trends chart generation")

            # Create empty chart with helpful message
            config = ChartConfig(
                title=title or "Agent Cost Trends - No Data Available",
                chart_type=ChartType.LINE,
                x_field="date",
                y_field="cost",
                color_field="agent",
                color_scheme=ColorScheme.BUSINESS,
                smooth=True,
            )

            metadata = {
                "chart_type": "agent_cost_trends",
                "data_points": 0,
                "agents": 0,
                "date_range": {"start": "N/A", "end": "N/A"},
                "total_cost": 0.0,
                "status": "no_data_available",
                "message": "No agent cost trend data available for the requested time period",
                "suggestions": [
                    "Try a longer time period to capture agent activity",
                    "Check if there are any agent transactions in the selected period",
                    "Verify that agent tracking is enabled for your account",
                ],
            }

            export_options = {
                "formats": ["png", "svg", "pdf"],
                "downloadable": False,
                "interactive_features": [],
            }

            return ChartData(
                config=config, data=[], metadata=metadata, export_options=export_options
            )

        try:
            logger.info(f"Formatting agent cost trends chart with {len(data)} data points")

            config = ChartConfig(
                title=title,
                chart_type=ChartType.LINE,
                x_field="date",
                y_field="cost",
                color_field="agent",
                color_scheme=ColorScheme.BUSINESS,
                smooth=True,
            )

            # Process and format data for multi-agent visualization
            formatted_data = self._process_agent_time_series_data(data)

            metadata = {
                "chart_type": "agent_cost_trends",
                "data_points": len(formatted_data),
                "agents": len(set(item.get("agent") for item in formatted_data)),
                "date_range": self._get_date_range(formatted_data),
                "total_cost": sum(item.get("cost", 0) for item in formatted_data),
            }

            export_options = {
                "formats": ["png", "svg", "pdf"],
                "downloadable": True,
                "interactive_features": ["zoom", "pan", "tooltip", "agent_toggle"],
            }

            return ChartData(
                config=config, data=formatted_data, metadata=metadata, export_options=export_options
            )

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Agent cost trends chart formatting failed: {e}")
            raise ToolError(
                message=f"Failed to format agent cost trends chart: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="chart_formatting",
                value=f"data_points={len(data) if isinstance(data, list) else 'invalid'}",
                suggestions=[
                    "Ensure data contains valid time, agent, and cost fields",
                    "Check that all data points have required fields",
                    "Verify data format matches expected structure",
                    "Try with a smaller dataset to isolate issues",
                ],
            )

    def format_agent_performance_metrics_chart(
        self, data: List[Dict[str, Any]], title: str = "Agent Performance Metrics"
    ) -> ChartData:
        """Format agent performance metrics data for scatter plot visualization.

        Args:
            data: Agent performance data with agent, response_time, and throughput fields
            title: Chart title

        Returns:
            Formatted chart data for agent performance metrics

        Raises:
            ToolError: If chart formatting fails or input validation errors occur
        """
        # Input validation
        if not isinstance(data, list):
            raise create_structured_validation_error(
                message=f"Data must be a list, got {type(data).__name__}",
                field="data",
                value=str(type(data)),
                suggestions=[
                    "Provide data as a list of dictionaries",
                    "Each dictionary should contain agent, response_time, and throughput fields",
                    "Example: [{'agent': 'agent1', 'response_time': 100, 'throughput': 50}]",
                ],
            )

        if not data:
            raise create_structured_validation_error(
                message="Data list cannot be empty for agent performance chart",
                field="data",
                value="empty_list",
                suggestions=[
                    "Provide at least one data point",
                    "Ensure data contains agent performance information",
                    "Check that data retrieval was successful",
                ],
            )

        try:
            logger.info(f"Formatting agent performance metrics chart with {len(data)} data points")

            config = ChartConfig(
                title=title,
                chart_type=ChartType.SCATTER,
                x_field="response_time",
                y_field="throughput",
                color_field="agent",
                color_scheme=ColorScheme.BUSINESS,
            )

            # Process and format data for agent performance visualization
            formatted_data = self._process_agent_performance_data(data)

            metadata = {
                "chart_type": "agent_performance_metrics",
                "data_points": len(formatted_data),
                "agents": len(set(item.get("agent") for item in formatted_data)),
                "avg_response_time": (
                    sum(item.get("response_time", 0) for item in formatted_data)
                    / len(formatted_data)
                    if formatted_data
                    else 0
                ),
                "avg_throughput": (
                    sum(item.get("throughput", 0) for item in formatted_data) / len(formatted_data)
                    if formatted_data
                    else 0
                ),
            }

            export_options = {
                "formats": ["png", "svg", "pdf"],
                "downloadable": True,
                "interactive_features": ["zoom", "pan", "tooltip", "agent_filter"],
            }

            return ChartData(
                config=config, data=formatted_data, metadata=metadata, export_options=export_options
            )

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Agent performance metrics chart formatting failed: {e}")
            raise ToolError(
                message=f"Failed to format agent performance metrics chart: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="chart_formatting",
                value=f"data_points={len(data) if isinstance(data, list) else 'invalid'}",
                suggestions=[
                    "Ensure data contains valid agent, response_time, and throughput fields",
                    "Check that all data points have required fields",
                    "Verify data format matches expected structure",
                    "Try with a smaller dataset to isolate issues",
                ],
            )

    def format_task_completion_analysis_chart(
        self, data: List[Dict[str, Any]], title: str = "Task Completion Analysis"
    ) -> ChartData:
        """Format task completion analysis data for area chart visualization.

        Args:
            data: Task completion data with time, completed_tasks, and success_rate fields
            title: Chart title

        Returns:
            Formatted chart data for task completion analysis

        Raises:
            ToolError: If chart formatting fails or input validation errors occur
        """
        # Input validation
        if not isinstance(data, list):
            raise create_structured_validation_error(
                message=f"Data must be a list, got {type(data).__name__}",
                field="data",
                value=str(type(data)),
                suggestions=[
                    "Provide data as a list of dictionaries",
                    "Each dictionary should contain time, completed_tasks, and success_rate fields",
                    "Example: [{'date': '2024-01-01', 'completed_tasks': 100, 'success_rate': 95.5}]",
                ],
            )

        if not data:
            raise create_structured_validation_error(
                message="Data list cannot be empty for task completion chart",
                field="data",
                value="empty_list",
                suggestions=[
                    "Provide at least one data point",
                    "Ensure data contains task completion information",
                    "Check that data retrieval was successful",
                ],
            )

        try:
            logger.info(f"Formatting task completion analysis chart with {len(data)} data points")

            config = ChartConfig(
                title=title,
                chart_type=ChartType.AREA,
                x_field="date",
                y_field="completed_tasks",
                color_scheme=ColorScheme.TREND,
                smooth=True,
            )

            # Process and format data for task completion visualization
            formatted_data = self._process_task_completion_data(data)

            metadata = {
                "chart_type": "task_completion_analysis",
                "data_points": len(formatted_data),
                "date_range": self._get_date_range(formatted_data),
                "total_completed_tasks": sum(
                    item.get("completed_tasks", 0) for item in formatted_data
                ),
                "avg_success_rate": (
                    sum(item.get("success_rate", 0) for item in formatted_data)
                    / len(formatted_data)
                    if formatted_data
                    else 0
                ),
            }

            export_options = {
                "formats": ["png", "svg", "pdf"],
                "downloadable": True,
                "interactive_features": ["zoom", "pan", "tooltip", "area_fill_toggle"],
            }

            return ChartData(
                config=config, data=formatted_data, metadata=metadata, export_options=export_options
            )

        except ToolError:

            # Re-raise ToolError exceptions without modification

            # This preserves helpful error messages with specific suggestions

            raise

        except ToolError:

            # Re-raise ToolError exceptions without modification

            # This preserves helpful error messages with specific suggestions

            raise

        except ToolError:

            # Re-raise ToolError exceptions without modification

            # This preserves helpful error messages with specific suggestions

            raise

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Task completion analysis chart formatting failed: {e}")
            raise ToolError(
                message=f"Failed to format task completion analysis chart: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="chart_formatting",
                value=f"data_points={len(data) if isinstance(data, list) else 'invalid'}",
                suggestions=[
                    "Ensure data contains valid time, completed_tasks, and success_rate fields",
                    "Check that all data points have required fields",
                    "Verify data format matches expected structure",
                    "Try with a smaller dataset to isolate issues",
                ],
            )

    def format_transaction_cost_distribution_chart(
        self, data: List[Dict[str, Any]], title: str = "Transaction Cost Distribution"
    ) -> ChartData:
        """Format transaction cost distribution data for histogram visualization.

        Args:
            data: Transaction cost distribution data with cost_range and frequency fields
            title: Chart title

        Returns:
            Formatted chart data for transaction cost distribution

        Raises:
            ToolError: If chart formatting fails or input validation errors occur
        """
        # Input validation
        if not isinstance(data, list):
            raise create_structured_validation_error(
                message=f"Data must be a list, got {type(data).__name__}",
                field="data",
                value=str(type(data)),
                suggestions=[
                    "Provide data as a list of dictionaries",
                    "Each dictionary should contain cost_range and frequency fields",
                    "Example: [{'cost_range': '$0-$1', 'frequency': 100, 'percentage': 25.5}]",
                ],
            )

        if not data:
            raise create_structured_validation_error(
                message="Data list cannot be empty for transaction cost distribution chart",
                field="data",
                value="empty_list",
                suggestions=[
                    "Provide at least one data point",
                    "Ensure data contains cost distribution information",
                    "Check that data retrieval was successful",
                ],
            )

        try:
            logger.info(
                f"Formatting transaction cost distribution chart with {len(data)} data points"
            )

            config = ChartConfig(
                title=title,
                chart_type=ChartType.BAR,
                x_field="cost_range",
                y_field="frequency",
                color_scheme=ColorScheme.COST_ANALYSIS,
            )

            # Process and format data for cost distribution visualization
            formatted_data = self._process_cost_distribution_data(data)

            metadata = {
                "chart_type": "transaction_cost_distribution",
                "data_points": len(formatted_data),
                "total_transactions": sum(item.get("frequency", 0) for item in formatted_data),
                "cost_ranges": len(formatted_data),
            }

            export_options = {
                "formats": ["png", "svg", "pdf"],
                "downloadable": True,
                "interactive_features": ["tooltip", "zoom", "distribution_details"],
            }

            return ChartData(
                config=config, data=formatted_data, metadata=metadata, export_options=export_options
            )

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Transaction cost distribution chart formatting failed: {e}")
            raise ToolError(
                message=f"Failed to format transaction cost distribution chart: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="chart_formatting",
                value=f"data_points={len(data) if isinstance(data, list) else 'invalid'}",
                suggestions=[
                    "Ensure data contains valid cost_range and frequency fields",
                    "Check that all data points have required fields",
                    "Verify data format matches expected structure",
                    "Try with a smaller dataset to isolate issues",
                ],
            )

    def format_provider_task_performance_chart(
        self, data: List[Dict[str, Any]], title: str = "Provider Task Performance Comparison"
    ) -> ChartData:
        """Format provider task performance data for dual-axis chart visualization.

        Args:
            data: Provider task performance data with provider, avg_duration, and task_count fields
            title: Chart title

        Returns:
            Formatted chart data for provider task performance

        Raises:
            ToolError: If chart formatting fails or input validation errors occur
        """
        # Input validation
        if not isinstance(data, list):
            raise create_structured_validation_error(
                message=f"Data must be a list, got {type(data).__name__}",
                field="data",
                value=str(type(data)),
                suggestions=[
                    "Provide data as a list of dictionaries",
                    "Each dictionary should contain provider, avg_duration, and task_count fields",
                    "Example: [{'provider': 'OpenAI', 'avg_duration': 150, 'task_count': 1000}]",
                ],
            )

        if not data:
            raise create_structured_validation_error(
                message="Data list cannot be empty for provider task performance chart",
                field="data",
                value="empty_list",
                suggestions=[
                    "Provide at least one data point",
                    "Ensure data contains provider performance information",
                    "Check that data retrieval was successful",
                ],
            )

        try:
            logger.info(f"Formatting provider task performance chart with {len(data)} data points")

            config = ChartConfig(
                title=title,
                chart_type=ChartType.DUAL_AXIS,
                x_field="provider",
                y_field="avg_duration",
                color_scheme=ColorScheme.COMPARISON,
            )

            # Process and format data for provider performance visualization
            formatted_data = self._process_provider_performance_data(data)

            metadata = {
                "chart_type": "provider_task_performance",
                "data_points": len(formatted_data),
                "providers": len(set(item.get("provider") for item in formatted_data)),
                "total_tasks": sum(item.get("task_count", 0) for item in formatted_data),
                "avg_duration": (
                    sum(item.get("avg_duration", 0) for item in formatted_data)
                    / len(formatted_data)
                    if formatted_data
                    else 0
                ),
            }

            export_options = {
                "formats": ["png", "svg", "pdf"],
                "downloadable": True,
                "interactive_features": ["tooltip", "zoom", "dual_axis_toggle", "provider_filter"],
            }

            return ChartData(
                config=config, data=formatted_data, metadata=metadata, export_options=export_options
            )

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Provider task performance chart formatting failed: {e}")
            raise ToolError(
                message=f"Failed to format provider task performance chart: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="chart_formatting",
                value=f"data_points={len(data) if isinstance(data, list) else 'invalid'}",
                suggestions=[
                    "Ensure data contains valid provider, avg_duration, and task_count fields",
                    "Check that all data points have required fields",
                    "Verify data format matches expected structure",
                    "Try with a smaller dataset to isolate issues",
                ],
            )

    def format_model_task_efficiency_chart(
        self, data: List[Dict[str, Any]], title: str = "Model Task Efficiency Analysis"
    ) -> ChartData:
        """Format model task efficiency data for stacked bar chart visualization.

        Args:
            data: Model task efficiency data with model, efficiency_score, and cost_per_task fields
            title: Chart title

        Returns:
            Formatted chart data for model task efficiency

        Raises:
            ToolError: If chart formatting fails or input validation errors occur
        """
        # Input validation
        if not isinstance(data, list):
            raise create_structured_validation_error(
                message=f"Data must be a list, got {type(data).__name__}",
                field="data",
                value=str(type(data)),
                suggestions=[
                    "Provide data as a list of dictionaries",
                    "Each dictionary should contain model, efficiency_score, and cost_per_task fields",
                    "Example: [{'model': 'gpt-4', 'efficiency_score': 85.5, 'cost_per_task': 0.05}]",
                ],
            )

        if not data:
            raise create_structured_validation_error(
                message="Data list cannot be empty for model task efficiency chart",
                field="data",
                value="empty_list",
                suggestions=[
                    "Provide at least one data point",
                    "Ensure data contains model efficiency information",
                    "Check that data retrieval was successful",
                ],
            )

        try:
            logger.info(f"Formatting model task efficiency chart with {len(data)} data points")

            config = ChartConfig(
                title=title,
                chart_type=ChartType.STACKED_BAR,
                x_field="model",
                y_field="efficiency_score",
                color_field="efficiency_category",
                color_scheme=ColorScheme.PROFITABILITY,
            )

            # Process and format data for model efficiency visualization
            formatted_data = self._process_model_efficiency_data(data)

            metadata = {
                "chart_type": "model_task_efficiency",
                "data_points": len(formatted_data),
                "models": len(set(item.get("model") for item in formatted_data)),
                "avg_efficiency": (
                    sum(item.get("efficiency_score", 0) for item in formatted_data)
                    / len(formatted_data)
                    if formatted_data
                    else 0
                ),
                "avg_cost_per_task": (
                    sum(item.get("cost_per_task", 0) for item in formatted_data)
                    / len(formatted_data)
                    if formatted_data
                    else 0
                ),
            }

            export_options = {
                "formats": ["png", "svg", "pdf"],
                "downloadable": True,
                "interactive_features": ["tooltip", "zoom", "stack_toggle", "model_filter"],
            }

            return ChartData(
                config=config, data=formatted_data, metadata=metadata, export_options=export_options
            )

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Model task efficiency chart formatting failed: {e}")
            raise ToolError(
                message=f"Failed to format model task efficiency chart: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="chart_formatting",
                value=f"data_points={len(data) if isinstance(data, list) else 'invalid'}",
                suggestions=[
                    "Ensure data contains valid model, efficiency_score, and cost_per_task fields",
                    "Check that all data points have required fields",
                    "Verify data format matches expected structure",
                    "Try with a smaller dataset to isolate issues",
                ],
            )

    def _process_time_series_data(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process time series data for chart formatting.

        Args:
            data: Raw time series data

        Returns:
            Formatted time series data

        Raises:
            ToolError: If time series processing fails
        """
        try:
            if not isinstance(data, list):
                raise ValueError(f"Expected list, got {type(data).__name__}")

            formatted_data = []
            for i, item in enumerate(data):
                if not isinstance(item, dict):
                    raise ValueError(
                        f"Data item {i} must be a dictionary, got {type(item).__name__}"
                    )

                # Extract date/timestamp
                date_value = item.get("date") or item.get("timestamp")
                if not date_value:
                    logger.warning(f"No date/timestamp found in item {i}, using index")
                    date_value = f"Point {i}"

                # Extract cost value
                cost_value = item.get("cost", 0)
                try:
                    cost_float = float(cost_value)
                except (ValueError, TypeError):
                    logger.warning(f"Invalid cost value '{cost_value}' in item {i}, using 0")
                    cost_float = 0.0

                formatted_item = {
                    "date": self._format_date(date_value),
                    "cost": cost_float,
                    "original_data": item,
                }
                formatted_data.append(formatted_item)

            # Sort by date
            formatted_data.sort(key=lambda x: x["date"])
            return formatted_data

        except ToolError:

            # Re-raise ToolError exceptions without modification

            # This preserves helpful error messages with specific suggestions

            raise

        except ToolError:

            # Re-raise ToolError exceptions without modification

            # This preserves helpful error messages with specific suggestions

            raise

        except ToolError:

            # Re-raise ToolError exceptions without modification

            # This preserves helpful error messages with specific suggestions

            raise

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Time series data processing failed: {e}")
            raise ToolError(
                message=f"Failed to process time series data: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="time_series_processing",
                value=f"data_points={len(data) if isinstance(data, list) else 'invalid'}",
                suggestions=[
                    "Ensure each data point is a dictionary",
                    "Include 'date' or 'timestamp' fields in data",
                    "Include 'cost' field with numeric values",
                    "Check data format and structure",
                ],
            )

    def _process_breakdown_data(
        self, data: List[Dict[str, Any]], breakdown_type: str
    ) -> List[Dict[str, Any]]:
        """Process breakdown data for chart formatting.

        Args:
            data: Raw breakdown data
            breakdown_type: Type of breakdown

        Returns:
            Formatted breakdown data

        Raises:
            ToolError: If breakdown processing fails
        """
        try:
            if not isinstance(data, list):
                raise ValueError(f"Expected list, got {type(data).__name__}")
            if not isinstance(breakdown_type, str):
                raise ValueError(
                    f"Expected string breakdown_type, got {type(breakdown_type).__name__}"
                )

            formatted_data = []
            for i, item in enumerate(data):
                if not isinstance(item, dict):
                    raise ValueError(
                        f"Data item {i} must be a dictionary, got {type(item).__name__}"
                    )

                # Determine the category field based on breakdown type
                category_field = {
                    "provider": "provider",
                    "model": "model",
                    "customer": "organization",
                    "product": "product",
                }.get(breakdown_type, "category")

                # Extract value from multiple possible fields (value, cost, totalCost)
                value = item.get("value", 0) or item.get("cost", 0) or item.get("totalCost", 0)

                # Convert value to float
                try:
                    value_float = float(value)
                except (ValueError, TypeError):
                    logger.warning(f"Invalid value '{value}' in item {i}, using 0")
                    value_float = 0.0

                # Use the category field or fallback to name/category
                category_name = (
                    item.get(category_field)
                    or item.get("name")
                    or item.get("category")
                    or f"Unknown_{i}"
                )

                formatted_item = {
                    "name": str(category_name),
                    "value": value_float,
                    "category": str(category_name),
                    "original_data": item,
                }
                formatted_data.append(formatted_item)

            # Sort by value descending
            formatted_data.sort(key=lambda x: x["value"], reverse=True)
            return formatted_data

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Breakdown data processing failed: {e}")
            raise ToolError(
                message=f"Failed to process breakdown data: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="breakdown_processing",
                value=f"breakdown_type={breakdown_type}, data_points={len(data) if isinstance(data, list) else 'invalid'}",
                suggestions=[
                    "Ensure each data point is a dictionary",
                    "Include value fields (value, cost, or totalCost)",
                    "Include category fields matching breakdown type",
                    "Check data format and field names",
                ],
            )

    def _process_profitability_data(
        self, data: List[Dict[str, Any]], entity_type: str
    ) -> List[Dict[str, Any]]:
        """Process profitability data for dual-axis chart formatting."""
        formatted_data = []
        for item in data:
            revenue = float(item.get("revenue", 0))
            cost = float(item.get("cost", 0))
            profit_margin = ((revenue - cost) / revenue * 100) if revenue > 0 else 0

            formatted_item = {
                "entity": item.get(entity_type, "Unknown"),
                "revenue": revenue,
                "cost": cost,
                "profit": revenue - cost,
                "profit_margin": profit_margin,
                "original_data": item,
            }
            formatted_data.append(formatted_item)

        # Sort by revenue descending
        formatted_data.sort(key=lambda x: x["revenue"], reverse=True)
        return formatted_data

    def _process_comparison_data(
        self, current_data: List[Dict[str, Any]], previous_data: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Process comparison data for stacked chart formatting."""
        formatted_data = []

        # Process current period data
        for item in current_data:
            formatted_data.append(
                {
                    "category": item.get("category", "Unknown"),
                    "value": float(item.get("value", 0)),
                    "period": "Current",
                    "original_data": item,
                }
            )

        # Process previous period data
        for item in previous_data:
            formatted_data.append(
                {
                    "category": item.get("category", "Unknown"),
                    "value": float(item.get("value", 0)),
                    "period": "Previous",
                    "original_data": item,
                }
            )

        return formatted_data

    def _process_multi_series_data(
        self, data: Dict[str, List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        """Process multi-series data for chart formatting."""
        formatted_data = []

        for series_name, series_data in data.items():
            for item in series_data:
                formatted_data.append(
                    {
                        "x": item.get("x"),
                        "y": float(item.get("y", 0)),
                        "series": series_name,
                        "original_data": item,
                    }
                )

        return formatted_data

    def _process_agent_time_series_data(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process agent time series data for chart formatting.

        Args:
            data: Raw agent time series data

        Returns:
            Formatted agent time series data

        Raises:
            ToolError: If agent time series processing fails
        """
        try:
            if not isinstance(data, list):
                raise ValueError(f"Expected list, got {type(data).__name__}")

            formatted_data = []
            for i, item in enumerate(data):
                if not isinstance(item, dict):
                    raise ValueError(
                        f"Data item {i} must be a dictionary, got {type(item).__name__}"
                    )

                # Extract date/timestamp
                date_value = item.get("date") or item.get("timestamp")
                if not date_value:
                    logger.warning(f"No date/timestamp found in item {i}, using index")
                    date_value = f"Point {i}"

                # Extract agent identifier
                agent_value = item.get("agent") or item.get("agent_id") or f"Agent {i}"

                # Extract cost value
                cost_value = item.get("cost", 0)
                try:
                    cost_float = float(cost_value)
                except (ValueError, TypeError):
                    logger.warning(f"Invalid cost value in item {i}: {cost_value}, using 0")
                    cost_float = 0.0

                formatted_item = {
                    "date": str(date_value),
                    "agent": str(agent_value),
                    "cost": cost_float,
                }

                formatted_data.append(formatted_item)

            return formatted_data

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Agent time series data processing failed: {e}")
            raise ToolError(
                message=f"Failed to process agent time series data: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="agent_time_series_processing",
                value=f"data_points={len(data) if isinstance(data, list) else 'invalid'}",
                suggestions=[
                    "Ensure all data points have date/timestamp and agent fields",
                    "Check that cost values are numeric",
                    "Verify agent identifiers are present",
                    "Try with a smaller dataset first",
                ],
            )

    def _process_agent_performance_data(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process agent performance data for chart formatting.

        Args:
            data: Raw agent performance data

        Returns:
            Formatted agent performance data

        Raises:
            ToolError: If agent performance processing fails
        """
        try:
            if not isinstance(data, list):
                raise ValueError(f"Expected list, got {type(data).__name__}")

            formatted_data = []
            for i, item in enumerate(data):
                if not isinstance(item, dict):
                    raise ValueError(
                        f"Data item {i} must be a dictionary, got {type(item).__name__}"
                    )

                # Extract agent identifier
                agent_value = item.get("agent") or item.get("agent_id") or f"Agent {i}"

                # Extract response time
                response_time = (
                    item.get("response_time") or item.get("duration") or item.get("latency", 0)
                )
                try:
                    response_time_float = float(response_time)
                except (ValueError, TypeError):
                    logger.warning(
                        f"Invalid response_time value in item {i}: {response_time}, using 0"
                    )
                    response_time_float = 0.0

                # Extract throughput
                throughput = (
                    item.get("throughput")
                    or item.get("requests_per_minute")
                    or item.get("calls_per_minute", 0)
                )
                try:
                    throughput_float = float(throughput)
                except (ValueError, TypeError):
                    logger.warning(f"Invalid throughput value in item {i}: {throughput}, using 0")
                    throughput_float = 0.0

                formatted_item = {
                    "agent": str(agent_value),
                    "response_time": response_time_float,
                    "throughput": throughput_float,
                    "efficiency_score": (
                        throughput_float / max(response_time_float, 1)
                        if response_time_float > 0
                        else throughput_float
                    ),
                }

                formatted_data.append(formatted_item)

            return formatted_data

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Agent performance data processing failed: {e}")
            raise ToolError(
                message=f"Failed to process agent performance data: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="agent_performance_processing",
                value=f"data_points={len(data) if isinstance(data, list) else 'invalid'}",
                suggestions=[
                    "Ensure all data points have agent and performance fields",
                    "Check that response_time and throughput values are numeric",
                    "Verify agent identifiers are present",
                    "Try with a smaller dataset first",
                ],
            )

    def _process_task_completion_data(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process task completion data for chart formatting.

        Args:
            data: Raw task completion data

        Returns:
            Formatted task completion data

        Raises:
            ToolError: If task completion processing fails
        """
        try:
            if not isinstance(data, list):
                raise ValueError(f"Expected list, got {type(data).__name__}")

            formatted_data = []
            for i, item in enumerate(data):
                if not isinstance(item, dict):
                    raise ValueError(
                        f"Data item {i} must be a dictionary, got {type(item).__name__}"
                    )

                # Extract date/timestamp
                date_value = item.get("date") or item.get("timestamp")
                if not date_value:
                    logger.warning(f"No date/timestamp found in item {i}, using index")
                    date_value = f"Point {i}"

                # Extract completed tasks
                completed_tasks = (
                    item.get("completed_tasks")
                    or item.get("tasks_completed")
                    or item.get("count", 0)
                )
                try:
                    completed_tasks_int = int(completed_tasks)
                except (ValueError, TypeError):
                    logger.warning(
                        f"Invalid completed_tasks value in item {i}: {completed_tasks}, using 0"
                    )
                    completed_tasks_int = 0

                # Extract success rate
                success_rate = item.get("success_rate") or item.get("completion_rate", 0)
                try:
                    success_rate_float = float(success_rate)
                except (ValueError, TypeError):
                    logger.warning(
                        f"Invalid success_rate value in item {i}: {success_rate}, using 0"
                    )
                    success_rate_float = 0.0

                formatted_item = {
                    "date": str(date_value),
                    "completed_tasks": completed_tasks_int,
                    "success_rate": success_rate_float,
                }

                formatted_data.append(formatted_item)

            return formatted_data

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Task completion data processing failed: {e}")
            raise ToolError(
                message=f"Failed to process task completion data: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="task_completion_processing",
                value=f"data_points={len(data) if isinstance(data, list) else 'invalid'}",
                suggestions=[
                    "Ensure all data points have date/timestamp and completion fields",
                    "Check that completed_tasks and success_rate values are numeric",
                    "Verify date fields are present",
                    "Try with a smaller dataset first",
                ],
            )

    def _process_cost_distribution_data(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process cost distribution data for chart formatting.

        Args:
            data: Raw cost distribution data

        Returns:
            Formatted cost distribution data

        Raises:
            ToolError: If cost distribution processing fails
        """
        try:
            if not isinstance(data, list):
                raise ValueError(f"Expected list, got {type(data).__name__}")

            formatted_data = []
            for i, item in enumerate(data):
                if not isinstance(item, dict):
                    raise ValueError(
                        f"Data item {i} must be a dictionary, got {type(item).__name__}"
                    )

                # Extract cost range
                cost_range = item.get("cost_range") or item.get("range") or f"Range {i}"

                # Extract frequency
                frequency = item.get("frequency") or item.get("count", 0)
                try:
                    frequency_int = int(frequency)
                except (ValueError, TypeError):
                    logger.warning(f"Invalid frequency value in item {i}: {frequency}, using 0")
                    frequency_int = 0

                # Extract percentage if available
                percentage = item.get("percentage", 0)
                try:
                    percentage_float = float(percentage)
                except (ValueError, TypeError):
                    percentage_float = 0.0

                formatted_item = {
                    "cost_range": str(cost_range),
                    "frequency": frequency_int,
                    "percentage": percentage_float,
                }

                formatted_data.append(formatted_item)

            return formatted_data

        except ToolError:

            # Re-raise ToolError exceptions without modification

            # This preserves helpful error messages with specific suggestions

            raise

        except ToolError:

            # Re-raise ToolError exceptions without modification

            # This preserves helpful error messages with specific suggestions

            raise

        except ToolError:

            # Re-raise ToolError exceptions without modification

            # This preserves helpful error messages with specific suggestions

            raise

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Cost distribution data processing failed: {e}")
            raise ToolError(
                message=f"Failed to process cost distribution data: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="cost_distribution_processing",
                value=f"data_points={len(data) if isinstance(data, list) else 'invalid'}",
                suggestions=[
                    "Ensure all data points have cost_range and frequency fields",
                    "Check that frequency values are numeric",
                    "Verify cost range labels are present",
                    "Try with a smaller dataset first",
                ],
            )

    def _process_provider_performance_data(
        self, data: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Process provider performance data for chart formatting.

        Args:
            data: Raw provider performance data

        Returns:
            Formatted provider performance data

        Raises:
            ToolError: If provider performance processing fails
        """
        try:
            if not isinstance(data, list):
                raise ValueError(f"Expected list, got {type(data).__name__}")

            formatted_data = []
            for i, item in enumerate(data):
                if not isinstance(item, dict):
                    raise ValueError(
                        f"Data item {i} must be a dictionary, got {type(item).__name__}"
                    )

                # Extract provider
                provider = item.get("provider") or f"Provider {i}"

                # Extract average duration
                avg_duration = (
                    item.get("avg_duration")
                    or item.get("average_duration")
                    or item.get("duration", 0)
                )
                try:
                    avg_duration_float = float(avg_duration)
                except (ValueError, TypeError):
                    logger.warning(
                        f"Invalid avg_duration value in item {i}: {avg_duration}, using 0"
                    )
                    avg_duration_float = 0.0

                # Extract task count
                task_count = item.get("task_count") or item.get("count", 0)
                try:
                    task_count_int = int(task_count)
                except (ValueError, TypeError):
                    logger.warning(f"Invalid task_count value in item {i}: {task_count}, using 0")
                    task_count_int = 0

                formatted_item = {
                    "provider": str(provider),
                    "avg_duration": avg_duration_float,
                    "task_count": task_count_int,
                    "efficiency_ratio": (
                        task_count_int / max(avg_duration_float, 1)
                        if avg_duration_float > 0
                        else task_count_int
                    ),
                }

                formatted_data.append(formatted_item)

            return formatted_data

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Provider performance data processing failed: {e}")
            raise ToolError(
                message=f"Failed to process provider performance data: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="provider_performance_processing",
                value=f"data_points={len(data) if isinstance(data, list) else 'invalid'}",
                suggestions=[
                    "Ensure all data points have provider, avg_duration, and task_count fields",
                    "Check that duration and count values are numeric",
                    "Verify provider names are present",
                    "Try with a smaller dataset first",
                ],
            )

    def _process_model_efficiency_data(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process model efficiency data for chart formatting.

        Args:
            data: Raw model efficiency data

        Returns:
            Formatted model efficiency data

        Raises:
            ToolError: If model efficiency processing fails
        """
        try:
            if not isinstance(data, list):
                raise ValueError(f"Expected list, got {type(data).__name__}")

            formatted_data = []
            for i, item in enumerate(data):
                if not isinstance(item, dict):
                    raise ValueError(
                        f"Data item {i} must be a dictionary, got {type(item).__name__}"
                    )

                # Extract model
                model = item.get("model") or f"Model {i}"

                # Extract efficiency score
                efficiency_score = item.get("efficiency_score") or item.get("efficiency", 0)
                try:
                    efficiency_float = float(efficiency_score)
                except (ValueError, TypeError):
                    logger.warning(
                        f"Invalid efficiency_score value in item {i}: {efficiency_score}, using 0"
                    )
                    efficiency_float = 0.0

                # Extract cost per task
                cost_per_task = item.get("cost_per_task") or item.get("cost", 0)
                try:
                    cost_float = float(cost_per_task)
                except (ValueError, TypeError):
                    logger.warning(
                        f"Invalid cost_per_task value in item {i}: {cost_per_task}, using 0"
                    )
                    cost_float = 0.0

                # Categorize efficiency
                if efficiency_float >= 80:
                    efficiency_category = "High Efficiency"
                elif efficiency_float >= 60:
                    efficiency_category = "Medium Efficiency"
                else:
                    efficiency_category = "Low Efficiency"

                formatted_item = {
                    "model": str(model),
                    "efficiency_score": efficiency_float,
                    "cost_per_task": cost_float,
                    "efficiency_category": efficiency_category,
                    "value_ratio": (
                        efficiency_float / max(cost_float * 100, 1)
                        if cost_float > 0
                        else efficiency_float
                    ),
                }

                formatted_data.append(formatted_item)

            return formatted_data

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Model efficiency data processing failed: {e}")
            raise ToolError(
                message=f"Failed to process model efficiency data: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="model_efficiency_processing",
                value=f"data_points={len(data) if isinstance(data, list) else 'invalid'}",
                suggestions=[
                    "Ensure all data points have model, efficiency_score, and cost_per_task fields",
                    "Check that efficiency and cost values are numeric",
                    "Verify model names are present",
                    "Try with a smaller dataset first",
                ],
            )

    def _format_date(self, date_value: Any) -> str:
        """Format date value for chart display.

        Args:
            date_value: Date value to format

        Returns:
            Formatted date string

        Raises:
            ToolError: If date formatting fails
        """
        try:
            if isinstance(date_value, str):
                # Try to parse common date formats
                try:
                    # ISO format
                    if "T" in date_value:
                        dt = datetime.fromisoformat(date_value.replace("Z", "+00:00"))
                        return dt.strftime("%Y-%m-%d")
                    # Date only
                    elif "-" in date_value:
                        return date_value[:10]  # Take first 10 chars (YYYY-MM-DD)
                    else:
                        return str(date_value)
                except ValueError:
                    return str(date_value)
            elif isinstance(date_value, datetime):
                return date_value.strftime("%Y-%m-%d")
            else:
                return str(date_value)

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Date formatting failed: {e}")
            raise ToolError(
                message=f"Failed to format date: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="date_formatting",
                value=str(date_value),
                suggestions=[
                    "Use ISO date format (YYYY-MM-DD)",
                    "Ensure date values are valid",
                    "Check date field format in data",
                ],
            )

    def _get_date_range(self, formatted_data: List[Dict[str, Any]]) -> Dict[str, str]:
        """Get date range from formatted data.

        Args:
            formatted_data: Formatted chart data

        Returns:
            Dictionary with start and end dates

        Raises:
            ToolError: If date range calculation fails
        """
        try:
            if not formatted_data:
                return {"start": "N/A", "end": "N/A"}

            dates = [item.get("date") for item in formatted_data if item.get("date") is not None]
            if not dates:
                return {"start": "N/A", "end": "N/A"}

            # Sort dates to get range (filter out None values)
            valid_dates = [d for d in dates if d is not None]
            if not valid_dates:
                return {"start": "N/A", "end": "N/A"}

            sorted_dates = sorted(valid_dates)
            return {"start": sorted_dates[0], "end": sorted_dates[-1]}

        except ToolError:
            # Re-raise ToolError exceptions without modification
            # This preserves helpful error messages with specific suggestions
            raise
        except Exception as e:
            logger.error(f"Date range calculation failed: {e}")
            raise ToolError(
                message=f"Failed to calculate date range: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="date_range_calculation",
                value=f"data_points={len(formatted_data)}",
                suggestions=[
                    "Ensure formatted data contains valid date fields",
                    "Check date format consistency",
                    "Verify data processing was successful",
                ],
            )

    def format_comparative_analysis_chart(
        self,
        comparison_result: Any,
        chart_type: ChartType = ChartType.STACKED_BAR,
        title: Optional[str] = None,
    ) -> ChartData:
        """Format comparative analysis results for visualization.

        Args:
            comparison_result: ComparisonResult from ComparativeAnalyticsProcessor
            chart_type: Type of chart to generate
            title: Chart title (auto-generated if not provided)

        Returns:
            Formatted chart data for comparative analysis
        """
        if title is None:
            title = f"Comparative Analysis - {comparison_result.metadata.get('comparison_type', 'Analysis')}"

        logger.info(f"Formatting comparative analysis chart: {chart_type.value}")

        config = ChartConfig(
            title=title,
            chart_type=chart_type,
            x_field="category",
            y_field="value",
            color_field="period" if chart_type == ChartType.STACKED_BAR else "series",
            color_scheme=ColorScheme.COMPARISON,
        )

        # Process comparison data for visualization
        formatted_data = self._process_comparative_data(comparison_result)

        metadata = {
            "chart_type": "comparative_analysis",
            "comparison_type": comparison_result.metadata.get("comparison_type", "unknown"),
            "data_points": len(formatted_data),
            "percentage_changes": (
                [pc.__dict__ for pc in comparison_result.percentage_changes]
                if hasattr(comparison_result, "percentage_changes")
                and comparison_result.percentage_changes
                else []
            ),
            "group_parameter": comparison_result.metadata.get("group", "TOTAL"),
        }

        export_options = {
            "formats": ["png", "svg", "pdf"],
            "downloadable": True,
            "interactive_features": ["tooltip", "zoom", "legend_toggle", "comparison_details"],
        }

        return ChartData(
            config=config, data=formatted_data, metadata=metadata, export_options=export_options
        )

    def format_group_parameter_chart(
        self,
        data: List[Dict[str, Any]],
        group: str,
        metric_type: str = "cost",
        title: Optional[str] = None,
    ) -> ChartData:
        """Format data with group parameter aggregation for visualization.

        Args:
            data: Raw data to be aggregated and formatted
            group: Aggregation type (TOTAL, MEAN, MAXIMUM, MINIMUM, MEDIAN)
            metric_type: Type of metric being visualized
            title: Chart title (auto-generated if not provided)

        Returns:
            Formatted chart data with group parameter aggregation
        """
        if title is None:
            title = f"{metric_type.title()} Analysis - {group} Aggregation"

        logger.info(f"Formatting group parameter chart: {group} aggregation for {metric_type}")

        # Choose chart type based on group parameter
        chart_type = ChartType.BAR if group in ["MAXIMUM", "MINIMUM"] else ChartType.LINE

        config = ChartConfig(
            title=title,
            chart_type=chart_type,
            x_field="category" if chart_type == ChartType.BAR else "date",
            y_field="value",
            color_scheme=(
                ColorScheme.TREND if chart_type == ChartType.LINE else ColorScheme.BUSINESS
            ),
        )

        # Process data with group parameter aggregation
        formatted_data = self._process_group_parameter_data(data, group, metric_type)

        metadata = {
            "chart_type": "group_parameter",
            "group_parameter": group,
            "metric_type": metric_type,
            "data_points": len(formatted_data),
            "aggregation_applied": True,
        }

        export_options = {
            "formats": ["png", "svg", "pdf"],
            "downloadable": True,
            "interactive_features": ["tooltip", "zoom", "aggregation_details"],
        }

        return ChartData(
            config=config, data=formatted_data, metadata=metadata, export_options=export_options
        )

    def _process_comparative_data(self, comparison_result: Any) -> List[Dict[str, Any]]:
        """Process comparative analysis results for chart formatting."""
        formatted_data = []

        # Extract current and comparison data
        current_data = getattr(comparison_result, "current_data", {})
        comparison_data = getattr(comparison_result, "comparison_data", {})

        # Process current period data
        if isinstance(current_data, dict):
            for category, value in current_data.items():
                formatted_data.append(
                    {
                        "category": str(category),
                        "value": float(value) if isinstance(value, (int, float)) else 0.0,
                        "period": "Current",
                        "series": "current",
                    }
                )

        # Process comparison period data
        if isinstance(comparison_data, dict):
            for category, value in comparison_data.items():
                formatted_data.append(
                    {
                        "category": str(category),
                        "value": float(value) if isinstance(value, (int, float)) else 0.0,
                        "period": "Previous",
                        "series": "comparison",
                    }
                )

        return formatted_data

    def _process_group_parameter_data(
        self, data: List[Dict[str, Any]], group: str, metric_type: str
    ) -> List[Dict[str, Any]]:
        """Process data with group parameter aggregation."""
        formatted_data = []

        # Group data by category for aggregation
        grouped_data = {}
        for item in data:
            category = item.get("category", item.get("name", "Unknown"))
            value = item.get("value", item.get(metric_type, 0))

            if category not in grouped_data:
                grouped_data[category] = []
            grouped_data[category].append(float(value) if isinstance(value, (int, float)) else 0.0)

        # Apply group parameter aggregation
        for category, values in grouped_data.items():
            if not values:
                continue

            if group == "TOTAL":
                aggregated_value = sum(values)
            elif group == "MEAN":
                aggregated_value = sum(values) / len(values)
            elif group == "MAXIMUM":
                aggregated_value = max(values)
            elif group == "MINIMUM":
                aggregated_value = min(values)
            elif group == "MEDIAN":
                sorted_values = sorted(values)
                n = len(sorted_values)
                aggregated_value = (
                    sorted_values[n // 2]
                    if n % 2 == 1
                    else (sorted_values[n // 2 - 1] + sorted_values[n // 2]) / 2
                )
            else:
                aggregated_value = sum(values)  # Default to TOTAL

            formatted_data.append(
                {
                    "category": category,
                    "value": aggregated_value,
                    "group_parameter": group,
                    "original_count": len(values),
                }
            )

        return formatted_data
