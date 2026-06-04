"""Shared fixtures for integration tests.

Re-exporting a fixture here makes it available to every test module in this
directory via pytest's fixture discovery, so individual test modules don't
import the fixture name (which would trip Ruff's F811 against the parameter).
"""
from tests.integration._http_api_key_server import mcp_http_server  # noqa: F401
from tests.integration._clerk_fixtures import (  # noqa: F401
    fake_clerk,
    mint_jwt,
    test_keypair,
)
