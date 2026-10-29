"""BACK-4635: an alert update applies the email and period it was given, or refuses them."""

from unittest.mock import AsyncMock

import pytest

from src.revenium_mcp_server.alerts.update_fidelity import (
    UNVERIFIED_UPDATE_FIELDS,
    platform_rule_breach,
    unapplied_fields,
)
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.tools_decomposed.alert_management import (
    FLAT_UPDATE_FIELDS,
    AlertManagement,
)
from tests.unit.anomaly_platform_fake import FakeAnomalyPlatform, answer, threshold_alert

NEW = "finance@example.com"
MODEL_FILTER = [{"dimension": "MODEL", "operator": "IS", "value": "gpt-4o"}]


_QUALITY_RATE_RULE = {
    "rule_type": "THRESHOLD",
    "metric": "quality_rate",
    "operator": "<",
    "value": 80,
    "time_window": "1h",
}
_TASK_TYPE_FILTER = {"field": "task_type", "operator": "is", "value": "code_review"}


def _tools_over(platform: FakeAnomalyPlatform) -> AlertManagement:
    tools = AlertManagement()
    tools.get_client = AsyncMock(return_value=platform)
    return tools


@pytest.fixture
def platform():
    return FakeAnomalyPlatform(
        [
            threshold_alert("a1"),
            threshold_alert(
                "b1", alertType="CUMULATIVE_USAGE", periodDuration="MONTHLY", name="Budget"
            ),
        ]
    )


@pytest.fixture
def tools(platform):
    return _tools_over(platform)


def _sent_body(platform: FakeAnomalyPlatform):
    assert platform.updated_bodies, "nothing was sent to the platform"
    return platform.updated_bodies[-1][1]


@pytest.mark.asyncio
class TestFlatEmail:
    async def test_flat_email_beside_another_field_changes_the_recipient(self, tools, platform):
        result = await tools.handle_action(
            "update", {"anomaly_id": "a1", "name": "Renamed", "email": NEW}
        )

        assert _sent_body(platform)["notificationAddresses"] == [NEW]
        assert _sent_body(platform)["name"] == "Renamed"
        assert platform.store["a1"]["notificationAddresses"] == [NEW]
        assert f"**Email Notifications:** {NEW}" in result[0].text

    async def test_flat_email_alone_is_an_update(self, tools, platform):
        await tools.handle_action("update", {"anomaly_id": "a1", "email": NEW})

        assert platform.store["a1"]["notificationAddresses"] == [NEW]

    async def test_email_and_addresses_are_unioned(self, tools, platform):
        await tools.handle_action(
            "update",
            {"anomaly_id": "a1", "email": NEW, "notificationAddresses": ["ops@example.com", NEW]},
        )

        assert _sent_body(platform)["notificationAddresses"] == [NEW, "ops@example.com"]

    async def test_email_inside_anomaly_data_still_works(self, tools, platform):
        await tools.handle_action("update", {"anomaly_id": "a1", "anomaly_data": {"email": NEW}})

        assert platform.store["a1"]["notificationAddresses"] == [NEW]


@pytest.mark.asyncio
class TestFlatPeriod:
    async def test_a_valid_window_changes_the_check_frequency(self, tools, platform):
        result = await tools.handle_action("update", {"anomaly_id": "a1", "period": "daily"})

        body = _sent_body(platform)
        assert body["periodDuration"] == "DAILY"
        assert "period" not in body
        assert platform.store["a1"]["periodDuration"] == "DAILY"
        assert "**Check Frequency:** DAILY" in result[0].text

    async def test_weekly_on_a_threshold_alert_is_applied(self, tools, platform):
        await tools.handle_action("update", {"anomaly_id": "a1", "period": "weekly"})

        assert _sent_body(platform)["periodDuration"] == "WEEKLY"
        assert platform.store["a1"]["periodDuration"] == "WEEKLY"

    @pytest.mark.parametrize(
        "alert, period, expected",
        [
            (threshold_alert("t1"), "weekly", "WEEKLY"),
            (threshold_alert("t1"), "monthly", "MONTHLY"),
            (threshold_alert("t1"), "thirty_days", "THIRTY_DAYS"),
            (threshold_alert("t1"), "thirty days", "THIRTY_DAYS"),
            (threshold_alert("t1"), "quarterly", "QUARTERLY"),
            (
                threshold_alert("t1", alertType="RELATIVE_CHANGE", operatorType="INCREASES_BY"),
                "quarterly",
                "QUARTERLY",
            ),
        ],
    )
    async def test_a_flat_period_reaches_every_window_period_duration_accepts(
        self, alert, period, expected
    ):
        """BACK-4801: a flat period takes every window periodDuration takes on that alert."""
        platform = FakeAnomalyPlatform([alert])
        tools = _tools_over(platform)
        update = {"anomaly_id": "t1", "period": period}

        dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
        assert dry[0] is False and "Dry Run Successful" in dry[1]
        assert platform.updated_bodies == []

        await tools.handle_action("update", update)
        assert _sent_body(platform)["periodDuration"] == expected

    @pytest.mark.parametrize(
        "alert_id, period, alert_type, accepted",
        [
            ("p1", "quarterly", "THRESHOLD", "DAILY, WEEKLY, MONTHLY"),
            ("b1", "fifteen_minutes", "CUMULATIVE_USAGE", "DAILY, WEEKLY, MONTHLY, QUARTERLY"),
        ],
    )
    async def test_a_flat_period_the_alert_type_refuses_is_still_refused(
        self, alert_id, period, alert_type, accepted
    ):
        platform = FakeAnomalyPlatform(
            [
                threshold_alert("p1", dataSource="PROVIDER", periodDuration="DAILY"),
                threshold_alert("b1", alertType="CUMULATIVE_USAGE", periodDuration="MONTHLY"),
            ]
        )
        tools = _tools_over(platform)
        update = {"anomaly_id": alert_id, "period": period}

        dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
        live = await answer(tools.handle_action("update", update))

        assert dry == live
        assert dry[0] is True
        assert f"period '{period}' is not valid for a {alert_type} alert" in live[1]
        assert f"use one of {accepted}." in live[1]
        assert platform.updated_bodies == []

    async def test_weekly_on_a_budget_alert_is_applied(self, tools, platform):
        await tools.handle_action("update", {"anomaly_id": "b1", "period": "weekly"})

        assert platform.store["b1"]["periodDuration"] == "WEEKLY"

    async def test_weekly_on_a_provider_threshold_alert_is_applied(self):
        platform = FakeAnomalyPlatform([threshold_alert("p1", dataSource="PROVIDER", periodDuration="DAILY")])

        await _tools_over(platform).handle_action("update", {"anomaly_id": "p1", "period": "weekly"})

        assert platform.store["p1"]["periodDuration"] == "WEEKLY"

    async def test_a_period_that_disagrees_with_period_duration_is_refused(self, tools, platform):
        with pytest.raises(ToolError, match="disagree"):
            await tools.handle_action(
                "update", {"anomaly_id": "a1", "period": "daily", "periodDuration": "ONE_HOUR"}
            )

        assert platform.updated_bodies == []


