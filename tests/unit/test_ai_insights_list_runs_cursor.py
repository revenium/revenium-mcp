"""get_ai_insights list_runs resumes from a cursor and hands one back (BACK-5152)."""

from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest
from unittest.mock import AsyncMock, patch

from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.tools_decomposed.ai_insights_management import (
    AIInsightsManagement,
)

RUN_COUNT = 15
FIRST_CREATED = datetime(2026, 10, 9, 1, 23, 53, tzinfo=timezone.utc)


def _created(index: int) -> str:
    instant = FIRST_CREATED - timedelta(hours=index)
    return instant.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _runs(count: int) -> List[Dict[str, Any]]:
    return [
        {"runId": f"run-{index:04d}", "created": _created(index)}
        for index in range(count)
    ]


RUNS = _runs(RUN_COUNT)


def _platform_cursor(run: Dict[str, Any]) -> str:
    payload = json.dumps({"created": run["created"], "id": run["runId"]})
    return base64.b64encode(payload.encode()).decode()


def _platform_position(runs: List[Dict[str, Any]], cursor: Optional[str]) -> int:
    """The platform restarts from the newest run when it cannot read a cursor."""
    if not cursor:
        return 0
    try:
        decoded = json.loads(base64.b64decode(cursor))
        return (
            next(i for i, run in enumerate(runs) if run["runId"] == decoded["id"]) + 1
        )
    except Exception:
        return 0


class FakeRunsPlatform:
    """Keyset-paged GET /api/v2/insights/runs, newest first."""

    def __init__(self, runs: List[Dict[str, Any]] = RUNS) -> None:
        self.runs = runs
        self.cursors_received: List[Optional[str]] = []

    async def list_recommendation_runs(
        self, *, limit: int, cursor: Optional[str] = None, **_filters: Any
    ) -> Dict[str, Any]:
        self.cursors_received.append(cursor)
        start = _platform_position(self.runs, cursor)
        page = self.runs[start : start + limit]
        more = start + limit < len(self.runs)
        return {
            "data": page,
            "next_cursor": _platform_cursor(page[-1]) if more and page else None,
        }


def _result_of(response: List[Any]) -> Dict[str, Any]:
    text = response[0].text
    match = re.search(r"```json\n(.*?)\n```", text, re.DOTALL)
    assert match, text
    return json.loads(match.group(1))["result"]


async def _list_runs(
    platform: FakeRunsPlatform, arguments: Dict[str, Any]
) -> Dict[str, Any]:
    tool = AIInsightsManagement()
    with patch.object(tool, "get_client", new=AsyncMock(return_value=platform)):
        return _result_of(await tool.handle_action("list_runs", arguments))


def _run_ids(result: Dict[str, Any]) -> List[str]:
    return [run["runId"] for run in result["runs"]]


async def _registered_insights_server():
    from fastmcp import FastMCP

    from src.revenium_mcp_server.tool_configuration.config import ToolConfig
    from src.revenium_mcp_server.tool_configuration.registry import (
        ToolConfigurationRegistry,
    )

    mcp = FastMCP("back-5152")
    registry = ToolConfigurationRegistry(
        tool_config=ToolConfig.create_for_testing(profile="business")
    )
    await registry._register_manage_ai_insights(mcp)
    return mcp


