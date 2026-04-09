"""Unit tests for Job Management tools.

Tests the JobManager and JobManagement classes from the decomposed tools module.
Focuses on 7 business actions, meta-actions, and the 409 Conflict edge case.
"""

import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.revenium_mcp_server.tools_decomposed.job_management import (
    JobManager,
    JobManagement,
)
from src.revenium_mcp_server.client import ReveniumAPIError
from src.revenium_mcp_server.common.error_handling import ToolError
from mcp.types import TextContent


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
    client.report_job_outcome = AsyncMock()
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
    client.report_job_outcome = AsyncMock()
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
    """Test JobManager.get_roi_summary orchestration behavior."""

    @pytest.mark.asyncio
    async def test_get_roi_summary_aggregates_all_types(self, job_manager, mock_client):
        """get_roi_summary fetches types and funnels, returns aggregated data."""
        mock_client.get_job_types.return_value = ["LEAD", "SALE"]
        mock_client.get_job_conversion_funnel.side_effect = [
            {"totalJobs": 100, "successfulJobs": 80, "convertedJobs": 60, "successRate": 0.8, "conversionRate": 0.6},
            {"totalJobs": 50, "successfulJobs": 40, "convertedJobs": 30, "successRate": 0.8, "conversionRate": 0.6},
        ]

        result = await job_manager.get_roi_summary({})

        assert result["action"] == "get_roi_summary"
        assert result["summary"]["totalJobTypes"] == 2
        assert result["summary"]["totalJobs"] == 150
        assert result["summary"]["successfulJobs"] == 120
        assert result["summary"]["convertedJobs"] == 90
        assert result["partial_failures"] == 0
        assert len(result["per_type_breakdown"]) == 2
        mock_client.get_job_types.assert_called_once()
        assert mock_client.get_job_conversion_funnel.call_count == 2

    @pytest.mark.asyncio
    async def test_get_roi_summary_passes_date_filters(self, job_manager, mock_client):
        """Date filters are forwarded to each funnel call."""
        mock_client.get_job_types.return_value = ["LEAD"]
        mock_client.get_job_conversion_funnel.return_value = {
            "totalJobs": 10, "successfulJobs": 8, "convertedJobs": 5,
            "successRate": 0.8, "conversionRate": 0.5,
        }

        result = await job_manager.get_roi_summary(
            {"filters": {"startDate": "2025-01-01", "endDate": "2025-12-31"}}
        )

        mock_client.get_job_conversion_funnel.assert_called_once_with(
            jobType="LEAD", startDate="2025-01-01", endDate="2025-12-31"
        )
        assert result["filters_applied"] == {"startDate": "2025-01-01", "endDate": "2025-12-31"}

    @pytest.mark.asyncio
    async def test_get_roi_summary_handles_partial_failure(self, job_manager, mock_client):
        """If one type's funnel fails, others still return successfully."""
        mock_client.get_job_types.return_value = ["LEAD", "BROKEN_TYPE"]
        mock_client.get_job_conversion_funnel.side_effect = [
            {"totalJobs": 100, "successfulJobs": 80, "convertedJobs": 60, "successRate": 0.8, "conversionRate": 0.6},
            ReveniumAPIError("Not found", status_code=404),
        ]

        result = await job_manager.get_roi_summary({})

        assert result["action"] == "get_roi_summary"
        assert result["summary"]["totalJobs"] == 100
        assert result["partial_failures"] == 1
        assert len(result["per_type_breakdown"]) == 2
        assert result["per_type_breakdown"][0]["status"] == "success"
        assert result["per_type_breakdown"][1]["status"] == "error"
        assert "status=404" in result["per_type_breakdown"][1]["error"]

    @pytest.mark.asyncio
    async def test_get_roi_summary_empty_types(self, job_manager, mock_client):
        """When no job types exist, returns empty summary."""
        mock_client.get_job_types.return_value = []

        result = await job_manager.get_roi_summary({})

        assert result["action"] == "get_roi_summary"
        assert result["summary"]["totalJobTypes"] == 0
        assert result["summary"]["totalJobs"] == 0
        assert result["summary"]["overallSuccessRate"] == 0
        assert result["summary"]["overallConversionRate"] == 0
        assert len(result["per_type_breakdown"]) == 0
        mock_client.get_job_conversion_funnel.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_roi_summary_all_failures_raises_error(self, job_manager, mock_client):
        """When all funnel calls fail, raises ToolError instead of returning zeroed data."""
        mock_client.get_job_types.return_value = ["LEAD", "SALE"]
        mock_client.get_job_conversion_funnel.side_effect = [
            ReveniumAPIError("Forbidden", status_code=403),
            ReveniumAPIError("Forbidden", status_code=403),
        ]

        with pytest.raises(ToolError) as exc_info:
            await job_manager.get_roi_summary({})

        assert "all" in str(exc_info.value).lower() or "failed" in str(exc_info.value).lower()


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
        """Unknown action returns a message indicating the action is not supported."""
        result = await job_mgmt.handle_action("nonexistent_action", {})

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
        text_lower = result[0].text.lower()
        assert "unknown action" in text_lower or "not supported" in text_lower


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
        """get_roi_summary action returns aggregated ROI summary."""
        mock_mgmt_client.get_job_types = AsyncMock(return_value=["LEAD"])
        mock_mgmt_client.get_job_conversion_funnel = AsyncMock(return_value={
            "totalJobs": 100, "successfulJobs": 80, "convertedJobs": 60,
            "successRate": 0.8, "conversionRate": 0.6,
        })

        result = await job_mgmt.handle_action("get_roi_summary", {})

        assert len(result) >= 1
        assert isinstance(result[0], TextContent)
        assert "roi summary" in result[0].text.lower()

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
