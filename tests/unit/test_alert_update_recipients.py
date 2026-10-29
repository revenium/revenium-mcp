"""BACK-4850: an update never leaves an alert notifying nobody, and every switch names a missing Slack channel."""

from unittest.mock import AsyncMock

import pytest

from src.revenium_mcp_server.tools_decomposed import alert_management
from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement
from tests.unit.anomaly_platform_fake import FakeAnomalyPlatform, answer, threshold_alert
from tests.unit.test_alert_platform_rules import UNKNOWN_SLACK, SlackCheckingPlatform, _outcome

CREATE_REFUSAL = "Email address is required for alert notifications"


def _tools(platform):
    tools = AlertManagement()
    tools.get_client = AsyncMock(return_value=platform)
    return tools


async def _preview_and_update(platform, anomaly_data):
    tools = _tools(platform)
    update = {"anomaly_id": "a1", "anomaly_data": anomaly_data}
    dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
    live = await answer(tools.handle_action("update", update))
    return dry, live


@pytest.mark.asyncio
class TestAnUpdateThatLeavesNoRecipient:
    @pytest.mark.parametrize(
        "emptied",
        [
            {"notificationAddresses": []},
            {"notificationAddresses": [], "slackConfigurations": []},
            {"notification_addresses": [], "slack_config_id": None},
        ],
        ids=["addresses-only-slack-already-empty", "both-lists", "snake-spellings"],
    )
    async def test_is_refused_with_the_create_message_and_nothing_is_sent(self, emptied):
        platform = FakeAnomalyPlatform([threshold_alert("a1")])

        dry, live = await _preview_and_update(platform, emptied)

        assert dry == live
        assert live[0] is True
        assert CREATE_REFUSAL in live[1]
        assert platform.updated_bodies == []
        assert platform.store["a1"]["notificationAddresses"] == ["old@example.com"]

    async def test_emptying_the_slack_list_of_an_alert_that_still_emails_is_allowed(self):
        platform = FakeAnomalyPlatform([threshold_alert("a1", slackConfigurations=["slack-1"])])

        _, live = await _preview_and_update(platform, {"slackConfigurations": []})

        assert live[0] is False
        assert platform.store["a1"]["slackConfigurations"] == []
        assert platform.store["a1"]["notificationAddresses"] == ["old@example.com"]

    async def test_emptying_the_addresses_of_an_alert_that_still_posts_to_slack_is_allowed(self):
        platform = FakeAnomalyPlatform([threshold_alert("a1", slackConfigurations=["slack-1"])])

        _, live = await _preview_and_update(platform, {"notificationAddresses": []})

        assert live[0] is False
        assert platform.store["a1"]["notificationAddresses"] == []
        assert platform.store["a1"]["slackConfigurations"] == ["slack-1"]

    @pytest.mark.parametrize(
        ("stored_webhooks", "update"),
        [
            ([], {"webhook_configurations": ["wh-1"], "notificationAddresses": []}),
            (["wh-1"], {"notificationAddresses": []}),
        ],
        ids=["update-sets-a-webhook", "alert-keeps-its-webhook"],
    )
    async def test_emptying_the_addresses_of_an_alert_that_still_calls_a_webhook_is_allowed(
        self, stored_webhooks, update
    ):
        platform = FakeAnomalyPlatform([threshold_alert("a1", webhookConfigurations=stored_webhooks)])

        _, live = await _preview_and_update(platform, update)

        assert live[0] is False
        assert platform.store["a1"]["notificationAddresses"] == []
        assert platform.store["a1"]["webhookConfigurations"] == ["wh-1"]

    async def test_emptying_the_last_webhook_of_an_alert_with_no_other_recipient_is_refused(self):
        platform = FakeAnomalyPlatform(
            [threshold_alert("a1", notificationAddresses=[], webhookConfigurations=["wh-1"])]
        )

        _, live = await _preview_and_update(platform, {"webhookConfigurations": []})

        assert live[0] is True
        assert CREATE_REFUSAL in live[1]
        assert platform.updated_bodies == []

    async def test_an_update_that_touches_no_recipient_list_is_not_checked(self):
        platform = FakeAnomalyPlatform([threshold_alert("a1", notificationAddresses=[])])

        _, live = await _preview_and_update(platform, {"name": "Renamed"})

        assert live[0] is False
        assert platform.store["a1"]["name"] == "Renamed"


def _disabled_alert_on_a_missing_slack_channel():
    return SlackCheckingPlatform(
        [threshold_alert("a1", enabled=False, slackConfigurations=[UNKNOWN_SLACK])]
    )


def _enabled_alert_on_a_missing_slack_channel():
    return SlackCheckingPlatform(
        [threshold_alert("a1", enabled=True, slackConfigurations=[UNKNOWN_SLACK])]
    )


SWITCHES = [
    ("enable", {"anomaly_id": "a1"}, _disabled_alert_on_a_missing_slack_channel, "enabled"),
    ("disable", {"anomaly_id": "a1"}, _enabled_alert_on_a_missing_slack_channel, "disabled"),
    ("toggle_status", {"anomaly_id": "a1"}, _enabled_alert_on_a_missing_slack_channel, "toggled"),
    ("enable_multiple", {"anomaly_ids": ["a1"]}, _disabled_alert_on_a_missing_slack_channel, "enabled"),
    ("disable_multiple", {"anomaly_ids": ["a1"]}, _enabled_alert_on_a_missing_slack_channel, "disabled"),
    ("enable_all", {"confirm": True}, _disabled_alert_on_a_missing_slack_channel, "enabled"),
    ("disable_all", {"confirm": True}, _enabled_alert_on_a_missing_slack_channel, "disabled"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "arguments", "platform_factory", "verb"),
    SWITCHES,
    ids=[switch[0] for switch in SWITCHES],
)
async def test_every_switch_names_the_missing_slack_channel(action, arguments, platform_factory, verb):
    platform = platform_factory()

    outcome = await _outcome(_tools(platform).handle_action(action, arguments))

    assert outcome[0] is True
    assert f"Slack configuration {UNKNOWN_SLACK} was not found in this organization" in outcome[1]
    assert f"nothing was {verb}" in outcome[1]
    assert platform.slack_lookups == [UNKNOWN_SLACK]
    assert platform.updated_bodies == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "arguments", "platform_factory", "verb"),
    SWITCHES,
    ids=[switch[0] for switch in SWITCHES],
)
async def test_every_switch_takes_its_refusal_verb_from_the_one_table(
    action, arguments, platform_factory, verb, monkeypatch
):
    reworded = {key: f"{key}-reworded" for key in alert_management._NOTHING_WAS}
    monkeypatch.setattr(alert_management, "_NOTHING_WAS", reworded)

    outcome = await _outcome(_tools(platform_factory()).handle_action(action, arguments))

    action_key = verb.removesuffix("d")
    assert f"nothing was {action_key}-reworded" in outcome[1]


SINGLE_SWITCHES = [switch for switch in SWITCHES if "anomaly_id" in switch[1]]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "arguments", "platform_factory", "verb"),
    SINGLE_SWITCHES,
    ids=[switch[0] for switch in SINGLE_SWITCHES],
)
async def test_a_single_switch_points_at_the_slack_configurations_not_the_alert_id(
    action, arguments, platform_factory, verb
):
    outcome = await _outcome(_tools(platform_factory()).handle_action(action, arguments))

    assert "get_slack(action='list_configurations')" in outcome[1]
    assert "Verify the anomaly_id exists" not in outcome[1]
    assert "ValidationError(" not in outcome[1]
