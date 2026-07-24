"""Tests for the manage_ai_insights tool (BACK-1455)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_list_investigators_action_returns_payload():
    from src.revenium_mcp_server.tools_decomposed.ai_insights_management import (
        AIInsightsManagement,
    )

    tool = AIInsightsManagement()
    with patch(
        "src.revenium_mcp_server.client.ReveniumClient.list_investigators",
        new=AsyncMock(return_value=[
            {"id": "det1", "displayName": "Detector One",
             "category": "waste", "version": "1.0"},
        ]),
    ):
        result = await tool.handle_action("list_investigators", {})

    # Tool returns a list of MCP content items; verify the first chunk is text and contains the id.
    assert len(result) >= 1
    text_payload = result[0].text if hasattr(result[0], "text") else str(result[0])
    assert "det1" in text_payload


@pytest.mark.asyncio
async def test_get_run_uses_slim_true_by_default():
    from src.revenium_mcp_server.tools_decomposed.ai_insights_management import (
        AIInsightsManagement,
    )

    tool = AIInsightsManagement()
    mock = AsyncMock(return_value={"id": "r1", "recommendationsSummary": []})
    with patch(
        "src.revenium_mcp_server.client.ReveniumClient.get_recommendation_run",
        new=mock,
    ):
        await tool.handle_action("get_run", {"run_id": "r1"})

    mock.assert_awaited_once_with("r1", slim=True)


@pytest.mark.asyncio
async def test_get_run_honors_explicit_slim_false():
    from src.revenium_mcp_server.tools_decomposed.ai_insights_management import (
        AIInsightsManagement,
    )

    tool = AIInsightsManagement()
    mock = AsyncMock(return_value={"id": "r1", "findingsJson": "[]"})
    with patch(
        "src.revenium_mcp_server.client.ReveniumClient.get_recommendation_run",
        new=mock,
    ):
        await tool.handle_action("get_run", {"run_id": "r1", "slim": False})

    mock.assert_awaited_once_with("r1", slim=False)


@pytest.mark.asyncio
async def test_get_run_missing_run_id_returns_validation_error():
    from src.revenium_mcp_server.common.error_handling import ToolError
    from src.revenium_mcp_server.tools_decomposed.ai_insights_management import (
        AIInsightsManagement,
    )

    tool = AIInsightsManagement()
    with pytest.raises(ToolError) as exc:
        await tool.handle_action("get_run", {})
    assert "run_id" in exc.value.message.lower() or exc.value.field == "run_id"


@pytest.mark.asyncio
async def test_list_runs_uses_backend_response_when_under_one_page():
    from src.revenium_mcp_server.tools_decomposed.ai_insights_management import (
        AIInsightsManagement,
    )

    tool = AIInsightsManagement()
    mock = AsyncMock(return_value={
        "data": [{"runId": "r1"}, {"runId": "r2"}],
        "next_cursor": None,
    })
    with patch(
        "src.revenium_mcp_server.client.ReveniumClient.list_recommendation_runs",
        new=mock,
    ):
        await tool.handle_action("list_runs", {"max_results": 50})

    assert mock.await_count == 1
    call = mock.await_args
    assert call.kwargs["limit"] == 50  # min(BACKEND_PAGE_LIMIT, 50)


@pytest.mark.asyncio
async def test_list_runs_auto_paginates_over_cursor():
    from src.revenium_mcp_server.tools_decomposed.ai_insights_management import (
        AIInsightsManagement,
    )

    tool = AIInsightsManagement()
    pages = [
        {"data": [{"runId": f"r{i}"} for i in range(100)], "next_cursor": "c1"},
        {"data": [{"runId": f"r{i}"} for i in range(100, 200)], "next_cursor": "c2"},
        {"data": [{"runId": f"r{i}"} for i in range(200, 250)], "next_cursor": None},
    ]
    mock = AsyncMock(side_effect=pages)
    with patch(
        "src.revenium_mcp_server.client.ReveniumClient.list_recommendation_runs",
        new=mock,
    ):
        result = await tool.handle_action("list_runs", {"max_results": 250})

    assert mock.await_count == 3
    text = result[0].text if hasattr(result[0], "text") else str(result[0])
    assert "250" in text or "r249" in text


@pytest.mark.asyncio
async def test_list_runs_rejects_max_results_over_hard_cap():
    """Over-cap values are rejected pre-flight with the valid range — a
    silent clamp hid the constraint from the caller."""
    from src.revenium_mcp_server.tools_decomposed.ai_insights_management import (
        AIInsightsManagement,
    )
    from src.revenium_mcp_server.common.error_handling import ToolError
    tool = AIInsightsManagement()
    mock = AsyncMock()
    with patch(
        "src.revenium_mcp_server.client.ReveniumClient.list_recommendation_runs",
        new=mock,
    ):
        with pytest.raises(ToolError) as exc:
            await tool.handle_action("list_runs", {"max_results": 5000})

    assert "1000" in exc.value.message
    assert "max_results" in exc.value.message
    mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_runs_stale_cursor_breaks_early():
    from src.revenium_mcp_server.tools_decomposed.ai_insights_management import (
        AIInsightsManagement,
    )

    tool = AIInsightsManagement()
    def stale_page(*_a, **_kw):
        return {"data": [{"runId": "x"}] * 5, "next_cursor": "stale"}

    mock = AsyncMock(side_effect=stale_page)
    with patch(
        "src.revenium_mcp_server.client.ReveniumClient.list_recommendation_runs",
        new=mock,
    ):
        await tool.handle_action("list_runs", {"max_results": 1000})

    assert mock.await_count == 2


@pytest.mark.asyncio
async def test_list_runs_rejects_invalid_max_results_type():
    from src.revenium_mcp_server.tools_decomposed.ai_insights_management import (
        AIInsightsManagement,
    )

    from src.revenium_mcp_server.common.error_handling import ToolError
    tool = AIInsightsManagement()
    with pytest.raises(ToolError) as exc:
        await tool.handle_action("list_runs", {"max_results": "abc"})
    assert "max_results" in exc.value.message
    assert "positive integer" in exc.value.message.lower()


@pytest.mark.asyncio
async def test_list_runs_rejects_nonpositive_max_results():
    from src.revenium_mcp_server.tools_decomposed.ai_insights_management import (
        AIInsightsManagement,
    )

    from src.revenium_mcp_server.common.error_handling import ToolError
    tool = AIInsightsManagement()
    with pytest.raises(ToolError) as exc:
        await tool.handle_action("list_runs", {"max_results": 0})
    assert "max_results" in exc.value.message


@pytest.mark.asyncio
async def test_list_feedback_auto_paginates_for_a_run():
    from src.revenium_mcp_server.tools_decomposed.ai_insights_management import (
        AIInsightsManagement,
    )

    tool = AIInsightsManagement()
    pages = [
        {"data": [{"id": "f1"}, {"id": "f2"}], "next_cursor": "c"},
        {"data": [{"id": "f3"}], "next_cursor": None},
    ]
    mock = AsyncMock(side_effect=pages)
    with patch(
        "src.revenium_mcp_server.client.ReveniumClient.list_recommendation_feedback",
        new=mock,
    ):
        await tool.handle_action("list_feedback", {"run_id": "r1", "max_results": 10})

    assert mock.await_count == 2
    for call in mock.await_args_list:
        assert call.args == ("r1",)


@pytest.mark.asyncio
async def test_list_feedback_missing_run_id_validation_error():
    from src.revenium_mcp_server.tools_decomposed.ai_insights_management import (
        AIInsightsManagement,
    )

    from src.revenium_mcp_server.common.error_handling import ToolError
    tool = AIInsightsManagement()
    with pytest.raises(ToolError) as exc:
        await tool.handle_action("list_feedback", {})
    assert "run_id" in exc.value.message.lower() or exc.value.field == "run_id"


@pytest.mark.asyncio
async def test_trigger_run_passes_filters_to_client():
    from src.revenium_mcp_server.tools_decomposed.ai_insights_management import (
        AIInsightsManagement,
    )

    tool = AIInsightsManagement()
    mock = AsyncMock(return_value={"runId": "r1", "status": "running"})
    with patch(
        "src.revenium_mcp_server.client.ReveniumClient.trigger_recommendation_run",
        new=mock,
    ):
        result = await tool.handle_action("trigger_run", {
            "period_start": "2026-01-01T00:00:00Z",
            "period_end":   "2026-01-31T23:59:59Z",
            "filter_agent": ["a"],
            "exclude_investigator_ids": ["x"],
        })

    mock.assert_awaited_once()
    call_kwargs = mock.await_args.kwargs
    assert call_kwargs["period_start"] == "2026-01-01T00:00:00Z"
    assert call_kwargs["period_end"] == "2026-01-31T23:59:59Z"
    assert call_kwargs["filter_agent"] == ["a"]
    assert call_kwargs["exclude_investigator_ids"] == ["x"]

    text = result[0].text if hasattr(result[0], "text") else str(result[0])
    assert "r1" in text


@pytest.mark.asyncio
async def test_trigger_run_missing_period_start_validation_error():
    from src.revenium_mcp_server.tools_decomposed.ai_insights_management import (
        AIInsightsManagement,
    )

    from src.revenium_mcp_server.common.error_handling import ToolError
    tool = AIInsightsManagement()
    with pytest.raises(ToolError) as exc:
        await tool.handle_action("trigger_run", {
            "period_end": "2026-01-31T23:59:59Z",
        })
    assert "period_start" in exc.value.message.lower() or exc.value.field == "period_start"


@pytest.mark.asyncio
async def test_submit_feedback_passes_all_fields():
    from src.revenium_mcp_server.tools_decomposed.ai_insights_management import (
        AIInsightsManagement,
    )

    tool = AIInsightsManagement()
    mock = AsyncMock(return_value={"id": "f1"})
    with patch(
        "src.revenium_mcp_server.client.ReveniumClient.submit_recommendation_feedback",
        new=mock,
    ):
        await tool.handle_action("submit_feedback", {
            "run_id": "r1",
            "recommendation_id": "rec1",
            "feedback_action": "implemented",
            "realized_savings": 42.5,
            "realized_savings_currency": "usd",
            "confidence_rating": 1,
        })

    call = mock.await_args
    # client signature: submit_recommendation_feedback(run_id, recommendation_id, action, *, ...)
    assert call.args == ("r1", "rec1", "implemented")
    assert call.kwargs["realized_savings"] == 42.5
    assert call.kwargs["realized_savings_currency"] == "usd"
    assert call.kwargs["confidence_rating"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_field", ["run_id", "recommendation_id", "feedback_action"])
async def test_submit_feedback_missing_required_field(missing_field):
    from src.revenium_mcp_server.tools_decomposed.ai_insights_management import (
        AIInsightsManagement,
    )

    from src.revenium_mcp_server.common.error_handling import ToolError
    tool = AIInsightsManagement()
    args = {
        "run_id": "r1",
        "recommendation_id": "rec1",
        "feedback_action": "implemented",
    }
    args.pop(missing_field)
    with pytest.raises(ToolError) as exc:
        await tool.handle_action("submit_feedback", args)
    assert missing_field in exc.value.message.lower() or exc.value.field == missing_field


@pytest.mark.asyncio
async def test_api_error_AI_RECOMMENDATIONS_DISABLED_raises_authorization_tool_error():
    """The disabled state is an authorization failure: it must propagate as a
    raised ToolError (isError:true envelope) carrying the friendly message and
    enablement suggestion, not render as success-shaped content."""
    from src.revenium_mcp_server.client import ReveniumAPIError
    from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError
    from src.revenium_mcp_server.tools_decomposed.ai_insights_management import (
        AIInsightsManagement,
    )

    tool = AIInsightsManagement()
    err = ReveniumAPIError(
        "AI recs disabled", status_code=403, code="AI_RECOMMENDATIONS_DISABLED",
    )
    with patch(
        "src.revenium_mcp_server.client.ReveniumClient.list_investigators",
        side_effect=err,
    ):
        with pytest.raises(ToolError) as exc:
            await tool.handle_action("list_investigators", {})

    assert "not enabled" in exc.value.message.lower()
    assert exc.value.error_code == ErrorCodes.API_AUTHORIZATION
    assert any("enable" in s.lower() for s in exc.value.suggestions)


@pytest.mark.asyncio
async def test_api_error_IDEMPOTENCY_BACKEND_UNAVAILABLE_yields_transient():
    from src.revenium_mcp_server.client import ReveniumAPIError
    from src.revenium_mcp_server.tools_decomposed.ai_insights_management import (
        AIInsightsManagement,
    )

    tool = AIInsightsManagement()
    err = ReveniumAPIError(
        "MemoryDB down", status_code=503, code="IDEMPOTENCY_BACKEND_UNAVAILABLE",
    )
    with patch(
        "src.revenium_mcp_server.client.ReveniumClient.trigger_recommendation_run",
        side_effect=err,
    ):
        result = await tool.handle_action("trigger_run", {
            "period_start": "2026-01-01T00:00:00Z",
            "period_end":   "2026-01-02T00:00:00Z",
        })

    text = result[0].text if hasattr(result[0], "text") else str(result[0])
    assert "retry" in text.lower() or "temporarily" in text.lower()


@pytest.mark.asyncio
async def test_api_error_NOT_FOUND_yields_not_found():
    from src.revenium_mcp_server.client import ReveniumAPIError
    from src.revenium_mcp_server.tools_decomposed.ai_insights_management import (
        AIInsightsManagement,
    )

    tool = AIInsightsManagement()
    err = ReveniumAPIError("run not found", status_code=404, code="NOT_FOUND")
    with patch(
        "src.revenium_mcp_server.client.ReveniumClient.get_recommendation_run",
        side_effect=err,
    ):
        result = await tool.handle_action("get_run", {"run_id": "missing"})

    text = result[0].text if hasattr(result[0], "text") else str(result[0])
    assert "not found" in text.lower()


@pytest.mark.asyncio
async def test_api_error_unknown_code_reraises():
    """A code with no bespoke RFC 7807 translation has no friendly render, so it
    must propagate out of handle_action for FastMCP to mark isError:true rather
    than be buried in success-shaped generic content text."""
    from src.revenium_mcp_server.client import ReveniumAPIError
    from src.revenium_mcp_server.tools_decomposed.ai_insights_management import (
        AIInsightsManagement,
    )

    tool = AIInsightsManagement()
    err = ReveniumAPIError("weird", status_code=500, code="SOMETHING_NEW")
    with patch(
        "src.revenium_mcp_server.client.ReveniumClient.list_investigators",
        side_effect=err,
    ):
        with pytest.raises(ReveniumAPIError) as exc:
            await tool.handle_action("list_investigators", {})

    assert exc.value is err


@pytest.mark.asyncio
async def test_get_supported_actions_lists_all_six_endpoint_actions_and_meta():
    from src.revenium_mcp_server.tools_decomposed.ai_insights_management import (
        AIInsightsManagement,
    )

    tool = AIInsightsManagement()
    actions = await tool._get_supported_actions()
    for needed in (
        "trigger_run", "get_run", "list_runs",
        "submit_feedback", "list_feedback", "list_investigators",
        "get_capabilities", "get_examples", "get_agent_summary",
    ):
        assert needed in actions, f"missing action {needed}"


@pytest.mark.asyncio
async def test_get_capabilities_returns_payload():
    from src.revenium_mcp_server.tools_decomposed.ai_insights_management import (
        AIInsightsManagement,
    )

    tool = AIInsightsManagement()
    result = await tool.handle_action("get_capabilities", {})
    text = result[0].text if hasattr(result[0], "text") else str(result[0])
    assert "ai" in text.lower() or "insights" in text.lower()


@pytest.mark.asyncio
async def test_get_examples_mentions_trigger_run_and_polling():
    from src.revenium_mcp_server.tools_decomposed.ai_insights_management import (
        AIInsightsManagement,
    )

    tool = AIInsightsManagement()
    result = await tool.handle_action("get_examples", {})
    text = result[0].text if hasattr(result[0], "text") else str(result[0])
    assert "trigger_run" in text and "get_run" in text


@pytest.mark.asyncio
async def test_get_agent_summary_is_concise_and_mentions_polling_pattern():
    from src.revenium_mcp_server.tools_decomposed.ai_insights_management import (
        AIInsightsManagement,
    )

    tool = AIInsightsManagement()
    result = await tool.handle_action("get_agent_summary", {})
    text = result[0].text if hasattr(result[0], "text") else str(result[0])
    assert "poll" in text.lower() or "polling" in text.lower()


def test_priority_order_includes_manage_ai_insights():
    from src.revenium_mcp_server.tool_configuration.registry import (
        TOOL_REGISTRATION_PRIORITY_ORDER,
    )
    assert "manage_ai_insights" in TOOL_REGISTRATION_PRIORITY_ORDER


@pytest.mark.asyncio
async def test_auth_failure_reraises_api_error():
    """A generic (auth) ReveniumAPIError with no RFC 7807 translation must
    propagate out of handle_action so FastMCP marks the envelope isError:true,
    not swallow it into generic content text."""
    from src.revenium_mcp_server.client import ReveniumAPIError
    from src.revenium_mcp_server.tools_decomposed.ai_insights_management import (
        AIInsightsManagement,
    )

    tool = AIInsightsManagement()
    err = ReveniumAPIError("Unauthorized", status_code=401)
    with patch(
        "src.revenium_mcp_server.client.ReveniumClient.list_investigators",
        side_effect=err,
    ):
        with pytest.raises(ReveniumAPIError) as exc:
            await tool.handle_action("list_investigators", {})
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_tool_error_propagates():
    """A ToolError raised while handling an action must propagate, not be
    rendered as content text without isError:true."""
    from src.revenium_mcp_server.client import ReveniumAPIError  # noqa: F401
    from src.revenium_mcp_server.common.error_handling import (
        ErrorCodes,
        ToolError,
    )
    from src.revenium_mcp_server.tools_decomposed.ai_insights_management import (
        AIInsightsManagement,
    )

    tool = AIInsightsManagement()
    boom = ToolError(message="unauthorized", error_code=ErrorCodes.API_AUTHORIZATION)
    with patch(
        "src.revenium_mcp_server.client.ReveniumClient.list_investigators",
        side_effect=boom,
    ):
        with pytest.raises(ToolError) as exc:
            await tool.handle_action("list_investigators", {})
    assert exc.value is boom


def test_business_profile_includes_manage_ai_insights():
    from src.revenium_mcp_server.tool_configuration.profiles import (
        PROFILE_DEFINITIONS, PROFILE_TOOL_COUNTS, validate_profile_definitions,
    )
    assert "manage_ai_insights" in PROFILE_DEFINITIONS["business"]
    assert PROFILE_TOOL_COUNTS["business"] == len(PROFILE_DEFINITIONS["business"])
    assert validate_profile_definitions() is True


@pytest.mark.asyncio
async def test_register_single_tool_dispatches_to_ai_insights_handler(monkeypatch):
    """The if/elif chain in _register_single_tool must include manage_ai_insights."""
    from src.revenium_mcp_server.tool_configuration.config import ToolConfig
    from src.revenium_mcp_server.tool_configuration.registry import (
        ToolConfigurationRegistry,
    )

    config = ToolConfig()  # default profile = "business"
    registry = ToolConfigurationRegistry(config)

    called = {}

    async def fake_register_manage_ai_insights(mcp):
        called["yes"] = True

    monkeypatch.setattr(
        registry, "_register_manage_ai_insights",
        fake_register_manage_ai_insights, raising=False,
    )

    from unittest.mock import MagicMock
    await registry._register_single_tool(MagicMock(), "manage_ai_insights")
    assert called.get("yes") is True
