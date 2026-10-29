"""BACK-5128 / BACK-5153: every alert write refuses a negative threshold, and a rule query or list searches by name."""

from unittest.mock import AsyncMock

import pytest

from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement
from tests.unit.anomaly_platform_fake import FakeAnomalyPlatform, threshold_alert

NEGATIVE_THRESHOLD_REFUSAL = "Invalid threshold value: -1; use a number, zero or more"
RECIPIENT = "ops@example.com"


def _tools_over(platform: FakeAnomalyPlatform) -> AlertManagement:
    tools = AlertManagement()
    tools.get_client = AsyncMock(return_value=platform)
    return tools


@pytest.fixture
def platform():
    return FakeAnomalyPlatform(
        [
            threshold_alert("a1", name="mcp-test-alert-target"),
            threshold_alert("a2", name="Nightly budget"),
            threshold_alert("a3", name="Cost spike"),
        ]
    )


@pytest.fixture
def tools(platform):
    return _tools_over(platform)


async def _refusal(call) -> str:
    with pytest.raises(ToolError) as exc_info:
        await call
    return str(exc_info.value)


def _advanced_create(threshold, **extra):
    return {
        "resource_type": "anomalies",
        "anomaly_data": {
            "name": "mcp-test-negative",
            "alertType": "THRESHOLD",
            "metricType": "TOTAL_COST",
            "threshold": threshold,
            "notificationAddresses": [RECIPIENT],
        },
        **extra,
    }


class TestNegativeThresholdIsRefusedOnEveryWrite:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("dry_run", [False, True])
    @pytest.mark.parametrize(
        "update",
        [
            {"anomaly_data": {"threshold": -1}},
            {"threshold": -1},
            {"anomaly_data": {"threshold": "-1"}},
        ],
        ids=["anomaly_data", "flat", "numeric-string"],
    )
    async def test_update_refuses_a_negative_threshold(
        self, tools, platform, update, dry_run
    ):
        message = await _refusal(
            tools.handle_action(
                "update", {"anomaly_id": "a1", "dry_run": dry_run, **update}
            )
        )

        assert "Invalid threshold value" in message
        assert "use a number, zero or more" in message
        assert platform.updated_bodies == []
        assert platform.store["a1"]["threshold"] == 100.0

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "action, extra",
        [("create", {}), ("create", {"dry_run": True}), ("validate", {})],
    )
    async def test_advanced_create_refuses_a_negative_threshold(
        self, tools, platform, action, extra
    ):
        message = await _refusal(
            tools.handle_action(action, _advanced_create(-1, **extra))
        )

        assert NEGATIVE_THRESHOLD_REFUSAL in message
        assert platform.created_bodies == []

    @pytest.mark.asyncio
    async def test_detection_rules_create_refuses_a_negative_threshold(
        self, tools, platform
    ):
        arguments = {
            "resource_type": "anomalies",
            "anomaly_data": {
                "name": "mcp-test-negative-rules",
                "detection_rules": [
                    {
                        "rule_type": "THRESHOLD",
                        "metric": "total_cost",
                        "operator": ">",
                        "value": -1,
                        "time_window": "1h",
                    }
                ],
                "notificationAddresses": [RECIPIENT],
            },
        }

        message = await _refusal(tools.handle_action("create", arguments))

        assert NEGATIVE_THRESHOLD_REFUSAL in message
        assert platform.created_bodies == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "convenience_value", [-1, -1.0, "-1"], ids=["int", "float", "string"]
    )
    @pytest.mark.parametrize("update_value", [-1, -1.0], ids=["int", "float"])
    @pytest.mark.parametrize(
        "convenience_action, convenience_arguments",
        [
            ("create_threshold_alert", {}),
            ("create_cumulative_usage_alert", {"period": "monthly"}),
        ],
    )
    async def test_the_refusal_reads_as_create_threshold_alert_reads(
        self,
        tools,
        convenience_action,
        convenience_arguments,
        convenience_value,
        update_value,
    ):
        convenience = await _refusal(
            tools.handle_action(
                convenience_action,
                {
                    "name": "mcp-test-negative",
                    "threshold": convenience_value,
                    "email": RECIPIENT,
                    **convenience_arguments,
                },
            )
        )
        update = await _refusal(
            tools.handle_action(
                "update", {"anomaly_id": "a1", "threshold": update_value}
            )
        )
        create = await _refusal(
            tools.handle_action("create", _advanced_create(update_value))
        )

        assert (
            convenience.splitlines()[0]
            == update.splitlines()[0]
            == create.splitlines()[0]
        )
        assert NEGATIVE_THRESHOLD_REFUSAL in update

    @pytest.mark.asyncio
    async def test_a_fractional_threshold_is_named_as_sent(self, tools):
        message = await _refusal(
            tools.handle_action("update", {"anomaly_id": "a1", "threshold": -0.5})
        )

        assert "Invalid threshold value: -0.5; use a number, zero or more" in message

    @pytest.mark.asyncio
    async def test_a_zero_threshold_is_still_accepted(self, tools, platform):
        await tools.handle_action("update", {"anomaly_id": "a1", "threshold": 0})
        await tools.handle_action("create", _advanced_create(0))

        assert platform.store["a1"]["threshold"] == 0
        assert platform.created_bodies[-1]["threshold"] == 0


