"""BACK-4706: create, validate, the update and its preview refuse every alert the platform's rule table refuses."""

from typing import Any, Dict, NamedTuple
from unittest.mock import AsyncMock, patch

import pytest

from src.revenium_mcp_server.alerts.update_fidelity import PLATFORM_ALERT_RULES
from src.revenium_mcp_server.client import ReveniumAPIError
from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement
from tests.unit.anomaly_platform_fake import FakeAnomalyPlatform, answer, threshold_alert

BASE_ALERT: Dict[str, Any] = {
    "name": "Rule table",
    "alertType": "THRESHOLD",
    "metricType": "TOTAL_COST",
    "operatorType": "GREATER_THAN",
    "threshold": 100,
    "periodDuration": "DAILY",
}
PROVIDER = {"dataSource": "PROVIDER"}
FIFTY_ONE_MODELS = [f"model-{index}" for index in range(51)]


def _row(dimension="MODEL", operator="IS", **value):
    return [{"dimension": dimension, "operator": operator, **value}]


class Breach(NamedTuple):
    """A create body and an update change that each break one rule, and the refusal's wording."""

    create: Dict[str, Any]
    update_id: str
    update: Dict[str, Any]
    says: str


BREACHES: Dict[str, Breach] = {
    "alert type is known": Breach(
        {"alertType": "THRESHOLDS"}, "a1", {"alertType": "THRESHOLDS"}, "THRESHOLDS"
    ),
    "data source is known": Breach(
        {"dataSource": "provider"}, "a1", {"dataSource": "provider"}, "SDK or PROVIDER"
    ),
    "provider alert type": Breach(
        {**PROVIDER, "alertType": "RELATIVE_CHANGE", "operatorType": "INCREASES_BY"},
        "p1",
        {"alertType": "RELATIVE_CHANGE", "operatorType": "INCREASES_BY"},
        "a provider-sourced alert takes THRESHOLD or CUMULATIVE_USAGE only",
    ),
    "metric is known": Breach(
        {"metricType": "TOKENS_PER_SECOND"}, "a1", {"metricType": "TOKENS_PER_SECOND"},
        "metricType TOKENS_PER_SECOND is not a metric the platform has",
    ),
    "provider metric": Breach(
        {**PROVIDER, "metricType": "ERROR_RATE"}, "p1", {"metricType": "ERROR_RATE"},
        "metricType ERROR_RATE is not supported for provider alerts",
    ),
    "filter dimension is known": Breach(
        {"filters": _row("DEPARTMENT", value="d1")}, "a1", {"filters": _row("DEPARTMENT", value="d1")},
        "filter dimension DEPARTMENT is not supported for AI alerts",
    ),
    "provider filter dimension": Breach(
        {**PROVIDER, "filters": _row("ORGANIZATION", value="o1")},
        "p1",
        {"filters": _row("ORGANIZATION", value="o1")},
        "filter dimension ORGANIZATION is not supported for provider alerts",
    ),
    "filter operator is known": Breach(
        {"filters": _row(operator="LIKE", value="gpt")}, "a1", {"filters": _row(operator="LIKE", value="gpt")},
        "LIKE",
    ),
    "IN filter values": Breach(
        {"filters": _row(operator="IN", values=FIFTY_ONE_MODELS)},
        "a1",
        {"filters": _row(operator="IN", values=FIFTY_ONE_MODELS)},
        "at most 50 entries",
    ),
    "scalar filter value": Breach(
        {"filters": _row(operator="IS")}, "a1", {"filters": _row(operator="IS")}, "value",
    ),
    "period by alert type and data source": Breach(
        {"periodDuration": "FIVE_MINUTES"}, "a1", {"periodDuration": "FIVE_MINUTES"}, "FIVE_MINUTES",
    ),
    "operator is accepted": Breach(
        {"operatorType": "EQUAL_TO"}, "a1", {"operatorType": "EQUAL_TO"}, "EQUAL_TO is not supported",
    ),
    "operator by alert type": Breach(
        {"operatorType": "INCREASES_BY"}, "a1", {"operatorType": "INCREASES_BY"}, "INCREASES_BY",
    ),
    "provider operator": Breach(
        {**PROVIDER, "operatorType": "PERCENT_INCREASE"}, "p1", {"operatorType": "PERCENT_INCREASE"},
        "PERCENT_INCREASE",
    ),
    "threshold is a number": Breach(
        {"threshold": "lots"}, "a1", {"threshold": "lots"}, "threshold",
    ),
    "persist period is known": Breach(
        {"triggerAfterPersistsDuration": "TEN_MINUTES"}, "a1", {"triggerAfterPersistsDuration": "TEN_MINUTES"},
        "triggerAfterPersistsDuration TEN_MINUTES is not a period the platform has",
    ),
    "no persist period on relative change": Breach(
        {"alertType": "RELATIVE_CHANGE", "operatorType": "INCREASES_BY",
         "triggerAfterPersistsDuration": "FIFTEEN_MINUTES"},
        "r1",
        {"triggerAfterPersistsDuration": "FIFTEEN_MINUTES"},
        "triggerAfterPersistsDuration is not supported on RELATIVE_CHANGE alerts",
    ),
    "groupBy is a dimension": Breach(
        {"groupBy": "MODELS"}, "a1", {"groupBy": "MODELS"}, "groupBy 'MODELS' is not a dimension",
    ),
    "provider groupBy": Breach(
        {**PROVIDER, "groupBy": "AGENT"}, "p1", {"groupBy": "AGENT"},
        "Provider alerts support grouping only by WORKSPACE, API_KEY, MODEL, PROVIDER",
    ),
    "QUALITY_RATE rule": Breach(
        {"metricType": "QUALITY_RATE"}, "a1", {"metricType": "QUALITY_RATE"}, "QUALITY_RATE",
    ),
}


