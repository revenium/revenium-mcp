"""Log filtering utilities for Revenium Log Analysis Tool.

This module contains client-side filtering logic to enable agents to easily
search for specific operations, statuses, or content even when the API
doesn't support server-side filtering.
"""

from typing import Any, Dict, List, Optional

from loguru import logger

from ..common.error_handling import ErrorCodes, ToolError


class LogFilter:
    """Handles client-side filtering of log entries."""

    def __init__(self):
        """Initialize the filter."""
        pass

    def apply_filters(
        self,
        log_entries: List[Dict[str, Any]],
        operation_filter: Optional[str] = None,
        status_filter: Optional[str] = None,
        search_term: Optional[str] = None,
        log_type_filter: Optional[str] = None,
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Apply client-side filters to log entries.

        Args:
            log_entries: Raw log entries from API
            operation_filter: Filter by operation (exact match or contains)
            status_filter: Filter by status (SUCCESS/FAILURE/INFO/WARNING)
            search_term: Search term for details field
            log_type_filter: Filter by log type (for multi-source searches)

        Returns:
            Tuple of (filtered_entries, applied_filters_dict)
        """
        try:
            filtered_entries = log_entries.copy()
            applied_filters = {}

            # Apply operation filter
            if operation_filter:
                filtered_entries = self._filter_by_operation(filtered_entries, operation_filter)
                applied_filters["operation_filter"] = operation_filter

            # Apply status filter
            if status_filter:
                filtered_entries = self._filter_by_status(filtered_entries, status_filter)
                applied_filters["status_filter"] = status_filter

            # Apply search term filter
            if search_term:
                filtered_entries = self._filter_by_search_term(filtered_entries, search_term)
                applied_filters["search_term"] = search_term

            # Apply log type filter (for multi-source)
            if log_type_filter:
                applied_filters["log_type_filter"] = log_type_filter

            logger.info(f"Filtered {len(log_entries)} entries to {len(filtered_entries)} entries")

            return filtered_entries, applied_filters

        except Exception as e:
            logger.error(f"Failed to apply filters: {e}")
            raise ToolError(
                message=f"Failed to apply filters: {str(e)}",
                error_code=ErrorCodes.PROCESSING_ERROR,
                field="filtering",
                suggestions=[
                    "Check filter parameters",
                    "Verify log entries format",
                    "Try simpler filter criteria",
                ],
            )

    def _filter_by_operation(
        self, entries: List[Dict[str, Any]], operation_filter: str
    ) -> List[Dict[str, Any]]:
        """Filter entries by operation type.

        Supports both exact match and contains matching for flexibility.
        """
        filtered = []
        operation_filter_upper = operation_filter.upper()

        for entry in entries:
            operation = entry.get("operation", "").upper()

            # Try exact match first, then contains match
            if operation == operation_filter_upper or operation_filter_upper in operation:
                filtered.append(entry)

        return filtered

    def _filter_by_status(
        self, entries: List[Dict[str, Any]], status_filter: str
    ) -> List[Dict[str, Any]]:
        """Filter entries by status.

        Supports: SUCCESS, FAILURE, INFO, WARNING, ERROR
        """
        filtered = []
        status_filter_upper = status_filter.upper()

        # Map common status variations
        status_mappings = {
            "ERROR": ["ERROR", "FAILURE"],
            "FAIL": ["FAILURE", "ERROR"],
            "FAILURE": ["FAILURE", "ERROR"],
            "SUCCESS": ["SUCCESS"],
            "INFO": ["INFO"],
            "WARNING": ["WARNING", "WARN"],
            "WARN": ["WARNING", "WARN"],
        }

        # Get acceptable statuses
        acceptable_statuses = status_mappings.get(status_filter_upper, [status_filter_upper])

        for entry in entries:
            status = entry.get("status", "").upper()
            if status in acceptable_statuses:
                filtered.append(entry)

        return filtered

    def _filter_by_search_term(
        self, entries: List[Dict[str, Any]], search_term: str
    ) -> List[Dict[str, Any]]:
        """Filter entries by search term in details field.

        Performs case-insensitive search across multiple fields.
        """
        filtered = []
        search_term_lower = search_term.lower()

        for entry in entries:
            # Search in multiple fields
            searchable_fields = [
                entry.get("details", ""),
                entry.get("operation", ""),
                entry.get("system", ""),
                str(entry.get("id", "")),
            ]

            # Check if search term appears in any field
            found = False
            for field_value in searchable_fields:
                if search_term_lower in str(field_value).lower():
                    found = True
                    break

            if found:
                filtered.append(entry)

        return filtered

    def get_available_operations(self, entries: List[Dict[str, Any]]) -> List[str]:
        """Get list of available operations from entries."""
        operations = set()
        for entry in entries:
            operation = entry.get("operation")
            if operation:
                operations.add(operation)
        return sorted(list(operations))

    def get_available_statuses(self, entries: List[Dict[str, Any]]) -> List[str]:
        """Get list of available statuses from entries."""
        statuses = set()
        for entry in entries:
            status = entry.get("status")
            if status:
                statuses.add(status)
        return sorted(list(statuses))

    def validate_filter_parameters(
        self,
        operation_filter: Optional[str] = None,
        status_filter: Optional[str] = None,
        search_term: Optional[str] = None,
    ) -> List[str]:
        """Validate filter parameters and return any warnings."""
        warnings = []

        # Validate status filter
        if status_filter:
            valid_statuses = ["SUCCESS", "FAILURE", "ERROR", "INFO", "WARNING", "WARN", "FAIL"]
            if status_filter.upper() not in valid_statuses:
                warnings.append(
                    f"Status filter '{status_filter}' may not match any entries. Valid statuses: {', '.join(valid_statuses)}"
                )

        # Validate search term
        if search_term and len(search_term) < 2:
            warnings.append("Search term is very short and may return too many results")

        # Validate operation filter
        if operation_filter and len(operation_filter) < 3:
            warnings.append("Operation filter is very short and may return too many results")

        return warnings

    def create_filter_summary(
        self, original_count: int, filtered_count: int, applied_filters: Dict[str, Any]
    ) -> str:
        """Create a summary of filtering results."""
        if not applied_filters:
            return ""

        summary = "\n## Filtering Results\n"
        summary += f"- **Original Entries**: {original_count:,}\n"
        summary += f"- **Filtered Entries**: {filtered_count:,}\n"
        summary += f"- **Reduction**: {original_count - filtered_count:,} entries removed\n"

        if filtered_count == 0:
            summary += "\n⚠️ **No entries match the specified filters**\n"
            summary += "Consider:\n"
            summary += "- Broadening filter criteria\n"
            summary += "- Checking spelling of operation/status names\n"
            summary += "- Using partial matches for operation names\n"
        elif filtered_count < original_count * 0.1:
            summary += f"\n💡 **Highly selective filter** - showing {(filtered_count/original_count)*100:.1f}% of original data\n"

        return summary

    def suggest_common_filters(self, entries: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        """Suggest common filter values based on available data."""
        suggestions = {
            "common_operations": [],
            "error_operations": [],
            "common_statuses": [],
            "sample_search_terms": [],
        }

        # Get operation frequencies
        operation_counts = {}
        error_operations = set()
        status_counts = {}

        for entry in entries:
            operation = entry.get("operation", "")
            status = entry.get("status", "")

            if operation:
                operation_counts[operation] = operation_counts.get(operation, 0) + 1
                if status in ["FAILURE", "ERROR"]:
                    error_operations.add(operation)

            if status:
                status_counts[status] = status_counts.get(status, 0) + 1

        # Most common operations
        suggestions["common_operations"] = [
            op for op, _ in sorted(operation_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        ]

        # Operations with errors
        suggestions["error_operations"] = list(error_operations)[:5]

        # Available statuses
        suggestions["common_statuses"] = list(status_counts.keys())

        # Sample search terms from details
        sample_terms = set()
        for entry in entries[:20]:  # Sample first 20 entries
            details = entry.get("details", "")
            if details and len(details) > 10:
                # Extract potential search terms
                words = details.split()
                for word in words:
                    if len(word) > 4 and word.isalpha():
                        sample_terms.add(word.lower())
                        if len(sample_terms) >= 5:
                            break

        suggestions["sample_search_terms"] = list(sample_terms)[:5]

        return suggestions
