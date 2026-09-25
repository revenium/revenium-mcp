"""Unit tests for Job Management tools.

Tests the JobManager and JobManagement classes from the decomposed tools module.
Focuses on 7 business actions, meta-actions, and the 409 Conflict edge case.
"""

import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.tools_decomposed import job_management as job_management_module
from src.revenium_mcp_server.tools_decomposed.job_management import (
    _ROI_ROW_FIELDS,
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
            "modalityCost": 0.0,
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
            "modalityCost": 0.0,
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
    async def test_get_roi_summary_carries_modality_cost(self, job_manager, mock_client):
        """The fourth cost category (image, video, audio) is a published field.

        BACK-3074: isotope's roi-summary now reports modalityCost beside
        tokenCost, externalToolCost and humanCost, and totalCost is the sum of
        all four. A row that carries it must surface it labeled, and a row that
        omits it must read as unavailable, never as 0 or as a missing key.
        """
        response = json.loads(json.dumps(ROI_SUMMARY_RESPONSE))
        response["byJobType"][0]["modalityCost"] = 0.75
        response["byJobType"][0]["totalCost"] = 4.25
        del response["byJobType"][1]["modalityCost"]
        mock_client.get_jobs_roi_summary = AsyncMock(return_value=response)

        result = await job_manager.get_roi_summary({})

        with_media, without_media = result["by_job_type"]
        assert with_media["modalityCost"] == 0.75
        assert with_media["totalCost"] == 4.25
        assert without_media["modalityCost"] == "unavailable"
        assert "modalityCost" in _ROI_ROW_FIELDS

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
        assert "separate metering-plane client owns the write" in doc
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


# ===========================================================================
# BACK-3090 — job type economics, baselines and period facts
# ===========================================================================

# The economics declaration as the platform returns it, including the two
# fields the PUT does not accept (jobType, currentBaseline). Built once so a
# test that narrows it is visibly narrowing this shape.
ECONOMICS_RESOURCE = {
    "jobType": "mcp-test-claims",
    "unitMetricKey": "completed_claims",
    "unitLabel": "claim",
    "metrics": [
        {
            "key": "completed_claims",
            "type": "COUNT",
            "direction": "HIGHER_IS_BETTER",
            "aggregation": "SUM",
            "resolution": "PER_JOB",
        }
    ],
    "dimensions": [{"key": "region", "allowedValues": ["us", "ca"]}],
    "monetization": {
        "metricKey": "completed_claims",
        "valuePerUnit": 4.25,
        "currency": "USD",
        "category": "COST_AVOIDED",
        "basis": "REALIZED",
    },
    "overheadPerUnit": None,
    "overheadCurrency": None,
    "currentBaseline": {
        "version": 1,
        "effectiveFrom": "2026-08-01T00:00:00Z",
        "costPerUnit": 4.5,
        "currency": "USD",
        "provenance": "CUSTOMER_DECLARED",
    },
}

BASELINE_VERSIONS = [
    {
        "version": 2,
        "effectiveFrom": "2026-09-01T00:00:00Z",
        "costPerUnit": 4.1,
        "currency": "USD",
        "provenance": "MEASURED",
    },
    {
        "version": 1,
        "effectiveFrom": "2026-08-01T00:00:00Z",
        "costPerUnit": 4.5,
        "currency": "USD",
        "provenance": "CUSTOMER_DECLARED",
    },
]

PERIOD_FACT = {
    "periodStart": "2026-08-01T00:00:00Z",
    "periodEnd": "2026-09-01T00:00:00Z",
    "dimensionKey": "region",
    "dimensionValue": "us",
    "key": "manual_rework_minutes",
    "value": 420,
}

JOB_TYPE_ECONOMICS_ACTIONS = (
    "get_job_type_economics",
    "upsert_job_type_economics",
    "list_job_type_baselines",
    "create_job_type_baseline",
    "report_period_facts",
    "append_outcome_metrics",
)


@pytest.fixture
def economics_client(mock_client):
    """The mock client with the BACK-3090 methods attached."""
    mock_client.get_job_type_economics = AsyncMock()
    mock_client.put_job_type_economics = AsyncMock()
    mock_client.list_job_type_baselines = AsyncMock()
    mock_client.create_job_type_baseline = AsyncMock()
    mock_client.append_job_type_facts = AsyncMock()
    mock_client.append_job_outcome_metrics = AsyncMock()
    return mock_client


class TestGetJobTypeEconomics:
    """The read that was missing: the declaration ROI is measured against."""

    @pytest.mark.asyncio
    async def test_reads_the_declaration_for_the_type(self, job_manager, economics_client):
        economics_client.get_job_type_economics.return_value = dict(ECONOMICS_RESOURCE)

        result = await job_manager.get_job_type_economics({"job_type": "mcp-test-claims"})

        economics_client.get_job_type_economics.assert_awaited_once_with("mcp-test-claims")
        assert result["action"] == "get_job_type_economics"
        assert result["job_type"] == "mcp-test-claims"
        assert result["data"]["unitMetricKey"] == "completed_claims"
        assert result["data"]["currentBaseline"]["version"] == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("job_type", [None, "", "   ", 7])
    async def test_blank_job_type_is_refused_before_the_request(
        self, job_manager, economics_client, job_type
    ):
        with pytest.raises(ToolError) as exc_info:
            await job_manager.get_job_type_economics({"job_type": job_type})

        assert exc_info.value.field == "job_type"
        assert exc_info.value.error_code == ErrorCodes.VALIDATION_ERROR
        economics_client.get_job_type_economics.assert_not_called()

    @pytest.mark.asyncio
    async def test_404_becomes_a_named_not_found(self, job_manager, economics_client):
        economics_client.get_job_type_economics.side_effect = ReveniumAPIError(
            "Not Found", status_code=404
        )

        with pytest.raises(ToolError) as exc_info:
            await job_manager.get_job_type_economics(
                {"job_type": "mcp-test-nonexistent-type"}
            )

        assert exc_info.value.error_code == ErrorCodes.RESOURCE_NOT_FOUND
        assert "mcp-test-nonexistent-type" in exc_info.value.message
        assert "no economics declaration" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_platform_400_detail_is_surfaced_verbatim(
        self, job_manager, economics_client
    ):
        economics_client.get_job_type_economics.side_effect = ReveniumAPIError(
            "job type not registered", status_code=400
        )

        with pytest.raises(ToolError) as exc_info:
            await job_manager.get_job_type_economics({"job_type": "mcp-test-claims"})

        assert "job type not registered" in exc_info.value.message
        assert exc_info.value.context["upstream_message"] == "job type not registered"

    @pytest.mark.asyncio
    async def test_other_api_errors_are_left_alone(self, job_manager, economics_client):
        economics_client.get_job_type_economics.side_effect = ReveniumAPIError(
            "boom", status_code=500
        )

        with pytest.raises(ReveniumAPIError):
            await job_manager.get_job_type_economics({"job_type": "mcp-test-claims"})


class TestUpsertJobTypeEconomicsReadsBeforeItWrites:
    """PUT replaces the whole declaration upstream, so a partial edit has to be
    merged over the stored one or it clears the baseline assumptions."""

    @pytest.mark.asyncio
    async def test_an_omitted_field_is_carried_over_not_cleared(
        self, job_manager, economics_client
    ):
        economics_client.get_job_type_economics.return_value = dict(ECONOMICS_RESOURCE)
        economics_client.put_job_type_economics.return_value = {"jobType": "mcp-test-claims"}

        result = await job_manager.upsert_job_type_economics(
            {
                "job_type": "mcp-test-claims",
                "economics": {"unitLabel": "processed claim"},
            }
        )

        sent = economics_client.put_job_type_economics.await_args[0][1]
        assert sent["unitLabel"] == "processed claim"
        # Everything the caller did not name survives the replace.
        assert sent["unitMetricKey"] == "completed_claims"
        assert sent["monetization"]["valuePerUnit"] == 4.25
        assert sent["dimensions"] == [{"key": "region", "allowedValues": ["us", "ca"]}]
        assert result["preserved_fields"] == ["dimensions", "metrics", "monetization", "unitMetricKey"]
        assert result["fields_set"] == ["unitLabel"]
        assert result["created"] is False

    @pytest.mark.asyncio
    async def test_the_read_only_resource_fields_are_not_sent_back(
        self, job_manager, economics_client
    ):
        economics_client.get_job_type_economics.return_value = dict(ECONOMICS_RESOURCE)
        economics_client.put_job_type_economics.return_value = {}

        await job_manager.upsert_job_type_economics(
            {"job_type": "mcp-test-claims", "economics": {"unitLabel": "claim"}}
        )

        sent = economics_client.put_job_type_economics.await_args[0][1]
        assert "jobType" not in sent
        assert "currentBaseline" not in sent
        # A null optional is dropped rather than echoed back as an explicit null.
        assert "overheadPerUnit" not in sent

    @pytest.mark.asyncio
    async def test_404_on_the_read_is_the_create_case(self, job_manager, economics_client):
        economics_client.get_job_type_economics.side_effect = ReveniumAPIError(
            "Not Found", status_code=404
        )
        economics_client.put_job_type_economics.return_value = {"jobType": "mcp-test-new"}

        result = await job_manager.upsert_job_type_economics(
            {
                "job_type": "mcp-test-new",
                "economics": {"unitMetricKey": "completed_claims", "unitLabel": "claim"},
            }
        )

        assert result["created"] is True
        assert result["preserved_fields"] == []
        assert economics_client.put_job_type_economics.await_args[0][1] == {
            "unitMetricKey": "completed_claims",
            "unitLabel": "claim",
        }

    @pytest.mark.asyncio
    async def test_a_create_missing_the_required_fields_is_refused(
        self, job_manager, economics_client
    ):
        economics_client.get_job_type_economics.side_effect = ReveniumAPIError(
            "Not Found", status_code=404
        )

        with pytest.raises(ToolError) as exc_info:
            await job_manager.upsert_job_type_economics(
                {"job_type": "mcp-test-new", "economics": {"unitLabel": "claim"}}
            )

        assert "unitMetricKey" in exc_info.value.message
        economics_client.put_job_type_economics.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_non_404_read_failure_stops_the_write(
        self, job_manager, economics_client
    ):
        """A 500 on the read means the stored declaration is unknown, and
        writing then would replace it with a partial one."""
        economics_client.get_job_type_economics.side_effect = ReveniumAPIError(
            "boom", status_code=500
        )

        with pytest.raises(ReveniumAPIError):
            await job_manager.upsert_job_type_economics(
                {"job_type": "mcp-test-claims", "economics": {"unitLabel": "claim"}}
            )

        economics_client.put_job_type_economics.assert_not_called()

    @pytest.mark.asyncio
    async def test_snake_case_field_is_translated_not_ignored(
        self, job_manager, economics_client
    ):
        economics_client.get_job_type_economics.return_value = dict(ECONOMICS_RESOURCE)
        economics_client.put_job_type_economics.return_value = {}

        await job_manager.upsert_job_type_economics(
            {"job_type": "mcp-test-claims", "economics": {"unit_label": "processed claim"}}
        )

        sent = economics_client.put_job_type_economics.await_args[0][1]
        assert sent["unitLabel"] == "processed claim"
        assert "unit_label" not in sent

    @pytest.mark.asyncio
    async def test_nested_snake_case_fields_are_translated(
        self, job_manager, economics_client
    ):
        """The capability text promises a declared field's snake_case spelling is
        translated. That has to hold one level down too: a PUT that REPLACES the
        declaration is the worst place for a key to be silently dropped."""
        economics_client.get_job_type_economics.side_effect = ReveniumAPIError(
            "Not Found", status_code=404
        )
        economics_client.put_job_type_economics.return_value = {}

        await job_manager.upsert_job_type_economics(
            {
                "job_type": "mcp-test-claims",
                "economics": {
                    "unit_metric_key": "completed_claims",
                    "unit_label": "claim",
                    "metrics": [
                        {
                            "key": "completed_claims",
                            "type": "COUNT",
                            "direction": "HIGHER_IS_BETTER",
                            "aggregation": "SUM",
                            "resolution": "PER_JOB",
                        }
                    ],
                    "dimensions": [{"key": "region", "allowed_values": ["us", "ca"]}],
                    "monetization": {
                        "metric_key": "completed_claims",
                        "value_per_unit": 4.25,
                        "currency": "USD",
                        "category": "COST_AVOIDED",
                        "basis": "REALIZED",
                    },
                },
            }
        )

        sent = economics_client.put_job_type_economics.await_args[0][1]
        assert sent["unitMetricKey"] == "completed_claims"
        assert sent["dimensions"] == [{"key": "region", "allowedValues": ["us", "ca"]}]
        assert sent["monetization"]["metricKey"] == "completed_claims"
        assert sent["monetization"]["valuePerUnit"] == 4.25
        # Not one snake_case key survives anywhere in the body.
        assert "allowed_values" not in sent["dimensions"][0]
        assert "metric_key" not in sent["monetization"]
        assert "value_per_unit" not in sent["monetization"]

    @pytest.mark.asyncio
    async def test_an_unknown_nested_key_still_rides_along(
        self, job_manager, economics_client
    ):
        """Translation must not turn into an allowlist: a field the contract
        adds has to reach the API without a release here."""
        economics_client.get_job_type_economics.side_effect = ReveniumAPIError(
            "Not Found", status_code=404
        )
        economics_client.put_job_type_economics.return_value = {}

        await job_manager.upsert_job_type_economics(
            {
                "job_type": "mcp-test-claims",
                "economics": {
                    "unitMetricKey": "completed_claims",
                    "unitLabel": "claim",
                    "dimensions": [{"key": "region", "somethingNew": True}],
                },
            }
        )

        sent = economics_client.put_job_type_economics.await_args[0][1]
        assert sent["dimensions"][0]["somethingNew"] is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "economics,field",
        [
            (
                {"dimensions": [{"key": "region", "allowedValues": [], "allowed_values": []}]},
                "economics.dimensions[0]",
            ),
            (
                {"monetization": {"metricKey": "a", "metric_key": "b"}},
                "economics.monetization",
            ),
        ],
    )
    async def test_both_spellings_of_a_nested_field_is_refused(
        self, job_manager, economics_client, economics, field
    ):
        with pytest.raises(ToolError) as exc_info:
            await job_manager.upsert_job_type_economics(
                {"job_type": "mcp-test-claims", "economics": economics}
            )

        assert exc_info.value.field == field
        assert "twice" in exc_info.value.message
        economics_client.get_job_type_economics.assert_not_called()

    @pytest.mark.asyncio
    async def test_both_spellings_at_once_is_refused(self, job_manager, economics_client):
        with pytest.raises(ToolError) as exc_info:
            await job_manager.upsert_job_type_economics(
                {
                    "job_type": "mcp-test-claims",
                    "economics": {"unitLabel": "a", "unit_label": "b"},
                }
            )

        assert "twice" in exc_info.value.message
        economics_client.get_job_type_economics.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("economics", [None, {}, "unitLabel=claim", 7])
    async def test_an_empty_economics_body_is_refused(
        self, job_manager, economics_client, economics
    ):
        with pytest.raises(ToolError) as exc_info:
            await job_manager.upsert_job_type_economics(
                {"job_type": "mcp-test-claims", "economics": economics}
            )

        assert exc_info.value.field == "economics"
        economics_client.get_job_type_economics.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "metrics", ["not-a-list", [{"type": "COUNT"}], [{"key": "  "}], ["completed"]]
    )
    async def test_a_malformed_metric_declaration_is_refused(
        self, job_manager, economics_client, metrics
    ):
        with pytest.raises(ToolError) as exc_info:
            await job_manager.upsert_job_type_economics(
                {"job_type": "mcp-test-claims", "economics": {"metrics": metrics}}
            )

        assert exc_info.value.field.startswith("economics.metrics")
        economics_client.get_job_type_economics.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_platform_400_on_the_write_is_surfaced_verbatim(
        self, job_manager, economics_client
    ):
        economics_client.get_job_type_economics.return_value = dict(ECONOMICS_RESOURCE)
        economics_client.put_job_type_economics.side_effect = ReveniumAPIError(
            "monetization.metricKey completed_claims is not declared", status_code=400
        )

        with pytest.raises(ToolError) as exc_info:
            await job_manager.upsert_job_type_economics(
                {"job_type": "mcp-test-claims", "economics": {"unitLabel": "claim"}}
            )

        assert "is not declared" in exc_info.value.message


