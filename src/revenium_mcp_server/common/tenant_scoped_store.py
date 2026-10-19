"""Bounded in-memory store whose entries are visible only to the organization that wrote them."""
from __future__ import annotations

from collections import OrderedDict
from typing import Generic, List, Optional, Tuple, TypeVar

from ..auth.tenant_scope import TenantScope

V = TypeVar("V")


class TenantScopedStore(Generic[V]):
    """Entries keyed by (scope, id); the oldest entry is evicted once ``max_entries`` is reached.

    One process serves many hosted customers, so an id alone never identifies
    an entry: two organizations may use the same id, and neither may see or
    change the other's entry.
    """

    def __init__(self, max_entries: int) -> None:
        self.max_entries = max_entries
        self._entries: "OrderedDict[Tuple[TenantScope, str], V]" = OrderedDict()

    def put(self, scope: TenantScope, entry_id: str, value: V) -> None:
        entry_key = (scope, entry_id)
        self._entries.pop(entry_key, None)
        self._entries[entry_key] = value
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def get(self, scope: TenantScope, entry_id: str) -> Optional[V]:
        return self._entries.get((scope, entry_id))

    def contains(self, scope: TenantScope, entry_id: str) -> bool:
        return (scope, entry_id) in self._entries

    def ids(self, scope: TenantScope) -> List[str]:
        return [entry_id for owner, entry_id in self._entries if owner == scope]

    def items(self, scope: TenantScope) -> List[Tuple[str, V]]:
        return [
            (entry_id, value)
            for (owner, entry_id), value in self._entries.items()
            if owner == scope
        ]

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)
