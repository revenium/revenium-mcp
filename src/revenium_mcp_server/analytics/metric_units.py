"""Units for the analytics figures.

The platform labels each analytics row with the endpoint that produced it as
``metricType`` (``PROFIT_MARGIN_BY_CUSTOMER``, ``TOP_MOVERS``, ...), not with a
unit. The unit of each figure comes from that endpoint's field description in
``specs/openapi/isotope.json``: profit margins are percents, the top-movers
change is a percent and its current and previous values are USD, and task
performance is milliseconds. Lookups are by the exact metricType. Dollar
figures follow the rule in ``common/money.py``.
"""

from typing import Any, Callable, Dict, Optional

from ..common.money import is_finite_number, render_dollars

NO_REVENUE_NOTE = "(no revenue, or revenue equal to cost; the platform reports 0 for both)"


def _percent(value: float) -> str:
    return f"{(0.0 if value == 0 else value):,.2f}%"


def _profit_margin(value: float) -> str:
    return f"{_percent(value)} {NO_REVENUE_NOTE}" if value == 0 else _percent(value)


def _milliseconds(value: float) -> str:
    return f"{int(value):,} ms" if float(value).is_integer() else f"{value:,.2f} ms"


_METRIC_RESULT_FORMATS: Dict[str, Callable[[float], str]] = {
    "PROFIT_MARGIN_BY_CUSTOMER": _profit_margin,
    "PROFIT_MARGIN_BY_PRODUCT": _profit_margin,
    "TOP_MOVERS": _percent,
    "TASK_PERFORMANCE_BY_AGENT": _milliseconds,
}

_COMPARISON_FORMATS: Dict[str, Callable[[float], str]] = {
    "TOP_MOVERS": render_dollars,
}


def _lookup(formats: Dict[str, Callable[[float], str]], value: Any, metric_type: Any) -> Optional[str]:
    render = formats.get(str(metric_type or "").upper())
    if render is None or not is_finite_number(value):
        return None
    return render(value)


def format_metric_result(value: Any, metric_type: Any) -> Optional[str]:
    """A row's metricResult with its unit, or None when the metricType has no known unit."""
    return _lookup(_METRIC_RESULT_FORMATS, value, metric_type)


def format_comparison_value(value: Any, metric_type: Any) -> Optional[str]:
    """A row's currentValue or previousValue with its unit, or None when unknown."""
    return _lookup(_COMPARISON_FORMATS, value, metric_type)

