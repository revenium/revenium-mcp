"""Unit tests for RFC 7807 problem-details handling + extra_headers plumbing in ReveniumClient."""
from __future__ import annotations

import pytest


def test_revenium_api_error_carries_optional_code():
    from src.revenium_mcp_server.client import ReveniumAPIError

    err = ReveniumAPIError(
        "boom",
        status_code=403,
        response_data={"code": "AI_RECOMMENDATIONS_DISABLED"},
        code="AI_RECOMMENDATIONS_DISABLED",
    )
    assert err.code == "AI_RECOMMENDATIONS_DISABLED"
    assert err.status_code == 403
    assert err.message == "boom"


def test_revenium_api_error_code_defaults_to_none_for_existing_callers():
    from src.revenium_mcp_server.client import ReveniumAPIError

    err = ReveniumAPIError("legacy boom", status_code=500)
    assert err.code is None
    assert err.message == "legacy boom"


@pytest.mark.asyncio
async def test_client_post_forwards_extra_headers_to_http_layer(monkeypatch):
    """`client.post(..., extra_headers={...})` must reach httpx.AsyncClient.request."""
    import httpx
    from unittest.mock import MagicMock

    from src.revenium_mcp_server.client import ReveniumClient

    monkeypatch.setenv("REVENIUM_API_KEY", "hak_test_abcd1234")
    monkeypatch.setenv("REVENIUM_TEAM_ID", "test_team_id_456")
    monkeypatch.setenv("REVENIUM_BASE_URL", "https://example.invalid")

    client = ReveniumClient()
    captured_headers: dict[str, str] = {}

    async def fake_request(method, url, params=None, json=None, headers=None):
        captured_headers.update(headers or {})
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.content = b'{"ok":true}'
        resp.json = MagicMock(return_value={"ok": True})
        resp.headers = {"content-type": "application/json"}
        resp.is_success = True
        return resp

    monkeypatch.setattr(client.client, "request", fake_request)

    await client.post(
        "/profitstream/v2/api/dummy",
        data={"k": "v"},
        extra_headers={"Idempotency-Key": "11111111-2222-3333-4444-555555555555"},
    )

    assert captured_headers.get("Idempotency-Key") == "11111111-2222-3333-4444-555555555555"


