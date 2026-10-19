"""BACK-4704: alert metric and window names are ones the platform's alert contract accepts."""

import inspect
import json
import re
from pathlib import Path
from typing import Optional, Set
from unittest.mock import AsyncMock, patch

import pytest

from src.revenium_mcp_server.alerts import anomaly_manager
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.tools_decomposed import alert_management
from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement
from src.revenium_mcp_server.validators import InputValidator
from tests.unit.anomaly_platform_fake import FakeAnomalyPlatform
from tests.unit.test_tool_config_registry_m4 import _call_through_the_boundary

REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = REPO_ROOT / "specs" / "openapi" / "hypercurrent.json"
OWNER = "owner@example.com"
PER_TRANSACTION_COMMAND = REPO_ROOT / ".claude" / "commands" / "rm-alert-per-transaction.md"
FENCED_JSON = re.compile(r"```json\n(.*?)\n```", re.DOTALL)

METRICS_KNOWN_BEFORE_THE_FIX = [
    "total_cost",
    "cost_per_transaction",
    "tokens_per_second",
    "requests_per_second",
    "token_count",
    "input_token_count",
    "output_token_count",
    "cached_token_count",
    "error_rate",
    "error_count",
    "tokens_per_minute",
    "requests_per_minute",
]
WINDOWS_KNOWN_BEFORE_THE_FIX = [
    "1m", "5m", "10m", "15m", "30m", "1h", "2h", "4h", "8h", "12h", "1d",
    "daily", "weekly", "monthly", "quarterly", "24h", "7d", "30d", None,
]
REFUSED_FOR_A_THRESHOLD_RULE = {"ONE_MINUTE", "FIVE_MINUTES", "TEN_MINUTES"}
# The published contract also lists TWENTY_FOUR_HOURS and SEVEN_DAYS, yet the platform's
# tracking-period check in AIAnomalyService refuses both with HTTP 404 (seen live on dev).
PERIODS_THE_PLATFORM_ACCEPTS = {
    "FIFTEEN_MINUTES", "THIRTY_MINUTES", "ONE_HOUR", "TWELVE_HOURS",
    "DAILY", "WEEKLY", "MONTHLY", "QUARTERLY", "THIRTY_DAYS",
}
ACCEPTED_THRESHOLD_WINDOWS = ["15m", "30m", "1h", "12h", "24h", "1d", "7d", "30d"]
PERIOD_MINUTES_THE_THRESHOLD_ACTION_ACCEPTS = {15, 30, 60, 720, 1440}
PERIOD_MINUTES_EXAMPLE = re.compile(r"period_minutes\s*=\s*(\d+)")
# Left as it is until the sibling pull request for BACK-4701 merges: it edits the line above it.
DEFERRED_EXAMPLE_LINES = frozenset(
    {'create_threshold_alert(name="Cost Spike", threshold=100, period_minutes=5)'}
)


def _contract_enum(field: str, snapshot: Path = SNAPSHOT) -> Set[str]:
    """The ``AIAnomalyResource_Write`` enum for ``field`` as the committed snapshot declares it."""
    if snapshot == SNAPSHOT and not snapshot.exists():
        pytest.skip(
            "specs/openapi/ is internal-only and not part of the public export "
            "(see public-allowlist-mcp.txt); the contract checks run in the internal repo"
        )
    spec = json.loads(snapshot.read_text())
    write_schema = spec["components"]["schemas"]["AIAnomalyResource_Write"]
    return set(write_schema["properties"][field]["enum"])


def _rule(metric: str = "total_cost", window: Optional[str] = "15m", **extra):
    rule = {"rule_type": "THRESHOLD", "metric": metric, "operator": ">", "value": 5}
    if window is not None:
        rule["time_window"] = window
    rule.update(extra)
    return {"name": "Contract check", "detection_rules": [rule]}


@pytest.fixture(autouse=True)
def no_default_slack_channel():
    with patch("src.revenium_mcp_server.config_store.get_config_value", return_value=None):
        yield


@pytest.fixture
def owner_email():
    with patch(
        "src.revenium_mcp_server.tools_decomposed.alert_management.default_notification_email",
        return_value=OWNER,
    ), patch(
        "src.revenium_mcp_server.alerts.semantic_processor.default_notification_email",
        return_value=OWNER,
    ):
        yield OWNER