@pytest.mark.asyncio
class TestNeverReportsAFieldItDidNotApply:
    async def test_a_field_the_platform_kept_turns_the_answer_into_an_error(self):
        platform = FakeAnomalyPlatform([threshold_alert("a1")], kept_on_update={"periodDuration"})

        with pytest.raises(ToolError) as refusal:
            await _tools_over(platform).handle_action(
                "update", {"anomaly_id": "a1", "periodDuration": "DAILY"}
            )

        message = str(refusal.value)
        assert "not fully updated" in message
        assert "periodDuration" in message
        assert "Updated Successfully" not in message

    async def test_flat_percentage_flag_is_applied(self, tools, platform):
        await tools.handle_action("update", {"anomaly_id": "a1", "isPercentage": True})

        assert platform.store["a1"]["isPercentage"] is True

    async def test_an_update_with_nothing_to_change_carries_the_error_flag(self, tools, platform):
        with pytest.raises(ToolError) as refusal:
            await tools.handle_action("update", {"anomaly_id": "a1"})

        assert "update_data" in str(refusal.value)
        assert 'email="user@example.com"' in str(refusal.value)
        assert platform.updated_bodies == []


ROWS = [{"dimension": "MODEL", "operator": "IS", "value": "gpt-4o"}]


@pytest.mark.asyncio
class TestAFieldTheAnswerOmitsIsReadBack:
    async def test_an_omitted_field_the_read_back_confirms_is_reported_as_updated(self):
        platform = FakeAnomalyPlatform(
            [threshold_alert("a1")], omitted_from_update_answer={"filters"}
        )

        result = await _tools_over(platform).handle_action(
            "update", {"anomaly_id": "a1", "anomaly_data": {"filters": ROWS}}
        )

        assert "Updated Successfully" in result[0].text
        assert platform.read_ids == ["a1", "a1"]

    async def test_an_omitted_field_the_read_back_does_not_confirm_is_an_error(self):
        platform = FakeAnomalyPlatform(
            [threshold_alert("a1", triggerAfterPersistsDuration="")],
            kept_on_update={"triggerAfterPersistsDuration"},
            omitted_from_update_answer={"triggerAfterPersistsDuration"},
        )

        with pytest.raises(ToolError) as refusal:
            await _tools_over(platform).handle_action(
                "update", {"anomaly_id": "a1", "triggerAfterPersistsDuration": "ONE_HOUR"}
            )

        assert "not fully updated" in str(refusal.value)
        assert "triggerAfterPersistsDuration" in str(refusal.value)

    async def test_a_field_absent_from_the_answer_and_the_read_back_is_an_error(self):
        platform = FakeAnomalyPlatform([threshold_alert("a1")], omitted_from_update_answer={"filters"})
        platform.get_anomaly_by_id = AsyncMock(
            side_effect=[threshold_alert("a1"), {"id": "a1", "name": "Alert a1"}]
        )

        with pytest.raises(ToolError, match="filters .*not returned"):
            await _tools_over(platform).handle_action(
                "update", {"anomaly_id": "a1", "anomaly_data": {"filters": ROWS}}
            )

    async def test_a_filter_the_platform_kept_is_an_error(self):
        platform = FakeAnomalyPlatform([threshold_alert("a1")], kept_on_update={"filters"})

        with pytest.raises(ToolError, match="filters"):
            await _tools_over(platform).handle_action(
                "update", {"anomaly_id": "a1", "anomaly_data": {"filters": ROWS}}
            )

    async def test_an_unchanged_persistence_setting_is_not_an_error(self):
        platform = FakeAnomalyPlatform(
            [threshold_alert("a1", triggerAfterPersistsDuration="FIFTEEN_MINUTES")],
            kept_on_update={"triggerAfterPersistsDuration"},
        )

        result = await _tools_over(platform).handle_action(
            "update",
            {"anomaly_id": "a1", "name": "Renamed", "triggerAfterPersistsDuration": "FIFTEEN_MINUTES"},
        )

        assert "Updated Successfully" in result[0].text
        assert platform.read_ids == ["a1"]

    async def test_a_persistence_setting_left_untouched_is_not_checked(self):
        platform = FakeAnomalyPlatform(
            [threshold_alert("a1", triggerAfterPersistsDuration="FIFTEEN_MINUTES")],
            omitted_from_update_answer={"triggerAfterPersistsDuration"},
        )

        await _tools_over(platform).handle_action("update", {"anomaly_id": "a1", "name": "Renamed"})

        assert platform.read_ids == ["a1"]


def _model_filter_with_value(value):
    return {"filters": [{"dimension": "MODEL", "operator": "IS", "value": value}]}


@pytest.mark.parametrize(
    ("sent", "stored"), [("", None), (None, "")], ids=["blank-sent-null-stored", "null-sent-blank-stored"]
)
def test_a_blank_filter_value_and_a_missing_one_read_back_as_different(sent, stored):
    differences = unapplied_fields(
        _model_filter_with_value(sent), _model_filter_with_value(stored)
    )

    assert len(differences) == 1
    assert differences[0].startswith("filters (sent")


@pytest.mark.parametrize("value", ["", None, "gpt-4o"])
def test_a_filter_value_stored_as_sent_reads_back_as_applied(value):
    assert unapplied_fields(_model_filter_with_value(value), _model_filter_with_value(value)) == []


