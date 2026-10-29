"""Every built-in workflow step names a call the serving tool runs as written (BACK-5084)."""

import re
from types import SimpleNamespace

import pytest

from src.revenium_mcp_server.common.subscription_create_fields import (
    REQUIRED_SUBSCRIPTION_CREATE_FIELDS,
)
from src.revenium_mcp_server.common.tool_surface import domain_for, public_tool_for
from src.revenium_mcp_server.tools_decomposed.alert_management import AlertManagement
from src.revenium_mcp_server.tools_decomposed.product_management import ProductValidator
from src.revenium_mcp_server.tools_decomposed.tool_registry import _get_tool_registry
from src.revenium_mcp_server.tools_decomposed.workflow_management import (
    WorkflowManagement,
    WorkflowManager,
)
from src.revenium_mcp_server.tools_decomposed.workflow_templates import (
    fill_from_context,
    step_context,
)

_TEMPLATES = WorkflowManager().workflow_templates
_STEPS = [
    (f"{name}[{index}]", step)
    for name, template in _TEMPLATES.items()
    for index, step in enumerate(template["steps"])
]
_SUPPORTED_ACTIONS: dict = {}


async def _supported_actions(domain_key: str) -> list:
    if domain_key not in _SUPPORTED_ACTIONS:
        tool_class = _get_tool_registry()[domain_key]
        _SUPPORTED_ACTIONS[domain_key] = list(
            await tool_class(ucm_helper=None)._get_supported_actions()
        )
    return _SUPPORTED_ACTIONS[domain_key]


@pytest.fixture(autouse=True)
def _clear_active_workflows():
    WorkflowManager.active_workflows.clear()
    yield
    WorkflowManager.active_workflows.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "step", [step for _, step in _STEPS], ids=[i for i, _ in _STEPS]
)
async def test_every_template_step_names_an_action_its_tool_advertises(step):
    domain = domain_for(step["tool"])

    assert step["action"] in await _supported_actions(domain.key)
    assert domain.serving_side(step["action"]) is not None


@pytest.mark.parametrize(
    "step", [step for _, step in _STEPS], ids=[i for i, _ in _STEPS]
)
def test_every_template_step_names_the_tool_that_serves_its_action(step):
    assert step["tool"] == public_tool_for(step["tool"], step["action"])


def test_a_validate_step_names_the_read_tool():
    alert_steps = _TEMPLATES["alert_configuration"]["steps"]

    assert {"action": "validate", "tool": "get_alerts"}.items() <= alert_steps[
        0
    ].items()


@pytest.mark.asyncio
async def test_customer_onboarding_first_step_is_a_call_that_runs_as_written():
    manager = WorkflowManager()
    workflow = await manager.start_workflow(
        {
            "workflow_type": "customer_onboarding",
            "context": {"customer_email": "ana@acme.com", "organization_name": "Acme"},
        }
    )

    guidance = await manager.next_step({"workflow_id": workflow["id"]})

    assert guidance["call"] == (
        "manage_customers(action='create', resource_type='organizations', "
        "organization_data={'name': 'Acme'})"
    )
    assert guidance["call"] in guidance["guidance"]


@pytest.mark.asyncio
async def test_a_step_value_from_an_earlier_step_stays_a_named_placeholder():
    manager = WorkflowManager()
    workflow = await manager.start_workflow(
        {
            "workflow_type": "customer_onboarding",
            "context": {"customer_email": "ana@acme.com", "organization_name": "Acme"},
        }
    )
    await manager.complete_step({"workflow_id": workflow["id"], "step_result": {}})

    guidance = await manager.next_step({"workflow_id": workflow["id"]})

    assert "'email': 'ana@acme.com'" in guidance["call"]
    assert "<organization id from step 1>" in guidance["call"]


@pytest.mark.asyncio
async def test_a_finished_workflow_names_no_action_that_does_not_exist():
    manager = WorkflowManager()
    workflow = await manager.start_workflow({"workflow_type": "generic", "context": {}})
    await manager.complete_step({"workflow_id": workflow["id"], "step_result": {}})

    guidance = await manager.next_step({"workflow_id": workflow["id"]})

    assert "complete_workflow" not in str(guidance)


@pytest.mark.asyncio
async def test_the_examples_show_the_template_steps_as_they_are():
    text = (await WorkflowManagement().handle_action("get_examples", {}))[0].text
    first_step = _TEMPLATES["customer_onboarding"]["steps"][0]

    assert "create_organization" not in text
    assert "create_user" not in text
    assert f'"action": "{first_step["action"]}"' in text
    assert f'"tool": "{first_step["tool"]}"' in text