class TestUpsertDisclosesTheLostUpdateWindow:
    """The read-modify-write closes one hole and opens a narrower one: the
    resource carries no version token, so two concurrent editors revert each
    other silently. No client-side lock is invented for that — the window is
    disclosed."""

    @pytest.mark.asyncio
    async def test_the_response_carries_the_note(self, job_manager, economics_client):
        economics_client.get_job_type_economics.return_value = dict(ECONOMICS_RESOURCE)
        economics_client.put_job_type_economics.return_value = {}

        result = await job_manager.upsert_job_type_economics(
            {"job_type": "mcp-test-claims", "economics": {"unitLabel": "claim"}}
        )

        assert "no version or ETag" in result["concurrency_note"]
        assert "reverted silently" in result["concurrency_note"]

    @pytest.mark.asyncio
    async def test_the_capability_text_states_it(self, job_mgmt, mock_mgmt_client):
        result = await job_mgmt.handle_action("get_capabilities", {})
        payload = json.loads(result[0].text)

        assert "no version or ETag" in (
            payload["parameters"]["upsert_job_type_economics"]["concurrency"]
        )

    @pytest.mark.asyncio
    async def test_the_note_names_the_known_second_writer(self, job_manager, economics_client):
        """BACK-3090 iteration 4: the concurrent writer is not hypothetical.
        The dashboard's Job Type editor saves a full replacement from its
        drawer-open snapshot and rebuilds metrics with PER_JOB/COUNT/SUM
        defaults, so it can downgrade a PERIOD metric this tool declared - and
        the next report_period_facts is then refused for a reason that has
        nothing to do with the call that failed. A caller who is told only
        'concurrent writes are possible' cannot act on that; one who is told
        where the other writer lives can."""
        economics_client.get_job_type_economics.return_value = dict(ECONOMICS_RESOURCE)
        economics_client.put_job_type_economics.return_value = {}

        result = await job_manager.upsert_job_type_economics(
            {"job_type": "mcp-test-claims", "economics": {"unitLabel": "claim"}}
        )

        note = result["concurrency_note"]
        assert "dashboard's Job Type editor" in note
        assert "report_period_facts" in note
        assert "immediately before an upsert" in note

    @pytest.mark.asyncio
    async def test_no_client_side_lock_was_invented(self, job_manager, economics_client):
        """A lock the server does not honour would read as a guarantee. The
        upsert must take no version argument and send none."""
        economics_client.get_job_type_economics.return_value = dict(ECONOMICS_RESOURCE)
        economics_client.put_job_type_economics.return_value = {}

        await job_manager.upsert_job_type_economics(
            {
                "job_type": "mcp-test-claims",
                "economics": {"unitLabel": "claim"},
                "expected_entity_version": 3,
            }
        )

        sent = economics_client.put_job_type_economics.await_args[0][1]
        assert "expectedEntityVersion" not in sent
        assert "entityVersion" not in sent