FLAT_FIELD_SAMPLES = {
    "name": ("Renamed", "name"),
    "threshold": (250, "threshold"),
    "isPercentage": (True, "isPercentage"),
    "alertType": ("CUMULATIVE_USAGE", "alertType"),
    "enabled": (False, "enabled"),
    "slackConfigurations": (["slack-1"], "slackConfigurations"),
    "slack_config_id": ("slack-2", "slackConfigurations"),
    "notificationAddresses": ([NEW], "notificationAddresses"),
    "email": (NEW, "notificationAddresses"),
    "description": ("Watches spend", "description"),
    "metricType": ("TOKEN_COUNT", "metricType"),
    "period": ("daily", "periodDuration"),
    "period_minutes": (15, "periodDuration"),
    "periodDuration": ("DAILY", "periodDuration"),
    "triggerAfterPersistsDuration": ("FIFTEEN_MINUTES", "triggerAfterPersistsDuration"),
    "filters": (MODEL_FILTER, "filters"),
}


def test_every_flat_update_field_has_a_sample():
    assert set(FLAT_FIELD_SAMPLES) == set(FLAT_UPDATE_FIELDS)


@pytest.mark.asyncio
@pytest.mark.parametrize("flat_field", FLAT_UPDATE_FIELDS)
async def test_every_flat_update_field_is_verified_or_deliberately_exempt(flat_field):
    value, platform_field = FLAT_FIELD_SAMPLES[flat_field]
    if platform_field in UNVERIFIED_UPDATE_FIELDS:
        return
    # A budget alert takes only budget periods, so the alert a type change moves keeps a daily one.
    stored = threshold_alert("a1", periodDuration="DAILY") if flat_field == "alertType" else threshold_alert("a1")
    platform = FakeAnomalyPlatform([stored], kept_on_update={platform_field})

    with pytest.raises(ToolError) as refusal:
        await _tools_over(platform).handle_action("update", {"anomaly_id": "a1", flat_field: value})

    assert "not fully updated" in str(refusal.value)
    assert platform_field in str(refusal.value)


@pytest.mark.asyncio
class TestTheUpdateAnswerIsCheckedForEverySentField:
    async def test_a_pass_through_field_the_platform_kept_is_an_error(self):
        platform = FakeAnomalyPlatform([threshold_alert("a1")], kept_on_update={"groupBy"})

        with pytest.raises(ToolError, match="not fully updated.*groupBy"):
            await _tools_over(platform).handle_action(
                "update", {"anomaly_id": "a1", "anomaly_data": {"groupBy": "MODEL"}}
            )

    async def test_an_exempt_field_is_not_checked(self):
        platform = FakeAnomalyPlatform(
            [threshold_alert("a1")], kept_on_update={"webhookConfigurations"}
        )

        result = await _tools_over(platform).handle_action(
            "update", {"anomaly_id": "a1", "anomaly_data": {"webhookConfigurations": ["hook-1"]}}
        )

        assert "Updated Successfully" in result[0].text


@pytest.mark.asyncio
class TestFlatArgumentsTheSignatureDeclares:
    async def test_slack_config_id_beside_a_name_changes_the_slack_channel(self, tools, platform):
        await tools.handle_action(
            "update", {"anomaly_id": "a1", "name": "Renamed", "slack_config_id": "slack-2"}
        )

        assert _sent_body(platform)["slackConfigurations"] == ["slack-2"]
        assert platform.store["a1"]["slackConfigurations"] == ["slack-2"]
        assert platform.store["a1"]["name"] == "Renamed"

    async def test_a_slack_change_the_platform_kept_is_an_error(self):
        platform = FakeAnomalyPlatform([threshold_alert("a1")], kept_on_update={"slackConfigurations"})

        with pytest.raises(ToolError, match="not fully updated.*slackConfigurations"):
            await _tools_over(platform).handle_action(
                "update", {"anomaly_id": "a1", "name": "Renamed", "slack_config_id": "slack-2"}
            )

    async def test_flat_filters_are_sent_and_stored(self, tools, platform):
        await tools.handle_action("update", {"anomaly_id": "a1", "filters": MODEL_FILTER})

        assert _sent_body(platform)["filters"] == MODEL_FILTER
        assert platform.store["a1"]["filters"] == MODEL_FILTER

    async def test_filters_the_platform_kept_are_an_error(self):
        platform = FakeAnomalyPlatform([threshold_alert("a1")], kept_on_update={"filters"})

        with pytest.raises(ToolError, match="not fully updated.*filters"):
            await _tools_over(platform).handle_action(
                "update", {"anomaly_id": "a1", "filters": MODEL_FILTER}
            )

    async def test_an_unknown_flat_argument_is_refused_before_any_request(self, tools, platform):
        with pytest.raises(ToolError) as refusal:
            await tools.handle_action(
                "update", {"anomaly_id": "a1", "name": "Renamed", "provider": "openai"}
            )

        assert refusal.value.field == "provider"
        assert "nothing was updated" in str(refusal.value)
        assert platform.read_ids == []
        assert platform.updated_bodies == []

    async def test_the_alert_id_alias_and_an_off_dry_run_are_not_refused(self, tools, platform):
        await tools.handle_action(
            "update", {"alert_id": "a1", "name": "Renamed", "dry_run": False}
        )

        assert platform.store["a1"]["name"] == "Renamed"


@pytest.mark.asyncio
class TestTagsAreRefused:
    async def test_flat_tags_are_refused_and_nothing_is_sent(self, tools, platform):
        with pytest.raises(ToolError) as refusal:
            await tools.handle_action("update", {"anomaly_id": "a1", "tags": ["finance"]})

        assert refusal.value.field == "tags"
        assert "tags" in str(refusal.value)
        assert platform.read_ids == []
        assert platform.updated_bodies == []

    async def test_tags_inside_anomaly_data_are_refused_and_nothing_is_sent(self, tools, platform):
        with pytest.raises(ToolError) as refusal:
            await tools.handle_action(
                "update", {"anomaly_id": "a1", "anomaly_data": {"name": "X", "tags": ["finance"]}}
            )

        assert refusal.value.field == "tags"
        assert platform.updated_bodies == []


@pytest.mark.asyncio
class TestRecipientRefusalsNameTheFieldSent:
    async def test_a_non_address_email_is_refused_under_email(self, tools, platform):
        with pytest.raises(ToolError) as refusal:
            await tools.handle_action("update", {"anomaly_id": "a1", "anomaly_data": {"email": 123}})

        assert refusal.value.field == "email"
        assert platform.updated_bodies == []

    async def test_non_address_notification_addresses_are_refused_under_their_name(
        self, tools, platform
    ):
        with pytest.raises(ToolError) as refusal:
            await tools.handle_action(
                "update", {"anomaly_id": "a1", "anomaly_data": {"notificationAddresses": [1]}}
            )

        assert refusal.value.field == "notificationAddresses"


