"""What this process last wrote to each record, so an update never merges onto a read that predates it."""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Dict,
    Mapping,
    NamedTuple,
    Optional,
    Tuple,
)

from ..auth.tenant_scope import TenantScope, tenant_scope
from .tenant_scoped_store import TenantScopedStore

# The platform's get-by-id serves the pre-write copy for 25 to 30 s after a PUT
# (measured in the BACK-4817 / BACK-4816 proof); 120 s leaves a wide margin.
RECENT_WRITE_TTL_SECONDS = 120.0
RECENT_WRITE_MAX_RECORDS = 1000
RECENT_WRITE_MAX_CHAIN = 8
# capped() keeps the first value a lagging read serves plus at least the latest write.
assert RECENT_WRITE_MAX_CHAIN >= 2


class _Write(NamedTuple):
    """A baseline read value of a field, then each value the platform is known to have stored for it.

    A known stored value is one this process sent, or one the platform's answer
    or a read back showed instead. After a collapse the baseline is the last
    value a read was seen to catch up to.
    """

    values: Tuple[Any, ...]
    written_at: float

    @property
    def latest(self) -> Any:
        return self.values[-1]

    def is_stale(self, stored: Any) -> bool:
        """True when a read shows a value this chain replaced, not the latest one nor a third party's."""
        return not shows_written_value(stored, self.latest) and any(
            shows_written_value(stored, earlier) for earlier in self.values[:-1]
        )

    def caught_up(self, stored: Any) -> bool:
        """True when a read shows the latest value and no earlier one, so it cannot be a stale read.

        A chain that wrote a value back (A, B, A) leaves a read showing A
        ambiguous: it may still be the original A, so the chain is kept until it expires.
        """
        return shows_written_value(stored, self.latest) and not any(
            shows_written_value(stored, earlier) for earlier in self.values[:-1]
        )

    def collapsed(self) -> "_Write":
        """Only the latest value: once a read shows it, earlier values can never be stale evidence again."""
        return _Write((self.latest,), self.written_at)

    def extended(self, read_value: Any, value: Any, written_at: float) -> "_Write":
        """This chain with a new write, or a fresh chain when the read shows a value it never held."""
        if self.caught_up(read_value):
            return _Write((self.latest, value), written_at)
        if any(shows_written_value(read_value, known) for known in self.values):
            return _Write(capped(self.values + (value,)), written_at)
        return _Write((read_value, value), written_at)


def capped(values: Tuple[Any, ...]) -> Tuple[Any, ...]:
    """The first value, which a lagging read keeps serving, and the most recent writes after it."""
    if len(values) <= RECENT_WRITE_MAX_CHAIN:
        return values
    return values[:1] + values[-(RECENT_WRITE_MAX_CHAIN - 1):]


WrittenFields = Dict[str, _Write]
RecordKey = Tuple[TenantScope, str]


def writer_scope() -> Optional[TenantScope]:
    """The organization this request writes for, or None when no tenant context is bound."""
    try:
        return tenant_scope()
    except PermissionError:
        return None


def record_name(resource_type: str, resource_id: str) -> str:
    return f"{resource_type}:{resource_id}"


def shows_written_value(stored: Any, written: Any) -> bool:
    """True when a read already carries a written value; an object counts when it holds every written key."""
    if isinstance(written, Mapping) and isinstance(stored, Mapping):
        return all(
            key in stored and shows_written_value(stored[key], value)
            for key, value in written.items()
        )
    return bool(stored == written)


class _KeyedLocks:
    """One asyncio lock per record, dropped once nobody holds or waits for it."""

    def __init__(self) -> None:
        self._locks: Dict[RecordKey, Tuple[asyncio.Lock, int]] = {}

    @asynccontextmanager
    async def held(self, key: RecordKey) -> AsyncIterator[None]:
        lock, users = self._locks.get(key, (asyncio.Lock(), 0))
        self._locks[key] = (lock, users + 1)
        try:
            async with lock:
                yield
        finally:
            lock, users = self._locks[key]
            if users == 1:
                del self._locks[key]
            else:
                self._locks[key] = (lock, users - 1)


