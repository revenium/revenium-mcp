"""Revenium Log Analysis Tool for MCP Server.

This tool provides log analysis capabilities including:
- Internal system log retrieval (AI metering, email dispatch)
- Integration log analysis (Stripe, OAuth, API gateways)
- Advanced log filtering and search
- Operation pattern analysis
- Diagnostic insights and troubleshooting
"""

import json
from typing import TYPE_CHECKING, Any, ClassVar, Dict, List, Optional, Union

if TYPE_CHECKING:
    from ..auth.tenant_context import TenantContext

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
        "Revenium log analysis for system troubleshooting and diagnostic investigation. Key actions: get_internal_logs, get_integration_logs, get_recent_logs, search_logs, analyze_operations, get_ingestion_failures, set_strict_ingestion_mode. Default size: 200 records (max: 1000). Use get_examples() for usage guidance and get_capabilities() for status."
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
        self,
        action: str,
        arguments: Dict[str, Any],
        *,
        ctx: Optional["TenantContext"] = None,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle log analysis actions."""
        try:
            return await self._route_action(action, arguments, ctx=ctx)
        except ToolError:
            # Re-raise ToolError exceptions without modification
            raise
        except PermissionError:
            # Auth failures must fail closed — never mask as a tool-error envelope.
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

    async def _make_api_call(
        self,
        endpoint: str,
        page: int,
        size: int,
        ctx: Optional["TenantContext"] = None,
    ) -> Dict[str, Any]:
        """Make API call with standard parameters."""
        params = {"page": page, "size": size, "sort": self.default_sort}

        client = await self.get_client(ctx=ctx)
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
        ctx: Optional["TenantContext"] = None,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """Get logs and apply client-side filtering."""
        # Determine endpoint
        endpoint = self.log_endpoints.get(log_type, self.log_endpoints["internal"])

        # Get raw data
        response = await self._make_api_call(endpoint, page, size, ctx=ctx)

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

    async def _get_multi_page_logs(
        self,
        log_type: str,
        pages: int,
        ctx: Optional["TenantContext"] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve logs from multiple pages and aggregate."""
        all_entries = []

        for page in range(pages):
            try:
                response = await self._make_api_call(
                    self.log_endpoints.get(log_type, self.log_endpoints["internal"]),
                    page,
                    self.default_size,
                    ctx=ctx,
                )

                embedded = response.get("_embedded", {})
                entries = embedded.get("systemLogResourceList", [])
                all_entries.extend(entries)

                # Stop if we've reached the end
                page_info = response.get("page", {})
                if page >= page_info.get("totalPages", 1) - 1:
                    break

            except PermissionError:
                # Auth failures must fail closed — never mask as a tool-error envelope.
                raise
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
        ctx: Optional["TenantContext"] = None,
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
                response = await self._make_api_call(endpoint, page, 1000, ctx=ctx)

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

            except PermissionError:
                # Auth failures must fail closed — never mask as a tool-error envelope.
                raise
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
        self,
        action: str,
        arguments: Dict[str, Any],
        *,
        ctx: Optional["TenantContext"] = None,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Route action to appropriate handler."""
        if action == "get_capabilities":
            return await self._handle_get_capabilities()
        elif action == "get_examples":
            return await self._handle_get_examples(arguments)
        elif action == "get_internal_logs":
            return await self._handle_get_internal_logs(arguments, ctx=ctx)
        elif action == "get_integration_logs":
            return await self._handle_get_integration_logs(arguments, ctx=ctx)
        elif action == "get_recent_logs":
            return await self._handle_get_recent_logs(arguments, ctx=ctx)
        elif action == "search_logs":
            return await self._handle_search_logs(arguments, ctx=ctx)
        elif action == "analyze_operations":
            return await self._handle_analyze_operations(arguments, ctx=ctx)
        elif action == "get_ingestion_failures":
            return await self._handle_get_ingestion_failures(arguments, ctx=ctx)
        elif action == "set_strict_ingestion_mode":
            return await self._handle_set_strict_ingestion_mode(arguments, ctx=ctx)
        else:
            return await self._handle_unsupported_action(action)

    # Per-entry cap for rendered originalPayload JSON, so a page of large
    # payloads cannot blow past the MCP transport's response limits.
    _MAX_RENDERED_PAYLOAD_CHARS = 2000
    # Bound on the COMPLETE rendered response: entries stop being appended
    # once the budget is spent (a page of many per-entry-capped payloads can
    # still exceed the transport limit otherwise).
    _MAX_RENDERED_RESPONSE_CHARS = 24000

    async def _handle_get_ingestion_failures(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """List AI transactions rejected by strict ingestion mode.

        Newest-first, paginated; each entry carries structured error details
        and the prompt-redacted original payload, so a rejected integration
        can be diagnosed without server access.
        """
        page = arguments.get("page", 0)
        size = arguments.get("size", 20)
        error_code = arguments.get("error_code")

        self._validate_page_size(size)

        try:
            client = await self.get_client(ctx=ctx)
            # Built here rather than splatted from a caller dict, so there is
            # no allowlist to apply. Verified 2026-08-28 against hypercurrent
            # origin/develop TenantController.listIngestionFailures, whose only
            # declared query parameter is errorCode (plus a Pageable).
            filters = {"errorCode": error_code} if error_code else {}
            response = await client.get_ingestion_failures(page=page, size=size, **filters)
            failures = client._extract_embedded_data(response)
            page_info = client._extract_pagination_info(response)

            if not failures:
                scope = f" with error code '{error_code}'" if error_code else ""
                return [
                    TextContent(
                        type="text",
                        text=(
                            f"**Ingestion Failures**\n\nNo strict-ingestion rejections{scope} "
                            "for this tenant. Either strict mode is disabled or every "
                            "transaction referenced known entities."
                        ),
                    )
                ]

            lines = [
                f"**Ingestion Failures** (page {page + 1}, "
                f"{page_info.get('totalElements', len(failures))} total)\n"
            ]
            rendered_chars = len(lines[0])
            rendered_count = 0
            for failure in failures:
                entry_lines = []
                ts = failure.get("failureTimestamp", "unknown time")
                entry_lines.append(f"### {ts}")
                for err in failure.get("errors") or []:
                    code = err.get("errorCode", "UNKNOWN")
                    message = err.get("message", "")
                    entry_lines.append(f"- **{code}**: {message}")
                payload = failure.get("originalPayload")
                if payload:
                    # Bound per-entry rendering: callers control page size, and
                    # an oversized MCP response gets rejected by the transport.
                    rendered = json.dumps(payload, indent=2, default=str)
                    if len(rendered) > self._MAX_RENDERED_PAYLOAD_CHARS:
                        rendered = (
                            rendered[: self._MAX_RENDERED_PAYLOAD_CHARS]
                            + "\n... (payload truncated; fetch the entry via the REST API for the full payload)"
                        )
                    entry_lines.append(f"```json\n{rendered}\n```")
                entry_text_len = sum(len(line) + 1 for line in entry_lines)
                # Bound the COMPLETE response: stop before this entry would
                # blow the budget, and say how many were cut and how to narrow.
                if rendered_chars + entry_text_len > self._MAX_RENDERED_RESPONSE_CHARS:
                    remaining = len(failures) - rendered_count
                    lines.append(
                        f"\n... output truncated: {remaining} more entries on this page "
                        "were not rendered. Use a smaller size, filter with error_code, "
                        "or paginate to see them."
                    )
                    break
                lines.extend(entry_lines)
                rendered_chars += entry_text_len
                rendered_count += 1
            lines.append(
                "\nEntries are newest-first; the original payload is prompt-redacted "
                "by the server. Filter with error_code, paginate with page/size."
            )
            return [TextContent(type="text", text="\n".join(lines))]

        except ToolError:
            raise
        except PermissionError:
            # Auth failures must fail closed — never mask as a tool-error envelope.
            raise
        except Exception as e:
            logger.error(f"Failed to retrieve ingestion failures: {e}")
            raise ToolError(
                message=f"Failed to retrieve ingestion failures: {str(e)}",
                error_code=ErrorCodes.API_ERROR,
                field="ingestion_failures",
                suggestions=[
                    "Verify the tenant id is available (auto-discovered from the API key)",
                    "Check API connectivity and authentication",
                    "Strict-ingestion rejections only exist when strict mode has been enabled",
                ],
            )

    async def _handle_set_strict_ingestion_mode(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Toggle the tenant's strict ingestion mode, guarded by confirm.

        Strict mode changes ingestion behavior for the whole tenant, so the
        toggle requires an explicit confirm=true; without it the handler
        returns a preview of the consequences and makes no API call.

        The optional allow_ticket_jobs sub-flag decides whether the
        coding-assistant enricher keeps creating ticket-grain Jobs while
        strict mode is on. Omitting it leaves the tenant's current setting
        untouched.
        """
        enabled = arguments.get("enabled")
        if not isinstance(enabled, bool):
            raise ToolError(
                message="set_strict_ingestion_mode requires 'enabled' (boolean)",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field="enabled",
                value=enabled,
                suggestions=[
                    "Pass enabled=true to turn strict mode on, enabled=false to turn it off",
                    "Add confirm=true to apply the change",
                ],
            )

        allow_ticket_jobs = arguments.get("allow_ticket_jobs")
        if allow_ticket_jobs is not None and not isinstance(allow_ticket_jobs, bool):
            raise ToolError(
                message="set_strict_ingestion_mode requires 'allow_ticket_jobs' to be a boolean when provided",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field="allow_ticket_jobs",
                value=allow_ticket_jobs,
                suggestions=[
                    "Pass allow_ticket_jobs=true to keep ticket-grain Job creation on under strict mode",
                    "Omit allow_ticket_jobs to leave the tenant's current setting unchanged",
                ],
            )

        # The API refuses exactly this pair: the sub-flag has no meaning while
        # strict ingestion is off. allow_ticket_jobs=false with enabled=false
        # is a legal call and must pass through.
        if allow_ticket_jobs is True and enabled is False:
            raise ToolError(
                message="allow_ticket_jobs=true requires strict ingestion mode to be enabled",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field="allow_ticket_jobs",
                value=allow_ticket_jobs,
                suggestions=[
                    "Pass enabled=true with allow_ticket_jobs=true to keep ticket-grain Jobs under strict mode",
                    "Omit allow_ticket_jobs when disabling strict mode — the server clears the opt-in anyway",
                ],
            )

        # Only the boolean True applies the change — loosely typed MCP
        # arguments (confirm="false", confirm=1) must not bypass the guard.
        if arguments.get("confirm") is not True:
            state = "ENABLE" if enabled else "DISABLE"
            # The ticket-jobs consequence depends on the opt-in actually being
            # sent: claiming Jobs "STOP" when the caller passes
            # allow_ticket_jobs=true (or when omission leaves an existing tenant
            # opt-in untouched) would make the confirmation preview lie.
            if allow_ticket_jobs is True:
                ticket_jobs_effect = (
                    "Ticket-grain Jobs from the coding-assistant enricher KEEP being "
                    "created: this call opts the tenant in with "
                    "allow_ticket_jobs=true."
                )
            elif allow_ticket_jobs is None:
                ticket_jobs_effect = (
                    "Ticket-grain Jobs follow the tenant's EXISTING opt-in, which "
                    "this call leaves unchanged (allow_ticket_jobs omitted): if the "
                    "tenant has never opted in (the platform default), they stop "
                    "being created; if a previous enable opted in, they continue. "
                    "Pass allow_ticket_jobs=true to opt in explicitly."
                )
            else:
                ticket_jobs_effect = (
                    "Ticket-grain Jobs from the coding-assistant enricher STOP being "
                    "created for this tenant (allow_ticket_jobs=false). To keep "
                    "them, opt in with allow_ticket_jobs=true."
                )
            effect = (
                "AI ingestion will REJECT transactions that reference entities "
                "(Product, Subscriber, Credential, Consuming Organization) which do "
                "not already exist for the tenant, instead of auto-creating them. "
                "Rejections are listed by get_ingestion_failures.\n\n"
                + ticket_jobs_effect
                if enabled
                else "AI ingestion will resume AUTO-CREATING unknown referenced "
                "entities (Product, Subscriber, Credential, Consuming Organization) "
                "instead of rejecting those transactions.\n\n"
                "Any existing ticket-grain Jobs opt-in is CLEARED by the server when "
                "strict mode goes off (allow_ticket_jobs is forced back to false). "
                "It is not remembered: you must re-state allow_ticket_jobs=true the "
                "next time you re-enable strict mode."
            )
            opt_in_arg = (
                f", allow_ticket_jobs={str(allow_ticket_jobs).lower()}"
                if allow_ticket_jobs is not None
                else ""
            )
            return [
                TextContent(
                    type="text",
                    text=(
                        f"**Confirmation Required — {state} strict ingestion mode**\n\n"
                        f"This changes ingestion behavior for the entire tenant:\n\n{effect}\n\n"
                        f"To apply, repeat the call with confirm=true:\n"
                        f'`set_strict_ingestion_mode(enabled={str(enabled).lower()}{opt_in_arg}, confirm=true)`'
                    ),
                )
            ]

        try:
            client = await self.get_client(ctx=ctx)
            result = await client.set_strict_ingestion_mode(
                enabled, allow_ticket_jobs=allow_ticket_jobs
            )
            new_state = result.get("strictIngestionMode")
            new_allow_ticket_jobs = result.get("strictIngestionAllowTicketJobs")
            if not isinstance(new_state, bool):
                # The PATCH succeeded but the response did not carry the
                # field — report that honestly instead of echoing the
                # requested value back as the server's confirmed state.
                return [
                    TextContent(
                        type="text",
                        text=(
                            "**Strict Ingestion Mode — change accepted, state not confirmed**\n\n"
                            "The server accepted the request but its response did not include "
                            "strictIngestionMode, so the resulting state could not be verified. "
                            "Check the tenant's current state before relying on it."
                        ),
                    )
                ]
            # Same honesty rule as strictIngestionMode: only report the
            # ticket-jobs opt-in when the server actually echoed it back.
            ticket_jobs_line = (
                f"- **Ticket-grain Jobs**: "
                f"{'allowed' if new_allow_ticket_jobs else 'suppressed'}\n"
                if isinstance(new_allow_ticket_jobs, bool)
                else ""
            )
            follow_up = (
                "Transactions referencing unknown entities will now be "
                "rejected — monitor them with get_ingestion_failures."
                if new_state
                else "Unknown referenced entities will now be auto-created again. "
                "Any ticket-grain Jobs opt-in has been cleared; re-state "
                "allow_ticket_jobs=true when you re-enable strict mode."
            )
            return [
                TextContent(
                    type="text",
                    text=(
                        f"**Strict Ingestion Mode Updated**\n\n"
                        f"- **State**: {'enabled' if new_state else 'disabled'}\n"
                        f"{ticket_jobs_line}"
                        f"- **Tenant**: {result.get('id', 'current')}\n\n"
                        + follow_up
                    ),
                )
            ]
        except ToolError:
            raise
        except PermissionError:
            # Auth failures must fail closed — never mask as a tool-error envelope.
            raise
        except Exception as e:
            logger.error(f"Failed to toggle strict ingestion mode: {e}")
            raise ToolError(
                message=f"Failed to toggle strict ingestion mode: {str(e)}",
                error_code=ErrorCodes.API_ERROR,
                field="strict_ingestion_mode",
                suggestions=[
                    "Verify the tenant id is available (auto-discovered from the API key)",
                    "Check that your API key can manage the tenant",
                ],
            )

    async def _handle_get_internal_logs(
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Retrieve internal system logs."""
        page = arguments.get("page", 0)
        size = arguments.get("size", self.default_size)

        try:
            self._validate_page_size(size)
            response = await self._make_api_call(self.log_endpoints["internal"], page, size, ctx=ctx)
            return self.response_formatter.format_log_response(response, "internal", page, size)

        except ToolError:
            raise
        except PermissionError:
            # Auth failures must fail closed — never mask as a tool-error envelope.
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
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Retrieve integration logs."""
        page = arguments.get("page", 0)
        size = arguments.get("size", self.default_size)

        try:
            self._validate_page_size(size)
            response = await self._make_api_call(self.log_endpoints["integration"], page, size, ctx=ctx)
            return self.response_formatter.format_log_response(response, "integration", page, size)

        except ToolError:
            raise
        except PermissionError:
            # Auth failures must fail closed — never mask as a tool-error envelope.
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
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Get recent activity across multiple pages."""
        pages = arguments.get("pages", 1)
        log_type = arguments.get("log_type", "internal")

        try:
            # Get entries from multiple pages
            all_entries = await self._get_multi_page_logs(log_type, pages, ctx=ctx)

            # Use formatter for multi-page response
            return self.response_formatter.format_multi_page_response(all_entries, log_type, pages)

        except ToolError:
            raise
        except PermissionError:
            # Auth failures must fail closed — never mask as a tool-error envelope.
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
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
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
                    ctx=ctx,
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
                    ctx=ctx,
                )
                return self.response_formatter.format_log_response(
                    response, f"filtered_{log_type}", page, size, applied_filters
                )
        except ToolError:
            raise
        except PermissionError:
            # Auth failures must fail closed — never mask as a tool-error envelope.
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
        self, arguments: Dict[str, Any], ctx: Optional["TenantContext"] = None
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Analyze operation patterns across multiple pages."""
        log_type = arguments.get("log_type", "internal")
        pages = arguments.get("pages", 3)  # Default to 3 pages for analysis

        try:
            all_entries = await self._get_multi_page_logs(log_type, pages, ctx=ctx)
            analysis = self._analyze_operation_patterns(all_entries)
            response_text = self._format_analysis_response(analysis, log_type, pages)
            return [TextContent(type="text", text=response_text)]

        except ToolError:
            raise
        except PermissionError:
            # Auth failures must fail closed — never mask as a tool-error envelope.
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