class TestJobTypeBaselines:
    """Baselines are append-only versions, newest first."""

    @pytest.mark.asyncio
    async def test_list_returns_the_versions_newest_first(
        self, job_manager, economics_client
    ):
        economics_client.list_job_type_baselines.return_value = list(BASELINE_VERSIONS)

        result = await job_manager.list_job_type_baselines({"job_type": "mcp-test-claims"})

        economics_client.list_job_type_baselines.assert_awaited_once_with("mcp-test-claims")
        assert result["count"] == 2
        assert result["data"][0]["version"] == 2

    @pytest.mark.asyncio
    async def test_no_baseline_is_an_answer_not_a_failure(
        self, job_manager, economics_client
    ):
        """An empty ARRAY is the one empty result that is an answer."""
        economics_client.list_job_type_baselines.return_value = []

        result = await job_manager.list_job_type_baselines({"job_type": "mcp-test-claims"})

        assert result["count"] == 0
        assert result["data"] == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("body", [{}, {"error": "nope"}, "text", None, 7])
    async def test_a_non_list_body_is_refused_not_reported_as_no_baselines(
        self, job_manager, economics_client, body
    ):
        """A contract failure must not read as "this job type declared none" --
        declaring a fresh baseline on top of history you failed to read is how a
        version gets superseded by accident."""
        economics_client.list_job_type_baselines.return_value = body

        with pytest.raises(ToolError) as exc_info:
            await job_manager.list_job_type_baselines({"job_type": "mcp-test-claims"})

        assert exc_info.value.error_code == ErrorCodes.API_ERROR
        assert "mcp-test-claims" in exc_info.value.message
        assert "NOT the same as the job type having none" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_the_refusal_names_the_keys_it_saw(self, job_manager, economics_client):
        economics_client.list_job_type_baselines.return_value = {"page": 1, "items": []}

        with pytest.raises(ToolError) as exc_info:
            await job_manager.list_job_type_baselines({"job_type": "mcp-test-claims"})

        assert "'items', 'page'" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_create_sends_the_baseline_and_reports_it(
        self, job_manager, economics_client
    ):
        economics_client.create_job_type_baseline.return_value = {"version": 3}

        result = await job_manager.create_job_type_baseline(
            {
                "job_type": "mcp-test-claims",
                "baseline": {
                    "effectiveFrom": "2026-10-01T00:00:00Z",
                    "costPerUnit": 3.9,
                    "currency": "USD",
                },
            }
        )

        economics_client.create_job_type_baseline.assert_awaited_once_with(
            "mcp-test-claims",
            {
                "effectiveFrom": "2026-10-01T00:00:00Z",
                "costPerUnit": 3.9,
                "currency": "USD",
            },
        )
        assert result["data"]["version"] == 3
        assert "not idempotent" in result["append_note"]

    @pytest.mark.asyncio
    async def test_effective_from_snake_case_is_accepted(
        self, job_manager, economics_client
    ):
        economics_client.create_job_type_baseline.return_value = {}

        await job_manager.create_job_type_baseline(
            {
                "job_type": "mcp-test-claims",
                "baseline": {"effective_from": "2026-10-01T00:00:00Z"},
            }
        )

        sent = economics_client.create_job_type_baseline.await_args[0][1]
        assert sent == {"effectiveFrom": "2026-10-01T00:00:00Z"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "baseline",
        [None, {}, {"costPerUnit": 4.5}, {"effectiveFrom": ""}, {"effectiveFrom": 2026}],
    )
    async def test_a_baseline_without_effective_from_is_refused(
        self, job_manager, economics_client, baseline
    ):
        with pytest.raises(ToolError) as exc_info:
            await job_manager.create_job_type_baseline(
                {"job_type": "mcp-test-claims", "baseline": baseline}
            )

        assert exc_info.value.field.startswith("baseline")
        economics_client.create_job_type_baseline.assert_not_called()


