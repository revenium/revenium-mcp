import asyncio

import pytest
from loguru import logger

from revenium_mcp_server.auth.tenant_context import TenantContext
from revenium_mcp_server.log_context import (
    _redact_message,
    bind_tenant_context,
    clear_tenant_context,
    redact_headers,
    redact_key,
    sanitize_error_message,
    tenant_log_patcher,
)

_VALID_API_KEY = "abcdef1234567890"


class TestBindAndClear:

    def test_bind_with_full_context(self):
        ctx = TenantContext(team_id="team-1", api_key=_VALID_API_KEY, tenant_id="t-9")
        tokens = bind_tenant_context(ctx)

        record = {"extra": {}}
        tenant_log_patcher(record)

        assert record["extra"]["team_id"] == "team-1"
        assert record["extra"]["tenant_id"] == "t-9"
        assert "request_id" in record["extra"]
        assert len(record["extra"]["request_id"]) == 12

        clear_tenant_context(tokens)

    def test_bind_without_tenant_id(self):
        ctx = TenantContext(team_id="team-1", api_key=_VALID_API_KEY)
        tokens = bind_tenant_context(ctx)

        record = {"extra": {}}
        tenant_log_patcher(record)

        assert record["extra"]["team_id"] == "team-1"
        assert "tenant_id" not in record["extra"]
        assert "request_id" in record["extra"]

        clear_tenant_context(tokens)

    def test_bind_with_none_context(self):
        tokens = bind_tenant_context(None)

        record = {"extra": {}}
        tenant_log_patcher(record)

        assert "team_id" not in record["extra"]
        assert "tenant_id" not in record["extra"]
        assert "request_id" in record["extra"]

        clear_tenant_context(tokens)

    def test_clear_removes_all_fields(self):
        ctx = TenantContext(team_id="team-1", api_key=_VALID_API_KEY, tenant_id="t-9")
        tokens = bind_tenant_context(ctx)
        clear_tenant_context(tokens)

        record = {"extra": {}}
        tenant_log_patcher(record)

        assert "team_id" not in record["extra"]
        assert "tenant_id" not in record["extra"]
        assert "request_id" not in record["extra"]

    def test_request_id_unique_per_bind(self):
        tokens_1 = bind_tenant_context(None)
        record_1 = {"extra": {}}
        tenant_log_patcher(record_1)
        clear_tenant_context(tokens_1)

        tokens_2 = bind_tenant_context(None)
        record_2 = {"extra": {}}
        tenant_log_patcher(record_2)
        clear_tenant_context(tokens_2)

        assert record_1["extra"]["request_id"] != record_2["extra"]["request_id"]


class TestPatcherNoContext:

    def test_patcher_adds_nothing_without_bind(self):
        record = {"extra": {}}
        tenant_log_patcher(record)

        assert "team_id" not in record["extra"]
        assert "tenant_id" not in record["extra"]
        assert "request_id" not in record["extra"]

    def test_patcher_preserves_existing_extras(self):
        ctx = TenantContext(team_id="team-1", api_key=_VALID_API_KEY)
        tokens = bind_tenant_context(ctx)

        record = {"extra": {"operation_id": "op_123"}}
        tenant_log_patcher(record)

        assert record["extra"]["operation_id"] == "op_123"
        assert record["extra"]["team_id"] == "team-1"

        clear_tenant_context(tokens)


class TestAsyncIsolation:

    @pytest.mark.asyncio
    async def test_concurrent_tenants_isolated(self):
        captured = {}

        async def tenant_task(name: str, team_id: str):
            ctx = TenantContext(team_id=team_id, api_key=_VALID_API_KEY)
            tokens = bind_tenant_context(ctx)
            await asyncio.sleep(0.01)

            record = {"extra": {}}
            tenant_log_patcher(record)
            captured[name] = record["extra"].get("team_id")

            clear_tenant_context(tokens)

        await asyncio.gather(
            tenant_task("a", "team-a"),
            tenant_task("b", "team-b"),
        )

        assert captured["a"] == "team-a"
        assert captured["b"] == "team-b"

    @pytest.mark.asyncio
    async def test_child_task_inherits_context(self):
        ctx = TenantContext(team_id="parent-team", api_key=_VALID_API_KEY)
        tokens = bind_tenant_context(ctx)

        child_team_id = None

        async def child():
            nonlocal child_team_id
            record = {"extra": {}}
            tenant_log_patcher(record)
            child_team_id = record["extra"].get("team_id")

        await child()

        assert child_team_id == "parent-team"
        clear_tenant_context(tokens)