@pytest.fixture
def platform():
    return FakeAnomalyPlatform()


@pytest.fixture
def tools(platform):
    alert_tools = AlertManagement()
    alert_tools.get_client = AsyncMock(return_value=platform)
    alert_tools._post_alert_creation_prompting = AsyncMock(return_value="")
    return alert_tools


class TestDetectionRulesConvertToContractNames:
    @pytest.mark.parametrize(
        "metric, window",
        [(metric, "15m") for metric in METRICS_KNOWN_BEFORE_THE_FIX]
        + [("total_cost", window) for window in WINDOWS_KNOWN_BEFORE_THE_FIX],
    )
    def test_every_converted_name_is_one_the_platform_contract_lists(self, metric, window):
        metrics = _contract_enum("metricType")
        periods = _contract_enum("periodDuration")

        try:
            converted = InputValidator.convert_to_api_format(_rule(metric, window))
        except ToolError:
            return

        assert converted["metricType"] in metrics
        assert converted["periodDuration"] in periods
        assert converted["periodDuration"] in PERIODS_THE_PLATFORM_ACCEPTS
        assert converted["periodDuration"] not in REFUSED_FOR_A_THRESHOLD_RULE

    @pytest.mark.parametrize(
        "window, expected", [("24h", "DAILY"), ("1d", "DAILY"), ("7d", "WEEKLY"), ("30d", "THIRTY_DAYS")]
    )
    def test_day_and_week_windows_convert_to_periods_the_platform_accepts(self, window, expected):
        converted = InputValidator.convert_to_api_format(_rule(window=window))

        assert converted["periodDuration"] == expected

    def test_the_unknown_window_refusal_message_names_every_accepted_window(self):
        with pytest.raises(ToolError) as refusal:
            InputValidator.convert_to_api_format(_rule(window="2h"))

        assert f"accepted: {', '.join(ACCEPTED_THRESHOLD_WINDOWS)}" in str(refusal.value)

    @pytest.mark.parametrize(
        "metric, expected",
        [("tokens_per_minute", "TOKENS_PER_MINUTE"), ("requests_per_minute", "REQUESTS_PER_MINUTE")],
    )
    def test_per_minute_throughput_metrics_convert(self, metric, expected):
        converted = InputValidator.convert_to_api_format(_rule(metric))

        assert converted["metricType"] == expected

    def test_a_threshold_rule_without_a_window_gets_fifteen_minutes(self):
        converted = InputValidator.convert_to_api_format(_rule(window=None))

        assert converted["periodDuration"] == "FIFTEEN_MINUTES"

    @pytest.mark.parametrize("window", ["1m", "5m", "10m"])
    def test_a_window_under_fifteen_minutes_is_refused_for_a_threshold_rule(self, window):
        with pytest.raises(ToolError) as refusal:
            InputValidator.convert_to_api_format(_rule(window=window))

        assert "FIFTEEN_MINUTES" in str(refusal.value)

    @pytest.mark.parametrize(
        "metric, per_minute",
        [("tokens_per_second", "tokens_per_minute"), ("requests_per_second", "requests_per_minute")],
    )
    def test_a_per_second_metric_is_refused_naming_the_per_minute_one(self, metric, per_minute):
        with pytest.raises(ToolError) as refusal:
            InputValidator.convert_to_api_format(_rule(metric))

        assert per_minute in str(refusal.value)


