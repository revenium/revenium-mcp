"""BACK-4634: the quick alert actions keep the percentage flag and every recipient, or refuse."""

import ast
import json
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.revenium_mcp_server.common.error_handling import ToolError, format_structured_error
from src.revenium_mcp_server.tool_configuration.config import ToolConfig
from src.revenium_mcp_server.tool_configuration.registry import ToolConfigurationRegistry
from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement
from tests.unit.anomaly_platform_fake import FakeAnomalyPlatform

B = "b@example.com"
C = "c@example.com"
TO_B = {"notificationAddresses": [B], "slackConfigurations": []}


@pytest.fixture(autouse=True)
def no_default_slack_channel():
    with patch("src.revenium_mcp_server.config_store.get_config_value", return_value=None):
        yield


@pytest.fixture
def platform():
    return FakeAnomalyPlatform()


@pytest.fixture
def tools(platform):
    alert_tools = AlertManagement()
    alert_tools.get_client = AsyncMock(return_value=platform)
    alert_tools._post_alert_creation_prompting = AsyncMock(return_value="")
    return alert_tools


def _percent_alert_to_two_people(**extra):
    return {
        "name": "Error rate",
        "metric": "ERROR_RATE",
        "threshold": 5,
        "isPercentage": True,
        "email": B,
        "notificationAddresses": [B, C],
        "period_minutes": 60,
        **extra,
    }


@pytest.mark.asyncio
class TestThresholdAlertKeepsWhatItWasGiven:
    async def test_percentage_and_every_recipient_reach_the_platform(self, tools, platform):
        await tools.handle_action("create_threshold_alert", _percent_alert_to_two_people())

        body = platform.created_bodies[-1]
        assert body["isPercentage"] is True
        assert body["notificationAddresses"] == [B, C]
        assert body["metricType"] == "ERROR_RATE"
        assert body["periodDuration"] == "ONE_HOUR"

    async def test_email_and_addresses_are_unioned_without_duplicates(self, tools, platform):
        await tools.handle_action(
            "create_threshold_alert",
            _percent_alert_to_two_people(email="B@Example.com", notificationAddresses=[B, C, C]),
        )

        assert platform.created_bodies[-1]["notificationAddresses"] == ["B@Example.com", C]

    async def test_confirmation_lists_every_recipient_and_marks_the_percentage(self, tools):
        result = await tools.handle_action("create_threshold_alert", _percent_alert_to_two_people())

        text = result[0].text
        assert "**Threshold:** 5.0% (percentage)" in text
        assert f"**Email Notifications:** {B}, {C}" in text

    async def test_a_list_email_stores_every_address(self, tools, platform):
        await tools.handle_action(
            "create_threshold_alert", {"name": "Cost", "threshold": 100, "email": [B, C]}
        )

        assert platform.created_bodies[-1]["notificationAddresses"] == [B, C]
        assert platform.store["new-1"]["notificationAddresses"] == [B, C]

    async def test_a_non_address_email_is_refused_under_email(self, tools, platform):
        with pytest.raises(ToolError) as refusal:
            await tools.handle_action(
                "create_threshold_alert", {"name": "Cost", "threshold": 100, "email": 123}
            )

        assert refusal.value.field == "email"
        assert platform.created_bodies == []

    async def test_absolute_threshold_stays_absolute(self, tools, platform):
        await tools.handle_action(
            "create_threshold_alert", {"name": "Cost", "threshold": 100, "email": B}
        )

        assert platform.created_bodies[-1]["isPercentage"] is False
        assert platform.created_bodies[-1]["notificationAddresses"] == [B]

    async def test_metric_type_spelling_is_honoured(self, tools, platform):
        await tools.handle_action(
            "create_threshold_alert",
            {"name": "Errors", "threshold": 5, "email": B, "metricType": "ERROR_RATE"},
        )

        assert platform.created_bodies[-1]["metricType"] == "ERROR_RATE"

    @pytest.mark.parametrize(
        "extra",
        [
            {"period": "weekly"},
            {"periodDuration": "DAILY"},
            {"description": "kept nowhere"},
            {"enabled": False},
            {"slackConfigurations": ["abc"]},
            {"anomaly_data": {"name": "x"}},
            {"dry_run": True},
        ],
    )
    async def test_an_argument_it_cannot_apply_is_refused_before_anything_is_created(
        self, tools, platform, extra
    ):
        with pytest.raises(ToolError) as refusal:
            await tools.handle_action("create_threshold_alert", _percent_alert_to_two_people(**extra))

        assert next(iter(extra)) in str(refusal.value)
        assert platform.created_bodies == []

    async def test_a_switched_off_dry_run_is_not_refused(self, tools, platform):
        await tools.handle_action(
            "create_threshold_alert", _percent_alert_to_two_people(dry_run=False)
        )

        assert len(platform.created_bodies) == 1

    async def test_a_non_boolean_percentage_flag_is_refused(self, tools, platform):
        with pytest.raises(ToolError, match="isPercentage"):
            await tools.handle_action(
                "create_threshold_alert", _percent_alert_to_two_people(isPercentage="sometimes")
            )

        assert platform.created_bodies == []

    async def test_malformed_addresses_are_refused(self, tools, platform):
        with pytest.raises(ToolError, match="notificationAddresses"):
            await tools.handle_action(
                "create_threshold_alert", _percent_alert_to_two_people(notificationAddresses=[1, 2])
            )

        assert platform.created_bodies == []