@pytest.mark.asyncio
class TestUpdatePreviewGivesTheLiveVerdict:
    async def test_a_preview_of_a_refused_operator_is_refused_like_the_live_update(
        self, tools, platform
    ):
        update = {"anomaly_id": "a1", "anomaly_data": {"operatorType": "EQUAL_TO"}}

        dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
        assert platform.updated_bodies == []
        live = await answer(tools.handle_action("update", update))

        assert dry == live
        assert "Dry Run Successful" not in dry[1]
        assert platform.updated_bodies == []

    async def test_a_preview_of_a_direct_threshold_shows_the_change_and_sends_nothing(
        self, tools, platform
    ):
        dry = await answer(
            tools.handle_action("update", {"anomaly_id": "a1", "dry_run": True, "threshold": 200})
        )

        assert dry[0] is False
        assert '"valid": true' in dry[1]
        assert '"threshold": 200' in dry[1]
        assert platform.updated_bodies == []
        assert platform.store["a1"]["threshold"] == 100.0

        await tools.handle_action("update", {"anomaly_id": "a1", "threshold": 200})
        assert platform.store["a1"]["threshold"] == 200

    async def test_a_preview_of_a_period_the_alert_refuses_raises_like_the_live_update(
        self, tools, platform
    ):
        update = {"anomaly_id": "a1", "period": "two_hours"}

        dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
        live = await answer(tools.handle_action("update", update))

        assert dry == live
        assert dry[0] is True
        assert "period 'two_hours' is not valid for a THRESHOLD alert" in live[1]
        assert (
            "use one of FIFTEEN_MINUTES, THIRTY_MINUTES, ONE_HOUR, TWELVE_HOURS, DAILY, "
            "WEEKLY, MONTHLY, THIRTY_DAYS, QUARTERLY." in live[1]
        )
        assert platform.updated_bodies == []

    async def test_a_preview_of_a_five_minute_period_is_refused_like_the_live_update(
        self, tools, platform
    ):
        update = {"anomaly_id": "a1", "period_minutes": 5}

        dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
        live = await answer(tools.handle_action("update", update))

        assert dry == live
        assert "FIFTEEN_MINUTES" in live[1]
        assert "Dry Run Successful" not in dry[1]
        assert platform.updated_bodies == []

    async def test_a_preview_of_a_five_minute_budget_period_is_refused_like_the_live_update(
        self, tools, platform
    ):
        update = {"anomaly_id": "b1", "periodDuration": "FIVE_MINUTES"}

        dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
        live = await answer(tools.handle_action("update", update))

        assert dry == live
        assert dry[0] is True
        assert "DAILY, WEEKLY, MONTHLY, QUARTERLY" in live[1]
        assert "FIFTEEN_MINUTES or longer" not in live[1]
        assert platform.updated_bodies == []

    async def test_a_preview_of_five_minutes_names_each_alert_types_own_rule(
        self, tools, platform
    ):
        budget = await answer(
            tools.handle_action("update", {"anomaly_id": "b1", "period_minutes": 5, "dry_run": True})
        )
        threshold = await answer(
            tools.handle_action("update", {"anomaly_id": "a1", "period_minutes": 5, "dry_run": True})
        )

        assert budget[0] == threshold[0]
        assert "DAILY, WEEKLY, MONTHLY, QUARTERLY" in budget[1]
        assert "FIFTEEN_MINUTES or longer" not in budget[1]
        assert "FIFTEEN_MINUTES or longer" in threshold[1]
        assert "Dry Run Successful" not in budget[1] + threshold[1]
        assert platform.updated_bodies == []

    async def test_a_preview_of_a_thirty_minute_budget_period_is_refused_like_the_live_update(
        self, tools, platform
    ):
        update = {"anomaly_id": "b1", "periodDuration": "THIRTY_MINUTES"}

        dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
        live = await answer(tools.handle_action("update", update))

        assert dry == live
        assert dry[0] is True
        assert "DAILY, WEEKLY, MONTHLY, QUARTERLY" in live[1]
        assert platform.updated_bodies == []

    async def test_a_day_of_minutes_previews_and_updates_as_daily(self, tools, platform):
        update = {"anomaly_id": "a1", "period_minutes": 1440}

        dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
        assert dry[0] is False
        assert '"periodDuration": "DAILY"' in dry[1]
        assert platform.updated_bodies == []

        await tools.handle_action("update", update)
        assert _sent_body(platform)["periodDuration"] == "DAILY"

    async def test_a_preview_of_twenty_four_hours_is_refused_like_the_live_update(
        self, tools, platform
    ):
        update = {"anomaly_id": "a1", "periodDuration": "TWENTY_FOUR_HOURS"}

        dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
        live = await answer(tools.handle_action("update", update))

        assert dry == live
        assert dry[0] is True
        assert "DAILY" in live[1]
        assert platform.updated_bodies == []


