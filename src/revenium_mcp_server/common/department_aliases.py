"""Deprecated org-unit spellings of the department actions, arguments and dimension.

The platform renamed org units to departments with no alias of its own, so these
0.7.0 spellings are accepted for one release to keep existing MCP clients working.
"""

from typing import Any, Dict, Mapping, Tuple

DEPRECATED_ACTION_ALIASES: Mapping[str, str] = {
    "list_org_units": "list_departments",
    "delete_org_unit_person": "delete_department_person",
    "clear_org_unit_assignment": "clear_department_assignment",
    "preview_org_unit_group": "preview_department_group",
}

DEPRECATED_ARGUMENT_ALIASES: Mapping[str, str] = {
    "org_unit_id": "department_id",
    "parent_org_unit_id": "parent_department_id",
    "filter_org_unit_id": "filter_department_id",
}

DEPRECATED_DIMENSION_ALIASES: Mapping[str, str] = {"ORG_UNIT": "DEPARTMENT"}

DIMENSION_ALIAS_TOOLS = frozenset({"manage_cost_controls"})
ALIASED_ACTIONS_BY_TOOL: Mapping[str, Tuple[str, ...]] = {
    "manage_customers": (
        "list_departments",
        "delete_department_person",
        "clear_department_assignment",
    ),
    "manage_cost_controls": ("preview_department_group",),
}
_DIMENSION_ARGUMENTS = ("dimension", "group_by")


def deprecated_aliases_note(*names: str) -> str:
    """Name the deprecated spellings that still resolve to ``names``, for help text."""
    pairs = [
        f"{alias} -> {target}"
        for table in (
            DEPRECATED_ACTION_ALIASES,
            DEPRECATED_ARGUMENT_ALIASES,
            DEPRECATED_DIMENSION_ALIASES,
        )
        for alias, target in table.items()
        if target in names
    ]
    if not pairs:
        return ""
    return (
        "Deprecated aliases, still accepted for one release (use the department "
        f"names): {', '.join(pairs)}."
    )


def deprecated_argument_properties(target: str, schema_type: Any) -> Dict[str, Any]:
    """Input-schema entries for the deprecated spellings of the ``target`` argument."""
    return {
        alias: {"type": schema_type, **_deprecated_argument_marker(target)}
        for alias, name in DEPRECATED_ARGUMENT_ALIASES.items()
        if name == target
    }


def _deprecated_argument_marker(target: str) -> Dict[str, Any]:
    return {
        "deprecated": True,
        "description": f"Deprecated alias of {target}, still accepted for one release.",
    }


def mark_deprecated_aliases(tool_name: str, schema: Mapping[str, Any]) -> Dict[str, Any]:
    """Flag the deprecated spellings in an advertised tool schema.

    Argument aliases get the same entry ``deprecated_argument_properties`` gives
    the introspection schema; the ``action`` property names the action aliases.
    """
    marked = dict(schema)
    properties = marked.get("properties")
    if not isinstance(properties, dict):
        return marked
    properties = dict(properties)
    for alias, target in DEPRECATED_ARGUMENT_ALIASES.items():
        prop = properties.get(alias)
        if isinstance(prop, Mapping):
            properties[alias] = {**prop, **_deprecated_argument_marker(target)}
    action = properties.get("action")
    note = deprecated_aliases_note(*ALIASED_ACTIONS_BY_TOOL.get(tool_name, ()))
    if note and isinstance(action, Mapping):
        existing = action.get("description")
        properties["action"] = {
            **action,
            "description": f"{existing} {note}" if existing else note,
        }
    marked["properties"] = properties
    return marked


def _resolve_dimension(value: Any) -> Any:
    if isinstance(value, str):
        return DEPRECATED_DIMENSION_ALIASES.get(value.upper(), value)
    return value


def _resolve_control_data(control_data: Any) -> Any:
    if not isinstance(control_data, dict):
        return control_data
    resolved = dict(control_data)
    if "groupBy" in resolved:
        resolved["groupBy"] = _resolve_dimension(resolved["groupBy"])
    filters = resolved.get("filters")
    if isinstance(filters, list):
        resolved["filters"] = [
            {**entry, "dimension": _resolve_dimension(entry["dimension"])}
            if isinstance(entry, dict) and "dimension" in entry
            else entry
            for entry in filters
        ]
    return resolved


def _resolve_dimensions(arguments: Dict[str, Any]) -> Dict[str, Any]:
    resolved = dict(arguments)
    for name in _DIMENSION_ARGUMENTS:
        if name in resolved:
            resolved[name] = _resolve_dimension(resolved[name])
    if "control_data" in resolved:
        resolved["control_data"] = _resolve_control_data(resolved["control_data"])
    return resolved


def resolve_department_aliases(
    tool_name: str, action: Any, arguments: Dict[str, Any]
) -> Tuple[Any, Dict[str, Any]]:
    """Rewrite deprecated org-unit spellings to their department names.

    A department argument sent alongside its deprecated alias wins over it.
    """
    resolved_action = (
        DEPRECATED_ACTION_ALIASES.get(action, action) if isinstance(action, str) else action
    )
    resolved: Dict[str, Any] = {}
    for name, value in arguments.items():
        target = DEPRECATED_ARGUMENT_ALIASES.get(name)
        if target is None:
            resolved[name] = value
        elif target not in arguments:
            resolved[target] = value
    if "action" in resolved:
        resolved["action"] = resolved_action
    if tool_name in DIMENSION_ALIAS_TOOLS:
        resolved = _resolve_dimensions(resolved)
    return resolved_action, resolved