class TestReportPeriodFacts:
    """PERIOD facts on the job type, as a bare JSON array."""

    @pytest.mark.asyncio
    async def test_the_array_is_the_body(self, job_manager, economics_client):
        economics_client.append_job_type_facts.return_value = {}

        result = await job_manager.report_period_facts(
            {"job_type": "mcp-test-claims", "facts": [dict(PERIOD_FACT)]}
        )

        economics_client.append_job_type_facts.assert_awaited_once_with(
            "mcp-test-claims", [dict(PERIOD_FACT)]
        )
        assert result["appended"] == 1
        assert "PERIOD" in result["resolution_note"]

    @pytest.mark.asyncio
    async def test_snake_case_entry_fields_are_translated(
        self, job_manager, economics_client
    ):
        economics_client.append_job_type_facts.return_value = {}

        await job_manager.report_period_facts(
            {
                "job_type": "mcp-test-claims",
                "facts": [
                    {
                        "period_start": "2026-08-01T00:00:00Z",
                        "period_end": "2026-09-01T00:00:00Z",
                        "dimension_key": "region",
                        "dimension_value": "us",
                        "key": "manual_rework_minutes",
                        "value": 420,
                    }
                ],
            }
        )

        sent = economics_client.append_job_type_facts.await_args[0][1]
        assert sent == [dict(PERIOD_FACT)]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("facts", [None, [], {}, "facts", [42], [{"value": 1}]])
    async def test_a_malformed_fact_body_is_refused_before_the_request(
        self, job_manager, economics_client, facts
    ):
        with pytest.raises(ToolError) as exc_info:
            await job_manager.report_period_facts(
                {"job_type": "mcp-test-claims", "facts": facts}
            )

        assert exc_info.value.error_code in (
            ErrorCodes.VALIDATION_ERROR,
            ErrorCodes.INVALID_PARAMETER,
        )
        economics_client.append_job_type_facts.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_missing_value_is_refused(self, job_manager, economics_client):
        entry = dict(PERIOD_FACT)
        entry["value"] = None

        with pytest.raises(ToolError) as exc_info:
            await job_manager.report_period_facts(
                {"job_type": "mcp-test-claims", "facts": [entry]}
            )

        assert "value" in exc_info.value.message
        economics_client.append_job_type_facts.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("reason", ["", "   ", 7])
    async def test_a_blank_reason_is_refused(self, job_manager, economics_client, reason):
        entry = dict(PERIOD_FACT)
        entry["reason"] = reason

        with pytest.raises(ToolError) as exc_info:
            await job_manager.report_period_facts(
                {"job_type": "mcp-test-claims", "facts": [entry]}
            )

        assert "reason" in exc_info.value.message
        economics_client.append_job_type_facts.assert_not_called()

    @pytest.mark.asyncio
    async def test_the_resolution_400_is_surfaced_verbatim(
        self, job_manager, economics_client
    ):
        economics_client.append_job_type_facts.side_effect = ReveniumAPIError(
            "metric manual_rework_minutes is not declared PERIOD", status_code=400
        )

        with pytest.raises(ToolError) as exc_info:
            await job_manager.report_period_facts(
                {"job_type": "mcp-test-claims", "facts": [dict(PERIOD_FACT)]}
            )

        assert "is not declared PERIOD" in exc_info.value.message
        assert exc_info.value.context["upstream_status"] == 400