class Pass(NamedTuple):
    """A create body and an update change that each sit inside one rule."""

    create: Dict[str, Any]
    update_id: str
    update: Dict[str, Any]


FIFTY_MODELS = FIFTY_ONE_MODELS[:50]
JOB_TYPE_ROW = _row("TASK_TYPE", value="summarize")

PASSES: Dict[str, Pass] = {
    "alert type is known": Pass({"alertType": "CUMULATIVE_USAGE"}, "a1", {"alertType": "CUMULATIVE_USAGE"}),
    "data source is known": Pass({"dataSource": "SDK"}, "a1", {"dataSource": "SDK"}),
    "provider alert type": Pass(
        {**PROVIDER, "alertType": "CUMULATIVE_USAGE"}, "p1", {"alertType": "CUMULATIVE_USAGE"}
    ),
    "metric is known": Pass(
        {"metricType": "TIME_TO_FIRST_TOKEN"}, "a1", {"metricType": "TIME_TO_FIRST_TOKEN"}
    ),
    "provider metric": Pass(
        {**PROVIDER, "metricType": "OUTPUT_TOKEN_COUNT"}, "p1", {"metricType": "OUTPUT_TOKEN_COUNT"}
    ),
    "filter dimension is known": Pass(
        {"filters": _row("AGENT", value="bot")}, "a1", {"filters": _row("AGENT", value="bot")}
    ),
    "provider filter dimension": Pass(
        {**PROVIDER, "filters": _row("API_KEY", value="k1")}, "p1", {"filters": _row("API_KEY", value="k1")}
    ),
    "filter operator is known": Pass(
        {"filters": _row(operator="STARTS_WITH", value="gpt")},
        "a1",
        {"filters": _row(operator="STARTS_WITH", value="gpt")},
    ),
    "IN filter values": Pass(
        {"filters": _row(operator="IN", values=FIFTY_MODELS)},
        "a1",
        {"filters": _row(operator="IN", values=FIFTY_MODELS)},
    ),
    "scalar filter value": Pass(
        {"filters": _row(value="gpt-4o")}, "a1", {"filters": _row(value="gpt-4o")}
    ),
    "period by alert type and data source": Pass(
        {"periodDuration": "THIRTY_DAYS"}, "a1", {"periodDuration": "THIRTY_DAYS"}
    ),
    "operator is accepted": Pass(
        {"operatorType": "LESS_THAN_OR_EQUAL_TO"}, "a1", {"operatorType": "LESS_THAN_OR_EQUAL_TO"}
    ),
    "operator by alert type": Pass(
        {"alertType": "RELATIVE_CHANGE", "operatorType": "PERCENT_INCREASE"},
        "r1",
        {"operatorType": "PERCENT_INCREASE"},
    ),
    "provider operator": Pass({**PROVIDER, "operatorType": "LESS_THAN"}, "p1", {"operatorType": "LESS_THAN"}),
    "threshold is a number": Pass({"threshold": 250.5}, "a1", {"threshold": 250.5}),
    "persist period is known": Pass(
        {"triggerAfterPersistsDuration": "FIFTEEN_MINUTES"},
        "a1",
        {"triggerAfterPersistsDuration": "FIFTEEN_MINUTES"},
    ),
    "no persist period on relative change": Pass(
        {"alertType": "RELATIVE_CHANGE", "operatorType": "INCREASES_BY", "triggerAfterPersistsDuration": ""},
        "r2",
        {"triggerAfterPersistsDuration": "FIFTEEN_MINUTES"},
    ),
    "groupBy is a dimension": Pass({"groupBy": "MODEL"}, "a1", {"groupBy": "MODEL"}),
    "provider groupBy": Pass({**PROVIDER, "groupBy": "WORKSPACE"}, "p1", {"groupBy": "WORKSPACE"}),
    "QUALITY_RATE rule": Pass(
        {"metricType": "QUALITY_RATE", "filters": JOB_TYPE_ROW},
        "a1",
        {"metricType": "QUALITY_RATE", "filters": JOB_TYPE_ROW},
    ),
}

