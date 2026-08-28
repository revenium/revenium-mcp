"""Job management tool for Revenium Jobs & Outcomes system.

Exposes 7 API endpoints under /v2/api/jobs for tracking job performance,
ROI, conversion funnels, and reporting outcomes.
"""

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

if TYPE_CHECKING:
    from ..auth.tenant_context import TenantContext

from loguru import logger
from mcp.types import EmbeddedResource, ImageContent, TextContent

from ..client import ReveniumAPIError, ReveniumClient
from ..common.error_handling import ErrorCodes, ToolError
from ..common.validation import apply_filter_allowlist
from ..introspection.metadata import (
    ResourceRelationship,
    ToolCapability,
    ToolType,
    UsagePattern,
)
from .unified_tool_base import ToolBase


# BACK-1140: client-determinable upper bound on the page parameter.
# Without this, page=2147483647 (32-bit MAX_INT) and similar boundary
# inputs were forwarded straight to the backend, which returned a
# generic HTTP 500 ("An unexpected error occurred, please contact
# Revenium support") instead of a 400 naming the offending field. The
# bound is intentionally generous — even at the smallest documented
# size=1 it covers a million-row job dataset, far beyond what the
# Jobs & Outcomes API surfaces today — so it stays a guard against
# pathological inputs rather than a real cap on legitimate paging.
_MAX_JOBS_PAGE = 1_000_000

# BACK-1140: upper bound on the size parameter. Matches
# PaginationPerformanceManager.MAXIMUM_LIMIT (50), the Revenium API
# absolute maximum. Without this, size=2147483647 (32-bit MAX_INT)
# passed the `size <= 0` guard and was forwarded to the backend, which
# returned the same generic HTTP 500 this PR closed for page.
_MAX_JOBS_SIZE = 50

# snake_case filter name -> camelCase query parameter, bounded to what the
# endpoint declares. Verified 2026-08-28 against hypercurrent origin/develop
# JobController.list, which binds teamId, a Pageable (page, size, sort) and a
# JobSearchParams @ParameterObject whose fields are the names below
# (model/repository/specification/JobSearchParams.kt). teamId and page/size are
# set by the client.
_JOB_FILTER_MAP: Dict[str, str] = {
    "search": "search",
    "type": "type",
    "execution_status": "executionStatus",
    "outcome_type": "outcomeType",
    "outcome_value_min": "outcomeValueMin",
    "outcome_value_max": "outcomeValueMax",
    "environment": "environment",
    "start_date": "startDate",
    "end_date": "endDate",
    "sort": "sort",
}

# Verified 2026-08-28 against hypercurrent origin/develop
# JobController.getConversionFunnel: @RequestParam teamId / startDate / endDate
# / jobType / environment. teamId is set by the client. The funnel is not
# paginated, so there is no Pageable and no sort.
_CONVERSION_FUNNEL_FILTER_MAP: Dict[str, str] = {
    "start_date": "startDate",
    "end_date": "endDate",
    "job_type": "jobType",
    "environment": "environment",
}

# get_roi_summary drives one funnel call per job type, so it sets jobType
# itself and only accepts the date/environment narrowing from the caller.
_ROI_SUMMARY_FILTER_MAP: Dict[str, str] = {
    "start_date": "startDate",
    "end_date": "endDate",
    "environment": "environment",
}


def _strip_links(value: Any) -> Any:
    """Return a copy of ``value`` with all HAL ``_links`` keys removed.

    Upstream HAL+JSON responses embed ``_links.*.href`` URLs that point at
    the internal load-balancer hostname (e.g. ``api-lb.dev.hcapp.io``).
    Forwarding those leaks internal infrastructure topology to MCP callers.
    Strip ``_links`` recursively at the tool boundary so the response carries
    only public-shape fields. Operates on a fresh structure — input is not
    mutated.
    """
    if isinstance(value, dict):
        return {k: _strip_links(v) for k, v in value.items() if k != "_links"}
    if isinstance(value, list):
        return [_strip_links(item) for item in value]
    return value