@pytest.mark.asyncio
class TestTheUpdatePeriodIsOneThePlatformKeeps:
    """The preview and the live update refuse a periodDuration the platform has no period for."""

    @pytest.fixture
    def platform(self):
        return FakeAnomalyPlatform(
            [
                threshold_alert("a1"),
                threshold_alert("p1", dataSource="PROVIDER", periodDuration="DAILY"),
            ]
        )

    @pytest.mark.parametrize("period", ["daily", "twenty_four_hours", "ONE_DAY", "TWO_HOURS"])
    async def test_a_period_the_platform_has_no_name_for_is_refused_by_preview_and_update(
        self, tools, platform, period
    ):
        update = {"anomaly_id": "a1", "periodDuration": period}

        dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
        live = await answer(tools.handle_action("update", update))

        assert dry == live
        assert dry[0] is True
        assert "Dry Run Successful" not in dry[1]
        assert "FIFTEEN_MINUTES" in live[1]
        assert platform.updated_bodies == []

    @pytest.mark.parametrize(
        "update",
        [
            {"periodDuration": "FIFTEEN_MINUTES"},
            {"period_minutes": 60},
        ],
    )
    async def test_a_provider_alert_under_a_day_is_refused_by_preview_and_update(
        self, tools, platform, update
    ):
        update = {"anomaly_id": "p1", **update}

        dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
        live = await answer(tools.handle_action("update", update))

        assert dry == live
        assert dry[0] is True
        assert "DAILY, WEEKLY, MONTHLY" in live[1]
        assert "QUARTERLY" not in live[1]
        assert platform.updated_bodies == []

    @pytest.mark.parametrize("period", ["WEEKLY", "QUARTERLY", "THIRTY_DAYS"])
    async def test_a_period_the_platform_keeps_still_previews_and_updates(
        self, tools, platform, period
    ):
        update = {"anomaly_id": "a1", "periodDuration": period}

        dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
        assert dry[0] is False
        assert platform.updated_bodies == []

        await tools.handle_action("update", update)
        assert _sent_body(platform)["periodDuration"] == period

    @pytest.mark.parametrize(
        "stored, change",
        [
            (
                {"alertType": "RELATIVE_CHANGE", "operatorType": "INCREASES_BY", "periodDuration": "DAILY"},
                {"dataSource": "PROVIDER"},
            ),
            ({"periodDuration": "DAILY"}, {"dataSource": "provider"}),
        ],
    )
    async def test_a_preview_of_a_data_source_the_platform_refuses_is_refused_like_the_live_update(
        self, stored, change
    ):
        platform = FakeAnomalyPlatform([threshold_alert("r1", **stored)])
        tools = _tools_over(platform)
        update = {"anomaly_id": "r1", "anomaly_data": change}

        dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
        live = await answer(tools.handle_action("update", update))

        assert dry == live
        assert dry[0] is True
        assert "PROVIDER" in live[1]
        assert platform.updated_bodies == []


@pytest.mark.asyncio
class TestTheUpdatePreviewAgreesWithTheLiveUpdateOnTheDataSource:
    """A provider-sourced alert takes THRESHOLD or CUMULATIVE_USAGE only, whichever side moves."""

    @pytest.fixture
    def platform(self):
        return FakeAnomalyPlatform(
            [
                threshold_alert("a1"),
                threshold_alert("r1", alertType="RELATIVE_CHANGE", periodDuration="DAILY"),
                threshold_alert("p1", dataSource="PROVIDER", periodDuration="DAILY"),
            ]
        )

    @pytest.mark.parametrize(
        "update",
        [
            {"anomaly_id": "r1", "anomaly_data": {"dataSource": "PROVIDER"}},
            {
                "anomaly_id": "p1",
                "anomaly_data": {"alertType": "RELATIVE_CHANGE", "operatorType": "INCREASES_BY"},
            },
        ],
        ids=["data source moved", "alert type moved"],
    )
    async def test_a_provider_relative_change_alert_is_refused_by_preview_and_update(
        self, tools, platform, update
    ):
        dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
        live = await answer(tools.handle_action("update", update))

        assert dry == live
        assert dry[0] is True
        assert "a provider-sourced alert takes THRESHOLD or CUMULATIVE_USAGE only" in live[1]
        assert "Dry Run Successful" not in dry[1]
        assert platform.updated_bodies == []

    @pytest.mark.parametrize("data_source", ["provider", "sdk"])
    async def test_a_data_source_other_than_sdk_or_provider_is_refused_by_preview_and_update(
        self, tools, platform, data_source
    ):
        update = {"anomaly_id": "p1", "anomaly_data": {"dataSource": data_source}}

        dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
        live = await answer(tools.handle_action("update", update))

        assert dry == live
        assert dry[0] is True
        assert "SDK" in live[1] and "PROVIDER" in live[1]
        assert "Dry Run Successful" not in dry[1]
        assert platform.updated_bodies == []

    async def test_moving_a_daily_threshold_alert_to_provider_still_updates(self, tools, platform):
        update = {"anomaly_id": "a1", "anomaly_data": {"dataSource": "PROVIDER", "periodDuration": "DAILY"}}

        dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
        assert dry[0] is False
        assert platform.updated_bodies == []

        await tools.handle_action("update", update)
        assert _sent_body(platform)["dataSource"] == "PROVIDER"


@pytest.mark.asyncio
class TestTheUpdatePreviewAgreesWithTheLiveUpdateOnTheProviderMetricAndFilters:
    """A provider alert's metric and filter dimensions are checked whenever either side moves."""

    @pytest.fixture
    def platform(self):
        return FakeAnomalyPlatform(
            [
                threshold_alert("p1", dataSource="PROVIDER", periodDuration="DAILY"),
                threshold_alert("e1", metricType="ERROR_RATE", periodDuration="DAILY"),
                threshold_alert(
                    "o1",
                    periodDuration="DAILY",
                    filters=[{"dimension": "ORGANIZATION", "operator": "IS", "value": "x"}],
                ),
            ]
        )

    @pytest.mark.parametrize(
        "update, refusal",
        [
            (
                {"anomaly_id": "p1", "anomaly_data": {"metricType": "ERROR_RATE"}},
                "metricType ERROR_RATE is not supported for provider alerts",
            ),
            (
                {"anomaly_id": "p1", "anomaly_data": {"metricType": "COST_PER_TRANSACTION"}},
                "metricType COST_PER_TRANSACTION is not supported for provider alerts",
            ),
            (
                {"anomaly_id": "e1", "anomaly_data": {"dataSource": "PROVIDER"}},
                "metricType ERROR_RATE is not supported for provider alerts",
            ),
            (
                {
                    "anomaly_id": "p1",
                    "anomaly_data": {
                        "filters": [{"dimension": "ORGANIZATION", "operator": "IS", "value": "x"}]
                    },
                },
                "filter dimension ORGANIZATION is not supported for provider alerts",
            ),
            (
                {"anomaly_id": "o1", "anomaly_data": {"dataSource": "PROVIDER"}},
                "filter dimension ORGANIZATION is not supported for provider alerts",
            ),
        ],
        ids=[
            "metric moved to ERROR_RATE",
            "metric moved to COST_PER_TRANSACTION",
            "error-rate alert moved to provider",
            "organization filter added",
            "organization-filtered alert moved to provider",
        ],
    )
    async def test_a_provider_alert_the_platform_refuses_is_refused_by_preview_and_update(
        self, tools, platform, update, refusal
    ):
        dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
        live = await answer(tools.handle_action("update", update))

        assert dry == live
        assert dry[0] is True
        assert refusal in live[1]
        assert "Dry Run Successful" not in dry[1]
        assert platform.updated_bodies == []

    @pytest.mark.parametrize(
        "anomaly_data",
        [
            {"metricType": "OUTPUT_TOKEN_COUNT"},
            {"filters": [{"dimension": "API_KEY", "operator": "IS", "value": "k1"}]},
        ],
        ids=["provider metric", "provider filter dimension"],
    )
    async def test_a_provider_metric_or_filter_the_platform_takes_still_updates(
        self, tools, platform, anomaly_data
    ):
        update = {"anomaly_id": "p1", "anomaly_data": anomaly_data}

        dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
        assert dry[0] is False
        assert platform.updated_bodies == []

        await tools.handle_action("update", update)
        assert platform.updated_bodies

    async def test_a_null_data_source_is_accepted_by_preview_and_update(self, tools, platform):
        update = {"anomaly_id": "e1", "anomaly_data": {"dataSource": None}}

        dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
        assert dry[0] is False

        await tools.handle_action("update", update)
        assert platform.updated_bodies