def _filled_arguments(template_name: str, step_index: int, context: dict) -> dict:
    template = _TEMPLATES[template_name]
    step = template["steps"][step_index]
    return fill_from_context(step["arguments"], step_context(template, context))


def _alert_preview(arguments: dict) -> str:
    alerts = AlertManagement(ucm_helper=None)
    preview = alerts._preview_create(
        SimpleNamespace(team_id="team-1"), "validate", arguments
    )
    return preview[0].text


@pytest.mark.parametrize("name", sorted(_TEMPLATES))
def test_every_context_field_a_step_uses_is_declared_by_its_template(name):
    template = _TEMPLATES[name]
    used = set(
        re.findall(r"\{(\w+)\}", str([step["arguments"] for step in template["steps"]]))
    )
    declared = set(template["required_context"]) | set(
        template.get("optional_context", {})
    )

    assert used - declared == set()


_SUBSCRIPTION_CREATE_CASES = [
    pytest.param(
        "customer_onboarding",
        {
            "customer_email": "ana@example.com",
            "organization_name": "Acme",
            "product_id": "prod_123",
        },
        "Acme subscription",
        id="customer_onboarding names it after the organization",
    ),
    pytest.param(
        "subscription_setup",
        {
            "product_id": "prod_123",
            "customer_email": "ana@example.com",
            "subscription_name": "Starter",
        },
        "Starter",
        id="subscription_setup uses the subscription_name the caller gives",
    ),
]


def _subscription_create_index(template_name: str) -> int:
    steps = _TEMPLATES[template_name]["steps"]
    (index,) = [
        i
        for i, step in enumerate(steps)
        if step["tool"] == "manage_subscriptions" and step["action"] == "create"
    ]
    return index


@pytest.mark.parametrize("name, context, expected_name", _SUBSCRIPTION_CREATE_CASES)
def test_a_subscription_create_step_carries_every_required_field_once_filled(
    name, context, expected_name
):
    """manage_subscriptions create refuses a missing name, product_id or clientEmailAddress."""
    subscription_data = _filled_arguments(
        name, _subscription_create_index(name), context
    )["subscription_data"]

    assert subscription_data["name"] == expected_name
    assert subscription_data["product_id"] == "prod_123"
    assert subscription_data["clientEmailAddress"] == "ana@example.com"
    assert set(REQUIRED_SUBSCRIPTION_CREATE_FIELDS) <= set(subscription_data)


def test_subscription_setup_without_a_name_leaves_the_placeholder_to_fill():
    index = _subscription_create_index("subscription_setup")
    subscription_data = _filled_arguments(
        "subscription_setup",
        index,
        {"product_id": "prod_123", "customer_email": "ana@example.com"},
    )["subscription_data"]

    assert subscription_data["name"] == "<subscription name>"


def test_the_product_setup_payload_passes_product_validation_once_filled():
    arguments = _filled_arguments(
        "product_setup",
        1,
        {
            "product_name": "AI API Service",
            "pricing_model": "subscription",
            "product_description": "Hosted inference API",
            "monthly_price": "49.00",
        },
    )

    result = ProductValidator(None).validate_configuration(
        arguments["product_data"], True
    )

    assert result["valid"] is True, result


def test_the_alert_configuration_payload_passes_alert_validation_with_its_example_context():
    arguments = _filled_arguments(
        "alert_configuration",
        0,
        {
            "alert_type": "THRESHOLD",
            "metric_name": "TOTAL_COST",
            "alert_name": "Cost",
            "alert_email": "ops@acme.com",
            "threshold": 100,
        },
    )

    assert arguments["anomaly_data"]["threshold"] == 100
    assert "Validation passed" in _alert_preview(arguments)


def test_the_customer_onboarding_alert_is_limited_to_the_new_organization():
    arguments = _filled_arguments(
        "customer_onboarding",
        3,
        {
            "customer_email": "ana@acme.com",
            "organization_name": "Acme",
            "monthly_budget": 500,
            "alert_email": "ops@acme.com",
        },
    )

    assert arguments["anomaly_data"]["filters"] == [
        {"dimension": "ORGANIZATION", "operator": "IS", "value": "Acme"}
    ]
    assert "Validation passed" in _alert_preview(arguments)
