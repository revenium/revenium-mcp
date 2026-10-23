"""get_cost_summary answers with the parts that came back (BACK-4690).

The five parts were read one after another inside one try, so a slow model
report threw away the provider figures already read and the answer advised
checking the period. Only the HTTP client is stubbed here, by path, so the
analyzer, the formatter and the error handler run together.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.revenium_mcp_server.analytics import simple_cost_analyzer
from src.revenium_mcp_server.analytics.formatters.base_formatter import mask_api_key_name
from src.revenium_mcp_server.analytics.simple_analytics_engine import (
    SimpleAnalyticsEngine,
)
from src.revenium_mcp_server.auth import AuthenticationError
from src.revenium_mcp_server.client import ReveniumAPIError, ReveniumClient
from src.revenium_mcp_server.common.error_handling import ToolError
from src.revenium_mcp_server.common.team_scope_error import TeamScopeForbiddenError
from src.revenium_mcp_server.endpoint_registry import get_endpoint_path

_PART_ROWS = {
    "cost_metric_by_provider_over_time": "OpenAI",
    "cost_metric_by_model": "gpt-4o",
    "cost_metric_by_organization": "Acme Corp",
    "cost_metrics_by_subscriber_credential": "key-prod",
    "cost_metrics_by_agents_over_time": "support-bot",
}


def _bucket(name, cost):
    return [{"groups": [{"groupName": name, "metrics": [{"metricResult": cost}]}]}]


def _timeout():
    return ReveniumAPIError("Endpoint request timed out", status_code=504)


def _engine(failing_keys, error=_timeout, team_id="team-abc", slow_keys=()):
    paths = {get_endpoint_path(key): key for key in _PART_ROWS}

    async def get(path, *args, **kwargs):
        key = paths[path]
        if key in slow_keys:
            await asyncio.Event().wait()
        if key in failing_keys:
            raise error()
        return _bucket(_PART_ROWS[key], 100.0)

    client = MagicMock()
    client.team_id = team_id
    client.get = AsyncMock(side_effect=get)
    return SimpleAnalyticsEngine(client)


@pytest.fixture(autouse=True)
def flag_unset(monkeypatch):
    monkeypatch.delenv("REVENIUM_USE_NEW_ANALYTICS_API", raising=False)


@pytest.mark.asyncio
async def test_failed_model_part_is_named_and_the_other_four_are_shown():
    engine = _engine({"cost_metric_by_model"})

    text = await engine.get_cost_summary(period="TWELVE_MONTHS")

    assert "Models" in text and "get_model_costs" in text
    assert "HTTP 504: Endpoint request timed out" in text
    for shown in ("OpenAI", "Acme Corp", mask_api_key_name("key-prod"), "support-bot"):
        assert shown in text
    assert "gpt-4o" not in text
    assert "**Total Cost**: $100.00" in text
    assert "time period is valid" not in text


@pytest.mark.asyncio
async def test_failed_provider_part_shows_the_total_as_not_read():
    engine = _engine({"cost_metric_by_provider_over_time"})

    text = await engine.get_cost_summary(period="TWELVE_MONTHS")

    assert "**Total Cost**: not read" in text
    assert "**Total Cost**: $0.00" not in text
    assert "get_provider_costs" in text
    assert "gpt-4o" in text


async def _failure(call):
    """The text of the error a summary that read nothing raises (BACK-4699)."""
    with pytest.raises(ToolError) as failure:
        await call
    return failure.value.message


@pytest.mark.asyncio
async def test_cost_summary_timeout_is_not_answered_with_period_advice():
    engine = _engine(set(_PART_ROWS))

    text = await _failure(engine.get_cost_summary(period="TWELVE_MONTHS"))

    assert "HTTP 504: Endpoint request timed out" in text
    assert "time period is valid" not in text
    assert "Verify that aggregation is valid" not in text
    for action in (
        "get_provider_costs",
        "get_model_costs",
        "get_customer_costs",
        "get_api_key_costs",
        "get_agent_costs",
    ):
        assert action in text



@pytest.mark.parametrize(
    "error, reason",
    [
        (
            lambda: ReveniumAPIError("API key is invalid or expired", status_code=401),
            "HTTP 401: API key is invalid or expired",
        ),
        (lambda: TeamScopeForbiddenError("team-abc"), "cannot read team team-abc"),
    ],
    ids=["http_401", "team_scope_forbidden"],
)
@pytest.mark.asyncio
async def test_refused_credential_fails_the_summary_instead_of_one_part(error, reason):
    engine = _engine({"cost_metric_by_model"}, error=error)

    text = await _failure(engine.get_cost_summary(period="TWELVE_MONTHS"))

    assert reason in text
    assert "Parts Not Read" not in text
    assert "Total Cost" not in text
    assert "Try a shorter period" not in text
    assert "API key or signed-in session" in text


@pytest.mark.asyncio
async def test_missing_auth_configuration_escapes_the_summary():
    engine = _engine(
        {"cost_metric_by_model"}, error=lambda: AuthenticationError("REVENIUM_API_KEY is not set")
    )

    with pytest.raises(AuthenticationError):
        await engine.get_cost_summary(period="TWELVE_MONTHS")


def _misconfigured_app_base_url():
    return ToolError("REVENIUM_APP_BASE_URL is misconfigured: not an HTTPS URL.")


@pytest.mark.parametrize(
    "engine, reason",
    [
        (lambda: _engine(set(_PART_ROWS), error=_misconfigured_app_base_url), "REVENIUM_APP_BASE_URL"),
        (lambda: _engine(set(), team_id=None), "Team ID not available"),
    ],
    ids=["misconfigured_app_base_url", "missing_team_id"],
)
@pytest.mark.asyncio
async def test_server_configuration_failure_names_the_server_setting(engine, reason, monkeypatch):
    monkeypatch.delenv("REVENIUM_TEAM_ID", raising=False)

    text = await _failure(engine().get_cost_summary(period="TWELVE_MONTHS"))

    assert reason in text
    assert "server's configuration" in text
    assert "Try a shorter period" not in text
    assert "Parts Not Read" not in text


_ALL_ACTIONS = (
    "get_provider_costs",
    "get_model_costs",
    "get_customer_costs",
    "get_api_key_costs",
    "get_agent_costs",
)


@pytest.fixture
def short_part_limit(monkeypatch):
    """A summary part gets a twentieth of a second, so a stuck part is cut quickly."""
    monkeypatch.setattr(
        simple_cost_analyzer, "COST_SUMMARY_PART_TIME_LIMIT_SECONDS", 0.05
    )


@pytest.mark.asyncio
async def test_a_part_slower_than_its_time_limit_is_named_and_the_others_are_shown(
    short_part_limit,
):
    """A stuck part no longer holds the whole summary (BACK-4809)."""
    engine = _engine(set(), slow_keys={"cost_metric_by_model"})

    text = await asyncio.wait_for(engine.get_cost_summary(period="TWELVE_MONTHS"), 5)

    assert "**Models**: not read within 0.05 seconds" in text
    assert "get_model_costs" in text
    for shown in ("OpenAI", "Acme Corp", mask_api_key_name("key-prod"), "support-bot"):
        assert shown in text
    assert "**Total Cost**: $100.00" in text


def _client_answering_504_then_hanging():
    """A client whose own retry loop meets a 504 and then a read that never ends."""
    client = ReveniumClient.__new__(ReveniumClient)

    async def request(*args, **kwargs):
        if client._request.await_count == 1:
            raise _timeout()
        await asyncio.Event().wait()

    client._request = AsyncMock(side_effect=request)
    return client


@pytest.mark.asyncio
async def test_a_part_cut_at_its_time_limit_keeps_the_platforms_last_error(
    short_part_limit,
):
    """The 504 the platform gave before the retry stays in the reason (BACK-4809)."""
    retrying = _client_answering_504_then_hanging()
    engine = _engine(set())
    answer_rows = engine.client.get.side_effect

    async def get(path, *args, **kwargs):
        if path == get_endpoint_path("cost_metric_by_model"):
            return await retrying._request_with_retry("GET", path, max_retries=3)
        return await answer_rows(path, *args, **kwargs)

    engine.client.get.side_effect = get

    text = await asyncio.wait_for(engine.get_cost_summary(period="TWELVE_MONTHS"), 5)

    assert (
        "**Models**: not read within 0.05 seconds; the platform last answered "
        "HTTP 504: Endpoint request timed out" in text
    )
    assert "get_model_costs" in text
    assert "**Total Cost**: $100.00" in text


@pytest.mark.asyncio
async def test_every_part_slower_than_its_time_limit_is_named_in_the_refusal(
    short_part_limit,
):
    engine = _engine(set(), slow_keys=set(_PART_ROWS))

    text = await asyncio.wait_for(_failure(engine.get_cost_summary(period="TWELVE_MONTHS")), 5)

    assert text.count("not read within 0.05 seconds") == len(_ALL_ACTIONS)
    for action in _ALL_ACTIONS:
        assert action in text


@pytest.mark.asyncio
async def test_a_refused_credential_still_fails_the_summary_while_another_part_is_slow(
    short_part_limit,
):
    engine = _engine(
        {"cost_metric_by_model"},
        error=lambda: ReveniumAPIError("API key is invalid or expired", status_code=401),
        slow_keys={"cost_metric_by_organization"},
    )

    text = await asyncio.wait_for(_failure(engine.get_cost_summary(period="TWELVE_MONTHS")), 5)

    assert "HTTP 401: API key is invalid or expired" in text
    assert "Parts Not Read" not in text
    assert "not read within" not in text


@pytest.mark.asyncio
async def test_cancelling_the_summary_is_not_turned_into_a_part_reason():
    engine = _engine(set(), slow_keys=set(_PART_ROWS))
    task = asyncio.create_task(engine.get_cost_summary(period="TWELVE_MONTHS"))
    await asyncio.sleep(0.05)

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


def _paged_envelope(number, total_pages):
    """One page of a provider report holding one daily OpenAI bucket at $1."""
    return {
        "_embedded": {
            "items": [
                {
                    "startTimestamp": f"2026-01-01T00:00:00.000Z#{number}",
                    "groups": [{"groupName": "OpenAI", "metrics": [{"metricResult": 1.0}]}],
                }
            ]
        },
        "page": {"number": number, "size": 100, "totalPages": total_pages, "totalElements": total_pages},
    }


class _PagedSummaryClient:
    """The analytics route: the provider report spans ``provider_pages`` pages, every other report one."""

    def __init__(self, provider_pages):
        self.team_id = "team-abc"
        self.provider_pages = provider_pages
        self.provider_calls = 0

    async def get(self, path, params=None, **kwargs):
        number = (params or {}).get("page", 0)
        if path.endswith("/cost-by-provider"):
            self.provider_calls += 1
            return _paged_envelope(number, self.provider_pages)
        return _paged_envelope(number, 1)


@pytest.mark.asyncio
async def test_a_provider_part_stopped_at_the_page_cap_is_named_and_the_total_is_partial(
    monkeypatch,
):
    """A summary over a report longer than ENVELOPE_MAX_PAGES says so (BACK-4866)."""
    from src.revenium_mcp_server.analytics.envelope_reads import ENVELOPE_MAX_PAGES

    monkeypatch.setenv("REVENIUM_USE_NEW_ANALYTICS_API", "true")
    total_pages = ENVELOPE_MAX_PAGES + 5
    client = _PagedSummaryClient(provider_pages=total_pages)

    text = await SimpleAnalyticsEngine(client).get_cost_summary(period="TWELVE_MONTHS")

    assert client.provider_calls == ENVELOPE_MAX_PAGES
    assert (
        f"**Total Cost**: ${ENVELOPE_MAX_PAGES:.2f} (partial: the provider part read "
        f"{ENVELOPE_MAX_PAGES} of {total_pages} pages" in text
    )
    assert "## **Parts Read Incompletely**" in text
    assert f"- **Providers**: read {ENVELOPE_MAX_PAGES} of {total_pages} pages" in text
    assert "get_provider_costs" in text
    for complete in ("Models", "Customers", "API keys", "Agents"):
        assert f"- **{complete}**: read" not in text


@pytest.mark.asyncio
async def test_a_summary_read_in_full_carries_no_incomplete_note(monkeypatch):
    monkeypatch.setenv("REVENIUM_USE_NEW_ANALYTICS_API", "true")

    text = await SimpleAnalyticsEngine(_PagedSummaryClient(provider_pages=2)).get_cost_summary(
        period="TWELVE_MONTHS"
    )

    assert "**Total Cost**: $2.00\n" in text
    assert "Parts Read Incompletely" not in text
    assert "partial" not in text


@pytest.mark.asyncio
async def test_the_summary_carries_the_total_parts_unread_pages(monkeypatch):
    """The analyzer alone decides which part's unread pages make the total partial."""
    from src.revenium_mcp_server.analytics.envelope_reads import ENVELOPE_MAX_PAGES

    monkeypatch.setenv("REVENIUM_USE_NEW_ANALYTICS_API", "true")
    analyzer = simple_cost_analyzer.SimpleCostAnalyzer(
        _PagedSummaryClient(provider_pages=ENVELOPE_MAX_PAGES + 5)
    )

    summary = await analyzer.get_cost_summary("TWELVE_MONTHS", "TOTAL")

    assert summary["total_unread"] is not None
    assert summary["total_unread"] == summary["incomplete"][simple_cost_analyzer.TOTAL_PART.key]