class TestAppendOutcomeMetrics:
    """PER_JOB facts appended to a reported outcome, without rewriting it."""

    @pytest.mark.asyncio
    async def test_the_array_is_the_body(self, job_manager, economics_client):
        economics_client.append_job_outcome_metrics.return_value = {}

        result = await job_manager.append_outcome_metrics(
            {
                "job_id": "job_123",
                "metrics": [{"key": "quality_rate", "value": 0.93, "provenance": "MEASURED"}],
            }
        )

        economics_client.append_job_outcome_metrics.assert_awaited_once_with(
            "job_123", [{"key": "quality_rate", "value": 0.93, "provenance": "MEASURED"}]
        )
        assert result["appended"] == 1
        assert "entityVersion" in result["entity_version_note"]

    @pytest.mark.asyncio
    async def test_missing_job_id_is_refused(self, job_manager, economics_client):
        with pytest.raises(ToolError) as exc_info:
            await job_manager.append_outcome_metrics(
                {"metrics": [{"key": "quality_rate", "value": 0.93}]}
            )

        assert exc_info.value.field == "job_id"
        economics_client.append_job_outcome_metrics.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("metrics", [None, [], [{"key": "  ", "value": 1}]])
    async def test_a_malformed_metric_body_is_refused(
        self, job_manager, economics_client, metrics
    ):
        with pytest.raises(ToolError):
            await job_manager.append_outcome_metrics(
                {"job_id": "job_123", "metrics": metrics}
            )

        economics_client.append_job_outcome_metrics.assert_not_called()

    @pytest.mark.asyncio
    async def test_404_names_the_job_not_the_job_type(self, job_manager, economics_client):
        economics_client.append_job_outcome_metrics.side_effect = ReveniumAPIError(
            "Not Found", status_code=404
        )

        with pytest.raises(ToolError) as exc_info:
            await job_manager.append_outcome_metrics(
                {"job_id": "job_123", "metrics": [{"key": "quality_rate", "value": 0.93}]}
            )

        assert exc_info.value.error_code == ErrorCodes.RESOURCE_NOT_FOUND
        assert exc_info.value.field == "job_id"
        assert "Job 'job_123'" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_the_undeclared_metric_400_is_surfaced_verbatim(
        self, job_manager, economics_client
    ):
        economics_client.append_job_outcome_metrics.side_effect = ReveniumAPIError(
            "metric quality_rate is not declared PER_JOB", status_code=400
        )

        with pytest.raises(ToolError) as exc_info:
            await job_manager.append_outcome_metrics(
                {"job_id": "job_123", "metrics": [{"key": "quality_rate", "value": 0.93}]}
            )

        assert "is not declared PER_JOB" in exc_info.value.message
        assert exc_info.value.field == "job_id"


class TestJobTypeEconomicsThroughHandleAction:
    """Every new action has a dispatch route and is advertised."""

    @pytest.fixture
    def economics_mgmt_client(self, mock_mgmt_client):
        mock_mgmt_client.get_job_type_economics = AsyncMock()
        mock_mgmt_client.put_job_type_economics = AsyncMock()
        mock_mgmt_client.list_job_type_baselines = AsyncMock()
        mock_mgmt_client.create_job_type_baseline = AsyncMock()
        mock_mgmt_client.append_job_type_facts = AsyncMock()
        mock_mgmt_client.append_job_outcome_metrics = AsyncMock()
        return mock_mgmt_client

    @pytest.mark.asyncio
    async def test_every_action_is_advertised(self, job_mgmt):
        supported = await job_mgmt._get_supported_actions()
        for action in JOB_TYPE_ECONOMICS_ACTIONS:
            assert action in supported

    @pytest.mark.asyncio
    async def test_capabilities_name_every_action(self, job_mgmt, mock_mgmt_client):
        result = await job_mgmt.handle_action("get_capabilities", {})
        payload = json.loads(result[0].text)
        for action in JOB_TYPE_ECONOMICS_ACTIONS:
            assert action in payload["business_actions"]
            assert action in payload["parameters"]

    @pytest.mark.asyncio
    async def test_examples_cover_every_action(self, job_mgmt, mock_mgmt_client):
        result = await job_mgmt.handle_action("get_examples", {})
        payload = json.loads(result[0].text)
        for action in JOB_TYPE_ECONOMICS_ACTIONS:
            assert action in payload

    @pytest.mark.asyncio
    async def test_get_economics_dispatches(self, job_mgmt, economics_mgmt_client):
        economics_mgmt_client.get_job_type_economics.return_value = dict(ECONOMICS_RESOURCE)

        result = await job_mgmt.handle_action(
            "get_job_type_economics", {"job_type": "mcp-test-claims"}
        )

        assert "mcp-test-claims" in result[0].text
        assert "completed_claims" in result[0].text

    @pytest.mark.asyncio
    async def test_upsert_dispatches_and_reports_the_merge(
        self, job_mgmt, economics_mgmt_client
    ):
        economics_mgmt_client.get_job_type_economics.return_value = dict(ECONOMICS_RESOURCE)
        economics_mgmt_client.put_job_type_economics.return_value = {}

        result = await job_mgmt.handle_action(
            "upsert_job_type_economics",
            {"job_type": "mcp-test-claims", "economics": {"unitLabel": "processed claim"}},
        )

        assert "Economics updated" in result[0].text
        assert "preserved_fields" in result[0].text

    @pytest.mark.asyncio
    async def test_list_baselines_dispatches(self, job_mgmt, economics_mgmt_client):
        economics_mgmt_client.list_job_type_baselines.return_value = list(BASELINE_VERSIONS)

        result = await job_mgmt.handle_action(
            "list_job_type_baselines", {"job_type": "mcp-test-claims"}
        )

        assert "newest first" in result[0].text

    @pytest.mark.asyncio
    async def test_create_baseline_dispatches(self, job_mgmt, economics_mgmt_client):
        economics_mgmt_client.create_job_type_baseline.return_value = {"version": 3}

        result = await job_mgmt.handle_action(
            "create_job_type_baseline",
            {
                "job_type": "mcp-test-claims",
                "baseline": {"effectiveFrom": "2026-10-01T00:00:00Z"},
            },
        )

        assert "Baseline version appended" in result[0].text

    @pytest.mark.asyncio
    async def test_report_period_facts_dispatches(self, job_mgmt, economics_mgmt_client):
        economics_mgmt_client.append_job_type_facts.return_value = {}

        result = await job_mgmt.handle_action(
            "report_period_facts",
            {"job_type": "mcp-test-claims", "facts": [dict(PERIOD_FACT)]},
        )

        assert "Appended 1 period fact(s)" in result[0].text

    @pytest.mark.asyncio
    async def test_append_outcome_metrics_dispatches(self, job_mgmt, economics_mgmt_client):
        economics_mgmt_client.append_job_outcome_metrics.return_value = {}

        result = await job_mgmt.handle_action(
            "append_outcome_metrics",
            {"job_id": "job_123", "metrics": [{"key": "quality_rate", "value": 0.93}]},
        )

        assert "Appended 1 outcome metric fact(s)" in result[0].text

    def test_registry_closure_declares_the_economics_parameters(self):
        """FastMCP derives the public schema from the closure signature, so a
        parameter missing there is rejected before handle_action runs."""
        import inspect

        from src.revenium_mcp_server.tool_configuration import registry as registry_module

        source = inspect.getsource(
            registry_module.ToolConfigurationRegistry._register_manage_jobs
        )
        for name in ("job_type", "economics", "baseline", "facts", "metrics"):
            assert f"{name}: Optional[" in source
            assert f'"{name}": {name},' in source