class TestLoguruIntegration:

    def test_logger_output_includes_tenant_fields(self):
        logger.remove()
        logger.configure(patcher=tenant_log_patcher)

        ctx = TenantContext(team_id="team-log", api_key=_VALID_API_KEY, tenant_id="t-log")
        tokens = bind_tenant_context(ctx)

        record_extras = {}

        def capture_sink(message):
            record_extras.update(message.record["extra"])

        handler_id = logger.add(capture_sink, format="{message}", level="DEBUG")
        try:
            logger.info("test message")
            logger.remove(handler_id)

            assert record_extras.get("team_id") == "team-log"
            assert record_extras.get("tenant_id") == "t-log"
            assert "request_id" in record_extras
        finally:
            clear_tenant_context(tokens)
            logger.remove()


class TestRedactKey:

    def test_long_key(self):
        assert redact_key("sk_live_abc123xyz789") == "***...z789"

    def test_short_key(self):
        assert redact_key("abcd") == "***"

    def test_exactly_five_chars(self):
        assert redact_key("abcde") == "***...bcde"

    def test_none(self):
        assert redact_key(None) == "<empty>"

    def test_empty_string(self):
        assert redact_key("") == "<empty>"


class TestRedactHeaders:

    def test_redacts_api_key_header(self):
        headers = {"x-api-key": "sk_live_secret123", "Content-Type": "application/json"}
        result = redact_headers(headers)
        assert result["x-api-key"] == "***...t123"
        assert result["Content-Type"] == "application/json"

    def test_redacts_authorization_header(self):
        headers = {"Authorization": "Bearer sk_live_secret123"}
        result = redact_headers(headers)
        assert result["Authorization"] == "***...t123"

    def test_case_insensitive(self):
        headers = {"X-API-KEY": "mysecretkey12345"}
        result = redact_headers(headers)
        assert result["X-API-KEY"] == "***...2345"

    def test_preserves_non_sensitive(self):
        headers = {"Accept": "application/json", "User-Agent": "test"}
        result = redact_headers(headers)
        assert result == headers


class TestAutoRedactionPatcher:

    def test_patcher_redacts_api_key_in_extras(self):
        record = {"extra": {"api_key": "sk_live_secret_full_key"}}
        tenant_log_patcher(record)
        assert record["extra"]["api_key"] == "***..._key"

    def test_patcher_redacts_x_api_key_in_extras(self):
        record = {"extra": {"x-api-key": "full_secret_value"}}
        tenant_log_patcher(record)
        assert record["extra"]["x-api-key"] == "***...alue"

    def test_patcher_ignores_non_sensitive_extras(self):
        record = {"extra": {"operation_id": "op_123", "team_id_label": "team-1"}}
        tenant_log_patcher(record)
        assert record["extra"]["operation_id"] == "op_123"

    def test_patcher_skips_non_string_values(self):
        record = {"extra": {"api_key_count": 42}}
        tenant_log_patcher(record)
        assert record["extra"]["api_key_count"] == 42

    def test_patcher_exact_match_does_not_redact_substrings(self):
        record = {"extra": {}, "message": "", "api_key_source": "env", "api_key_algorithm": "RS256"}
        tenant_log_patcher(record)
        assert record.get("api_key_source") == "env"
        assert record.get("api_key_algorithm") == "RS256"

    def test_patcher_redacts_api_key_in_message(self):
        record = {"extra": {}, "message": "Using api_key=sk_live_secret123 for request"}
        tenant_log_patcher(record)
        assert "sk_live_secret123" not in record["message"]
        assert "***...t123" in record["message"]

    def test_patcher_redacts_authorization_in_message(self):
        record = {"extra": {}, "message": "Header Authorization: Bearer sk_live_real_token_value"}
        tenant_log_patcher(record)
        assert "sk_live_real_token_value" not in record["message"]
        assert "***...alue" in record["message"]

    def test_patcher_leaves_safe_message_alone(self):
        record = {"extra": {}, "message": "Processing request for team-1"}
        tenant_log_patcher(record)
        assert record["message"] == "Processing request for team-1"


