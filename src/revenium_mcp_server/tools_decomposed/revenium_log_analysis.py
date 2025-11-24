"""Revenium Log Analysis Tool for MCP Server.

This tool provides log analysis capabilities including:
- Internal system log retrieval (AI metering, email dispatch)
- Integration log analysis (Stripe, OAuth, API gateways)
- Advanced log filtering and search
- Operation pattern analysis
- Diagnostic insights and troubleshooting
"""

from typing import Any, ClassVar, Dict, List, Optional, Union

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..agent_friendly import UnifiedResponseFormatter
from ..common.error_handling import ErrorCodes, ToolError
from ..introspection.metadata import ToolType
from .log_analysis_constants import (
    CAPABILITIES_TEXT,
    DEFAULT_VALUES,
    ERROR_MESSAGES,
    EXAMPLES_TEXT,
    LOG_ENDPOINTS,
    SUGGESTIONS,
    UNSUPPORTED_ACTION_TEMPLATE,
)
from .log_filters import LogFilter
from .log_formatters import LogResponseFormatter
from .unified_tool_base import ToolBase


class ReveniumLogAnalysis(ToolBase):
    """Revenium Log Analysis Tool.

    Provides comprehensive log analysis capabilities for system troubleshooting
    and diagnostic investigation including internal logs and integration logs.
    """

    tool_name: ClassVar[str] = "revenium_log_analysis"
    tool_description: ClassVar[str] = (
        "Revenium log analysis for system troubleshooting and diagnostic investigation. Key actions: get_internal_logs, get_integration_logs, get_recent_logs, search_logs, analyze_operations. Default size: 200 records (max: 1000). Use get_examples() for usage guidance and get_capabilities() for status."
    )
    business_category: ClassVar[str] = "System & Monitoring Tools"
    tool_type: ClassVar[ToolType] = ToolType.UTILITY
    tool_version: ClassVar[str] = "1.0.0"

    def __init__(self, ucm_helper=None, config: Optional[Dict[str, Any]] = None):
        """Initialize the log analysis tool."""
        super().__init__(ucm_helper, config)
        self.formatter = UnifiedResponseFormatter("revenium_log_analysis")
        self.response_formatter = LogResponseFormatter()
        self.log_filter = LogFilter()

        # Configuration from constants
        self.log_endpoints = LOG_ENDPOINTS
        self.default_size = DEFAULT_VALUES["size"]
        self.default_sort = DEFAULT_VALUES["sort"]

    async def handle_action(
        self, action: str, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle log analysis actions."""
        try:
            return await self._route_action(action, arguments)
        except ToolError:
            # Re-raise ToolError exceptions without modification
            raise
        except Exception as e:
            raise self._create_action_error(action, e)

    async def _handle_get_capabilities(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Return summary of capabilities in log analysis suite."""
        return [TextContent(type="text", text=CAPABILITIES_TEXT)]

    async def _handle_get_examples(
        self, _arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Return examples for log analysis features."""
        return [TextContent(type="text", text=EXAMPLES_TEXT)]

    async def _handle_unsupported_action(
        self, action: str
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle requests for unsupported actions."""
        response = UNSUPPORTED_ACTION_TEMPLATE.format(action=action)
        return [TextContent(type="text", text=response)]

    def _validate_page_size(self, size: int) -> None:
        """Validate page size parameter."""
        if size > 1000:  # Test actual API limit
            raise ToolError(
                message="Page size cannot exceed 1000 records",
                error_code=ErrorCodes.INVALID_PARAMETER,
                field="size",
                value=size,
                suggestions=["Use size <= 1000", "Use pagination for larger datasets"],
            )

    async def _make_api_call(self, endpoint: str, page: int, size: int) -> Dict[str, Any]:
        """Make API call with standard parameters."""
        params = {"page": page, "size": size, "sort": self.default_sort}

        client = await self.get_client()
        params = client._add_team_id_to_params(params)
        return await client.get(endpoint, params)

    async def _get_filtered_logs(
        self,
        log_type: str,
        page: int,
        size: int,
        operation_filter: Optional[str],
        status_filter: Optional[str],
        search_term: Optional[str],
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """Get logs and apply client-side filtering."""
        # Determine endpoint
        endpoint = self.log_endpoints.get(log_type, self.log_endpoints["internal"])

        # Get raw data
        response = await self._make_api_call(endpoint, page, size)

        # Extract and filter entries
        embedded = response.get("_embedded", {})
        log_entries = embedded.get("systemLogResourceList", [])

        filtered_entries, applied_filters = self.log_filter.apply_filters(
            log_entries, operation_filter, status_filter, search_term, log_type
        )

        # Update response with filtered data
        response["_embedded"]["systemLogResourceList"] = filtered_entries
        if "page" in response:
            response["page"]["numberOfElements"] = len(filtered_entries)

        return response, applied_filters

    async def _get_multi_page_logs(self, log_type: str, pages: int) -> List[Dict[str, Any]]:
        """Retrieve logs from multiple pages and aggregate."""
        all_entries = []

        for page in range(pages):
            try:
                response = await self._make_api_call(
                    self.log_endpoints.get(log_type, self.log_endpoints["internal"]),
                    page,
                    self.default_size,
                )

                embedded = response.get("_embedded", {})
                entries = embedded.get("systemLogResourceList", [])
                all_entries.extend(entries)

                # Stop if we've reached the end
                page_info = response.get("page", {})
                if page >= page_info.get("totalPages", 1) - 1:
                    break

            except Exception as e:
                logger.warning(f"Failed to retrieve page {page}: {e}")
                break

        return all_entries

    async def _search_all_pages(
        self,
        log_type: str,
        operation_filter: Optional[str],
        status_filter: Optional[str],
        search_term: Optional[str],
        max_pages: int = 50,
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any], int]:
        """Search across all pages for comprehensive results."""
        all_matches = []
        applied_filters = {}
        total_pages_searched = 0

        logger.info(f"Starting comprehensive search across up to {max_pages} pages")

        for page in range(max_pages):
            try:
                # Get data from this page with maximum size for efficiency
                endpoint = self.log_endpoints.get(log_type, self.log_endpoints["internal"])
                response = await self._make_api_call(endpoint, page, 1000)

                # Extract entries
                embedded = response.get("_embedded", {})
                log_entries = embedded.get("systemLogResourceList", [])

                # If no entries, we've reached the end
                if not log_entries:
                    logger.info(f"Reached end of data at page {page}")
                    break

                # Apply filters to this page
                filtered_entries, page_filters = self.log_filter.apply_filters(
                    log_entries, operation_filter, status_filter, search_term, log_type
                )

                # Add matches to our collection
                all_matches.extend(filtered_entries)
                applied_filters = page_filters  # Keep the filter info
                total_pages_searched += 1

                # Log progress for searches with results
                if len(filtered_entries) > 0:
                    logger.info(f"Found {len(filtered_entries)} matches on page {page}")

                # Check if we've reached the last page
                page_info = response.get("page", {})
                if page >= page_info.get("totalPages", 1) - 1:
                    logger.info(f"Reached last page ({page_info.get('totalPages', 1)} total pages)")
                    break

            except Exception as e:
                logger.warning(f"Failed to search page {page}: {e}")
                break

        logger.info(
            f"Search complete: {len(all_matches)} total matches across {total_pages_searched} pages"
        )
        return all_matches, applied_filters, total_pages_searched

    def _analyze_operation_patterns(self, all_entries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze operation patterns and generate insights."""
        if not all_entries:
            return {"error": "No entries to analyze"}

        # Basic frequency analysis
        operation_counts = {}
        status_counts = {}
        error_patterns = {}

        for entry in all_entries:
            operation = entry.get("operation", "UNKNOWN")
            status = entry.get("status", "UNKNOWN")

            operation_counts[operation] = operation_counts.get(operation, 0) + 1
            status_counts[status] = status_counts.get(status, 0) + 1

            # Track error patterns
            if status in ["FAILURE", "ERROR"]:
                if operation not in error_patterns:
                    error_patterns[operation] = []
                error_patterns[operation].append(entry.get("details", ""))

        # Calculate insights
        total_operations = len(all_entries)
        failure_rate = (
            status_counts.get("FAILURE", 0) / total_operations if total_operations > 0 else 0
        )

        return {
            "total_operations": total_operations,
            "operation_counts": operation_counts,
            "status_counts": status_counts,
            "error_patterns": error_patterns,
            "failure_rate": failure_rate,
            "top_operations": sorted(operation_counts.items(), key=lambda x: x[1], reverse=True)[
                :5
            ],
            "problematic_operations": [
                op for op, errors in error_patterns.items() if len(errors) > 1
            ],
        }

    def _format_analysis_response(self, analysis: Dict[str, Any], log_type: str, pages: int) -> str:
        """Format operation analysis response."""
        # Handle case where no entries were found
        if "error" in analysis:
            return f"""
# Operation Pattern Analysis ({log_type.title()} Logs)

## Summary
- **Total Operations Analyzed**: 0
- **Pages Analyzed**: {pages}
- **Status**: {analysis['error']}

## Result
No log entries found for analysis. This may be expected for integration logs.

## Recommendations
- Try analyzing internal logs instead: `{{"action": "analyze_operations", "log_type": "internal"}}`
- Check if integration logs are available: `{{"action": "get_integration_logs"}}`
- Verify the log_type parameter is correct
"""

        response_text = f"""
# Operation Pattern Analysis ({log_type.title()} Logs)

## Summary
- **Total Operations Analyzed**: {analysis['total_operations']:,}
- **Pages Analyzed**: {pages}
- **Failure Rate**: {analysis['failure_rate']:.2%}
- **Unique Operations**: {len(analysis['operation_counts'])}

## Top Operations by Frequency
"""
        for operation, count in analysis["top_operations"]:
            percentage = (count / analysis["total_operations"]) * 100
            response_text += f"- **{operation}**: {count:,} ({percentage:.1f}%)\n"

        response_text += "\n## Status Distribution\n"
        for status, count in sorted(
            analysis["status_counts"].items(), key=lambda x: x[1], reverse=True
        ):
            percentage = (count / analysis["total_operations"]) * 100
            response_text += f"- **{status}**: {count:,} ({percentage:.1f}%)\n"

        if analysis["problematic_operations"]:
            response_text += "\n## Problematic Operations (Multiple Failures)\n"
            for operation in analysis["problematic_operations"]:
                error_count = len(analysis["error_patterns"][operation])
                response_text += f"- **{operation}**: {error_count} failures\n"

        response_text += "\n## Insights\n"
        if analysis["failure_rate"] > 0.1:
            response_text += (
                f"- ⚠️ High failure rate ({analysis['failure_rate']:.1%}) requires investigation\n"
            )
        if analysis["problematic_operations"]:
            response_text += f"- 🔍 {len(analysis['problematic_operations'])} operations have recurring failures\n"
        if analysis["total_operations"] > 1000:
            response_text += f"- 📊 Large dataset ({analysis['total_operations']:,} operations) provides reliable patterns\n"

        return response_text

    def _create_action_error(self, action: str, error: Exception) -> ToolError:
        """Create standardized action error."""
        logger.error(f"Unexpected error in log analysis action {action}: {error}")
        return ToolError(
            message=f"Log analysis action failed: {str(error)}",
            error_code=ErrorCodes.PROCESSING_ERROR,
            field="action",
            value=action,
            suggestions=[
                "Check the action parameters and try again",
                "Use get_capabilities() to see available actions",
                "Use get_examples() to see working examples",
            ],
        )

    async def _route_action(
        self, action: str, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Route action to appropriate handler."""
        if action == "get_capabilities":
            return await self._handle_get_capabilities()
        elif action == "get_examples":
            return await self._handle_get_examples(arguments)
        elif action == "get_internal_logs":
            return await self._handle_get_internal_logs(arguments)
        elif action == "get_integration_logs":
            return await self._handle_get_integration_logs(arguments)
        elif action == "get_recent_logs":
            return await self._handle_get_recent_logs(arguments)
        elif action == "search_logs":
            return await self._handle_search_logs(arguments)
        elif action == "analyze_operations":
            return await self._handle_analyze_operations(arguments)
        else:
            return await self._handle_unsupported_action(action)

    async def _handle_get_internal_logs(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Retrieve internal system logs."""
        page = arguments.get("page", 0)
        size = arguments.get("size", self.default_size)

        try:
            self._validate_page_size(size)
            response = await self._make_api_call(self.log_endpoints["internal"], page, size)
            return self.response_formatter.format_log_response(response, "internal", page, size)

        except ToolError:
            raise
        except Exception as e:
            logger.error(f"Failed to retrieve internal logs: {e}")
            raise ToolError(
                message=ERROR_MESSAGES["api_error"].format(log_type="internal", error=str(e)),
                error_code=ErrorCodes.API_ERROR,
                field="internal_logs",
                suggestions=SUGGESTIONS["api_connectivity"],
            )

    async def _handle_get_integration_logs(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Retrieve integration logs."""
        page = arguments.get("page", 0)
        size = arguments.get("size", self.default_size)

        try:
            self._validate_page_size(size)
            response = await self._make_api_call(self.log_endpoints["integration"], page, size)
            return self.response_formatter.format_log_response(response, "integration", page, size)

        except ToolError:
            raise
        except Exception as e:
            logger.error(f"Failed to retrieve integration logs: {e}")
            raise ToolError(
                message=ERROR_MESSAGES["api_error"].format(log_type="integration", error=str(e)),
                error_code=ErrorCodes.API_ERROR,
                field="integration_logs",
                suggestions=SUGGESTIONS["integration_logs"],
            )

    async def _handle_get_recent_logs(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Get recent activity across multiple pages."""
        pages = arguments.get("pages", 1)
        log_type = arguments.get("log_type", "internal")

        try:
            # Get entries from multiple pages
            all_entries = await self._get_multi_page_logs(log_type, pages)

            # Use formatter for multi-page response
            return self.response_formatter.format_multi_page_response(all_entries, log_type, pages)

        except ToolError:
            raise
        except Exception as e:
            logger.error(f"Failed to get recent logs: {e}")
            raise ToolError(
                message=ERROR_MESSAGES["multi_page_error"].format(error=str(e)),
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="recent_logs",
                suggestions=SUGGESTIONS["multi_page"],
            )

    async def _handle_search_logs(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Search logs with client-side filtering."""
        page = arguments.get("page", 0)
        size = arguments.get("size", self.default_size)
        log_type = arguments.get("log_type", "internal")
        search_all_pages = arguments.get("search_all_pages", False)

        try:
            if search_all_pages:
                # Comprehensive search across all pages
                all_matches, applied_filters, pages_searched = await self._search_all_pages(
                    log_type,
                    arguments.get("operation_filter"),
                    arguments.get("status_filter"),
                    arguments.get("search_term"),
                )

                # Format comprehensive search response
                return self.response_formatter.format_comprehensive_search_response(
                    all_matches, log_type, pages_searched, applied_filters
                )
            else:
                # Single page search (existing behavior)
                self._validate_page_size(size)
                response, applied_filters = await self._get_filtered_logs(
                    log_type,
                    page,
                    size,
                    arguments.get("operation_filter"),
                    arguments.get("status_filter"),
                    arguments.get("search_term"),
                )
                return self.response_formatter.format_log_response(
                    response, f"filtered_{log_type}", page, size, applied_filters
                )
        except ToolError:
            raise
        except Exception as e:
            logger.error(f"Failed to search logs: {e}")
            raise ToolError(
                message=ERROR_MESSAGES["filtering_error"].format(error=str(e)),
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="search_logs",
                suggestions=SUGGESTIONS["filtering"],
            )

    async def _handle_analyze_operations(
        self, arguments: Dict[str, Any]
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Analyze operation patterns across multiple pages."""
        log_type = arguments.get("log_type", "internal")
        pages = arguments.get("pages", 3)  # Default to 3 pages for analysis

        try:
            all_entries = await self._get_multi_page_logs(log_type, pages)
            analysis = self._analyze_operation_patterns(all_entries)
            response_text = self._format_analysis_response(analysis, log_type, pages)
            return [TextContent(type="text", text=response_text)]

        except ToolError:
            raise
        except Exception as e:
            logger.error(f"Failed to analyze operations: {e}")
            raise ToolError(
                message=f"Operation analysis failed: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="analyze_operations",
                suggestions=[
                    "Check log type parameter",
                    "Try with fewer pages",
                    "Verify API connectivity",
                ],
            )