class TestJobTypeEconomicsDecisionIsRecorded:
    """The BACK-3091 docstring declined POST .../outcome/metrics. The reversal
    has to be written down where that decline is, or the module contradicts
    itself."""

    def test_the_decision_block_is_present(self):
        doc = job_management_module.__doc__ or ""
        assert "Decision (BACK-3090)" in doc
        assert "read-modify-write" in doc
        assert "not idempotent" in doc

    def test_the_replace_semantics_are_stated_to_the_caller(self):
        assert "replaces the whole declaration" in (
            job_management_module._ECONOMICS_REPLACE_NOTE
        )
        assert "preserved_fields" in job_management_module._ECONOMICS_REPLACE_NOTE

    def test_the_request_field_set_excludes_the_read_only_resource_fields(self):
        fields = job_management_module._ECONOMICS_REQUEST_FIELDS
        assert "jobType" not in fields
        assert "currentBaseline" not in fields
        assert "unitMetricKey" in fields


# ===========================================================================
# BACK-3090 iteration 2 - a refusal is an error, and a write's 404 is its own
# ===========================================================================

class TestManageJobsJsonArgumentsRaiseOnBadInput:
    """FastMCP sets the response's error flag only when the tool raises, so a
    decode failure that RETURNS TextContent reports a write that never happened
    as a completed call - the BACK-2937 shape, which was still open in this
    closure. All six JSON-string arguments now share one raising rule."""

    @staticmethod
    async def _closure():
        from src.revenium_mcp_server.tool_configuration.config import ToolConfig
        from src.revenium_mcp_server.tool_configuration.registry import (
            ToolConfigurationRegistry,
        )

        captured = {}

        class _CapturingMCP:
            def tool(self, *args, **kwargs):
                def decorator(fn):
                    captured["fn"] = fn
                    return fn

                return decorator

        registry = ToolConfigurationRegistry(ToolConfig())
        await registry._register_manage_jobs(_CapturingMCP())
        return captured["fn"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "argument",
        ["outcome_data", "filters", "economics", "baseline", "facts", "metrics"],
    )
    async def test_a_malformed_json_string_raises_rather_than_returning_text(
        self, argument
    ):
        manage_jobs = await self._closure()

        with pytest.raises(ToolError) as exc_info:
            await manage_jobs(action="get_capabilities", **{argument: "{not json"})

        assert exc_info.value.error_code == ErrorCodes.VALIDATION_ERROR
        assert exc_info.value.field == argument
        assert f"Invalid JSON for {argument}" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_an_empty_filters_string_raises_like_any_other_bad_json(self):
        """Raised in review: `filters or {}` ran BEFORE the decode loop, so
        filters="" was already {} by the time the loop looked for a string --
        list_jobs then ran unfiltered and returned every job as though the
        filter had been applied. The default now lands after the loop."""
        manage_jobs = await self._closure()

        with pytest.raises(ToolError) as exc_info:
            await manage_jobs(action="list_jobs", filters="")

        assert exc_info.value.field == "filters"
        assert "Invalid JSON for filters" in exc_info.value.message

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "argument", ["economics", "baseline", "facts", "metrics", "outcome_data"]
    )
    async def test_an_empty_string_raises_on_every_other_json_argument_too(
        self, argument
    ):
        manage_jobs = await self._closure()

        with pytest.raises(ToolError) as exc_info:
            await manage_jobs(action="get_capabilities", **{argument: ""})

        assert exc_info.value.field == argument

    @pytest.mark.asyncio
    async def test_omitted_filters_still_defaults_to_an_empty_dict(self):
        """The default is delayed, not removed: a caller who sends no filters
        must still reach the tool with {} rather than None."""
        from unittest.mock import AsyncMock as _AsyncMock

        manage_jobs = await self._closure()
        captured = {}

        async def fake_execution(*, tool_name, action, arguments, tool_class):
            captured.update(arguments)
            return []

        with patch(
            "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
            new=_AsyncMock(side_effect=fake_execution),
        ):
            await manage_jobs(action="list_jobs")

        assert captured["filters"] == {}

    @pytest.mark.asyncio
    async def test_the_caller_facing_wording_is_unchanged(self):
        """The conversion changed the mechanism, not the guidance."""
        manage_jobs = await self._closure()

        with pytest.raises(ToolError) as exc_info:
            await manage_jobs(action="list_jobs", filters="{not json")
        assert 'e.g. {"type": "loan_processing"}' in exc_info.value.message

        with pytest.raises(ToolError) as exc_info:
            await manage_jobs(action="report_outcome", outcome_data="{not json")
        assert "with outcome, revenue, etc." in exc_info.value.message

    def test_every_json_argument_is_in_one_table(self):
        """The three hand-copied decode blocks are gone; a seventh JSON argument
        must be added to the table rather than to a fourth block."""
        import inspect

        from src.revenium_mcp_server.tool_configuration import registry as registry_module

        source = inspect.getsource(
            registry_module.ToolConfigurationRegistry._register_manage_jobs
        )
        assert "MANAGE_JOBS_JSON_ARGUMENTS" in source
        assert "TextContent as TC" not in source
        assert [name for name, _ in registry_module.MANAGE_JOBS_JSON_ARGUMENTS] == [
            "outcome_data",
            "filters",
            "economics",
            "baseline",
            "facts",
            "metrics",
        ]


