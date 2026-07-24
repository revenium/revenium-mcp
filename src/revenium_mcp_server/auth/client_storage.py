"""Factory for the OAuth proxy's shared client_storage.

With MCP_OAUTH_REDIS_URL set, OAuth state goes to a shared Fernet-encrypted
Redis store so every task sees the same registrations; unset returns None and
FastMCP keeps its per-task local-disk default.
"""
from __future__ import annotations

import redis  # sync client, used only for the startup connectivity ping
from key_value.aio.protocols.key_value import AsyncKeyValue
from key_value.aio.stores.redis import RedisStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

_COLLECTION = "mcp-oauth-proxy"
_STORAGE_SALT = "mcp-oauth-redis-storage"


def _ping_redis(redis_url: str) -> None:
    """Fail-fast startup connectivity check; raises RuntimeError if unreachable.

    Sync client to avoid event-loop concerns at startup. The error carries only
    the exception type, never str(exc) (which can echo the URL/credentials); a
    close() failure is swallowed so a healthy connection isn't misreported.
    """
    try:
        client = redis.Redis.from_url(redis_url)
    except Exception as exc:  # noqa: BLE001 - a malformed URL is fatal at startup
        raise RuntimeError(
            "MCP_OAUTH_REDIS_URL is set but could not be parsed into a Redis "
            f"client ({type(exc).__name__})"
        ) from exc
    try:
        client.ping()
    except Exception as exc:  # noqa: BLE001 - any connect/auth failure is fatal
        raise RuntimeError(
            "MCP_OAUTH_REDIS_URL is set but the Redis server is unreachable "
            f"({type(exc).__name__})"
        ) from exc
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001 - close failures must not mask success
            pass


def build_client_storage(
    redis_url: str | None, client_secret: str
) -> AsyncKeyValue | None:
    if not redis_url:
        return None
    _ping_redis(redis_url)
    store = RedisStore(url=redis_url, default_collection=_COLLECTION)
    return FernetEncryptionWrapper(
        store,
        source_material=client_secret,
        salt=_STORAGE_SALT,
        raise_on_decryption_error=False,
    )
