"""Pin how the spec fetch authenticates and how it fails (BACK-3697).

The hypercurrent docs endpoint started refusing anonymous requests, and the
nightly drift job then failed for days with a message that never named the
missing credential. These tests pin the credential each source sends and the
failures that must stay loud: a missing variable and a refused credential both
exit 2 with the variable and the status named, and a redirect is refused so
the key never travels to another host. Requests go through the script's real
opener with only the HTTPS transport stubbed; no test touches the network.
"""

from __future__ import annotations

import http.client
import importlib.util
import io
import json
import sys
import urllib.request
import urllib.response
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "fetch_openapi_specs.py"
if not SCRIPT.exists():
    pytest.skip(
        "scripts/fetch_openapi_specs.py is an internal-only asset that the public "
        "export leaves out; nothing to test without it",
        allow_module_level=True,
    )

MODULE_NAME = "fetch_openapi_specs_under_test"
CREDENTIAL_VAR = "REVENIUM_DEV_API_KEY"
FAKE_KEY = "test-key-not-a-secret"
MINIMAL_DOCUMENT = json.dumps({"openapi": "3.1.0", "info": {"title": "t"}, "paths": {}}).encode()


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location(MODULE_NAME, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # @dataclass looks its defining module up in sys.modules while the class
    # body is processed, so the module must be registered before execution.
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


fetch_mod = _load_module()
HYPERCURRENT = fetch_mod.SPEC_SOURCES["hypercurrent"]
ISOTOPE = fetch_mod.SPEC_SOURCES["isotope"]


Answer = Tuple[int, Dict[str, str], bytes]


class _StubHTTPS(urllib.request.HTTPSHandler):
    """Replaces the HTTPS transport; every other opener handler stays real."""

    def __init__(self, answer: Callable[[urllib.request.Request], Answer]) -> None:
        super().__init__()
        self.answer = answer
        self.requests: List[urllib.request.Request] = []

    def https_open(self, req: urllib.request.Request) -> urllib.response.addinfourl:
        self.requests.append(req)
        status, headers, body = self.answer(req)
        message = http.client.HTTPMessage()
        for name, value in headers.items():
            message[name] = value
        response = urllib.response.addinfourl(io.BytesIO(body), message, req.full_url, status)
        response.msg = "stub"
        return response


def _install(monkeypatch, answer: Callable[[urllib.request.Request], Answer]) -> List[urllib.request.Request]:
    transport = _StubHTTPS(answer)
    monkeypatch.setattr(fetch_mod, "SPEC_OPENER", fetch_mod.build_spec_opener(transport))
    return transport.requests


def _status(code: int, headers: Optional[Dict[str, str]] = None) -> Callable[[urllib.request.Request], Answer]:
    return lambda req: (code, headers or {}, b"")


@pytest.fixture()
def sent_requests(monkeypatch) -> List[urllib.request.Request]:
    """Answer every request with a valid document and record what was sent."""
    return _install(monkeypatch, lambda req: (200, {}, MINIMAL_DOCUMENT))


def _answer_with_status(monkeypatch, status: int) -> None:
    _install(monkeypatch, _status(status))


class TestCredentialSelection:
    def test_hypercurrent_sends_the_dev_key_as_x_api_key(self, monkeypatch, sent_requests):
        monkeypatch.setenv(CREDENTIAL_VAR, FAKE_KEY)

        fetch_mod.fetch_spec(HYPERCURRENT)

        (request,) = sent_requests
        assert request.get_header("X-api-key") == FAKE_KEY
        assert request.get_header("Accept") == "application/json"
        assert request.get_header("Authorization") is None

    def test_surrounding_whitespace_is_not_sent(self, monkeypatch, sent_requests):
        monkeypatch.setenv(CREDENTIAL_VAR, f"  {FAKE_KEY}\n")

        fetch_mod.fetch_spec(HYPERCURRENT)

        assert sent_requests[0].get_header("X-api-key") == FAKE_KEY

    def test_isotope_stays_anonymous_even_when_the_key_is_set(self, monkeypatch, sent_requests):
        monkeypatch.setenv(CREDENTIAL_VAR, FAKE_KEY)

        fetch_mod.fetch_spec(ISOTOPE)

        (request,) = sent_requests
        assert request.get_header("X-api-key") is None
        assert request.get_header("Authorization") is None

    def test_isotope_needs_no_variable(self, monkeypatch, sent_requests):
        monkeypatch.delenv(CREDENTIAL_VAR, raising=False)

        assert fetch_mod.fetch_spec(ISOTOPE)["openapi"] == "3.1.0"


class TestMissingCredential:
    @pytest.mark.parametrize("value", [None, "", "   "], ids=["unset", "empty", "blank"])
    def test_fails_before_any_request_and_names_the_variable(self, monkeypatch, sent_requests, value):
        if value is None:
            monkeypatch.delenv(CREDENTIAL_VAR, raising=False)
        else:
            monkeypatch.setenv(CREDENTIAL_VAR, value)

        with pytest.raises(fetch_mod.SpecFetchError, match=CREDENTIAL_VAR):
            fetch_mod.fetch_spec(HYPERCURRENT)
        assert sent_requests == []

    def test_check_run_exits_2_with_the_variable_on_stderr(self, monkeypatch, sent_requests, capsys):
        monkeypatch.delenv(CREDENTIAL_VAR, raising=False)

        code = fetch_mod.run([HYPERCURRENT], check=True, out=io.StringIO())

        assert code == 2
        assert f"environment variable {CREDENTIAL_VAR} is not set" in capsys.readouterr().err


class TestRefusedCredential:
    @pytest.mark.parametrize("status", [401, 403])
    def test_message_names_the_status_and_the_variable(self, monkeypatch, status):
        monkeypatch.setenv(CREDENTIAL_VAR, FAKE_KEY)
        _answer_with_status(monkeypatch, status)

        with pytest.raises(fetch_mod.SpecFetchError) as raised:
            fetch_mod.fetch_spec(HYPERCURRENT)

        message = str(raised.value)
        assert f"HTTP {status}" in message
        assert CREDENTIAL_VAR in message
        assert FAKE_KEY not in message

    def test_check_run_exits_2_on_403(self, monkeypatch, capsys):
        monkeypatch.setenv(CREDENTIAL_VAR, FAKE_KEY)
        _answer_with_status(monkeypatch, 403)

        code = fetch_mod.run([HYPERCURRENT], check=True, out=io.StringIO())

        assert code == 2
        err = capsys.readouterr().err
        assert "HTTP 403" in err and CREDENTIAL_VAR in err

    def test_anonymous_source_refused_says_it_now_needs_auth(self, monkeypatch):
        _answer_with_status(monkeypatch, 403)

        with pytest.raises(fetch_mod.SpecFetchError, match="now requires auth"):
            fetch_mod.fetch_spec(ISOTOPE)

    def test_other_http_errors_are_not_reported_as_auth_failures(self, monkeypatch):
        monkeypatch.setenv(CREDENTIAL_VAR, FAKE_KEY)
        _answer_with_status(monkeypatch, 503)

        with pytest.raises(fetch_mod.SpecFetchError) as raised:
            fetch_mod.fetch_spec(HYPERCURRENT)

        message = str(raised.value)
        assert "HTTP 503" in message
        assert CREDENTIAL_VAR not in message


class TestRedirectsAreRefused:
    ELSEWHERE = "https://elsewhere.example/api-docs"

    def _redirect_once(self, monkeypatch, status: int) -> List[urllib.request.Request]:
        def answer(req: urllib.request.Request) -> Answer:
            if req.full_url == HYPERCURRENT.url:
                return status, {"Location": self.ELSEWHERE}, b""
            return 200, {}, MINIMAL_DOCUMENT

        return _install(monkeypatch, answer)

    @pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
    def test_redirect_raises_and_the_key_is_never_resent(self, monkeypatch, status):
        monkeypatch.setenv(CREDENTIAL_VAR, FAKE_KEY)
        sent = self._redirect_once(monkeypatch, status)

        with pytest.raises(fetch_mod.SpecFetchError) as raised:
            fetch_mod.fetch_spec(HYPERCURRENT)

        assert [req.full_url for req in sent] == [HYPERCURRENT.url]
        message = str(raised.value)
        assert f"HTTP {status}" in message
        assert self.ELSEWHERE in message
        assert FAKE_KEY not in message

    def test_check_run_exits_2_on_redirect(self, monkeypatch, capsys):
        monkeypatch.setenv(CREDENTIAL_VAR, FAKE_KEY)
        self._redirect_once(monkeypatch, 302)

        code = fetch_mod.run([HYPERCURRENT], check=True, out=io.StringIO())

        assert code == 2
        assert "redirected (HTTP 302)" in capsys.readouterr().err

    def test_the_production_opener_refuses_redirects(self):
        assert any(isinstance(handler, fetch_mod.RefuseRedirects) for handler in fetch_mod.SPEC_OPENER.handlers)
