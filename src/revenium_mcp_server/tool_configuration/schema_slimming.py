"""Slim the JSON schemas the MCP server advertises for its tools (BACK-3170).

Every agent that connects pays for the tool list before it does any work. The
registration closures in ``registry.py`` declare one named parameter per
accepted argument, and FastMCP turns each ``Optional[Union[...]]`` annotation
into a multi-branch ``anyOf`` with ``"default": null``. Nothing in that
expansion tells a caller anything it could not have guessed, and on the
twenty-tool business profile it adds up to roughly 18.7K tokens.

Two transforms live here:

``slim_schema``
    Collapses the union noise. ``{"type": "null"}`` branches disappear, a
    single remaining branch is inlined, a ``Union[X, str]`` written only so a
    string can be coerced at runtime advertises ``X``, and ``"default": null``
    is dropped. Nothing a caller may send changes: FastMCP validates arguments
    against the closure signature's TypeAdapter, not against the advertised
    schema.

``thin_schema``
    For the heaviest tools, replaces the long parameter list with ``action``,
    the parameters the signature always supplies a value for, the common
    paging/filter parameters, and a ``params`` object. Per-action parameters
    are then documented on demand by each tool's ``get_capabilities`` action,
    which is where an agent already has to look for allowed values.

``merge_params_argument`` is the runtime half of the ``params`` convention: a
registration closure folds the bag into the named arguments it built, with the
named arguments winning.
"""

from typing import Any, Dict, Mapping, Optional, Sequence, Set

from loguru import logger

from ..common.department_aliases import mark_deprecated_aliases

#: Parameters advertised on a thin schema when the tool declares them. These
#: are the argument names that are meaningful across most actions of a tool,
#: so leaving them visible saves a ``get_capabilities`` round trip for the
#: common "list the next page" case.
COMMON_PARAMETERS: Sequence[str] = ("page", "size", "filters", "dry_run")

#: Defaults the thin-schema tools apply after the ``params`` bag is merged.
#:
#: These parameters used to carry their default in the closure signature,
#: which made them unfillable from the bag: the signature had already put a
#: value in the arguments dict before the merge ran, so ``{"params": {"page":
#: 3}}`` silently paged from zero. The closures now declare them optional and
#: call ``apply_thin_tool_defaults`` after merging, so the bag is honoured and
#: the tool classes still receive the value they have always received. Keeping
#: the map here rather than in the closures means the advertised schema and
#: the runtime default cannot drift apart — ``thin_schema`` reads the same
#: literal back onto the advertised property.
#:
#: The keys of this map double as the list of thin-schema tools. Every other
#: tool keeps its full parameter list, merely slimmed.
THIN_TOOL_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "manage_metering": {},
    "business_analytics_management": {"page": 0, "size": 20},
    "manage_alerts": {"page": 0, "size": 20, "resource_type": "anomalies"},
    "manage_ai_insights": {},
    "manage_tools": {"page": 0, "size": 20},
}

#: The tools whose advertised parameter list is replaced by the thin shape.
#: These are the five heaviest schemas on the business profile.
THIN_SCHEMA_TOOLS: Set[str] = set(THIN_TOOL_DEFAULTS)

#: Name of the catch-all object property added by the thin shape.
PARAMS_PROPERTY = "params"

PARAMS_DESCRIPTION = (
    "Per-action parameters as a JSON object. Run get_capabilities for the "
    "parameters each action accepts; the same names also work as top-level "
    "arguments, and a top-level value wins over the same name here."
)

#: Appended to the description of every thin-schema tool so an agent reading
#: only the tool list knows where the per-action detail went.
DESCRIPTION_SUFFIX = (
    "Per-action parameters are documented by get_capabilities and may be "
    "passed at the top level or inside params."
)

_NULL_BRANCH = {"type": "null"}
_STRING_BRANCH = {"type": "string"}


#: The ``_JSONScalar = Union[str, int, float, bool]`` widening, as branches.
_JSON_SCALAR_BRANCHES = [
    {"type": "string"},
    {"type": "integer"},
    {"type": "number"},
    {"type": "boolean"},
]