class TestUpsertWriteNotFoundIsNotTheReadNotFound:
    """Routing the PUT's 404 through the read's branch told the caller the type
    'has nothing to read' and advised fixing it with upsert_job_type_economics
    - the action that had just failed."""

    @pytest.mark.asyncio
    async def test_the_write_404_names_the_write_and_does_not_advise_the_failed_action(
        self, job_manager, economics_client
    ):
        economics_client.get_job_type_economics.return_value = dict(ECONOMICS_RESOURCE)
        economics_client.put_job_type_economics.side_effect = ReveniumAPIError(
            "Not Found", status_code=404
        )

        with pytest.raises(ToolError) as exc_info:
            await job_manager.upsert_job_type_economics(
                {"job_type": "mcp-test-claims", "economics": {"unitLabel": "claim"}}
            )

        error = exc_info.value
        assert error.error_code == ErrorCodes.RESOURCE_NOT_FOUND
        assert "rejected the upsert_job_type_economics write" in error.message
        assert "nothing was stored" in error.message
        assert error.context["phase"] == "write"
        # The read branch's advice must not appear: it points at this action.
        assert "has nothing to read" not in error.message
        assert not any(
            "Declare the economics first with upsert_job_type_economics" in s
            for s in error.suggestions
        )
        assert any("removed between" in s for s in error.suggestions)

    @pytest.mark.asyncio
    async def test_the_read_404_keeps_its_own_text(self, job_manager, economics_client):
        """The read path is unchanged: there, 'declare it with
        upsert_job_type_economics' is exactly the right advice."""
        economics_client.get_job_type_economics.side_effect = ReveniumAPIError(
            "Not Found", status_code=404
        )

        with pytest.raises(ToolError) as exc_info:
            await job_manager.get_job_type_economics({"job_type": "mcp-test-claims"})

        error = exc_info.value
        assert "has nothing to read" in error.message
        assert any(
            "Declare the economics first with upsert_job_type_economics" in s
            for s in error.suggestions
        )
        # All three builders label their phase now; what matters is that the
        # read is labelled as a read, not as a write or an append.
        assert error.context["phase"] == "read"

    @pytest.mark.asyncio
    async def test_the_write_400_is_still_the_verbatim_platform_sentence(
        self, job_manager, economics_client
    ):
        """Splitting the 404 out must not take the 400 with it."""
        economics_client.get_job_type_economics.return_value = dict(ECONOMICS_RESOURCE)
        economics_client.put_job_type_economics.side_effect = ReveniumAPIError(
            "unitMetricKey completed_claims is not among the declared metrics",
            status_code=400,
        )

        with pytest.raises(ToolError) as exc_info:
            await job_manager.upsert_job_type_economics(
                {"job_type": "mcp-test-claims", "economics": {"unitLabel": "claim"}}
            )

        assert "is not among the declared metrics" in exc_info.value.message
        assert exc_info.value.context["upstream_status"] == 400

    @pytest.mark.asyncio
    async def test_a_write_500_still_reaches_the_caller_untranslated(
        self, job_manager, economics_client
    ):
        economics_client.get_job_type_economics.return_value = dict(ECONOMICS_RESOURCE)
        economics_client.put_job_type_economics.side_effect = ReveniumAPIError(
            "boom", status_code=500
        )

        with pytest.raises(ReveniumAPIError):
            await job_manager.upsert_job_type_economics(
                {"job_type": "mcp-test-claims", "economics": {"unitLabel": "claim"}}
            )


# ===========================================================================
# BACK-3090 iteration 3 - the write 404s, the read the upsert builds on, and
# the summary surface
# ===========================================================================

class TestAppendNotFoundIsItsOwnMessage:
    """An append performs no read, so the upsert's "removed between your read
    and your write" advice is noise there, and the READ's advice - declare it
    with upsert_job_type_economics - is the only useful half."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "action,arguments,client_method",
        [
            (
                "create_job_type_baseline",
                {
                    "job_type": "mcp-test-claims",
                    "baseline": {"effectiveFrom": "2026-10-01T00:00:00Z"},
                },
                "create_job_type_baseline",
            ),
            (
                "report_period_facts",
                {"job_type": "mcp-test-claims", "facts": [dict(PERIOD_FACT)]},
                "append_job_type_facts",
            ),
        ],
    )
    async def test_the_append_404_says_nothing_was_appended(
        self, job_manager, economics_client, action, arguments, client_method
    ):
        getattr(economics_client, client_method).side_effect = ReveniumAPIError(
            "Not Found", status_code=404
        )

        with pytest.raises(ToolError) as exc_info:
            await getattr(job_manager, action)(arguments)

        error = exc_info.value
        assert error.error_code == ErrorCodes.RESOURCE_NOT_FOUND
        assert f"rejected the {action} append" in error.message
        assert "nothing was appended" in error.message
        assert error.context["phase"] == "append"
        # The read's wording must not appear...
        assert "has nothing to read" not in error.message
        # ...nor the upsert's read-then-write race, which an append cannot have.
        assert not any("removed between" in s for s in error.suggestions)
        assert not any("no version or ETag" in s for s in error.suggestions)
        # ...but "declare the economics first" is still the useful advice here.
        assert any("Declare the economics first" in s for s in error.suggestions)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "action,arguments,client_method",
        [
            (
                "create_job_type_baseline",
                {
                    "job_type": "mcp-test-claims",
                    "baseline": {"effectiveFrom": "2026-10-01T00:00:00Z"},
                },
                "create_job_type_baseline",
            ),
            (
                "report_period_facts",
                {"job_type": "mcp-test-claims", "facts": [dict(PERIOD_FACT)]},
                "append_job_type_facts",
            ),
        ],
    )
    async def test_the_append_400_is_still_the_platform_sentence(
        self, job_manager, economics_client, action, arguments, client_method
    ):
        getattr(economics_client, client_method).side_effect = ReveniumAPIError(
            "metric manual_rework_minutes is not declared PERIOD", status_code=400
        )

        with pytest.raises(ToolError) as exc_info:
            await getattr(job_manager, action)(arguments)

        assert "is not declared PERIOD" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_the_read_404_keeps_pointing_at_the_declaration(
        self, job_manager, economics_client
    ):
        """The read builder is unchanged by the split."""
        economics_client.list_job_type_baselines.side_effect = ReveniumAPIError(
            "Not Found", status_code=404
        )

        with pytest.raises(ToolError) as exc_info:
            await job_manager.list_job_type_baselines({"job_type": "mcp-test-claims"})

        assert "has nothing to read" in exc_info.value.message
        assert exc_info.value.context["phase"] == "read"


class TestUpsertWillNotBuildOnABodyItCouldNotRead:
    """Only an explicit 404 means "no declaration yet". Inferring it from a
    malformed 200 would REPLACE a declaration nobody read with whatever fields
    the caller happened to name - the exact loss the read-modify-write exists
    to prevent."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "body",
        [
            {},
            [],
            [{"unitLabel": "claim"}],
            "unitLabel=claim",
            None,
            {"error": "something went wrong"},
        ],
    )
    async def test_a_malformed_read_refuses_and_never_writes(
        self, job_manager, economics_client, body
    ):
        economics_client.get_job_type_economics.return_value = body

        with pytest.raises(ToolError) as exc_info:
            await job_manager.upsert_job_type_economics(
                {"job_type": "mcp-test-claims", "economics": {"unitLabel": "claim"}}
            )

        assert exc_info.value.error_code == ErrorCodes.API_ERROR
        assert "Nothing was written" in exc_info.value.message
        assert "which the platform reports as a 404" in exc_info.value.message
        economics_client.put_job_type_economics.assert_not_called()

    @pytest.mark.asyncio
    async def test_the_refusal_names_what_it_saw(self, job_manager, economics_client):
        economics_client.get_job_type_economics.return_value = {"error": "nope"}

        with pytest.raises(ToolError) as exc_info:
            await job_manager.upsert_job_type_economics(
                {"job_type": "mcp-test-claims", "economics": {"unitLabel": "claim"}}
            )

        assert "['error']" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_a_declaration_carrying_one_request_field_is_accepted(
        self, job_manager, economics_client
    ):
        """The check is the weakest one that separates a declaration from an
        error envelope: which fields a tenant's declaration carries is the
        platform's business, not this tool's."""
        economics_client.get_job_type_economics.return_value = {
            "jobType": "mcp-test-claims",
            "unitMetricKey": "completed_claims",
        }
        economics_client.put_job_type_economics.return_value = {}

        result = await job_manager.upsert_job_type_economics(
            {"job_type": "mcp-test-claims", "economics": {"unitLabel": "claim"}}
        )

        assert result["created"] is False
        assert result["preserved_fields"] == ["unitMetricKey"]

    @pytest.mark.asyncio
    async def test_an_explicit_404_is_still_the_create_case(
        self, job_manager, economics_client
    ):
        economics_client.get_job_type_economics.side_effect = ReveniumAPIError(
            "Not Found", status_code=404
        )
        economics_client.put_job_type_economics.return_value = {}

        result = await job_manager.upsert_job_type_economics(
            {
                "job_type": "mcp-test-new",
                "economics": {"unitMetricKey": "completed_claims", "unitLabel": "claim"},
            }
        )

        assert result["created"] is True
        economics_client.put_job_type_economics.assert_awaited_once()


