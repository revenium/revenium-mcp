"""The pinned fastmcp keeps rejected arguments out of logs and refuses forged ID-JAG tokens (BACK-4637).

fastmcp before 4.0.4 logged the rejected value of every argument that failed
binding, and its OAuth proxy accepted a self-signed identity-assertion token
even with identity assertion unconfigured. Both live in the framework, so these
tests exercise the pinned framework through this server's own wiring.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastmcp import Client, FastMCP
from fastmcp.server.auth.oidc_proxy import OIDCConfiguration
from key_value.aio.stores.memory import MemoryStore
from loguru import logger

from src.revenium_mcp_server.auth.oidc_logging import AuthLoggingOIDCProxy
from src.revenium_mcp_server.log_context import tenant_log_patcher
from src.revenium_mcp_server.logging_config import LoggingConfig
from src.revenium_mcp_server.middleware.framework_leak_guard import (
    FrameworkLeakGuardMiddleware,
)
from src.revenium_mcp_server.tool_configuration.config import ToolConfig
from src.revenium_mcp_server.tool_configuration.registry import ToolConfigurationRegistry

CANARY = "FS-CANARY-SECRET-4637"
TOOL = "manage_credentials"
INVALID_ARGUMENTS_WARNING = "Invalid arguments for tool"


class _EveryRecord(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.lines: List[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(f"{record.getMessage()} {record.__dict__!r}")


@pytest.fixture
def every_log_sink(tmp_path: Path, capfd):
    LoggingConfig(
        log_level="DEBUG",
        log_file=str(tmp_path / "server.jsonl"),
        crash_log_directory=tmp_path,
    )
    loguru_lines: List[str] = []
    logger.add(
        lambda message: loguru_lines.append(
            json.dumps(
                {"message": message.record["message"], "extra": message.record["extra"]},
                default=repr,
            )
        ),
        level="DEBUG",
    )
    stdlib = _EveryRecord()
    watched = [logging.getLogger(), logging.getLogger("fastmcp")]
    for each in watched:
        each.addHandler(stdlib)

    def everything_logged() -> str:
        out, err = capfd.readouterr()
        files = [path.read_text() for path in tmp_path.glob("server.*") if path.is_file()]
        return "\n".join(loguru_lines + stdlib.lines + files + [out, err])

    yield everything_logged

    for each in watched:
        each.removeHandler(stdlib)
    logger.remove()
    logger.configure(patcher=tenant_log_patcher)


async def _credentials_server() -> FastMCP:
    mcp = FastMCP("back-4637")
    mcp.add_middleware(FrameworkLeakGuardMiddleware())
    registry = ToolConfigurationRegistry(tool_config=ToolConfig.create_for_testing(profile="business"))
    await registry._register_manage_subscriber_credentials(mcp)
    return mcp


async def _call_rejected(arguments: Dict[str, Any]) -> str:
    mcp = await _credentials_server()
    async with Client(mcp) as client:
        result = await client.call_tool(TOOL, arguments, raise_on_error=False)
    assert result.is_error is True
    return result.content[0].text


@pytest.mark.parametrize(
    "arguments",
    [
        pytest.param({"action": "get_capabilities", "notAnArgumentOfThisTool": CANARY}, id="unknown_argument"),
        pytest.param({"action": "create", "credential_data": [CANARY]}, id="failed_type_validation"),
    ],
)
async def test_a_rejected_argument_value_reaches_no_log_sink(every_log_sink, arguments):
    await _call_rejected(arguments)

    logged = every_log_sink()
    assert INVALID_ARGUMENTS_WARNING in logged
    assert CANARY not in logged


ISSUER = "https://clerk.example.invalid"
OFFLINE_DISCOVERY = OIDCConfiguration.model_validate(
    {
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/oauth/authorize",
        "token_endpoint": f"{ISSUER}/oauth/token",
        "jwks_uri": f"{ISSUER}/.well-known/jwks.json",
        "response_types_supported": ["code"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
    }
)


def _clerk_mode_proxy() -> AuthLoggingOIDCProxy:
    with patch.object(
        AuthLoggingOIDCProxy, "get_oidc_configuration", return_value=OFFLINE_DISCOVERY
    ):
        proxy = AuthLoggingOIDCProxy(
            config_url=f"{ISSUER}/.well-known/openid-configuration",
            client_id="clerk-oauth-client",
            client_secret="clerk-oauth-client-secret",
            base_url="https://mcp.example.invalid",
            required_scopes=["openid", "profile", "email", "private_metadata"],
            verify_id_token=True,
            algorithm="RS256",
            client_storage=MemoryStore(),
        )
    proxy.set_mcp_path("/mcp")
    return proxy


async def test_a_forged_identity_assertion_token_is_refused_without_identity_assertion():
    proxy = _clerk_mode_proxy()
    forged = proxy.jwt_issuer.issue_access_token(
        client_id="anything",
        scopes=["openid"],
        jti="forged-id-jag-jti-4637",
        subject="user_forged_123",
        extra_claims={"fastmcp_grant": "id_jag", "email": "victim@example.com"},
    )

    assert proxy._identity_assertion is None
    assert await proxy.load_access_token(forged) is None
    assert await proxy.verify_token(forged) is None
