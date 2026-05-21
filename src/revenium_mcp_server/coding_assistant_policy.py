import asyncio
import time
from typing import Any, Dict, FrozenSet, List, Optional

from loguru import logger


SUBSCRIPTION_TO_METRIC_PROVIDERS: Dict[str, FrozenSet[str]] = {
    "claude-code": frozenset({"ClaudeCode", "ClaudeCowork"}),
    "gemini-cli": frozenset({"GeminiCli"}),
    "cursor": frozenset({"CursorIde"}),
    "codex-cli": frozenset({"CodexCli"}),
}

ALL_CODING_ASSISTANT_METRIC_PROVIDERS: FrozenSet[str] = frozenset().union(
    *SUBSCRIPTION_TO_METRIC_PROVIDERS.values()
)


class CodingAssistantPolicyCache:

    _DEFAULT_TTL_SECONDS = 30
    _ERROR_TTL_SECONDS = 5

    def __init__(self, ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds
        self._lock = asyncio.Lock()
        self._cache: Dict[str, _CacheEntry] = {}
        self._in_flight: Dict[str, asyncio.Task[Optional[FrozenSet[str]]]] = {}

    async def get_allowed_metric_providers(
        self,
        client: Any,
        tenant_id: Optional[str],
    ) -> Optional[FrozenSet[str]]:
        cache_key = tenant_id or client.team_id
        now = time.monotonic()

        async with self._lock:
            entry = self._cache.get(cache_key)
            if entry and now - entry.fetched_at < entry.ttl:
                return entry.allowed

            existing_task = self._in_flight.get(cache_key)
            if existing_task and not existing_task.done():
                task = existing_task
            else:
                task = asyncio.create_task(self._resolve(client, cache_key))
                self._in_flight[cache_key] = task

        try:
            return await task
        finally:
            async with self._lock:
                self._in_flight.pop(cache_key, None)

    async def _resolve(
        self, client: Any, cache_key: str
    ) -> Optional[FrozenSet[str]]:
        now = time.monotonic()
        try:
            subscribed = await self._fetch_subscribed_providers(client)
        except Exception as exc:
            logger.warning(
                "CodingAssistantPolicy: fetch failed for tenant {}, defaulting to allow-all: {}",
                cache_key,
                exc,
            )
            async with self._lock:
                self._cache[cache_key] = _CacheEntry(
                    allowed=None, fetched_at=now, ttl=self._ERROR_TTL_SECONDS
                )
            return None

        allowed = self._map_to_metric_providers(subscribed)
        async with self._lock:
            self._cache[cache_key] = _CacheEntry(
                allowed=allowed, fetched_at=now, ttl=self._ttl_seconds
            )
        return allowed

    async def _fetch_subscribed_providers(self, client: Any) -> List[str]:
        endpoint = "/profitstream/v2/api/coding-assistant/subscriptions/{}".format(
            client.team_id
        )
        response = await client.get(endpoint)

        if isinstance(response, list):
            return [item["provider"] for item in response if "provider" in item]

        if isinstance(response, dict):
            embedded = response.get("_embedded", {})
            items = (
                embedded.get("codingAssistantSubscriptionResponseList")
                or embedded.get("codingAssistantSubscriptionList")
                or []
            )
            if items:
                return [item["provider"] for item in items if "provider" in item]

            if "provider" in response:
                return [response["provider"]]

        return []

    @staticmethod
    def _map_to_metric_providers(subscribed: List[str]) -> FrozenSet[str]:
        result: set[str] = set()
        for sub_provider in subscribed:
            mapped = SUBSCRIPTION_TO_METRIC_PROVIDERS.get(sub_provider)
            if mapped:
                result.update(mapped)
            else:
                logger.warning(
                    "CodingAssistantPolicy: unknown subscription provider '{}', skipping",
                    sub_provider,
                )
        return frozenset(result)


class _CacheEntry:
    __slots__ = ("allowed", "fetched_at", "ttl")

    def __init__(
        self,
        allowed: Optional[FrozenSet[str]],
        fetched_at: float,
        ttl: float = 30,
    ) -> None:
        self.allowed = allowed
        self.fetched_at = fetched_at
        self.ttl = ttl


def filter_transactions_by_policy(
    transactions: List[Dict[str, Any]],
    allowed_metric_providers: Optional[FrozenSet[str]],
) -> List[Dict[str, Any]]:
    if allowed_metric_providers is None:
        return transactions

    return [
        txn
        for txn in transactions
        if _transaction_passes_policy(txn, allowed_metric_providers)
    ]


def _transaction_passes_policy(
    txn: Dict[str, Any],
    allowed_metric_providers: FrozenSet[str],
) -> bool:
    provider = txn.get("provider", "")
    if provider not in ALL_CODING_ASSISTANT_METRIC_PROVIDERS:
        return True
    return provider in allowed_metric_providers


_policy_cache = CodingAssistantPolicyCache()


def get_policy_cache() -> CodingAssistantPolicyCache:
    return _policy_cache