class TestBaselineResponseCarriesTheCurrencyConstraint:
    """A baseline carries costPerUnit and hourlyRate, so USD-only belongs on
    its response as much as on the upsert's."""

    @pytest.mark.asyncio
    async def test_currency_note_is_on_the_response(self, job_manager, economics_client):
        economics_client.create_job_type_baseline.return_value = {"version": 1}

        result = await job_manager.create_job_type_baseline(
            {
                "job_type": "mcp-test-claims",
                "baseline": {"effectiveFrom": "2026-10-01T00:00:00Z"},
            }
        )

        assert "USD only" in result["currency_note"]


class TestOneTranslatorForEveryEconomicsCall:
    """The try/except/translate/re-raise block was written out verbatim at four
    sites, which is four places to route a 404 to the wrong builder - the
    mistake that actually happened twice on this branch."""

    def test_the_verbatim_blocks_are_gone(self):
        import inspect

        source = inspect.getsource(job_management_module.JobManager)
        # One helper, used at five economics call sites.
        assert source.count("_translated_economics_call(") == 5
        # The removed read-path translator must not come back by name.
        assert "_job_type_economics_error" not in source

    def test_each_phase_has_its_own_builder(self):
        for builder, phase in (
            (job_management_module._job_type_read_not_found_error, "read"),
            (job_management_module._job_type_write_not_found_error, "write"),
            (job_management_module._job_type_append_not_found_error, "append"),
        ):
            error = builder(
                ReveniumAPIError("Not Found", status_code=404),
                action="an_action",
                job_type="a-type",
            )
            assert error.context["phase"] == phase
            assert error.error_code == ErrorCodes.RESOURCE_NOT_FOUND


class TestAgentSummaryNamesTheNewActions:
    """PR #384 shipped with this exact gap: the agent summary is the surface an
    agent reads first, and an action missing from it is an action it will not
    call."""

    @pytest.mark.asyncio
    async def test_key_actions_lists_all_six(self, job_mgmt):
        summary = await job_mgmt._get_agent_summary()

        for action in JOB_TYPE_ECONOMICS_ACTIONS:
            assert f"• {action} —" in summary, action

    @pytest.mark.asyncio
    async def test_the_summary_states_the_two_write_rules(self, job_mgmt):
        summary = await job_mgmt._get_agent_summary()

        assert "replaces the whole declaration" in summary
        assert "Append-only and never retried" in summary


# ===========================================================================
# BACK-3090 iteration 5 - dot-segment job types, and the create branch through
# dispatch
# ===========================================================================

class TestDotSegmentJobTypeIsRefused:
    """Percent-encoding keeps a value inside one path segment, but '.' is
    unreserved and survives it, so these two reach the URL as real dot-segments
    and URL resolution removes them - '..' turns .../jobs/types/{type}/economics
    into .../jobs/economics, a different endpoint called silently."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("job_type", ["..", ".", "  ..  "])
    @pytest.mark.parametrize(
        "action,extra",
        [
            ("get_job_type_economics", {}),
            ("list_job_type_baselines", {}),
            ("upsert_job_type_economics", {"economics": {"unitLabel": "claim"}}),
            (
                "create_job_type_baseline",
                {"baseline": {"effectiveFrom": "2026-10-01T00:00:00Z"}},
            ),
            ("report_period_facts", {"facts": [dict(PERIOD_FACT)]}),
        ],
    )
    async def test_every_action_refuses_it_before_any_request(
        self, job_manager, economics_client, job_type, action, extra
    ):
        with pytest.raises(ToolError) as exc_info:
            await getattr(job_manager, action)({"job_type": job_type, **extra})

        assert exc_info.value.error_code == ErrorCodes.INVALID_PARAMETER
        assert exc_info.value.field == "job_type"
        assert "dot-segment is normalised out of the URL path" in exc_info.value.message
        economics_client.get_job_type_economics.assert_not_called()
        economics_client.put_job_type_economics.assert_not_called()
        economics_client.list_job_type_baselines.assert_not_called()
        economics_client.create_job_type_baseline.assert_not_called()
        economics_client.append_job_type_facts.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("job_type", ["claims.v2", "x..y", ".hidden", "v1."])
    async def test_a_dot_inside_a_name_is_still_a_valid_job_type(
        self, job_manager, economics_client, job_type
    ):
        """Only a name that is ENTIRELY '.' or '..' is a dot-segment."""
        economics_client.get_job_type_economics.return_value = dict(ECONOMICS_RESOURCE)

        result = await job_manager.get_job_type_economics({"job_type": job_type})

        assert result["job_type"] == job_type


class TestUpsertCreateBranchThroughDispatch:
    """The dispatch tests only ever drove created=False, so the "declared"
    half of `"declared" if result["created"] else "updated"` was never rendered
    through handle_action."""

    @pytest.fixture
    def economics_mgmt_client(self, mock_mgmt_client):
        mock_mgmt_client.get_job_type_economics = AsyncMock()
        mock_mgmt_client.put_job_type_economics = AsyncMock()
        return mock_mgmt_client

    @pytest.mark.asyncio
    async def test_a_create_renders_declared_not_updated(
        self, job_mgmt, economics_mgmt_client
    ):
        economics_mgmt_client.get_job_type_economics.side_effect = ReveniumAPIError(
            "Not Found", status_code=404
        )
        economics_mgmt_client.put_job_type_economics.return_value = {}

        result = await job_mgmt.handle_action(
            "upsert_job_type_economics",
            {
                "job_type": "mcp-test-new",
                "economics": {
                    "unitMetricKey": "completed_claims",
                    "unitLabel": "claim",
                },
            },
        )

        text = result[0].text
        assert "Economics declared for job type mcp-test-new" in text
        assert "Economics updated" not in text
        assert '"created": true' in text
