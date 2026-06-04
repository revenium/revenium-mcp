"""Unit tests for Idempotency-Key auto-generation on metering POST methods."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import httpx
import pytest


def _make_client(monkeypatch):
    monkeypatch.setenv("REVENIUM_API_KEY", "hak_test_abcd1234")
    monkeypatch.setenv("REVENIUM_TEAM_ID", "test_team_id_456")
    monkeypatch.setenv("REVENIUM_BASE_URL", "https://example.invalid")

    from src.revenium_mcp_server.client import ReveniumClient

    client = ReveniumClient()
    captured: list[dict[str, str]] = []

    async def fake_request(method, url, params=None, json=None, headers=None):
        captured.append(dict(headers or {}))
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.content = b'{"ok":true}'
        resp.json = MagicMock(return_value={"ok": True})
        resp.headers = {"content-type": "application/json"}
        resp.is_success = True
        return resp

    monkeypatch.setattr(client.client, "request", fake_request)
    return client, captured


class TestMeterToolEventIdempotency:

    @pytest.mark.asyncio
    async def test_auto_generates_uuid4(self, monkeypatch):
        client, captured = _make_client(monkeypatch)
        await client.meter_tool_event({"toolId": "t1", "tokens": 100})

        key = captured[0].get("Idempotency-Key")
        assert key is not None
        parsed = uuid.UUID(key, version=4)
        assert str(parsed) == key

    @pytest.mark.asyncio
    async def test_forwards_explicit_key(self, monkeypatch):
        client, captured = _make_client(monkeypatch)
        await client.meter_tool_event(
            {"toolId": "t1"}, idempotency_key="meter-explicit-key",
        )

        assert captured[0]["Idempotency-Key"] == "meter-explicit-key"

    @pytest.mark.asyncio
    async def test_each_call_generates_unique_key(self, monkeypatch):
        client, captured = _make_client(monkeypatch)
        await client.meter_tool_event({"toolId": "t1", "tokens": 1})
        await client.meter_tool_event({"toolId": "t1", "tokens": 2})

        assert captured[0]["Idempotency-Key"] != captured[1]["Idempotency-Key"]


class TestRecordToolEventIdempotency:

    @pytest.mark.asyncio
    async def test_auto_generates_uuid4(self, monkeypatch):
        client, captured = _make_client(monkeypatch)
        await client.record_tool_event("tool-123", {"event_type": "usage"})

        key = captured[0].get("Idempotency-Key")
        assert key is not None
        uuid.UUID(key, version=4)

    @pytest.mark.asyncio
    async def test_forwards_explicit_key(self, monkeypatch):
        client, captured = _make_client(monkeypatch)
        await client.record_tool_event(
            "tool-123", {"event_type": "usage"},
            idempotency_key="record-explicit-key",
        )

        assert captured[0]["Idempotency-Key"] == "record-explicit-key"


class TestSubmitAiTransactionIdempotency:

    @pytest.mark.asyncio
    async def test_auto_generates_uuid4(self, monkeypatch):
        client, captured = _make_client(monkeypatch)
        await client.submit_ai_transaction({"model": "gpt-4", "provider": "OPENAI"})

        key = captured[0].get("Idempotency-Key")
        assert key is not None
        uuid.UUID(key, version=4)

    @pytest.mark.asyncio
    async def test_forwards_explicit_key(self, monkeypatch):
        client, captured = _make_client(monkeypatch)
        await client.submit_ai_transaction(
            {"model": "gpt-4", "provider": "OPENAI"},
            idempotency_key="submit-explicit-key",
        )

        assert captured[0]["Idempotency-Key"] == "submit-explicit-key"


class TestRetryPreservesKey:

    @pytest.mark.asyncio
    async def test_same_key_across_retries(self, monkeypatch):
        monkeypatch.setenv("REVENIUM_API_KEY", "hak_test_abcd1234")
        monkeypatch.setenv("REVENIUM_TEAM_ID", "test_team_id_456")
        monkeypatch.setenv("REVENIUM_BASE_URL", "https://example.invalid")

        from src.revenium_mcp_server.client import ReveniumClient

        client = ReveniumClient()
        captured: list[dict[str, str]] = []
        call_count = 0

        async def flaky_request(method, url, params=None, json=None, headers=None):
            nonlocal call_count
            captured.append(dict(headers or {}))
            call_count += 1
            resp = MagicMock(spec=httpx.Response)
            resp.headers = {"content-type": "application/json"}
            if call_count == 1:
                resp.status_code = 503
                resp.content = b'{"error":"unavailable"}'
                resp.json = MagicMock(return_value={"error": "unavailable"})
                resp.is_success = False
                resp.raise_for_status = MagicMock(
                    side_effect=httpx.HTTPStatusError(
                        "503", request=MagicMock(), response=resp,
                    )
                )
            else:
                resp.status_code = 200
                resp.content = b'{"ok":true}'
                resp.json = MagicMock(return_value={"ok": True})
                resp.is_success = True
            return resp

        monkeypatch.setattr(client.client, "request", flaky_request)

        await client.meter_tool_event({"toolId": "t1", "tokens": 1})

        assert len(captured) >= 2
        first_key = captured[0]["Idempotency-Key"]
        for headers in captured[1:]:
            assert headers["Idempotency-Key"] == first_key


class TestNonMeteringPostNoKey:

    @pytest.mark.asyncio
    async def test_generic_post_has_no_idempotency_key(self, monkeypatch):
        client, captured = _make_client(monkeypatch)
        await client.post("/profitstream/v2/api/some-other-endpoint", data={"x": 1})

        assert "Idempotency-Key" not in captured[0]
