"""Auth-failure surface consistency across MCP tools.

When REVENIUM_API_KEY is unset, every auth-enforcing MCP tool must surface
the failure as an exception that escapes standardized_tool_execution.
That is what makes FastMCP set the response envelope's `isError: true` flag,
which protocol-conformant clients branch on.

Pre-fix several tools (business_analytics_management, manage_sources,
manage_metering_elements, manage_subscriber_credentials, slack_management)
let the auth ValueError bubble through paths that were swallowed by the
dispatch layer's catch-all and converted into a TextContent body without
the isError flag. Clients that rely on the flag would treat the response
as success-with-unusual-content.

This test parametrizes the affected tools and asserts the call raises a
ToolError / ToolExecutionError so the envelope carries isError=true.
"""

import pytest

from src.revenium_mcp_server.auth import ConfigManager
from src.revenium_mcp_server.common.error_handling import (
    ToolError,
    ToolExecutionError,
)
from src.revenium_mcp_server.common.tool_execution import (
    standardized_tool_execution,
)
from src.revenium_mcp_server.tools_decomposed.business_analytics_management import (
    BusinessAnalyticsManagement,
)
from src.revenium_mcp_server.tools_decomposed.metering_elements_management import (
    MeteringElementsManagement,
)
from src.revenium_mcp_server.tools_decomposed.slack_management import SlackManagement
from src.revenium_mcp_server.tools_decomposed.source_management import (
    SourceManagement,
)
from src.revenium_mcp_server.tools_decomposed.subscriber_credentials_management import (
    SubscriberCredentialsManagement,
)


@pytest.fixture
def no_api_key(monkeypatch):
    """Strip REVENIUM_API_KEY/TEAM_ID from the environment and reset the
    ConfigManager singleton so the next get_config() call hits load_from_env
    without the env vars present.
    """
    monkeypatch.delenv("REVENIUM_API_KEY", raising=False)
    monkeypatch.delenv("REVENIUM_TEAM_ID", raising=False)
    monkeypatch.delenv("REVENIUM_API_TOKEN", raising=False)
    ConfigManager._instance = None
    ConfigManager._config = None
    yield
    ConfigManager._instance = None
    ConfigManager._config = None


AUTH_FAILURE_CASES = [
    pytest.param(
        "business_analytics_management",
        BusinessAnalyticsManagement,
        "get_provider_costs",
        {"period": "SEVEN_DAYS"},
        id="business_analytics_management",
    ),
    pytest.param(
        "business_analytics_management",
        BusinessAnalyticsManagement,
        "analyze_cost_anomalies",
        {"period": "SEVEN_DAYS"},
        id="business_analytics_management__analyze_cost_anomalies",
    ),
    pytest.param(
        "manage_sources",
        SourceManagement,
        "list",
        {},
        id="manage_sources",
    ),
    pytest.param(
        "manage_metering_elements",
        MeteringElementsManagement,
        "list",
        {},
        id="manage_metering_elements",
    ),
    pytest.param(
        "manage_subscriber_credentials",
        SubscriberCredentialsManagement,
        "list",
        {},
        id="manage_subscriber_credentials",
    ),
    pytest.param(
        "slack_management",
        SlackManagement,
        "list_configurations",
        {},
        id="slack_management",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name,tool_class,action,arguments", AUTH_FAILURE_CASES)
async def test_auth_failure_escapes_dispatch_so_envelope_carries_iserror(
    tool_name, tool_class, action, arguments, no_api_key
):
    """Auth failure must escape the dispatch layer as an exception (ToolError
    or ToolExecutionError) so FastMCP sets isError=true on the envelope.

    Pre-fix the auth ValueError was caught by the dispatch catch-all and
    returned as TextContent — protocol-conformant clients would see a
    success envelope with error text inside.
    """
    with pytest.raises((ToolError, ToolExecutionError)) as exc_info:
        await standardized_tool_execution(tool_name, action, arguments, tool_class)

    raised = exc_info.value
    msg = str(raised)
    assert "REVENIUM_API_KEY" in msg or "API key" in msg.lower() or "auth" in msg.lower(), (
        f"{tool_name}: expected the raised exception to mention the auth/API-key "
        f"failure root cause; got message: {msg!r}"
    )


class TestAuthEnvelopeIs401Equivalent:
    """BACK-1270 / item #9 — env-var-missing must surface as auth-shape error.

    The pre-fix flow let the raw infrastructure framing
    ("REVENIUM_API_KEY environment variable is required") reach the user.
    Phase-10c probes expect a 401-equivalent envelope shape; leaking the
    env-var name implies "no auth attempt was even made" which confuses
    callers about where the failure originated.
    """

    @pytest.mark.asyncio
    async def test_missing_api_key_returns_unauthorized_envelope(self, monkeypatch):
        from src.revenium_mcp_server.client import ReveniumClient
        from src.revenium_mcp_server.common.error_handling import (
            ErrorCodes,
            ToolError,
        )
        from tests.unit._helpers_no_framework_leak import assert_no_framework_leak

        # Blank the API key so auth.load_from_env raises AuthenticationError.
        monkeypatch.delenv("REVENIUM_API_KEY", raising=False)
        monkeypatch.delenv("REVENIUM_TEAM_ID", raising=False)
        monkeypatch.delenv("REVENIUM_API_TOKEN", raising=False)
        # Force fresh ConfigManager so the env-var check fires now. Use
        # monkeypatch so pytest reverts the singleton even if the test body
        # raises between setup and the implicit teardown.
        monkeypatch.setattr(ConfigManager, "_instance", None)
        monkeypatch.setattr(ConfigManager, "_config", None)

        client = ReveniumClient()

        with pytest.raises(ToolError) as exc:
            await client.get_jobs(page=0, size=20)

        # Envelope must look like an auth failure, not infrastructure framing.
        assert exc.value.error_code == ErrorCodes.UNAUTHORIZED
        assert (
            "unauthorized" in exc.value.message.lower()
            or "authentication" in exc.value.message.lower()
        )
        # Must not leak the literal "REVENIUM_API_KEY environment variable" string.
        assert "REVENIUM_API_KEY environment variable" not in exc.value.message
        # Suggestions must not name the env var either — Fix 2 of the BACK-1270
        # follow-up scrubbed the suggestion list, this lock makes the contract
        # machine-checked.
        assert "REVENIUM_API_KEY" not in str(exc.value.suggestions)
        assert_no_framework_leak(exc.value.message)