def _platform():
    return FakeAnomalyPlatform(
        [
            threshold_alert("a1", periodDuration="DAILY"),
            threshold_alert("p1", dataSource="PROVIDER", periodDuration="DAILY"),
            threshold_alert(
                "r1", alertType="RELATIVE_CHANGE", operatorType="INCREASES_BY", periodDuration="DAILY"
            ),
            threshold_alert(
                "r2",
                alertType="RELATIVE_CHANGE",
                operatorType="INCREASES_BY",
                periodDuration="DAILY",
                triggerAfterPersistsDuration="FIFTEEN_MINUTES",
            ),
        ]
    )


def _tools(platform):
    tools = AlertManagement()
    tools.get_client = AsyncMock(return_value=platform)
    return tools


def test_every_platform_rule_has_a_breach_and_a_pass_case():
    names = {rule.name for rule in PLATFORM_ALERT_RULES}
    assert set(BREACHES) == names
    assert set(PASSES) == names


@pytest.mark.asyncio
@pytest.mark.parametrize("rule", sorted(BREACHES))
@pytest.mark.usefixtures("alert_owner_email")
async def test_validate_refuses_what_create_refuses_for_every_platform_rule(rule):
    breach = BREACHES[rule]
    platform = _platform()
    tools = _tools(platform)
    alert = {**BASE_ALERT, **breach.create}

    validated = await answer(tools.handle_action("validate", {"anomaly_data": dict(alert)}))
    created = await answer(tools.handle_action("create", {"anomaly_data": dict(alert)}))

    assert validated == created
    assert validated[0] is True
    assert breach.says in validated[1]
    assert '"valid": true' not in validated[1]
    assert platform.created_bodies == []


@pytest.mark.asyncio
@pytest.mark.parametrize("rule", sorted(BREACHES))
async def test_the_update_preview_refuses_what_the_live_update_refuses_for_every_platform_rule(rule):
    breach = BREACHES[rule]
    platform = _platform()
    tools = _tools(platform)
    update = {"anomaly_id": breach.update_id, "anomaly_data": dict(breach.update)}

    dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
    live = await answer(tools.handle_action("update", update))

    assert dry == live
    assert _refused(live)
    assert breach.says in live[1]
    assert "Dry Run Successful" not in dry[1]
    assert platform.updated_bodies == []


def _refused(result):
    # The update's older operator, filter-row and QUALITY_RATE refusals come back as an
    # **Error** text without the error flag; PR 479 owns making the flag consistent.
    flagged, text = result
    return flagged or text.startswith("**Error**")


@pytest.mark.asyncio
@pytest.mark.parametrize("rule", sorted(PASSES))
@pytest.mark.usefixtures("alert_owner_email")
async def test_validate_accepts_what_create_sends_for_every_platform_rule(rule):
    platform = _platform()
    tools = _tools(platform)
    alert = {**BASE_ALERT, **PASSES[rule].create}

    validated = await answer(tools.handle_action("validate", {"anomaly_data": dict(alert)}))
    created = await answer(tools.handle_action("create", {"anomaly_data": dict(alert)}))

    assert validated[0] is False and '"valid": true' in validated[1]
    assert created[0] is False and len(platform.created_bodies) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("rule", sorted(PASSES))
async def test_the_update_preview_accepts_what_the_live_update_sends_for_every_platform_rule(rule):
    passing = PASSES[rule]
    platform = _platform()
    tools = _tools(platform)
    update = {"anomaly_id": passing.update_id, "anomaly_data": dict(passing.update)}

    dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
    assert dry[0] is False and "Dry Run Successful" in dry[1]
    assert platform.updated_bodies == []

    live = await answer(tools.handle_action("update", update))
    assert not _refused(live)
    assert platform.updated_bodies


@pytest.mark.asyncio
@pytest.mark.usefixtures("alert_owner_email")
async def test_an_alert_breaking_no_rule_is_valid_and_created():
    platform = _platform()
    tools = _tools(platform)

    validated = await answer(tools.handle_action("validate", {"anomaly_data": dict(BASE_ALERT)}))
    created = await answer(tools.handle_action("create", {"anomaly_data": dict(BASE_ALERT)}))

    assert validated[0] is False and '"valid": true' in validated[1]
    assert created[0] is False and len(platform.created_bodies) == 1