def _validate_jobs_pagination(page: Any, size: Any) -> None:
    """Reject client-determinable boundary inputs with a structured 400.

    Raises:
        ToolError: when page or size is non-integer, negative, or exceeds
            the bound; carries field/value/expected so the caller can fix
            their input without inspecting a server-side traceback.
    """
    for label, value in (("page", page), ("size", size)):
        if not isinstance(value, int) or isinstance(value, bool):
            raise ToolError(
                message=f"{label} must be an integer (got {type(value).__name__})",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field=label,
                value=value,
                suggestions=[
                    f"Pass an integer for {label} (no quotes, no booleans)",
                ],
            )
    if page < 0:
        raise ToolError(
            message=f"page must be >= 0 (got {page})",
            error_code=ErrorCodes.VALIDATION_ERROR,
            field="page",
            value=page,
            suggestions=["Use page=0 for the first page; pages are zero-indexed"],
        )
    if page > _MAX_JOBS_PAGE:
        raise ToolError(
            message=(
                f"page exceeds maximum (expected 0 <= page <= {_MAX_JOBS_PAGE}, got {page})"
            ),
            error_code=ErrorCodes.VALIDATION_ERROR,
            field="page",
            value=page,
            suggestions=[
                "Pick a smaller page; very large indices indicate an off-by-one or "
                "misuse — the underlying dataset never reaches this depth.",
                "If you are looking for a specific job, use get_job(job_id=...) "
                "instead of paginating to find it.",
            ],
        )
    if size <= 0:
        raise ToolError(
            message=f"size must be > 0 (got {size})",
            error_code=ErrorCodes.VALIDATION_ERROR,
            field="size",
            value=size,
            suggestions=["Use size between 1 and 50 (default 20)"],
        )
    if size > _MAX_JOBS_SIZE:
        raise ToolError(
            message=(
                f"size exceeds maximum (expected 1 <= size <= {_MAX_JOBS_SIZE}, got {size})"
            ),
            error_code=ErrorCodes.VALIDATION_ERROR,
            field="size",
            value=size,
            suggestions=[
                f"Use size between 1 and {_MAX_JOBS_SIZE} (default 20)",
                "Paginate with larger page numbers instead of oversized page sizes.",
            ],
        )


