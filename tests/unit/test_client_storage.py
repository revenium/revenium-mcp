"""Unit tests for the OAuth proxy client_storage factory."""
from __future__ import annotations

from src.revenium_mcp_server.auth import client_storage as cs


def test_returns_none_when_url_is_none():
    assert cs.build_client_storage(None, "secret") is None


def test_returns_none_when_url_is_empty():
    assert cs.build_client_storage("", "secret") is None


from key_value.aio.stores.redis import RedisStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper


def test_returns_fernet_wrapped_redis_store(monkeypatch):
    # Skip the real network ping; we are testing store construction only.
    monkeypatch.setattr(cs, "_ping_redis", lambda url: None)

    store = cs.build_client_storage("redis://localhost:6379/0", "secret")

    assert isinstance(store, FernetEncryptionWrapper)
    assert isinstance(store.key_value, RedisStore)


import pytest


class _FakeSyncClient:
    def __init__(self, *, fail: bool):
        self._fail = fail
        self.closed = False

    def ping(self):
        if self._fail:
            raise Exception("connection refused")
        return True

    def close(self):
        self.closed = True


def test_ping_success_closes_client(monkeypatch):
    client = _FakeSyncClient(fail=False)
    monkeypatch.setattr(cs.redis.Redis, "from_url", lambda url: client)

    assert cs._ping_redis("redis://localhost:6379/0") is None
    assert client.closed is True


def test_ping_failure_raises_runtimeerror_without_leaking_url(monkeypatch):
    client = _FakeSyncClient(fail=True)
    monkeypatch.setattr(cs.redis.Redis, "from_url", lambda url: client)

    with pytest.raises(RuntimeError, match="Redis server is unreachable") as excinfo:
        cs._ping_redis("redis://user:secretpw@host:6379/0")

    # The error message must not echo the URL or its inline credentials.
    assert "secretpw" not in str(excinfo.value)
    assert "host:6379" not in str(excinfo.value)


def test_build_propagates_ping_failure(monkeypatch):
    client = _FakeSyncClient(fail=True)
    monkeypatch.setattr(cs.redis.Redis, "from_url", lambda url: client)

    with pytest.raises(RuntimeError):
        cs.build_client_storage("redis://host:6379/0", "secret")


import fakeredis


def _route_to_shared_fakeredis(monkeypatch):
    """Skip the network ping and route RedisStore's async client to a single
    shared in-memory fake server so multiple build_client_storage() instances
    read/write the same data, exactly like multiple ECS tasks sharing Redis.
    """
    monkeypatch.setattr(cs, "_ping_redis", lambda url: None)
    server = fakeredis.FakeServer()
    monkeypatch.setattr(
        "key_value.aio.stores.redis.store.Redis",
        lambda *a, **k: fakeredis.aioredis.FakeRedis(
            server=server, decode_responses=True
        ),
    )
    return server


async def test_same_secret_decrypts_across_instances(monkeypatch):
    """The Fernet key is derived deterministically from the shared client_secret,
    so a second instance can decrypt the first's entries. A per-process/random
    key would reproduce "Client Not Registered" across tasks.
    """
    _route_to_shared_fakeredis(monkeypatch)

    writer = cs.build_client_storage("redis://shared", "shared-secret")
    reader = cs.build_client_storage("redis://shared", "shared-secret")

    await writer.put("client-key", {"client_id": "abc"}, collection=cs._COLLECTION)
    got = await reader.get("client-key", collection=cs._COLLECTION)

    assert got == {"client_id": "abc"}


async def test_different_secret_cannot_decrypt(monkeypatch):
    """A different client_secret derives a different Fernet key, so the entry
    fails to decrypt; raise_on_decryption_error=False turns that into a miss.
    """
    _route_to_shared_fakeredis(monkeypatch)

    writer = cs.build_client_storage("redis://shared", "secret-A")
    other = cs.build_client_storage("redis://shared", "secret-B")

    await writer.put("client-key", {"client_id": "abc"}, collection=cs._COLLECTION)
    got = await other.get("client-key", collection=cs._COLLECTION)

    assert got is None