class TestRuleQueryAppliesItsText:
    @pytest.mark.asyncio
    async def test_query_on_rules_returns_only_the_rules_the_text_names(
        self, tools, platform
    ):
        result = await tools.handle_action(
            "query", {"resource_type": "anomalies", "query": "MCP-TEST-ALERT"}
        )
        text = result[0].text

        assert platform.list_filters[-1]["query"] == "MCP-TEST-ALERT"
        assert "Found 1 anomalies" in text
        assert "mcp-test-alert-target" in text
        assert "Nightly budget" not in text
        assert "Cost spike" not in text

    @pytest.mark.asyncio
    async def test_query_matches_list_with_the_same_name_filter(self, tools):
        queried = await tools.handle_action(
            "query", {"resource_type": "anomalies", "query": "budget"}
        )
        listed = await tools.handle_action(
            "list", {"resource_type": "anomalies", "filters": {"query": "budget"}}
        )

        assert queried[0].text == listed[0].text

    @pytest.mark.asyncio
    async def test_query_with_the_same_text_in_filters_is_one_search(
        self, tools, platform
    ):
        await tools.handle_action(
            "query",
            {
                "resource_type": "anomalies",
                "query": "budget",
                "filters": {"query": "budget"},
            },
        )

        assert platform.list_filters[-1] == {"query": "budget"}

    @pytest.mark.asyncio
    async def test_query_text_that_disagrees_with_filters_query_is_refused(
        self, tools, platform
    ):
        message = await _refusal(
            tools.handle_action(
                "query",
                {
                    "resource_type": "anomalies",
                    "query": "budget",
                    "filters": {"query": "spike"},
                },
            )
        )

        assert "query" in message
        assert "filters.query" in message
        assert platform.list_filters == []

    @pytest.mark.asyncio
    async def test_query_without_text_still_lists_every_rule(self, tools, platform):
        result = await tools.handle_action("query", {"resource_type": "anomalies"})

        assert "query" not in platform.list_filters[-1]
        assert "Found 3 anomalies" in result[0].text


class TestRuleListAppliesItsQueryText:
    @pytest.mark.asyncio
    async def test_list_on_rules_returns_only_the_rules_the_text_names(
        self, tools, platform
    ):
        result = await tools.handle_action(
            "list", {"resource_type": "anomalies", "query": "MCP-TEST-ALERT"}
        )
        text = result[0].text

        assert platform.list_filters[-1]["query"] == "MCP-TEST-ALERT"
        assert "Found 1 anomalies" in text
        assert "mcp-test-alert-target" in text
        assert "Nightly budget" not in text
        assert "Cost spike" not in text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("text", ["budget", "no-rule-has-this-name"])
    async def test_list_answers_as_query_answers_for_the_same_text(self, tools, text):
        queried = await tools.handle_action(
            "query", {"resource_type": "anomalies", "query": text}
        )
        listed = await tools.handle_action(
            "list", {"resource_type": "anomalies", "query": text}
        )

        assert listed[0].text == queried[0].text

    @pytest.mark.asyncio
    async def test_a_no_match_list_says_no_rule_matches(self, tools):
        result = await tools.handle_action(
            "list", {"resource_type": "anomalies", "query": "no-rule-has-this-name"}
        )

        assert "No anomalies match your criteria" in result[0].text
        assert "Found" not in result[0].text

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "question", ["show my active alert rules", "list monitoring rules", "budget"]
    )
    async def test_a_routed_list_reads_the_text_as_a_question_and_lists_every_rule(
        self, tools, platform, question
    ):
        result = await tools.handle_action("list", {"query": question})

        assert "query" not in platform.list_filters[-1]
        assert "Found 3 anomalies" in result[0].text

    @pytest.mark.asyncio
    async def test_a_routed_list_still_applies_filters_query(self, tools, platform):
        result = await tools.handle_action(
            "list", {"query": "show my rules", "filters": {"query": "budget"}}
        )

        assert platform.list_filters[-1] == {"query": "budget"}
        assert "Found 1 anomalies" in result[0].text

    @pytest.mark.asyncio
    async def test_list_with_the_same_text_in_filters_is_one_search(
        self, tools, platform
    ):
        await tools.handle_action(
            "list",
            {
                "resource_type": "anomalies",
                "query": "budget",
                "filters": {"query": "budget"},
            },
        )

        assert platform.list_filters[-1] == {"query": "budget"}

    @pytest.mark.asyncio
    async def test_list_text_that_disagrees_with_filters_query_is_refused_as_query_refuses(
        self, tools, platform
    ):
        conflicting = {
            "resource_type": "anomalies",
            "query": "budget",
            "filters": {"query": "spike"},
        }

        listed = await _refusal(tools.handle_action("list", conflicting))
        queried = await _refusal(tools.handle_action("query", conflicting))

        assert listed == queried
        assert "filters.query" in listed
        assert platform.list_filters == []

    @pytest.mark.asyncio
    async def test_list_without_text_still_lists_every_rule(self, tools, platform):
        result = await tools.handle_action("list", {"resource_type": "anomalies"})

        assert "query" not in platform.list_filters[-1]
        assert "Found 3 anomalies" in result[0].text