class JobManager:
    """Internal manager wrapping async client calls for Jobs & Outcomes API."""

    def __init__(self, client: ReveniumClient):
        self.client = client

    async def list_jobs(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """List jobs with pagination."""
        page = arguments.get("page", 0)
        size = arguments.get("size", 20)
        filters = apply_filter_allowlist(
            arguments.get("filters"), _JOB_FILTER_MAP, action="list_jobs"
        )
        _validate_jobs_pagination(page, size)
        response = await self.client.get_jobs(page=page, size=size, **filters)
        jobs = self.client._extract_embedded_data(response)
        page_info = self.client._extract_pagination_info(response)
        return {
            "action": "list_jobs",
            "data": _strip_links(jobs),
            "pagination": {
                "page": page,
                "size": size,
                "total_pages": page_info.get("totalPages", 1),
                "total_items": page_info.get("totalElements", len(jobs)),
                "has_next": page < page_info.get("totalPages", 1) - 1,
                "has_previous": page > 0,
            },
            "metadata": {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")},
        }

    async def get_job(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get a specific job by ID."""
        job_id = arguments.get("job_id")
        if not job_id:
            raise ToolError(
                message="job_id is required for get_job action",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field="job_id",
                suggestions=["Use list_jobs to find valid job IDs"],
            )
        result = await self.client.get_job_by_id(job_id)
        return {"action": "get_job", "job_id": job_id, "data": _strip_links(result)}

    async def get_job_transactions(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get transactions for a job."""
        job_id = arguments.get("job_id")
        if not job_id:
            raise ToolError(
                message="job_id is required for get_job_transactions action",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field="job_id",
                suggestions=["Use list_jobs to find valid job IDs"],
            )
        page = arguments.get("page", 0)
        size = arguments.get("size", 20)
        _validate_jobs_pagination(page, size)
        response = await self.client.get_job_transactions(job_id, page=page, size=size)
        transactions = self.client._extract_embedded_data(response)
        page_info = self.client._extract_pagination_info(response)
        return {
            "action": "get_job_transactions",
            "job_id": job_id,
            "data": _strip_links(transactions),
            "pagination": {
                "page": page,
                "size": size,
                "total_pages": page_info.get("totalPages", 1),
                "total_items": page_info.get("totalElements", len(transactions)),
                "has_next": page < page_info.get("totalPages", 1) - 1,
                "has_previous": page > 0,
            },
        }

    async def get_job_roi(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get ROI metrics for a job."""
        job_id = arguments.get("job_id")
        if not job_id:
            raise ToolError(
                message="job_id is required for get_job_roi action",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field="job_id",
                suggestions=["Use list_jobs to find valid job IDs"],
            )
        result = await self.client.get_job_roi(job_id)
        return {"action": "get_job_roi", "job_id": job_id, "data": _strip_links(result)}

    async def get_job_types(self, arguments: Dict[str, Any]) -> Dict[str, Any]:  # noqa: ARG002
        """Get available job types."""
        result = await self.client.get_job_types()
        types = self.client._extract_embedded_data(result) if isinstance(result, dict) else result
        return {"action": "get_job_types", "data": _strip_links(types)}

    async def get_conversion_funnel(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get global conversion funnel analytics with optional filters."""
        # paginated=False: this action takes no page/size arguments, so a
        # page/size inside filters would be a silent no-op rather than a
        # shadowed duplicate - reject it like any other unknown key.
        filters = apply_filter_allowlist(
            arguments.get("filters"),
            _CONVERSION_FUNNEL_FILTER_MAP,
            action="get_conversion_funnel",
            paginated=False,
        )
        result = await self.client.get_job_conversion_funnel(**filters)
        return {"action": "get_conversion_funnel", "data": _strip_links(result)}

    async def get_roi_summary(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get ROI summary across all job types with per-type conversion funnels.

        Orchestrates get_job_types + get_conversion_funnel(jobType=...) for each type,
        so jobType is set per call rather than accepted from the caller. The
        remaining funnel filters (start_date, end_date, environment) are passed
        through to every call.
        """
        date_filters = apply_filter_allowlist(
            arguments.get("filters"),
            _ROI_SUMMARY_FILTER_MAP,
            action="get_roi_summary",
            paginated=False,
        )

        # Step 1: Get all job types
        types_result = await self.client.get_job_types()
        job_types = (
            self.client._extract_embedded_data(types_result)
            if isinstance(types_result, dict)
            else types_result
        )

        # Normalize: job_types may be a list of strings or list of dicts
        type_names = []
        for jt in job_types:
            if isinstance(jt, str):
                type_names.append(jt)
            elif isinstance(jt, dict):
                type_names.append(jt.get("name", jt.get("type", str(jt))))
            else:
                type_names.append(str(jt))

        # Step 2: Fetch conversion funnel for each type concurrently
        async def fetch_funnel(job_type: str) -> Dict[str, Any]:
            try:
                funnel_filters = {"jobType": job_type, **date_filters}
                result = await self.client.get_job_conversion_funnel(**funnel_filters)
                return {"jobType": job_type, "data": _strip_links(result), "status": "success"}
            except Exception as e:
                logger.warning(f"Failed to fetch funnel for job type '{job_type}': {e}")
                status_code = getattr(e, "status_code", "unknown")
                return {
                    "jobType": job_type,
                    "data": None,
                    "status": "error",
                    "error": f"Request failed (status={status_code})",
                }

        funnel_results = await asyncio.gather(
            *[fetch_funnel(jt) for jt in type_names]
        )

        # Step 3: Aggregate results
        successful = [r for r in funnel_results if r["status"] == "success"]
        failed = [r for r in funnel_results if r["status"] == "error"]

        # If all funnel calls failed, surface the error instead of returning zeroed data
        if type_names and not successful:
            raise ToolError(
                message=(
                    f"All {len(failed)} job type funnel requests failed. "
                    f"First error: {failed[0].get('error', 'unknown')}"
                ),
                error_code=ErrorCodes.API_ERROR,
                suggestions=["Check API connectivity", "Verify API key permissions for /v2/api/jobs/conversion-funnel"],
            )

        total_jobs = sum(r["data"].get("totalJobs", 0) for r in successful)
        total_successful = sum(r["data"].get("successfulJobs", 0) for r in successful)
        total_converted = sum(r["data"].get("convertedJobs", 0) for r in successful)

        return {
            "action": "get_roi_summary",
            "summary": {
                "totalJobTypes": len(type_names),
                "totalJobs": total_jobs,
                "successfulJobs": total_successful,
                "convertedJobs": total_converted,
                "overallSuccessRate": round(total_successful / total_jobs, 4) if total_jobs > 0 else 0,
                "overallConversionRate": round(total_converted / total_jobs, 4) if total_jobs > 0 else 0,
            },
            "per_type_breakdown": list(funnel_results),
            "filters_applied": date_filters if date_filters else None,
            "partial_failures": len(failed),
            "metadata": {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")},
        }

    async def report_outcome(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Report an outcome for a job."""
        job_id = arguments.get("job_id")
        if not job_id:
            raise ToolError(
                message="job_id is required for report_outcome action",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field="job_id",
                suggestions=["Use list_jobs to find valid job IDs"],
            )
        outcome_data = arguments.get("outcome_data")
        if outcome_data is None:
            raise ToolError(
                message="outcome_data is required for report_outcome action",
                error_code=ErrorCodes.VALIDATION_ERROR,
                field="outcome_data",
                examples={
                    "report_outcome_converted": {
                        "executionStatus": "SUCCESS",
                        "outcomeType": "CONVERTED",
                        "outcomeValue": 99.99,
                        "outcomeCurrency": "USD",
                    },
                    "report_outcome_failed": {
                        "executionStatus": "FAILED",
                        "outcomeType": "UNSUCCESSFUL",
                        "outcomeReason": "Upstream agent timed out after 300s",
                    },
                },
                suggestions=[
                    "Provide a dict with 'executionStatus' (SUCCESS, FAILED, or CANCELLED) "
                    "plus optional 'outcomeType' (CONVERTED, ESCALATED, DEFLECTED, "
                    "UNSUCCESSFUL, or CUSTOM), 'outcomeValue', and 'outcomeCurrency'",
                    "When executionStatus is FAILED or CANCELLED, explain why in "
                    "'outcomeReason' — a human-readable string; do not bury the reason "
                    "inside 'metadata'",
                    "Keys are camelCase and are sent to the API exactly as given; a "
                    "snake_case or invented key is silently ignored upstream",
                ],
            )
        # outcome_data is forwarded verbatim so that fields added to the outcome
        # contract (outcomeReason was the most recent) reach the API without a
        # release here. Do not introduce key filtering or renaming on this path.
        try:
            result = await self.client.report_job_outcome(job_id, outcome_data)
            return {"action": "report_outcome", "job_id": job_id, "data": _strip_links(result)}
        except ReveniumAPIError as e:
            if e.status_code == 409:
                return {
                    "action": "report_outcome",
                    "job_id": job_id,
                    "status": "conflict",
                    "message": (
                        f"Outcome already reported for job {job_id}. "
                        "Duplicate outcomes are not allowed. "
                        "Use get_job to verify the existing outcome."
                    ),
                }
            raise


class JobManagement(ToolBase):
    """Job management tool for the Jobs & Outcomes system."""

    tool_name = "manage_jobs"
    tool_description = (
        "Job and outcomes management for the Revenium platform. "
        "Track job performance, ROI, conversion funnels, and report outcomes. "
        "Key actions: list_jobs, get_job, get_job_transactions, get_job_roi, "
        "get_job_types, get_conversion_funnel, get_roi_summary, report_outcome. "
        "Use get_capabilities() for full details or get_examples() for usage templates."
    )
    business_category = "Core Business Management Tools"
    tool_type = ToolType.CRUD
    tool_version = "1.0.0"

    async def handle_action(
        self,
        action: str,
        arguments: Dict[str, Any],
        *,
        ctx: Optional["TenantContext"] = None,
    ) -> List[Union[TextContent, ImageContent, EmbeddedResource]]:
        """Handle job management actions."""
        try:
            client = await self.get_client(ctx=ctx)
            job_manager = JobManager(client)

            # --- Meta-actions ---

            if action == "get_capabilities":
                capabilities = {
                    "tool": self.tool_name,
                    "description": self.tool_description,
                    "version": self.tool_version,
                    "actions": await self._get_supported_actions(),
                    "business_actions": [
                        "list_jobs",
                        "get_job",
                        "get_job_transactions",
                        "get_job_roi",
                        "get_job_types",
                        "get_conversion_funnel",
                        "get_roi_summary",
                        "report_outcome",
                    ],
                    "meta_actions": [
                        "get_capabilities",
                        "get_examples",
                        "get_tool_metadata",
                        "get_agent_summary",
                    ],
                    "parameters": {
                        "list_jobs": {
                            "page": "int (default 0)",
                            "size": "int (default 20)",
                            "filters": (
                                "dict (optional) — supported keys: "
                                "search (free text), "
                                "type (job type, case-insensitive), "
                                "executionStatus (SUCCESS|FAILED|CANCELLED), "
                                "outcomeType (CONVERTED|ESCALATED|DEFLECTED|UNSUCCESSFUL|CUSTOM|PENDING), "
                                "outcomeValueMin, outcomeValueMax, environment, "
                                "startDate (ISO 8601), endDate (ISO 8601), sort. "
                                "Any other key is rejected rather than silently ignored"
                            ),
                            "returns": (
                                "job records carrying outcomeReason — the human-readable "
                                "explanation of why a job failed or was cancelled (null "
                                "until an outcome with a reason is reported)"
                            ),
                        },
                        "get_job": {
                            "job_id": "str (required)",
                            "returns": (
                                "a job record carrying outcomeReason — read it instead of "
                                "parsing a reason out of outcomeMetadata"
                            ),
                        },
                        "get_job_transactions": {
                            "job_id": "str (required)",
                            "page": "int (default 0)",
                            "size": "int (default 20)",
                        },
                        "get_job_roi": {"job_id": "str (required)"},
                        "get_job_types": {},
                        "get_conversion_funnel": {
                            "filters": (
                                "dict (optional) — supported keys: "
                                "jobType (case-insensitive), startDate (ISO 8601), "
                                "endDate (ISO 8601), environment"
                            ),
                        },
                        "get_roi_summary": {
                            "filters": (
                                "dict (optional) — supported keys: "
                                "startDate (ISO 8601), endDate (ISO 8601), environment. "
                                "Orchestrates get_job_types + per-type conversion funnels, "
                                "so jobType is set per call and not accepted here."
                            ),
                        },
                        "report_outcome": {
                            "job_id": "str (required)",
                            "outcome_data": (
                                "dict (required), camelCase keys forwarded verbatim: "
                                "executionStatus (SUCCESS|FAILED|CANCELLED, required), "
                                "outcomeType (CONVERTED|ESCALATED|DEFLECTED|UNSUCCESSFUL|CUSTOM), "
                                "outcomeValue (number), outcomeCurrency (ISO 4217, defaults to USD), "
                                "metadata (JSON string), "
                                "outcomeReason (str — human-readable explanation of why the "
                                "job failed or was cancelled). "
                                "outcomeReason is a key of this dict; only job_id and "
                                "outcome_data are read from the call, so a sibling argument "
                                "of any other name is dropped"
                            ),
                        },
                    },
                }
                return [TextContent(type="text", text=json.dumps(capabilities, indent=2))]

            elif action == "get_examples":
                examples = {
                    "list_jobs": {
                        "description": (
                            "List all jobs with pagination. Each job record carries "
                            "outcomeReason, the human-readable explanation of a failed or "
                            "cancelled outcome"
                        ),
                        "example": {"action": "list_jobs", "page": 0, "size": 20},
                        "with_filters": {
                            "action": "list_jobs",
                            "page": 0,
                            "size": 10,
                            "filters": {"type": "loan_processing", "executionStatus": "SUCCESS"},
                        },
                    },
                    "get_job": {
                        "description": (
                            "Get a specific job by ID. The record carries outcomeReason "
                            "alongside outcomeType, outcomeValue and outcomeMetadata"
                        ),
                        "example": {"action": "get_job", "job_id": "job_123"},
                    },
                    "get_job_transactions": {
                        "description": "Get transactions for a job",
                        "example": {
                            "action": "get_job_transactions",
                            "job_id": "job_123",
                            "page": 0,
                            "size": 20,
                        },
                    },
                    "get_job_roi": {
                        "description": "Get ROI metrics for a job",
                        "example": {"action": "get_job_roi", "job_id": "job_123"},
                    },
                    "get_job_types": {
                        "description": "Get all available job types",
                        "example": {"action": "get_job_types"},
                    },
                    "get_conversion_funnel": {
                        "description": "Get global conversion funnel analytics (total/successful/converted)",
                        "example": {"action": "get_conversion_funnel"},
                        "with_filters": {
                            "action": "get_conversion_funnel",
                            "filters": {"startDate": "2025-01-01", "endDate": "2025-12-31", "jobType": "LEAD"},
                        },
                    },
                    "get_roi_summary": {
                        "description": "Get aggregated ROI summary across all job types with per-type breakdown",
                        "example": {"action": "get_roi_summary"},
                        "with_filters": {
                            "action": "get_roi_summary",
                            "filters": {"startDate": "2025-01-01", "endDate": "2025-12-31"},
                        },
                    },
                    "report_outcome": {
                        "description": (
                            "Report an outcome for a job (409 = duplicate, already reported). "
                            "outcome_data keys are sent to the API verbatim, so use the "
                            "camelCase spellings below"
                        ),
                        "execution_statuses": ["SUCCESS", "FAILED", "CANCELLED"],
                        "outcome_types": [
                            "CONVERTED",
                            "ESCALATED",
                            "DEFLECTED",
                            "UNSUCCESSFUL",
                            "CUSTOM",
                        ],
                        "example_converted": {
                            "action": "report_outcome",
                            "job_id": "job_123",
                            "outcome_data": {
                                "executionStatus": "SUCCESS",
                                "outcomeType": "CONVERTED",
                                "outcomeValue": 99.99,
                                "outcomeCurrency": "USD",
                            },
                        },
                        "example_unsuccessful": {
                            "action": "report_outcome",
                            "job_id": "job_456",
                            "outcome_data": {
                                "executionStatus": "SUCCESS",
                                "outcomeType": "UNSUCCESSFUL",
                                "outcomeReason": "Customer declined after the trial period",
                            },
                        },
                        "example_failed": {
                            "action": "report_outcome",
                            "job_id": "job_789",
                            "outcome_data": {
                                "executionStatus": "FAILED",
                                "outcomeReason": "Upstream agent timed out after 300s",
                            },
                        },
                    },
                }
                return [TextContent(type="text", text=json.dumps(examples, indent=2))]

            elif action == "get_tool_metadata":
                metadata = await self.get_tool_metadata()
                return [TextContent(type="text", text=json.dumps(metadata.to_dict(), indent=2))]

            elif action == "get_agent_summary":
                summary = await self._get_agent_summary()
                return [TextContent(type="text", text=summary)]

            # --- Business actions ---

            elif action == "list_jobs":
                result = await job_manager.list_jobs(arguments)
                return [
                    TextContent(
                        type="text",
                        text=f"Jobs (page {arguments.get('page', 0) + 1}):\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            elif action == "get_job":
                result = await job_manager.get_job(arguments)
                return [
                    TextContent(
                        type="text",
                        text=f"Job details for {arguments.get('job_id')}:\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            elif action == "get_job_transactions":
                result = await job_manager.get_job_transactions(arguments)
                return [
                    TextContent(
                        type="text",
                        text=f"Transactions for job {arguments.get('job_id')}:\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            elif action == "get_job_roi":
                result = await job_manager.get_job_roi(arguments)
                return [
                    TextContent(
                        type="text",
                        text=f"ROI for job {arguments.get('job_id')}:\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            elif action == "get_job_types":
                result = await job_manager.get_job_types(arguments)
                return [
                    TextContent(
                        type="text",
                        text="Available job types:\n\n" + json.dumps(result, indent=2),
                    )
                ]

            elif action == "get_conversion_funnel":
                result = await job_manager.get_conversion_funnel(arguments)
                return [
                    TextContent(
                        type="text",
                        text="Conversion funnel analytics:\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            elif action == "get_roi_summary":
                result = await job_manager.get_roi_summary(arguments)
                return [
                    TextContent(
                        type="text",
                        text="ROI summary across all job types:\n\n"
                        + json.dumps(result, indent=2),
                    )
                ]

            elif action == "report_outcome":
                result = await job_manager.report_outcome(arguments)
                if result.get("status") == "conflict":
                    prefix = f"Outcome already exists for job {arguments.get('job_id')}"
                else:
                    prefix = f"Outcome reported for job {arguments.get('job_id')}"
                return [
                    TextContent(
                        type="text",
                        text=f"{prefix}:\n\n" + json.dumps(result, indent=2),
                    )
                ]

            else:
                return [
                    TextContent(
                        type="text",
                        text=f"Unknown action '{action}'. "
                        f"Use get_capabilities() to see all supported actions.",
                    )
                ]

        except ReveniumAPIError as e:
            logger.error(f"API error in manage_jobs: {e}")
            raise
        except Exception as e:
            logger.error(f"Error in manage_jobs: {e}")
            raise

    # --- ToolBase metadata method overrides ---

    async def _get_supported_actions(self) -> List[str]:
        """Return all supported actions."""
        return [
            "get_capabilities",
            "get_examples",
            "get_tool_metadata",
            "get_agent_summary",
            "list_jobs",
            "get_job",
            "get_job_transactions",
            "get_job_roi",
            "get_job_types",
            "get_conversion_funnel",
            "get_roi_summary",
            "report_outcome",
        ]

    async def _get_tool_capabilities(self) -> List[ToolCapability]:
        """Get job management tool capabilities."""
        return [
            ToolCapability(
                name="Job Listing and Retrieval",
                description=(
                    "List and retrieve job details with pagination support; job records "
                    "carry outcomeReason for failed or cancelled outcomes"
                ),
                parameters={
                    "list_jobs": {"page": "int", "size": "int", "filters": "dict"},
                    "get_job": {"job_id": "str"},
                },
                examples=["list_jobs(page=0, size=20)", "get_job(job_id='job_123')"],
            ),
            ToolCapability(
                name="Job Analytics",
                description="Access job transactions, ROI metrics, conversion funnel data, and aggregate ROI summaries",
                parameters={
                    "get_job_transactions": {"job_id": "str", "page": "int", "size": "int"},
                    "get_job_roi": {"job_id": "str"},
                    "get_conversion_funnel": {"filters": "dict (optional)"},
                    "get_roi_summary": {"filters": "dict (optional: startDate, endDate, environment)"},
                },
                examples=[
                    "get_job_transactions(job_id='job_123')",
                    "get_job_roi(job_id='job_123')",
                    "get_conversion_funnel(filters={'jobType': 'LEAD'})",
                    "get_roi_summary()",
                    "get_roi_summary(filters={'startDate': '2025-01-01', 'endDate': '2025-12-31'})",
                ],
            ),
            ToolCapability(
                name="Job Types and Outcomes",
                description="Retrieve available job types and report job outcomes",
                parameters={
                    "get_job_types": {},
                    "report_outcome": {"job_id": "str", "outcome_data": "dict"},
                },
                examples=[
                    "get_job_types()",
                    "report_outcome(job_id='job_123', outcome_data={'executionStatus': "
                    "'SUCCESS', 'outcomeType': 'CONVERTED', 'outcomeValue': 99.99})",
                    "report_outcome(job_id='job_789', outcome_data={'executionStatus': "
                    "'FAILED', 'outcomeReason': 'Upstream agent timed out after 300s'})",
                ],
            ),
        ]

    async def _get_resource_relationships(self) -> List[ResourceRelationship]:
        """Get resource relationships for job management."""
        return [
            ResourceRelationship(
                resource_type="subscriptions",
                relationship_type="enhances",
                description="Jobs track performance outcomes for subscription-based workflows",
                cardinality="N:1",
                optional=True,
            ),
            ResourceRelationship(
                resource_type="customers",
                relationship_type="requires",
                description="Jobs are associated with customer organizations",
                cardinality="N:1",
                optional=False,
            ),
            ResourceRelationship(
                resource_type="products",
                relationship_type="enhances",
                description="Jobs measure conversion performance against product offerings",
                cardinality="N:M",
                optional=True,
            ),
        ]

    async def _get_usage_patterns(self) -> List[UsagePattern]:
        """Get common usage patterns for job management."""
        return [
            UsagePattern(
                pattern_name="Job Performance Review",
                description="Analyze job performance with ROI and transaction data",
                frequency=0.8,
                typical_sequence=["list_jobs", "get_job", "get_job_roi", "get_job_transactions"],
                common_parameters={"page": 0, "size": 20},
                success_indicators=["Jobs listed", "ROI data retrieved"],
            ),
            UsagePattern(
                pattern_name="Conversion Analysis",
                description="Review conversion funnel and report outcomes",
                frequency=0.6,
                typical_sequence=["list_jobs", "get_conversion_funnel", "report_outcome"],
                common_parameters={},
                success_indicators=["Funnel data retrieved", "Outcome reported"],
            ),
            UsagePattern(
                pattern_name="Job Discovery",
                description="Explore available job types and current jobs",
                frequency=0.5,
                typical_sequence=["get_job_types", "list_jobs"],
                common_parameters={},
                success_indicators=["Job types listed", "Jobs enumerated"],
            ),
        ]

    async def _get_agent_summary(self) -> str:
        """Get agent-friendly summary for job management."""
        return """**Job Management Tool (manage_jobs)**

Track and analyze job performance in the Revenium Jobs & Outcomes system.

**Key Actions:**
• list_jobs — List all jobs with pagination
• get_job — Get job details by ID, including outcomeReason for failed or cancelled jobs
• get_job_transactions — View transactions for a job
• get_job_roi — Get ROI metrics for a job
• get_job_types — List available job types
• get_conversion_funnel — View conversion funnel data
• get_roi_summary — Aggregated ROI across all job types (orchestrates types + funnels)
• report_outcome — Report a job outcome (executionStatus plus optional outcomeType and
  outcomeReason; 409 = already reported)

**Quick Start:**
1. Call get_capabilities() to explore all parameters
2. Use list_jobs() to find existing jobs
3. Analyze performance with get_job_roi(), get_conversion_funnel(), or get_roi_summary()
4. Report results with report_outcome()"""

    async def _get_quick_start_guide(self) -> List[str]:
        """Get quick start guide for job management."""
        return [
            "Call get_capabilities() to see all available actions and parameters",
            "Use list_jobs(page=0, size=20) to browse existing jobs",
            "Get detailed job info with get_job(job_id='...')",
            "Analyze performance using get_job_roi(), get_conversion_funnel(), or get_roi_summary()",
            "Report job outcomes with report_outcome(job_id='...', outcome_data={...})",
        ]

    async def _get_common_use_cases(self) -> List[str]:
        """Get common use cases for job management."""
        return [
            "Track AI job ROI to measure cost-effectiveness of automated workflows",
            "Analyze conversion funnels to identify drop-off points in customer journeys",
            "Report job outcomes to feed data back into the Revenium analytics pipeline",
            "List and filter jobs to monitor active and completed job statuses",
            "Retrieve job transactions for detailed billing and usage audits",
        ]

    async def _get_troubleshooting_tips(self) -> List[str]:
        """Get troubleshooting tips for job management."""
        return [
            "If report_outcome returns a 409 conflict, the outcome was already reported — use get_job to verify",
            "If list_jobs returns empty results, check filters or try with page=0 and no filters",
            "If get_job_roi returns no data, the job may still be running or not have sufficient transaction history",
            "Ensure job_id is a valid string identifier — use list_jobs to confirm IDs",
            "For pagination, start with page=0 and check has_next to determine if more pages exist",
        ]