STORED_BREACHES = {
    "period": ({"periodDuration": "FIVE_MINUTES"}, "periodDuration FIVE_MINUTES"),
    "operator": ({"operatorType": "EQUAL_TO"}, "operatorType EQUAL_TO"),
    "operator by alert type": ({"operatorType": "INCREASES_BY"}, "operatorType INCREASES_BY"),
    "metric": ({"metricType": "TOKENS_PER_SECOND"}, "metricType TOKENS_PER_SECOND"),
    "filter dimension": ({"filters": _row("DEPARTMENT", value="d1")}, "filters DEPARTMENT"),
    "provider alert type": (
        {**PROVIDER, "alertType": "RELATIVE_CHANGE", "operatorType": "INCREASES_BY"},
        "alertType RELATIVE_CHANGE",
    ),
    "provider period": ({**PROVIDER, "periodDuration": "ONE_HOUR"}, "periodDuration ONE_HOUR"),
    "provider metric": ({**PROVIDER, "metricType": "ERROR_RATE"}, "metricType ERROR_RATE"),
    "provider filter dimension": (
        {**PROVIDER, "filters": _row("ORGANIZATION", value="o1")}, "filters ORGANIZATION"
    ),
    "provider groupBy": ({**PROVIDER, "groupBy": "AGENT"}, "groupBy AGENT"),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("stored_rule", sorted(STORED_BREACHES))
async def test_a_rename_of_a_stored_alert_breaking_a_rule_is_refused_by_preview_and_update(stored_rule):
    stored, says = STORED_BREACHES[stored_rule]
    platform = FakeAnomalyPlatform([threshold_alert("old", **{"periodDuration": "DAILY", **stored})])
    tools = _tools(platform)
    update = {"anomaly_id": "old", "anomaly_data": {"name": "Renamed"}}

    dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
    live = await answer(tools.handle_action("update", update))

    assert dry == live
    assert dry[0] is True
    assert f"This alert's stored {says} is no longer accepted" in live[1]
    assert "in this update" in live[1]
    assert platform.updated_bodies == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stored, fix",
    [
        ({"periodDuration": "FIVE_MINUTES"}, {"periodDuration": "DAILY"}),
        ({"operatorType": "EQUAL_TO"}, {"operatorType": "GREATER_THAN"}),
        ({**PROVIDER, "metricType": "ERROR_RATE"}, {"metricType": "TOTAL_COST"}),
    ],
    ids=["period", "operator", "provider metric"],
)
async def test_an_update_that_fixes_the_stored_field_while_renaming_still_updates(stored, fix):
    platform = FakeAnomalyPlatform([threshold_alert("old", **{"periodDuration": "DAILY", **stored})])
    tools = _tools(platform)
    update = {"anomaly_id": "old", "anomaly_data": {"name": "Renamed", **fix}}

    dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
    assert dry[0] is False and "Dry Run Successful" in dry[1]

    live = await answer(tools.handle_action("update", update))
    assert not _refused(live)
    assert platform.updated_bodies


@pytest.mark.asyncio
async def test_a_rename_of_a_budget_whose_stored_period_the_platform_keeps_still_updates():
    platform = FakeAnomalyPlatform(
        [threshold_alert("b1", alertType="CUMULATIVE_USAGE", periodDuration="ONE_HOUR")]
    )
    tools = _tools(platform)
    update = {"anomaly_id": "b1", "anomaly_data": {"name": "Renamed"}}

    dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
    assert dry[0] is False

    await tools.handle_action("update", update)
    assert platform.updated_bodies


NOT_JSON_NUMBERS = ["NaN", "Infinity", "1_000", True]