def test_the_formatter_labels_the_total_partial_from_the_summarys_total_unread():
    from src.revenium_mcp_server.analytics.envelope_reads import UnreadPages
    from src.revenium_mcp_server.analytics.formatters.cost_summary_formatter import (
        CostSummaryFormatter,
    )

    unread = UnreadPages("any_report", pages_read=3, total_pages=7, total_elements=None)

    text = CostSummaryFormatter().format(
        {"total_cost": 3.0, "total_unread": unread}, {"period": "TWELVE_MONTHS"}
    )

    assert "**Total Cost**: $3.00 (partial: the provider part read 3 of 7 pages" in text


def _transport_timeout():
    """What the client raises when httpx gives up waiting: a plain error raised while handling it."""
    import httpx

    try:
        raise httpx.ReadTimeout("")
    except httpx.ReadTimeout:
        try:
            raise ReveniumAPIError("Request failed: no answer to GET within 30 seconds (ReadTimeout)")
        except ReveniumAPIError as error:
            return error


_SHORTER_PERIOD = (
    "The platform did not answer this report over TWELVE_MONTHS in time, so the same "
    "period is likely to run out again; read it with `get_model_costs` over a shorter "
    "period or start_date/end_date range."
)


@pytest.mark.parametrize(
    "error",
    [_timeout, lambda: ReveniumAPIError("Request Timeout", status_code=408), _transport_timeout],
    ids=["http_504", "http_408", "transport_timeout"],
)
@pytest.mark.asyncio
async def test_a_model_part_the_platform_did_not_answer_in_time_names_a_shorter_period(error):
    """A twelve-month model report that times out is not retried over the same period (BACK-4856)."""
    engine = _engine({"cost_metric_by_model"}, error=error)

    text = await engine.get_cost_summary(period="TWELVE_MONTHS")

    assert _SHORTER_PERIOD in text
    assert "Retry this part alone with `get_model_costs`" not in text
    assert "**Total Cost**: $100.00" in text


