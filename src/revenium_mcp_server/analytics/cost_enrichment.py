"""Enrich manage_tools cost analytics responses with explicit USD labels.

The raw API responses for cost endpoints return bare numeric ``metricResult``
and ``totalCost`` values with no currency context. LLM consumers misinterpret
those numbers (e.g., dividing to normalize). This helper walks the response
and adds:

- ``currency: "USD"`` at the top level (when the root is a dict)
- ``metricResult_formatted: "$X,XXX.XX"`` next to every numeric ``metricResult``
- ``totalCost_formatted: "$X,XXX.XX"`` next to every numeric ``totalCost``

The transformation is additive: existing fields are never modified, and a new
structure is returned rather than mutating the input.
"""

from typing import Any

from .formatters.base_formatter import BaseFormattingUtilities

_COST_FIELDS = ("metricResult", "totalCost")


def _is_numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _walk(value: Any) -> Any:
    if isinstance(value, dict):
        enriched: dict = {}
        for key, val in value.items():
            enriched[key] = _walk(val)
        for field in _COST_FIELDS:
            if field in enriched and _is_numeric(enriched[field]):
                enriched[f"{field}_formatted"] = (
                    BaseFormattingUtilities.format_currency(enriched[field])
                )
        return enriched
    if isinstance(value, list):
        return [_walk(item) for item in value]
    return value


def enrich_cost_response(response: Any) -> Any:
    """Return a new response with USD currency labels and formatted cost fields.

    Non-dict / non-list inputs are returned unchanged.
    """
    walked = _walk(response)
    if isinstance(walked, dict):
        walked.setdefault("currency", "USD")
    return walked