@pytest.mark.asyncio
class TestANullDataSourceOnAnUpdateKeepsTheStoredSource:
    """The platform keeps the stored dataSource when an update sends null, so every check does too."""

    @pytest.fixture
    def platform(self):
        return FakeAnomalyPlatform(
            [
                threshold_alert("p1", dataSource="PROVIDER", periodDuration="DAILY"),
                threshold_alert("s1", dataSource="SDK", periodDuration="DAILY"),
            ]
        )

    @pytest.mark.parametrize(
        "change, refusal",
        [
            ({"metricType": "ERROR_RATE"}, "metricType ERROR_RATE is not supported for provider alerts"),
            (
                {"periodDuration": "FIFTEEN_MINUTES"},
                "periodDuration FIFTEEN_MINUTES is not supported for a provider-sourced",
            ),
        ],
        ids=["provider metric", "provider period"],
    )
    async def test_a_provider_rule_is_still_checked_by_preview_and_update(
        self, tools, platform, change, refusal
    ):
        update = {"anomaly_id": "p1", "anomaly_data": {"dataSource": None, **change}}

        dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
        live = await answer(tools.handle_action("update", update))

        assert dry == live
        assert dry[0] is True
        assert refusal in live[1]
        assert "Dry Run Successful" not in dry[1]
        assert platform.updated_bodies == []

    async def test_a_null_data_source_alone_changes_nothing_and_reports_success(
        self, tools, platform
    ):
        update = {"anomaly_id": "p1", "anomaly_data": {"dataSource": None}}

        dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
        assert dry[0] is False
        assert '"dataSource": null' not in dry[1]

        live = await answer(tools.handle_action("update", update))
        assert live[0] is False
        assert "not fully updated" not in live[1]
        assert _sent_body(platform)["dataSource"] == "PROVIDER"
        assert platform.store["p1"]["dataSource"] == "PROVIDER"

    async def test_an_sdk_alert_with_a_null_data_source_and_a_valid_change_updates(
        self, tools, platform
    ):
        update = {"anomaly_id": "s1", "anomaly_data": {"dataSource": None, "metricType": "ERROR_RATE"}}

        dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
        assert dry[0] is False

        live = await answer(tools.handle_action("update", update))
        assert live[0] is False
        assert "not fully updated" not in live[1]
        assert platform.store["s1"]["metricType"] == "ERROR_RATE"
        assert platform.store["s1"]["dataSource"] == "SDK"


REQUIRED_UPDATE_REFUSAL = "is required; send a value, or leave it out to keep the stored one"
REQUIRED_CAMEL_FIELDS = ["name", "alertType", "metricType", "operatorType", "periodDuration", "enabled"]


@pytest.mark.asyncio
class TestExplicitNullsInsideAnomalyDataAnswerAlikeOnPreviewAndUpdate:
    """BACK-4824: a preview never approves a null the live update would send or misreport."""

    @staticmethod
    async def _preview_and_update(tools, anomaly_data):
        update = {"anomaly_id": "a1", "anomaly_data": anomaly_data}
        dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
        live = await answer(tools.handle_action("update", update))
        return dry, live

    @pytest.mark.parametrize("field_name", REQUIRED_CAMEL_FIELDS)
    async def test_a_null_required_field_is_refused_alike_by_preview_and_update(
        self, tools, platform, field_name
    ):
        dry, live = await self._preview_and_update(tools, {field_name: None})

        assert dry == live
        assert live[0] is True
        assert f"{field_name} {REQUIRED_UPDATE_REFUSAL}" in live[1]
        assert platform.updated_bodies == []

    @pytest.mark.parametrize(
        "field_name, flagged, refusal",
        [(name, True, f"{name} {REQUIRED_UPDATE_REFUSAL}") for name in REQUIRED_CAMEL_FIELDS]
        + [
            ("threshold", True, "threshold must be a number"),
            ("isPercentage", False, None),
            ("minSampleCount", False, None),
            ("description", False, None),
            ("groupBy", False, None),
        ],
    )
    async def test_the_eleven_explicit_nulls_answer_alike_on_preview_and_update(
        self, tools, field_name, flagged, refusal
    ):
        dry, live = await self._preview_and_update(tools, {field_name: None})

        assert dry[0] == live[0] == flagged
        if flagged:
            assert refusal in dry[1] and refusal in live[1]
        else:
            assert "not fully updated" not in live[1]

    @pytest.mark.parametrize("stored_flag", [True, False])
    async def test_a_null_percent_flag_keeps_the_stored_flag_and_reports_the_update_applied(
        self, stored_flag
    ):
        platform = FakeAnomalyPlatform([threshold_alert("a1", isPercentage=stored_flag)])
        tools = _tools_over(platform)

        dry, live = await self._preview_and_update(tools, {"isPercentage": None, "name": "Renamed"})

        assert dry[0] is False
        assert "isPercentage" not in dry[1]
        assert live[0] is False
        assert "not fully updated" not in live[1]
        assert _sent_body(platform)["isPercentage"] is stored_flag
        assert platform.store["a1"]["isPercentage"] is stored_flag
        assert platform.store["a1"]["name"] == "Renamed"


def _switch_arguments(action, anomaly_id):
    if action.endswith("_all"):
        return {}
    if action.endswith("_multiple"):
        return {"anomaly_ids": [anomaly_id]}
    return {"anomaly_id": anomaly_id}


def _breaking_provider_alert(anomaly_id="p1", **overrides):
    """A provider alert takes only DAILY, WEEKLY or MONTHLY, so a stored window breaks a current rule."""
    return threshold_alert(
        anomaly_id, dataSource="PROVIDER", periodDuration="FIFTEEN_MINUTES", **overrides
    )


