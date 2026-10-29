"""The built-in workflow templates and the call each step asks an agent to run.

A step names a domain action and the public tool that serves it after the
read/write split (``public_tool_for``), plus the arguments the call needs.

Two kinds of placeholder appear in those arguments:

- ``{field}`` is a context field. Each one is listed in the template's
  ``required_context`` or ``optional_context``. An optional field the caller
  does not pass takes the value ``optional_context`` gives it: a real default
  (``GREATER_THAN``) or a ``<...>`` placeholder for the caller to fill in.
- ``<...>`` is a value that only the result of an earlier step provides, and
  that step is named in the placeholder.
"""

import re
from typing import Any, Dict

from ..common.tool_surface import public_tool_for, tool_call

_WHOLE_FIELD = re.compile(r"\{(\w+)\}")


def _invoiced_product() -> Dict[str, Any]:
    return {
        "name": "{product_name}",
        "description": "{product_description}",
        "version": "1.0.0",
        "paymentSource": "INVOICE_ONLY_NO_PAYMENT",
        "plan": {
            "type": "SUBSCRIPTION",
            "name": "{product_name} plan",
            "currency": "USD",
            "period": "MONTH",
            "tiers": [
                {"name": "Base", "up_to": None, "flat_amount": "{monthly_price}"}
            ],
        },
    }


def _alert() -> Dict[str, Any]:
    return {
        "name": "{alert_name}",
        "alertType": "{alert_type}",
        "metricType": "{metric_name}",
        "operatorType": "{operator_type}",
        "threshold": "{threshold}",
    }


def _step(domain: str, action: str, purpose: str, **arguments: Any) -> Dict[str, Any]:
    return {
        "action": action,
        "tool": public_tool_for(domain, action),
        "arguments": arguments,
        "purpose": purpose,
    }


