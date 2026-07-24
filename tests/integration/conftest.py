"""Shared fixtures for integration tests.

Re-exporting a fixture here makes it available to every test module in this
directory via pytest's fixture discovery, so individual test modules don't
import the fixture name (which would trip Ruff's F811 against the parameter).
"""
from tests.integration._http_api_key_server import (  # noqa: F401
    mcp_http_server,
    mcp_http_server_with_server_creds,
)
from tests.integration._clerk_fixtures import (  # noqa: F401
    fake_clerk,
    mint_jwt,
    test_keypair,
)
