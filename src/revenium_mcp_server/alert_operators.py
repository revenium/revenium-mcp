"""Threshold operators the Revenium platform accepts when an alert is created or updated.

The MCP has to advertise the *accepted* set. The platform's ``OperatorType`` enum
is wider than that set: it still declares ``EQUAL_TO`` and ``NOT_EQUAL_TO`` so
alerts stored before those were refused keep loading, but create and update refuse
both. An agent that reads the wider list and composes a create call walks into an
error the MCP itself recommended.

Platform anchors, in the ``hypercurrent`` repo under
``service/src/main/kotlin/io/hypercurrent/profitstream/service/v2/ai/alerts/``:

- ``AIAnomalyService.COMPARISON_OPERATORS`` — compares a value against a fixed
  threshold; mirrored here as :data:`COMPARISON_OPERATORS`.
- ``AlertCapabilityRegistry.CHANGE_OPERATORS`` — compares one period against the
  period before it; mirrored here as :data:`CHANGE_OPERATORS`.
- ``AIAnomalyService.ACCEPTED_OPERATORS`` — the union of the two.
  ``AIAnomalyService.getOperator`` refuses anything outside it (BACK-2875) and then
  narrows to ``AIAnomalyService.acceptedOperatorsFor(alertType)`` (BACK-3043),
  mirrored here as :data:`OPERATORS_BY_ALERT_TYPE`.

``EQUAL_TO`` and ``NOT_EQUAL_TO`` stay in the platform's ``OperatorType`` enum in
``AIAnomaly.kt`` and ``describeOperator`` still renders them, so alerts already
stored with either value keep listing and rendering normally. Only create and
update refuse them — see :data:`REJECTED_OPERATORS` and
:func:`rejected_operator_message`, which mirrors the alternative the platform's own
error names.

Why these values are hand-typed rather than read from
``specs/openapi/hypercurrent.json``: the snapshot publishes whatever the platform
annotates on the resource, and that annotation has been both wider and narrower
than the accepted set. Today ``AIAnomalyResource`` annotates ``operatorType`` with
exactly the eight accepted values and ``EnumSchemaConsistencyTest`` keeps that
annotation pinned to ``AIAnomalyService.ACCEPTED_OPERATORS``; the legacy pair
survives only in ``OperatorType`` in ``AIAnomaly.kt``, which no OpenAPI enum
publishes. ``tests/unit/test_alert_operators.py`` pins every name here against the
snapshot enum in a way that holds whichever shape the snapshot carries, so a
platform rename or a new operator fails a test rather than an agent.

Note for future readers: ``OperatorType`` in ``models.py`` /
``models_decomposed/alerts.py`` is a legacy shape whose members
(``GREATER_THAN_OR_EQUAL``, ``EQUAL``, ``CONTAINS``, ...) are not platform
``operatorType`` values at all. Do not use it to advertise or validate operators.
"""

from typing import Any, Dict, List, Tuple

from .exceptions import ValidationError

# AIAnomalyService.COMPARISON_OPERATORS — a value against a fixed threshold.
COMPARISON_OPERATORS: Tuple[str, ...] = (
    "GREATER_THAN",
    "GREATER_THAN_OR_EQUAL_TO",
    "LESS_THAN",
    "LESS_THAN_OR_EQUAL_TO",
)

# AlertCapabilityRegistry.CHANGE_OPERATORS — one period against the period before it.
CHANGE_OPERATORS: Tuple[str, ...] = (
    "INCREASES_BY",
    "DECREASES_BY",
    "PERCENT_INCREASE",
    "PERCENT_DECREASE",
)

# AIAnomalyService.ACCEPTED_OPERATORS — the union getOperator() checks first.
ACCEPTED_OPERATORS: Tuple[str, ...] = COMPARISON_OPERATORS + CHANGE_OPERATORS

# AIAnomalyService.acceptedOperatorsFor(alertType) — the per-type narrowing that
# runs after ACCEPTED_OPERATORS. THRESHOLD and CUMULATIVE_USAGE both evaluate
# through the absolute-value threshold check, which throws on a change operator;
# RELATIVE_CHANGE compares periods and only understands the change operators.
OPERATORS_BY_ALERT_TYPE: Dict[str, Tuple[str, ...]] = {
    "THRESHOLD": COMPARISON_OPERATORS,
    "CUMULATIVE_USAGE": COMPARISON_OPERATORS,
    "RELATIVE_CHANGE": CHANGE_OPERATORS,
}

# Declared by the platform, refused on create and update, still readable.
REJECTED_OPERATORS: Tuple[str, ...] = ("EQUAL_TO", "NOT_EQUAL_TO")