@pytest.mark.asyncio
async def test_a_part_cut_at_its_time_limit_names_a_shorter_period(short_part_limit):
    engine = _engine(set(), slow_keys={"cost_metric_by_model"})

    text = await asyncio.wait_for(engine.get_cost_summary(period="TWELVE_MONTHS"), 5)

    assert "**Models**: not read within 0.05 seconds. " + _SHORTER_PERIOD in text


@pytest.mark.asyncio
async def test_a_part_refused_for_another_reason_keeps_the_plain_retry():
    engine = _engine(
        {"cost_metric_by_model"},
        error=lambda: ReveniumAPIError("Internal Server Error", status_code=500),
    )

    text = await engine.get_cost_summary(period="TWELVE_MONTHS")

    assert "Retry this part alone with `get_model_costs`." in text
    assert "shorter period" not in text


@pytest.mark.asyncio
async def test_a_summary_no_part_of_which_answered_in_time_names_a_shorter_period():
    """The refusal keeps each part's out-of-time advice when nothing was read."""
    engine = _engine(set(_PART_ROWS))

    text = await _failure(engine.get_cost_summary(period="TWELVE_MONTHS"))

    assert _SHORTER_PERIOD in text
    assert text.count("over a shorter period or start_date/end_date range") == len(_ALL_ACTIONS)


@pytest.mark.asyncio
async def test_a_summary_no_part_of_which_was_read_for_another_reason_names_no_shorter_period():
    engine = _engine(
        set(_PART_ROWS),
        error=lambda: ReveniumAPIError("Internal Server Error", status_code=500),
    )

    text = await _failure(engine.get_cost_summary(period="TWELVE_MONTHS"))

    assert "HTTP 500: Internal Server Error" in text
    assert "over a shorter period or start_date/end_date range" not in text