@pytest.mark.asyncio
class TestTheOtherQuickActionsFollowTheSameRule:
    async def test_cumulative_usage_alert_keeps_the_flag_and_recipients(self, tools, platform):
        await tools.handle_action(
            "create_cumulative_usage_alert",
            {
                "name": "Budget",
                "threshold": 80,
                "isPercentage": True,
                "period": "monthly",
                "email": B,
                "notificationAddresses": [C],
            },
        )

        body = platform.created_bodies[-1]
        assert body["isPercentage"] is True
        assert body["notificationAddresses"] == [B, C]
        assert "threshold: 80%" in body["description"]

    async def test_cumulative_usage_alert_refuses_what_it_cannot_apply(self, tools, platform):
        with pytest.raises(ToolError, match="filters"):
            await tools.handle_action(
                "create_cumulative_usage_alert",
                {"name": "Budget", "threshold": 80, "email": B, "filters": {"x": 1}},
            )

        assert platform.created_bodies == []

    async def test_simple_alert_keeps_the_flag_and_recipients(self, tools, platform):
        await tools.handle_action(
            "create_simple",
            {"name": "Simple", "threshold": 5, "isPercentage": True, "notificationAddresses": [B, C]},
        )

        body = platform.created_bodies[-1]
        assert body["isPercentage"] is True
        assert body["notificationAddresses"] == [B, C]

    def test_text_with_a_percent_sign_is_a_percentage_threshold(self, tools):
        parsed = tools._simple_parse_alert_text(
            "Alert me when error rate exceeds 5% per hour", TO_B
        )

        assert parsed["threshold"] == 5.0
        assert parsed["isPercentage"] is True

    def test_text_without_a_percent_sign_is_an_absolute_threshold(self, tools):
        parsed = tools._simple_parse_alert_text(
            "Alert me when cost exceeds 500 per hour", TO_B
        )

        assert parsed["isPercentage"] is False


@pytest.mark.asyncio
async def test_a_bagged_percentage_string_reaches_the_handler_as_a_boolean():
    registry = ToolConfigurationRegistry(tool_config=ToolConfig.create_for_testing())
    mcp = MagicMock()
    await registry._register_manage_alerts(mcp)
    closure = mcp.tool.call_args_list[0][0][0].__wrapped__

    with patch(
        "src.revenium_mcp_server.common.tool_execution.standardized_tool_execution",
        new=AsyncMock(return_value=[]),
    ) as execution:
        await closure(action="create_threshold_alert", params={"isPercentage": "true"})

    assert execution.await_args.kwargs["arguments"]["isPercentage"] is True


@pytest.mark.asyncio
async def test_a_percentage_in_plain_text_reaches_the_platform_as_a_percentage(tools, platform):
    await tools.handle_action(
        "create_from_text", {"text": "Alert me when error rate exceeds 5% per hour", "email": B}
    )

    body = platform.created_bodies[-1]
    assert body["threshold"] == 5.0
    assert body["isPercentage"] is True


@pytest.mark.asyncio
async def test_an_absolute_amount_in_plain_text_stays_absolute(tools, platform):
    await tools.handle_action(
        "create_from_text", {"text": "Alert me when total cost exceeds 500 per hour", "email": B}
    )

    body = platform.created_bodies[-1]
    assert body["threshold"] == 500.0
    assert body["isPercentage"] is False


ALERT_TOOL_SOURCES = (
    "src/revenium_mcp_server/tools_decomposed/alert_management.py",
    "src/revenium_mcp_server/alerts/anomaly_manager.py",
    "src/revenium_mcp_server/error_handlers.py",
)
PERIOD_MINUTES = re.compile(r"""period_minutes["']?\s*[=:]\s*(\d+)""")
EVERY_MINUTES = re.compile(r"every (\d+) minutes")
SHORT_PERIOD_DURATION = re.compile(r"periodDuration[^A-Z]*'?(ONE_MINUTE|FIVE_MINUTES|TEN_MINUTES)")


def _string_constants(path):
    with open(path, encoding="utf-8") as source:
        tree = ast.parse(source.read())
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


