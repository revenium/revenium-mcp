"""The HAL ``page`` block of an analytics envelope, and the lines a report renders from it."""

from dataclasses import dataclass
from typing import Any, List, Mapping, Optional


@dataclass(frozen=True)
class PageInfo:
    """Position of one page in a paged analytics answer; None where the platform sent nothing."""

    number: Optional[int] = None
    size: Optional[int] = None
    total_pages: Optional[int] = None
    total_elements: Optional[int] = None

    @classmethod
    def from_envelope(cls, envelope: Mapping[str, Any]) -> "PageInfo":
        page = envelope.get("page")
        if not isinstance(page, Mapping):
            return cls()
        return cls(
            number=_whole_number(page.get("number")),
            size=_whole_number(page.get("size")),
            total_pages=_whole_number(page.get("totalPages")),
            total_elements=_whole_number(page.get("totalElements")),
        )

    @property
    def spans_several_pages(self) -> bool:
        return (self.total_pages or 0) > 1

    @property
    def next_number(self) -> Optional[int]:
        if self.number is None or self.total_pages is None:
            return None
        return self.number + 1 if self.number + 1 < self.total_pages else None

    @property
    def first_index(self) -> int:
        if self.number and self.size:
            return self.number * self.size + 1
        return 1

    @property
    def size_hint(self) -> str:
        return f" size={self.size}" if self.size else ""


def counted(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def pagination_lines(page: PageInfo, singular: str, plural: str) -> List[str]:
    """``Page X of Y, N <things> in all.`` plus the call that reads the next page."""
    if page.number is None or page.total_pages is None:
        return []
    total = (
        f"unknown {plural}"
        if page.total_elements is None
        else counted(page.total_elements, singular, plural)
    )
    lines = [f"Page {page.number + 1} of {max(page.total_pages, 1)}, {total} in all."]
    if page.next_number is not None:
        lines.append(f"Pass page={page.next_number}{page.size_hint} for the next page.")
    return lines


def past_last_page_sentence(page: PageInfo, described_total: str) -> str:
    """Say that the requested page is past the last one and name the pages that exist."""
    total_pages = max(page.total_pages or 1, 1)
    requested = "" if page.number is None else f" (page={page.number})"
    pages = counted(total_pages, "page", "pages")
    if total_pages == 1:
        where_to_read = f"Pass page=0{page.size_hint} for the only page."
    else:
        where_to_read = (
            f"Pass page={total_pages - 1}{page.size_hint} for the last page, or "
            f"page=0{page.size_hint} for the first."
        )
    return (
        f"The report has {described_total} on {pages}, and the page "
        f"requested{requested} is past the last. {where_to_read}"
    )


def _whole_number(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return int(value)
