"""Reading every page of a paged analytics envelope, and saying so when the read stops early."""

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ..constants import ANALYTICS_MAX_PAGE_SIZE
from .paging import PageInfo

logger = logging.getLogger(__name__)

# Every paged envelope read asks for the platform's largest page and follows
# the rest, up to ENVELOPE_MAX_PAGES (2,000 rows: a year of daily buckets for
# several groups) so one call cannot fan out without bound.
ENVELOPE_PAGE_SIZE = ANALYTICS_MAX_PAGE_SIZE
ENVELOPE_MAX_PAGES = 20

PageFetcher = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]


@dataclass(frozen=True)
class UnreadPages:
    """A paged envelope read that stopped at ENVELOPE_MAX_PAGES before the last page."""

    endpoint_key: str
    pages_read: int
    total_pages: int
    total_elements: Optional[int]


def with_unread_pages_notice(text: str, unread: Optional[UnreadPages]) -> str:
    """Say so when the read stopped before the platform's last page."""
    if unread is None:
        return text
    return (
        f"{text}\n\n_Incomplete: the platform holds {unread.total_pages} pages of rows for "
        f"this report and this read stops after {unread.pages_read} pages of "
        f"{ENVELOPE_PAGE_SIZE}, so the figures above leave the rest out. Narrow the "
        "period, for example with a shorter start_date/end_date range, to read all of it._"
    )


@dataclass(frozen=True)
class EnvelopeRead:
    """An analytics envelope with every page's rows, and what was left unread if the read stopped early."""

    envelope: Dict[str, Any]
    unread: Optional[UnreadPages] = None


def envelope_items(response: Any) -> List[Dict[str, Any]]:
    """Return ``_embedded.items`` from an analytics envelope; anything else yields an empty list."""
    if not isinstance(response, dict):
        return []
    embedded = response.get("_embedded", {})
    if not isinstance(embedded, dict):
        return []
    items = embedded.get("items", [])
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


async def read_every_page(key: str, fetch_page: PageFetcher, params: Dict[str, Any]) -> EnvelopeRead:
    """Read the first page with ``params``, then append every further page's items to it.

    The first page's ``page`` block names how many pages there are; the walk
    stops after ENVELOPE_MAX_PAGES and records what it left unread.
    """
    envelope = await fetch_page(params)
    first_page = PageInfo.from_envelope(envelope)
    total_pages = first_page.total_pages or 1
    pages_to_read = min(total_pages, ENVELOPE_MAX_PAGES)
    if pages_to_read <= 1:
        return EnvelopeRead(envelope)
    items = envelope_items(envelope)
    for number in range(1, pages_to_read):
        items.extend(envelope_items(await fetch_page({**params, "page": number})))
    envelope["_embedded"] = {"items": items}
    if total_pages == pages_to_read:
        return EnvelopeRead(envelope)
    logger.warning("Stopped reading %s after %d of %d pages", key, pages_to_read, total_pages)
    return EnvelopeRead(
        envelope,
        UnreadPages(
            endpoint_key=key,
            pages_read=pages_to_read,
            total_pages=total_pages,
            total_elements=first_page.total_elements,
        ),
    )