@pytest.mark.asyncio
@pytest.mark.usefixtures("owner_email")
class TestTheCreateActionSendsOnlyContractNames:
    async def test_detection_rules_with_a_five_minute_window_create_nothing(self, tools, platform):
        with pytest.raises(ToolError) as refusal:
            await tools.handle_action("create", {"anomaly_data": _rule(window="5m")})

        assert "FIFTEEN_MINUTES" in str(refusal.value)
        assert platform.created_bodies == []

    async def test_an_unknown_window_is_refused_and_nothing_is_created(self, tools, platform):
        with pytest.raises(ToolError) as refusal:
            await tools.handle_action("create", {"anomaly_data": _rule(window="2h")})

        assert "2h" in str(refusal.value)
        assert platform.created_bodies == []

    async def test_a_detection_rules_dry_run_refuses_what_the_live_create_refuses(
        self, tools, platform
    ):
        with pytest.raises(ToolError) as previewed:
            await tools.handle_action(
                "create", {"anomaly_data": _rule(window="2h"), "dry_run": True}
            )
        with pytest.raises(ToolError) as created:
            await tools.handle_action("create", {"anomaly_data": _rule(window="2h")})

        assert previewed.value.message == created.value.message
        assert "2h" in previewed.value.message
        assert platform.created_bodies == []

    async def test_a_plain_text_threshold_alert_without_a_window_is_sent_with_fifteen_minutes(
        self, tools, platform, owner_email
    ):
        await tools.handle_action(
            "create_from_text", {"text": "alert when cost per transaction exceeds 5"}
        )

        body = platform.created_bodies[-1]
        assert body["metricType"] == "COST_PER_TRANSACTION"
        assert body["periodDuration"] == "FIFTEEN_MINUTES"

    async def test_plain_text_tokens_per_minute_is_sent_as_tokens_per_minute(
        self, tools, platform, owner_email
    ):
        await tools.handle_action(
            "create_from_text", {"text": "Alert when tokens per minute exceed 1000"}
        )

        body = platform.created_bodies[-1]
        assert body["metricType"] == "TOKENS_PER_MINUTE"
        assert body["periodDuration"] == "FIFTEEN_MINUTES"

    async def test_a_rate_per_second_in_plain_text_is_refused_not_read_as_per_minute(
        self, tools, platform, owner_email
    ):
        with pytest.raises(ToolError) as refusal:
            await tools.handle_action(
                "create_from_text", {"text": "Alert when token rate exceeds 100 per second"}
            )

        assert "tokens_per_minute" in str(refusal.value)
        assert platform.created_bodies == []

    async def test_a_request_rate_per_second_in_plain_text_is_refused(
        self, tools, platform, owner_email
    ):
        with pytest.raises(ToolError) as refusal:
            await tools.handle_action(
                "create_from_text", {"text": "Alert when request rate exceeds 50 per second"}
            )

        assert "requests_per_minute" in str(refusal.value)
        assert platform.created_bodies == []

    async def test_a_second_alert_in_plain_text_creates_the_per_minute_alert(
        self, tools, platform, owner_email
    ):
        """BACK-4800: "a second alert" names a second alert, not a per-second rate."""
        await tools.handle_action(
            "create_from_text", {"text": "Add a second alert when token rate exceeds 900000"}
        )

        body = platform.created_bodies[-1]
        assert body["metricType"] == "TOKENS_PER_MINUTE"
        assert body["threshold"] == 900000
        assert body["alertType"] == "THRESHOLD"
        assert body["periodDuration"] == "FIFTEEN_MINUTES"

    async def test_a_rate_without_a_unit_in_plain_text_is_per_minute(
        self, tools, platform, owner_email
    ):
        await tools.handle_action(
            "create_from_text", {"text": "Alert when token rate exceeds 100"}
        )

        assert platform.created_bodies[-1]["metricType"] == "TOKENS_PER_MINUTE"

    async def test_the_unknown_window_refusal_lists_only_windows_a_threshold_rule_accepts(
        self, tools, platform
    ):
        with pytest.raises(ToolError) as refusal:
            await tools.handle_action("create", {"anomaly_data": _rule(window="2h")})

        accepted = refusal.value.examples["accepted_time_windows"]
        for calendar_window in ("daily", "weekly", "monthly", "quarterly"):
            assert calendar_window not in accepted
        assert "15m" in accepted
        for window in accepted:
            InputValidator.validate_detection_rule(
                {"rule_type": "THRESHOLD", "metric": "total_cost", "operator": ">",
                 "value": 5, "time_window": window}
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.usefixtures("owner_email")
async def test_the_unknown_window_refusal_on_the_wire_names_the_accepted_windows(dry_run, platform):
    arguments = {"action": "create", "anomaly_data": _rule(window="2h")}
    if dry_run:
        arguments["dry_run"] = True

    with patch.object(AlertManagement, "get_client", AsyncMock(return_value=platform)):
        _, text, _ = await _call_through_the_boundary(
            "_register_manage_alerts", "manage_alerts", arguments, execute=True
        )

    assert "'2h' is not a window the platform accepts" in text
    assert ", ".join(ACCEPTED_THRESHOLD_WINDOWS) in text
    assert platform.created_bodies == []


def _refused_period_examples(text: str):
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() not in DEFERRED_EXAMPLE_LINES
        for minutes in PERIOD_MINUTES_EXAMPLE.findall(line)
        if int(minutes) not in PERIOD_MINUTES_THE_THRESHOLD_ACTION_ACCEPTS
    ]


