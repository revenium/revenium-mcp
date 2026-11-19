"""BACK-3977: a detection_rules create sends a dimension-format filter row as the caller wrote it."""

from unittest.mock import AsyncMock, patch

import pytest

from src.revenium_mcp_server.alerts.anomaly_manager import AnomalyManager
from src.revenium_mcp_server.common.error_handling import ErrorCodes, ToolError
from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement
from src.revenium_mcp_server.validators import InputValidator, _is_dimension_format_row
from tests.unit.anomaly_platform_fake import FakeAnomalyPlatform, threshold_alert
from tests.unit.test_tool_config_registry_m4 import _call_through_the_boundary


def _rules_payload(filters):
    return {
        "name": "Filtered spend",
        "detection_rules": [
            {"rule_type": "THRESHOLD", "metric": "total_cost", "operator": ">", "value": 50, "time_window": "1h"}
        ],
        "notificationAddresses": ["ops@example.com"],
        "filters": filters,
    }


def _created_filters(filters):
    return AnomalyManager().prepare_create(_rules_payload(filters), "team-1")["filters"]


@pytest.mark.parametrize(
    "row",
    [
        pytest.param({"dimension": "MODEL", "operator": "IS", "value": "gpt-4"}, id="is"),
        pytest.param({"dimension": "PROVIDER", "operator": "CONTAINS", "value": "openai"}, id="contains"),
        pytest.param({"dimension": "MODEL", "operator": "IN", "values": ["gpt-4", "claude-sonnet-4-5"]}, id="in"),
    ],
)
def test_a_dimension_format_row_is_sent_as_written(row):
    assert _created_filters([row]) == [row]


def test_a_dimension_format_row_is_normalized_like_the_direct_create():
    row = {"dimension": "model", "operator": "equals", "value": "gpt-4"}

    assert _created_filters([row]) == [{"dimension": "MODEL", "operator": "IS", "value": "gpt-4"}]


def test_a_field_format_row_still_converts():
    row = {"field": "model", "operator": "equals", "value": "gpt-4"}

    assert _created_filters([row]) == [{"dimension": "MODEL", "operator": "IS", "value": "gpt-4"}]


def test_rows_in_both_shapes_each_keep_their_dimension():
    rows = [
        {"field": "provider", "operator": "contains", "value": "openai"},
        {"dimension": "MODEL", "operator": "IN", "values": ["gpt-4"]},
    ]

    assert _created_filters(rows) == [
        {"dimension": "PROVIDER", "operator": "CONTAINS", "value": "openai"},
        {"dimension": "MODEL", "operator": "IN", "values": ["gpt-4"]},
    ]


@pytest.mark.parametrize(
    "row",
    [
        pytest.param({"operator": "IS", "value": "gpt-4"}, id="neither"),
        pytest.param({"dimension": "", "operator": "IS", "value": "gpt-4"}, id="blank_dimension"),
        pytest.param({"field": "  ", "operator": "IS", "value": "gpt-4"}, id="blank_field"),
    ],
)
def test_a_row_naming_no_dimension_is_refused_naming_both_shapes(row):
    with pytest.raises(ToolError) as refusal:
        _created_filters([row])

    assert refusal.value.error_code == ErrorCodes.VALIDATION_ERROR
    assert refusal.value.field == "filters"
    assert "names no dimension" in refusal.value.message
    suggestions = " ".join(refusal.value.suggestions)
    assert "{'dimension': 'MODEL', 'operator': 'IS', 'value': 'gpt-4'}" in suggestions
    assert "{'field': 'model', 'operator': 'is', 'value': 'gpt-4'}" in suggestions


def test_a_row_naming_its_dimension_twice_is_refused():
    row = {"dimension": "MODEL", "field": "provider", "operator": "IS", "value": "gpt-4"}

    with pytest.raises(ToolError) as refusal:
        _created_filters([row])

    assert refusal.value.field == "filters"
    assert "names its dimension twice" in refusal.value.message


def test_the_conversion_alone_passes_a_dimension_format_row_through():
    row = {"dimension": "MODEL", "operator": "IS", "value": "gpt-4"}

    assert InputValidator.convert_filters_to_api_format([row]) == [row]


@pytest.mark.parametrize(
    "row, expected",
    [
        pytest.param({"dimension": "MODEL", "operator": "IS", "value": "gpt-4"}, True, id="dimension"),
        pytest.param({"field": "model", "operator": "is", "value": "gpt-4"}, False, id="field"),
        pytest.param({"operator": "IS", "value": "gpt-4"}, False, id="neither"),
        pytest.param({"dimension": "MODEL", "field": "model", "operator": "IS", "value": "gpt-4"}, False, id="both"),
    ],
)
def test_the_shape_check_only_answers_and_never_refuses(row, expected):
    assert _is_dimension_format_row(row) is expected