# The alternative AIAnomalyService.operatorNotSupportedMessage names, so the MCP
# points an agent the same way the platform would.
REJECTED_OPERATOR_GUIDANCE: str = (
    "An exact match on a continuous or aggregated value would rarely or never hold. "
    "Use GREATER_THAN, LESS_THAN, GREATER_THAN_OR_EQUAL_TO or "
    "LESS_THAN_OR_EQUAL_TO, or express a band as two alerts, one on each side."
)


def accepted_operators_for(alert_type: str) -> Tuple[str, ...]:
    """Return the operators the platform accepts for ``alert_type``.

    An unrecognised alert type falls back to the full accepted set rather than an
    empty one: the platform is the authority on a type this build has not heard
    of, so let it answer instead of refusing the call here.
    """
    return OPERATORS_BY_ALERT_TYPE.get(str(alert_type).upper(), ACCEPTED_OPERATORS)


def is_rejected_operator(operator: str) -> bool:
    """Whether the platform declares ``operator`` but refuses it on create/update."""
    return str(operator).upper() in REJECTED_OPERATORS


def rejected_operator_message(operator: str) -> str:
    """The refusal an agent should see for a declared-but-unaccepted operator."""
    return (
        f"Operator {operator} is not supported for AI alerts. "
        f"{REJECTED_OPERATOR_GUIDANCE}"
    )


def historical_operator_notice(operator: str) -> str:
    """The note to attach when a call resubmits a stored, no-longer-accepted operator.

    Enable, disable and a partial update all read the stored definition and PUT it
    back whole. When that definition carries an operator the platform stored before
    it stopped accepting the value, blocking the call would make the alert
    uneditable and undeletable through the MCP for a value the platform itself
    wrote. So the call goes out and the caller is told what it carried.
    """
    return (
        f"Note: this alert stores operatorType {operator}, which the platform still "
        f"returns on read but no longer accepts on create or update. If the platform "
        f"refuses this call, change the operator first. "
        f"{REJECTED_OPERATOR_GUIDANCE}"
    )


# ---------------------------------------------------------------------------
# Filter operators. A DIFFERENT vocabulary from everything above: the constants
# above are ``operatorType`` values, which compare a metric against a threshold;
# these are ``AIAnomalyFilter.operator`` values, which compare a dimension
# (MODEL, PROVIDER, ...) against a value. The two sets never mix, and neither one
# is a fallback for the other.
#
# Platform anchor: ``AIAnomalyFilter.kt`` in the ``hypercurrent`` repo, whose
# ``operator`` enum the ``AIAnomalyFilter`` schema in
# ``specs/openapi/hypercurrent.json`` publishes. ``IN`` arrived with BACK-2972,
# together with the ``values`` list it reads.
# ---------------------------------------------------------------------------

# AIAnomalyFilter.operator — the whole accepted set.
FILTER_OPERATORS: Tuple[str, ...] = (
    "IS",
    "IS_NOT",
    "CONTAINS",
    "STARTS_WITH",
    "ENDS_WITH",
    "IN",
)

# The one operator that reads ``values`` instead of ``value``.
FILTER_LIST_OPERATOR: str = "IN"

# Aliases callers reach for that the platform does not declare. They live beside
# the vocabulary because every surface that maps an incoming filter row maps them.
FILTER_OPERATOR_ALIASES: Dict[str, str] = {
    "EQUALS": "IS",
    "EQUAL": "IS",
    "NOT_EQUALS": "IS_NOT",
    "NOT_EQUAL": "IS_NOT",
}

# The exclusivity rule, spelled once. Every surface that teaches the filter row
# shape — the input schema descriptions, the capability text, the examples —
# interpolates this rather than restating it.
FILTER_IN_OPERATOR_NOTE: str = (
    'The IN operator ("is one of") takes its list in `values` instead of a single '
    "`value` and matches when the dimension equals any listed entry; every other "
    "operator takes `value`. A row carries one or the other, never both. Filter "
    "rows are still combined with AND, so IN adds OR within one row only."
)


def normalize_filter_operator(operator: object) -> str:
    """Return ``operator`` upper-cased with the non-platform aliases resolved.

    An operator this build has never heard of comes back unchanged (upper-cased)
    rather than replaced, so the caller is the one that decides to refuse it.
    """
    raw = str(operator).strip().upper()
    return FILTER_OPERATOR_ALIASES.get(raw, raw)


