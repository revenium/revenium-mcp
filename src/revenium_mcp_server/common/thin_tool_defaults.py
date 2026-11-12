"""The defaults the thin-schema tools fill in on every call, whatever the caller sent.

Kept out of ``tool_configuration`` so a tool class can read them without
importing the registry, which imports the tool classes.
"""

from typing import Any, Dict, FrozenSet

from ..constants import USER_COSTS_DEFAULT_PAGE_SIZE

#: Defaults the thin-schema tools apply after the ``params`` bag is merged.
#:
#: These parameters used to carry their default in the closure signature,
#: which made them unfillable from the bag: the signature had already put a
#: value in the arguments dict before the merge ran, so ``{"params": {"page":
#: 3}}`` silently paged from zero. The closures now declare them optional and
#: call ``apply_thin_tool_defaults`` after merging, so the bag is honoured and
#: the tool classes still receive the value they have always received. Keeping
#: the map out of the closures means the advertised schema and the runtime
#: default cannot drift apart — ``thin_schema`` reads the same literal back
#: onto the advertised property.
#:
#: The keys of this map double as the list of thin-schema tools. Every other
#: tool keeps its full parameter list, merely slimmed.
THIN_TOOL_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "manage_metering": {},
    "get_business_analytics": {"page": 0, "size": 20},
    "manage_alerts": {"page": 0, "size": 20},
    "manage_ai_insights": {},
    "manage_tools": {"page": 0, "size": 20},
}

#: Per-action defaults that replace the tool's own default for one action.
THIN_ACTION_DEFAULTS: Dict[str, Dict[str, Dict[str, Any]]] = {
    "get_business_analytics": {
        "get_user_costs": {"size": USER_COSTS_DEFAULT_PAGE_SIZE},
        "get_agent_costs": {"size": USER_COSTS_DEFAULT_PAGE_SIZE},
    },
}


def apply_thin_tool_defaults(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Apply a thin tool's defaults to whatever the caller and the bag left unset.

    Called after ``merge_params_argument`` so the bag can override a default
    the closure signature used to hard-code. An action's own default, from
    ``THIN_ACTION_DEFAULTS``, replaces the tool's default for that action.
    """
    action_defaults = THIN_ACTION_DEFAULTS.get(tool_name, {}).get(str(arguments.get("action")), {})
    defaults = {**THIN_TOOL_DEFAULTS.get(tool_name, {}), **action_defaults}
    for name, default in defaults.items():
        if arguments.get(name) is None:
            arguments[name] = default
    return arguments


def arguments_filled_on_every_call(tool_name: str, action: str) -> FrozenSet[str]:
    """``action`` and every name ``apply_thin_tool_defaults`` fills in on a call of it.

    Their presence on a call says nothing about what the caller asked for.
    """
    return frozenset(apply_thin_tool_defaults(tool_name, {"action": action}))