class TestRedactMessage:

    def test_fstring_api_key(self):
        msg = f"Configured api_key={'sk_live_abc123xyz789'}"
        assert "sk_live_abc123xyz789" not in _redact_message(msg)
        assert "***...z789" in _redact_message(msg)

    def test_x_api_key_header_format(self):
        msg = "x-api-key: my_super_secret_key_value"
        assert "my_super_secret_key_value" not in _redact_message(msg)

    def test_authorization_bearer_space_separated(self):
        msg = "Authorization: Bearer eyJhbGci.payload.abc123"
        result = _redact_message(msg)
        assert "eyJhbGci.payload.abc123" not in result
        assert "***...c123" in result

    def test_authorization_bearer_underscore_joined(self):
        msg = 'Authorization: "Bearer_full_token"'
        assert "Bearer_full_token" not in _redact_message(msg)

    def test_no_match_leaves_unchanged(self):
        msg = "Normal log message with no keys"
        assert _redact_message(msg) == msg

    def test_case_insensitive(self):
        msg = "API_KEY=sk_live_secret_value123"
        assert "sk_live_secret_value123" not in _redact_message(msg)


class TestSanitizeErrorMessage:

    def test_removes_stack_trace(self):
        msg = (
            "Something failed\n"
            "Traceback (most recent call last):\n"
            '  File "/app/src/server.py", line 42, in handle\n'
            "    result = process()\n"
            "ValueError: bad value"
        )
        result = sanitize_error_message(msg)
        assert "Traceback" not in result
        assert "/app/src/server.py" not in result
        assert "Something failed" in result

    def test_removes_file_paths(self):
        msg = 'Error in /Users/gabi/Documents/project/src/module.py at line 55'
        result = sanitize_error_message(msg)
        assert "/Users/gabi" not in result
        assert "[path removed]" in result

    def test_removes_internal_urls(self):
        msg = "Failed to connect to http://internal-service:8080/api/v1/data"
        result = sanitize_error_message(msg)
        assert "http://internal-service:8080" not in result
        assert "[internal url removed]" in result

    def test_preserves_public_urls(self):
        msg = "See docs at https://revenium.io/docs and https://docs.revenium.io/api"
        result = sanitize_error_message(msg)
        assert "https://revenium.io/docs" in result
        assert "https://docs.revenium.io/api" in result

    def test_preserves_github_urls(self):
        msg = "Report at https://github.com/revenium/mcp/issues"
        result = sanitize_error_message(msg)
        assert "https://github.com/revenium/mcp/issues" in result

    def test_redacts_api_keys(self):
        msg = "Request failed with api_key=sk_live_secret_full_key123"
        result = sanitize_error_message(msg)
        assert "sk_live_secret_full_key123" not in result

    def test_safe_message_unchanged(self):
        msg = "Invalid organization ID format: expected hashed ID"
        assert sanitize_error_message(msg) == msg

    def test_combined_sensitive_content(self):
        msg = (
            "Error at /app/src/client.py: "
            "api_key=sk_live_full_secret "
            "url=http://10.0.0.1:3000/internal"
        )
        result = sanitize_error_message(msg)
        assert "sk_live_full_secret" not in result
        assert "/app/src/client.py" not in result
        assert "http://10.0.0.1:3000" not in result
