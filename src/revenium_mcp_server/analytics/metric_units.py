"""Units for the analytics figures, and dollar amounts that keep their sub-cent digits.

The platform labels each analytics row with the endpoint that produced it as
``metricType`` (``PROFIT_MARGIN_BY_CUSTOMER``, ``TOP_MOVERS``, ...), not with a
unit. The unit of each figure comes from that endpoint's field description in
``specs/openapi/isotope.json``: profit margins are percents, the top-movers
change is a percent and its current and previous values are USD, and task
performance is milliseconds. Lookups are by the exact metricType.

Every analytics dollar figure follows one rule: two decimals from a cent up,
two significant digits below a cent. ``render_usd`` prints it as "X USD" and
``render_dollars`` as "$X".
"""

import math
from typing import Any, Callable, Dict, Optional

NO_REVENUE_NOTE = "(no revenue, or revenue equal to cost; the platform reports 0 for both)"


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _percent(value: float) -> str:
    return f"{(0.0 if value == 0 else value):,.2f}%"


def _profit_margin(value: float) -> str:
    return f"{_percent(value)} {NO_REVENUE_NOTE}" if value == 0 else _percent(value)


def _milliseconds(value: float) -> str:
    return f"{int(value):,} ms" if float(value).is_integer() else f"{value:,.2f} ms"


def _usd_amount(value: float) -> str:
    if value == 0:
        return "0.00"
    if abs(value) >= 0.01:
        return f"{value:,.2f}"
    decimals = 1 - math.floor(math.log10(abs(value)))
    return f"{value:.{decimals}f}".rstrip("0")


_METRIC_RESULT_FORMATS: Dict[str, Callable[[float], str]] = {
    "PROFIT_MARGIN_BY_CUSTOMER": _profit_margin,
    "PROFIT_MARGIN_BY_PRODUCT": _profit_margin,
    "TOP_MOVERS": _percent,
    "TASK_PERFORMANCE_BY_AGENT": _milliseconds,
}

_COMPARISON_FORMATS: Dict[str, Callable[[float], str]] = {
    "TOP_MOVERS": lambda value: render_dollars(value),
}


def _lookup(formats: Dict[str, Callable[[float], str]], value: Any, metric_type: Any) -> Optional[str]:
    render = formats.get(str(metric_type or "").upper())
    if render is None or not _is_number(value):
        return None
    return render(value)


def format_metric_result(value: Any, metric_type: Any) -> Optional[str]:
    """A row's metricResult with its unit, or None when the metricType has no known unit."""
    return _lookup(_METRIC_RESULT_FORMATS, value, metric_type)


def format_comparison_value(value: Any, metric_type: Any) -> Optional[str]:
    """A row's currentValue or previousValue with its unit, or None when unknown."""
    return _lookup(_COMPARISON_FORMATS, value, metric_type)


def render_usd(amount: Any) -> str:
    """A USD amount with separators and two decimals, two significant digits below a cent; n/a when missing."""
    if not _is_number(amount):
        return "n/a"
    return f"{_usd_amount(amount)} USD"


def render_dollars(amount: Any) -> str:
    """The same amount as render_usd in the "$" form; n/a when missing or not finite."""
    if not _is_number(amount):
        return "n/a"
    return f"${_usd_amount(amount)}"