def _collapse_branches(non_null: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Pick the single branch a multi-branch ``anyOf`` should advertise.

    Returns ``None`` unless the union is one of the two lenient-coercion
    idioms the registration closures use. A union that carries real choice —
    ``Optional[Union[int, List[int]]]``, say — keeps its branches: collapsing
    it would tell a caller that half of what the tool accepts is invalid.
    """
    if len(non_null) == 1:
        return non_null[0]

    others = [branch for branch in non_null if branch != _STRING_BRANCH]

    # ``Union[X, str]`` is the lenient-coercion idiom used throughout the
    # registration closures: the parameter is an X, and the str branch only
    # exists because agent interfaces serialize scalars as strings. Advertise
    # the X.
    if len(non_null) == 2 and len(others) == 1:
        return others[0]

    # ``_JSONScalar = Union[str, int, float, bool]`` runs the other way: it
    # widens a *string* parameter so the closure can reject bad input with a
    # structured error instead of a framework error. Advertise the string.
    if _STRING_BRANCH in non_null and all(branch in _JSON_SCALAR_BRANCHES for branch in non_null):
        return dict(_STRING_BRANCH)

    return None


def slim_property(schema: Mapping[str, Any]) -> Dict[str, Any]:
    """Slim one property schema. Pure, deterministic, and idempotent."""
    slimmed = dict(schema)

    branches = slimmed.get("anyOf")
    if isinstance(branches, list) and branches:
        non_null = [dict(branch) for branch in branches if dict(branch) != _NULL_BRANCH]
        chosen = _collapse_branches(non_null) if non_null else None
        if chosen is not None:
            slimmed.pop("anyOf")
            # Keys already on the property (default, description, ...) win
            # over the branch's own keys, which only carry type information.
            chosen.update(slimmed)
            slimmed = chosen
        elif non_null:
            # Real choice: keep every branch a caller may send, minus the
            # null one that Optional added.
            slimmed["anyOf"] = non_null

    if "default" in slimmed and slimmed["default"] is None:
        slimmed.pop("default")

    return slimmed


def slim_schema(schema: Mapping[str, Any]) -> Dict[str, Any]:
    """Slim a whole tool input schema, keeping ``action`` first."""
    slimmed = dict(schema)
    properties = slimmed.get("properties")
    if not isinstance(properties, dict):
        return slimmed

    slimmed_properties = {
        name: slim_property(prop) if isinstance(prop, Mapping) else prop
        for name, prop in properties.items()
    }

    if "action" in slimmed_properties:
        ordered = {"action": slimmed_properties.pop("action")}
        ordered.update(slimmed_properties)
        slimmed_properties = ordered

    slimmed["properties"] = slimmed_properties
    return slimmed


def thin_schema(
    schema: Mapping[str, Any], defaults: Optional[Mapping[str, Any]] = None
) -> Dict[str, Any]:
    """Advertise only ``action``, the common and defaulted parameters, and ``params``.

    ``defaults`` is the tool's entry from ``THIN_TOOL_DEFAULTS``: those names
    stay advertised and get their default written back onto the advertised
    property, because the closure applies it after the merge rather than in
    its signature.

    Expects an already-slimmed schema. Idempotent.
    """
    defaults = defaults or {}
    thinned = dict(schema)
    properties = thinned.get("properties")
    if not isinstance(properties, dict):
        return thinned

    kept: Dict[str, Any] = {}
    if "action" in properties:
        kept["action"] = properties["action"]
    for name, prop in properties.items():
        if name in kept or name == PARAMS_PROPERTY:
            continue
        if name in defaults or name in COMMON_PARAMETERS:
            kept[name] = prop
    for name, default in defaults.items():
        if name in kept and isinstance(kept[name], Mapping):
            kept[name] = {**kept[name], "default": default}

    kept[PARAMS_PROPERTY] = {
        "type": "object",
        "additionalProperties": True,
        "description": PARAMS_DESCRIPTION,
    }

    thinned["properties"] = kept
    # The tool still accepts every name its closure declares; saying otherwise
    # would tell a strict client that a working call is invalid.
    thinned["additionalProperties"] = True

    required = thinned.get("required")
    if isinstance(required, list):
        still_required = [name for name in required if name in kept]
        if still_required:
            thinned["required"] = still_required
        else:
            thinned.pop("required")

    return thinned


def slim_tool_schema(tool_name: str, schema: Mapping[str, Any]) -> Dict[str, Any]:
    """Return the schema to advertise for ``tool_name``."""
    slimmed = mark_deprecated_aliases(tool_name, slim_schema(schema))
    if tool_name in THIN_SCHEMA_TOOLS:
        return thin_schema(slimmed, THIN_TOOL_DEFAULTS[tool_name])
    return slimmed


def slim_tool_description(tool_name: str, description: Optional[str]) -> Optional[str]:
    """Append the ``params`` pointer to a thin-schema tool's description."""
    if tool_name not in THIN_SCHEMA_TOOLS or not description:
        return description
    if DESCRIPTION_SUFFIX in description:
        return description
    return f"{description.rstrip()}\n\n{DESCRIPTION_SUFFIX}"


def merge_params_argument(arguments: Dict[str, Any], params: Any) -> Dict[str, Any]:
    """Fold a ``params`` bag into the named arguments a closure built.

    Precedence, in one sentence: a top-level argument beats the same name in
    the bag, the bag beats the tool's default, and ``action`` never comes from
    the bag — the closure has already dispatched on it by the time this runs.
    That holds only because the thin closures declare their defaulted
    parameters optional and apply the default *after* this merge, via
    ``apply_thin_tool_defaults``; a default left in a closure signature would
    silently outrank the bag.

    ``params`` is typed loosely because the guard below is the last line of
    defence for a client that sends something other than an object.
    """
    if not params:
        return arguments
    if not isinstance(params, Mapping):
        logger.warning(f"Ignoring non-object params argument of type {type(params).__name__}")
        return arguments

    for name, value in params.items():
        if name in ("action", PARAMS_PROPERTY):
            continue
        if arguments.get(name) is None:
            arguments[name] = value
    return arguments


def apply_thin_tool_defaults(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Apply a thin tool's defaults to whatever the caller and the bag left unset.

    Called after ``merge_params_argument`` so the bag can override a default
    the closure signature used to hard-code.
    """
    for name, default in THIN_TOOL_DEFAULTS.get(tool_name, {}).items():
        if arguments.get(name) is None:
            arguments[name] = default
    return arguments


async def apply_schema_slimming(mcp: Any, tool_names: Sequence[str]) -> None:
    """Rewrite the advertised schema of each registered tool in place.

    Runs once after registration. ``Tool.parameters`` is a plain field on the
    live object FastMCP hands back, and FastMCP validates calls against the
    closure signature rather than against this field, so replacing it changes
    only what callers are told.
    """
    for tool_name in tool_names:
        try:
            tool = await mcp.get_tool(tool_name)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(f"Could not slim schema for {tool_name}: {exc}")
            continue
        if tool is None:  # pragma: no cover - defensive
            continue

        tool.parameters = slim_tool_schema(tool_name, tool.parameters or {})
        tool.description = slim_tool_description(tool_name, tool.description)

    logger.debug(f"Applied advertised-schema slimming to {len(tool_names)} tools")