def validate_filter_rows(filters: List[Any]) -> List[Dict[str, Any]]:
    """Normalize API-format anomaly filter rows and refuse the shapes the platform will.

    One row is one dimension compared against one value, except for ``IN``, which
    compares against the list in ``values`` (``AIAnomalyFilter.kt``, BACK-2972).
    The two fields are mutually exclusive, and getting that wrong is silent
    upstream — an ``IN`` row with no ``values`` matches nothing rather than
    erroring — so it is refused here, naming the field that is missing.

    This lives beside the vocabulary rather than in either caller because BOTH
    filter shapes have to end up here: the API-format rows
    ``AnomalyManager`` validates on create and update, and the rows
    ``InputValidator._convert_filters_to_api_format`` builds from the
    user-friendly ``field``/``operator``/``value`` shape. A rule enforced on one
    path and skipped on its sibling is the same bug in a different doorway.

    ``values`` entries must already be strings: the published contract says so,
    and coercing would turn ``[null, 42]`` into the model names ``"None"`` and
    ``"42"`` — an alert scoped to something the caller never asked for. A row
    without ``dimension`` is the user-friendly shape on its way to conversion and
    is passed through untouched. Keys this build does not know are carried
    through rather than dropped, so a field the platform adds is not silently
    swallowed on the way out.

    A ``value`` alongside ``IN`` is dropped rather than refused: the platform
    reads ``values`` on that branch and ignores ``value``, so refusing would be
    stricter than the API itself.
    """
    validated: List[Dict[str, Any]] = []

    for filter_item in filters:
        if not isinstance(filter_item, dict):
            raise ValidationError(
                message="Each filter must be a dictionary",
                field="filters",
                value=type(filter_item).__name__,
                expected="Dictionary with dimension, operator and value (or values for IN)",
            )

        if "dimension" not in filter_item:
            validated.append(filter_item)
            continue

        if "operator" not in filter_item:
            raise ValidationError(
                message="Filter missing required field: operator",
                field="filters",
                value=filter_item,
                expected=f"One of: {', '.join(FILTER_OPERATORS)}",
            )

        operator = normalize_filter_operator(filter_item["operator"])
        if operator not in FILTER_OPERATORS:
            raise ValidationError(
                message=f"Invalid filter operator: {filter_item['operator']}",
                field="filters",
                value=filter_item["operator"],
                expected=f"One of: {', '.join(FILTER_OPERATORS)}",
                suggestion=FILTER_IN_OPERATOR_NOTE,
            )

        row = dict(filter_item)
        row["dimension"] = str(filter_item["dimension"]).upper()
        row["operator"] = operator
        raw_values = filter_item.get("values")

        if operator == FILTER_LIST_OPERATOR:
            if not isinstance(raw_values, list) or not raw_values:
                raise ValidationError(
                    message=(
                        f"Filter operator {FILTER_LIST_OPERATOR} requires a non-empty "
                        "'values' list"
                    ),
                    field="values",
                    value=raw_values,
                    expected="Non-empty list of strings, e.g. ['gpt-4', 'claude-sonnet-4-5']",
                    suggestion=FILTER_IN_OPERATOR_NOTE,
                )
            entries: List[str] = []
            for index, entry in enumerate(raw_values):
                if not isinstance(entry, str):
                    raise ValidationError(
                        message=(
                            f"Filter 'values' entry at index {index} is a "
                            f"{type(entry).__name__}, not a string"
                        ),
                        field="values",
                        value=entry,
                        expected="String, e.g. 'gpt-4'",
                        suggestion=FILTER_IN_OPERATOR_NOTE,
                    )
                stripped = entry.strip()
                if not stripped:
                    raise ValidationError(
                        message=(
                            f"Filter operator {FILTER_LIST_OPERATOR} rejects blank entries in "
                            f"'values' (index {index})"
                        ),
                        field="values",
                        value=raw_values,
                        expected="Non-empty list of non-blank strings",
                    )
                entries.append(stripped)
            row["values"] = entries
            row.pop("value", None)
        else:
            if isinstance(raw_values, list) and raw_values:
                raise ValidationError(
                    message=(
                        f"Filter operator {operator} takes a single 'value'; 'values' is "
                        f"read only for {FILTER_LIST_OPERATOR}"
                    ),
                    field="values",
                    value=raw_values,
                    expected=(
                        f"Use operator {FILTER_LIST_OPERATOR} to match a list, or send a "
                        "single 'value'"
                    ),
                    suggestion=FILTER_IN_OPERATOR_NOTE,
                )
            value = filter_item.get("value")
            if value is None or not str(value).strip():
                raise ValidationError(
                    message=f"Filter operator {operator} requires a non-empty 'value'",
                    field="filters",
                    value=filter_item,
                    expected="Dictionary with dimension, operator and value",
                    suggestion=FILTER_IN_OPERATOR_NOTE,
                )
            row["value"] = str(value)
            row.pop("values", None)

        validated.append(row)

    return validated