async def _published_text(tools):
    """Everything the alert tool tells a caller: answers, schema, metadata and its string constants."""
    texts = []
    for alert_type in (None, "budget_threshold", "threshold", "relative_change", "update"):
        texts.append((await tools.handle_action("get_examples", {"alert_type": alert_type}))[0].text)
    for action in ("get_capabilities", "get_agent_summary"):
        texts.append((await tools.handle_action(action, {}))[0].text)
    for capability in await tools._get_tool_capabilities():
        texts.append(json.dumps(capability.parameters))
        texts.extend(capability.examples)
    texts.append(json.dumps(await tools._get_input_schema()))
    for refused in ({}, {"resource_type": "alerts"}):
        with pytest.raises(ToolError) as refusal:
            await tools.handle_action("create", refused)
        texts.append(format_structured_error(refusal.value))
    for path in ALERT_TOOL_SOURCES:
        texts.extend(_string_constants(path))
    return texts


def _threshold_alert_calls(text):
    """Each create_threshold_alert(...) example in the text whose arguments are literals.

    A bare create_threshold_alert() names the action rather than giving an example.
    """
    calls = []
    start = text.find("create_threshold_alert(")
    while start != -1:
        depth, end = 0, start
        for end in range(text.index("(", start), len(text)):
            depth += {"(": 1, ")": -1}.get(text[end], 0)
            if depth == 0:
                break
        try:
            call = ast.parse(text[start:end + 1], mode="eval").body
            if isinstance(call, ast.Call) and call.keywords and not call.args:
                calls.append({kw.arg: ast.literal_eval(kw.value) for kw in call.keywords})
        except (SyntaxError, ValueError):
            pass
        start = text.find("create_threshold_alert(", end)
    return calls


@pytest.mark.asyncio
class TestPublishedThresholdPeriodsAreAccepted:
    async def test_every_published_threshold_period_creates_an_alert(self, tools, platform):
        texts = await _published_text(tools)
        joined = "\n".join(texts)

        periods = {int(value) for value in PERIOD_MINUTES.findall(joined)}
        assert periods, "the tool publishes no period_minutes example"
        assert [m for m in EVERY_MINUTES.findall(joined) if int(m) < 15] == []
        assert SHORT_PERIOD_DURATION.findall(joined) == []

        for minutes in sorted(periods):
            await tools.handle_action(
                "create_threshold_alert",
                {"name": "Spike check", "threshold": 100, "period_minutes": minutes, "email": B},
            )
        assert len(platform.created_bodies) == len(periods)

        examples = [call for text in texts for call in _threshold_alert_calls(text)]
        assert any("period_minutes" in example for example in examples)
        for example in examples:
            await tools.handle_action("create_threshold_alert", {"email": B, **example})
        assert len(platform.created_bodies) == len(periods) + len(examples)

    async def test_the_documented_default_period_is_the_one_used(self, tools, platform):
        schema = await tools._get_input_schema()
        assert "(default: 15)" in schema["properties"]["period_minutes"]["description"]
        assert "Sub-fifteen-minute" not in schema["properties"]["periodDuration"]["description"]

        await tools.handle_action(
            "create_threshold_alert", {"name": "Spike check", "threshold": 100, "email": B}
        )

        assert platform.created_bodies[-1]["periodDuration"] == "FIFTEEN_MINUTES"


@pytest.mark.asyncio
async def test_confirmation_prints_a_cost_threshold_in_dollars(tools):
    result = await tools.handle_action(
        "create_cumulative_usage_alert",
        {"name": "Monthly Budget", "threshold": 6321.87, "period": "monthly", "email": B},
    )

    assert "**Threshold:** $6,321.87" in result[0].text


def _percent_increase_rule(**extra):
    return {
        "anomaly_data": {
            "name": "Spend jumps",
            "alertType": "RELATIVE_CHANGE",
            "metricType": "TOTAL_COST",
            "operatorType": "PERCENT_INCREASE",
            "threshold": 20,
            "periodDuration": "WEEKLY",
            "notificationAddresses": [B],
            **extra,
        }
    }


@pytest.mark.asyncio
async def test_confirmation_names_a_percent_increase_in_words(tools, platform):
    result = await tools.handle_action("create", _percent_increase_rule(isPercentage=True))

    assert "**Operator:** increases by (PERCENT_INCREASE)" in result[0].text


@pytest.mark.asyncio
async def test_confirmation_of_a_percent_increase_without_the_flag_reads_as_percent(
    tools, platform
):
    result = await tools.handle_action("create", _percent_increase_rule())

    text = result[0].text
    assert not platform.created_bodies[-1].get("isPercentage")
    assert "% (percentage)" in text
    assert "$" not in text
