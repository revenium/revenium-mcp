"""Flatten untrusted text to one bounded line before it reaches agent-facing output."""

import unicodedata
from typing import Any

# C0/C1 controls (Cc), format characters including the zero-width and
# bidi-override family (Cf), and lone surrogates (Cs). Unassigned code points
# (Cn) are deliberately NOT dropped: that would silently eat characters a newer
# Unicode release assigns.
_DROPPED_CATEGORIES = frozenset({"Cc", "Cf", "Cs"})

_ELLIPSIS = "..."


def one_line(value: Any, max_length: int) -> str:
    """Flatten a platform value to a single line of at most ``max_length`` characters.

    Rendered output is plain text an agent reads as status, so an embedded
    newline must not be able to fabricate a line of its own. Every run of
    whitespace, newlines and carriage returns included, collapses to a single
    space; other control and format characters are dropped; an overlong result
    is cut and ends in an ellipsis.
    """
    text = "".join(
        " " if char.isspace() else char
        for char in str(value)
        if char.isspace() or unicodedata.category(char) not in _DROPPED_CATEGORIES
    )
    text = " ".join(text.split())
    if len(text) > max_length:
        text = text[: max_length - len(_ELLIPSIS)].rstrip() + _ELLIPSIS
    return text