@pytest.mark.asyncio
async def test_every_threshold_example_uses_a_period_the_action_accepts(tools):
    texts = [inspect.getsource(alert_management), inspect.getsource(anomaly_manager)]
    for action, arguments in [
        ("get_capabilities", {}),
        ("get_examples", {}),
        ("get_examples", {"alert_type": "threshold"}),
        ("get_examples", {"alert_type": "cumulative_usage"}),
    ]:
        texts.extend(part.text for part in await tools.handle_action(action, arguments))
    for capability in await tools._get_tool_capabilities():
        texts.extend(capability.examples)
    with pytest.raises(ToolError) as missing_data:
        await tools.handle_action("create", {})
    texts.append(str(missing_data.value))
    texts.append(json.dumps(missing_data.value.examples))

    refused = [line for text in texts for line in _refused_period_examples(text)]

    assert refused == []


@pytest.mark.asyncio
async def test_the_help_text_states_the_fifteen_minute_default(tools):
    period_minutes = (await tools._get_input_schema())["properties"]["period_minutes"]
    source = inspect.getsource(alert_management)

    assert "(default: 15)" in period_minutes["description"]
    assert "every 5 minutes" not in source


@pytest.mark.asyncio
async def test_the_per_transaction_command_creates_a_cost_per_transaction_alert_that_notifies_someone(
    tools, platform, owner_email
):
    blocks = FENCED_JSON.findall(PER_TRANSACTION_COMMAND.read_text())
    assert len(blocks) == 1, "the command must give its arguments as one json block"
    command_arguments = json.loads(blocks[0])

    is_error, text, captured = await _call_through_the_boundary(
        "_register_manage_alerts", "manage_alerts", command_arguments
    )
    assert not is_error, text
    result = await tools.handle_action(command_arguments["action"], captured)

    assert "Created" in result[0].text
    body = platform.created_bodies[-1]
    assert body["alertType"] == "THRESHOLD"
    assert body["metricType"] == "COST_PER_TRANSACTION"
    assert body["operatorType"] == "GREATER_THAN"
    assert body["threshold"] == 5.0
    assert body["periodDuration"] == "FIFTEEN_MINUTES"
    assert body["notificationAddresses"] == [owner_email]


@pytest.mark.asyncio
@pytest.mark.parametrize("window", [None, "", "  "], ids=repr)
async def test_a_threshold_rule_with_a_blank_window_gets_fifteen_minutes(tools, platform, window):
    """BACK-4801: a blank time_window is a window nobody sent, so it gets the 15 minute default."""
    rule = _rule()
    rule["detection_rules"][0]["time_window"] = window
    rule["notificationAddresses"] = [OWNER]

    validated = await tools.handle_action("validate", {"anomaly_data": rule})

    assert "Validation passed" in validated[0].text
    assert '"periodDuration": "FIFTEEN_MINUTES"' in validated[0].text
    assert platform.created_bodies == []


@pytest.mark.parametrize("window", [None, "", "  "], ids=repr)
def test_a_budget_rule_with_a_blank_window_takes_the_period_it_was_given(window):
    """BACK-4801: a blank time_window on a budget rule falls back to the given period."""
    without_window = _rule(window=None, rule_type="CUMULATIVE_USAGE")
    without_window["period"] = "weekly"
    blank_window = _rule(window=None, rule_type="CUMULATIVE_USAGE")
    blank_window["detection_rules"][0]["time_window"] = window
    blank_window["period"] = "weekly"

    omitted = InputValidator.convert_to_api_format(without_window)
    converted = InputValidator.convert_to_api_format(blank_window)

    assert omitted["periodDuration"] == "WEEKLY"
    assert converted["periodDuration"] == "WEEKLY"
