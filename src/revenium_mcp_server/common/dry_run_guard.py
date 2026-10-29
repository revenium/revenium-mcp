"""Refuse a dry_run request on any action that cannot honour it.

``dry_run`` is advertised on every tool, but only a few actions return a
preview instead of writing. The rest used to ignore the flag and carry out the
delete or update. The allowlist below holds the actions whose handler reads
``dry_run`` and sends no write when it is set: a real preview, or a read such
as the get_slack ones that honours the flag. An action whose handler
ignores the flag is not listed and refuses it, reads included, before a client
is built, so an action added later cannot ignore it.
"""

from types import MappingProxyType
from typing import Any, Dict, FrozenSet, List, Mapping, Tuple

from .error_handling import ErrorCodes, raise_refusal
from .tool_surface import domain_for
from .validation import preprocess_boolean_parameters

DRY_RUN_REFUSED = "the dry_run request was refused and nothing was sent or changed"

_CRUD_PREVIEWS = frozenset({"create", "update", "delete", "validate"})

DRY_RUN_PREVIEW_ACTIONS: Mapping[str, FrozenSet[str]] = MappingProxyType(
    {
        "manage_alerts": frozenset({"create", "update", "create_simple", "validate"}),
        "manage_customers": _CRUD_PREVIEWS
        | {"delete_department_person", "clear_department_assignment"},
        "manage_subscriptions": frozenset({"create", "update", "validate"}),
        "manage_credentials": frozenset({"create", "validate"}),
        "manage_products": _CRUD_PREVIEWS,
        "manage_sources": _CRUD_PREVIEWS,
        "manage_metering": frozenset({"submit_ai_transaction", "validate"}),
        "manage_usage_meters": _CRUD_PREVIEWS | {"create_from_template"},
        "manage_workflows": frozenset({"start", "complete_step"}),
        "manage_system_settings": frozenset(
            {"set_strict_ingestion_mode", "set_usage_billing"}
        ),
        "manage_slack": frozenset(
            {
                "set_default_configuration",
                "list_configurations",
                "get_configuration",
                "initiate_oauth",
                "refresh_configurations",
                "check_new_configurations",
                "quick_setup",
            }
        ),
    }
)


# Tool arguments forwarded as a write body; the classification test fails when a tool adds one that is not listed.
WRITE_PAYLOAD_ARGUMENTS: FrozenSet[str] = frozenset(
    {
        "agent_data",
        "anomaly_data",
        "control_data",
        "credential_data",
        "element_data",
        "event_data",
        "organization_data",
        "outcome_data",
        "product_data",
        "resource_data",
        "source_data",
        "subscriber_data",
        "subscription_data",
        "team_data",
        "tool_data",
        "user_data",
        "workflow_data",
    }
)


def _is_switched_off(value: Any) -> bool:
    return value is None or value is False or (type(value) is int and value == 0)


def dry_run_requested(arguments: Mapping[str, Any]) -> bool:
    """Whether the caller asked for a dry run.

    Only an absent flag, ``None``, ``False``, ``0`` or a recognised off
    spelling such as ``"false"`` switches it off. Every other value, an empty
    or unrecognised string included, counts as a request, so a value that
    slipped past the boolean preprocessing fails closed instead of letting the
    write run.
    """
    coerced = preprocess_boolean_parameters(
        {"dry_run": arguments.get("dry_run")}, ["dry_run"]
    )
    return not _is_switched_off(coerced["dry_run"])


def normalise_dry_run(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Hand handlers the dry_run flag as a bool, decided by ``dry_run_requested``.

    Handlers test the flag by truthiness, so an empty string would otherwise
    read as off there even though the guard counts it as a request.
    """
    if "dry_run" not in arguments:
        return arguments
    return {**arguments, "dry_run": dry_run_requested(arguments)}


def _tool_names(tool_name: str) -> Tuple[str, str]:
    """The read tool and the tool whose preview table applies, for a domain key or public name."""
    try:
        domain = domain_for(tool_name)
    except KeyError:
        return tool_name, tool_name
    return domain.read_name, domain.write_name or domain.read_name


def preview_actions(tool_name: str) -> FrozenSet[str]:
    """The actions of ``tool_name``'s domain that honour dry_run."""
    return DRY_RUN_PREVIEW_ACTIONS.get(_tool_names(tool_name)[1], frozenset())


def _previews_by_tool(tool_name: str) -> Dict[str, List[str]]:
    """The actions that honour dry_run, grouped under the public tool that serves each."""
    previews = sorted(preview_actions(tool_name))
    try:
        domain = domain_for(tool_name)
    except KeyError:
        return {tool_name: previews} if previews else {}
    grouped = {
        tool: domain.actions_served_by(tool, previews) for tool in domain.public_names
    }
    return {tool: actions for tool, actions in grouped.items() if actions}


def _no_preview_guidance(tool_name: str, action: str) -> str:
    read_tool = _tool_names(tool_name)[0]
    text = (
        f"To show what {action} would affect, run a read action of {read_tool} "
        "without dry_run (get_capabilities lists them). "
        f"Run {action} without dry_run, and if it changes data, "
        "only after the customer confirms."
    )
    for tool, actions in _previews_by_tool(tool_name).items():
        text += f" Actions of {tool} that preview with dry_run: {', '.join(actions)}."
    return text


def _refusal_text(tool_name: str, action: str) -> str:
    return (
        f"{action} has no preview, so {DRY_RUN_REFUSED}. "
        f"{_no_preview_guidance(tool_name, action)}"
    )


def _refuse_dry_run_inside_a_write_payload(
    tool_name: str, action: str, arguments: Mapping[str, Any]
) -> None:
    can_preview = action in preview_actions(tool_name)
    for argument in sorted(WRITE_PAYLOAD_ARGUMENTS):
        payload = arguments.get(argument)
        if isinstance(payload, Mapping) and "dry_run" in payload:
            advice = (
                "Send dry_run=true next to action to preview, or leave dry_run "
                "out to carry the action out."
                if can_preview
                else f"{action} has no preview. "
                f"{_no_preview_guidance(tool_name, action)}"
            )
            raise_refusal(
                f"dry_run was sent inside {argument}, where nothing reads it, "
                f"so {DRY_RUN_REFUSED}. {advice}",
                error_code=ErrorCodes.INVALID_PARAMETER,
                field=f"{argument}.dry_run",
                value=payload["dry_run"],
            )


def refuse_unsupported_dry_run(
    tool_name: str, action: str, arguments: Mapping[str, Any]
) -> None:
    """Raise a refusal when dry_run is requested on an action that cannot preview,
    or is sent inside a write payload where no handler reads it."""
    _refuse_dry_run_inside_a_write_payload(tool_name, action, arguments)
    if not dry_run_requested(arguments):
        return
    if action in preview_actions(tool_name):
        return
    raise_refusal(
        _refusal_text(tool_name, action),
        error_code=ErrorCodes.INVALID_PARAMETER,
        field="dry_run",
        value=arguments.get("dry_run"),
    )
