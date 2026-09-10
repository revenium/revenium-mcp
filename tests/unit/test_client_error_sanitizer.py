"""Tests for HTTP error sanitizers in client.py (BACK-1313).

The dev backend returns plain-text error bodies with a Python dict-repr suffix
(`<msg> - {'error': '<msg>'}`) and sometimes an internal `Error ID:` token.
These sanitizers strip both before the message reaches the caller.
"""
from __future__ import annotations

import pytest

from src.revenium_mcp_server.client import (
    ReveniumClient,
    _sanitize_error_text,
    _strip_dict_repr_suffix,
    _strip_internal_class_names,
    _strip_internal_error_id,
)
from tests.unit._helpers_no_framework_leak import assert_no_framework_leak


class TestStripDictReprSuffix:
    def test_simple_single_quoted(self):
        assert (
            _strip_dict_repr_suffix("msg - {'error': 'msg'}")
            == "msg"
        )

    def test_double_quoted(self):
        assert (
            _strip_dict_repr_suffix('msg - {"error": "msg"}')
            == "msg"
        )

    def test_no_match_passes_through(self):
        assert _strip_dict_repr_suffix("clean message") == "clean message"

    def test_does_not_strip_set_repr(self):
        assert (
            _strip_dict_repr_suffix("items in {1, 2, 3}")
            == "items in {1, 2, 3}"
        )

    def test_does_not_strip_legit_braces_no_error_key(self):
        assert (
            _strip_dict_repr_suffix("valid until {now}")
            == "valid until {now}"
        )

    def test_handles_real_audit_products_shape(self):
        """C.1 audit reproduction — products get-after-delete leak."""
        leak = (
            "Could not find Product with id: 3ByY1L2 "
            "- {'error': 'Could not find Product with id: 3ByY1L2'}"
        )
        out = _strip_dict_repr_suffix(leak)
        assert out == "Could not find Product with id: 3ByY1L2"

    def test_handles_real_audit_subscriptions_403(self):
        """C.2 audit reproduction — subscriptions cross-resource 403 leak."""
        leak = (
            "Tool execution failed: HTTP 403: Access Denied "
            "- {'error': 'Access Denied'}"
        )
        out = _strip_dict_repr_suffix(leak)
        assert out == "Tool execution failed: HTTP 403: Access Denied"

    def test_idempotent(self):
        """Stripping twice should produce the same result as stripping once."""
        leak = "msg - {'error': 'msg'}"
        once = _strip_dict_repr_suffix(leak)
        twice = _strip_dict_repr_suffix(once)
        assert once == twice

    def test_does_not_match_across_newlines(self):
        """re.DOTALL was dropped — a multi-line body whose suffix-style block
        spans newlines must NOT be over-stripped."""
        text = "Real message line 1\nReal message line 2 - {'error': 'msg with\nnewline'}"
        out = _strip_dict_repr_suffix(text)
        # The dict-repr does not match (its inner string contains \n), so the
        # entire body passes through unchanged.
        assert out == text


class TestStripInternalErrorId:
    def test_removes_pattern(self):
        out = _strip_internal_error_id("Error ID: get_anomaly_0974\nReal msg")
        assert out.strip() == "Real msg"

    def test_no_match_passes_through(self):
        assert (
            _strip_internal_error_id("clean message")
            == "clean message"
        )

    def test_strips_inline_occurrence(self):
        """Error ID may appear without a trailing newline (single-line bodies)."""
        out = _strip_internal_error_id("prefix Error ID: get_anomaly_0974 suffix")
        # Both prefix and suffix preserved; only the Error ID token stripped.
        assert "get_anomaly_0974" not in out
        assert "prefix" in out
        assert "suffix" in out

    def test_does_not_strip_unrelated_id_format(self):
        """`request_id: abc-123` is not the internal pattern (no `Error ID:` prefix)."""
        out = _strip_internal_error_id("request_id: abc-123 — ok")
        assert "abc-123" in out

    def test_idempotent(self):
        text = "Error ID: get_anomaly_0974\nReal msg"
        once = _strip_internal_error_id(text)
        twice = _strip_internal_error_id(once)
        assert once == twice

    def test_body_that_is_only_error_id_falls_back_to_original(self):
        """If stripping the Error ID would leave an empty string, return the
        original (stripped) text so callers don't see an opaque empty error."""
        original = "Error ID: get_anomaly_0974"
        out = _strip_internal_error_id(original)
        assert out != ""
        # Original surfaces (stripped of leading/trailing whitespace) so the
        # caller has SOMETHING actionable.
        assert "Error ID" in out or "get_anomaly_0974" in out