# Stored bodies the way the platform returns them, each reaching a stored-value exemption.
STORED_SHAPES = {
    "threshold with nulls and read-only keys": threshold_alert(
        "g1",
        name=None,
        dataSource=None,
        groupBy=None,
        minSampleCount=None,
        triggerAfterPersistsDuration=None,
        filters=None,
        _links={"self": {"href": "https://example.invalid/anomaly/g1"}},
        createdAt="2026-01-01T00:00:00Z",
        updatedAt="2026-01-02T00:00:00Z",
    ),
    "budget on QUARTERLY": threshold_alert(
        "g1", alertType="CUMULATIVE_USAGE", periodDuration="QUARTERLY"
    ),
    "budget kept on a window": threshold_alert(
        "g1", alertType="CUMULATIVE_USAGE", periodDuration="ONE_HOUR"
    ),
    "cost alert storing a floor": threshold_alert("g1", periodDuration="DAILY", minSampleCount=5),
    "relative change storing a persist wait": threshold_alert(
        "g1",
        alertType="RELATIVE_CHANGE",
        operatorType="INCREASES_BY",
        threshold=20.0,
        triggerAfterPersistsDuration="ONE_HOUR",
    ),
}

# (action, the stored enabled state the action changes)
SWITCH_CASES = [
    ("enable", False),
    ("disable", True),
    ("enable_multiple", False),
    ("disable_multiple", True),
    ("enable_all", False),
    ("disable_all", True),
    ("toggle_status", False),
    ("toggle_status", True),
]
SWITCH_IDS = [
    "enable", "disable", "enable_multiple", "disable_multiple",
    "enable_all", "disable_all", "toggle on", "toggle off",
]


@pytest.mark.asyncio
class TestEnableDisableAndToggleCheckTheStoredAlert:
    """BACK-4825: switching an alert on or off runs the platform's rules on the stored body."""

    @pytest.mark.parametrize(
        "action, stored_enabled, wording",
        [
            ("enable", False, "before you enable this alert"),
            ("disable", True, "before you disable this alert"),
            ("toggle_status", True, "before you toggle this alert"),
        ],
    )
    async def test_a_stored_value_the_platform_refuses_is_named_and_nothing_is_sent(
        self, action, stored_enabled, wording
    ):
        platform = FakeAnomalyPlatform([_breaking_provider_alert(enabled=stored_enabled)])

        flagged, text = await answer(
            _tools_over(platform).handle_action(action, {"anomaly_id": "p1"})
        )

        assert flagged is True
        assert "stored periodDuration FIFTEEN_MINUTES" in text
        assert wording in text
        assert "in this update" not in text
        assert platform.updated_bodies == []

    @pytest.mark.parametrize(
        "action, stored_enabled",
        [
            ("enable_multiple", False),
            ("disable_multiple", True),
            ("enable_all", False),
            ("disable_all", True),
        ],
    )
    async def test_a_bulk_call_skips_the_refused_alert_and_changes_the_rest(
        self, action, stored_enabled
    ):
        platform = FakeAnomalyPlatform(
            [
                _breaking_provider_alert(enabled=stored_enabled),
                threshold_alert("a1", enabled=stored_enabled),
            ]
        )
        arguments = {} if action.endswith("_all") else {"anomaly_ids": ["p1", "a1"]}

        flagged, text = await answer(_tools_over(platform).handle_action(action, arguments))

        assert flagged is False
        assert [anomaly_id for anomaly_id, _ in platform.updated_bodies] == ["a1"]
        assert platform.store["a1"]["enabled"] is (not stored_enabled)
        assert platform.store["p1"]["enabled"] is stored_enabled
        refused = [line for line in text.splitlines() if "stored periodDuration FIFTEEN_MINUTES" in line]
        assert len(refused) == 1
        assert refused[0].startswith("Failed: ") and "p1" in refused[0]

    async def test_a_bulk_call_where_every_alert_is_refused_sends_nothing(self):
        platform = FakeAnomalyPlatform([_breaking_provider_alert(enabled=False)])

        flagged, text = await answer(
            _tools_over(platform).handle_action("enable_multiple", {"anomaly_ids": ["p1"]})
        )

        assert flagged is True
        assert "Failed: p1" in text
        assert "stored periodDuration FIFTEEN_MINUTES" in text
        assert platform.updated_bodies == []

    @pytest.mark.parametrize("shape", list(STORED_SHAPES))
    @pytest.mark.parametrize("action, stored_enabled", SWITCH_CASES, ids=SWITCH_IDS)
    async def test_valid_stored_alerts_behave_as_before_on_every_handler(
        self, action, stored_enabled, shape
    ):
        stored = {**STORED_SHAPES[shape], "enabled": stored_enabled}
        platform = FakeAnomalyPlatform([stored])

        flagged, text = await answer(
            _tools_over(platform).handle_action(action, _switch_arguments(action, "g1"))
        )

        assert flagged is False, text
        assert platform.updated_bodies == [("g1", {**stored, "enabled": not stored_enabled})]

    @pytest.mark.parametrize(
        "shape",
        ["budget kept on a window", "cost alert storing a floor", "relative change storing a persist wait"],
    )
    async def test_the_stored_shapes_reach_a_stored_value_exemption(self, shape):
        stored = STORED_SHAPES[shape]

        assert platform_rule_breach(stored) is not None
        assert platform_rule_breach(stored, stored) is None


