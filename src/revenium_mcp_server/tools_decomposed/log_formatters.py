"""Log response formatting utilities for Revenium Log Analysis Tool.

This module contains all response formatting logic extracted from the main
tool class to comply with the 300-line module limit requirement.
"""

from typing import Any, Dict, List, NamedTuple, Optional, Union

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..analytics.paging import PageInfo, counted
from ..common.error_handling import ErrorCodes, ToolError
from .log_filters import CONTENT_FILTER_KEYS


class PageCoverage(NamedTuple):
    """How much of the platform's paged log list a walk read, and why it stopped."""

    pages_read: int
    entries_read: int
    platform: PageInfo
    failed_page: Optional[int] = None  # 0-based
    failure: Optional[str] = None
    page_limit: Optional[int] = None

    @property
    def pages_left(self) -> Optional[int]:
        if self.platform.total_pages is None:
            return None
        return max(self.platform.total_pages - self.pages_read, 0)

    @property
    def complete(self) -> bool:
        """True only when every page up to the platform's last was read; never on an unknown total."""
        return self.failed_page is None and self.pages_left == 0

    def failure_note(self) -> Optional[str]:
        if self.failed_page is None:
            return None
        return (
            f"page {self.failed_page + 1} (page={self.failed_page}) failed ({self.failure}); "
            f"results cover {counted(self.pages_read, 'page', 'pages')}"
        )


def _of_total(read: str, total: Optional[int], spec: str = "") -> str:
    return f"{read} of {'an unknown number' if total is None else format(total, spec)}"


