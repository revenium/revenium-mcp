"""Pages a list tool may read, and the heading each must print (BACK-4814).

A list heading counts the rows on the page against the total the platform
reported, through `format_page_count_heading`. Each case pairs one pagination
block with the exact heading for it, so a heading written by hand, or one that
reads the page from the arguments instead of the validated page, fails.
"""

import json
from typing import Any, Dict, List, Tuple

import pytest

LIST_HEADING_CASES = [
    pytest.param(
        {"totalPages": 25, "totalElements": 500},
        20,
        2,
        "Found 20 of 500 {noun} (page 3 of 25):",
        500,
        id="platform_total",
    ),
    pytest.param(
        {"totalPages": 1},
        1,
        0,
        "Found 1 {noun} on page 1; the platform reported no total, so more may exist:",
        None,
        id="no_total",
    ),
    pytest.param(
        {"totalPages": 2, "totalElements": 31},
        0,
        5,
        "Page 6 is past the last page (2 pages); the platform reports 31 {noun} "
        "in total. Pass page=0 for the first page.",
        31,
        id="past_the_end",
    ),
]


def rows(count: int) -> List[Dict[str, Any]]:
    """`count` list rows, each with its own id."""
    return [{"id": f"row_{index}", "name": f"Row {index}"} for index in range(count)]


def heading_and_body(text: str) -> Tuple[str, Dict[str, Any]]:
    """Split a list reply into its heading line and its JSON body."""
    heading, body = text.split("\n\n", 1)
    return heading, json.loads(body)