class TestCombinedSanitizationAuditShapes:
    """Parametrized: feed each audit-observed leak through both sanitizers in the
    correct order (Error ID first, dict-repr second) and assert the output
    passes the framework-leak helper."""

    @pytest.mark.parametrize(
        "shape",
        [
            # C.1 — products get-after-delete
            "Could not find Product with id: 3ByY1L2 - {'error': 'Could not find Product with id: 3ByY1L2'}",
            # C.2 — subscriptions cross-resource 403
            "Tool execution failed: HTTP 403: Access Denied - {'error': 'Access Denied'}",
            # C.3 — alerts get-after-delete with internal Error ID
            "Error ID: get_anomaly_0974\nHTTP 403: Access Denied - {'error': 'Access Denied'}",
            # C.2 — sources/metering_elements 404 with locator failure
            "Asset locator failure - {'error': 'Asset locator failure'}",
        ],
    )
    def test_sanitization_clears_leak_signatures(self, shape):
        out = _sanitize_error_text(shape)
        # The leak signatures: dict-repr suffix and internal Error ID must be gone.
        assert " - {'error':" not in out
        assert ' - {"error":' not in out
        assert "Error ID:" not in out
        # And the result must pass the project-wide leak helper.
        assert_no_framework_leak(out)


# BACK-2941: the jobs list endpoint answers an unbindable enum with Spring's own
# type-conversion prose, naming internal classes in full.
_SPRING_TYPE_CONVERSION_400 = (
    "Validation failed for one or more fields - Failed to convert value of type "
    "'java.lang.String' to required type "
    "'io.hypercurrent.profitstream.model.entity.ExecutionStatus'; Failed to convert "
    "from type [java.lang.String] to type "
    "[io.hypercurrent.profitstream.model.entity.ExecutionStatus] for value [BOGUS_STATUS]"
)


class TestStripInternalClassNames:
    """BACK-2941: fully qualified internal class names never reach a caller."""

    def test_strips_package_path_keeps_simple_name(self):
        out = _strip_internal_class_names(_SPRING_TYPE_CONVERSION_400)
        assert "io.hypercurrent" not in out
        assert "java.lang" not in out
        assert "ExecutionStatus" in out
        assert "BOGUS_STATUS" in out

    def test_applied_by_the_shared_sanitizer(self):
        out = _sanitize_error_text(_SPRING_TYPE_CONVERSION_400)
        assert "io.hypercurrent" not in out

    def test_leaves_ordinary_prose_alone(self):
        text = "Contact support at https://app.revenium.ai/help for details."
        assert _strip_internal_class_names(text) == text

    def test_leaves_sentence_boundaries_alone(self):
        text = "The source was created. Verify it with list()."
        assert _strip_internal_class_names(text) == text

    def test_idempotent(self):
        once = _strip_internal_class_names(_SPRING_TYPE_CONVERSION_400)
        assert _strip_internal_class_names(once) == once


class TestEnhanceBadRequestError:
    """BACK-2941: a 400 that does reach the caller is guidance, not a raw body."""

    @pytest.fixture
    def client(self):
        return ReveniumClient.__new__(ReveniumClient)

    def test_type_conversion_400_becomes_guidance(self, client):
        sanitized = _sanitize_error_text(_SPRING_TYPE_CONVERSION_400)
        out = client._enhance_bad_request_error(sanitized)

        assert out is not None
        assert "BOGUS_STATUS" in out
        assert "get_capabilities()" in out
        assert "Failed to convert" not in out
        assert "io.hypercurrent" not in out
        assert_no_framework_leak(out)

    def test_other_400_bodies_keep_their_message(self, client):
        assert client._enhance_bad_request_error("name must not be blank") is None