from unittest.mock import MagicMock


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status_code, code",
    [
        (403, "AI_RECOMMENDATIONS_DISABLED"),
        (404, "NOT_FOUND"),
        (503, "IDEMPOTENCY_BACKEND_UNAVAILABLE"),
    ],
)
async def test_problem_json_response_raises_api_error_with_code(monkeypatch, status_code, code):
    from src.revenium_mcp_server.client import ReveniumAPIError, ReveniumClient

    monkeypatch.setenv("REVENIUM_API_KEY", "hak_test_abcd1234")
    monkeypatch.setenv("REVENIUM_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("REVENIUM_TEAM_ID", "team_1")

    client = ReveniumClient()
    problem_body = {
        "type": "https://example.invalid/probs/x",
        "title": "AI insights problem",
        "status": status_code,
        "detail": "Detailed reason.",
        "code": code,
    }

    async def fake_request(method, url, params=None, json=None, headers=None):
        resp = MagicMock()
        resp.status_code = status_code
        resp.content = json_lib.dumps(problem_body).encode()  # use stdlib name to avoid kwarg shadow
        resp.text = json_lib.dumps(problem_body)
        resp.reason_phrase = "Test"
        resp.headers = {"content-type": "application/problem+json; charset=utf-8"}
        resp.is_success = False
        resp.json = MagicMock(return_value=problem_body)
        return resp

    import json as json_lib
    monkeypatch.setattr(client.client, "request", fake_request)

    with pytest.raises(ReveniumAPIError) as ei:
        await client.get("/api/v2/insights/runs/abc", use_retry=False)

    assert ei.value.code == code
    assert ei.value.status_code == status_code
    assert "Detailed reason" in str(ei.value.message)


@pytest.mark.asyncio
async def test_problem_json_without_code_field_yields_none_code(monkeypatch):
    import json as json_lib
    from src.revenium_mcp_server.client import ReveniumAPIError, ReveniumClient

    monkeypatch.setenv("REVENIUM_API_KEY", "hak_test_abcd1234")
    monkeypatch.setenv("REVENIUM_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("REVENIUM_TEAM_ID", "team_1")

    client = ReveniumClient()
    problem_body = {"title": "Bad", "status": 400, "detail": "Something broke."}

    async def fake_request(method, url, params=None, json=None, headers=None):
        resp = MagicMock()
        resp.status_code = 400
        resp.content = json_lib.dumps(problem_body).encode()
        resp.text = json_lib.dumps(problem_body)
        resp.reason_phrase = "Bad Request"
        resp.headers = {"content-type": "application/problem+json"}
        resp.is_success = False
        resp.json = MagicMock(return_value=problem_body)
        return resp

    monkeypatch.setattr(client.client, "request", fake_request)

    with pytest.raises(ReveniumAPIError) as ei:
        await client.get("/api/v2/insights/runs/abc", use_retry=False)

    assert ei.value.code is None
    assert "Something broke" in str(ei.value.message)


@pytest.mark.asyncio
async def test_legacy_envelope_unaffected_by_problem_json_branch(monkeypatch):
    """A non-problem+json 4xx must still flow through the legacy error-text logic."""
    import json as json_lib
    from src.revenium_mcp_server.client import ReveniumAPIError, ReveniumClient

    monkeypatch.setenv("REVENIUM_API_KEY", "hak_test_abcd1234")
    monkeypatch.setenv("REVENIUM_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("REVENIUM_TEAM_ID", "team_1")

    client = ReveniumClient()
    body = {"error": "legacy error message"}

    async def fake_request(method, url, params=None, json=None, headers=None):
        resp = MagicMock()
        resp.status_code = 500
        resp.content = json_lib.dumps(body).encode()
        resp.text = json_lib.dumps(body)
        resp.reason_phrase = "Server Error"
        resp.headers = {"content-type": "application/json"}
        resp.is_success = False
        resp.json = MagicMock(return_value=body)
        return resp

    monkeypatch.setattr(client.client, "request", fake_request)

    with pytest.raises(ReveniumAPIError) as ei:
        await client.get("/profitstream/v2/api/anything", use_retry=False)

    assert ei.value.code is None
    assert ei.value.status_code == 500


def test_new_idempotency_key_returns_uuid4_string():
    import uuid
    from src.revenium_mcp_server.client import _new_idempotency_key

    key = _new_idempotency_key()
    parsed = uuid.UUID(key)
    assert parsed.version == 4
    assert str(parsed) == key


def test_new_idempotency_key_returns_distinct_values():
    from src.revenium_mcp_server.client import _new_idempotency_key

    a = _new_idempotency_key()
    b = _new_idempotency_key()
    assert a != b


@pytest.mark.asyncio
async def test_list_investigators_hits_canonical_path(monkeypatch):
    from src.revenium_mcp_server.client import ReveniumClient

    monkeypatch.setenv("REVENIUM_API_KEY", "hak_test_abcd1234")
    monkeypatch.setenv("REVENIUM_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("REVENIUM_TEAM_ID", "team_1")

    client = ReveniumClient()
    captured_url = []

    async def fake_request(method, url, params=None, json=None, headers=None):
        captured_url.append(str(url))
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b'[{"id":"detector_a","displayName":"A","category":"waste","version":"1.0"}]'
        resp.json = MagicMock(return_value=[
            {"id": "detector_a", "displayName": "A", "category": "waste", "version": "1.0"}
        ])
        resp.is_success = True
        resp.headers = {"content-type": "application/json"}
        return resp

    monkeypatch.setattr(client.client, "request", fake_request)

    result = await client.list_investigators()

    assert isinstance(result, list)
    assert result[0]["id"] == "detector_a"
    assert "/api/v2/insights/investigators" in captured_url[0]
    assert "/recommendations" not in captured_url[0]


@pytest.mark.asyncio
async def test_get_recommendation_run_default_no_slim(monkeypatch):
    from src.revenium_mcp_server.client import ReveniumClient

    monkeypatch.setenv("REVENIUM_API_KEY", "hak_test_abcd1234")
    monkeypatch.setenv("REVENIUM_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("REVENIUM_TEAM_ID", "team_1")

    client = ReveniumClient()
    captured = {}

    async def fake_request(method, url, params=None, json=None, headers=None):
        captured["url"] = str(url)
        captured["params"] = params
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b'{"id":"r1","status":"completed"}'
        resp.json = MagicMock(return_value={"id": "r1", "status": "completed"})
        resp.is_success = True
        resp.headers = {"content-type": "application/json"}
        return resp

    monkeypatch.setattr(client.client, "request", fake_request)

    await client.get_recommendation_run("r1")

    assert "/api/v2/insights/runs/r1" in captured["url"]
    assert captured["params"] == {} or captured["params"] is None or "slim" not in (captured["params"] or {})


@pytest.mark.asyncio
async def test_get_recommendation_run_with_slim_true(monkeypatch):
    from src.revenium_mcp_server.client import ReveniumClient

    monkeypatch.setenv("REVENIUM_API_KEY", "hak_test_abcd1234")
    monkeypatch.setenv("REVENIUM_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("REVENIUM_TEAM_ID", "team_1")

    client = ReveniumClient()
    captured = {}

    async def fake_request(method, url, params=None, json=None, headers=None):
        captured["params"] = params
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b'{"id":"r1"}'
        resp.json = MagicMock(return_value={"id": "r1"})
        resp.is_success = True
        resp.headers = {"content-type": "application/json"}
        return resp

    monkeypatch.setattr(client.client, "request", fake_request)

    await client.get_recommendation_run("r1", slim=True)


@pytest.mark.asyncio
async def test_list_recommendation_runs_query_params(monkeypatch):
    from src.revenium_mcp_server.client import ReveniumClient

    monkeypatch.setenv("REVENIUM_API_KEY", "hak_test_abcd1234")
    monkeypatch.setenv("REVENIUM_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("REVENIUM_TEAM_ID", "team_1")

    client = ReveniumClient()
    captured = {}

    async def fake_request(method, url, params=None, json=None, headers=None):
        captured["url"] = str(url)
        captured["params"] = params
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b'{"data":[],"next_cursor":null}'
        resp.json = MagicMock(return_value={"data": [], "next_cursor": None})
        resp.is_success = True
        resp.headers = {"content-type": "application/json"}
        return resp

    monkeypatch.setattr(client.client, "request", fake_request)

    await client.list_recommendation_runs(
        limit=25,
        cursor="opaque",
        status="completed",
        triggered_by="api",
    )

    assert "/api/v2/insights/runs" in captured["url"]
    p = captured["params"]
    assert p["limit"] == 25
    assert p["cursor"] == "opaque"
    assert p["status"] == "completed"
    assert p["triggered_by"] == "api"


@pytest.mark.asyncio
async def test_list_recommendation_feedback_hits_nested_path(monkeypatch):
    from src.revenium_mcp_server.client import ReveniumClient

    monkeypatch.setenv("REVENIUM_API_KEY", "hak_test_abcd1234")
    monkeypatch.setenv("REVENIUM_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("REVENIUM_TEAM_ID", "team_1")

    client = ReveniumClient()
    captured = {}

    async def fake_request(method, url, params=None, json=None, headers=None):
        captured["url"] = str(url)
        captured["params"] = params
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b'{"data":[],"next_cursor":null}'
        resp.json = MagicMock(return_value={"data": [], "next_cursor": None})
        resp.is_success = True
        resp.headers = {"content-type": "application/json"}
        return resp

    monkeypatch.setattr(client.client, "request", fake_request)

    await client.list_recommendation_feedback("r1", limit=50, cursor="c2")

    assert "/api/v2/insights/runs/r1/feedback" in captured["url"]
    assert captured["params"] == {"limit": 50, "cursor": "c2"}


@pytest.mark.asyncio
async def test_list_recommendation_feedback_wraps_bare_array_wire_shape(monkeypatch):
    """The live endpoint answers with a BARE JSON ARRAY, not the documented
    {"data": [...], "next_cursor": ...} envelope. The client owns the wire, so it
    normalizes here and the documented return contract stays true for callers."""
    from src.revenium_mcp_server.client import ReveniumClient

    monkeypatch.setenv("REVENIUM_API_KEY", "hak_test_abcd1234")
    monkeypatch.setenv("REVENIUM_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("REVENIUM_TEAM_ID", "team_1")

    client = ReveniumClient()
    wire = [{"id": "f1", "action": "implemented"}, {"id": "f2", "action": "dismissed"}]

    async def fake_get(endpoint, **kwargs):
        return wire

    monkeypatch.setattr(client, "get", fake_get)

    result = await client.list_recommendation_feedback("r1")

    assert isinstance(result, dict), f"expected an envelope dict, got {type(result).__name__}"
    assert result["data"] == wire
    assert result["next_cursor"] is None


@pytest.mark.asyncio
async def test_list_recommendation_feedback_wraps_empty_bare_array(monkeypatch):
    """The common live answer is a bare `[]`; it must normalize to an empty
    envelope rather than reach the caller as a list."""
    from src.revenium_mcp_server.client import ReveniumClient

    monkeypatch.setenv("REVENIUM_API_KEY", "hak_test_abcd1234")
    monkeypatch.setenv("REVENIUM_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("REVENIUM_TEAM_ID", "team_1")

    client = ReveniumClient()

    async def fake_get(endpoint, **kwargs):
        return []

    monkeypatch.setattr(client, "get", fake_get)

    result = await client.list_recommendation_feedback("r1")

    assert isinstance(result, dict), f"expected an envelope dict, got {type(result).__name__}"
    assert result == {"data": [], "next_cursor": None}


@pytest.mark.asyncio
async def test_list_recommendation_feedback_passes_dict_envelope_through(monkeypatch):
    """If the backend ever adopts the documented envelope, normalization must be a
    no-op — cursor pagination keeps working unchanged."""
    from src.revenium_mcp_server.client import ReveniumClient

    monkeypatch.setenv("REVENIUM_API_KEY", "hak_test_abcd1234")
    monkeypatch.setenv("REVENIUM_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("REVENIUM_TEAM_ID", "team_1")

    client = ReveniumClient()
    envelope = {"data": [{"id": "f1"}], "next_cursor": "c2"}

    async def fake_get(endpoint, **kwargs):
        return envelope

    monkeypatch.setattr(client, "get", fake_get)

    result = await client.list_recommendation_feedback("r1")

    assert result == envelope
    assert result["next_cursor"] == "c2"


@pytest.mark.asyncio
async def test_list_recommendation_feedback_raises_on_envelope_without_list_data(
    monkeypatch,
):
    """A dict envelope whose data field is missing or not a list is upstream
    schema breakage too — passing it through would let the handler read
    page.get("data", []) as an empty page and report zero feedback for an
    existing run."""
    import pytest as _pytest

    from src.revenium_mcp_server.client import ReveniumAPIError, ReveniumClient

    monkeypatch.setenv("REVENIUM_API_KEY", "hak_test_abcd1234")
    monkeypatch.setenv("REVENIUM_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("REVENIUM_TEAM_ID", "team_1")

    client = ReveniumClient()

    for bad in ({"error": "oops"}, {"data": None}, {"data": "not-a-list"}):
        async def fake_get(endpoint, **kwargs):
            return bad

        monkeypatch.setattr(client, "get", fake_get)
        with _pytest.raises(ReveniumAPIError) as exc:
            await client.list_recommendation_feedback("r1")
        assert "list_recommendation_feedback" in str(exc.value)


@pytest.mark.asyncio
async def test_list_recommendation_feedback_raises_on_unknown_shape(
    monkeypatch,
):
    """Any third shape (string, number, null) raises a structured API error —
    degrading to an empty envelope would render a confident "0 feedback items"
    success for what is actually upstream schema breakage."""
    import pytest as _pytest

    from src.revenium_mcp_server.client import ReveniumAPIError, ReveniumClient

    monkeypatch.setenv("REVENIUM_API_KEY", "hak_test_abcd1234")
    monkeypatch.setenv("REVENIUM_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("REVENIUM_TEAM_ID", "team_1")

    client = ReveniumClient()

    async def fake_get(endpoint, **kwargs):
        return "unexpected"

    monkeypatch.setattr(client, "get", fake_get)

    with _pytest.raises(ReveniumAPIError) as exc:
        await client.list_recommendation_feedback("r1")

    assert "list_recommendation_feedback" in str(exc.value)
    assert "unexpected" in str(exc.value).lower() or "shape" in str(exc.value).lower()


import uuid as _uuid_test


@pytest.mark.asyncio
async def test_trigger_recommendation_run_posts_body_and_idempotency_key(monkeypatch):
    from src.revenium_mcp_server.client import ReveniumClient

    monkeypatch.setenv("REVENIUM_API_KEY", "hak_test_abcd1234")
    monkeypatch.setenv("REVENIUM_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("REVENIUM_TEAM_ID", "team_1")

    client = ReveniumClient()
    captured = {}

    async def fake_request(method, url, params=None, json=None, headers=None):
        captured["method"] = method
        captured["url"] = str(url)
        captured["body"] = json
        captured["headers"] = headers or {}
        resp = MagicMock()
        resp.status_code = 202
        resp.content = b'{"runId":"r1","status":"running"}'
        resp.json = MagicMock(return_value={"runId": "r1", "status": "running"})
        resp.is_success = True
        resp.headers = {"content-type": "application/json"}
        return resp

    monkeypatch.setattr(client.client, "request", fake_request)

    result = await client.trigger_recommendation_run(
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-01-31T23:59:59Z",
        filter_agent=["agent_a"],
        exclude_investigator_ids=["x"],
    )

    assert captured["method"] == "POST"
    assert "/api/v2/insights/runs" in captured["url"]
    assert captured["body"]["periodStart"] == "2026-01-01T00:00:00Z"
    assert captured["body"]["periodEnd"] == "2026-01-31T23:59:59Z"
    assert captured["body"]["filterAgent"] == ["agent_a"]
    assert captured["body"]["excludeInvestigatorIds"] == ["x"]
    assert captured["body"]["filterIncludeCodingAssistants"] is True
    assert captured["body"]["filterIncludeCodingAssistantsForCostDetectors"] is False
    key = captured["headers"].get("Idempotency-Key")
    parsed = _uuid_test.UUID(key)
    assert parsed.version == 4
    assert result["runId"] == "r1"


@pytest.mark.asyncio
async def test_trigger_recommendation_run_two_calls_distinct_keys(monkeypatch):
    from src.revenium_mcp_server.client import ReveniumClient

    monkeypatch.setenv("REVENIUM_API_KEY", "hak_test_abcd1234")
    monkeypatch.setenv("REVENIUM_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("REVENIUM_TEAM_ID", "team_1")

    client = ReveniumClient()
    seen_keys: list[str] = []

    async def fake_request(method, url, params=None, json=None, headers=None):
        seen_keys.append((headers or {}).get("Idempotency-Key", ""))
        resp = MagicMock()
        resp.status_code = 202
        resp.content = b'{"runId":"x","status":"running"}'
        resp.json = MagicMock(return_value={"runId": "x", "status": "running"})
        resp.is_success = True
        resp.headers = {"content-type": "application/json"}
        return resp

    monkeypatch.setattr(client.client, "request", fake_request)

    await client.trigger_recommendation_run(period_start="2026-01-01T00:00:00Z", period_end="2026-01-02T00:00:00Z")
    await client.trigger_recommendation_run(period_start="2026-01-01T00:00:00Z", period_end="2026-01-02T00:00:00Z")

    assert len(seen_keys) == 2
    assert seen_keys[0] != seen_keys[1]


@pytest.mark.asyncio
async def test_submit_recommendation_feedback_uppercases_currency_and_carries_key(monkeypatch):
    from src.revenium_mcp_server.client import ReveniumClient

    monkeypatch.setenv("REVENIUM_API_KEY", "hak_test_abcd1234")
    monkeypatch.setenv("REVENIUM_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("REVENIUM_TEAM_ID", "team_1")

    client = ReveniumClient()
    captured = {}

    async def fake_request(method, url, params=None, json=None, headers=None):
        captured["method"] = method
        captured["url"] = str(url)
        captured["body"] = json
        captured["headers"] = headers or {}
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b'{"id":"f1"}'
        resp.json = MagicMock(return_value={"id": "f1"})
        resp.is_success = True
        resp.headers = {"content-type": "application/json"}
        return resp

    monkeypatch.setattr(client.client, "request", fake_request)

    await client.submit_recommendation_feedback(
        run_id="r1",
        recommendation_id="rec1",
        action="implemented",
        realized_savings=42.5,
        realized_savings_currency="usd",
    )

    assert captured["method"] == "POST"
    assert "/api/v2/insights/feedback" in captured["url"]
    assert captured["body"]["realizedSavingsCurrency"] == "USD"
    assert captured["body"]["action"] == "implemented"
    assert _uuid_test.UUID(captured["headers"].get("Idempotency-Key")).version == 4


@pytest.mark.asyncio
async def test_submit_recommendation_feedback_omits_realized_savings_measured_at_when_absent(monkeypatch):
    from src.revenium_mcp_server.client import ReveniumClient

    monkeypatch.setenv("REVENIUM_API_KEY", "hak_test_abcd1234")
    monkeypatch.setenv("REVENIUM_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("REVENIUM_TEAM_ID", "team_1")

    client = ReveniumClient()
    captured = {}

    async def fake_request(method, url, params=None, json=None, headers=None):
        captured["method"] = method
        captured["url"] = str(url)
        captured["body"] = json
        captured["headers"] = headers or {}
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b'{"id":"f1"}'
        resp.json = MagicMock(return_value={"id": "f1"})
        resp.is_success = True
        resp.headers = {"content-type": "application/json"}
        return resp

    monkeypatch.setattr(client.client, "request", fake_request)

    await client.submit_recommendation_feedback(
        run_id="r1",
        recommendation_id="rec1",
        action="dismissed",
    )

    assert "realizedSavingsMeasuredAt" not in captured["body"]


@pytest.mark.asyncio
async def test_submit_recommendation_feedback_includes_realized_savings_measured_at_when_present(monkeypatch):
    from src.revenium_mcp_server.client import ReveniumClient

    monkeypatch.setenv("REVENIUM_API_KEY", "hak_test_abcd1234")
    monkeypatch.setenv("REVENIUM_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("REVENIUM_TEAM_ID", "team_1")

    client = ReveniumClient()
    captured = {}

    async def fake_request(method, url, params=None, json=None, headers=None):
        captured["method"] = method
        captured["url"] = str(url)
        captured["body"] = json
        captured["headers"] = headers or {}
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b'{"id":"f1"}'
        resp.json = MagicMock(return_value={"id": "f1"})
        resp.is_success = True
        resp.headers = {"content-type": "application/json"}
        return resp

    monkeypatch.setattr(client.client, "request", fake_request)

    await client.submit_recommendation_feedback(
        run_id="r1",
        recommendation_id="rec1",
        action="implemented",
        realized_savings_measured_at="2026-05-01T00:00:00Z",
    )

    assert captured["body"]["realizedSavingsMeasuredAt"] == "2026-05-01T00:00:00Z"
