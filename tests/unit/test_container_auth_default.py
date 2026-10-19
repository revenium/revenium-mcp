"""The shipped container artefacts must not choose a sign-in mode (BACK-4687).

An HTTP server with no AUTH_MODE refuses to start, so an operator has to pick
a mode on purpose. Setting AUTH_MODE in the example environment file, the
image or the compose service would choose one for them and reopen the server
to every caller.
"""

from pathlib import Path

import yaml
from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_env_example_does_not_set_auth_mode():
    values = dotenv_values(REPO_ROOT / ".env.example")
    assert "AUTH_MODE" not in values, (
        ".env.example sets AUTH_MODE, so `cp .env.example .env` plus "
        "`docker compose up` would start an HTTP server in that mode "
        "without the operator choosing it."
    )


def test_dockerfile_does_not_set_auth_mode():
    offending = [
        line
        for line in (REPO_ROOT / "Dockerfile").read_text().splitlines()
        if "AUTH_MODE" in line and not line.strip().startswith("#")
    ]
    assert offending == [], (
        "The Dockerfile sets AUTH_MODE, which makes the image's start-up "
        f"refusal dead: {offending}"
    )


def test_compose_service_does_not_set_auth_mode():
    compose = yaml.safe_load((REPO_ROOT / "compose.yaml").read_text())
    environment = compose["services"]["mcp-server"].get("environment") or {}
    if isinstance(environment, list):
        names = {entry.split("=", 1)[0] for entry in environment}
    else:
        names = set(environment)
    assert "AUTH_MODE" not in names, (
        "compose.yaml sets AUTH_MODE under environment:, which overrides "
        "the operator's .env choice."
    )