@pytest.mark.asyncio
class TestABulkCallWhereNothingSucceededIsAnError:
    """BACK-4805: a bulk switch where every attempt failed carries the error flag."""

    @pytest.mark.parametrize("action", ["enable_multiple", "disable_multiple"])
    async def test_a_bulk_call_where_every_alert_failed_is_flagged(self, tools, action):
        flagged, text = await answer(
            tools.handle_action(action, {"anomaly_ids": ["x1", "x2", "x3"]})
        )

        assert flagged is True
        assert "**Successful:** 0" in text
        assert "**Failed:** 3" in text

    async def test_a_bulk_call_with_one_success_is_not_flagged(self):
        platform = FakeAnomalyPlatform([threshold_alert("a1", enabled=False)])

        flagged, text = await answer(
            _tools_over(platform).handle_action("enable_multiple", {"anomaly_ids": ["a1", "x1"]})
        )

        assert flagged is False
        assert "**Successful:** 1" in text and "**Failed:** 1" in text
        assert platform.store["a1"]["enabled"] is True

    @pytest.mark.parametrize("action, stored_enabled", [("enable_all", False), ("disable_all", True)])
    async def test_enable_all_where_every_attempt_failed_is_flagged(self, action, stored_enabled):
        platform = FakeAnomalyPlatform([threshold_alert("a1", enabled=stored_enabled)])
        platform.get_anomaly_by_id = AsyncMock(side_effect=RuntimeError("platform timed out"))

        flagged, text = await answer(
            _tools_over(platform).handle_action(action, {})
        )

        assert flagged is True
        assert "**Failed:** 1" in text
        assert "platform timed out" in text
        assert platform.updated_bodies == []

    async def test_enable_all_with_every_alert_already_enabled_is_not_flagged(self, tools):
        flagged, text = await answer(tools.handle_action("enable_all", {}))

        assert flagged is False
        assert "**Failed:** 0" in text

    async def test_a_nameless_alert_is_named_by_its_id_in_a_bulk_answer(self):
        platform = FakeAnomalyPlatform([threshold_alert("g1", name=None, enabled=False)])

        flagged, text = await answer(
            _tools_over(platform).handle_action("enable_all", {})
        )

        assert flagged is False
        assert "g1 (no name)" in text
        assert "None" not in text


REQUEST_COUNT = "REQUEST_COUNT"


@pytest.mark.asyncio
class TestRequestCountIsAMetricThePlatformHas:
    """BACK-4911: the platform added REQUEST_COUNT to AIAlertMetricType, so the MCP passes it through."""

    @pytest.mark.usefixtures("alert_owner_email")
    async def test_a_request_count_alert_is_created(self, platform, tools):
        alert = {
            "name": "Request volume",
            "alertType": "THRESHOLD",
            "metricType": REQUEST_COUNT,
            "operatorType": "GREATER_THAN",
            "threshold": 1000,
            "periodDuration": "DAILY",
        }

        flagged, text = await answer(tools.handle_action("create", {"anomaly_data": alert}))

        assert flagged is False, text
        assert platform.created_bodies[-1]["metricType"] == REQUEST_COUNT

    @pytest.mark.usefixtures("alert_owner_email")
    @pytest.mark.parametrize(
        "metric", ["request_count", "image_count", "duration", "tokens_per_request"]
    )
    async def test_a_detection_rule_naming_a_newer_metric_is_created(self, platform, tools, metric):
        """BACK-4965: detection_rules accept every metric the plain metricType does."""
        rule = {
            "rule_type": "THRESHOLD",
            "metric": metric,
            "operator": ">",
            "value": 1000,
            "time_window": "1h",
        }

        flagged, text = await answer(
            tools.handle_action(
                "create", {"anomaly_data": {"name": "Rule volume", "detection_rules": [rule]}}
            )
        )

        assert flagged is False, text
        assert platform.created_bodies[-1]["metricType"] == metric.upper()

    @pytest.mark.usefixtures("alert_owner_email")
    @pytest.mark.parametrize("action", ["create", "validate"])
    @pytest.mark.parametrize("spelling", ["minSampleCount", "min_sample_count"])
    async def test_a_quality_rate_detection_rule_keeps_its_sample_floor(
        self, platform, tools, action, spelling
    ):
        """BACK-4965 review: the floor is checked against the converted metric and sent."""
        alert = {
            "name": "Review quality",
            "detection_rules": [_QUALITY_RATE_RULE],
            "filters": [_TASK_TYPE_FILTER],
            spelling: 100,
        }

        flagged, text = await answer(tools.handle_action(action, {"anomaly_data": alert}))

        assert flagged is False, text
        if action == "create":
            sent = platform.created_bodies[-1]
            assert sent["metricType"] == "QUALITY_RATE"
            assert sent["minSampleCount"] == 100
        else:
            assert '"valid": true' in text

    @pytest.mark.usefixtures("alert_owner_email")
    async def test_a_sample_floor_on_a_non_quality_detection_rule_is_refused(self, platform, tools):
        rule = {**_QUALITY_RATE_RULE, "metric": "request_count"}
        alert = {"name": "Volume", "detection_rules": [rule], "minSampleCount": 100}

        flagged, text = await answer(tools.handle_action("create", {"anomaly_data": alert}))

        assert flagged is True
        assert "minSampleCount applies to QUALITY_RATE alerts only" in text
        assert "REQUEST_COUNT" in text
        assert platform.created_bodies == []

    @pytest.mark.usefixtures("alert_owner_email")
    async def test_a_sample_floor_below_one_on_a_quality_detection_rule_is_refused(self, platform, tools):
        alert = {
            "name": "Review quality",
            "detection_rules": [_QUALITY_RATE_RULE],
            "filters": [_TASK_TYPE_FILTER],
            "minSampleCount": 0,
        }

        flagged, text = await answer(tools.handle_action("create", {"anomaly_data": alert}))

        assert flagged is True
        assert "at least 1" in text
        assert platform.created_bodies == []

    async def test_an_alert_moved_to_request_count_is_updated(self, platform, tools):
        flagged, text = await answer(
            tools.handle_action(
                "update", {"anomaly_id": "a1", "anomaly_data": {"metricType": REQUEST_COUNT}}
            )
        )

        assert flagged is False, text
        assert _sent_body(platform)["metricType"] == REQUEST_COUNT
        assert platform.store["a1"]["metricType"] == REQUEST_COUNT

    @pytest.mark.parametrize("action, stored_enabled", [("enable", False), ("disable", True)])
    async def test_a_stored_request_count_alert_can_be_switched(self, action, stored_enabled):
        platform = FakeAnomalyPlatform(
            [threshold_alert("q1", metricType=REQUEST_COUNT, enabled=stored_enabled)]
        )

        flagged, text = await answer(
            _tools_over(platform).handle_action(action, {"anomaly_id": "q1"})
        )

        assert flagged is False, text
        assert platform.store["q1"]["enabled"] is (not stored_enabled)

    async def test_request_count_is_advertised_beside_requests_per_minute(self):
        from src.revenium_mcp_server.schema.alert_schema import get_alert_metrics_capabilities

        metrics = await get_alert_metrics_capabilities(None)

        assert REQUEST_COUNT in metrics["performance_metrics"]
        assert "REQUESTS_PER_MINUTE" in metrics["performance_metrics"]
