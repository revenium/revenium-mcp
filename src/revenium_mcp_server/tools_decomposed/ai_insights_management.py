"""Consolidated AI Insights management tool.

Wraps the /api/v2/insights/* public API surface introduced in BACK-1381
(isotope phase-1). Six endpoint actions plus the three standard ToolBase
meta actions. Auto-paginates list endpoints. Defaults get_run to slim mode.
Maps RFC 7807 problem-details codes to structured tool errors.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, List, Optional, Union, cast

if TYPE_CHECKING:
    from ..auth.tenant_context import TenantContext
    from ..client import ReveniumClient

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..agent_friendly import UnifiedResponseFormatter
from ..client import ReveniumAPIError
from ..common.error_handling import (
    ErrorCodes,
    ToolError,
    create_structured_validation_error,
)
from ..introspection.metadata import ToolType
from .unified_tool_base import ToolBase


class AIInsightsManagement(ToolBase):
    """MCP tool wrapping AI Insights public API endpoints."""

    tool_name = "manage_ai_insights"
    tool_description = (
        "Trigger AI cost-intelligence analysis runs and retrieve findings. "
        "Actions: trigger_run (async, returns runId; poll get_run for status), "
        "get_run (slim summary by default; pass slim=False for raw findings), "
        "list_runs (auto-paginated, filterable), submit_feedback, list_feedback, "
        "list_investigators. Use get_examples() for usage patterns."
    )
    business_category = "AI Cost Intelligence and Recommendations"
    tool_type = ToolType.ANALYTICS
    tool_version = "1.0.0"

    DEFAULT_MAX_RESULTS = 100
    HARD_CAP_MAX_RESULTS = 1000
    BACKEND_PAGE_LIMIT = 100
    # The documented per-page cap of the feedback endpoint. It cannot be
    # verified client-side (a bare-array response carries no page metadata),
    # so a cursorless page at or above this size is treated as possibly
    # capped rather than provably complete.
    _FEEDBACK_DOCUMENTED_PAGE_CAP = 100

    def __init__(self, ucm_helper: Any = None) -> None:
        super().__init__(ucm_helper)
        self.formatter = UnifiedResponseFormatter("manage_ai_insights")

    async def handle_action(
        self,
        action: str,
        arguments: Dict[str, Any],
        *,
        ctx: Optional["TenantContext"] = None,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        try:
            if action == "list_investigators":
                return await self._handle_list_investigators(arguments, ctx=ctx)
            elif action == "get_run":
                return await self._handle_get_run(arguments, ctx=ctx)
            elif action == "list_runs":
                return await self._handle_list_runs(arguments, ctx=ctx)
            elif action == "list_feedback":
                return await self._handle_list_feedback(arguments, ctx=ctx)
            elif action == "trigger_run":
                return await self._handle_trigger_run(arguments, ctx=ctx)
            elif action == "submit_feedback":
                return await self._handle_submit_feedback(arguments, ctx=ctx)
            elif action == "get_capabilities":
                return await self._handle_get_capabilities()
            elif action == "get_examples":
                return await self._handle_get_examples()
            elif action == "get_agent_summary":
                return await self._handle_get_agent_summary()
            else:
                raise create_structured_validation_error(
                    message=f"Unknown action '{action}'",
                    field="action",
                    value=action,
                    suggestions=await self._get_supported_actions(),
                )
        except ToolError as e:
            logger.error(f"Tool error in manage_ai_insights: {e}")
            raise e
        except ReveniumAPIError as e:
            logger.error(f"Revenium API error in manage_ai_insights: {e}")
            return self._format_api_error(e)

    async def _handle_list_investigators(
        self,
        arguments: Dict[str, Any],
        *,
        ctx: Optional["TenantContext"] = None,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        client = await self.get_client(ctx=ctx)
        investigators = await client.list_investigators()
        return self.formatter.format_success_response(
            message=f"Retrieved {len(investigators)} investigators",
            data={"investigators": investigators, "count": len(investigators)},
            action="list_investigators",
        )

    def _validate_max_results(self, arguments: Dict[str, Any]) -> int:
        raw = arguments.get("max_results", self.DEFAULT_MAX_RESULTS)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise create_structured_validation_error(
                message=f"max_results must be a positive integer, got {raw!r}",
                field="max_results",
                value=raw,
                suggestions=[f"Pass an integer between 1 and {self.HARD_CAP_MAX_RESULTS}"],
            )
        if value <= 0:
            raise create_structured_validation_error(
                message=f"max_results must be > 0, got {value}",
                field="max_results",
                value=value,
                suggestions=[f"Pass an integer between 1 and {self.HARD_CAP_MAX_RESULTS}"],
            )
        if value > self.HARD_CAP_MAX_RESULTS:
            raise create_structured_validation_error(
                message=(
                    f"max_results must be <= {self.HARD_CAP_MAX_RESULTS}, got {value}"
                ),
                field="max_results",
                value=value,
                suggestions=[
                    f"Pass an integer between 1 and {self.HARD_CAP_MAX_RESULTS}",
                    "Paginate with repeated calls if you need more results",
                ],
            )
        return value

    async def _autopaginate(
        self,
        client_method: Callable[..., Awaitable[Dict[str, Any]]],
        max_results: int,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """Drain cursor-based pagination up to max_results.

        Stops on next_cursor=None, when collected length reaches max_results,
        or when the backend returns the same cursor we just used (no advance).
        Each request uses limit=min(BACKEND_PAGE_LIMIT, remaining).
        """
        collected: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        while len(collected) < max_results:
            remaining = max_results - len(collected)
            page_limit = min(self.BACKEND_PAGE_LIMIT, remaining)
            response = await client_method(limit=page_limit, cursor=cursor, **kwargs)
            page_data = response.get("data", [])
            if not page_data:
                break
            collected.extend(page_data)
            new_cursor = response.get("next_cursor")
            if new_cursor is None:
                break
            if new_cursor == cursor:
                break  # backend did not advance the cursor
            cursor = new_cursor
        return collected

    async def _handle_list_runs(
        self,
        arguments: Dict[str, Any],
        *,
        ctx: Optional["TenantContext"] = None,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        max_results = self._validate_max_results(arguments)
        client = await self.get_client(ctx=ctx)
        runs = await self._autopaginate(
            client.list_recommendation_runs,
            max_results=max_results,
            status=arguments.get("status"),
            since=arguments.get("since"),
            until=arguments.get("until"),
            triggered_by=arguments.get("triggered_by"),
        )
        return self.formatter.format_success_response(
            message=f"Retrieved {len(runs)} runs",
            data={"runs": runs, "count": len(runs)},
            action="list_runs",
        )

    async def _handle_get_run(
        self,
        arguments: Dict[str, Any],
        *,
        ctx: Optional["TenantContext"] = None,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        run_id = arguments.get("run_id")
        if not run_id:
            raise create_structured_validation_error(
                message="run_id is required for action='get_run'",
                field="run_id",
                value=run_id,
                suggestions=[
                    "Pass run_id from a prior trigger_run or list_runs response",
                ],
            )
        slim = arguments.get("slim", True)
        client = await self.get_client(ctx=ctx)
        run = await client.get_recommendation_run(run_id, slim=slim)
        return self.formatter.format_success_response(
            message=f"Retrieved run {run_id} (slim={slim})",
            data=run,
            action="get_run",
        )

    async def _handle_list_feedback(
        self,
        arguments: Dict[str, Any],
        *,
        ctx: Optional["TenantContext"] = None,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        run_id = arguments.get("run_id")
        if not run_id:
            raise create_structured_validation_error(
                message="run_id is required for action='list_feedback'",
                field="run_id",
                value=run_id,
                suggestions=["Pass run_id from list_runs or trigger_run"],
            )
        max_results = self._validate_max_results(arguments)
        client = await self.get_client(ctx=ctx)

        # Inline loop mirrors _autopaginate but binds run_id positionally
        # because client.list_recommendation_feedback(run_id, *, limit, cursor)
        # doesn't fit the (limit, cursor, **kwargs) shape _autopaginate expects.
        collected: List[Dict[str, Any]] = []
        # Seed from a caller-supplied cursor so a next_cursor handed back on a
        # budget stop is actually consumable — resuming, not restarting.
        cursor_argument: Optional[str] = arguments.get("cursor")
        cursor: Optional[str] = cursor_argument
        possibly_truncated = False
        continuation_cursor: Optional[str] = None
        while len(collected) < max_results:
            remaining = max_results - len(collected)
            # The feedback endpoint is cursorless in practice (bare array), so
            # the caller's budget must reach it in the first request — a 100-item
            # page cap would silently truncate larger runs with no cursor to recover.
            page_limit = remaining
            page = await client.list_recommendation_feedback(
                run_id, limit=page_limit, cursor=cursor,
            )
            page_data = page.get("data", [])
            if not page_data:
                break
            collected.extend(page_data)
            new_cursor = page.get("next_cursor")
            if new_cursor is None:
                # A cursorless page is provably complete only when it is
                # smaller than BOTH bounds: the requested limit AND the
                # backend's documented per-page cap. A page at either bound
                # is ambiguous — the run may have exactly that many items,
                # or the server capped the page and dropped the tail with
                # no cursor to recover it.
                possibly_truncated = len(page_data) >= min(
                    page_limit, self._FEEDBACK_DOCUMENTED_PAGE_CAP
                )
                break
            if new_cursor == cursor:
                # The backend repeated the cursor: remaining items are
                # stranded, so the result cannot be presented as complete.
                possibly_truncated = True
                break
            cursor = new_cursor
        else:
            # Budget reached with the backend still offering a cursor —
            # expose it so the caller has a continuation instead of an
            # invisible cliff.
            continuation_cursor = cursor

        if not collected:
            if cursor_argument is not None:
                # Resumed past the end of the listing. The run's total is
                # unknown from here (earlier pages may have returned items),
                # so this is end-of-results — not a zero-feedback run, and
                # not worth a run-existence lookup.
                return self.formatter.format_success_response(
                    message=(
                        f"No further feedback items for run {run_id} beyond the"
                        " supplied cursor (end of results)"
                    ),
                    data={"feedback": [], "count": 0, "end_of_results": True},
                    action="list_feedback",
                )
            return await self._render_empty_feedback(client, cast(str, run_id))

        message = f"Retrieved {len(collected)} feedback items for run {run_id}"
        if possibly_truncated:
            message += (
                " (the response may have been capped by the server and the"
                " endpoint returned no usable cursor — more items may exist)"
            )

        data: Dict[str, Any] = {
            "feedback": collected,
            "count": len(collected),
            "possibly_truncated": possibly_truncated,
        }
        if continuation_cursor is not None:
            data["next_cursor"] = continuation_cursor

        return self.formatter.format_success_response(
            message=message,
            data=data,
            action="list_feedback",
        )

    @staticmethod
    def _is_not_found(error: ReveniumAPIError) -> bool:
        """True for the not-found family, matching _format_api_error's NOT_FOUND
        branch and covering 404s that arrive without an RFC 7807 code."""
        return (
            getattr(error, "code", None) == "NOT_FOUND"
            or getattr(error, "status_code", None) == 404
        )

    async def _render_empty_feedback(
        self,
        client: "ReveniumClient",
        run_id: str,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Resolve what an empty feedback list actually means before reporting it.

        The feedback endpoint answers 200 with an empty body for an unknown run as
        well as for a real run with no feedback, so the empty page is ambiguous on
        its own and reporting "0 items" for a typo'd run_id would be a false
        negative. One extra read of the run disambiguates: a not-found there means
        the run_id is wrong and gets the same structured not-found the get_run
        action produces, now naming the run_id; any other failure propagates
        untouched so the envelope stays isError:true.
        """
        try:
            await client.get_recommendation_run(run_id, slim=True)
        except ReveniumAPIError as error:
            if not self._is_not_found(error):
                raise
            return self.formatter.format_error_response(
                message=f"Run '{run_id}' was not found.",
                error_code=ErrorCodes.RESOURCE_NOT_FOUND,
                suggestions=[
                    "Confirm the run_id / recommendation_id from list_runs or trigger_run",
                ],
            )
        return self.formatter.format_success_response(
            message=f"Run {run_id} exists and has 0 feedback items",
            data={"feedback": [], "count": 0, "run_id": run_id, "run_exists": True},
            action="list_feedback",
        )

    async def _handle_trigger_run(
        self,
        arguments: Dict[str, Any],
        *,
        ctx: Optional["TenantContext"] = None,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        period_start = arguments.get("period_start")
        period_end = arguments.get("period_end")
        for field, value in (("period_start", period_start), ("period_end", period_end)):
            if not value:
                raise create_structured_validation_error(
                    message=f"{field} is required (ISO 8601 string)",
                    field=field,
                    value=value,
                    suggestions=["e.g. 2026-01-01T00:00:00Z"],
                )

        client = await self.get_client(ctx=ctx)
        result = await client.trigger_recommendation_run(
            period_start=cast(str, period_start),
            period_end=cast(str, period_end),
            filter_agent=arguments.get("filter_agent"),
            filter_product_id=arguments.get("filter_product_id"),
            filter_trace_type=arguments.get("filter_trace_type"),
            filter_consuming_org_id=arguments.get("filter_consuming_org_id"),
            filter_environment=arguments.get("filter_environment", ""),
            filter_include_coding_assistants=arguments.get("filter_include_coding_assistants", True),
            filter_include_coding_assistants_for_cost_detectors=arguments.get(
                "filter_include_coding_assistants_for_cost_detectors", False,
            ),
            exclude_investigator_ids=arguments.get("exclude_investigator_ids"),
        )
        run_id = result.get("runId")
        if run_id is None:
            raise ToolError(
                message="Backend returned no runId for trigger_run",
                error_code=ErrorCodes.API_ERROR,
                suggestions=[
                    "Retry the trigger_run call; if it persists, contact support",
                ],
            )
        return self.formatter.format_success_response(
            message=f"Analysis run triggered: {run_id} "
                    f"(status: {result.get('status', 'running')})",
            data=result,
            action="trigger_run",
        )

    async def _handle_submit_feedback(
        self,
        arguments: Dict[str, Any],
        *,
        ctx: Optional["TenantContext"] = None,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        run_id = arguments.get("run_id")
        recommendation_id = arguments.get("recommendation_id")
        feedback_action = arguments.get("feedback_action")

        for field, value in (
            ("run_id", run_id),
            ("recommendation_id", recommendation_id),
            ("feedback_action", feedback_action),
        ):
            if not value:
                raise create_structured_validation_error(
                    message=f"{field} is required for action='submit_feedback'",
                    field=field, value=value,
                    suggestions=[
                        "feedback_action must be one of: acknowledged | implemented | "
                        "dismissed | not_applicable | already_aware"
                    ],
                )

        client = await self.get_client(ctx=ctx)
        result = await client.submit_recommendation_feedback(
            cast(str, run_id),
            cast(str, recommendation_id),
            cast(str, feedback_action),
            dismissal_reason=arguments.get("dismissal_reason", ""),
            confidence_rating=int(arguments.get("confidence_rating", 0)),
            realized_savings=arguments.get("realized_savings", 0),
            realized_savings_currency=arguments.get("realized_savings_currency", "USD"),
            realized_savings_measured_at=arguments.get("realized_savings_measured_at"),
        )
        return self.formatter.format_success_response(
            message=f"Feedback recorded for recommendation {recommendation_id}",
            data=result,
            action="submit_feedback",
        )

    async def _get_supported_actions(self) -> List[str]:
        return [
            "trigger_run", "get_run", "list_runs",
            "submit_feedback", "list_feedback", "list_investigators",
            "get_capabilities", "get_examples", "get_agent_summary",
        ]

    async def _handle_get_capabilities(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        return self.formatter.format_success_response(
            message="Capabilities for manage_ai_insights",
            data={
                "tool_name": self.tool_name,
                "supported_actions": await self._get_supported_actions(),
                "description": self.tool_description,
                "default_max_results": self.DEFAULT_MAX_RESULTS,
                "hard_cap_max_results": self.HARD_CAP_MAX_RESULTS,
                "default_slim_on_get_run": True,
            },
            action="get_capabilities",
        )

    async def _handle_get_examples(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        examples_md = (
            "# manage_ai_insights — Usage examples\n\n"
            "## Discover detectors\n"
            "`action=list_investigators` — returns the catalog so you can pass valid IDs "
            "to `exclude_investigator_ids` on trigger_run.\n\n"
            "## Trigger an analysis run (async)\n"
            "`action=trigger_run`, `period_start=2026-01-01T00:00:00Z`, "
            "`period_end=2026-01-31T23:59:59Z`. Returns immediately with `runId` and "
            "`status=running`. Poll `get_run` until status is one of "
            "`completed | partial | failed | cancelled`.\n\n"
            "## Read a run (compact)\n"
            "`action=get_run`, `run_id=<id>` — defaults to slim mode (compact "
            "`recommendationsSummary`). Pass `slim=false` to get raw findingsJson + "
            "parsedFindings.\n\n"
            "## List recent runs\n"
            "`action=list_runs`, optional `status=completed`, `since=...`, "
            "`triggered_by=api`, `max_results=200` (auto-paginates up to "
            f"{AIInsightsManagement.HARD_CAP_MAX_RESULTS}).\n\n"
            "## Submit feedback\n"
            "`action=submit_feedback`, `run_id`, `recommendation_id`, "
            "`feedback_action=implemented`, optional `realized_savings`, "
            "`realized_savings_currency` (default USD).\n"
        )
        return self.formatter.format_success_response(
            message="Usage examples for manage_ai_insights",
            data={"examples_markdown": examples_md},
            action="get_examples",
        )

    async def _handle_get_agent_summary(
        self,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        summary = (
            "manage_ai_insights wraps Revenium's AI cost-intelligence pipeline. "
            "Trigger a run (async: returns runId; poll get_run until status!=running), "
            "then read findings via get_run (defaults to compact slim mode). "
            "List endpoints auto-paginate up to a hard cap of "
            f"{AIInsightsManagement.HARD_CAP_MAX_RESULTS}. "
            "Submit feedback per recommendation to record outcomes."
        )
        return self.formatter.format_success_response(
            message="Agent summary for manage_ai_insights",
            data={"summary": summary},
            action="get_agent_summary",
        )

    async def _get_input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": await self._get_supported_actions()},
                "run_id": {"type": "string"},
                "recommendation_id": {"type": "string"},
                "feedback_action": {
                    "type": "string",
                    "enum": [
                        "acknowledged", "implemented", "dismissed",
                        "not_applicable", "already_aware",
                    ],
                },
                "period_start": {"type": "string", "description": "ISO 8601 datetime"},
                "period_end":   {"type": "string", "description": "ISO 8601 datetime"},
                "filter_agent":             {"type": "array", "items": {"type": "string"}},
                "filter_product_id":        {"type": "array", "items": {"type": "string"}},
                "filter_trace_type":        {"type": "array", "items": {"type": "string"}},
                "filter_consuming_org_id":  {"type": "array", "items": {"type": "string"}},
                "filter_environment":       {"type": "string"},
                "filter_include_coding_assistants": {"type": "boolean"},
                "filter_include_coding_assistants_for_cost_detectors": {"type": "boolean"},
                "exclude_investigator_ids": {"type": "array", "items": {"type": "string"}},
                "slim": {"type": "boolean"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 1000},
                "cursor": {"type": "string"},
                "status": {"type": "string"},
                "since": {"type": "string"},
                "until": {"type": "string"},
                "triggered_by": {"type": "string"},
                "dismissal_reason": {"type": "string"},
                "confidence_rating": {"type": "integer", "minimum": -1, "maximum": 1},
                "realized_savings": {},
                "realized_savings_currency": {"type": "string"},
                "realized_savings_measured_at": {"type": "string"},
            },
            "required": ["action"],
        }

    def _format_api_error(
        self, error: ReveniumAPIError,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Translate the handful of known RFC 7807 codes into friendly guidance.

        Only codes with a bespoke, actionable render are handled here (the
        not-found / disabled / backend-unavailable translations). Every other
        error — including auth failures — is re-raised so FastMCP marks the
        response envelope isError:true instead of hiding the failure in
        success-shaped content text.
        """
        code = getattr(error, "code", None)
        raw_message = str(getattr(error, "message", None) or error)

        if code == "AI_RECOMMENDATIONS_DISABLED":
            # An authorization state, not an informational one: raise so the
            # envelope carries isError:true while keeping the friendly guidance.
            raise ToolError(
                message="AI recommendations is not enabled for this team.",
                error_code=ErrorCodes.API_AUTHORIZATION,
                suggestions=[
                    "Contact your Revenium admin to enable AI Recommendations for this tenant",
                ],
            )
        if code == "IDEMPOTENCY_BACKEND_UNAVAILABLE":
            return self.formatter.format_error_response(
                message="AI Insights backend is temporarily unavailable. Retry shortly.",
                error_code=ErrorCodes.RESOURCE_UNAVAILABLE,
                suggestions=[
                    "Wait 10-30 seconds and retry; if it persists, contact support",
                ],
            )
        if code == "NOT_FOUND":
            return self.formatter.format_error_response(
                message=raw_message,
                error_code=ErrorCodes.RESOURCE_NOT_FOUND,
                suggestions=[
                    "Confirm the run_id / recommendation_id from list_runs or trigger_run",
                ],
            )
        # Unknown code (or no code, e.g. auth failures) has no bespoke render;
        # re-raise so FastMCP surfaces it with isError:true rather than burying
        # it in success-shaped content text.
        raise error