class LogResponseFormatter:
    """Handles formatting of log analysis responses."""

    def __init__(self):
        """Initialize the formatter."""
        pass

    def format_log_response(
        self,
        api_response: Dict[str, Any],
        log_type: str,
        page: int,
        _size: int,
        applied_filters: Optional[Dict[str, Any]] = None,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format API response with actual structure from PRD.

        Args:
            api_response: Raw API response
            log_type: Type of logs (internal/integration)
            page: Current page number
            size: Page size
            applied_filters: Dictionary of filters that were applied

        Returns:
            Formatted response content
        """
        try:
            # Extract log entries from _embedded.systemLogResourceList
            embedded = api_response.get("_embedded", {})
            log_entries = embedded.get("systemLogResourceList", [])

            # Extract pagination info
            page_info = api_response.get("page", {})
            total_elements = page_info.get("totalElements", 0)
            total_pages = page_info.get("totalPages", 0)
            current_page = page_info.get("number", page)

            # Generate operation and status summaries
            operation_counts = self._count_operations(log_entries)
            status_counts = self._count_statuses(log_entries)

            # A client-side filter narrows the fetched page only; the platform's
            # totals still count every entry, so they are never the filter's totals.
            filtered = any((applied_filters or {}).get(key) for key in CONTENT_FILTER_KEYS)
            if filtered:
                platform = PageInfo.from_envelope(api_response)
                total_elements, total_pages = platform.total_elements, platform.total_pages
                insights = self._generate_diagnostic_insights(
                    log_entries, operation_counts, status_counts
                )
            else:
                insights = self._generate_diagnostic_insights(
                    log_entries, operation_counts, status_counts, total_elements, total_pages
                )

            # Build response text
            response_text = self._build_response_header(
                log_type,
                total_elements,
                current_page,
                total_pages,
                len(log_entries),
                applied_filters,
                filtered=filtered,
            )

            response_text += self._build_operation_summary(operation_counts)
            response_text += self._build_status_summary(status_counts)

            if insights:
                response_text += self._build_insights_section(insights)

            if log_entries:
                response_text += self._build_recent_entries_section(log_entries)

            return [TextContent(type="text", text=response_text)]

        except Exception as e:
            logger.error(f"Failed to format log response: {e}")
            raise ToolError(
                message=f"Failed to format log response: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="response_formatting",
                suggestions=[
                    "Check API response structure",
                    "Verify log data format",
                    "Try with smaller page size",
                ],
            )

    def _count_operations(self, log_entries: List[Dict[str, Any]]) -> Dict[str, int]:
        """Count operations in log entries."""
        operation_counts = {}
        for entry in log_entries:
            operation = entry.get("operation", "UNKNOWN")
            operation_counts[operation] = operation_counts.get(operation, 0) + 1
        return operation_counts

    def _count_statuses(self, log_entries: List[Dict[str, Any]]) -> Dict[str, int]:
        """Count statuses in log entries."""
        status_counts = {}
        for entry in log_entries:
            status = entry.get("status", "UNKNOWN")
            status_counts[status] = status_counts.get(status, 0) + 1
        return status_counts

    def _build_response_header(
        self,
        log_type: str,
        total_elements: Optional[int],
        current_page: int,
        total_pages: Optional[int],
        entries_this_page: int,
        applied_filters: Optional[Dict[str, Any]] = None,
        filtered: bool = False,
    ) -> str:
        """Build the response header section."""
        if filtered:
            header = self._build_filtered_summary(
                log_type, total_elements, current_page, total_pages, entries_this_page
            )
        else:
            header = f"""
# {log_type.title()} Log Analysis

## Summary
- **Total Entries**: {total_elements:,}
- **Current Page**: {current_page + 1} of {total_pages}
- **Entries This Page**: {entries_this_page}
- **Log Type**: {log_type}
"""

        if applied_filters:
            header += "\n## Applied Filters\n"
            for filter_name, filter_value in applied_filters.items():
                if filter_value:
                    header += f"- **{filter_name}**: {filter_value}\n"

        return header

    def _build_filtered_summary(
        self,
        log_type: str,
        total_elements: Optional[int],
        current_page: int,
        total_pages: Optional[int],
        entries_this_page: int,
    ) -> str:
        """Summary of a filtered page: its matches, and the platform totals labelled unfiltered."""
        summary = f"""
# {log_type.title()} Log Analysis

## Summary
- **Matches On This Page**: {entries_this_page}
"""
        if total_elements is not None and total_pages is not None:
            summary += (
                f"- **Platform Total (unfiltered)**: {total_elements:,} entries across "
                f"{counted(total_pages, 'page', 'pages')}\n"
            )
        if total_pages is not None:
            summary += f"- **Current Page**: {current_page + 1} of {total_pages} (unfiltered pages)\n"
        summary += "- **Filter Scope**: the filter was applied to the entries on this page only\n"
        summary += f"- **Log Type**: {log_type}\n"
        return summary

    def _build_operation_summary(self, operation_counts: Dict[str, int]) -> str:
        """Build the operation summary section."""
        summary = "\n## Operation Summary\n"
        for operation, count in sorted(operation_counts.items(), key=lambda x: x[1], reverse=True):
            summary += f"- **{operation}**: {count}\n"
        return summary

    def _build_status_summary(self, status_counts: Dict[str, int]) -> str:
        """Build the status summary section."""
        summary = "\n## Status Summary\n"
        for status, count in sorted(status_counts.items(), key=lambda x: x[1], reverse=True):
            summary += f"- **{status}**: {count}\n"
        return summary

    def _build_insights_section(self, insights: List[str]) -> str:
        """Build the diagnostic insights section."""
        section = "\n## Diagnostic Insights\n"
        for insight in insights:
            section += f"- {insight}\n"
        return section

    def _build_recent_entries_section(self, log_entries: List[Dict[str, Any]]) -> str:
        """Build the recent entries section."""
        section = f"\n## Recent Entries (Latest {min(5, len(log_entries))})\n"
        for i, entry in enumerate(log_entries[:5]):
            created = entry.get("created", "Unknown")
            operation = entry.get("operation", "Unknown")
            status = entry.get("status", "Unknown")
            details = entry.get("details", "No details")

            section += f"""
**Entry {i+1}**
- **Time**: {created}
- **Operation**: {operation}
- **Status**: {status}
- **Details**: {details}
"""
        return section

    def _generate_diagnostic_insights(
        self,
        log_entries: List[Dict[str, Any]],
        operation_counts: Dict[str, int],
        status_counts: Dict[str, int],
        total_elements: int = 0,
        total_pages: int = 0,
    ) -> List[str]:
        """Generate diagnostic insights based on log patterns."""
        insights = []

        # Check for failures
        failure_count = status_counts.get("FAILURE", 0)
        if failure_count > 0:
            insights.append(f"Found {failure_count} failed operations requiring investigation")

        # Check for AI metric processing
        ai_processing = operation_counts.get("AI_METRIC_PROCESSING", 0)
        if ai_processing > 0:
            ai_info_count = sum(
                1
                for entry in log_entries
                if entry.get("operation") == "AI_METRIC_PROCESSING"
                and entry.get("status") == "INFO"
            )
            if ai_info_count > 0:
                insights.append(
                    f"{ai_info_count} AI_METRIC_PROCESSING entries with INFO status (new products/organizations created)"
                )

        # Check for large datasets - USE ACTUAL TOTAL FROM API
        if total_elements > 100:
            if total_pages > 1:
                insights.append(
                    f"Large dataset available: {total_elements:,} total entries across {total_pages} pages"
                )
            else:
                insights.append(f"Large dataset available: {total_elements:,} total entries")

        # Check for email dispatch issues
        email_failures = sum(
            1
            for entry in log_entries
            if "EMAIL_DISPATCH" in entry.get("operation", "") and entry.get("status") == "FAILURE"
        )
        if email_failures > 0:
            insights.append(f"Found {email_failures} email dispatch failures")

        return insights

    def format_multi_page_response(
        self,
        all_entries: List[Dict[str, Any]],
        log_type: str,
        pages_retrieved: int,
        applied_filters: Optional[Dict[str, Any]] = None,
        stop_note: Optional[str] = None,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format multi-page analysis response."""
        try:
            # Generate comprehensive summaries
            operation_counts = self._count_operations(all_entries)
            status_counts = self._count_statuses(all_entries)
            # For multi-page, use the total entries retrieved as the dataset size
            total_entries_retrieved = len(all_entries)
            insights = self._generate_diagnostic_insights(
                all_entries,
                operation_counts,
                status_counts,
                total_entries_retrieved,
                pages_retrieved,
            )

            stopped = f"- **Stopped Early**: {stop_note}\n" if stop_note else ""

            # Build multi-page response
            response_text = f"""
# Multi-Page {log_type.title()} Log Analysis

## Summary
- **Total Entries Analyzed**: {len(all_entries):,}
- **Pages Retrieved**: {pages_retrieved}
{stopped}- **Log Type**: {log_type}
"""

            if applied_filters:
                response_text += "\n## Applied Filters\n"
                for filter_name, filter_value in applied_filters.items():
                    if filter_value:
                        response_text += f"- **{filter_name}**: {filter_value}\n"

            response_text += self._build_operation_summary(operation_counts)
            response_text += self._build_status_summary(status_counts)

            if insights:
                response_text += self._build_insights_section(insights)

            # Add time-based analysis for multi-page
            response_text += self._build_temporal_analysis(all_entries)

            if all_entries:
                response_text += self._build_recent_entries_section(all_entries)

            return [TextContent(type="text", text=response_text)]

        except Exception as e:
            logger.error(f"Failed to format multi-page response: {e}")
            raise ToolError(
                message=f"Failed to format multi-page response: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="multi_page_formatting",
                suggestions=[
                    "Check log entries format",
                    "Verify pages were retrieved correctly",
                    "Try with fewer pages",
                ],
            )

    def format_comprehensive_search_response(
        self,
        all_matches: List[Dict[str, Any]],
        log_type: str,
        coverage: PageCoverage,
        applied_filters: Optional[Dict[str, Any]] = None,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Format a page-by-page search with the pages and entries it covered."""
        try:
            # Generate operation and status summaries
            operation_counts = {}
            status_counts = {}

            for entry in all_matches:
                operation = entry.get("operation", "UNKNOWN")
                status = entry.get("status", "UNKNOWN")

                operation_counts[operation] = operation_counts.get(operation, 0) + 1
                status_counts[status] = status_counts.get(status, 0) + 1

            platform = coverage.platform
            pages_searched = _of_total(str(coverage.pages_read), platform.total_pages)
            entries_searched = _of_total(
                f"{coverage.entries_read:,}", platform.total_elements, ","
            )

            # Format response
            response_text = f"""
# Comprehensive Search Results ({log_type.title()} Logs)

## Search Summary
- **Total Matches Found**: {len(all_matches):,}
- **Pages Searched**: {pages_searched}
- **Entries Searched**: {entries_searched}
- **Search Scope**: {self._search_scope(coverage)}
- **Log Type**: {log_type}
"""

            # Add applied filters section
            if applied_filters:
                response_text += "\n## Applied Filters\n"
                for filter_name, filter_value in applied_filters.items():
                    response_text += f"- **{filter_name}**: {filter_value}\n"

            if all_matches:
                # Add operation summary
                response_text += "\n## Operation Summary\n"
                for operation, count in sorted(
                    operation_counts.items(), key=lambda x: x[1], reverse=True
                ):
                    response_text += f"- **{operation}**: {count}\n"

                # Add status summary
                response_text += "\n## Status Summary\n"
                for status, count in sorted(
                    status_counts.items(), key=lambda x: x[1], reverse=True
                ):
                    response_text += f"- **{status}**: {count}\n"

                # Add sample entries (latest 10)
                response_text += f"\n## Sample Matches (Latest {min(10, len(all_matches))})\n"
                for i, entry in enumerate(all_matches[:10]):
                    created = entry.get("created", "Unknown")
                    operation = entry.get("operation", "Unknown")
                    status = entry.get("status", "Unknown")
                    details = entry.get("details", "No details")

                    response_text += f"""
**Match {i+1}**
- **Time**: {created}
- **Operation**: {operation}
- **Status**: {status}
- **Details**: {details}
"""
            else:
                not_found = (
                    "The search terms were not found in the "
                    f"{counted(coverage.pages_read, 'page', 'pages')} searched."
                )
                if not coverage.complete:
                    not_found += "\nMatches may still exist in the pages that were not searched."
                response_text += f"""
## No Matches Found

{not_found}

## Recommendations
- Verify the search term spelling
- Try partial search terms
- Check if the data might be in integration logs
- Consider that the data might be older than the current dataset
"""

            return [TextContent(type="text", text=response_text)]

        except Exception as e:
            logger.error(f"Failed to format comprehensive search response: {e}")
            raise ToolError(
                message=f"Failed to format comprehensive search response: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="comprehensive_search_formatting",
                suggestions=[
                    "Check search results format",
                    "Verify filter data structure",
                    "Try with simpler search criteria",
                ],
            )

    @staticmethod
    def _search_scope(coverage: PageCoverage) -> str:
        """Complete only when every page was read; otherwise say why the search stopped."""
        if coverage.failed_page is not None:
            page = coverage.failed_page
            return (
                f"Incomplete: page {page + 1} (page={page}) failed ({coverage.failure}), "
                "so it and every later page went unsearched"
            )
        if coverage.complete:
            return "Complete: every page the platform reported was searched"
        if coverage.pages_left is None:
            return "Unknown: the platform did not report how many pages exist"
        not_searched = counted(coverage.pages_left, "page", "pages")
        if coverage.pages_read == coverage.page_limit:
            return f"Incomplete: stopped at the search's page limit with {not_searched} not searched"
        return (
            "Incomplete: the platform returned an empty page before its last page; "
            f"{not_searched} not searched"
        )

    def _build_temporal_analysis(self, all_entries: List[Dict[str, Any]]) -> str:
        """Build temporal analysis section for multi-page data."""
        if not all_entries:
            return ""

        # Extract timestamps and analyze patterns
        timestamps = []
        for entry in all_entries:
            created = entry.get("created")
            if created:
                timestamps.append(created)

        section = "\n## Temporal Analysis\n"
        if timestamps:
            section += f"- **Time Range**: {timestamps[-1]} to {timestamps[0]}\n"
            section += f"- **Entries with Timestamps**: {len(timestamps)}\n"
        else:
            section += "- **Time Range**: No timestamp data available\n"

        return section