@pytest.mark.asyncio
@pytest.mark.parametrize("threshold", NOT_JSON_NUMBERS, ids=repr)
@pytest.mark.usefixtures("alert_owner_email")
async def test_validate_refuses_a_threshold_the_platform_cannot_read_as_a_number(threshold):
    tools = _tools(_platform())

    validated = await answer(
        tools.handle_action("validate", {"anomaly_data": {**BASE_ALERT, "threshold": threshold}})
    )

    assert validated[0] is True
    assert "threshold must be a number" in validated[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("threshold", NOT_JSON_NUMBERS, ids=repr)
async def test_the_update_preview_refuses_a_threshold_the_platform_cannot_read_as_a_number(threshold):
    platform = _platform()
    tools = _tools(platform)
    update = {"anomaly_id": "a1", "anomaly_data": {"threshold": threshold}}

    dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
    live = await answer(tools.handle_action("update", update))

    assert dry == live
    assert dry[0] is True
    assert "threshold must be a number" in live[1]
    assert platform.updated_bodies == []


@pytest.mark.asyncio
@pytest.mark.parametrize("threshold", ["12.5", 12.5], ids=repr)
@pytest.mark.usefixtures("alert_owner_email")
async def test_a_numeric_threshold_is_accepted_and_sent_as_a_number(threshold):
    platform = _platform()
    tools = _tools(platform)

    validated = await answer(
        tools.handle_action("validate", {"anomaly_data": {**BASE_ALERT, "threshold": threshold}})
    )
    assert validated[0] is False and '"valid": true' in validated[1]
    await tools.handle_action("create", {"anomaly_data": {**BASE_ALERT, "threshold": threshold}})
    assert platform.created_bodies[-1]["threshold"] == 12.5

    update = {"anomaly_id": "a1", "anomaly_data": {"threshold": threshold}}
    dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
    assert dry[0] is False and '"threshold": 12.5' in dry[1]
    await tools.handle_action("update", update)
    sent = platform.updated_bodies[-1][1]["threshold"]
    assert sent == 12.5 and not isinstance(sent, str)


OWNER = {"notificationAddresses": ["owner@example.test"]}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("threshold", "number"), [(".5", 0.5), ("5.", 5.0), (" .5 ", 0.5)], ids=repr
)
async def test_a_threshold_with_a_bare_decimal_point_is_accepted_and_sent_as_a_number(threshold, number):
    """BACK-4823: the platform reads `.5` and `5.` as numbers, so the tool accepts them too."""
    platform = _platform()
    tools = _tools(platform)
    alert = {**BASE_ALERT, **OWNER, "threshold": threshold}

    validated = await answer(tools.handle_action("validate", {"anomaly_data": dict(alert)}))
    assert validated[0] is False and '"valid": true' in validated[1]
    previewed = await answer(tools.handle_action("create", {"anomaly_data": dict(alert), "dry_run": True}))
    assert previewed[0] is False and "Dry Run Successful" in previewed[1]
    assert platform.created_bodies == []
    await tools.handle_action("create", {"anomaly_data": dict(alert)})
    created = platform.created_bodies[-1]["threshold"]
    assert isinstance(created, float) and created == number

    update = {"anomaly_id": "a1", "anomaly_data": {"threshold": threshold}}
    dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
    assert dry[0] is False and "Dry Run Successful" in dry[1]
    await tools.handle_action("update", update)
    sent = platform.updated_bodies[-1][1]["threshold"]
    assert isinstance(sent, float) and sent == number


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "threshold", ["abc", "NaN", "1e", ".", "", "5.5.5", "+", ".e5", "1.2e"], ids=repr
)
async def test_a_threshold_that_is_not_a_number_is_still_refused(threshold):
    platform = _platform()
    tools = _tools(platform)

    validated = await answer(
        tools.handle_action("validate", {"anomaly_data": {**BASE_ALERT, **OWNER, "threshold": threshold}})
    )
    assert validated[0] is True
    assert "threshold must be a number" in validated[1]

    update = {"anomaly_id": "a1", "anomaly_data": {"threshold": threshold}}
    dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
    live = await answer(tools.handle_action("update", update))
    assert dry == live
    assert dry[0] is True
    assert "threshold must be a number" in live[1]
    assert platform.created_bodies == [] and platform.updated_bodies == []


QUICK_CREATE = {"name": "Quick", "threshold": 5, "email": "owner@example.test"}


@pytest.fixture
def no_configured_defaults():
    with patch(
        "src.revenium_mcp_server.common.default_slack_configuration.get_config_value",
        return_value=None,
    ):
        yield


@pytest.mark.asyncio
@pytest.mark.usefixtures("no_configured_defaults")
async def test_a_quick_create_preview_refuses_a_metric_the_create_refuses():
    """BACK-4802: the create_simple dry run checks what the live create checks."""
    platform = _platform()
    tools = _tools(platform)
    arguments = {**QUICK_CREATE, "metric": "TOKENS_PER_SECOND"}

    dry = await answer(tools.handle_action("create_simple", {**arguments, "dry_run": True}))
    live = await answer(tools.handle_action("create_simple", arguments))

    assert dry == live
    assert dry[0] is True
    assert "is not a metric the platform has" in dry[1]
    assert "Dry Run Successful" not in dry[1]
    assert platform.created_bodies == []


@pytest.mark.asyncio
@pytest.mark.usefixtures("no_configured_defaults")
async def test_a_quick_create_preview_of_a_metric_the_platform_has_is_successful():
    platform = _platform()
    tools = _tools(platform)

    dry = await answer(
        tools.handle_action("create_simple", {**QUICK_CREATE, "metric": "TOTAL_COST", "dry_run": True})
    )

    assert dry[0] is False and "Dry Run Successful" in dry[1]
    assert '"operation": "create_simple"' in dry[1]
    assert platform.created_bodies == []