DIMENSION_ROW = {"dimension": "MODEL", "operator": "IS", "value": "gpt-4"}
FIELD_ROW = {"field": "provider", "operator": "contains", "value": "openai"}
CONVERTED_FIELD_ROW = {"dimension": "PROVIDER", "operator": "CONTAINS", "value": "openai"}
NEITHER_ROW = {"operator": "IS", "value": "x"}
BOTH_ROW = {"dimension": "MODEL", "field": "model", "operator": "IS", "value": "x"}
UNSHAPED_ROWS = [
    pytest.param(NEITHER_ROW, "names no dimension", id="neither"),
    pytest.param(BOTH_ROW, "names its dimension twice", id="both"),
]
ROWS_BEFORE_IT = [
    pytest.param([FIELD_ROW], id="after_a_field_row"),
    pytest.param([DIMENSION_ROW], id="after_a_dimension_row"),
    pytest.param([], id="first"),
]
DIRECT_ALERT = {
    "name": "Direct filtered spend",
    "alertType": "THRESHOLD",
    "metricType": "TOTAL_COST",
    "operatorType": "GREATER_THAN",
    "threshold": 50,
    "periodDuration": "ONE_HOUR",
    "notificationAddresses": ["ops@example.com"],
}


async def _manage_alerts(platform, arguments):
    with patch.object(AlertManagement, "get_client", AsyncMock(return_value=platform)):
        is_error, text, _ = await _call_through_the_boundary(
            "_register_manage_alerts", "manage_alerts", arguments, execute=True
        )
    return is_error, text


def _update(filters):
    return {"action": "update", "anomaly_id": "anom_5", "anomaly_data": {"filters": filters}}


def _direct_create(filters):
    return {"action": "create", "anomaly_data": {**DIRECT_ALERT, "filters": filters}}


def _assert_the_shape_refusal(is_error, text, problem):
    assert is_error, text
    assert problem in text
    assert "Invalid filter format" not in text
    assert "{'dimension': 'MODEL', 'operator': 'IS', 'value': 'gpt-4'}" in text
    assert "{'field': 'model', 'operator': 'is', 'value': 'gpt-4'}" in text


@pytest.mark.parametrize("unshaped_row, problem", UNSHAPED_ROWS)
@pytest.mark.parametrize("rows_before", ROWS_BEFORE_IT)
@pytest.mark.asyncio
async def test_an_update_refuses_an_unshaped_row_wherever_it_sits(rows_before, unshaped_row, problem):
    platform = FakeAnomalyPlatform([threshold_alert("anom_5")])

    is_error, text = await _manage_alerts(platform, _update([*rows_before, unshaped_row]))

    _assert_the_shape_refusal(is_error, text, problem)
    assert platform.updated_bodies == []


@pytest.mark.asyncio
async def test_an_update_converts_a_field_row_after_a_dimension_row():
    platform = FakeAnomalyPlatform([threshold_alert("anom_5")])

    is_error, text = await _manage_alerts(platform, _update([DIMENSION_ROW, FIELD_ROW]))

    assert not is_error, text
    assert platform.updated_bodies[-1][1]["filters"] == [DIMENSION_ROW, CONVERTED_FIELD_ROW]


@pytest.mark.parametrize("unshaped_row, problem", UNSHAPED_ROWS)
@pytest.mark.parametrize("rows_before", ROWS_BEFORE_IT)
@pytest.mark.asyncio
async def test_a_direct_create_refuses_an_unshaped_row_wherever_it_sits(rows_before, unshaped_row, problem):
    platform = FakeAnomalyPlatform()

    is_error, text = await _manage_alerts(platform, _direct_create([*rows_before, unshaped_row]))

    _assert_the_shape_refusal(is_error, text, problem)
    assert platform.created_bodies == []


@pytest.mark.asyncio
async def test_a_direct_create_converts_a_field_row_after_a_dimension_row():
    platform = FakeAnomalyPlatform()

    is_error, text = await _manage_alerts(platform, _direct_create([DIMENSION_ROW, FIELD_ROW]))

    assert not is_error, text
    assert platform.created_bodies[-1]["filters"] == [DIMENSION_ROW, CONVERTED_FIELD_ROW]


@pytest.mark.parametrize("rows_before", ROWS_BEFORE_IT)
@pytest.mark.parametrize("action", ["update", "create"])
@pytest.mark.asyncio
async def test_a_row_that_is_not_a_dictionary_is_refused_not_dropped(action, rows_before):
    platform = FakeAnomalyPlatform([threshold_alert("anom_5")])
    write = _update if action == "update" else _direct_create

    is_error, text = await _manage_alerts(platform, write([*rows_before, "MODEL IS gpt-4"]))

    assert is_error, text
    assert "Each filter must be a dictionary" in text
    assert platform.updated_bodies == [] and platform.created_bodies == []


