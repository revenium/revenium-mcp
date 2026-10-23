"""BACK-4855: a test that patches the shared httpx client's instance must not hide the next test's class-level patch.

The two tests run in file order: the first leaves monkeypatch's undo behind,
the second checks that it is gone.
"""

import httpx

from src.revenium_mcp_server.client import get_shared_http_client


async def _never_sent(*args, **kwargs):
    raise AssertionError("the instance patch must not outlive its test")


def test_patching_the_shared_client_instance(monkeypatch):
    monkeypatch.setattr(get_shared_http_client(), "request", _never_sent)

    assert get_shared_http_client().request is _never_sent


def test_the_next_test_sees_the_class_level_patch(monkeypatch):
    async def recorder(self, *args, **kwargs):
        return None

    monkeypatch.setattr(httpx.AsyncClient, "request", recorder)

    assert "request" not in vars(get_shared_http_client())
    assert get_shared_http_client().request.__func__ is recorder