def _enums(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "enum":
                yield from value
            else:
                yield from _enums(value)
    elif isinstance(node, list):
        for value in node:
            yield from _enums(value)


def test_no_published_metric_list_names_a_per_second_metric():
    """BACK-4802: the platform has no per-second metric, so no published list offers one."""
    from src.revenium_mcp_server.alert_metrics import METRIC_BUCKETS
    from src.revenium_mcp_server.json_schema_validator import JSONSchemaValidator

    bucketed = [metric for metrics in METRIC_BUCKETS.values() for metric in metrics]
    enumerated = [str(value) for value in _enums(JSONSchemaValidator()._build_alerts_schema())]

    assert [name for name in bucketed if "PER_SECOND" in name] == []
    assert [name for name in enumerated if "PER_SECOND" in name.upper()] == []


def _published_examples():
    from src.revenium_mcp_server.schema_discovery import SchemaDiscoveryEngine

    examples = SchemaDiscoveryEngine().get_agent_friendly_summary("anomalies")[
        "natural_language_examples"
    ]
    return [
        pytest.param(text, marks=pytest.mark.xfail(strict=True, reason=PARSER_GAPS[text]))
        if text in PARSER_GAPS
        else text
        for text in examples
    ]


PARSER_GAPS = {
    "Alert when OpenAI model costs exceed $50 per hour": (
        "the text parser reads 'model costs' as a MODEL filter on 'costs', which the "
        "create refuses; the text parser belongs to the sibling lane"
    ),
}


@pytest.mark.asyncio
@pytest.mark.usefixtures("no_configured_defaults")
@pytest.mark.parametrize("text", _published_examples())
async def test_every_natural_language_example_creates_without_a_per_second_refusal(text):
    """BACK-4802: an example the tool publishes never resolves to a metric the platform lacks."""
    platform = _platform()
    tools = _tools(platform)

    result = await answer(
        tools.handle_action("create_from_text", {"text": text, "email": "owner@example.test"})
    )

    assert result[0] is False, result[1]
    assert len(platform.created_bodies) == 1
    assert "PER_SECOND" not in result[1].upper()
    assert "not one the platform measures" not in result[1]
    assert all("PER_SECOND" not in str(body.get("metricType")) for body in platform.created_bodies)


EMPTY_VALUE_ROW = _row(value="")


@pytest.mark.asyncio
async def test_a_scalar_filter_with_an_empty_value_is_accepted_and_sent():
    """BACK-4803: the platform stores a filter row whose value is empty, so the tool sends it."""
    platform = _platform()
    tools = _tools(platform)
    alert = {**BASE_ALERT, **OWNER, "filters": EMPTY_VALUE_ROW}

    validated = await answer(tools.handle_action("validate", {"anomaly_data": dict(alert)}))
    assert validated[0] is False and '"valid": true' in validated[1]
    await tools.handle_action("create", {"anomaly_data": dict(alert)})
    assert platform.created_bodies[-1]["filters"] == EMPTY_VALUE_ROW

    update = {"anomaly_id": "a1", "anomaly_data": {"filters": EMPTY_VALUE_ROW}}
    dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
    assert dry[0] is False and "Dry Run Successful" in dry[1]
    await tools.handle_action("update", update)
    assert platform.updated_bodies[-1][1]["filters"] == EMPTY_VALUE_ROW


@pytest.mark.asyncio
async def test_a_friendly_filter_row_without_a_value_is_still_refused():
    platform = _platform()
    tools = _tools(platform)
    alert = {
        "name": "Friendly filter",
        **OWNER,
        "detection_rules": [
            {"rule_type": "THRESHOLD", "metric": "total_cost", "operator": ">", "value": 5}
        ],
        "filters": [{"field": "model", "operator": "is"}],
    }

    validated = await answer(tools.handle_action("validate", {"anomaly_data": alert}))

    assert validated[0] is True
    assert "Filter operator IS requires a" in validated[1]
    assert platform.created_bodies == []


@pytest.mark.asyncio
async def test_an_empty_task_type_value_on_a_quality_rate_alert_is_still_refused():
    platform = _platform()
    tools = _tools(platform)
    alert = {**BASE_ALERT, **OWNER, "metricType": "QUALITY_RATE", "filters": _row("TASK_TYPE", value="")}

    validated = await answer(tools.handle_action("validate", {"anomaly_data": alert}))

    assert validated[0] is True
    assert "needs the job type name as its value" in validated[1]


class FloorStoringPlatform(FakeAnomalyPlatform):
    """The platform stores minSampleCount on every metric and reads it on QUALITY_RATE only."""

    @staticmethod
    def _stored(body):
        stored = FakeAnomalyPlatform._stored(body)
        if "minSampleCount" in body:
            stored["minSampleCount"] = body["minSampleCount"]
        return stored


def _cost_alert_storing_a_floor(floor=5):
    return FloorStoringPlatform([threshold_alert("m1", periodDuration="DAILY", minSampleCount=floor)])


@pytest.mark.asyncio
async def test_a_rename_of_an_alert_storing_min_sample_count_on_a_cost_metric_still_updates():
    """BACK-4803: a value the alert already stores and the update leaves alone is not refused."""
    platform = _cost_alert_storing_a_floor()
    tools = _tools(platform)
    update = {"anomaly_id": "m1", "anomaly_data": {"name": "Renamed"}}

    dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
    assert dry[0] is False and "Dry Run Successful" in dry[1]

    live = await answer(tools.handle_action("update", update))
    assert not _refused(live)
    sent = platform.updated_bodies[-1][1]
    assert sent["name"] == "Renamed" and sent["minSampleCount"] == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("floor", [7, 0], ids=["setting", "zeroing"])
async def test_changing_min_sample_count_on_a_cost_alert_is_still_refused(floor):
    platform = _cost_alert_storing_a_floor()
    tools = _tools(platform)
    update = {"anomaly_id": "m1", "anomaly_data": {"minSampleCount": floor}}

    dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
    live = await answer(tools.handle_action("update", update))

    assert dry == live
    assert _refused(live)
    assert "minSampleCount applies to QUALITY_RATE alerts only" in live[1]
    assert platform.updated_bodies == []


@pytest.mark.asyncio
async def test_a_null_min_sample_count_on_a_cost_alert_keeps_the_stored_floor():
    """The platform keeps a stored minSampleCount when an update sends null, so null changes nothing."""
    platform = _cost_alert_storing_a_floor()
    tools = _tools(platform)

    live = await answer(
        tools.handle_action("update", {"anomaly_id": "m1", "anomaly_data": {"minSampleCount": None}})
    )

    assert not _refused(live)
    assert "not fully updated" not in live[1]
    assert platform.updated_bodies[-1][1]["minSampleCount"] == 5
    assert platform.store["m1"]["minSampleCount"] == 5


@pytest.mark.asyncio
async def test_moving_an_alert_off_quality_rate_with_a_stored_floor_is_refused():
    platform = FakeAnomalyPlatform(
        [
            threshold_alert(
                "q1",
                periodDuration="DAILY",
                metricType="QUALITY_RATE",
                filters=JOB_TYPE_ROW,
                minSampleCount=5,
            )
        ]
    )
    tools = _tools(platform)
    update = {"anomaly_id": "q1", "anomaly_data": {"metricType": "TOTAL_COST"}}

    dry = await answer(tools.handle_action("update", {**update, "dry_run": True}))
    live = await answer(tools.handle_action("update", update))

    assert dry == live
    assert _refused(live)
    assert "minSampleCount" in live[1]
    assert platform.updated_bodies == []


UNKNOWN_SLACK = "zzzzzz"


async def _outcome(call):
    """answer(), plus the platform error the tool re-raises for the server boundary to render."""
    try:
        return await answer(call)
    except ReveniumAPIError as exc:
        return True, exc.message


def _invalid_anomaly_id_error():
    """What the client raises when the platform cannot decode an id in an anomaly write."""
    return ReveniumAPIError(
        "Invalid Anomaly ID\n\nThe provided anomaly ID is not valid or does not exist.",
        400,
        {"error_data": {"message": "Failed to decode hashed id"}},
    )


class SlackCheckingPlatform(FakeAnomalyPlatform):
    """Refuses an anomaly write that names a Slack configuration in `refused`, and counts lookups."""

    def __init__(self, anomalies=(), known=(), refused=(UNKNOWN_SLACK,), lookup_error=None):
        super().__init__(anomalies)
        self.known = set(known)
        self.refused = set(refused)
        self.lookup_error = lookup_error
        self.slack_lookups = []

    def _refuse(self, body):
        if self.refused & set(body.get("slackConfigurations") or []):
            raise _invalid_anomaly_id_error()

    async def create_anomaly(self, body):
        self._refuse(body)
        return await super().create_anomaly(body)

    async def update_anomaly(self, anomaly_id, body):
        self._refuse(body)
        return await super().update_anomaly(anomaly_id, body)

    async def get_slack_configuration_by_id(self, config_id):
        self.slack_lookups.append(config_id)
        if self.lookup_error is not None:
            raise self.lookup_error
        if config_id not in self.known:
            raise ReveniumAPIError("HTTP 404: not found", 404, {"error_data": "not found"})
        return {"id": config_id}


BUDGET_WITH_SLACK = {
    "name": "Budget",
    "threshold": 500,
    "period": "monthly",
    "email": "owner@example.test",
    "slack_config_id": UNKNOWN_SLACK,
}


@pytest.mark.asyncio
async def test_an_unknown_slack_configuration_is_named_instead_of_the_alert():
    """BACK-4803: a Slack id the organization lacks is named, not reported as a bad alert id."""
    platform = SlackCheckingPlatform([threshold_alert("a1", periodDuration="DAILY")])
    tools = _tools(platform)

    created = await _outcome(tools.handle_action("create_cumulative_usage_alert", dict(BUDGET_WITH_SLACK)))
    updated = await _outcome(
        tools.handle_action("update", {"anomaly_id": "a1", "slack_config_id": UNKNOWN_SLACK})
    )

    for result, verb in ((created, "created"), (updated, "updated")):
        assert result[0] is True
        assert "slackConfigurations" in result[1]
        assert f"Slack configuration {UNKNOWN_SLACK} was not found" in result[1]
        assert f"nothing was {verb}" in result[1]
        assert "Anomaly ID" not in result[1]
    assert platform.slack_lookups == [UNKNOWN_SLACK, UNKNOWN_SLACK]
    assert platform.created_bodies == [] and platform.updated_bodies == []


@pytest.mark.asyncio
async def test_a_slack_lookup_answered_403_refuses_create_and_update_as_not_found():
    """BACK-4679: that endpoint answers 403 for an id it does not hold, as setup_status reads it."""
    forbidden = ReveniumAPIError("HTTP 403: Access Denied", 403, {"error_data": "Access Denied"})
    platform = SlackCheckingPlatform([threshold_alert("a1", periodDuration="DAILY")], lookup_error=forbidden)
    tools = _tools(platform)

    created = await _outcome(tools.handle_action("create_cumulative_usage_alert", dict(BUDGET_WITH_SLACK)))
    updated = await _outcome(
        tools.handle_action("update", {"anomaly_id": "a1", "slack_config_id": UNKNOWN_SLACK})
    )

    for result, verb in ((created, "created"), (updated, "updated")):
        assert result[0] is True
        assert f"Slack configuration {UNKNOWN_SLACK} was not found in this organization" in result[1]
        assert f"nothing was {verb}" in result[1]
        assert "Anomaly ID" not in result[1]
    assert platform.slack_lookups == [UNKNOWN_SLACK, UNKNOWN_SLACK]
    assert platform.created_bodies == [] and platform.updated_bodies == []


@pytest.mark.asyncio
async def test_a_refused_update_that_sends_no_slack_configuration_keeps_the_platform_error():
    """BACK-4803: a stored Slack id the update never sends is not blamed for its refusal."""
    platform = SlackCheckingPlatform(
        [threshold_alert("a1", periodDuration="DAILY", slackConfigurations=[UNKNOWN_SLACK])]
    )
    tools = _tools(platform)

    updated = await _outcome(
        tools.handle_action("update", {"anomaly_id": "a1", "anomaly_data": {"name": "Renamed"}})
    )

    assert updated[0] is True
    assert _invalid_anomaly_id_error().message in updated[1]
    assert "was not found in this organization" not in updated[1]
    assert platform.slack_lookups == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "known, lookup_error",
    [
        ((UNKNOWN_SLACK,), None),
        ((), ReveniumAPIError("HTTP 500: platform error", 500, {"error_data": "boom"})),
    ],
    ids=["every configuration exists", "the lookup fails for another reason"],
)
async def test_a_refused_create_the_slack_lookup_cannot_explain_keeps_the_platform_error(known, lookup_error):
    platform = SlackCheckingPlatform(known=known, lookup_error=lookup_error)
    tools = _tools(platform)

    created = await _outcome(tools.handle_action("create_cumulative_usage_alert", dict(BUDGET_WITH_SLACK)))

    assert created[0] is True
    assert _invalid_anomaly_id_error().message in created[1]
    assert "was not found in this organization" not in created[1]
    assert platform.slack_lookups == [UNKNOWN_SLACK]


@pytest.mark.asyncio
async def test_a_successful_create_looks_up_its_slack_configuration_only_to_name_it():
    platform = SlackCheckingPlatform(known=("good01",), refused=())
    tools = _tools(platform)

    created = await answer(
        tools.handle_action("create_cumulative_usage_alert", {**BUDGET_WITH_SLACK, "slack_config_id": "good01"})
    )

    assert created[0] is False
    assert platform.created_bodies[-1]["slackConfigurations"] == ["good01"]
    assert platform.slack_lookups == ["good01"]