def _rules_create(filters):
    return {"action": "create", "anomaly_data": _rules_payload(filters)}


WRITES = {"update": _update, "create": _direct_create, "rules": _rules_create}


@pytest.mark.parametrize(
    "filters",
    [pytest.param(DIMENSION_ROW, id="one_row_not_in_a_list"), pytest.param("MODEL IS gpt-4", id="text")],
)
@pytest.mark.parametrize("action", sorted(WRITES))
@pytest.mark.asyncio
async def test_a_filters_value_that_is_not_a_list_is_refused_not_dropped(action, filters):
    platform = FakeAnomalyPlatform([threshold_alert("anom_5")])

    is_error, text = await _manage_alerts(platform, WRITES[action](filters))

    assert is_error, text
    assert "filters" in text
    assert platform.updated_bodies == [] and platform.created_bodies == []


@pytest.mark.parametrize(
    "row",
    [
        pytest.param({"dimension": "MODEL", "operator": "IN"}, id="in_without_values"),
        pytest.param({"dimension": "MODEL", "operator": "LIKE", "value": "gpt-4"}, id="unknown_operator"),
        pytest.param("MODEL IS gpt-4", id="not_a_dictionary"),
    ],
)
@pytest.mark.asyncio
async def test_a_detection_rules_create_refuses_a_bad_row_the_way_an_update_does(row):
    platform = FakeAnomalyPlatform([threshold_alert("anom_5")])

    _, update_text = await _manage_alerts(platform, _update([row]))
    is_error, rules_text = await _manage_alerts(platform, _rules_create([row]))

    assert is_error, rules_text
    assert "Failed to convert to API format" not in rules_text
    assert "field: anomaly_data" not in rules_text
    assert rules_text == update_text
    assert platform.created_bodies == []


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(_rules_payload([FIELD_ROW]), id="detection_rules"),
        pytest.param({**DIRECT_ALERT, "filters": [FIELD_ROW]}, id="direct"),
    ],
)
def test_a_create_converts_its_filter_rows_once(payload):
    conversion = InputValidator.convert_filters_to_api_format
    with patch.object(InputValidator, "convert_filters_to_api_format", wraps=conversion) as converted:
        body = AnomalyManager().prepare_create(payload, "team-1")

    assert body["filters"] == [CONVERTED_FIELD_ROW]
    assert converted.call_count == 1


FIELD_ROWS_WITHOUT_TEXT = [
    pytest.param({"field": 5, "operator": "is", "value": "gpt-4"}, "field", id="numeric_field"),
    pytest.param({"field": "model", "operator": None, "value": "gpt-4"}, "operator", id="null_operator"),
    pytest.param({"field": "model", "operator": 7, "value": "gpt-4"}, "operator", id="numeric_operator"),
]


@pytest.mark.parametrize("row, key", FIELD_ROWS_WITHOUT_TEXT)
@pytest.mark.parametrize("action", sorted(WRITES))
@pytest.mark.asyncio
async def test_a_field_row_whose_field_or_operator_is_not_text_is_refused_naming_it(action, row, key):
    platform = FakeAnomalyPlatform([threshold_alert("anom_5")])

    is_error, text = await _manage_alerts(platform, WRITES[action]([row]))

    assert is_error, text
    assert f"has no text in '{key}'" in text
    assert "has no attribute" not in text
    assert "{'field': 'model', 'operator': 'is', 'value': 'gpt-4'}" in text
    assert platform.updated_bodies == [] and platform.created_bodies == []


@pytest.mark.parametrize("row, key", FIELD_ROWS_WITHOUT_TEXT)
@pytest.mark.asyncio
async def test_every_alert_write_gives_the_same_refusal_for_a_field_row_without_text(row, key):
    platform = FakeAnomalyPlatform([threshold_alert("anom_5")])

    answers = {action: await _manage_alerts(platform, write([row])) for action, write in WRITES.items()}
    texts = {action: text for action, (_, text) in answers.items()}

    assert all(is_error for is_error, _ in answers.values()), texts
    assert texts["update"] == texts["create"] == texts["rules"], texts
    assert f"has no text in '{key}'" in texts["update"]
    assert "has no attribute" not in texts["update"]


@pytest.mark.parametrize("row, key", FIELD_ROWS_WITHOUT_TEXT)
def test_the_conversion_refuses_a_field_row_without_text_as_a_filters_error(row, key):
    with pytest.raises(ToolError) as refusal:
        InputValidator.convert_filters_to_api_format([row])

    assert refusal.value.error_code == ErrorCodes.VALIDATION_ERROR
    assert refusal.value.field == "filters"
    assert refusal.value.value == row
