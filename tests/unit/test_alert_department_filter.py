"""BACK-5706: an alert filtered on one department is accepted, round-trips on update and is documented truthfully."""

import pytest
from unittest.mock import AsyncMock

from src.revenium_mcp_server.alerts.update_fidelity import (
    ALERT_FILTER_DIMENSIONS,
    DEPARTMENT_ALERT_BUDGET_SHAPE,
    DEPARTMENT_ALERT_FORMS,
    DEPARTMENT_INCLUDE_DESCENDANTS_DEFAULT,
    platform_rule_breach,
)
from src.revenium_mcp_server.schema.alert_schema import AlertSchemaDiscovery
from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement
from tests.unit.anomaly_platform_fake import FakeAnomalyPlatform, answer, threshold_alert

DEPARTMENT_FILTER = [
    {"dimension": "DEPARTMENT", "operator": "IS", "value": "4127", "includeDescendants": True}
]


def _tools(platform):
    tools = AlertManagement()
    tools.get_client = AsyncMock(return_value=platform)
    return tools


def _budget(**overrides):
    return threshold_alert(
        "dept", alertType="CUMULATIVE_USAGE", periodDuration="MONTHLY", filters=DEPARTMENT_FILTER, **overrides
    )


def test_department_is_a_filter_dimension():
    assert "DEPARTMENT" in ALERT_FILTER_DIMENSIONS


def test_a_department_filter_breaks_no_platform_rule():
    assert platform_rule_breach({"filters": DEPARTMENT_FILTER}, None) is None


@pytest.mark.asyncio
async def test_a_field_format_update_keeps_the_include_descendants_choice():
    platform = FakeAnomalyPlatform([_budget()])
    friendly = [{"field": "department", "operator": "is", "value": "4127", "includeDescendants": False}]

    flagged, text = await answer(
        _tools(platform).handle_action("update", {"anomaly_id": "dept", "anomaly_data": {"filters": friendly}})
    )

    assert not flagged and not text.startswith("**Error**")
    (_, body), = platform.updated_bodies
    assert body["filters"] == [{**DEPARTMENT_FILTER[0], "includeDescendants": False}]
    assert platform.store["dept"]["filters"] == body["filters"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "row",
    [
        {"field": "department", "operator": "is", "value": 4127, "include_descendants": False},
        {"dimension": "DEPARTMENT", "operator": "IS", "value": "4127", "include_descendants": False},
    ],
    ids=["field-format", "dimension-format"],
)
async def test_a_snake_case_include_descendants_reaches_the_platform_under_its_wire_name(row):
    platform = FakeAnomalyPlatform([_budget()])

    flagged, text = await answer(
        _tools(platform).handle_action("update", {"anomaly_id": "dept", "anomaly_data": {"filters": [row]}})
    )

    assert not flagged and not text.startswith("**Error**")
    (_, body), = platform.updated_bodies
    assert body["filters"] == [{**DEPARTMENT_FILTER[0], "includeDescendants": False}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "row",
    [
        {"field": "department", "operator": "is", "value": 4127, "include_descendants": False, "includeDescendants": True},
        {"dimension": "DEPARTMENT", "operator": "IS", "value": "4127", "include_descendants": False, "includeDescendants": True},
    ],
    ids=["field-format", "dimension-format"],
)
async def test_include_descendants_under_both_spellings_is_refused_naming_both(row):
    platform = FakeAnomalyPlatform([_budget()])

    flagged, text = await answer(
        _tools(platform).handle_action("update", {"anomaly_id": "dept", "anomaly_data": {"filters": [row]}})
    )

    assert flagged
    assert "include_descendants" in text and "includeDescendants" in text
    assert platform.updated_bodies == []


@pytest.mark.asyncio
@pytest.mark.usefixtures("alert_owner_email")
async def test_a_snake_case_include_descendants_is_sent_under_its_wire_name_on_create():
    platform = FakeAnomalyPlatform([])
    alert = {
        "name": "Department budget",
        "alertType": "CUMULATIVE_USAGE",
        "metricType": "TOTAL_COST",
        "operatorType": "GREATER_THAN",
        "threshold": 500,
        "periodDuration": "MONTHLY",
        "filters": [{"dimension": "DEPARTMENT", "operator": "IS", "value": "4127", "include_descendants": False}],
    }

    flagged, _ = await answer(_tools(platform).handle_action("create", {"anomaly_data": alert}))

    assert not flagged
    assert platform.created_bodies[0]["filters"] == [{**DEPARTMENT_FILTER[0], "includeDescendants": False}]


@pytest.mark.asyncio
async def test_renaming_a_department_budget_resends_its_filter_with_include_descendants():
    platform = FakeAnomalyPlatform([_budget()])

    flagged, text = await answer(
        _tools(platform).handle_action("update", {"anomaly_id": "dept", "anomaly_data": {"name": "Renamed"}})
    )

    assert not flagged and not text.startswith("**Error**")
    (_, body), = platform.updated_bodies
    assert body["name"] == "Renamed"
    assert body["filters"] == DEPARTMENT_FILTER
    assert platform.store["dept"]["filters"] == DEPARTMENT_FILTER


@pytest.mark.asyncio
@pytest.mark.usefixtures("alert_owner_email")
async def test_a_department_filter_is_sent_to_the_platform_on_create():
    platform = FakeAnomalyPlatform([])
    alert = {
        "name": "Department budget",
        "alertType": "CUMULATIVE_USAGE",
        "metricType": "TOTAL_COST",
        "operatorType": "GREATER_THAN",
        "threshold": 500,
        "periodDuration": "MONTHLY",
        "filters": DEPARTMENT_FILTER,
    }

    flagged, _ = await answer(_tools(platform).handle_action("create", {"anomaly_data": alert}))

    assert not flagged
    assert platform.created_bodies[0]["filters"] == DEPARTMENT_FILTER


@pytest.mark.asyncio
async def test_the_capabilities_text_states_the_department_filter_limits():
    text = await AlertManagement()._build_enhanced_capabilities_text(None)

    section = text.split("**DEPARTMENT filters**")[1].split("```")[0]
    assert "numeric id" in section
    assert "includeDescendants" in section
    assert DEPARTMENT_ALERT_FORMS in section
    assert "refuses any other shape" in section
    assert "leave it out" in section and "counts as true" in section
    assert "Enforce a hard stop" in section and "manage_cost_controls" in section


def test_the_schema_discovery_says_a_department_filter_counts_sub_departments_unless_told_not_to():
    department = AlertSchemaDiscovery().get_capabilities()["filter_dimensions"]["DEPARTMENT"]

    assert DEPARTMENT_INCLUDE_DESCENDANTS_DEFAULT in department["example"]
    assert "counts as true" in department["example"]


@pytest.mark.asyncio
async def test_the_capabilities_text_states_every_limit_the_platform_gate_enforces():
    text = await AlertManagement()._build_enhanced_capabilities_text(None)

    section = text.split("**DEPARTMENT filters**")[1].split("```")[0]
    assert "GREATER_THAN or GREATER_THAN_OR_EQUAL_TO" in section
    assert "dataSource SDK" in section
    assert DEPARTMENT_ALERT_BUDGET_SHAPE in section
    assert "department alert budgets" in section
    assert "does not say whether the shape or the company setting is the cause" in section