class RecentWrites:
    """The fields each organization's recent updates stored, per record, for one process.

    Entries expire after ``ttl_seconds`` and at most ``max_records`` records are
    kept, so memory stays bounded however many records are updated.
    """

    def __init__(
        self,
        ttl_seconds: float = RECENT_WRITE_TTL_SECONDS,
        max_records: int = RECENT_WRITE_MAX_RECORDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._written: TenantScopedStore[WrittenFields] = TenantScopedStore(max_records)
        self._locks = _KeyedLocks()

    @asynccontextmanager
    async def one_at_a_time(
        self, scope: Optional[TenantScope], record: str
    ) -> AsyncIterator[None]:
        """Run updates of one record in turn, so each reads after the previous one is remembered."""
        if scope is None:
            yield
            return
        async with self._locks.held((scope, record)):
            yield

    def unseen_fields(
        self, scope: Optional[TenantScope], record: str, stored: Mapping[str, Any]
    ) -> Dict[str, Any]:
        """Recently written fields the read still shows with a value they held earlier, with the latest written values.

        A field the read shows with a value this process never wrote nor read
        before writing was changed by someone else, so it is not reported.
        """
        entry = self._live_entry(scope, record)
        return {
            field: write.latest
            for field, write in entry.items()
            if field in stored and write.is_stale(stored[field])
        }

    def observe_read(
        self, scope: Optional[TenantScope], record: str, stored: Mapping[str, Any]
    ) -> None:
        """Forget the earlier values of each field a read shows caught up to its latest stored value.

        Only an update holding ``one_at_a_time`` for the record may call this,
        so a preview never reshapes a chain another update relies on.
        """
        entry = self._live_entry(scope, record)
        caught_up = {
            field: write.collapsed()
            for field, write in entry.items()
            if field in stored and len(write.values) > 1 and write.caught_up(stored[field])
        }
        if scope is None or not caught_up:
            return
        entry.update(caught_up)
        self._written.put(scope, record, entry)

    def remember(
        self,
        scope: Optional[TenantScope],
        record: str,
        fields: Mapping[str, Any],
        read_before: Mapping[str, Any],
    ) -> None:
        """Record the values the platform stored for fields the read an update merged onto names.

        The latest value of a field's chain is what the platform stored, whether
        that is the value sent or another one its answer or a read back showed,
        so a later stale read is overlaid with what is stored, never a value it replaced.

        A field sent under a request-only name (``parentId`` beside the stored
        ``parent``) cannot be told stale from changed elsewhere, so it is not kept.
        """
        named = {field: value for field, value in fields.items() if field in read_before}
        if scope is None or not named:
            return
        written_at = self._clock()
        entry = self._live_entry(scope, record)
        for field, value in named.items():
            earlier = entry.get(field)
            entry[field] = (
                earlier.extended(read_before[field], value, written_at)
                if earlier is not None
                else _Write((read_before[field], value), written_at)
            )
        self._written.put(scope, record, entry)

    def known_values(
        self, scope: Optional[TenantScope], record: str, field: str
    ) -> Tuple[Any, ...]:
        """A field's baseline read value, then each value the platform is known to have stored, within the TTL.

        After a collapse the baseline is the last value a read caught up to.
        """
        write = self._live_entry(scope, record).get(field)
        return write.values if write is not None else ()

    def clear(self) -> None:
        self._written.clear()

    def __len__(self) -> int:
        return len(self._written)

    def _live_entry(self, scope: Optional[TenantScope], record: str) -> WrittenFields:
        if scope is None:
            return {}
        entry = self._written.get(scope, record) or {}
        oldest_live = self._clock() - self._ttl_seconds
        return {field: write for field, write in entry.items() if write.written_at > oldest_live}


RECENT_WRITES = RecentWrites()
