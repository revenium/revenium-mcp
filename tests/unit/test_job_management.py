"""Unit tests for Job Management tools.

Tests the JobManager and JobManagement classes from the decomposed tools module.
Focuses on 7 business actions, meta-actions, and the 409 Conflict edge case.
"""

import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.tools_decomposed import job_management as job_management_module
from src.revenium_mcp_server.tools_decomposed.job_management import (
    JobManager,
    JobManagement,
    _SESSION_ATTRIBUTION_FIELDS,
    _parse_outcome_conflict_version,
    _SESSION_ATTRIBUTION_REASON_NOTE,
    _SESSION_ATTRIBUTION_SPLITS_NOTE,
    _render_session_attributions,
    _session_attribution_intervals,
    _strip_links,
)
from src.revenium_mcp_server.client import ReveniumAPIError
from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError
from mcp.types import TextContent


# The published GET /api/v2/analytics/jobs/roi-summary envelope (isotope), with
# the field set the byJobType row declares. Built once here so a test that
# narrows a field is visibly narrowing this shape rather than inventing one.
ROI_SUMMARY_RESPONSE = {
    "id": "jobs-roi-summary",
    "resourceType": "JobTypeRoiSummary",
    "label": "Job type ROI summary",
    "period": {"start": "2026-08-05T00:00:00.000Z", "end": "2026-09-04T00:00:00.000Z"},
    "byJobType": [
        {
            "jobType": "LEAD_QUALIFICATION",
            "totalJobs": 2,
            "totalCost": 3.5,
            "tokenCost": 2.0,
            "externalToolCost": 1.0,
            "humanCost": 0.5,
            "conversions": 1,
            "deflections": 0,
            "totalValue": 100.0,
            "averageValue": 50.0,
            "costPerConversion": 3.5,
            "costPerOutcome": 3.5,
            "roi": 27.57,
            "successRate": 1.0,
            "toolCostAttribution": "ALLOCATED_BY_AGENT",
        },
        {
            "jobType": "SUPPORT_DEFLECTION",
            "totalJobs": 1,
            "totalCost": 0.5,
            "tokenCost": 0.5,
            "externalToolCost": 0.0,
            "humanCost": 0.0,
            "conversions": 0,
            "deflections": 1,
            "totalValue": 20.0,
            "averageValue": 20.0,
            "costPerConversion": 0.0,
            "costPerOutcome": 0.5,
            "roi": 39.0,
            "successRate": 1.0,
            "toolCostAttribution": "ALLOCATED_BY_AGENT",
        },
    ],
    "summary": {
        "totalJobTypes": 2,
        "totalJobs": 3,
        "totalCost": 4.0,
        "totalValue": 120.0,
        "overallROI": 29.0,
    },
    "_links": {
        "self": {"href": "https://api-lb.dev.hcapp.io/api/v2/analytics/jobs/roi-summary"}
    },
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_client():
    """Create a mock ReveniumClient for JobManager."""
    client = MagicMock()
    client.team_id = "test_team_id_789"
    client.get_jobs = AsyncMock()
    client.get_job_by_id = AsyncMock()
    client.get_job_transactions = AsyncMock()
    client.get_job_roi = AsyncMock()
    client.get_job_types = AsyncMock()
    client.get_job_conversion_funnel = AsyncMock()
    client.get_jobs_roi_summary = AsyncMock()
    client.report_job_outcome = AsyncMock()
    client.amend_job_outcome = AsyncMock()
    client.get_session_attributions = AsyncMock()
    client._extract_embedded_data = MagicMock()
    client._extract_pagination_info = MagicMock()
    return client


@pytest.fixture
def job_manager(mock_client):
    """Create JobManager with mocked client."""
    return JobManager(mock_client)


@pytest.fixture
def job_mgmt():
    """Create JobManagement instance (top-level tool)."""
    return JobManagement()


@pytest.fixture
def mock_mgmt_client(job_mgmt):
    """Patch JobManagement.get_client and return the mock client."""
    client = MagicMock()
    client.get_jobs = AsyncMock()
    client.get_job_by_id = AsyncMock()
    client.get_job_transactions = AsyncMock()
    client.get_job_roi = AsyncMock()
    client.get_job_types = AsyncMock()
    client.get_job_conversion_funnel = AsyncMock()
    client.get_jobs_roi_summary = AsyncMock()
    client.report_job_outcome = AsyncMock()
    client.amend_job_outcome = AsyncMock()
    client.get_session_attributions = AsyncMock()
    client._extract_embedded_data = MagicMock()
    client._extract_pagination_info = MagicMock()
    with patch.object(job_mgmt, "get_client", new_callable=AsyncMock) as mock_get_client:
        mock_get_client.return_value = client
        yield client


# ===========================================================================
# JobManager Business Action Tests
# ===========================================================================


class TestJobManagerListJobs:
    """Test JobManager.list_jobs behavior."""

    @pytest.mark.asyncio
    async def test_list_jobs_returns_paginated_result(self, job_manager, mock_client):
        """Listing jobs returns data with pagination metadata."""
        mock_client.get_jobs.return_value = {"_embedded": {"jobs": []}}
        mock_client._extract_embedded_data.return_value = [
            {"id": "j1", "name": "Job A"},
            {"id": "j2", "name": "Job B"},
        ]
        mock_client._extract_pagination_info.return_value = {
            "totalPages": 3,
            "totalElements": 45,
        }

        result = await job_manager.list_jobs({"page": 1, "size": 10})

        assert result["action"] == "list_jobs"
        assert len(result["data"]) == 2
        assert result["pagination"]["page"] == 1
        assert result["pagination"]["size"] == 10
        assert result["pagination"]["total_pages"] == 3
        assert result["pagination"]["total_items"] == 45
        assert result["pagination"]["has_next"] is True
        assert result["pagination"]["has_previous"] is True
        mock_client.get_jobs.assert_called_once_with(page=1, size=10)

    @pytest.mark.asyncio
    async def test_list_jobs_defaults_page_zero(self, job_manager, mock_client):
        """Listing without explicit page/size uses defaults."""
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {"totalPages": 1, "totalElements": 0}

        result = await job_manager.list_jobs({})

        mock_client.get_jobs.assert_called_once_with(page=0, size=20)
        assert result["pagination"]["has_previous"] is False

    @pytest.mark.asyncio
    async def test_list_jobs_last_page_has_no_next(self, job_manager, mock_client):
        """has_next is False when on the last page."""
        mock_client._extract_embedded_data.return_value = [{"id": "j1"}]
        mock_client._extract_pagination_info.return_value = {"totalPages": 2, "totalElements": 15}

        result = await job_manager.list_jobs({"page": 1, "size": 10})

        assert result["pagination"]["has_next"] is False

    @pytest.mark.asyncio
    async def test_list_jobs_passes_filters_to_client(self, job_manager, mock_client):
        """Filters are forwarded as keyword arguments to get_jobs."""
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {"totalPages": 1, "totalElements": 0}

        await job_manager.list_jobs({"page": 0, "size": 5, "filters": {"type": "loan_processing", "executionStatus": "SUCCESS"}})

        mock_client.get_jobs.assert_called_once_with(page=0, size=5, type="loan_processing", executionStatus="SUCCESS")


class TestJobFilterValueValidation:
    """BACK-2941: an unbindable enum value is refused here, not upstream.

    The backend answered an invalid executionStatus with Spring's own
    type-conversion 400, naming internal platform classes in the message.
    """

    @pytest.mark.asyncio
    async def test_invalid_execution_status_rejected_before_request(
        self, job_manager, mock_client
    ):
        with pytest.raises(ToolError) as exc_info:
            await job_manager.list_jobs({"filters": {"executionStatus": "BOGUS_STATUS"}})

        message = exc_info.value.message
        assert "BOGUS_STATUS" in message
        assert "SUCCESS" in message and "FAILED" in message and "CANCELLED" in message
        assert "io.hypercurrent" not in message
        assert exc_info.value.field == "filters.executionStatus"
        mock_client.get_jobs.assert_not_called()

    @pytest.mark.asyncio
    async def test_lowercase_filter_value_is_canonicalised_not_refused(self, job_manager, mock_client):
        """hypercurrent uppercases these values, so lowercase must keep working through the MCP."""
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {"totalPages": 1, "totalElements": 0}

        await job_manager.list_jobs({"filters": {"outcomeType": "converted", "executionStatus": "failed"}})

        mock_client.get_jobs.assert_called_once_with(page=0, size=20, outcomeType="CONVERTED", executionStatus="FAILED")

    @pytest.mark.asyncio
    async def test_virtual_pending_outcome_is_accepted(self, job_manager, mock_client):
        """PENDING is not an OutcomeType member but the platform documents it as a filter value."""
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {"totalPages": 1, "totalElements": 0}

        await job_manager.list_jobs({"filters": {"outcomeType": "PENDING"}})

        mock_client.get_jobs.assert_called_once_with(page=0, size=20, outcomeType="PENDING")

    @pytest.mark.asyncio
    async def test_invalid_outcome_type_rejected_before_request(
        self, job_manager, mock_client
    ):
        with pytest.raises(ToolError) as exc_info:
            await job_manager.list_jobs({"filters": {"outcome_type": "NOT_A_TYPE"}})

        assert "NOT_A_TYPE" in exc_info.value.message
        assert "CONVERTED" in exc_info.value.message
        mock_client.get_jobs.assert_not_called()

    @pytest.mark.asyncio
    async def test_valid_values_still_filter(self, job_manager, mock_client):
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {"totalPages": 1, "totalElements": 0}

        await job_manager.list_jobs(
            {"filters": {"executionStatus": "SUCCESS", "outcomeType": "CONVERTED"}}
        )

        mock_client.get_jobs.assert_called_once_with(
            page=0, size=20, executionStatus="SUCCESS", outcomeType="CONVERTED"
        )

    @pytest.mark.asyncio
    async def test_free_form_filter_values_are_not_checked(self, job_manager, mock_client):
        """`type` is a caller-defined job type, so its values stay unchecked."""
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {"totalPages": 1, "totalElements": 0}

        await job_manager.list_jobs({"filters": {"type": "anything_at_all"}})

        mock_client.get_jobs.assert_called_once_with(page=0, size=20, type="anything_at_all")

    @pytest.mark.asyncio
    async def test_unknown_key_message_is_unchanged(self, job_manager, mock_client):
        with pytest.raises(ToolError) as exc_info:
            await job_manager.list_jobs({"filters": {"nonsenseKey": "x"}})

        assert "Unknown filter key 'nonsenseKey' for 'list_jobs'" in exc_info.value.message
        assert exc_info.value.field == "filters"
        mock_client.get_jobs.assert_not_called()


class TestJobManagerGetJob:
    """Test JobManager.get_job behavior."""

    @pytest.mark.asyncio
    async def test_get_job_returns_data(self, job_manager, mock_client):
        """Getting a job by ID returns it wrapped with metadata."""
        mock_client.get_job_by_id.return_value = {"id": "j1", "name": "My Job"}

        result = await job_manager.get_job({"job_id": "j1"})

        assert result["action"] == "get_job"
        assert result["job_id"] == "j1"
        assert result["data"]["name"] == "My Job"
        mock_client.get_job_by_id.assert_called_once_with("j1")

    @pytest.mark.asyncio
    async def test_get_job_missing_id_raises_error(self, job_manager):
        """Getting a job without job_id raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await job_manager.get_job({})

        assert "job_id" in str(exc_info.value).lower()


class TestJobManagerGetJobTransactions:
    """Test JobManager.get_job_transactions behavior."""

    @pytest.mark.asyncio
    async def test_get_job_transactions_returns_paginated_data(self, job_manager, mock_client):
        """Getting transactions returns paginated results."""
        mock_client.get_job_transactions.return_value = {}
        mock_client._extract_embedded_data.return_value = [{"txn_id": "t1"}, {"txn_id": "t2"}]
        mock_client._extract_pagination_info.return_value = {"totalPages": 1, "totalElements": 2}

        result = await job_manager.get_job_transactions({"job_id": "j1", "page": 0, "size": 20})

        assert result["action"] == "get_job_transactions"
        assert result["job_id"] == "j1"
        assert len(result["data"]) == 2
        assert result["pagination"]["page"] == 0
        mock_client.get_job_transactions.assert_called_once_with("j1", page=0, size=20)

    @pytest.mark.asyncio
    async def test_get_job_transactions_missing_id_raises_error(self, job_manager):
        """Getting transactions without job_id raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await job_manager.get_job_transactions({})

        assert "job_id" in str(exc_info.value).lower()


class TestJobManagerGetJobRoi:
    """Test JobManager.get_job_roi behavior."""

    @pytest.mark.asyncio
    async def test_get_job_roi_returns_roi_data(self, job_manager, mock_client):
        """Getting ROI for a job returns ROI data."""
        mock_client.get_job_roi.return_value = {"roi": 2.5, "revenue": 1000.0}

        result = await job_manager.get_job_roi({"job_id": "j1"})

        assert result["action"] == "get_job_roi"
        assert result["job_id"] == "j1"
        assert result["data"]["roi"] == 2.5
        mock_client.get_job_roi.assert_called_once_with("j1")

    @pytest.mark.asyncio
    async def test_get_job_roi_missing_id_raises_error(self, job_manager):
        """Getting ROI without job_id raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await job_manager.get_job_roi({})

        assert "job_id" in str(exc_info.value).lower()


class TestJobManagerGetJobTypes:
    """Test JobManager.get_job_types behavior."""

    @pytest.mark.asyncio
    async def test_get_job_types_returns_types_list(self, job_manager, mock_client):
        """Getting job types returns a list of available types."""
        mock_client.get_job_types.return_value = {
            "_embedded": {"jobTypes": [{"name": "LEAD"}, {"name": "SALE"}]}
        }
        mock_client._extract_embedded_data.return_value = [{"name": "LEAD"}, {"name": "SALE"}]

        result = await job_manager.get_job_types({})

        assert result["action"] == "get_job_types"
        assert len(result["data"]) == 2
        mock_client.get_job_types.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_job_types_with_list_response(self, job_manager, mock_client):
        """get_job_types handles raw list response without embedded extraction."""
        mock_client.get_job_types.return_value = [{"name": "LEAD"}, {"name": "SALE"}]

        result = await job_manager.get_job_types({})

        assert result["action"] == "get_job_types"
        assert len(result["data"]) == 2


class TestJobManagerGetConversionFunnel:
    """Test JobManager.get_conversion_funnel behavior."""

    @pytest.mark.asyncio
    async def test_get_conversion_funnel_returns_funnel_data(self, job_manager, mock_client):
        """Getting conversion funnel returns global analytics data."""
        mock_client.get_job_conversion_funnel.return_value = {
            "stages": [{"stage": "aware", "count": 100}, {"stage": "converted", "count": 10}]
        }

        result = await job_manager.get_conversion_funnel({})

        assert result["action"] == "get_conversion_funnel"
        assert "stages" in result["data"]
        mock_client.get_job_conversion_funnel.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_get_conversion_funnel_passes_filters(self, job_manager, mock_client):
        """Filters are forwarded as keyword arguments to client."""
        mock_client.get_job_conversion_funnel.return_value = {"total": 50}

        result = await job_manager.get_conversion_funnel(
            {"filters": {"startDate": "2025-01-01", "jobType": "LEAD"}}
        )

        assert result["action"] == "get_conversion_funnel"
        mock_client.get_job_conversion_funnel.assert_called_once_with(
            startDate="2025-01-01", jobType="LEAD"
        )


class TestJobManagerGetRoiSummary:
    """Test JobManager.get_roi_summary against the published summary endpoint.

    BACK-2915: the action used to call get_job_types and then one conversion
    funnel per type, aggregating here. It now makes one request whose response
    already carries the per-type cost breakdown and the toolCostAttribution
    qualifier, so these tests mock that single call.
    """

    @pytest.mark.asyncio
    async def test_get_roi_summary_makes_one_published_call(self, job_manager, mock_client):
        """One request to the ROI summary endpoint, and no funnel fan-out."""
        mock_client.get_jobs_roi_summary.return_value = ROI_SUMMARY_RESPONSE

        result = await job_manager.get_roi_summary({})

        assert result["action"] == "get_roi_summary"
        mock_client.get_jobs_roi_summary.assert_called_once_with()
        mock_client.get_job_types.assert_not_called()
        mock_client.get_job_conversion_funnel.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_roi_summary_returns_the_server_rows(self, job_manager, mock_client):
        """Rows and summary come back as the endpoint reported them."""
        mock_client.get_jobs_roi_summary.return_value = ROI_SUMMARY_RESPONSE

        result = await job_manager.get_roi_summary({})

        assert [row["jobType"] for row in result["by_job_type"]] == [
            "LEAD_QUALIFICATION",
            "SUPPORT_DEFLECTION",
        ]
        first = result["by_job_type"][0]
        assert first["tokenCost"] == 2.0
        assert first["externalToolCost"] == 1.0
        assert first["humanCost"] == 0.5
        assert first["roi"] == 27.57
        assert result["summary"]["totalJobs"] == 3
        assert result["summary"]["overallROI"] == 29.0
        assert result["period"]["start"] == "2026-08-05T00:00:00.000Z"

    @pytest.mark.asyncio
    async def test_get_roi_summary_surfaces_tool_cost_attribution(self, job_manager, mock_client):
        """Each row keeps its qualifier, and its meaning is stated once."""
        mock_client.get_jobs_roi_summary.return_value = ROI_SUMMARY_RESPONSE

        result = await job_manager.get_roi_summary({})

        assert all(
            row["toolCostAttribution"] == "ALLOCATED_BY_AGENT"
            for row in result["by_job_type"]
        )
        assert result["cost_attribution"]["field"] == "toolCostAttribution"
        notes = " ".join(result["cost_attribution"]["notes"])
        assert "ALLOCATED_BY_AGENT" in notes
        assert "apportioned" in notes
        assert "not measured per job type directly" in notes

    @pytest.mark.asyncio
    async def test_get_roi_summary_names_an_unrecognised_attribution(
        self, job_manager, mock_client
    ):
        """An enum value the client does not know is named, not dropped."""
        response = json.loads(json.dumps(ROI_SUMMARY_RESPONSE))
        response["byJobType"][0]["toolCostAttribution"] = "MEASURED_PER_JOB_TYPE"
        mock_client.get_jobs_roi_summary.return_value = response

        result = await job_manager.get_roi_summary({})

        notes = " ".join(result["cost_attribution"]["notes"])
        assert "MEASURED_PER_JOB_TYPE" in notes

    @pytest.mark.asyncio
    async def test_get_roi_summary_forwards_declared_filters(self, job_manager, mock_client):
        """startDate/endDate reach the endpoint, and are reported as applied."""
        mock_client.get_jobs_roi_summary.return_value = ROI_SUMMARY_RESPONSE

        result = await job_manager.get_roi_summary(
            {"filters": {"startDate": "2025-01-01", "endDate": "2025-12-31"}}
        )

        mock_client.get_jobs_roi_summary.assert_called_once_with(
            startDate="2025-01-01", endDate="2025-12-31"
        )
        assert result["filters_applied"] == {
            "startDate": "2025-01-01",
            "endDate": "2025-12-31",
        }
        assert "filters_not_applied" not in result

    @pytest.mark.asyncio
    async def test_get_roi_summary_accepts_snake_case_filters(self, job_manager, mock_client):
        """The caller-facing surface still takes the snake_case spellings."""
        mock_client.get_jobs_roi_summary.return_value = ROI_SUMMARY_RESPONSE

        await job_manager.get_roi_summary(
            {"filters": {"start_date": "2025-01-01", "end_date": "2025-12-31"}}
        )

        mock_client.get_jobs_roi_summary.assert_called_once_with(
            startDate="2025-01-01", endDate="2025-12-31"
        )

    @pytest.mark.asyncio
    async def test_get_roi_summary_reports_a_filter_it_cannot_apply(
        self, job_manager, mock_client
    ):
        """environment is accepted, held back, and reported as not applied.

        The published operation does not declare it, so forwarding it would
        return a tenant-wide answer that reads as environment-scoped.
        """
        mock_client.get_jobs_roi_summary.return_value = ROI_SUMMARY_RESPONSE

        result = await job_manager.get_roi_summary(
            {"filters": {"startDate": "2025-01-01", "environment": "production"}}
        )

        mock_client.get_jobs_roi_summary.assert_called_once_with(startDate="2025-01-01")
        assert result["filters_not_applied"]["parameters"] == ["environment"]
        assert "does not declare" in result["filters_not_applied"]["reason"]

    @pytest.mark.asyncio
    async def test_get_roi_summary_rejects_an_unknown_filter(self, job_manager, mock_client):
        """The allow-list is unchanged: jobType is still not accepted here."""
        mock_client.get_jobs_roi_summary.return_value = ROI_SUMMARY_RESPONSE

        with pytest.raises(ToolError):
            await job_manager.get_roi_summary({"filters": {"jobType": "LEAD"}})

        mock_client.get_jobs_roi_summary.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_roi_summary_absent_fields_are_unavailable(self, job_manager, mock_client):
        """A field the endpoint omits reads as unavailable, never as 0."""
        response = json.loads(json.dumps(ROI_SUMMARY_RESPONSE))
        del response["byJobType"][0]["externalToolCost"]
        response["byJobType"][0]["humanCost"] = None
        del response["byJobType"][0]["toolCostAttribution"]
        del response["summary"]["overallROI"]
        mock_client.get_jobs_roi_summary.return_value = response

        result = await job_manager.get_roi_summary({})

        row = result["by_job_type"][0]
        assert row["externalToolCost"] == "unavailable"
        assert row["humanCost"] == "unavailable"
        assert row["toolCostAttribution"] == "unavailable"
        assert result["summary"]["overallROI"] == "unavailable"
        # One note, for the one row that still reports a qualifier: none is
        # invented for the row whose qualifier is missing.
        notes = result["cost_attribution"]["notes"]
        assert len(notes) == 1
        assert "ALLOCATED_BY_AGENT" in notes[0]

    @pytest.mark.asyncio
    async def test_get_roi_summary_empty_window_is_an_empty_report(
        self, job_manager, mock_client
    ):
        """A window with no jobs is the envelope with no rows, and renders as one."""
        mock_client.get_jobs_roi_summary.return_value = {
            "id": "jobs-roi-summary",
            "resourceType": "JobTypeRoiSummary",
            "label": "Job type ROI summary",
            "period": {"start": "2026-09-03T00:00:00.000Z", "end": "2026-09-04T00:00:00.000Z"},
            "byJobType": [],
            "summary": {
                "totalJobTypes": 0,
                "totalJobs": 0,
                "totalCost": 0,
                "totalValue": 0,
                "overallROI": 0,
            },
        }

        result = await job_manager.get_roi_summary({})

        assert result["by_job_type"] == []
        assert result["summary"]["totalJobs"] == 0
        assert result["cost_attribution"]["notes"] == []

    @pytest.mark.parametrize(
        "response,expected_in_message",
        [
            pytest.param("<html>gateway timeout</html>", "is a str", id="string_body"),
            pytest.param([{"jobType": "LEAD"}], "is a list", id="list_body"),
            pytest.param({}, "top-level keys observed: []", id="empty_object"),
            pytest.param(
                {"summary": {"totalJobs": 3}, "period": {}},
                "byJobType (array)",
                id="missing_byJobType",
            ),
            pytest.param(
                {"byJobType": [], "period": {}},
                "summary (object)",
                id="missing_summary",
            ),
            pytest.param(
                {"byJobType": {}, "summary": []},
                "byJobType (array), summary (object)",
                id="wrongly_typed_members",
            ),
        ],
    )
    @pytest.mark.asyncio
    async def test_get_roi_summary_refuses_an_unpublished_envelope(
        self, job_manager, mock_client, response, expected_in_message
    ):
        """A body that is not the published envelope is an error, not no data.

        Rendering it would produce an empty by_job_type and unavailable totals
        -- indistinguishable from a quiet tenant, which is the one reading a
        schema failure must never get.
        """
        mock_client.get_jobs_roi_summary.return_value = response

        with pytest.raises(ToolError) as exc_info:
            await job_manager.get_roi_summary({})

        message = str(exc_info.value)
        assert "published envelope" in message
        assert expected_in_message in message

    @pytest.mark.asyncio
    async def test_get_roi_summary_error_names_the_observed_keys(
        self, job_manager, mock_client
    ):
        """The refusal names what did arrive, so it can be diagnosed once."""
        mock_client.get_jobs_roi_summary.return_value = {
            "error": "upstream unavailable",
            "status": 503,
        }

        with pytest.raises(ToolError) as exc_info:
            await job_manager.get_roi_summary({})

        assert "top-level keys observed: ['error', 'status']" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_roi_summary_upstream_failure_raises_structured_error(
        self, job_manager, mock_client
    ):
        """An upstream failure is a structured error, not an empty summary."""
        mock_client.get_jobs_roi_summary.side_effect = ReveniumAPIError(
            "Forbidden", status_code=403
        )

        with pytest.raises(ToolError) as exc_info:
            await job_manager.get_roi_summary({})

        message = str(exc_info.value)
        assert "status=403" in message
        assert "no summary was returned" in message.lower()


class TestJobManagerReportOutcome:
    """Test JobManager.report_outcome behavior including 409 conflict path."""

    @pytest.mark.asyncio
    async def test_report_outcome_success(self, job_manager, mock_client):
        """Reporting outcome succeeds and returns result."""
        mock_client.report_job_outcome.return_value = {"status": "reported", "id": "o1"}
        outcome_data = {"outcome": "CONVERTED", "revenue": 99.99}

        result = await job_manager.report_outcome({"job_id": "j1", "outcome_data": outcome_data})

        assert result["action"] == "report_outcome"
        assert result["job_id"] == "j1"
        assert result["data"]["status"] == "reported"
        mock_client.report_job_outcome.assert_called_once_with("j1", outcome_data)

    @pytest.mark.asyncio
    async def test_report_outcome_409_conflict_returns_message(self, job_manager, mock_client):
        """409 Conflict from API returns a conflict message instead of re-raising."""
        error_409 = ReveniumAPIError("Conflict", status_code=409)
        mock_client.report_job_outcome.side_effect = error_409

        result = await job_manager.report_outcome(
            {"job_id": "j1", "outcome_data": {"outcome": "CONVERTED"}}
        )

        assert result["action"] == "report_outcome"
        assert result["job_id"] == "j1"
        assert result["status"] == "conflict"
        assert "duplicate" in result["message"].lower() or "already reported" in result["message"].lower()
        assert "j1" in result["message"]

    @pytest.mark.asyncio
    async def test_report_outcome_non_409_error_reraises(self, job_manager, mock_client):
        """Non-409 API errors are re-raised, not swallowed."""
        error_500 = ReveniumAPIError("Server Error", status_code=500)
        mock_client.report_job_outcome.side_effect = error_500

        with pytest.raises(ReveniumAPIError) as exc_info:
            await job_manager.report_outcome(
                {"job_id": "j1", "outcome_data": {"outcome": "CONVERTED"}}
            )

        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_report_outcome_missing_id_raises_error(self, job_manager):
        """Reporting outcome without job_id raises ToolError."""
        with pytest.raises(ToolError) as exc_info:
            await job_manager.report_outcome({})

        assert "job_id" in str(exc_info.value).lower()


class TestReportOutcomeReason:
    """outcomeReason has to survive the tool boundary and be discoverable.

    The field only reaches the API if the caller sends it, and callers only send
    what the tool documents — so both the passthrough and the agent-facing text
    are asserted here.
    """

    @pytest.mark.asyncio
    async def test_outcome_reason_forwarded_verbatim(self, job_manager, mock_client):
        """outcome_data reaches the client unchanged, outcomeReason included."""
        mock_client.report_job_outcome.return_value = {"id": "o1"}
        outcome_data = {
            "executionStatus": "FAILED",
            "outcomeType": "UNSUCCESSFUL",
            "outcomeReason": "Upstream agent timed out after 300s",
        }

        await job_manager.report_outcome({"job_id": "j1", "outcome_data": outcome_data})

        sent = mock_client.report_job_outcome.call_args[0][1]
        assert sent == outcome_data
        assert sent["outcomeReason"] == "Upstream agent timed out after 300s"

    @pytest.mark.asyncio
    async def test_unrecognised_keys_are_not_filtered(self, job_manager, mock_client):
        """No allowlist sits between the tool and the client, so fields the API
        gains later work without a release here."""
        mock_client.report_job_outcome.return_value = {"id": "o1"}
        outcome_data = {"executionStatus": "SUCCESS", "someFutureField": "keep me"}

        await job_manager.report_outcome({"job_id": "j1", "outcome_data": outcome_data})

        assert mock_client.report_job_outcome.call_args[0][1] == outcome_data

    @pytest.mark.asyncio
    async def test_missing_outcome_data_error_documents_outcome_reason(self, job_manager):
        """The pre-flight error teaches outcomeReason in both examples and suggestions."""
        with pytest.raises(ToolError) as exc_info:
            await job_manager.report_outcome({"job_id": "j1"})

        err = exc_info.value
        assert err.field == "outcome_data"
        assert "outcomeReason" in json.dumps(err.examples)
        assert any("outcomeReason" in suggestion for suggestion in err.suggestions)
        # camelCase only — a snake_case alias would be dropped upstream silently
        assert "outcome_reason" not in json.dumps(err.examples)

    @pytest.mark.asyncio
    async def test_capabilities_document_outcome_reason(self, job_mgmt, mock_mgmt_client):
        """get_capabilities names outcomeReason on the write action and on the reads."""
        result = await job_mgmt.handle_action("get_capabilities", {})
        parameters = json.loads(result[0].text)["parameters"]

        assert "outcomeReason" in json.dumps(parameters["report_outcome"])
        assert "outcomeReason" in json.dumps(parameters["list_jobs"])
        assert "outcomeReason" in json.dumps(parameters["get_job"])

    @pytest.mark.asyncio
    async def test_capabilities_scope_outcome_reason_to_outcome_data(
        self, job_mgmt, mock_mgmt_client
    ):
        """report_outcome reads only job_id and outcome_data from the call, so the
        schema must not advertise outcomeReason as a sibling of them — a value put
        there would be dropped without an error."""
        result = await job_mgmt.handle_action("get_capabilities", {})
        report_outcome = json.loads(result[0].text)["parameters"]["report_outcome"]

        assert set(report_outcome) == {"job_id", "outcome_data"}
        assert "outcomeReason" in report_outcome["outcome_data"]

    @pytest.mark.asyncio
    async def test_examples_use_api_field_names(self, job_mgmt, mock_mgmt_client):
        """The templates agents copy carry the request-body spelling of every key."""
        result = await job_mgmt.handle_action("get_examples", {})
        parsed = json.loads(result[0].text)
        report = parsed["report_outcome"]

        assert report["example_converted"]["outcome_data"]["executionStatus"] == "SUCCESS"
        assert report["example_converted"]["outcome_data"]["outcomeType"] == "CONVERTED"
        assert "outcomeReason" in report["example_failed"]["outcome_data"]
        assert "outcomeReason" in parsed["list_jobs"]["description"]
        assert "outcomeReason" in parsed["get_job"]["description"]


# ===========================================================================
# JobManagement handle_action routing tests (meta-actions)
# ===========================================================================


class TestJobManagementMetaActions:
    """Test JobManagement.handle_action meta-action routing."""

    @pytest.mark.asyncio
    async def test_get_capabilities_returns_capability_data(self, job_mgmt, mock_mgmt_client):
        """get_capabilities action returns capability data without error."""
        result = await job_mgmt.handle_action("get_capabilities", {})

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
        parsed = json.loads(result[0].text)
        assert "actions" in parsed
        assert "business_actions" in parsed
        assert "list_jobs" in parsed["business_actions"]
        assert "get_roi_summary" in parsed["business_actions"]
        assert "report_outcome" in parsed["business_actions"]

    @pytest.mark.asyncio
    async def test_get_examples_returns_example_content(self, job_mgmt, mock_mgmt_client):
        """get_examples action returns example content for all 7 actions."""
        result = await job_mgmt.handle_action("get_examples", {})

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
        parsed = json.loads(result[0].text)
        assert "list_jobs" in parsed
        assert "get_job" in parsed
        assert "get_job_transactions" in parsed
        assert "get_job_roi" in parsed
        assert "get_job_types" in parsed
        assert "get_conversion_funnel" in parsed
        assert "get_roi_summary" in parsed
        assert "report_outcome" in parsed

    @pytest.mark.asyncio
    async def test_get_tool_metadata_returns_metadata(self, job_mgmt, mock_mgmt_client):
        """get_tool_metadata action returns serialized tool metadata."""
        result = await job_mgmt.handle_action("get_tool_metadata", {})

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
        parsed = json.loads(result[0].text)
        assert isinstance(parsed, dict)

    @pytest.mark.asyncio
    async def test_get_agent_summary_returns_summary(self, job_mgmt, mock_mgmt_client):
        """get_agent_summary action returns agent-friendly summary text."""
        result = await job_mgmt.handle_action("get_agent_summary", {})

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
        assert "manage_jobs" in result[0].text.lower() or "job" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error_message(self, job_mgmt, mock_mgmt_client):
        """BACK-2937: an unknown action raises so the envelope carries isError."""
        with pytest.raises(ToolError) as exc_info:
            await job_mgmt.handle_action("nonexistent_action", {})

        assert "unknown action" in exc_info.value.message.lower()
        assert exc_info.value.field == "action"


# ===========================================================================
# JobManagement handle_action routing tests (business actions)
# ===========================================================================


class TestJobManagementBusinessActions:
    """Test JobManagement.handle_action routing for business actions."""

    @pytest.mark.asyncio
    async def test_list_jobs_action_returns_formatted_response(self, job_mgmt, mock_mgmt_client):
        """list_jobs action returns formatted job list."""
        mock_mgmt_client.get_jobs = AsyncMock(return_value={})
        mock_mgmt_client._extract_embedded_data.return_value = [{"id": "j1", "name": "Job A"}]
        mock_mgmt_client._extract_pagination_info.return_value = {
            "totalPages": 1,
            "totalElements": 1,
        }

        result = await job_mgmt.handle_action("list_jobs", {"page": 0, "size": 10})

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
        assert "Jobs (page 1)" in result[0].text

    @pytest.mark.asyncio
    async def test_get_job_action_returns_job_details(self, job_mgmt, mock_mgmt_client):
        """get_job action returns job details for valid ID."""
        mock_mgmt_client.get_job_by_id = AsyncMock(
            return_value={"id": "j1", "name": "Job A"}
        )

        result = await job_mgmt.handle_action("get_job", {"job_id": "j1"})

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
        assert "j1" in result[0].text

    @pytest.mark.asyncio
    async def test_get_job_transactions_action_returns_transactions(self, job_mgmt, mock_mgmt_client):
        """get_job_transactions action returns transaction data."""
        mock_mgmt_client.get_job_transactions = AsyncMock(return_value={})
        mock_mgmt_client._extract_embedded_data.return_value = [{"txn_id": "t1"}]
        mock_mgmt_client._extract_pagination_info.return_value = {"totalPages": 1, "totalElements": 1}

        result = await job_mgmt.handle_action(
            "get_job_transactions", {"job_id": "j1", "page": 0, "size": 20}
        )

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
        assert "j1" in result[0].text

    @pytest.mark.asyncio
    async def test_get_job_roi_action_returns_roi_data(self, job_mgmt, mock_mgmt_client):
        """get_job_roi action returns ROI metrics."""
        mock_mgmt_client.get_job_roi = AsyncMock(return_value={"roi": 3.5})

        result = await job_mgmt.handle_action("get_job_roi", {"job_id": "j1"})

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
        assert "j1" in result[0].text

    @pytest.mark.asyncio
    async def test_get_job_types_action_returns_types(self, job_mgmt, mock_mgmt_client):
        """get_job_types action returns available job types."""
        mock_mgmt_client.get_job_types = AsyncMock(return_value=[{"name": "LEAD"}])

        result = await job_mgmt.handle_action("get_job_types", {})

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
        assert "job types" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_get_conversion_funnel_action_returns_funnel_data(self, job_mgmt, mock_mgmt_client):
        """get_conversion_funnel action returns global funnel analytics."""
        mock_mgmt_client.get_job_conversion_funnel = AsyncMock(
            return_value={"stages": [{"stage": "aware", "count": 100}]}
        )

        result = await job_mgmt.handle_action("get_conversion_funnel", {})

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
        assert "conversion funnel" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_get_roi_summary_action_returns_summary(self, job_mgmt, mock_mgmt_client):
        """get_roi_summary action renders the published summary."""
        mock_mgmt_client.get_jobs_roi_summary = AsyncMock(return_value=ROI_SUMMARY_RESPONSE)

        result = await job_mgmt.handle_action("get_roi_summary", {})

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
        assert "roi summary" in result[0].text.lower()
        assert "LEAD_QUALIFICATION" in result[0].text

    @pytest.mark.asyncio
    async def test_get_roi_summary_renders_the_attribution_qualifier(
        self, job_mgmt, mock_mgmt_client
    ):
        """The rendered text says what ALLOCATED_BY_AGENT means.

        Without it the cost split reads as measured per job type, which it is
        not -- external tool cost is apportioned via the agent that spent it.
        """
        mock_mgmt_client.get_jobs_roi_summary = AsyncMock(return_value=ROI_SUMMARY_RESPONSE)

        result = await job_mgmt.handle_action("get_roi_summary", {})

        text = result[0].text
        assert "toolCostAttribution" in text
        assert "ALLOCATED_BY_AGENT" in text
        assert "apportioned to job types via the agent that incurred it" in text
        assert "not measured per job type directly" in text

    @pytest.mark.asyncio
    async def test_get_roi_summary_renders_unavailable_fields_as_missing(
        self, job_mgmt, mock_mgmt_client
    ):
        """An omitted field renders as unavailable, and is called out as missing."""
        response = json.loads(json.dumps(ROI_SUMMARY_RESPONSE))
        del response["byJobType"][0]["externalToolCost"]
        mock_mgmt_client.get_jobs_roi_summary = AsyncMock(return_value=response)

        result = await job_mgmt.handle_action("get_roi_summary", {})

        text = result[0].text
        assert '"externalToolCost": "unavailable"' in text
        assert "missing values, not zeros" in text

    @pytest.mark.asyncio
    async def test_get_roi_summary_renders_the_unapplied_filter(
        self, job_mgmt, mock_mgmt_client
    ):
        """A filter the endpoint cannot apply is visible in the rendered text."""
        mock_mgmt_client.get_jobs_roi_summary = AsyncMock(return_value=ROI_SUMMARY_RESPONSE)

        result = await job_mgmt.handle_action(
            "get_roi_summary", {"filters": {"environment": "production"}}
        )

        assert "Filters not applied: environment" in result[0].text

    @pytest.mark.asyncio
    async def test_report_outcome_action_returns_success_response(self, job_mgmt, mock_mgmt_client):
        """report_outcome action returns success response."""
        mock_mgmt_client.report_job_outcome = AsyncMock(return_value={"status": "reported"})

        result = await job_mgmt.handle_action(
            "report_outcome",
            {"job_id": "j1", "outcome_data": {"outcome": "CONVERTED"}},
        )

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
        assert "j1" in result[0].text

    @pytest.mark.asyncio
    async def test_report_outcome_409_conflict_via_handle_action(self, job_mgmt, mock_mgmt_client):
        """handle_action report_outcome with 409 conflict returns conflict message in TextContent."""
        error_409 = ReveniumAPIError("Conflict", status_code=409)
        mock_mgmt_client.report_job_outcome = AsyncMock(side_effect=error_409)

        result = await job_mgmt.handle_action(
            "report_outcome",
            {"job_id": "j1", "outcome_data": {"outcome": "CONVERTED"}},
        )

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
        text_lower = result[0].text.lower()
        assert "conflict" in text_lower or "duplicate" in text_lower or "already reported" in text_lower


# ===========================================================================
# BACK-1140 — page boundary translates into a structured 400, not HTTP 500
# ===========================================================================


class TestJobManagerPaginationBoundary:
    """Regression for BACK-1140 — list_jobs with page=2147483647 (32-bit
    MAX_INT) used to forward the value to the backend, which returned a
    generic HTTP 500 ('An unexpected error occurred'). Client-determinable
    boundary inputs now raise a structured ToolError naming the field and
    the bound, so callers can fix the input without inspecting a server
    traceback."""

    @pytest.mark.asyncio
    async def test_list_jobs_max_int_page_raises_structured_400(
        self, job_manager, mock_client
    ):
        """page=2^31-1 is rejected before the request ever reaches the API."""
        with pytest.raises(ToolError) as exc_info:
            await job_manager.list_jobs({"page": 2_147_483_647, "size": 10})
        err = exc_info.value
        assert getattr(err, "field", None) == "page"
        assert "page" in err.message.lower()
        assert "exceeds maximum" in err.message
        mock_client.get_jobs.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_jobs_negative_page_raises(self, job_manager, mock_client):
        with pytest.raises(ToolError) as exc_info:
            await job_manager.list_jobs({"page": -1, "size": 10})
        assert getattr(exc_info.value, "field", None) == "page"
        mock_client.get_jobs.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_jobs_non_integer_page_raises(self, job_manager, mock_client):
        with pytest.raises(ToolError) as exc_info:
            await job_manager.list_jobs({"page": "1", "size": 10})
        assert getattr(exc_info.value, "field", None) == "page"
        mock_client.get_jobs.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_jobs_zero_size_raises(self, job_manager, mock_client):
        with pytest.raises(ToolError) as exc_info:
            await job_manager.list_jobs({"page": 0, "size": 0})
        assert getattr(exc_info.value, "field", None) == "size"
        mock_client.get_jobs.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_jobs_max_int_size_raises_structured_400(
        self, job_manager, mock_client
    ):
        """size=2^31-1 is rejected before the request ever reaches the API."""
        with pytest.raises(ToolError) as exc_info:
            await job_manager.list_jobs({"page": 0, "size": 2_147_483_647})
        err = exc_info.value
        assert getattr(err, "field", None) == "size"
        assert "exceeds maximum" in err.message
        mock_client.get_jobs.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_jobs_within_bounds_still_works(
        self, job_manager, mock_client
    ):
        """The fix does not regress legitimate pagination."""
        mock_client._extract_embedded_data.return_value = []
        mock_client._extract_pagination_info.return_value = {
            "totalPages": 1,
            "totalElements": 0,
        }
        result = await job_manager.list_jobs({"page": 999_999, "size": 20})
        assert result["action"] == "list_jobs"
        assert result["pagination"]["page"] == 999_999
        assert result["pagination"]["size"] == 20
        mock_client.get_jobs.assert_called_once_with(page=999_999, size=20)

    @pytest.mark.asyncio
    async def test_get_job_transactions_max_int_page_raises_structured_400(
        self, job_manager, mock_client
    ):
        """The same guard applies to get_job_transactions, the other paginated
        action on this tool."""
        with pytest.raises(ToolError) as exc_info:
            await job_manager.get_job_transactions(
                {"job_id": "j1", "page": 2_147_483_647, "size": 10}
            )
        assert getattr(exc_info.value, "field", None) == "page"
        mock_client.get_job_transactions.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_job_transactions_max_int_size_raises_structured_400(
        self, job_manager, mock_client
    ):
        """The size upper-bound guard also applies to get_job_transactions."""
        with pytest.raises(ToolError) as exc_info:
            await job_manager.get_job_transactions(
                {"job_id": "j1", "page": 0, "size": 2_147_483_647}
            )
        err = exc_info.value
        assert getattr(err, "field", None) == "size"
        assert "exceeds maximum" in err.message
        mock_client.get_job_transactions.assert_not_called()


# ===========================================================================
# _links sanitisation
# ===========================================================================


class TestStripLinks:
    """``_strip_links`` removes HAL ``_links`` keys from any nested shape."""

    def test_strips_top_level_links(self):
        sanitised = _strip_links(
            {
                "id": "j1",
                "_links": {"self": {"href": "http://api-lb.dev.hcapp.io/jobs/j1"}},
            }
        )
        assert "_links" not in sanitised
        assert sanitised == {"id": "j1"}

    def test_strips_nested_links_in_list_items(self):
        items = [
            {"id": "a", "_links": {"self": {"href": "http://api-lb.dev.hcapp.io/jobs/a"}}},
            {"id": "b", "_links": {"self": {"href": "http://api-lb.dev.hcapp.io/jobs/b"}}},
        ]
        sanitised = _strip_links(items)
        assert all("_links" not in item for item in sanitised)
        assert [item["id"] for item in sanitised] == ["a", "b"]

    def test_strips_links_inside_embedded_collections(self):
        sanitised = _strip_links(
            {
                "id": "j1",
                "_links": {"collection": {"href": "http://api-lb.dev.hcapp.io/jobs"}},
                "outcomes": [
                    {"id": "o1", "_links": {"self": {"href": "http://api-lb.dev.hcapp.io/o/1"}}},
                ],
            }
        )
        assert "_links" not in sanitised
        assert "_links" not in sanitised["outcomes"][0]
        assert sanitised["outcomes"][0]["id"] == "o1"

    def test_does_not_mutate_input(self):
        original = {"id": "j1", "_links": {"self": {"href": "x"}}}
        _strip_links(original)
        assert "_links" in original

    def test_passes_through_scalars(self):
        assert _strip_links("string") == "string"
        assert _strip_links(42) == 42
        assert _strip_links(None) is None


class TestListJobsStripsLinks:
    """list_jobs must not surface HAL _links from the upstream HAL+JSON."""

    @pytest.mark.asyncio
    async def test_list_jobs_strips_internal_lb_links(self, job_manager, mock_client):
        """Each job item arrives from the API with _links pointing at api-lb.* — strip them."""
        mock_client.get_jobs.return_value = {"_embedded": {"jobs": []}}
        mock_client._extract_embedded_data.return_value = [
            {
                "id": "j1",
                "name": "Job A",
                "_links": {
                    "self": {"href": "http://api-lb.dev.hcapp.io/profitstream/v2/api/jobs/j1"},
                    "collection": {"href": "http://api-lb.dev.hcapp.io/profitstream/v2/api/jobs"},
                },
            }
        ]
        mock_client._extract_pagination_info.return_value = {"totalPages": 1, "totalElements": 1}

        result = await job_manager.list_jobs({"page": 0, "size": 10})

        for job in result["data"]:
            assert "_links" not in job, "manage_jobs list response must not expose HAL _links"
        # serialised payload must not mention the internal LB hostname
        assert "api-lb.dev.hcapp.io" not in json.dumps(result)


class TestGetJobStripsLinks:
    """get_job must also strip _links from the single-resource response."""

    @pytest.mark.asyncio
    async def test_get_job_strips_links(self, job_manager, mock_client):
        mock_client.get_job_by_id.return_value = {
            "id": "j1",
            "name": "Job A",
            "_links": {"self": {"href": "http://api-lb.dev.hcapp.io/jobs/j1"}},
        }

        result = await job_manager.get_job({"job_id": "j1"})

        assert "_links" not in result["data"]
        assert "api-lb.dev.hcapp.io" not in json.dumps(result)


class TestGetJobTransactionsStripsLinks:
    """get_job_transactions must strip _links from each transaction item."""

    @pytest.mark.asyncio
    async def test_get_job_transactions_strips_links(self, job_manager, mock_client):
        mock_client.get_job_transactions.return_value = {"_embedded": {"transactions": []}}
        mock_client._extract_embedded_data.return_value = [
            {
                "id": "t1",
                "_links": {"self": {"href": "https://api-lb.dev.hcapp.io/profitstream/v2/api/transactions/t1"}},
            }
        ]
        mock_client._extract_pagination_info.return_value = {"totalPages": 1, "totalElements": 1}

        result = await job_manager.get_job_transactions({"job_id": "j1", "page": 0, "size": 10})

        for tx in result["data"]:
            assert "_links" not in tx
        assert "api-lb.dev.hcapp.io" not in json.dumps(result)


class TestGetJobRoiStripsLinks:
    """get_job_roi must strip _links from the ROI payload."""

    @pytest.mark.asyncio
    async def test_get_job_roi_strips_links(self, job_manager, mock_client):
        mock_client.get_job_roi.return_value = {
            "jobId": "j1",
            "roi": 1.42,
            "_links": {"self": {"href": "https://api-lb.dev.hcapp.io/profitstream/v2/api/jobs/j1/roi"}},
        }

        result = await job_manager.get_job_roi({"job_id": "j1"})

        assert "_links" not in result["data"]
        assert "api-lb.dev.hcapp.io" not in json.dumps(result)


class TestGetJobTypesStripsLinks:
    """get_job_types must strip _links from the types payload."""

    @pytest.mark.asyncio
    async def test_get_job_types_strips_links(self, job_manager, mock_client):
        mock_client.get_job_types.return_value = {"_embedded": {"jobTypes": []}}
        mock_client._extract_embedded_data.return_value = [
            {
                "name": "TYPE_A",
                "_links": {"self": {"href": "https://api-lb.dev.hcapp.io/profitstream/v2/api/jobs/types/TYPE_A"}},
            }
        ]

        result = await job_manager.get_job_types({})

        for item in result["data"]:
            assert "_links" not in item
        assert "api-lb.dev.hcapp.io" not in json.dumps(result)


class TestGetConversionFunnelStripsLinks:
    """get_conversion_funnel must strip _links from the funnel payload."""

    @pytest.mark.asyncio
    async def test_get_conversion_funnel_strips_links(self, job_manager, mock_client):
        mock_client.get_job_conversion_funnel = AsyncMock(return_value={
            "totalJobs": 10,
            "successfulJobs": 7,
            "convertedJobs": 5,
            "_links": {"self": {"href": "https://api-lb.dev.hcapp.io/profitstream/v2/api/jobs/conversion-funnel"}},
        })

        result = await job_manager.get_conversion_funnel({"filters": {}})

        assert "_links" not in result["data"]
        assert "api-lb.dev.hcapp.io" not in json.dumps(result)


class TestGetRoiSummaryStripsLinks:
    """get_roi_summary must strip _links from the published envelope."""

    @pytest.mark.asyncio
    async def test_get_roi_summary_strips_links(self, job_manager, mock_client):
        mock_client.get_jobs_roi_summary.return_value = ROI_SUMMARY_RESPONSE

        result = await job_manager.get_roi_summary({"filters": {}})

        assert "_links" not in result
        assert "api-lb.dev.hcapp.io" not in json.dumps(result)


class TestReportOutcomeStripsLinks:
    """report_outcome must strip _links from the upstream confirmation payload."""

    @pytest.mark.asyncio
    async def test_report_outcome_strips_links(self, job_manager, mock_client):
        mock_client.report_job_outcome.return_value = {
            "id": "o1",
            "outcome": "CONVERTED",
            "_links": {"self": {"href": "https://api-lb.dev.hcapp.io/profitstream/v2/api/jobs/j1/outcomes/o1"}},
        }

        result = await job_manager.report_outcome(
            {"job_id": "j1", "outcome_data": {"outcome": "CONVERTED", "revenue": 99.99}}
        )

        assert "_links" not in result["data"]
        assert "api-lb.dev.hcapp.io" not in json.dumps(result)


class TestListJobsRejectsFloatPageNoLeak:
    """BACK-1270 / item #6 — float page must reject without Pydantic URL."""

    @pytest.mark.asyncio
    async def test_float_page_returns_clean_error(self, job_manager):
        from src.revenium_mcp_server.common.error_handling import ToolError
        from tests.unit._helpers_no_framework_leak import assert_no_framework_leak
        with pytest.raises(ToolError) as exc:
            await job_manager.list_jobs({"page": 3.7, "size": 20})
        assert exc.value.field == "page"
        assert_no_framework_leak(exc.value.message)


# ===========================================================================
# BACK-2769 — coding-session attribution, read half
# ===========================================================================


SESSION_ID = "853a73bf-d9d7-4351-a548-9d6c05648c61"


def _collection(*intervals):
    """The CollectionModel envelope the platform wraps intervals in."""
    return {
        "_embedded": {"objectList": list(intervals)},
        "_links": {"self": {"href": "https://example.invalid/attribution"}},
    }


class TestListSessionAttributions:
    """JobManager.list_session_attributions behaviour."""

    @pytest.mark.asyncio
    async def test_returns_intervals_newest_first(self, job_manager, mock_client):
        """The client's ordering is preserved: element 0 is the current interval."""
        mock_client.get_session_attributions.return_value = _collection(
            {"ticketId": "BACK-2769", "effectiveFrom": "2026-09-04T10:00:00Z"},
            {"ticketId": "BACK-2768", "effectiveFrom": "2026-09-03T10:00:00Z"},
        )

        result = await job_manager.list_session_attributions({"session_id": SESSION_ID})

        mock_client.get_session_attributions.assert_awaited_once_with(SESSION_ID)
        assert result["action"] == "list_session_attributions"
        assert result["session_id"] == SESSION_ID
        assert result["count"] == 2
        assert [row["ticketId"] for row in result["data"]] == ["BACK-2769", "BACK-2768"]

    @pytest.mark.parametrize(
        "envelope",
        [
            # What dev actually returns for a session with no attributions
            # (verified live 2026-09-04), and what the client returns for an
            # empty body.
            {},
            # HAL omits _embedded when there is nothing to embed.
            {"_links": {"self": {"href": "https://example.invalid/x"}}},
            {"_links": {}, "page": {"totalElements": 0}},
            # An _embedded envelope carrying an empty list is equally empty.
            {"_embedded": {"objectList": []}},
        ],
        ids=["bare-object", "links-only", "links-and-page", "empty-objectList"],
    )
    @pytest.mark.asyncio
    async def test_empty_collection_is_an_answer_not_an_error(
        self, job_manager, mock_client, envelope
    ):
        """A session that was never attributed returns an empty, successful result."""
        mock_client.get_session_attributions.return_value = envelope

        result = await job_manager.list_session_attributions({"session_id": SESSION_ID})

        assert result["count"] == 0
        assert result["data"] == []

    @pytest.mark.asyncio
    async def test_links_are_stripped(self, job_manager, mock_client):
        """HAL _links leak the internal load balancer hostname."""
        mock_client.get_session_attributions.return_value = _collection(
            {
                "ticketId": "BACK-2769",
                "_links": {
                    "self": {
                        "href": "https://api-lb.dev.hcapp.io/profitstream/v2/api/"
                        "sessions/x/attribution"
                    }
                },
            }
        )

        result = await job_manager.list_session_attributions({"session_id": SESSION_ID})

        assert "api-lb.dev.hcapp.io" not in json.dumps(result)

    @pytest.mark.asyncio
    async def test_missing_session_id_raises_structured_error(self, job_manager, mock_client):
        """No session_id means no request is attempted at all."""
        with pytest.raises(ToolError) as exc_info:
            await job_manager.list_session_attributions({})

        assert exc_info.value.field == "session_id"
        assert "session_id" in exc_info.value.message
        mock_client.get_session_attributions.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_upstream_403_propagates(self, job_manager, mock_client):
        """A team the caller cannot read must surface as the upstream 403."""
        mock_client.get_session_attributions.side_effect = ReveniumAPIError(
            "Forbidden", status_code=403
        )

        with pytest.raises(ReveniumAPIError) as exc_info:
            await job_manager.list_session_attributions({"session_id": SESSION_ID})

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_upstream_404_propagates(self, job_manager, mock_client):
        """404 is team-not-found upstream, not an empty attribution list."""
        mock_client.get_session_attributions.side_effect = ReveniumAPIError(
            "Not Found", status_code=404
        )

        with pytest.raises(ReveniumAPIError) as exc_info:
            await job_manager.list_session_attributions({"session_id": SESSION_ID})

        assert exc_info.value.status_code == 404


class TestSessionAttributionEnvelopeShape:
    """An envelope this code does not recognise must not read as "no attributions"."""

    @pytest.mark.parametrize(
        "response",
        [
            "not an object at all",
            ["a", "list"],
            42,
            None,
            {"error": "boom", "status": 500},
            {"_embedded": "not an object"},
            {"_embedded": {}},
            {"_embedded": {"objectList": {"not": "a list"}}},
            {"_embedded": {"attributions": [], "somethingElse": []}},
            # Two lists are refused even when one of them is the expected
            # member: picking objectList would silently drop the other.
            {"_embedded": {"objectList": [{"ticketId": "A-1"}], "somethingElse": [{"x": 1}]}},
            # A non-object element must never reach the renderer, where it
            # would be printed verbatim and bypass the field allowlist.
            {"_embedded": {"objectList": ["a string, not an interval"]}},
            {"_embedded": {"objectList": [{"ticketId": "A-1"}, None]}},
        ],
        ids=[
            "string-body",
            "list-body",
            "int-body",
            "none-body",
            "unexpected-keys",
            "embedded-not-an-object",
            "embedded-with-no-list",
            "objectList-not-a-list",
            "two-list-members",
            "objectList-plus-another-list",
            "string-item-in-the-collection",
            "null-item-in-the-collection",
        ],
    )
    def test_unrecognised_shapes_are_refused(self, response):
        with pytest.raises(ToolError) as exc_info:
            _session_attribution_intervals(SESSION_ID, response)

        assert exc_info.value.error_code == ErrorCodes.API_ERROR
        assert "Unexpected response shape" in exc_info.value.message
        assert SESSION_ID in exc_info.value.message

    def test_the_error_names_what_came_back(self):
        with pytest.raises(ToolError) as exc_info:
            _session_attribution_intervals(SESSION_ID, {"error": "boom", "status": 500})

        assert "error" in exc_info.value.message and "status" in exc_info.value.message
        assert exc_info.value.context["observed"] == ["error", "status"]

    def test_two_lists_are_refused_by_name_even_with_objectList_present(self):
        with pytest.raises(ToolError) as exc_info:
            _session_attribution_intervals(
                SESSION_ID,
                {"_embedded": {"objectList": [{"ticketId": "A-1"}], "extra": [{"x": 1}]}},
            )

        message = exc_info.value.message
        assert "more than one list member" in message
        assert "objectList" in message and "extra" in message

    def test_a_non_object_element_is_refused_naming_its_index_and_type(self):
        with pytest.raises(ToolError) as exc_info:
            _session_attribution_intervals(
                SESSION_ID,
                {"_embedded": {"objectList": [{"ticketId": "A-1"}, "not an interval"]}},
            )

        message = exc_info.value.message
        assert "element 1" in message
        assert "str" in message
        assert exc_info.value.context["observed"] == {
            "member": "objectList",
            "index": 1,
            "type": "str",
        }

    def test_snapshot_member_name_is_read(self):
        intervals = _session_attribution_intervals(
            SESSION_ID, {"_embedded": {"objectList": [{"ticketId": "BACK-2769"}]}}
        )

        assert intervals == [{"ticketId": "BACK-2769"}]

    def test_a_single_differently_named_list_is_accepted(self):
        """A resource-named list must not turn a working read into a failure."""
        intervals = _session_attribution_intervals(
            SESSION_ID,
            {"_embedded": {"sessionAttributionIntervalResourceList": [{"ticketId": "A-1"}]}},
        )

        assert intervals == [{"ticketId": "A-1"}]

    @pytest.mark.asyncio
    async def test_malformed_envelope_reaches_the_caller_as_an_error(
        self, job_manager, mock_client
    ):
        """The action must not answer "no attributions recorded" for a bad shape."""
        mock_client.get_session_attributions.return_value = {"unexpected": "payload"}

        with pytest.raises(ToolError) as exc_info:
            await job_manager.list_session_attributions({"session_id": SESSION_ID})

        assert exc_info.value.error_code == ErrorCodes.API_ERROR
        assert "No attributions recorded" not in exc_info.value.message


class TestRenderSessionAttributions:
    """The rendering must not invent values it was not given."""

    def test_absent_fields_render_as_unavailable_never_zero(self):
        rendered = _render_session_attributions(SESSION_ID, [{"ticketId": "BACK-2769"}])

        assert "Ticket: BACK-2769" in rendered
        assert "Ticket title: unavailable" in rendered
        assert "Effective from: unavailable" in rendered
        assert ": 0" not in rendered

    def test_every_declared_field_gets_a_row(self):
        rendered = _render_session_attributions(SESSION_ID, [{"ticketId": "BACK-2769"}])

        for _, label in _SESSION_ATTRIBUTION_FIELDS:
            assert f"{label}:" in rendered

    def test_unknown_field_names_are_reported_but_their_values_are_not(self):
        rendered = _render_session_attributions(
            SESSION_ID,
            [{"ticketId": "BACK-2769", "brandNewField": "surprise", "another": "secret"}],
        )

        assert "2 additional fields not shown: another, brandNewField" in rendered
        assert "surprise" not in rendered
        assert "secret" not in rendered

    def test_a_single_unknown_field_reads_in_the_singular(self):
        rendered = _render_session_attributions(
            SESSION_ID, [{"ticketId": "BACK-2769", "brandNewField": "surprise"}]
        )

        assert "1 additional field not shown: brandNewField" in rendered

    def test_no_extras_line_when_every_field_is_known(self):
        rendered = _render_session_attributions(
            SESSION_ID, [{name: "x" for name, _ in _SESSION_ATTRIBUTION_FIELDS}]
        )

        assert "additional field" not in rendered

    def test_empty_collection_says_so_in_words(self):
        rendered = _render_session_attributions(SESSION_ID, [])

        assert "No attributions recorded for this session." in rendered
        assert SESSION_ID in rendered

    def test_footer_states_splits_are_not_exposed(self):
        for intervals in ([], [{"ticketId": "BACK-2769"}]):
            rendered = _render_session_attributions(SESSION_ID, intervals)
            assert "does not expose splits" in rendered
            assert "declares no splits field" in rendered

    def test_interval_count_is_reported(self):
        one = _render_session_attributions(SESSION_ID, [{"ticketId": "A-1"}])
        two = _render_session_attributions(
            SESSION_ID, [{"ticketId": "A-1"}, {"ticketId": "A-2"}]
        )

        assert "(1 interval, current first)" in one
        assert "(2 intervals, current first)" in two


class TestSessionAttributionAction:
    """JobManagement.handle_action routing and documented surfaces."""

    @pytest.mark.asyncio
    async def test_action_renders_the_collection(self, job_mgmt, mock_mgmt_client):
        mock_mgmt_client.get_session_attributions = AsyncMock(
            return_value=_collection(
                {"ticketId": "BACK-2769", "ticketTitle": "Session attribution read"}
            )
        )

        result = await job_mgmt.handle_action(
            "list_session_attributions", {"session_id": SESSION_ID}
        )

        assert isinstance(result[0], TextContent)
        assert SESSION_ID in result[0].text
        assert "BACK-2769" in result[0].text
        assert "does not expose splits" in result[0].text

    @pytest.mark.asyncio
    async def test_action_renders_empty_collection(self, job_mgmt, mock_mgmt_client):
        mock_mgmt_client.get_session_attributions = AsyncMock(return_value={})

        result = await job_mgmt.handle_action(
            "list_session_attributions", {"session_id": SESSION_ID}
        )

        assert "No attributions recorded for this session." in result[0].text

    @pytest.mark.asyncio
    async def test_action_without_session_id_raises(self, job_mgmt, mock_mgmt_client):
        with pytest.raises(ToolError) as exc_info:
            await job_mgmt.handle_action("list_session_attributions", {})

        assert exc_info.value.field == "session_id"

    @pytest.mark.asyncio
    async def test_action_is_advertised(self, job_mgmt, mock_mgmt_client):
        actions = await job_mgmt._get_supported_actions()
        assert "list_session_attributions" in actions

        result = await job_mgmt.handle_action("get_capabilities", {})
        payload = json.loads(result[0].text)

        assert "list_session_attributions" in payload["business_actions"]
        assert "list_session_attributions" in payload["parameters"]
        assert "session_id" in payload["parameters"]["list_session_attributions"]

    @pytest.mark.asyncio
    async def test_documentation_names_the_missing_splits_field(self, job_mgmt, mock_mgmt_client):
        result = await job_mgmt.handle_action("get_capabilities", {})
        payload = json.loads(result[0].text)

        assert "splits" in payload["parameters"]["list_session_attributions"]["splits"]
        assert (
            "declares no splits field"
            in payload["parameters"]["list_session_attributions"]["splits"]
        )

    @pytest.mark.asyncio
    async def test_examples_include_the_action(self, job_mgmt, mock_mgmt_client):
        result = await job_mgmt.handle_action("get_examples", {})
        payload = json.loads(result[0].text)

        assert payload["list_session_attributions"]["example"]["action"] == (
            "list_session_attributions"
        )

    @pytest.mark.asyncio
    async def test_no_write_action_is_exposed(self, job_mgmt, mock_mgmt_client):
        """Decision (BACK-2769): the MCP exposes no session-attribution write."""
        actions = await job_mgmt._get_supported_actions()

        assert not [
            action
            for action in actions
            if "session" in action and action != "list_session_attributions"
        ]


class TestSessionAttributionDecisionIsRecorded:
    """The decision must stay findable in code, not only on the ticket."""

    def test_module_docstring_records_the_decision_and_error_semantics(self):
        from src.revenium_mcp_server.tools_decomposed import job_management

        doc = job_management.__doc__ or ""
        assert "Decision (BACK-2769)" in doc
        assert "does NOT expose" in doc
        assert "association-client.ts" in doc
        assert "422" in doc and "400" in doc
        assert "CodingAssistantSource" in doc


# ===========================================================================


REASON_CATEGORY_ROW = {
    "ticketId": "BACK-3094",
    "reasonCategory": "peer-review",
    "reasonCategoryGroup": "delivery-support",
    "reasonCategoryWorkClassification": "WORK",
}


class TestSessionAttributionReasonCategoryFields:
    """PRODUCT-2796 added three classification fields the renderer must name."""

    def test_the_three_fields_are_declared(self):
        names = [name for name, _ in _SESSION_ATTRIBUTION_FIELDS]

        assert names.count("reasonCategory") == 1
        assert names.count("reasonCategoryGroup") == 1
        assert names.count("reasonCategoryWorkClassification") == 1

    def test_values_render_by_name_when_present(self):
        rendered = _render_session_attributions(SESSION_ID, [REASON_CATEGORY_ROW])

        assert "Reason category: peer-review" in rendered
        assert "Reason category group: delivery-support" in rendered
        assert "Reason category work classification: WORK" in rendered

    def test_absent_fields_render_as_unavailable_never_zero_or_empty(self):
        rendered = _render_session_attributions(SESSION_ID, [{"ticketId": "BACK-3094"}])

        assert "Reason category: unavailable" in rendered
        assert "Reason category group: unavailable" in rendered
        assert "Reason category work classification: unavailable" in rendered
        assert ": 0" not in rendered
        assert "Reason category:\n" not in rendered

    def test_a_standalone_category_without_a_group_still_shows_the_category(self):
        """The registry returns no group for personal/restricted/other/uncategorized."""
        rendered = _render_session_attributions(
            SESSION_ID,
            [
                {
                    "ticketId": "BACK-3094",
                    "reasonCategory": "personal",
                    "reasonCategoryGroup": None,
                    "reasonCategoryWorkClassification": "NON_WORK",
                }
            ],
        )

        assert "Reason category: personal" in rendered
        assert "Reason category group: unavailable" in rendered
        assert "Reason category work classification: NON_WORK" in rendered

    def test_they_no_longer_count_as_additional_fields_not_shown(self):
        rendered = _render_session_attributions(SESSION_ID, [REASON_CATEGORY_ROW])

        assert "additional field" not in rendered

    def test_only_genuinely_unknown_fields_are_counted(self):
        rendered = _render_session_attributions(
            SESSION_ID, [{**REASON_CATEGORY_ROW, "brandNewField": "surprise"}]
        )

        assert "1 additional field not shown: brandNewField" in rendered
        assert "surprise" not in rendered


class TestSessionAttributionNullReasonNote:
    """A null reason has three meanings this read cannot tell apart."""

    def test_note_states_all_three_meanings(self):
        rendered = _render_session_attributions(SESSION_ID, [{"ticketId": "BACK-3094"}])

        assert "Reason: unavailable" in rendered
        assert "no note was recorded for the interval" in rendered
        assert "not visible to this caller" in rendered
        assert "attribution detail text setting is off" in rendered
        assert "BACK-3096" in rendered

    def test_note_is_absent_when_every_row_carries_its_reason(self):
        rendered = _render_session_attributions(
            SESSION_ID,
            [
                {"ticketId": "A-1", "reason": "Investigating before opening a ticket"},
                {"ticketId": "A-2", "reason": "Follow-up"},
            ],
        )

        assert _SESSION_ATTRIBUTION_REASON_NOTE not in rendered
        assert "Reason: Investigating before opening a ticket" in rendered

    def test_note_appears_when_only_one_row_lacks_the_reason(self):
        rendered = _render_session_attributions(
            SESSION_ID,
            [{"ticketId": "A-1", "reason": "Kept"}, {"ticketId": "A-2"}],
        )

        assert _SESSION_ATTRIBUTION_REASON_NOTE in rendered

    def test_an_empty_collection_carries_no_reason_note(self):
        rendered = _render_session_attributions(SESSION_ID, [])

        assert _SESSION_ATTRIBUTION_REASON_NOTE not in rendered
        assert "does not expose splits" in rendered

    def test_the_splits_note_is_still_the_last_line(self):
        rendered = _render_session_attributions(SESSION_ID, [{"ticketId": "A-1"}])

        assert rendered.endswith(_SESSION_ATTRIBUTION_SPLITS_NOTE)

    @pytest.mark.asyncio
    async def test_result_carries_the_note_only_when_a_row_lacks_the_reason(
        self, job_manager, mock_client
    ):
        mock_client.get_session_attributions.return_value = _collection(
            {"ticketId": "A-1"}
        )
        without = await job_manager.list_session_attributions({"session_id": SESSION_ID})

        mock_client.get_session_attributions.return_value = _collection(
            {"ticketId": "A-1", "reason": "Kept"}
        )
        with_reason = await job_manager.list_session_attributions(
            {"session_id": SESSION_ID}
        )

        assert without["reason_note"] == _SESSION_ATTRIBUTION_REASON_NOTE
        assert "reason_note" not in with_reason

    @pytest.mark.asyncio
    async def test_action_output_carries_the_note(self, job_mgmt, mock_mgmt_client):
        mock_mgmt_client.get_session_attributions = AsyncMock(
            return_value=_collection(REASON_CATEGORY_ROW)
        )

        result = await job_mgmt.handle_action(
            "list_session_attributions", {"session_id": SESSION_ID}
        )

        assert "Reason category: peer-review" in result[0].text
        assert _SESSION_ATTRIBUTION_REASON_NOTE in result[0].text

    @pytest.mark.asyncio
    async def test_capabilities_document_the_fields_and_the_note(
        self, job_mgmt, mock_mgmt_client
    ):
        result = await job_mgmt.handle_action("get_capabilities", {})
        entry = json.loads(result[0].text)["parameters"]["list_session_attributions"]

        assert "reasonCategoryWorkClassification" in entry["returns"]
        assert "WORK, NON_WORK or UNKNOWN" in entry["returns"]
        assert entry["reason"] == _SESSION_ATTRIBUTION_REASON_NOTE

    @pytest.mark.asyncio
    async def test_capability_metadata_lists_the_note_as_a_limitation(
        self, job_mgmt, mock_mgmt_client
    ):
        capabilities = await job_mgmt._get_tool_capabilities()
        attribution = [
            capability for capability in capabilities if "Attribution" in capability.name
        ]

        assert attribution
        assert _SESSION_ATTRIBUTION_REASON_NOTE in attribution[0].limitations
# BACK-3091 — the outcome metrics array, entityVersion, and amend_outcome
# ===========================================================================


class TestOutcomeMetricsAndEntityVersionAreDocumented:
    """The two fields already flowed through untouched; nothing an agent reads
    said so. `metrics` rides the outcome body verbatim and `entityVersion`
    survives `_strip_links`, so the only possible regression is the guidance
    going quiet about them again."""

    @pytest.mark.asyncio
    async def test_capabilities_name_metrics_on_report_outcome(self, job_mgmt):
        result = await job_mgmt.handle_action("get_capabilities", {})
        report_outcome = json.loads(result[0].text)["parameters"]["report_outcome"]

        assert "metrics" in report_outcome["outcome_data"]
        assert "quality_rate" in report_outcome["outcome_data"]
        assert "PER_JOB" in report_outcome["outcome_data"]
        assert "entityVersion" in report_outcome["outcome_data"]

    @pytest.mark.asyncio
    async def test_examples_carry_a_metrics_payload(self, job_mgmt):
        result = await job_mgmt.handle_action("get_examples", {})
        report_outcome = json.loads(result[0].text)["report_outcome"]

        entry = report_outcome["example_with_metrics"]["outcome_data"]["metrics"][0]
        assert entry["key"] == "quality_rate"
        assert entry["provenance"] == "MEASURED"
        assert "entityVersion" in report_outcome["entity_version"]

    @pytest.mark.asyncio
    async def test_read_examples_name_entity_version(self, job_mgmt):
        result = await job_mgmt.handle_action("get_examples", {})
        parsed = json.loads(result[0].text)

        assert "entityVersion" in parsed["list_jobs"]["description"]
        assert "entityVersion" in parsed["get_job"]["description"]

    @pytest.mark.asyncio
    async def test_report_outcome_still_forwards_metrics_verbatim(
        self, job_manager, mock_client
    ):
        """The docs item must not have grown a filter on the write path."""
        mock_client.report_job_outcome.return_value = {"status": "reported"}
        outcome_data = {
            "executionStatus": "SUCCESS",
            "metrics": [{"key": "quality_rate", "value": 0.93, "provenance": "MEASURED"}],
        }

        await job_manager.report_outcome({"job_id": "j1", "outcome_data": outcome_data})

        mock_client.report_job_outcome.assert_called_once_with("j1", outcome_data)

    @pytest.mark.asyncio
    async def test_get_job_keeps_entity_version(self, job_manager, mock_client):
        mock_client.get_job_by_id.return_value = {
            "id": "j1",
            "entityVersion": 3,
            "_links": {"self": {"href": "http://internal-lb/x"}},
        }

        result = await job_manager.get_job({"job_id": "j1"})

        assert result["data"]["entityVersion"] == 3
        assert "_links" not in result["data"]


class TestAmendOutcomeDecisionIsRecorded:
    """BACK-3091 item 2. The adopt-or-decline decision lives in the module
    docstring beside Decision (BACK-2769); a future drift run must find the
    reasoning rather than re-deriving it. Deleting the block, or shipping the
    action without it, fails here."""

    def test_decision_block_present_in_module_docstring(self):
        docstring = job_management_module.__doc__ or ""

        assert "Decision (BACK-3091)" in docstring
        assert "ADOPTED" in docstring
        assert "expected_entity_version" in docstring
        assert "outcome/metrics" in docstring

    @pytest.mark.asyncio
    async def test_amend_outcome_is_an_advertised_action(self, job_mgmt):
        actions = await job_mgmt._get_supported_actions()

        assert "amend_outcome" in actions

    def test_registry_closure_declares_expected_entity_version(self):
        """FastMCP derives the public schema from the closure signature, so a
        parameter missing there is rejected before handle_action runs."""
        import inspect

        from src.revenium_mcp_server.tool_configuration import registry as registry_module

        source = inspect.getsource(registry_module.ToolConfigurationRegistry._register_manage_jobs)
        assert "expected_entity_version: Optional[Union[int, str]] = None" in source
        assert '"expected_entity_version": expected_entity_version,' in source


class TestJobManagerAmendOutcome:
    """The PATCH path: verbatim body, the optimistic lock, and the 409."""

    @pytest.mark.asyncio
    async def test_amend_forwards_the_body_verbatim_with_the_version(
        self, job_manager, mock_client
    ):
        mock_client.amend_job_outcome.return_value = {"id": "j1", "entityVersion": 3}

        result = await job_manager.amend_outcome(
            {
                "job_id": "j1",
                "expected_entity_version": 2,
                "outcome_data": {
                    "reason": "Deal value corrected after invoicing",
                    "outcomeValue": 149.99,
                    "metrics": [{"key": "quality_rate", "value": 0.93}],
                },
            }
        )

        mock_client.amend_job_outcome.assert_called_once_with(
            "j1",
            {
                "reason": "Deal value corrected after invoicing",
                "outcomeValue": 149.99,
                "metrics": [{"key": "quality_rate", "value": 0.93}],
                "expectedEntityVersion": 2,
            },
        )
        assert result["action"] == "amend_outcome"
        assert result["data"]["entityVersion"] == 3

    @pytest.mark.asyncio
    async def test_amend_omits_the_lock_when_no_version_is_given(
        self, job_manager, mock_client
    ):
        """Omitted means last-write-wins, the platform's documented backward
        compatible default. The key must be absent, not null."""
        mock_client.amend_job_outcome.return_value = {"id": "j1"}

        await job_manager.amend_outcome(
            {"job_id": "j1", "outcome_data": {"outcomeReason": "Customer confirmed churn"}}
        )

        sent = mock_client.amend_job_outcome.call_args[0][1]
        assert "expectedEntityVersion" not in sent

    @pytest.mark.asyncio
    async def test_version_zero_is_sent_not_dropped_as_falsy(
        self, job_manager, mock_client
    ):
        mock_client.amend_job_outcome.return_value = {"id": "j1"}

        await job_manager.amend_outcome(
            {"job_id": "j1", "expected_entity_version": 0, "outcome_data": {"outcomeValue": 1.0}}
        )

        assert mock_client.amend_job_outcome.call_args[0][1]["expectedEntityVersion"] == 0

    @pytest.mark.asyncio
    async def test_numeric_string_version_is_coerced(self, job_manager, mock_client):
        """The MCP boundary can hand a string through for any argument."""
        mock_client.amend_job_outcome.return_value = {"id": "j1"}

        await job_manager.amend_outcome(
            {"job_id": "j1", "expected_entity_version": "4", "outcome_data": {"outcomeValue": 1.0}}
        )

        assert mock_client.amend_job_outcome.call_args[0][1]["expectedEntityVersion"] == 4

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad", [-1, "abc", 1.5, True, {"v": 1}])
    async def test_bad_version_is_rejected_before_the_request(
        self, job_manager, mock_client, bad
    ):
        with pytest.raises(ToolError) as exc_info:
            await job_manager.amend_outcome(
                {"job_id": "j1", "expected_entity_version": bad, "outcome_data": {"outcomeValue": 1.0}}
            )

        assert exc_info.value.field == "expected_entity_version"
        assert exc_info.value.error_code == ErrorCodes.INVALID_PARAMETER
        mock_client.amend_job_outcome.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_job_id_is_rejected(self, job_manager):
        with pytest.raises(ToolError) as exc_info:
            await job_manager.amend_outcome({"outcome_data": {"outcomeValue": 1.0}})

        assert exc_info.value.field == "job_id"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("empty", [None, {}, "not a dict"])
    async def test_empty_amendment_is_rejected(self, job_manager, mock_client, empty):
        """An amendment naming nothing burns a revision for no change."""
        with pytest.raises(ToolError) as exc_info:
            await job_manager.amend_outcome({"job_id": "j1", "outcome_data": empty})

        assert exc_info.value.field == "outcome_data"
        mock_client.amend_job_outcome.assert_not_called()

    @pytest.mark.asyncio
    async def test_409_becomes_a_structured_conflict_naming_the_current_version(
        self, job_manager, mock_client
    ):
        """The version to retry with exists only in the platform's prose."""
        mock_client.amend_job_outcome.side_effect = ReveniumAPIError(
            "Outcome has changed since entity version 1; current version is 4",
            status_code=409,
        )

        with pytest.raises(ToolError) as exc_info:
            await job_manager.amend_outcome(
                {"job_id": "j1", "expected_entity_version": 1, "outcome_data": {"outcomeValue": 1.0}}
            )

        error = exc_info.value
        assert error.error_code == ErrorCodes.RESOURCE_CONFLICT
        assert error.context["current_entity_version"] == 4
        assert error.context["expected_entity_version"] == 1
        assert "was NOT applied" in error.message
        assert any("get_job" in s for s in error.suggestions)

    @pytest.mark.asyncio
    async def test_409_without_a_parseable_version_says_unknown_rather_than_guessing(
        self, job_manager, mock_client
    ):
        mock_client.amend_job_outcome.side_effect = ReveniumAPIError(
            "Conflict", status_code=409
        )

        with pytest.raises(ToolError) as exc_info:
            await job_manager.amend_outcome(
                {"job_id": "j1", "expected_entity_version": 1, "outcome_data": {"outcomeValue": 1.0}}
            )

        assert exc_info.value.context["current_entity_version"] is None
        assert "did not name the current version" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_409_is_not_retried(self, job_manager, mock_client):
        """The PATCH is not idempotent; a retry appends a duplicate revision."""
        mock_client.amend_job_outcome.side_effect = ReveniumAPIError(
            "Outcome has changed since entity version 1; current version is 4",
            status_code=409,
        )

        with pytest.raises(ToolError):
            await job_manager.amend_outcome(
                {"job_id": "j1", "expected_entity_version": 1, "outcome_data": {"outcomeValue": 1.0}}
            )

        assert mock_client.amend_job_outcome.call_count == 1

    @pytest.mark.asyncio
    async def test_non_409_api_errors_are_reraised(self, job_manager, mock_client):
        mock_client.amend_job_outcome.side_effect = ReveniumAPIError(
            "Bad request", status_code=400
        )

        with pytest.raises(ReveniumAPIError):
            await job_manager.amend_outcome(
                {"job_id": "j1", "outcome_data": {"outcomeValue": 1.0}}
            )

    @pytest.mark.asyncio
    async def test_amend_strips_links(self, job_manager, mock_client):
        mock_client.amend_job_outcome.return_value = {
            "id": "j1",
            "entityVersion": 5,
            "_links": {"self": {"href": "http://internal-lb/x"}},
        }

        result = await job_manager.amend_outcome(
            {"job_id": "j1", "outcome_data": {"outcomeValue": 1.0}}
        )

        assert "_links" not in result["data"]

    def test_conflict_version_is_read_from_the_response_body_too(self):
        """Depending on how the body decoded, the prose may be on a field."""
        error = ReveniumAPIError(
            "Conflict",
            status_code=409,
            response_data={"message": "Outcome has changed since entity version 2; current version is 7"},
        )

        assert _parse_outcome_conflict_version(error) == 7


class TestAmendOutcomeThroughHandleAction:
    @pytest.mark.asyncio
    async def test_amend_outcome_dispatches(self, job_mgmt, mock_mgmt_client):
        mock_mgmt_client.amend_job_outcome = AsyncMock(
            return_value={"id": "j1", "entityVersion": 3}
        )

        result = await job_mgmt.handle_action(
            "amend_outcome",
            {
                "job_id": "j1",
                "expected_entity_version": 2,
                "outcome_data": {"reason": "corrected", "outcomeValue": 149.99},
            },
        )

        assert isinstance(result[0], TextContent)
        assert "Outcome amended for job j1" in result[0].text
        assert "entityVersion" in result[0].text

    @pytest.mark.asyncio
    async def test_capabilities_describe_the_amendment(self, job_mgmt):
        result = await job_mgmt.handle_action("get_capabilities", {})
        parsed = json.loads(result[0].text)

        assert "amend_outcome" in parsed["business_actions"]
        amend = parsed["parameters"]["amend_outcome"]
        assert set(amend) == {"job_id", "outcome_data", "expected_entity_version", "history"}
        assert "metrics" in amend["outcome_data"]
        assert "last-write-wins" in amend["expected_entity_version"]

    @pytest.mark.asyncio
    async def test_examples_show_the_read_then_amend_loop(self, job_mgmt):
        result = await job_mgmt.handle_action("get_examples", {})
        amend = json.loads(result[0].text)["amend_outcome"]

        assert amend["example_corrected_value"]["expected_entity_version"] == 2
        assert (
            amend["example_late_quality_metric"]["outcome_data"]["metrics"][0]["key"]
            == "quality_rate"
        )
        assert "expected_entity_version" not in amend["example_without_the_lock"]


class TestAmendOutcomeNestedVersionCannotBypassValidation:
    """outcome_data is free-form and forwarded verbatim, so a caller can put
    the platform's own `expectedEntityVersion` spelling inside it. It is lifted
    out and run through the same coercion as the argument — never forwarded
    unvalidated, and never counted as a field being amended."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("key", ["expectedEntityVersion", "expected_entity_version"])
    async def test_nested_version_is_validated_and_sent(self, job_manager, mock_client, key):
        mock_client.amend_job_outcome.return_value = {"id": "j1"}

        await job_manager.amend_outcome(
            {"job_id": "j1", "outcome_data": {"outcomeValue": 1.0, key: "4"}}
        )

        sent = mock_client.amend_job_outcome.call_args[0][1]
        assert sent == {"outcomeValue": 1.0, "expectedEntityVersion": 4}

    @pytest.mark.asyncio
    async def test_malformed_nested_version_is_rejected_before_the_request(
        self, job_manager, mock_client
    ):
        with pytest.raises(ToolError) as exc_info:
            await job_manager.amend_outcome(
                {
                    "job_id": "j1",
                    "outcome_data": {"outcomeValue": 1.0, "expectedEntityVersion": -3},
                }
            )

        assert exc_info.value.error_code == ErrorCodes.INVALID_PARAMETER
        assert "outcome_data.expectedEntityVersion" in exc_info.value.message
        mock_client.amend_job_outcome.assert_not_called()

    @pytest.mark.asyncio
    async def test_nested_and_argument_agreeing_is_accepted(self, job_manager, mock_client):
        mock_client.amend_job_outcome.return_value = {"id": "j1"}

        await job_manager.amend_outcome(
            {
                "job_id": "j1",
                "expected_entity_version": 2,
                "outcome_data": {"outcomeValue": 1.0, "expectedEntityVersion": 2},
            }
        )

        assert mock_client.amend_job_outcome.call_args[0][1]["expectedEntityVersion"] == 2

    @pytest.mark.asyncio
    async def test_nested_and_argument_disagreeing_is_refused_not_guessed(
        self, job_manager, mock_client
    ):
        with pytest.raises(ToolError) as exc_info:
            await job_manager.amend_outcome(
                {
                    "job_id": "j1",
                    "expected_entity_version": 2,
                    "outcome_data": {"outcomeValue": 1.0, "expectedEntityVersion": 5},
                }
            )

        assert "Conflicting optimistic-lock versions" in exc_info.value.message
        mock_client.amend_job_outcome.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_body_naming_only_the_lock_is_an_empty_amendment(
        self, job_manager, mock_client
    ):
        """The lock is not a change; a body carrying nothing else amends nothing."""
        with pytest.raises(ToolError) as exc_info:
            await job_manager.amend_outcome(
                {"job_id": "j1", "outcome_data": {"expectedEntityVersion": 2}}
            )

        assert exc_info.value.field == "outcome_data"
        assert "A version is the lock, not a change" in exc_info.value.message
        mock_client.amend_job_outcome.assert_not_called()
# BACK-3094 — the reason-category fields, and what a null reason means
# ====================================================================