class TestListRunsContinuation:
    @pytest.mark.asyncio
    async def test_a_budget_stop_returns_the_next_cursor(self):
        result = await _list_runs(FakeRunsPlatform(), {"max_results": 5})

        assert _run_ids(result) == [run["runId"] for run in RUNS[:5]]
        assert result["next_cursor"] == _platform_cursor(RUNS[4])

    @pytest.mark.asyncio
    async def test_the_next_cursor_reaches_every_run_once(self):
        platform = FakeRunsPlatform()
        seen: List[str] = []
        arguments: Dict[str, Any] = {"max_results": 5}
        for _ in range(RUN_COUNT):
            result = await _list_runs(platform, arguments)
            seen.extend(_run_ids(result))
            if "next_cursor" not in result:
                break
            arguments = {"max_results": 5, "cursor": result["next_cursor"]}

        assert seen == [run["runId"] for run in RUNS]

    @pytest.mark.asyncio
    async def test_a_cursor_from_the_hard_cap_resumes_after_many_platform_pages(self):
        runs = _runs(AIInsightsManagement.HARD_CAP_MAX_RESULTS + 205)
        platform = FakeRunsPlatform(runs)
        cap = {"max_results": AIInsightsManagement.HARD_CAP_MAX_RESULTS}

        first = await _list_runs(platform, cap)
        second = await _list_runs(platform, {**cap, "cursor": first["next_cursor"]})

        assert _run_ids(first) + _run_ids(second) == [run["runId"] for run in runs]
        assert "next_cursor" not in second

    @pytest.mark.asyncio
    async def test_the_supplied_cursor_is_sent_on_the_first_request(self):
        platform = FakeRunsPlatform()
        cursor = _platform_cursor(RUNS[4])

        result = await _list_runs(platform, {"max_results": 5, "cursor": cursor})

        assert platform.cursors_received[0] == cursor
        assert _run_ids(result) == [run["runId"] for run in RUNS[5:10]]

    @pytest.mark.asyncio
    async def test_the_last_page_has_no_next_cursor(self):
        result = await _list_runs(FakeRunsPlatform(), {"max_results": RUN_COUNT})

        assert result["count"] == RUN_COUNT
        assert "next_cursor" not in result

    @pytest.mark.asyncio
    async def test_a_cursor_past_the_last_run_is_the_end_of_the_results(self):
        result = await _list_runs(
            FakeRunsPlatform(), {"max_results": 5, "cursor": _platform_cursor(RUNS[-1])}
        )

        assert result["runs"] == []
        assert result["end_of_results"] is True


class TestUnreadableCursorIsRefused:
    @pytest.mark.parametrize(
        "cursor",
        [
            "bogus-cursor-xyz",
            "",
            "   ",
            base64.b64encode(b"not json").decode(),
            base64.b64encode(b'{"created": "yesterday", "id": "run-01"}').decode(),
            base64.b64encode(
                b'{"created": "2026-10-09T01:23:53.424Z", "id": ""}'
            ).decode(),
            base64.b64encode(b'["2026-10-09T01:23:53.424Z", "run-01"]').decode(),
            42,
        ],
    )
    @pytest.mark.asyncio
    async def test_a_cursor_the_platform_would_restart_from_is_refused_before_any_read(
        self, cursor
    ):
        platform = FakeRunsPlatform()

        with pytest.raises(ToolError) as refusal:
            await _list_runs(platform, {"max_results": 5, "cursor": cursor})

        assert platform.cursors_received == []
        assert refusal.value.field == "cursor"
        assert "next_cursor" in refusal.value.message

    @pytest.mark.asyncio
    async def test_the_refusal_reaches_the_caller_with_the_error_flag(
        self, monkeypatch
    ):
        from fastmcp import Client

        mcp = await _registered_insights_server()
        with patch.object(
            AIInsightsManagement,
            "get_client",
            new=AsyncMock(return_value=FakeRunsPlatform()),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "get_ai_insights",
                    {"action": "list_runs", "params": {"cursor": "bogus-cursor-xyz"}},
                    raise_on_error=False,
                )

        assert result.is_error
        assert "is not a list_runs next_cursor" in result.content[0].text


class TestOverCapAdvice:
    @pytest.mark.asyncio
    async def test_the_over_cap_refusal_points_at_the_cursor(self):
        with pytest.raises(ToolError) as refusal:
            await _list_runs(FakeRunsPlatform(), {"max_results": 1001})

        advice = " ".join(refusal.value.suggestions or [])
        assert "next_cursor" in advice

    @pytest.mark.asyncio
    async def test_the_list_feedback_over_cap_refusal_offers_no_cursor(self):
        tool = AIInsightsManagement()
        with pytest.raises(ToolError) as refusal:
            await tool.handle_action(
                "list_feedback", {"run_id": "run-0001", "max_results": 1001}
            )

        assert refusal.value.suggestions == [
            f"Pass an integer between 1 and {AIInsightsManagement.HARD_CAP_MAX_RESULTS}"
        ]


class TestHelpNamesTheCursor:
    @pytest.mark.asyncio
    async def test_the_list_runs_example_says_how_to_continue(self):
        examples = _result_of(
            await AIInsightsManagement().handle_action("get_examples", {})
        )

        assert "pass it back unchanged as `cursor`" in examples["examples_markdown"]
