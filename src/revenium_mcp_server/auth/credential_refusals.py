"""The API keys the Revenium platform refused while one hosted tool call ran.

ReveniumClient notes each refused key, and whether the refusal was ambiguous
(it may be about the request rather than the key); ApiKeyAuthMiddleware evicts
those keys' cached sign-ins when the call ends, however the tool reported the
refusal. Outside a tool call nothing is noted.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Dict, Iterator, Optional

_refused_during_call: ContextVar[Optional[Dict[str, bool]]] = ContextVar(
    "refused_during_call", default=None
)


@contextmanager
def evicting_refused_keys(
    evict: Callable[[str], None], evict_ambiguous: Callable[[str], None]
) -> Iterator[None]:
    """On exit, hand each key the platform refused inside the block to `evict`.

    A key whose every refusal was ambiguous goes to `evict_ambiguous` instead.
    """
    # One dict shared by reference, never re-bound: a task the tool spawns runs
    # on a copy of this context, so only a mutation of this object reaches here.
    ambiguous_by_key: Dict[str, bool] = {}
    reset_token = _refused_during_call.set(ambiguous_by_key)
    try:
        yield
    finally:
        _refused_during_call.reset(reset_token)
        for key, ambiguous in ambiguous_by_key.items():
            (evict_ambiguous if ambiguous else evict)(key)


def note_refused_key(credential: str, *, ambiguous: bool) -> None:
    ambiguous_by_key = _refused_during_call.get()
    if ambiguous_by_key is not None:
        ambiguous_by_key[credential] = ambiguous_by_key.get(credential, True) and ambiguous
