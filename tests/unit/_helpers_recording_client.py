"""A real `ReveniumClient` whose HTTP transport records requests and answers them.

BACK-4709: the subscription tool called a client method that does not exist, and
its tests passed because they used a bare mock client that answers any name.
Building the real client and replacing only `client.client.request` keeps the
production method surface, URL building and team-id injection under test while
no request leaves the process.
"""

import json
from typing import Any, Callable, Dict, List, Optional, Tuple
from unittest.mock import MagicMock

from src.revenium_mcp_server.auth import AuthConfig
from src.revenium_mcp_server.client import ReveniumClient

Answer = Callable[[str, str, Optional[Dict[str, Any]]], Any]


def recording_client(monkeypatch: Any, answer: Answer) -> Tuple[ReveniumClient, List[Dict[str, Any]]]:
    """Return a real client and the list every request it sends is appended to.

    `answer(method, url, params)` returns the JSON body for a request; raise from
    it to fail a request the test must never send.
    """
    # Config auto-discovery (an unset app URL, or the first import of the
    # onboarding defaults) calls the platform with whatever key the
    # developer's shell exports; without a key it makes no call.
    monkeypatch.setenv("REVENIUM_APP_BASE_URL", "https://example.invalid")
    monkeypatch.delenv("REVENIUM_API_KEY", raising=False)
    client = ReveniumClient(
        auth_config=AuthConfig(
            api_key="hak_test_abcd1234",
            team_id="team_1",
            base_url="https://example.invalid",
        )
    )
    requests: List[Dict[str, Any]] = []

    async def fake_request(method, url, params=None, json=None, headers=None):
        requests.append({"method": method, "url": url, "params": params, "json": json})
        body = answer(method, url, params)
        resp = MagicMock()
        resp.status_code = 200
        resp.content = _encode(body)
        resp.text = resp.content.decode()
        resp.json = MagicMock(return_value=body)
        resp.is_success = True
        resp.headers = {"content-type": "application/json"}
        return resp

    monkeypatch.setattr(client.client, "request", fake_request)
    return client, requests


def _encode(body: Any) -> bytes:
    return json.dumps(body).encode()
