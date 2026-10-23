"""Dollar amounts that keep their sub-cent digits.

Every analytics dollar figure follows one rule: two decimals from a cent up,
two significant digits below a cent. ``render_usd`` prints it as "X USD" and
``render_dollars`` as "$X".

A unit price or a per-call cost is quoted back to a user verbatim, so
``render_exact_dollars`` keeps every significant digit at any magnitude and
only pads to the caller's minimum decimals; it never rounds a price away.

An amount the platform states as a total, such as an alert's triggered value
or a billed charge, prints with ``render_rounded_amount``: six decimals, or two
significant digits when that needs more, trailing zeros trimmed.
``render_rounded_dollars`` is the "$" form for an alert value or an average:
``render_dollars`` from a dollar up, ``render_rounded_amount`` below.
"""

import math
from decimal import Decimal
from typing import Any

# Fifteen significant digits drop the binary noise a product of two floats
# leaves (10 * 0.000000042 -> 4.2000000000000006e-07) without touching a price.
_EXACT_SIGNIFICANT_DIGITS = 15

# A millionth of a dollar: stops a repeating quotient (0.534666666666667 ->
# 0.534667) while a billed fraction of a cent keeps its digits.
_ROUNDED_DECIMALS = 6


def is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _decimals_for_two_significant_digits(value: float) -> int:
    return 1 - math.floor(math.log10(abs(value)))


def _usd_amount(value: float) -> str:
    if value == 0:
        return "0.00"
    if abs(value) >= 0.01:
        return f"{value:,.2f}"
    return f"{value:.{_decimals_for_two_significant_digits(value)}f}".rstrip("0")


def _rounded_amount(value: float, min_decimals: int, grouped: bool) -> str:
    decimals = _ROUNDED_DECIMALS
    if value != 0:
        decimals = max(decimals, _decimals_for_two_significant_digits(value))
    separator = "," if grouped else ""
    whole, _, fraction = f"{value:{separator}.{decimals}f}".partition(".")
    fraction = fraction.rstrip("0").ljust(min_decimals, "0")
    return f"{whole}.{fraction}" if fraction else whole


def _exact_amount(value: float, min_decimals: int) -> str:
    value = 0.0 if value == 0 else value
    digits = format(Decimal(format(value, f".{_EXACT_SIGNIFICANT_DIGITS}g")), "f")
    whole, _, fraction = digits.partition(".")
    fraction = fraction.ljust(min_decimals, "0")
    return f"{whole}.{fraction}" if fraction else whole


def render_usd(amount: Any) -> str:
    """A USD amount with separators and two decimals, two significant digits below a cent; n/a when missing."""
    if not is_finite_number(amount):
        return "n/a"
    return f"{_usd_amount(amount)} USD"


def render_dollars(amount: Any) -> str:
    """The same amount as render_usd in the "$" form; n/a when missing or not finite."""
    if not is_finite_number(amount):
        return "n/a"
    return f"${_usd_amount(amount)}"


def render_exact_dollars(amount: Any, min_decimals: int) -> str:
    """A price or per-call cost as "$X" with every significant digit, padded to min_decimals; n/a when missing."""
    if not is_finite_number(amount):
        return "n/a"
    return f"${_exact_amount(amount, min_decimals)}"


def render_rounded_amount(amount: Any, min_decimals: int = 2, grouped: bool = False) -> str:
    """A stated amount without a symbol: six decimals, or two significant digits when that needs more; n/a when missing.

    ``grouped`` adds thousands separators.
    """
    if not is_finite_number(amount):
        return "n/a"
    return _rounded_amount(amount, min_decimals, grouped)


def render_rounded_dollars(amount: Any) -> str:
    """"$X" from render_dollars at a dollar or more, render_rounded_amount below; n/a when missing."""
    if not is_finite_number(amount):
        return "n/a"
    sign = "-" if amount < 0 else ""
    magnitude = abs(amount)
    if magnitude >= 1:
        return f"{sign}{render_dollars(magnitude)}"
    return f"{sign}${render_rounded_amount(magnitude)}"