def fill_from_context(value: Any, context: Dict[str, Any]) -> Any:
    """``value`` with every ``{field}`` replaced; a whole-value field keeps its type."""
    if isinstance(value, str):
        whole = _WHOLE_FIELD.fullmatch(value)
        if whole and whole.group(1) in context:
            return context[whole.group(1)]
        return value.format_map(context)
    if isinstance(value, dict):
        return {key: fill_from_context(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [fill_from_context(item, context) for item in value]
    return value


def step_context(template: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """The workflow context over the template's optional defaults."""
    return {**template.get("optional_context", {}), **context}


def render_step_call(step: Dict[str, Any], context: Dict[str, Any]) -> str:
    """The step's call with ``context`` filled in, ready to run."""
    arguments = fill_from_context(step["arguments"], context)
    return tool_call(step["tool"], step["action"], **arguments)


def _customer_onboarding() -> Dict[str, Any]:
    return {
        "name": "Customer Onboarding",
        "description": "Complete customer setup workflow",
        "steps": [
            _step(
                "manage_customers",
                "create",
                "Create the customer's organization",
                resource_type="organizations",
                organization_data={"name": "{organization_name}"},
            ),
            _step(
                "manage_customers",
                "create",
                "Create the subscriber who will use the product, in that organization",
                resource_type="subscribers",
                subscriber_data={
                    "email": "{customer_email}",
                    "organizationIds": ["<organization id from step 1>"],
                },
            ),
            _step(
                "manage_subscriptions",
                "create",
                "Subscribe the customer to a product so usage is billed",
                subscription_data={
                    "name": "{organization_name} subscription",
                    "product_id": "{product_id}",
                    "clientEmailAddress": "{customer_email}",
                },
            ),
            _step(
                "manage_alerts",
                "create",
                "Alert when this organization's monthly cost passes its budget",
                anomaly_data={
                    "name": "{organization_name} monthly budget",
                    "alertType": "CUMULATIVE_USAGE",
                    "metricType": "TOTAL_COST",
                    "threshold": "{monthly_budget}",
                    "periodDuration": "MONTHLY",
                    "filters": [
                        {
                            "dimension": "ORGANIZATION",
                            "operator": "IS",
                            "value": "{organization_name}",
                        }
                    ],
                },
                email="{alert_email}",
            ),
        ],
        "required_context": ["customer_email", "organization_name"],
        "optional_context": {
            "product_id": "<product id>",
            "monthly_budget": "<monthly budget in USD>",
            "alert_email": "<email to notify>",
        },
    }


def _product_setup() -> Dict[str, Any]:
    return {
        "name": "Product Setup",
        "description": "Product creation and configuration workflow",
        "steps": [
            _step(
                "manage_products",
                "clarify_pricing",
                "Check how the pricing model maps to a plan. The plan in the next steps "
                "is a flat monthly fee; replace its tiers when the pricing model is usage based",
                text="{pricing_model}",
            ),
            _step(
                "manage_products",
                "validate",
                "Check the product the way create will, without creating it",
                product_data=_invoiced_product(),
            ),
            _step(
                "manage_products",
                "create",
                "Create the product",
                product_data=_invoiced_product(),
            ),
            _step(
                "manage_usage_meters",
                "create",
                "Create a usage meter that records the product's usage, for a usage-based "
                "plan to rate by",
                element_data={"name": "{meter_name}", "type": "NUMBER"},
            ),
        ],
        "required_context": ["product_name", "pricing_model"],
        "optional_context": {
            "product_description": "<product description>",
            "monthly_price": "<monthly price in USD>",
            "meter_name": "<meter name>",
        },
    }


def _alert_configuration() -> Dict[str, Any]:
    return {
        "name": "Alert Configuration",
        "description": "Alert setup and testing workflow",
        "steps": [
            _step(
                "manage_alerts",
                "validate",
                "Check the alert the way create will, without creating it",
                anomaly_data=_alert(),
                email="{alert_email}",
            ),
            _step(
                "manage_alerts",
                "create",
                "Create the alert",
                anomaly_data=_alert(),
                email="{alert_email}",
            ),
            _step(
                "manage_alerts",
                "get",
                "Read the created alert back",
                anomaly_id="<alert id from step 2>",
            ),
            _step(
                "manage_alerts",
                "enable",
                "Make sure the alert is enabled",
                anomaly_id="<alert id from step 2>",
            ),
        ],
        "required_context": ["alert_type", "metric_name"],
        "optional_context": {
            "alert_name": "<alert name>",
            "threshold": "<threshold>",
            "operator_type": "GREATER_THAN",
            "alert_email": "<email to notify>",
        },
    }


def _subscription_setup() -> Dict[str, Any]:
    return {
        "name": "Subscription Setup",
        "description": "Complete subscription creation workflow",
        "steps": [
            _step(
                "manage_subscriptions",
                "validate_product_for_subscription",
                "Check that the product can be subscribed to",
                product_id="{product_id}",
            ),
            _step(
                "manage_customers",
                "lookup_subscriber",
                "Check that the customer exists as a subscriber",
                email="{customer_email}",
            ),
            _step(
                "manage_subscriptions",
                "create",
                "Create the subscription",
                subscription_data={
                    "name": "{subscription_name}",
                    "product_id": "{product_id}",
                    "clientEmailAddress": "{customer_email}",
                },
            ),
            _step(
                "manage_subscriptions",
                "get",
                "Read the subscription back",
                subscription_id="<subscription id from step 3>",
            ),
        ],
        "required_context": ["product_id", "customer_email"],
        "optional_context": {"subscription_name": "<subscription name>"},
    }


def build_workflow_templates() -> Dict[str, Dict[str, Any]]:
    """A fresh copy of every built-in template."""
    return {
        "customer_onboarding": _customer_onboarding(),
        "product_setup": _product_setup(),
        "alert_configuration": _alert_configuration(),
        "subscription_setup": _subscription_setup(),
    }
